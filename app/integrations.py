"""Connections to Google Sheets, Sarvam, Veblika and email.

Each external call retries on network errors and 5xx responses, so a short
outage does not lose a call result or a WhatsApp message.
"""
import logging
import smtplib
import time
from dataclasses import dataclass
from email.message import EmailMessage
from urllib.parse import urlencode

import httpx

from .config import Settings
from .leads import COL

log = logging.getLogger("didm")

RETRY_STATUSES = {429, 500, 502, 503, 504}


def request_with_retry(client: httpx.Client, method: str, url: str, tries: int = 3, **kwargs) -> httpx.Response:
    last_exc = None
    for i in range(tries):
        try:
            resp = client.request(method, url, **kwargs)
            if resp.status_code not in RETRY_STATUSES or i == tries - 1:
                return resp
        except httpx.TransportError as exc:
            last_exc = exc
            if i == tries - 1:
                raise
        time.sleep(2 ** i)
    raise last_exc  # pragma: no cover


def col_letter(index: int) -> str:
    s, n = "", index + 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


class GoogleSheet:
    """Reads and writes the Leads sheet through the Sheets API with a service account."""

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30)
        self._creds = None

    def _token(self) -> str:
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        if self._creds is None:
            self._creds = service_account.Credentials.from_service_account_info(
                self.s.google_credentials_info(), scopes=self.SCOPES)
        if not self._creds.valid:
            self._creds.refresh(Request())
        return self._creds.token

    def _url(self, path: str) -> str:
        return f"https://sheets.googleapis.com/v4/spreadsheets/{self.s.spreadsheet_id}{path}"

    def read_rows(self) -> list[tuple[int, list]]:
        """Returns (sheet row number, values) for every data row."""
        rng = f"{self.s.leads_sheet}!A2:{col_letter(max(COL.values()))}"
        resp = request_with_retry(self.client, "GET", self._url(f"/values/{rng}"),
                                  headers={"Authorization": f"Bearer {self._token()}"})
        resp.raise_for_status()
        values = resp.json().get("values", [])
        return [(i + 2, row) for i, row in enumerate(values)]

    def update_row(self, row: int, updates: dict[str, object]):
        """updates maps a column key from leads.COL to the value to write."""
        data = [{"range": f"{self.s.leads_sheet}!{col_letter(COL[k])}{row}", "values": [[v]]}
                for k, v in updates.items()]
        resp = request_with_retry(
            self.client, "POST", self._url("/values:batchUpdate"),
            headers={"Authorization": f"Bearer {self._token()}"},
            json={"valueInputOption": "RAW", "data": data})
        resp.raise_for_status()


@dataclass(frozen=True)
class CallTarget:
    """Which hosted Sarvam agent places a call, and from which number.

    The lead dialler uses the one agent in its settings (CallTarget.from_settings). The training platform
    will pass a target per session so each session stays pinned to the agent version it started with.
    """
    app_id: str
    app_version: int
    connection_id: str
    agent_phone: str

    @classmethod
    def from_settings(cls, s: Settings) -> "CallTarget":
        return cls(s.sarvam_app_id, s.sarvam_app_version, s.sarvam_connection_id, s.sarvam_agent_phone)


class Sarvam:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30)

    def start_call(self, phone_e164: str, variables: dict, metadata: dict,
                   target: CallTarget | None = None, webhook_url: str | None = None) -> dict:
        """Starts one outbound call. Returns {"ok", "status_code", "attempt_id", "error"}.

        Without target and webhook_url it sends exactly what it always did: the settings' agent, and
        results to /webhooks/sarvam/{WEBHOOK_SECRET}.
        """
        s = self.s
        t = target or CallTarget.from_settings(s)
        url = f"{s.sarvam_base_url}/v1/orgs/{s.sarvam_org_id}/workspaces/{s.sarvam_workspace_id}/outbounds"
        body = {
            "app_config": {
                "app_id": t.app_id,
                "app_version": t.app_version,
                "connection_config": {"connection_id": t.connection_id,
                                      "agent_phone_number": t.agent_phone},
                "agent_variables": variables,
            },
            "user_config": {"user_phone_number": phone_e164},
            "webhook_config": {"url": webhook_url or f"{s.public_base_url}/webhooks/sarvam/{s.webhook_secret}",
                               "metadata": metadata},
        }
        api_key = (s.sarvam_api_key or "").strip()
        if len(api_key) >= 2 and ((api_key.startswith('"') and api_key.endswith('"')) or
                                  (api_key.startswith("'") and api_key.endswith("'"))):
            api_key = api_key[1:-1].strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        try:
            resp = request_with_retry(self.client, "POST", url, json=body,
                                      headers={"X-API-Key": api_key})
        except httpx.TransportError as exc:
            return {"ok": False, "status_code": None, "attempt_id": None, "error": f"network: {exc}"}
        data = _json(resp)
        ok = 200 <= resp.status_code < 300 and bool(data.get("attempt_id"))
        err = None if ok else str(data.get("error") or data or resp.text)[:500]
        return {"ok": ok, "status_code": resp.status_code, "attempt_id": data.get("attempt_id"), "error": err}


class SarvamWebAuth:
    """Gets a signed, single-use WebSocket URL for one browser voice session, keeping the API key on
    the server.

    NOT VERIFIED: this endpoint is not on any Sarvam docs page. It is copied from the published
    sarvam-conv-ai-sdk 0.0.42 package source (see docs/phase3_sarvam_verification.md). It is only
    built when TRAINING_BROWSER_ENABLED is on, which must wait for a live test with approval.
    """

    URL_TTL_SECONDS = 60  # the docs give no lifetime; treat the URL as short-lived

    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=15)

    def signed_url(self, app_id: str, app_version: int) -> dict:
        s = self.s
        url = (f"https://apps.sarvam.ai/api/app-runtime/orgs/{s.sarvam_org_id}/workspaces/"
               f"{s.sarvam_workspace_id}/apps/{app_id}/url")
        api_key = (s.sarvam_api_key or "").strip()
        if len(api_key) >= 2 and ((api_key.startswith('"') and api_key.endswith('"')) or
                                  (api_key.startswith("'") and api_key.endswith("'"))):
            api_key = api_key[1:-1].strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        resp = self.client.get(url, params={"interaction_type": "call", "version": app_version},
                               headers={"X-API-Key": api_key})
        data = _json(resp)
        if resp.status_code != 200 or not data.get("url"):
            raise RuntimeError(f"Sarvam signed URL request answered {resp.status_code}")
        return {"url": data["url"], "reference_id": data.get("reference_id"), "ttl_seconds": self.URL_TTL_SECONDS}


class Veblika:
    def __init__(self, settings: Settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=30)

    def send_template(self, phone_digits: str, template: str | None = None, language: str | None = None,
                      header_image_url: str | None = None, extra_params: dict | None = None) -> dict:
        s = self.s
        image = s.veblika_header_image_url if header_image_url is None else header_image_url
        params = {"to": phone_digits, "phoneNoId": s.veblika_phone_no_id, "type": "template",
                  "name": template or s.veblika_template, "language": language or s.veblika_language}
        if image:
            params.update({"headerType": "image", "headerUrl": image})
        if extra_params:
            params.update(extra_params)
        if s.veblika_make_hook_url:
            return self._send_via_make(params)
        headers = {}
        if s.veblika_auth_in == "query":
            params[s.veblika_auth_name] = s.veblika_api_key
        else:
            headers[s.veblika_auth_name] = s.veblika_api_key
        try:
            resp = request_with_retry(self.client, "GET", s.veblika_url, params=params, headers=headers)
        except httpx.TransportError as exc:
            return {"ok": False, "status_code": None, "error": f"network: {exc}"}
        data = _json(resp)
        ok = resp.status_code == 200
        return {"ok": ok, "status_code": resp.status_code,
                "error": None if ok else str(data.get("message") or resp.text)[:300]}


    def _send_via_make(self, params: dict) -> dict:
        try:
            resp = request_with_retry(self.client, "POST", self.s.veblika_make_hook_url,
                                      json={"query": urlencode(params), "to": params.get("to", "")})
        except httpx.TransportError as exc:
            return {"ok": False, "status_code": None, "error": f"network: {exc}"}
        data = _json(resp)
        ok = resp.status_code == 200 and data.get("status") != "error"
        return {"ok": ok, "status_code": resp.status_code,
                "error": None if ok else str(data.get("message") or resp.text)[:300]}


class Mailer:
    def __init__(self, settings: Settings):
        self.s = settings

    @property
    def enabled(self) -> bool:
        return bool(self.s.smtp_host and self.s.alert_email_to)

    def send(self, subject: str, body: str) -> bool:
        """Alerts and reports, to ALERT_EMAIL_TO."""
        return self.send_to(self.s.alert_email_to, subject, body)

    def send_to(self, to: str, subject: str, body: str) -> bool:
        """One email to one address, e.g. an invitation or a password reset."""
        if not self.enabled:
            log.info("email not configured, skipped: %s", subject)
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.s.smtp_user or self.s.alert_email_to
        msg["To"] = to
        msg.set_content(body)
        try:
            with smtplib.SMTP(self.s.smtp_host, self.s.smtp_port, timeout=30) as smtp:
                smtp.starttls()
                if self.s.smtp_user:
                    smtp.login(self.s.smtp_user, self.s.smtp_password)
                smtp.send_message(msg)
            return True
        except Exception as exc:  # email must never crash the app
            log.error("email failed: %s", exc)
            return False


def _json(resp: httpx.Response) -> dict:
    try:
        data = resp.json()
        return data if isinstance(data, dict) else {"data": data}
    except ValueError:
        return {}

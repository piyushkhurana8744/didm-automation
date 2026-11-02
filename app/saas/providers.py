"""Sarvam adapters for the post-call jobs: call lookup, transcripts, recordings and the evaluator.

Every endpoint and field here is from Sarvam's docs; see docs/phase4_sarvam_capabilities.md for the page
and quote behind each one. Nothing here runs in tests (they use fakes), and none of it is switched on by
default: main.py only builds an adapter when its settings are present.
"""
import json
import logging
from datetime import timedelta
from urllib.parse import quote

import httpx

from .intelligence import EvaluatorError, JobGiveUp, JobRetry
from .recordings import RecordingSource

log = logging.getLogger("didm.providers")

ANALYTICS_BASE = "https://apps.sarvam.ai/api/analytics/v1"
CHAT_URL = "https://api.sarvam.ai/v1/chat/completions"


def _iso(dt) -> str:
    """Naive UTC datetime to ISO 8601 with an explicit offset, as the analytics API asks."""
    return dt.replace(microsecond=0).isoformat() + "+00:00"


def _retry_after(resp: httpx.Response) -> int | None:
    try:
        return int(resp.headers.get("Retry-After", ""))
    except ValueError:
        return None


class SarvamAnalytics:
    """List attempts and List interactions (VERIFIED). Header X-API-Key; responses cached for 60 seconds;
    429 carries Retry-After."""

    def __init__(self, settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=20)

    def _get(self, app_id: str, path: str, params: dict) -> httpx.Response:
        s = self.s
        url = f"{ANALYTICS_BASE}/{s.sarvam_org_id}/{s.sarvam_workspace_id}/{quote(app_id, safe='')}/{path}"
        api_key = (s.sarvam_api_key or "").strip()
        if len(api_key) >= 2 and ((api_key.startswith('"') and api_key.endswith('"')) or
                                  (api_key.startswith("'") and api_key.endswith("'"))):
            api_key = api_key[1:-1].strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        try:
            resp = self.client.get(url, params=params, headers={"X-API-Key": api_key})
        except httpx.TransportError as exc:
            raise JobRetry("provider_unreachable", type(exc).__name__)
        if resp.status_code == 429:
            raise JobRetry("provider_rate_limited", "Sarvam asked us to slow down.", _retry_after(resp))
        if resp.status_code >= 500:
            raise JobRetry("provider_error", f"Sarvam answered {resp.status_code}")
        if resp.status_code in (401, 403):
            raise JobRetry("provider_auth", f"Sarvam answered {resp.status_code}")
        return resp

    def _window(self, sess) -> dict:
        start = (sess.started_at or sess.created_at) - timedelta(minutes=5)
        end = start + timedelta(seconds=sess.max_duration_seconds) + timedelta(hours=2)
        return {"start_datetime": _iso(start), "end_datetime": _iso(end)}

    def find_attempt(self, sess) -> dict | None:
        """The provider's record of the session's outbound attempt, or None if it has none (yet)."""
        params = {**self._window(sess), "limit": 5,
                  "filter_conditions": json.dumps([{"field": "attempt_id", "operator": "equals",
                                                    "value": str(sess.provider_attempt_id)}])}
        resp = self._get(sess.provider_app_id, "attempts", params)
        if resp.status_code != 200:
            raise JobRetry("provider_rejected", f"Sarvam answered {resp.status_code}")
        items = [i for i in (resp.json().get("items") or []) if str(i.get("attempt_id")) == str(sess.provider_attempt_id)]
        if not items:
            return None
        it = items[0]
        return {"status": str(it.get("connectivity_status") or "unknown").lower(),
                "duration": it.get("duration_in_seconds"), "attempt_id": it.get("attempt_id"),
                "interaction_id": it.get("interaction_id"), "failure_reason": it.get("failure_reason"),
                "ended_by": it.get("ended_by")}

    def fetch(self, sess):
        """The English transcript of the session's interaction as [{role, en_text}], the same shape the
        webhook sends. Uses List interactions with include_transcript=true and reads translate_transcript
        (English, aligned 1:1 with original_transcript). Raises JobRetry while the data is not there yet."""
        if not sess.provider_session_id:
            return None
        params = {**self._window(sess), "limit": 5, "include_transcript": "true",
                  "filter_conditions": json.dumps([{"field": "interaction_id", "operator": "equals",
                                                    "value": str(sess.provider_session_id)}])}
        resp = self._get(sess.provider_app_id, "interactions", params)
        if resp.status_code != 200:
            raise JobRetry("provider_rejected", f"Sarvam answered {resp.status_code}")
        items = [i for i in (resp.json().get("items") or []) if str(i.get("interaction_id")) == str(sess.provider_session_id)]
        if not items or not items[0].get("translate_transcript"):
            raise JobRetry("transcript_not_ready", "The provider has no transcript for this call yet.")
        return [{"role": t.get("role"), "en_text": t.get("text")} for t in items[0]["translate_transcript"]
                if isinstance(t, dict)]


class SarvamRecordingSource(RecordingSource):
    """GET {analytics}/recordings/{interaction_id} returns a stereo WAV, 404 when there is none (VERIFIED).
    The download goes straight from Sarvam's API host with our key, so no unsigned provider media link
    is ever followed or shown."""

    allowed_hosts = ("apps.sarvam.ai",)

    def __init__(self, settings, client: httpx.Client | None = None):
        self.s = settings
        self.client = client or httpx.Client(timeout=60)

    def fetch_url(self, sess, job_input: dict) -> str | None:
        inter = job_input.get("interaction_id") or sess.provider_session_id
        if not inter:
            return None
        s = self.s
        return (f"{ANALYTICS_BASE}/{s.sarvam_org_id}/{s.sarvam_workspace_id}/{quote(sess.provider_app_id, safe='')}"
                f"/recordings/{quote(str(inter), safe='')}")

    def download(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        api_key = (self.s.sarvam_api_key or "").strip()
        if len(api_key) >= 2 and ((api_key.startswith('"') and api_key.endswith('"')) or
                                  (api_key.startswith("'") and api_key.endswith("'"))):
            api_key = api_key[1:-1].strip()
        if api_key.lower().startswith("bearer "):
            api_key = api_key[7:].strip()
        try:
            with self.client.stream("GET", url, headers={"X-API-Key": api_key}) as resp:
                if resp.status_code == 404:
                    return b"", ""
                if resp.status_code == 429:
                    raise JobRetry("provider_rate_limited", "", _retry_after(resp))
                if resp.status_code != 200:
                    raise JobRetry("provider_error", f"Sarvam answered {resp.status_code}")
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise JobGiveUp("too_large", "The recording is larger than allowed.")
                    chunks.append(chunk)
                return b"".join(chunks), resp.headers.get("content-type", "")
        except httpx.TransportError as exc:
            raise JobRetry("provider_unreachable", type(exc).__name__)


class SarvamChatEvaluator:
    """Sarvam chat completions with a strict JSON schema (VERIFIED: response_format json_schema, header
    api-subscription-key). The JSON comes back as a string in choices[0].message.content, and usage{} carries
    the token counts. Billed per token, so it is only built when EVALUATOR_PROVIDER=sarvam and its key is set;
    the engine meters every call and checks budgets first (intelligence.py)."""

    provider = "sarvam_chat"

    def __init__(self, api_key: str, model: str, client: httpx.Client | None = None, timeout: float = 60,
                 max_output_tokens: int = 4096):
        k = (api_key or "").strip()
        if len(k) >= 2 and ((k.startswith('"') and k.endswith('"')) or (k.startswith("'") and k.endswith("'"))):
            k = k[1:-1].strip()
        if k.lower().startswith("bearer "):
            k = k[7:].strip()
        self._api_key, self.model, self.max_output_tokens = k, model, max_output_tokens
        self.client = client or httpx.Client(timeout=timeout)

    def __repr__(self):
        return f"SarvamChatEvaluator(model={self.model!r})"

    @staticmethod
    def _usage(data) -> dict | None:
        u = data.get("usage") if isinstance(data, dict) else None
        if not isinstance(u, dict):
            return None
        return {k: u.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")}

    def evaluate_metered(self, system: str, user: str, schema: dict) -> tuple[dict, dict | None]:
        body = {"model": self.model, "temperature": 0, "max_tokens": self.max_output_tokens,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_schema",
                                    "json_schema": {"name": "training_evaluation", "schema": schema, "strict": True}}}
        headers = {
            "api-subscription-key": self._api_key,
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            resp = self.client.post(CHAT_URL, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise EvaluatorError("evaluator_timeout", type(exc).__name__)
        except httpx.TransportError as exc:
            raise EvaluatorError("evaluator_unreachable", type(exc).__name__)
        if resp.status_code == 429:
            raise EvaluatorError("evaluator_rate_limited", retry_after=_retry_after(resp))
        if resp.status_code >= 500:
            raise EvaluatorError("evaluator_error", f"answered {resp.status_code}")
        if resp.status_code in (401, 403):
            raise EvaluatorError("evaluator_auth", f"answered {resp.status_code}", retryable=False)
        if resp.status_code != 200:
            raise EvaluatorError("evaluator_rejected", f"answered {resp.status_code}", retryable=False)
        try:
            data = resp.json()
        except ValueError:
            raise EvaluatorError("invalid_output", "The evaluator did not return JSON.")
        usage = self._usage(data)
        try:
            choice = data["choices"][0]
            if choice.get("finish_reason") == "length":
                err = EvaluatorError("output_truncated", "The answer hit the output token limit.")
                err.usage = usage
                raise err
            return json.loads(choice["message"]["content"]), usage
        except (KeyError, IndexError, TypeError, ValueError):
            err = EvaluatorError("invalid_output", "The evaluator did not return JSON.")
            err.usage = usage
            raise err

    def evaluate(self, system: str, user: str, schema: dict) -> dict:
        return self.evaluate_metered(system, user, schema)[0]

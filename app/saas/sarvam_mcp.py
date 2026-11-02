"""Read-only Sarvam Voice Agents MCP OAuth and metadata lookup.

OAuth state and the 24-hour access token are organization scoped and encrypted inside Organization.settings.
The implementation uses standards-level HTTP so the main application does not need to keep an OAuth coroutine
alive between the browser redirect and callback.
"""
import base64
import hashlib
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken


KEY = "sarvam_mcp"


class SarvamMCPError(RuntimeError):
    pass


def _fernet(secret: str) -> Fernet:
    if len(secret) < 32:
        raise SarvamMCPError("Sarvam auto-fetch is not configured. Set SARVAM_MCP_ENCRYPTION_KEY.")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()))


def _load(org, secret: str) -> dict:
    value = (org.settings or {}).get(KEY)
    if not value:
        return {}
    try:
        return json.loads(_fernet(secret).decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError):
        raise SarvamMCPError("The stored Sarvam connection cannot be read. Reconnect Sarvam.")


def _save(org, secret: str, value: dict) -> None:
    settings = dict(org.settings or {})
    settings[KEY] = _fernet(secret).encrypt(json.dumps(value, separators=(",", ":")).encode()).decode()
    org.settings = settings


def connection_status(org, secret: str) -> dict:
    try:
        data = _load(org, secret)
    except SarvamMCPError as exc:
        return {"configured": len(secret) >= 32, "connected": False, "detail": str(exc)}
    expiry = int(data.get("expires_at") or 0)
    return {"configured": len(secret) >= 32, "connected": bool(data.get("access_token") and expiry > time.time() + 30),
            "expires_at": expiry or None}


def _json(resp: httpx.Response, label: str) -> dict:
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if not 200 <= resp.status_code < 300:
        detail = data.get("error_description") or data.get("detail") or data.get("error") or resp.text
        raise SarvamMCPError(f"Sarvam {label} failed ({resp.status_code}): {str(detail)[:300]}")
    return data


def _metadata(client: httpx.Client, mcp_url: str) -> tuple[dict, dict]:
    parsed = urlparse(mcp_url)
    resource_url = f"{parsed.scheme}://{parsed.netloc}/.well-known/oauth-protected-resource{parsed.path}"
    resource = _json(client.get(resource_url), "OAuth discovery")
    servers = resource.get("authorization_servers") or []
    if not servers:
        raise SarvamMCPError("Sarvam OAuth discovery did not return an authorization server.")
    issuer = str(servers[0]).rstrip("/")
    auth = _json(client.get(f"{issuer}/.well-known/oauth-authorization-server"), "OAuth discovery")
    return resource, auth


def begin(org, secret: str, mcp_url: str, redirect_uri: str, client: httpx.Client | None = None) -> str:
    http = client or httpx.Client(timeout=20)
    resource, auth = _metadata(http, mcp_url)
    registration = auth.get("registration_endpoint")
    if not registration:
        raise SarvamMCPError("Sarvam OAuth does not advertise dynamic client registration.")
    existing = _load(org, secret)
    client_info = existing.get("client") or {}
    if not client_info.get("client_id"):
        client_info = _json(http.post(registration, json={
            "client_name": "DIDM Agent Registry", "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code"], "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }), "client registration")
    state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    scope = " ".join(resource.get("scopes_supported") or auth.get("scopes_supported") or [])
    pending = {"state": state, "verifier": verifier, "redirect_uri": redirect_uri,
               "token_endpoint": auth.get("token_endpoint"), "created_at": int(time.time())}
    _save(org, secret, {"client": client_info, "pending": pending})
    query = {"response_type": "code", "client_id": client_info["client_id"], "redirect_uri": redirect_uri,
             "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
             "resource": mcp_url}
    if scope:
        query["scope"] = scope
    return f"{auth['authorization_endpoint']}?{urlencode(query)}"


def callback(org, secret: str, code: str, state: str, client: httpx.Client | None = None) -> None:
    data = _load(org, secret)
    pending, client_info = data.get("pending") or {}, data.get("client") or {}
    if not state or not secrets.compare_digest(state, str(pending.get("state") or "")):
        raise SarvamMCPError("Sarvam OAuth state is invalid or expired.")
    if time.time() - int(pending.get("created_at") or 0) > 600:
        raise SarvamMCPError("Sarvam OAuth login expired. Start it again.")
    body = {"grant_type": "authorization_code", "code": code, "redirect_uri": pending["redirect_uri"],
            "client_id": client_info["client_id"], "code_verifier": pending["verifier"]}
    if client_info.get("client_secret"):
        body["client_secret"] = client_info["client_secret"]
    token = _json((client or httpx.Client(timeout=20)).post(pending["token_endpoint"], data=body), "token exchange")
    expires = int(time.time()) + int(token.get("expires_in") or 86400)
    _save(org, secret, {"client": client_info, "access_token": token["access_token"], "expires_at": expires})


def org_for_state(orgs, secret: str, state: str):
    for org in orgs:
        try:
            pending = _load(org, secret).get("pending") or {}
            if state and secrets.compare_digest(state, str(pending.get("state") or "")):
                return org
        except SarvamMCPError:
            continue
    return None


def _rpc(client: httpx.Client, url: str, token: str, method: str, params: dict, rpc_id: int,
         session_id: str | None = None, protocol_version: str | None = None) -> tuple[dict, str | None]:
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    if protocol_version:
        headers["MCP-Protocol-Version"] = protocol_version
    resp = client.post(url, headers=headers, json={"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params})
    if resp.status_code == 401:
        raise SarvamMCPError("Sarvam login expired. Reconnect Sarvam.")
    if not 200 <= resp.status_code < 300:
        raise SarvamMCPError(f"Sarvam MCP failed ({resp.status_code}).")
    raw = resp.text
    if "text/event-stream" in resp.headers.get("content-type", ""):
        messages = [line[6:] for line in raw.splitlines() if line.startswith("data: ")]
        raw = messages[-1] if messages else "{}"
    payload = json.loads(raw or "{}")
    if payload.get("error"):
        raise SarvamMCPError(str(payload["error"].get("message") or "Sarvam MCP request failed."))
    return payload.get("result") or {}, resp.headers.get("mcp-session-id") or session_id


def fetch_agent(org, secret: str, mcp_url: str, app_id: str, client: httpx.Client | None = None) -> dict:
    stored = _load(org, secret)
    if not stored.get("access_token") or int(stored.get("expires_at") or 0) <= time.time() + 30:
        raise SarvamMCPError("Connect Sarvam to fetch agent details.")
    http = client or httpx.Client(timeout=30)
    init, sid = _rpc(http, mcp_url, stored["access_token"], "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "didm-agent-registry", "version": "1.0"}}, 1)
    headers = {"Authorization": f"Bearer {stored['access_token']}", "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json", "MCP-Protocol-Version": init.get("protocolVersion", "2025-06-18")}
    if sid:
        headers["Mcp-Session-Id"] = sid
    http.post(mcp_url, headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
    protocol = init.get("protocolVersion", "2025-06-18")
    result, _ = _rpc(http, mcp_url, stored["access_token"], "tools/call",
                     {"name": "agents", "arguments": {"operation": "get", "id": app_id}}, 2, sid, protocol)
    content = result.get("structuredContent")
    if content is None:
        texts = [x.get("text", "") for x in result.get("content", []) if x.get("type") == "text"]
        try:
            content = json.loads("\n".join(texts))
        except json.JSONDecodeError:
            raise SarvamMCPError("Sarvam returned agent details in an unsupported format.")
    return normalize_agent(content, app_id)


def normalize_agent(value, app_id: str) -> dict:
    if isinstance(value, dict) and isinstance(value.get("agent"), dict):
        value = value["agent"]
    if not isinstance(value, dict):
        raise SarvamMCPError("Sarvam did not return this agent.")
    config = value.get("config") or value.get("configuration") or value.get("draft") or value
    variables = config.get("variables") or value.get("variables") or []
    schema = []
    if isinstance(variables, dict):
        variables = [{"name": k, **(v if isinstance(v, dict) else {"default": v})} for k, v in variables.items()]
    for item in variables if isinstance(variables, list) else []:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not re.fullmatch(r"[a-z_][a-z0-9_]{0,63}", item["name"])):
            continue
        typ = str(item.get("type") or item.get("data_type") or "string").lower()
        typ = "enum" if typ in ("select", "choice") else typ
        if typ not in ("string", "number", "integer", "boolean", "enum"):
            typ = "string"
        row = {"name": item["name"], "type": typ, "required": bool(item.get("required", False))}
        for src, dst in (("description", "description"), ("default", "default"), ("options", "options"),
                         ("enum_values", "options")):
            if src in item:
                row[dst] = item[src]
        schema.append(row)
    version = value.get("latest_committed_version") or value.get("app_version") or value.get("version")
    if isinstance(version, dict):
        version = version.get("version") or version.get("number")
    return {"provider_app_id": app_id, "name": str(value.get("name") or config.get("name") or app_id),
            "description": str(value.get("description") or config.get("description") or ""),
            "provider_app_version": version if isinstance(version, int) else None, "variable_schema": schema}

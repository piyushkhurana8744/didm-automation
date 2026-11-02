import json
from types import SimpleNamespace

import httpx

from app.saas.sarvam_mcp import callback, connection_status, normalize_agent


SECRET = "test-only-secret-that-is-at-least-thirty-two-characters"


def test_normalize_agent_metadata_and_variables():
    out = normalize_agent({"agent": {"name": "Ananya", "description": "Admissions",
        "latest_committed_version": 7, "config": {"variables": [
            {"name": "user_name", "data_type": "String", "default": "friend"},
            {"name": "disposition", "type": "choice", "enum_values": ["yes", "no"]},
            {"name": "Bad Name", "type": "string"},
        ]}}}, "agent-1")
    assert out["name"] == "Ananya"
    assert out["provider_app_version"] == 7
    assert [v["name"] for v in out["variable_schema"]] == ["user_name", "disposition"]
    assert out["variable_schema"][1]["type"] == "enum"


def test_callback_stores_short_lived_connection(monkeypatch):
    from app.saas import sarvam_mcp
    org = SimpleNamespace(settings={})
    sarvam_mcp._save(org, SECRET, {"client": {"client_id": "cid"}, "pending": {
        "state": "right", "verifier": "v", "redirect_uri": "https://didm.test/callback",
        "token_endpoint": "https://login.test/token", "created_at": 1000}})
    monkeypatch.setattr(sarvam_mcp.time, "time", lambda: 1010)
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json={"access_token": "token", "expires_in": 60}))
    callback(org, SECRET, "code", "right", httpx.Client(transport=transport))
    assert connection_status(org, SECRET)["connected"] is True

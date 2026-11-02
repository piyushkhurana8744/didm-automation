"""Tests for Sarvam authentication header construction, key normalization, and mocked responses.

Verifies:
- Voice Agents endpoints (outbounds, analytics, recordings, web auth) use X-API-Key with cleaned bare key.
- Chat completions endpoint uses api-subscription-key and Authorization: Bearer <key> without duplicate Bearer.
- Keys with quotes, whitespace, newlines, and Bearer prefix are cleanly sanitized.
- Mocked 401 "Invalid API key format" responses are parsed safely without crashing or leaking secrets.
"""
import json
import httpx
import pytest

from app.config import Settings, _clean_secret
from app.integrations import CallTarget, Sarvam, SarvamWebAuth
from app.saas import providers
from app.saas.intelligence import EvaluatorError, JobRetry


def test_clean_secret_normalization():
    # Plain key
    assert _clean_secret("K", "simple_key") == "simple_key"
    # Leading and trailing whitespace
    assert _clean_secret("K", "  whitespace_key  \n") == "whitespace_key"
    # Double quotes
    assert _clean_secret("K", '"quoted_key"') == "quoted_key"
    # Single quotes
    assert _clean_secret("K", "'single_quoted_key'") == "single_quoted_key"
    # Bearer prefix
    assert _clean_secret("K", "Bearer my_key") == "my_key"
    assert _clean_secret("K", "bearer  my_key") == "my_key"
    # Quoted with Bearer prefix
    assert _clean_secret("K", '"Bearer quoted_bearer_key"') == "quoted_bearer_key"
    assert _clean_secret("K", "'Bearer single_quoted_bearer'") == "single_quoted_bearer"
    # Empty and None
    assert _clean_secret("K", "") == ""


def test_sarvam_start_call_headers_and_mock_response():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"attempt_id": "att-12345"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    # Test key with quotes and Bearer prefix in Settings
    s = Settings()
    s.sarvam_api_key = '"Bearer test_secret_voice_key"'
    s.sarvam_org_id = "org-1"
    s.sarvam_workspace_id = "ws-1"
    s.sarvam_app_id = "app-1"
    s.sarvam_app_version = 1
    s.sarvam_connection_id = "conn-1"
    s.sarvam_agent_phone = "+911234567890"

    sarvam = Sarvam(s, client=mock_client)
    res = sarvam.start_call("+919876543210", {"test": "var"}, {"kind": "test"})

    assert res["ok"] is True
    assert res["attempt_id"] == "att-12345"
    assert len(recorded_requests) == 1

    req = recorded_requests[0]
    assert req.method == "POST"
    assert "https://apps.sarvam.ai/api/outbounds/v1/orgs/org-1/workspaces/ws-1/outbounds" in str(req.url)
    # The X-API-Key header must be the cleaned bare key without quotes or Bearer
    assert req.headers["X-API-Key"] == "test_secret_voice_key"
    assert "Bearer" not in req.headers["X-API-Key"]
    assert '"' not in req.headers["X-API-Key"]


def test_sarvam_start_call_401_invalid_api_key_format_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "message": "(401) Unauthorized",
                "type": "unauthorized",
                "code": 401,
                "data": {"details": "Invalid API key format."},
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    s = Settings()
    s.sarvam_api_key = "invalid_key_format"
    s.sarvam_org_id = "org-1"
    s.sarvam_workspace_id = "ws-1"

    sarvam = Sarvam(s, client=mock_client)
    res = sarvam.start_call("+919876543210", {}, {})

    assert res["ok"] is False
    assert res["status_code"] == 401
    assert res["attempt_id"] is None
    assert "Invalid API key format" in res["error"]


def test_sarvam_chat_evaluator_authorization_header():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"score": 90})}}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
            },
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))

    # Pass key with redundant "Bearer " prefix and surrounding quotes
    evaluator = providers.SarvamChatEvaluator(
        api_key='"Bearer test_chat_subscription_key"',
        model="sarvam-105b",
        client=mock_client,
    )

    out, usage = evaluator.evaluate_metered("system prompt", "user query", {"type": "object"})
    assert out == {"score": 90}
    assert usage["total_tokens"] == 150
    assert len(recorded_requests) == 1

    req = recorded_requests[0]
    # Check that api-subscription-key has the bare cleaned key
    assert req.headers["api-subscription-key"] == "test_chat_subscription_key"
    # Check that Authorization has exactly one "Bearer " prefix and no duplicate "Bearer Bearer"
    assert req.headers["Authorization"] == "Bearer test_chat_subscription_key"
    assert "Bearer Bearer" not in req.headers["Authorization"]


def test_sarvam_chat_evaluator_401_error_handling():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={"message": "(401) Unauthorized", "data": {"details": "Invalid API key format."}},
        )

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    evaluator = providers.SarvamChatEvaluator("bad_key", "sarvam-105b", client=mock_client)

    with pytest.raises(EvaluatorError) as exc_info:
        evaluator.evaluate_metered("sys", "usr", {})

    assert exc_info.value.code == "evaluator_auth"
    assert exc_info.value.retryable is False


def test_sarvam_analytics_headers():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"items": []})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    s = Settings()
    s.sarvam_api_key = "  Bearer ws_key_123  "
    s.sarvam_org_id = "org-1"
    s.sarvam_workspace_id = "ws-1"

    analytics = providers.SarvamAnalytics(s, client=mock_client)
    resp = analytics._get("app-1", "attempts", {})

    assert resp.status_code == 200
    assert recorded_requests[0].headers["X-API-Key"] == "ws_key_123"


def test_sarvam_web_auth_headers():
    recorded_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded_requests.append(request)
        return httpx.Response(200, json={"url": "wss://apps.sarvam.ai/ws", "reference_id": "ref-1"})

    mock_client = httpx.Client(transport=httpx.MockTransport(handler))
    s = Settings()
    s.sarvam_api_key = '"ws_key_456"'
    s.sarvam_org_id = "org-1"
    s.sarvam_workspace_id = "ws-1"

    web_auth = SarvamWebAuth(s, client=mock_client)
    res = web_auth.signed_url("app-1", 1)

    assert res["url"] == "wss://apps.sarvam.ai/ws"
    assert recorded_requests[0].headers["X-API-Key"] == "ws_key_456"


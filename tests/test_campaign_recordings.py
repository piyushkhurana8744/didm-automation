from datetime import datetime
from types import SimpleNamespace

import httpx
import pytest

from app.config import Settings
from app.db import Batch, CallAttempt, SessionLocal
from app.saas.campaign_recordings import CampaignRecordings
from app.saas.intelligence import JobGiveUp, JobRetry
from app.saas.providers import SarvamAnalytics, SarvamRecordingSource
from tests.test_agents import world, publish_agent, assign  # noqa: F401
from tests.test_saas import saas  # noqa: F401

from io import BytesIO
import wave

buffer = BytesIO()
with wave.open(buffer, "wb") as wav:
    wav.setnchannels(1)
    wav.setsampwidth(2)
    wav.setframerate(8000)
    wav.writeframes(b"\x00\x00" * 32)
WAV = buffer.getvalue()


def test_recording_uses_pinned_app_and_exact_attempt_before_fetching_audio():
    s = Settings(sarvam_api_key="key", sarvam_org_id="org", sarvam_workspace_id="workspace")
    seen = []

    def respond(request):
        seen.append(request)
        assert request.headers["X-API-Key"] == "key"
        if request.url.path.endswith("/attempts"):
            assert '"value": "attempt-1"' in request.url.params["filter_conditions"]
            assert request.url.params["start_datetime"].endswith("+00:00")
            return httpx.Response(200, json={"items": [
                {"attempt_id": "other", "interaction_id": "wrong"},
                {"attempt_id": "attempt-1", "interaction_id": "20261116/interaction"}]})
        assert "/pinned-app/recordings/" in request.url.path
        return httpx.Response(200, content=WAV, headers={"Content-Type": "audio/wav"})

    client = httpx.Client(transport=httpx.MockTransport(respond))
    service = CampaignRecordings(s, SarvamAnalytics(s, client), SarvamRecordingSource(s, client))
    call = SimpleNamespace(attempt_id="attempt-1", raw_result=None, duration=70,
                           started_at=datetime(2026, 11, 16, 6, 0))
    result = service.fetch(call, SimpleNamespace(provider_app_id="pinned-app"))
    assert result == (WAV, "audio/wav", "20261116/interaction")
    assert len(seen) == 2


@pytest.mark.parametrize("status,content,mime,expected", [
    (404, b"", "", None),
    (200, b"<html>error</html>", "audio/wav", JobGiveUp),
    (429, b"", "", JobRetry),
])
def test_recording_handles_unavailable_invalid_and_rate_limited_audio(status, content, mime, expected):
    s = Settings(sarvam_api_key="key", sarvam_org_id="org", sarvam_workspace_id="workspace")
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(
        status, content=content, headers={"Content-Type": mime, "Retry-After": "90"})))
    service = CampaignRecordings(s, source=SarvamRecordingSource(s, client))
    call = SimpleNamespace(attempt_id="attempt", raw_result={"interaction_id": "20261116/known"},
                           duration=30, started_at=datetime(2026, 11, 16))
    if expected:
        with pytest.raises(expected):
            service.fetch(call, SimpleNamespace(provider_app_id="pinned-app"))
    else:
        assert service.fetch(call, SimpleNamespace(provider_app_id="pinned-app")) is None


def saved_call(agent_id, **values):
    with SessionLocal() as db:
        batch = Batch(agent_id=agent_id, provider_app_id="pinned-app", requested=1, active=False)
        db.add(batch)
        db.flush()
        call = CallAttempt(batch_id=batch.id, sheet_row=2, attempt_id="recording-attempt",
                           state="done", dry_run=False, **values)
        db.add(call)
        db.commit()
        return call.id


def test_recording_route_checks_org_and_assignment_before_provider_access(world):
    a = world.a
    agent, _ = publish_agent(a)
    other, _ = publish_agent(a, app_id="other-agent")
    assign(a, a.owner, [other], [a.user_id("trainee@alpha.in")])
    call_id = saved_call(agent)
    fetched = []

    def fetch(call, batch):
        fetched.append(call.id)
        return WAV, "audio/wav", "20261116/recorded"

    world.app.state.campaign_recordings.fetch = fetch
    path = f"/calling-campaign/calls/{call_id}/recording"
    assert world.b.owner.get(world.b.base + path).status_code == 404
    assert a.trainee.get(a.base + path).status_code == 404
    assert not fetched
    response = a.owner.get(a.base + path)
    assert response.status_code == 200, response.text
    assert response.content == WAV
    assert response.headers["cache-control"] == "private, no-store"
    assert "call-" in response.headers["content-disposition"]
    assert fetched == [call_id]
    with SessionLocal() as db:
        assert db.get(CallAttempt, call_id).raw_result["interaction_id"] == "20261116/recorded"
    assign(a, a.owner, [agent], [a.user_id("trainee@alpha.in")])
    assert a.trainee.get(a.base + path).status_code == 200


def test_test_calls_have_no_recording_and_missing_audio_is_explained(world):
    a = world.a
    agent, _ = publish_agent(a)
    call_id = saved_call(agent)
    path = f"{a.base}/calling-campaign/calls/{call_id}/recording"
    world.app.state.campaign_recordings.fetch = lambda *args: None
    assert a.owner.get(path).status_code == 404
    with SessionLocal() as db:
        db.get(CallAttempt, call_id).dry_run = True
        db.commit()
    assert "Test calls" in a.owner.get(path).json()["detail"]


def test_recording_route_serves_selected_speaker_and_preserves_original(world):
    from tests.test_campaign_audio import wav
    a = world.a
    agent, _ = publish_agent(a)
    call_id = saved_call(agent)
    stereo = wav([100, 0, 0, 80])
    world.app.state.campaign_recordings.fetch = lambda *args: (stereo, "audio/wav", "20261116/test")
    path = f"{a.base}/calling-campaign/calls/{call_id}/recording"
    student = a.owner.get(path + "?channel=student")
    assert student.status_code == 200
    with wave.open(BytesIO(student.content), "rb") as audio:
        assert audio.getnchannels() == 1
        assert audio.readframes(2) == b"\x64\x00\x00\x00"
    assert "student.wav" in student.headers["content-disposition"]
    assert a.owner.get(path + "?channel=original").content == stereo
    assert a.owner.get(path + "?channel=invalid").status_code == 422

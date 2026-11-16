"""Excel calling follows active phone-agent assignments."""
from tests.test_agents import world, publish_agent, assign  # noqa: F401
from tests.test_saas import saas  # noqa: F401


def test_assigned_trainee_can_upload_and_only_select_assigned_agents(world):
    a = world.a
    agent, _ = publish_agent(a)
    other, _ = publish_agent(a, app_id="other-phone")
    base = f"{a.base}/calling-campaign"
    assert a.trainee.get(base).status_code == 403
    result = assign(a, a.owner, [agent], [a.user_id("trainee@alpha.in")])
    assert result.status_code == 201, result.text
    assignment = result.json()["created"][0]["id"]
    status = a.trainee.get(base)
    assert status.status_code == 200, status.text
    assert [item["id"] for item in status.json()["agents"]] == [agent]
    assert a.trainee.get(f"{base}/sample.xlsx").status_code == 200
    uploaded = a.trainee.post(f"{base}/upload", content=b"name,phone\nRiya,9876543210\n",
                             headers={"X-Upload-Filename": "leads.csv"})
    assert uploaded.status_code == 200, uploaded.text
    assert a.trainee.post(f"{base}/start", {"agent_id": other}).status_code == 422
    assert a.trainee2.post(f"{base}/stop").status_code == 403
    assert a.owner.post(f"{a.base}/assignments/{assignment}/revoke").status_code == 200
    assert a.trainee.get(base).status_code == 403
    assert a.trainee.post(f"{base}/resume").status_code == 403
    assert a.owner.get(base).status_code == 200


def test_browser_only_assignment_does_not_allow_excel_calling(world):
    a = world.a
    agent, _ = publish_agent(a, channels=["browser"])
    assert assign(a, a.owner, [agent], [a.user_id("trainee@alpha.in")]).status_code == 201
    assert a.trainee.get(f"{a.base}/calling-campaign").status_code == 403


def test_campaign_mode_is_explicit_and_persisted(world):
    from datetime import datetime
    from app.db import Batch, CallAttempt, SessionLocal
    from app.excel_leads import DatabaseLeadSheet
    from sqlalchemy import select
    from app.integrations import Sarvam
    import httpx

    a = world.a
    agent, _ = publish_agent(a, schema=[])
    auto = world.app.state.automation
    auto.sheet = DatabaseLeadSheet()
    auto._clock = lambda: datetime(2026, 11, 16, 11, 0)
    for key, value in {"sarvam_api_key": "key", "sarvam_org_id": "org", "sarvam_workspace_id": "ws",
                       "sarvam_connection_id": "conn", "sarvam_agent_phone": "+917965853567",
                       "whatsapp_enabled": False}.items():
        setattr(auto.s, key, value)
    sent = []
    def respond(request):
        sent.append(request)
        return httpx.Response(200, json={"attempt_id": "live-attempt"})
    auto.sarvam = Sarvam(auto.s, client=httpx.Client(transport=httpx.MockTransport(respond)))
    base = f"{a.base}/calling-campaign"
    uploaded = a.owner.post(base + "/upload", content=b"name,phone\nRiya,9876543210\n",
                            headers={"X-Upload-Filename": "leads.csv"}).json()
    body = {"agent_id": agent, "upload_id": uploaded["upload_id"], "count": 1}
    simulated = a.owner.post(base + "/start", {**body, "mode": "test"})
    assert simulated.status_code == 200, simulated.text
    assert simulated.json()["dry_run"] and not sent
    assert a.owner.get(base).json()["queue"]["ready"] == 1
    live = a.owner.post(base + "/start", {**body, "mode": "live"})
    assert live.status_code == 200, live.text
    assert not live.json()["dry_run"] and len(sent) == 1
    assert auto.s.dry_run is True  # global default remains unchanged
    with SessionLocal() as db:
        assert db.get(Batch, live.json()["batch_id"]).dry_run is False
        assert db.scalars(select(CallAttempt).where(CallAttempt.attempt_id == "live-attempt")).one().dry_run is False
    assert a.owner.post(base + "/start", {**body, "mode": "invalid"}).status_code == 422
    for invalid in (0, 11):
        assert a.owner.post(base + "/start", {**body, "parallel_calls": invalid}).status_code == 422

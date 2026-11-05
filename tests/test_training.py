"""Phase 3: training sessions over phone and browser, limits, reservations, provider results, isolation."""
import threading
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db import CallAttempt, SessionLocal, WhatsAppMessage, utcnow
from app.saas.models import (BrowserSessionToken, Membership, Organization, TrainingSession, TrainingSessionEvent,
                             TrainingUsageEvent, TrainingUsageReservation, User)
from app.saas.training import TrainingError, runtime_identity_variables, webhook_signature
from tests.test_agents import Org, assign, publish_agent, scenario
from tests.test_saas import saas  # noqa: F401  (fixture)

SECRET = "train-secret"


def test_runtime_identity_uses_declared_aliases_and_legacy_lead_name():
    assert runtime_identity_variables(set(), "Piyush", "Counsellor") == {"lead_name": "Piyush"}
    assert runtime_identity_variables({"user_name", "agent_name"}, "Piyush", "Counsellor") == {
        "user_name": "Piyush", "agent_name": "Counsellor"}
    assert runtime_identity_variables({"student_name"}, "Piyush", "Counsellor") == {"student_name": "Piyush"}


class FakeSarvam:
    def __init__(self):
        self.calls = []
        self.fail = None
        self.during_call = None  # runs inside start_call, before it returns (out-of-order tests)
        self.n = 0
        self.lock = threading.Lock()

    def start_call(self, phone, variables, metadata, target=None, webhook_url=None):
        with self.lock:
            self.n += 1
            n = self.n
        self.calls.append({"phone": phone, "variables": variables, "metadata": metadata, "target": target,
                           "webhook_url": webhook_url})
        if self.fail:
            return {"ok": False, "status_code": self.fail, "attempt_id": None, "error": "nope"}
        attempt = f"att-{n}"
        if self.during_call:
            self.during_call(attempt, metadata)
        return {"ok": True, "status_code": 200, "attempt_id": attempt, "error": None}


class FakeBrowser:
    def __init__(self):
        self.n = 0

    def signed_url(self, app_id, app_version):
        self.n += 1
        return {"url": f"wss://voice.example/{app_id}/{app_version}/{self.n}?sig=secret", "reference_id": f"ref-{self.n}",
                "ttl_seconds": 60}


@pytest.fixture
def tw(saas):
    s = saas.settings
    s.training_phone_enabled, s.training_webhook_secret = True, SECRET
    s.training_max_concurrent_total = 50
    eng = saas.app.state.training
    eng.sarvam = FakeSarvam()
    a, b = Org(saas, "alpha"), Org(saas, "beta")
    a.admin = a.invite("admin@alpha.in", "organization_admin")
    a.trainer = a.invite("trainer@alpha.in", "trainer")
    a.t1 = a.invite("t1@alpha.in", "trainee")
    a.t2 = a.invite("t2@alpha.in", "trainee")
    b.t1 = b.invite("t1@beta.in", "trainee")
    saas.a, saas.b, saas.eng = a, b, eng
    for org in (a, b):
        set_limits(saas, org, enabled=True, max_concurrent_sessions=10, max_concurrent_per_user=1,
                   max_sessions_per_user_per_day=20, monthly_minutes=1000, max_session_minutes=10)
        org.agent, org.v1 = publish_agent(org, f"app-{org.id[:6]}", channels=["phone", "browser"])
        org.scn = scenario(org, org.agent)
    team = a.owner.post(f"{a.base}/teams", {"name": "All"}).json()["id"]
    a.owner.post(f"{a.base}/teams/{team}/members", {"user_ids": [a.user_id("t1@alpha.in"), a.user_id("t2@alpha.in")]})
    assert assign(a, a.owner, [a.agent], team_ids=[team]).status_code == 201
    assert assign(b, b.owner, [b.agent], [b.user_id("t1@beta.in")]).status_code == 201
    a.team = team
    for org, who, email in ((a, a.t1, "t1@alpha.in"), (a, a.t2, "t2@alpha.in"), (b, b.t1, "t1@beta.in")):
        verify_phone(org, who, email, "98765" + str(abs(hash(email)) % 100000).zfill(5))
    return saas


def set_limits(w, org, **kw):
    r = w.root.c.put(f"/api/v1/platform/organizations/{org.id}/training-limits", json=kw,
                     headers={"X-CSRF-Token": w.root.c.cookies.get("didm_csrf")})
    assert r.status_code == 200, r.text
    return r.json()


def verify_phone(org, who, email, phone):
    assert who.c.put("/api/v1/auth/me/phone", json={"phone": phone},
                     headers={"X-CSRF-Token": who.c.cookies.get("didm_csrf")}).status_code == 200
    mid = next(m["membership_id"] for m in org.owner.get(f"{org.base}/members").json() if m["user"]["email"] == email)
    assert org.owner.post(f"{org.base}/members/{mid}/verify-phone", {"phone": phone}).status_code == 200


def start(org, who, channel="phone", scenario_id="default", agent=None, **kw):
    """The test agent has required variables, so a session needs a scenario that sets them."""
    return who.post(f"{org.base}/training/sessions", {
        "agent_id": agent or org.agent, "channel": channel,
        "scenario_id": org.scn if scenario_id == "default" else scenario_id, **kw})


def result(w, sid, org_id, status="connected", duration=95, attempt=None, sig=None, secret=SECRET):
    payload = {"attempt_id": attempt, "status": status, "duration": duration if status == "connected" else None,
               "interaction_id": "20261021/abc" if status == "connected" else None,
               "final_agent_variables": {"disposition": "interested"},
               "webhook_config": {"url": "x", "metadata": {"kind": "training", "session_id": sid, "org_id": org_id,
                                                          "sig": sig or webhook_signature(SECRET, sid, org_id)}}}
    return w.browser().c.post(f"/webhooks/sarvam-training/{secret}", json=payload)


def row(sid):
    with SessionLocal() as db:
        return db.get(TrainingSession, sid)


# ---------- phone: start ----------
def test_phone_session_starts_with_pinned_version_and_training_webhook(tw):
    a = tw.a
    r = start(a, a.t1, scenario_id=a.scn)
    assert r.status_code == 201, r.text
    s = r.json()
    assert s["status"] == "connecting" and s["agent_version_id"] == a.v1 and s["provider_app_version"] == 3
    assert s["phone"].startswith("******") and "98765" not in str(s)
    call = tw.eng.sarvam.calls[-1]
    assert call["target"].app_id == f"app-{a.id[:6]}" and call["target"].app_version == 3
    assert call["webhook_url"] == f"https://automation.example.in/webhooks/sarvam-training/{SECRET}"
    assert call["metadata"]["session_id"] == s["id"] and call["metadata"]["kind"] == "training"
    assert call["variables"] == {"tone": "friendly", "student_name": "Riya", "course": "MBA"}
    assert row(s["id"]).provider_attempt_id == "att-1"
    with SessionLocal() as db:
        res = db.scalars(select(TrainingUsageReservation).where(TrainingUsageReservation.session_id == s["id"])).one()
        assert res.status == "confirmed" and res.reserved_seconds == 600


def test_custom_lead_name_and_variables_passed_to_sarvam(tw):
    a = tw.a
    res = a.t1.post(f"{a.base}/training/sessions", json={
        "agent_id": a.agent,
        "channel": "phone",
        "scenario_id": a.scn,
        "lead_name": "Piyush Khurana",
        "custom_variables": {"city": "Delhi", "budget": "50000"}
    }, headers={"X-CSRF-Token": a.t1.c.cookies.get("didm_csrf")})
    assert res.status_code == 201, res.text
    call = tw.eng.sarvam.calls[-1]
    assert call["variables"]["lead_name"] == "Piyush Khurana"
    assert call["variables"]["student_name"] == "Piyush Khurana"
    assert call["variables"]["city"] == "Delhi"
    assert call["variables"]["budget"] == "50000"


def test_org_admin_selects_exact_sarvam_name_variable(tw):
    a = tw.a
    def put(who, name):
        return who.c.put(f"{a.base}/training/sarvam-name-variable", json={"name": name},
                         headers={"X-CSRF-Token": who.c.cookies.get("didm_csrf")})
    saved = put(a.owner, "contact_name")
    assert saved.status_code == 200 and saved.json() == {"name": "contact_name"}
    assert a.owner.get(f"{a.base}/training/sarvam-name-variable").json() == {"name": "contact_name"}
    response = start(a, a.t1)
    assert response.status_code == 201, response.text
    assert tw.eng.sarvam.calls[-1]["variables"]["contact_name"] == "t1@alpha.in"
    assert put(a.t1, "hacked").status_code == 403
    assert put(a.owner, "Bad Name").status_code == 422


def test_org_admin_maps_personal_material_to_exact_sarvam_context_variable(tw):
    a = tw.a
    csrf = {"X-CSRF-Token": a.owner.c.cookies.get("didm_csrf")}
    saved = a.owner.c.put(f"{a.base}/training/sarvam-context-variable",
                          json={"name": "call_training_material"}, headers=csrf)
    assert saved.status_code == 200 and saved.json() == {"name": "call_training_material"}
    assert a.owner.get(f"{a.base}/training/sarvam-context-variable").json() == {
        "name": "call_training_material"
    }

    trainee_csrf = {"X-CSRF-Token": a.t1.c.cookies.get("didm_csrf")}
    added = a.t1.c.post(f"{a.base}/my/agents/{a.agent}/training-profile/text",
                        json={"title": "Course facts", "text": "The approved fee is 50000."},
                        headers=trainee_csrf)
    assert added.status_code == 201, added.text

    response = start(a, a.t1)
    assert response.status_code == 201, response.text
    context = tw.eng.sarvam.calls[-1]["variables"]["call_training_material"]
    assert "SOURCE: Course facts" in context
    assert "SOURCE TYPE: TEXT" in context
    assert "The approved fee is 50000." in context
    assert a.t1.c.put(f"{a.base}/training/sarvam-context-variable",
                      json={"name": "hacked"}, headers=trainee_csrf).status_code == 403
    assert a.owner.c.put(f"{a.base}/training/sarvam-context-variable",
                         json={"name": "Bad Name"}, headers=csrf).status_code == 422


def test_new_published_version_does_not_change_existing_session(tw):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    base = f"{a.base}/agents/{a.agent}/versions"
    d = a.owner.post(base, {}).json()
    a.owner.patch(f"{base}/{d['id']}", {"provider_app_version": 9})
    assert a.owner.post(f"{base}/{d['id']}/publish").status_code == 200
    assert row(sid).provider_app_version == 3 and row(sid).agent_version_id == a.v1
    result(tw, sid, a.id, attempt="att-1")
    assert start(a, a.t1).json()["provider_app_version"] == 9


def test_start_refusals(tw):
    a = tw.a
    assert start(a, a.t1, agent=tw.b.agent).status_code == 404  # another org's agent
    r = start(a, a.t1, scenario_id=None)  # required variables need a scenario
    assert r.status_code == 422 and "required" in r.json()["detail"]
    assert start(a, a.t1, scenario_id=tw.b.scn).status_code == 404
    assert start(a, a.t1, channel="fax").status_code == 422
    assert start(a, a.t1, channel="browser").status_code == 503  # browser is off
    # an admin who is not assigned the agent cannot start it
    assert start(a, a.admin).status_code == 404
    # phone must be verified, and changing it un-verifies it
    a.t1.c.put("/api/v1/auth/me/phone", json={"phone": "9000000001"}, headers={"X-CSRF-Token": a.t1.c.cookies.get("didm_csrf")})
    r = start(a, a.t1)
    assert r.status_code == 409 and "verify" in r.json()["detail"]
    set_limits(tw, a, enabled=False)
    assert start(a, a.t2).status_code == 403
    assert tw.eng.sarvam.calls == []
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrainingSession.id))) == 0


def test_platform_phone_switch_off_blocks_calls(tw):
    tw.settings.training_phone_enabled = False
    r = start(tw.a, tw.a.t1)
    assert r.status_code == 503 and tw.eng.sarvam.calls == []


def test_revoked_assignment_blocks_start(tw):
    a = tw.a
    aid = a.owner.get(f"{a.base}/assignments").json()["items"][0]["id"]
    a.owner.post(f"{a.base}/assignments/{aid}/revoke")
    assert start(a, a.t1).status_code == 404


def test_scenario_variables_rechecked_at_start(tw):
    """A scenario made invalid by a new published schema is refused instead of sent to Sarvam."""
    a = tw.a
    base = f"{a.base}/agents/{a.agent}/versions"
    d = a.owner.post(base, {}).json()
    schema = d["variable_schema"] + [{"name": "city", "type": "string", "required": True}]
    a.owner.patch(f"{base}/{d['id']}", {"variable_schema": schema})
    a.owner.post(f"{base}/{d['id']}/publish")
    r = start(a, a.t1, scenario_id=a.scn)
    assert r.status_code == 422 and "city" in r.json()["detail"]


def test_phone_verification_rules(tw):
    a = tw.a
    mid = next(m["membership_id"] for m in a.owner.get(f"{a.base}/members").json() if m["user"]["email"] == "t1@alpha.in")
    assert a.trainer.post(f"{a.base}/members/{mid}/verify-phone", {"phone": "9000000000"}).status_code == 403
    assert a.owner.post(f"{a.base}/members/{mid}/verify-phone", {"phone": "9111111111"}).status_code == 409
    assert tw.b.owner.post(f"{tw.b.base}/members/{mid}/verify-phone", {"phone": "9111111111"}).status_code == 404
    phones = a.owner.get(f"{a.base}/training/phones").json()
    assert any(p["email"] == "t1@alpha.in" and p["verified"] for p in phones)


def test_only_platform_admin_changes_limits(tw):
    a = tw.a
    r = a.owner.c.put(f"/api/v1/platform/organizations/{a.id}/training-limits", json={"monthly_minutes": 99999},
                      headers={"X-CSRF-Token": a.owner.c.cookies.get("didm_csrf")})
    assert r.status_code == 403
    a.owner.patch(f"/api/v1/organizations/{a.id}", {"settings": {"training": {"monthly_minutes": 99999}}})
    assert a.owner.get(f"{a.base}/training/limits").json()["effective"]["monthly_minutes"] == 1000


# ---------- provider results ----------
def test_result_completes_session_once_and_never_touches_lead_automation(tw):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    r = result(tw, sid, a.id, attempt="att-1")
    assert r.status_code == 200 and r.json()["status"] == "completed"
    s = row(sid)
    assert s.status == "completed" and s.duration_seconds == 95 and s.billable_seconds == 95
    assert s.provider_session_id == "20261021/abc" and s.connected_at is not None
    assert result(tw, sid, a.id, attempt="att-1").json().get("duplicate")
    with SessionLocal() as db:
        usage = {u.metric: u.quantity for u in db.scalars(select(TrainingUsageEvent).where(
            TrainingUsageEvent.session_id == sid))}
        assert usage == {"billable_seconds": 95, "sessions": 1}
        assert db.scalars(select(TrainingUsageReservation.status).where(
            TrainingUsageReservation.session_id == sid)).one() == "settled"
        assert db.scalar(select(func.count(CallAttempt.id))) == 0
        assert db.scalar(select(func.count(WhatsAppMessage.id))) == 0


def test_not_connected_result_fails_and_frees_capacity(tw):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    assert start(a, a.t1).status_code == 409  # one open session per trainee
    result(tw, sid, a.id, status="no_answer", attempt="att-1")
    s = row(sid)
    assert s.status == "failed" and s.failure_code == "no_answer" and s.billable_seconds == 0
    with SessionLocal() as db:
        assert db.scalars(select(TrainingUsageReservation.status).where(
            TrainingUsageReservation.session_id == sid)).one() == "released"
    assert start(a, a.t1).status_code == 201


def test_forged_or_cross_tenant_results_are_ignored(tw):
    a, b = tw.a, tw.b
    sid = start(a, a.t1).json()["id"]
    assert tw.browser().c.post("/webhooks/sarvam-training/wrong", json={}).status_code == 404
    # signed for org B, claiming org A's session
    r = result(tw, sid, b.id, attempt="att-1", sig=webhook_signature(SECRET, sid, b.id))
    assert r.json()["reason"] == "unknown session"
    assert result(tw, sid, a.id, attempt="att-1", sig="0" * 64).json()["reason"] == "bad signature"
    assert result(tw, sid, a.id, attempt="att-999").json()["reason"] == "attempt mismatch"
    assert row(sid).status == "connecting"
    # The legacy dialler webhook does not accept the training secret
    assert tw.browser().c.post(f"/webhooks/sarvam/{SECRET}", json={}).status_code == 404


def test_result_arriving_before_start_call_returns(tw):
    """Sarvam can post the result before our start request has stored the attempt id."""
    a = tw.a

    def early(attempt, metadata):
        assert result(tw, metadata["session_id"], a.id, attempt=attempt).json()["status"] == "completed"
    tw.eng.sarvam.during_call = early
    s = start(a, a.t1).json()
    assert s["status"] == "completed"
    assert row(s["id"]).provider_attempt_id == "att-1" and row(s["id"]).billable_seconds == 95


def test_late_result_after_timeout_keeps_terminal_state(tw):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    out = tw.eng.sweep(now=utcnow() + timedelta(minutes=60))
    assert out["timed_out"] == 1
    s = row(sid)
    assert s.status == "timed_out" and s.billable_seconds == 600  # placed call, no result: bill the cap
    assert result(tw, sid, a.id, attempt="att-1").json()["late"] is True
    assert row(sid).status == "timed_out"
    with SessionLocal() as db:
        ev = db.scalars(select(TrainingSessionEvent).where(TrainingSessionEvent.session_id == sid,
                                                          TrainingSessionEvent.event_type == "provider_result")).one()
        assert ev.event_payload["late"] is True
        assert db.scalar(select(func.count(TrainingUsageEvent.id)).where(
            TrainingUsageEvent.session_id == sid, TrainingUsageEvent.metric == "billable_seconds")) == 1


def test_provider_failure_marks_failed_and_releases(tw):
    a = tw.a
    tw.eng.sarvam.fail = 500
    s = start(a, a.t1).json()
    assert s["status"] == "failed" and s["failure_code"] == "provider_rejected"
    tw.eng.sarvam.fail = None
    assert start(a, a.t1).json()["status"] == "connecting"


def test_start_timeout_reclaims_reservation(tw):
    a = tw.a
    with SessionLocal() as db:
        org, user = db.get(Organization, a.id), db.scalars(select(User).where(User.email == "t1@alpha.in")).one()
        m = db.scalars(select(Membership).where(Membership.user_id == user.id, Membership.organization_id == a.id)).one()
        sess, _ = tw.eng.request_session(db, org, user, m, a.agent, "phone", a.scn, None)
        sid = sess.id
    assert tw.eng.sweep(now=utcnow() + timedelta(minutes=5))["start_timeouts"] == 1
    assert row(sid).status == "failed" and row(sid).failure_code == "start_timeout"
    with SessionLocal() as db:
        assert db.scalars(select(TrainingUsageReservation.status).where(
            TrainingUsageReservation.session_id == sid)).one() == "expired"
    assert tw.eng.sweep(now=utcnow() + timedelta(minutes=5)) == {"start_timeouts": 0, "timed_out": 0,
                                                                  "reservations_expired": 0}


def test_cancel_rules(tw):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    assert a.t1.post(f"{a.base}/training/sessions/{sid}/cancel").status_code == 409  # call already placed
    assert a.t2.post(f"{a.base}/training/sessions/{sid}/cancel").status_code == 404
    with SessionLocal() as db:
        org, user = db.get(Organization, a.id), db.scalars(select(User).where(User.email == "t2@alpha.in")).one()
        m = db.scalars(select(Membership).where(Membership.user_id == user.id, Membership.organization_id == a.id)).one()
        sid2 = tw.eng.request_session(db, org, user, m, a.agent, "phone", a.scn, None)[0].id
    assert a.admin.post(f"{a.base}/training/sessions/{sid2}/cancel").json()["status"] == "cancelled"
    assert row(sid2).billable_seconds == 0


# ---------- limits and races ----------
def test_idempotent_start_returns_same_session(tw):
    a = tw.a
    one = start(a, a.t1, client_request_id="req-12345678").json()
    two = start(a, a.t1, client_request_id="req-12345678").json()
    assert one["id"] == two["id"] and two["replayed"] is True and len(tw.eng.sarvam.calls) == 1


def test_daily_and_monthly_limits(tw):
    a = tw.a
    set_limits(tw, a, max_sessions_per_user_per_day=1)
    sid = start(a, a.t1).json()["id"]
    result(tw, sid, a.id, attempt="att-1")
    r = start(a, a.t1)
    assert r.status_code == 429 and r.headers["x-error-code"] == "daily_limit"
    set_limits(tw, a, max_sessions_per_user_per_day=20, monthly_minutes=11)  # 95 s used, a 10 min session would exceed
    r = start(a, a.t2)
    assert r.status_code == 429 and r.headers["x-error-code"] == "monthly_minutes"
    usage = a.owner.get(f"{a.base}/training/usage").json()
    assert usage["billable_minutes"] == 1.6 and usage["connected_sessions"] == 1
    assert a.t1.get(f"{a.base}/training/usage").status_code == 403


def test_assignment_limit_cannot_be_widened_by_extra_teams(tw):
    """Joining several teams gives the most generous single grant, never the sum, and org caps still win."""
    a = tw.a
    aid = a.owner.get(f"{a.base}/assignments").json()["items"][0]["id"]
    a.owner.patch(f"{a.base}/assignments/{aid}", {"settings": {"max_sessions": 1}})
    team2 = a.owner.post(f"{a.base}/teams", {"name": "Second"}).json()["id"]
    a.owner.post(f"{a.base}/teams/{team2}/members", {"user_ids": [a.user_id("t1@alpha.in")]})
    assign(a, a.owner, [a.agent], team_ids=[team2], settings={"max_sessions": 1})
    sid = start(a, a.t1).json()["id"]
    result(tw, sid, a.id, attempt="att-1")
    r = start(a, a.t1)
    assert r.status_code == 429 and r.headers["x-error-code"] == "assignment_limit"


def _parallel_starts(tw, org, users, n_each=1):
    """Fires start requests at the same moment from separate threads and DB sessions."""
    barrier = threading.Barrier(len(users) * n_each)
    results = []

    def go(email):
        with SessionLocal() as db:
            o = db.get(Organization, org.id)
            u = db.scalars(select(User).where(User.email == email)).one()
            m = db.scalars(select(Membership).where(Membership.user_id == u.id, Membership.organization_id == org.id)).one()
            barrier.wait()
            try:
                results.append(tw.eng.request_session(db, o, u, m, org.agent, "phone", org.scn, None)[0].id)
            except TrainingError as e:
                results.append(e.code)
    threads = [threading.Thread(target=go, args=(e,)) for e in users for _ in range(n_each)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_concurrent_starts_cannot_exceed_org_limit(tw):
    a = tw.a
    emails = []
    for i in range(6):
        email = f"race{i}@alpha.in"
        who = a.invite(email, "trainee")
        verify_phone(a, who, email, f"97000000{i:02d}")
        emails.append(email)
        a.owner.post(f"{a.base}/teams/{a.team}/members", {"user_ids": [a.user_id(email)]})
    set_limits(tw, a, max_concurrent_sessions=2)
    out = _parallel_starts(tw, a, emails)
    assert sum(1 for x in out if x == "org_concurrency") == 4 and len([x for x in out if len(x) == 36]) == 2
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrainingUsageReservation.id)).where(
            TrainingUsageReservation.organization_id == a.id)) == 2


def test_concurrent_starts_by_one_user_reserve_one_slot(tw):
    out = _parallel_starts(tw, tw.a, ["t1@alpha.in"], n_each=5)
    assert len([x for x in out if len(x) == 36]) == 1 and out.count("user_concurrency") == 4


def test_platform_cap_applies_across_organizations(tw):
    tw.settings.training_max_concurrent_total = 1
    assert start(tw.a, tw.a.t1).status_code == 201
    r = start(tw.b, tw.b.t1)
    assert r.status_code == 429 and r.headers["x-error-code"] == "platform_busy"


# ---------- isolation ----------
def test_sessions_are_private_to_owner_viewers_and_org(tw):
    a, b = tw.a, tw.b
    sid = start(a, a.t1).json()["id"]
    assert a.t1.get(f"{a.base}/training/sessions/{sid}").status_code == 200
    assert a.t2.get(f"{a.base}/training/sessions/{sid}").status_code == 404
    assert a.trainer.get(f"{a.base}/training/sessions/{sid}").status_code == 200
    assert b.owner.get(f"{b.base}/training/sessions/{sid}").status_code == 404
    assert b.owner.get(f"{a.base}/training/sessions/{sid}").status_code == 404
    assert b.owner.post(f"{b.base}/training/sessions/{sid}/cancel").status_code == 404
    assert a.t1.get(f"{a.base}/training/sessions").status_code == 403
    listed = a.trainer.get(f"{a.base}/training/sessions?status=open").json()
    assert listed["total"] == 1 and listed["items"][0]["user_email"] == "t1@alpha.in"
    assert b.owner.get(f"{b.base}/training/sessions").json()["total"] == 0
    mine = a.t1.get(f"{a.base}/my/training/sessions").json()
    assert mine["total"] == 1 and a.t2.get(f"{a.base}/my/training/sessions").json()["total"] == 0


def test_availability_reflects_real_switches(tw):
    a = tw.a
    av = a.t1.get(f"{a.base}/training/availability").json()
    assert av["phone"]["available"] and av["phone"]["phone_verified"] and not av["browser"]["available"]
    assert "98765" not in str(av)


# ---------- browser ----------
def test_browser_flow_with_provider_double(tw):
    a = tw.a
    tw.settings.training_browser_enabled = True
    tw.eng.browser_provider = FakeBrowser()
    set_limits(tw, a, browser_enabled=True)
    s = start(a, a.t1, channel="browser").json()
    assert s["status"] == "requested" and tw.eng.sarvam.calls == []
    assert a.t2.post(f"{a.base}/training/browser/authorize", {"session_id": s["id"]}).status_code == 404
    g = a.t1.post(f"{a.base}/training/browser/authorize", {"session_id": s["id"]})
    assert g.status_code == 200 and g.json()["signed_url"].startswith("wss://")
    assert a.t1.post(f"{a.base}/training/browser/authorize", {"session_id": s["id"]}).status_code == 409
    with SessionLocal() as db:
        tok = db.scalars(select(BrowserSessionToken).where(BrowserSessionToken.session_id == s["id"])).one()
        assert "wss" not in tok.token_hash and len(tok.token_hash) == 64
    ev = f"{a.base}/training/sessions/{s['id']}/browser-events"
    assert a.t1.post(ev, {"event": "connected"}).json()["status"] == "active"
    done = a.t1.post(ev, {"event": "ended"}).json()
    assert done["status"] == "completed" and done["billable_seconds"] is not None
    assert a.t1.post(ev, {"event": "connected"}).json()["status"] == "completed"  # stale event changes nothing


def test_browser_authorize_rechecks_assignment_and_handles_mic_denial(tw):
    a = tw.a
    tw.settings.training_browser_enabled = True
    tw.eng.browser_provider = FakeBrowser()
    set_limits(tw, a, browser_enabled=True)
    sid = start(a, a.t1, channel="browser").json()["id"]
    aid = a.owner.get(f"{a.base}/assignments").json()["items"][0]["id"]
    a.owner.post(f"{a.base}/assignments/{aid}/revoke")
    assert a.t1.post(f"{a.base}/training/browser/authorize", {"session_id": sid}).status_code == 403
    assert row(sid).status == "failed"
    assign(a, a.owner, [a.agent], team_ids=[a.team])
    sid2 = start(a, a.t1, channel="browser").json()["id"]
    a.t1.post(f"{a.base}/training/browser/authorize", {"session_id": sid2})
    r = a.t1.post(f"{a.base}/training/sessions/{sid2}/browser-events", {"event": "microphone_denied"})
    assert r.json()["status"] == "failed" and r.json()["failure_code"] == "microphone_denied"


def test_browser_disabled_by_default(tw):
    a = tw.a
    assert start(a, a.t1, channel="browser").status_code == 503
    r = a.t1.post(f"{a.base}/training/browser/authorize", {"session_id": "x" * 36})
    assert r.status_code == 503


def test_training_secrets_not_logged(tw, caplog):
    a = tw.a
    sid = start(a, a.t1).json()["id"]
    with caplog.at_level("INFO"):
        result(tw, sid, a.id, attempt="att-1")
    text_ = caplog.text
    assert SECRET not in text_ and "9876" not in text_

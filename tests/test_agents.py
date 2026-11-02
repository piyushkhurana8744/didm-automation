"""Phase 2: agent registry, immutable versions, scenarios, team and user assignments, tenant isolation."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import SessionLocal, utcnow
from app.integrations import CallTarget, Sarvam
from app.saas.agents import NotEntitled, PublishedVersionImmutable, resolve_training_target
from app.saas.models import AgentAssignment, AgentVersion, AuditEvent
from tests.test_saas import saas  # noqa: F401  (fixture)

SCHEMA = [
    {"name": "student_name", "type": "string", "required": True, "max_length": 50},
    {"name": "course", "type": "enum", "options": ["MBA", "BBA"], "required": True},
    {"name": "budget", "type": "integer", "min": 0, "max": 500000},
    {"name": "tone", "type": "string", "default": "friendly"},
]


class Org:
    def __init__(self, w, slug):
        self.id, self.owner = w.make_org(slug, f"owner@{slug}.in")
        self.w = w
        self.base = f"/api/v1/organizations/{self.id}"

    def invite(self, email, role):
        return self.w.invite(self.owner, self.id, email, role)

    def user_id(self, email):
        return next(m["user"]["id"] for m in self.owner.get(f"{self.base}/members").json()
                    if m["user"]["email"] == email)


@pytest.fixture
def world(saas):
    a, b = Org(saas, "alpha"), Org(saas, "beta")
    a.trainer = a.invite("trainer@alpha.in", "trainer")
    a.trainee = a.invite("trainee@alpha.in", "trainee")
    a.trainee2 = a.invite("trainee2@alpha.in", "trainee")
    a.admin = a.invite("admin@alpha.in", "organization_admin")
    saas.a, saas.b = a, b
    return saas


def register(org, app_id="app-sales-1", **kw):
    body = {"name": kw.pop("name", "Admissions caller"), "provider_app_id": app_id,
            "channels": kw.pop("channels", ["phone", "browser"]), **kw}
    r = org.owner.post(f"{org.base}/agents", body)
    assert r.status_code == 201, r.text
    return r.json()


def publish_agent(org, app_id="app-sales-1", schema=SCHEMA, app_version=3, **kw):
    ag = register(org, app_id, **kw)
    draft = ag["draft_version"]["id"]
    r = org.owner.patch(f"{org.base}/agents/{ag['id']}/versions/{draft}",
                        {"provider_app_version": app_version, "variable_schema": schema,
                         "configuration_snapshot": {"language": "hi-IN"}})
    assert r.status_code == 200, r.text
    r = org.owner.post(f"{org.base}/agents/{ag['id']}/versions/{draft}/publish")
    assert r.status_code == 200, r.text
    return ag["id"], draft


def scenario(org, agent_id, actor=None, **kw):
    body = {"name": kw.pop("name", "Price objection"), "difficulty": "intermediate",
            "agent_variables": kw.pop("agent_variables", {"student_name": "Riya", "course": "MBA"}),
            "status": kw.pop("status", "active"), **kw}
    r = (actor or org.owner).post(f"{org.base}/agents/{agent_id}/scenarios", body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def assign(org, actor, agent_ids, user_ids=(), team_ids=(), **kw):
    return actor.post(f"{org.base}/assignments", {"agent_ids": list(agent_ids), "user_ids": list(user_ids),
                                                  "team_ids": list(team_ids), **kw})


# ---------- registry ----------
def test_admin_registers_multiple_agents_in_own_org(world):
    a = world.a
    one = register(a, "app-one", name="Caller A")
    two = register(a, "app-two", name="Caller B", category="admissions")
    assert one["draft_version"]["internal_version"] == 1 and one["published_version"] is None
    listed = a.owner.get(f"{a.base}/agents").json()
    assert listed["total"] == 2 and {x["name"] for x in listed["items"]} == {"Caller A", "Caller B"}
    assert a.owner.get(f"{a.base}/agents?category=admissions").json()["total"] == 1
    assert a.owner.get(f"{a.base}/agents?q=caller%20b").json()["items"][0]["id"] == two["id"]
    page = a.owner.get(f"{a.base}/agents?limit=1&offset=1").json()
    assert page["total"] == 2 and len(page["items"]) == 1
    assert world.b.owner.get(f"{world.b.base}/agents").json()["total"] == 0


def test_registration_validates_and_never_stores_credentials(world):
    a = world.a
    assert a.owner.post(f"{a.base}/agents", {"name": "x", "provider_app_id": "bad id!"}).status_code == 422
    assert a.owner.post(f"{a.base}/agents", {"name": "x", "provider_app_id": "ok", "channels": ["fax"]}).status_code == 422
    assert a.owner.post(f"{a.base}/agents", {"name": "x", "provider_app_id": "ok", "provider": "other"}).status_code == 422
    ag = register(a)
    r = a.owner.patch(f"{a.base}/agents/{ag['id']}/versions/{ag['draft_version']['id']}",
                      {"configuration_snapshot": {"nested": {"Sarvam_API_Key": "sk-123"}}})
    assert r.status_code == 422 and "credentials" in r.json()["detail"]


def test_same_provider_app_cannot_be_registered_by_another_org(world):
    register(world.a, "shared-app")
    r = world.b.owner.post(f"{world.b.base}/agents", {"name": "Copy", "provider_app_id": "shared-app"})
    assert r.status_code == 409 and "alpha" not in r.text.lower()


def test_trainer_and_trainee_cannot_manage_agents(world):
    a = world.a
    ag = register(a)
    for who in (a.trainer, a.trainee):
        assert who.post(f"{a.base}/agents", {"name": "x", "provider_app_id": "x1"}).status_code == 403
        assert who.patch(f"{a.base}/agents/{ag['id']}", {"name": "hacked"}).status_code == 403
        assert who.post(f"{a.base}/agents/{ag['id']}/versions/{ag['draft_version']['id']}/publish").status_code == 403
        assert who.post(f"{a.base}/agents/{ag['id']}/archive").status_code == 403
    assert a.trainer.get(f"{a.base}/agents").status_code == 200  # trainers can see the registry
    assert a.trainee.get(f"{a.base}/agents").status_code == 403  # trainees only see their own
    assert a.admin.patch(f"{a.base}/agents/{ag['id']}", {"name": "Renamed"}).status_code == 200


# ---------- versions ----------
def test_publish_requires_valid_configuration(world):
    a = world.a
    ag = register(a)
    vid = ag["draft_version"]["id"]
    check = a.owner.post(f"{a.base}/agents/{ag['id']}/versions/{vid}/validate").json()
    assert not check["ok"] and any("app version" in p for p in check["problems"])
    assert a.owner.post(f"{a.base}/agents/{ag['id']}/versions/{vid}/publish").status_code == 422
    bad = a.owner.patch(f"{a.base}/agents/{ag['id']}/versions/{vid}",
                        {"variable_schema": [{"name": "Bad Name", "type": "string"}]})
    assert bad.status_code == 422
    enum = a.owner.patch(f"{a.base}/agents/{ag['id']}/versions/{vid}",
                         {"variable_schema": [{"name": "c", "type": "enum"}]})
    assert enum.status_code == 422


def test_published_version_is_immutable_and_new_draft_copies_it(world):
    a = world.a
    agent_id, v1 = publish_agent(a)
    base = f"{a.base}/agents/{agent_id}/versions"
    assert a.owner.patch(f"{base}/{v1}", {"provider_app_version": 9}).status_code == 409
    assert a.owner.delete(f"{base}/{v1}").status_code == 409
    assert a.owner.post(f"{base}/{v1}/publish").status_code == 409
    d = a.owner.post(base, {}).json()
    assert d["internal_version"] == 2 and d["based_on_version_id"] == v1
    assert d["provider_app_version"] == 3 and d["variable_schema"] == SCHEMA
    assert a.owner.post(base, {}).status_code == 409  # one draft at a time
    assert a.owner.patch(f"{base}/{d['id']}", {"provider_app_version": 4}).json()["provider_app_version"] == 4
    assert a.owner.post(f"{base}/{d['id']}/publish").status_code == 200
    versions = a.owner.get(base).json()
    assert [v["internal_version"] for v in versions] == [2, 1]
    assert versions[0]["is_current"] and not versions[1]["is_current"]
    assert versions[1]["provider_app_version"] == 3  # the old pin is untouched
    assert a.owner.get(f"{a.base}/agents/{agent_id}").json()["published_version"]["provider_app_version"] == 4


def test_orm_guard_blocks_direct_writes_to_published_versions(world):
    agent_id, v1 = publish_agent(world.a)
    with SessionLocal() as db:
        v = db.get(AgentVersion, v1)
        v.provider_app_version = 99
        with pytest.raises(PublishedVersionImmutable):
            db.commit()
        db.rollback()
        with pytest.raises(PublishedVersionImmutable):
            db.delete(db.get(AgentVersion, v1))
            db.commit()
        db.rollback()
    with SessionLocal() as db:
        assert db.get(AgentVersion, v1).provider_app_version == 3


def test_provider_app_id_locks_after_first_publish(world):
    a = world.a
    ag = register(a, "first-app")
    assert a.owner.patch(f"{a.base}/agents/{ag['id']}", {"provider_app_id": "second-app"}).status_code == 200
    agent_id, _ = publish_agent(a, "third-app")
    r = a.owner.patch(f"{a.base}/agents/{agent_id}", {"provider_app_id": "other"})
    assert r.status_code == 409


def test_discard_draft_and_archive_keep_history(world):
    a = world.a
    agent_id, v1 = publish_agent(a)
    d = a.owner.post(f"{a.base}/agents/{agent_id}/versions", {}).json()
    assert a.owner.delete(f"{a.base}/agents/{agent_id}/versions/{d['id']}").status_code == 200
    assert a.owner.post(f"{a.base}/agents/{agent_id}/archive").json()["status"] == "archived"
    assert a.owner.post(f"{a.base}/agents/{agent_id}/versions", {}).status_code == 409
    assert [v["id"] for v in a.owner.get(f"{a.base}/agents/{agent_id}/versions").json()] == [v1]
    assert a.owner.get(f"{a.base}/agents?status=archived").json()["total"] == 1
    assert a.owner.post(f"{a.base}/agents/{agent_id}/restore").json()["status"] == "active"


# ---------- scenarios ----------
def test_scenario_variables_checked_against_schema(world):
    a = world.a
    agent_id, _ = publish_agent(a)
    url = f"{a.base}/agents/{agent_id}/scenarios"
    for bad in ({"student_name": "Riya", "course": "PhD"}, {"student_name": "Riya", "course": "MBA", "x": 1},
                {"student_name": "Riya", "course": "MBA", "budget": "lots"}, {"course": "MBA"}):
        r = a.owner.post(url, {"name": "s", "agent_variables": bad, "status": "active"})
        assert r.status_code == 422, bad
    # Drafts may leave required variables out; activating needs them
    sid = scenario(a, agent_id, status="draft", agent_variables={"course": "BBA"})
    assert a.owner.patch(f"{a.base}/scenarios/{sid}", {"status": "active"}).status_code == 422
    r = a.owner.patch(f"{a.base}/scenarios/{sid}", {"status": "active",
                                                    "agent_variables": {"course": "BBA", "student_name": "Aman"}})
    assert r.status_code == 200 and r.json()["status"] == "active"
    assert a.owner.patch(f"{a.base}/scenarios/{sid}", {"difficulty": "impossible"}).status_code == 422
    assert a.trainer.post(url, {"name": "by trainer", "agent_variables": {}, "status": "draft"}).status_code == 201
    assert a.trainee.post(url, {"name": "nope", "agent_variables": {}}).status_code == 403


def test_scenario_cannot_be_active_before_a_version_is_published(world):
    a = world.a
    ag = register(a)
    r = a.owner.post(f"{a.base}/agents/{ag['id']}/scenarios", {"name": "s", "status": "active"})
    assert r.status_code == 409
    assert a.owner.post(f"{a.base}/agents/{ag['id']}/scenarios", {"name": "s"}).status_code == 201


# ---------- assignments ----------
def test_trainee_sees_only_assigned_agents_and_allowed_scenarios(world):
    a = world.a
    ag1, _ = publish_agent(a, "app-1", name="Alpha One")
    ag2, _ = publish_agent(a, "app-2", name="Alpha Two")
    s1 = scenario(a, ag1, name="Easy")
    scenario(a, ag1, name="Hard")
    scenario(a, ag1, name="Draft one", status="draft")
    t1 = a.user_id("trainee@alpha.in")
    r = assign(a, a.owner, [ag1], [t1], settings={"allowed_scenario_ids": [s1], "max_sessions": 5})
    assert r.status_code == 201 and len(r.json()["created"]) == 1
    mine = a.trainee.get(f"{a.base}/my/agents").json()
    assert [m["name"] for m in mine] == ["Alpha One"]
    assert mine[0]["access"]["max_sessions"] == 5 and mine[0]["training_available"] is False
    assert "provider_app_id" not in str(mine)
    detail = a.trainee.get(f"{a.base}/my/agents/{ag1}").json()
    assert [s["name"] for s in detail["scenarios"]] == ["Easy"]
    assert a.trainee.get(f"{a.base}/my/agents/{ag2}").status_code == 404
    assert a.trainee2.get(f"{a.base}/my/agents").json() == []


def test_visibility_requires_published_active_in_tenant_and_ignores_session_limit(world):
    """One trainee sees every eligible agent; neither limits nor another tenant can collapse the list."""
    a, b = world.a, world.b
    first, _ = publish_agent(a, "visibility-1", name="Visible One")
    second, _ = publish_agent(a, "visibility-2", name="Visible Two")
    draft = register(a, "visibility-draft", name="Draft Hidden")
    expired, _ = publish_agent(a, "visibility-expired", name="Expired Hidden")
    foreign, _ = publish_agent(b, "visibility-foreign", name="Other Tenant")
    trainee = a.user_id("trainee@alpha.in")

    assert assign(a, a.owner, [first, second], [trainee],
                  settings={"max_sessions": 1}).status_code == 201
    # The write API must not create a misleading assignment for an unpublished agent.
    rejected = assign(a, a.owner, [draft["id"]], [trainee])
    assert rejected.status_code == 409
    assert "Publish every selected agent" in rejected.json()["detail"]

    # Seed historical/invalid rows directly to prove the read boundary remains fail-closed. This is
    # representative of assignments made before the write-side validation above existed.
    with SessionLocal() as db:
        db.add(AgentAssignment(organization_id=a.id, agent_id=draft["id"], user_id=trainee,
                               assigned_by=trainee, starts_at=utcnow(), settings={"max_sessions": 10}))
        db.add(AgentAssignment(organization_id=a.id, agent_id=expired, user_id=trainee,
                               assigned_by=trainee, starts_at=utcnow() - timedelta(days=2),
                               expires_at=utcnow() - timedelta(days=1), settings={}))
        # Even a malformed cross-tenant row must not expose the foreign agent through Org A.
        db.add(AgentAssignment(organization_id=a.id, agent_id=foreign, user_id=trainee,
                               assigned_by=trainee, starts_at=utcnow(), settings={}))
        db.commit()

    mine = a.trainee.get(f"{a.base}/my/agents")
    assert mine.status_code == 200
    assert [x["name"] for x in mine.json()] == ["Visible One", "Visible Two"]
    assert all(x["access"]["max_sessions"] == 1 for x in mine.json())


def test_revoked_and_expired_assignments_disappear(world):
    a = world.a
    ag, _ = publish_agent(a)
    t1 = a.user_id("trainee@alpha.in")
    aid = assign(a, a.owner, [ag], [t1]).json()["created"][0]["id"]
    assert len(a.trainee.get(f"{a.base}/my/agents").json()) == 1
    assert a.owner.post(f"{a.base}/assignments/{aid}/revoke").json()["state"] == "revoked"
    assert a.trainee.get(f"{a.base}/my/agents").json() == []
    assert a.trainee.get(f"{a.base}/my/assignments").json() == []
    # expiry
    aid = assign(a, a.owner, [ag], [t1]).json()["created"][0]["id"]
    with SessionLocal() as db:
        row = db.get(AgentAssignment, aid)
        row.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert a.trainee.get(f"{a.base}/my/agents").json() == []
    with SessionLocal() as db:
        with pytest.raises(NotEntitled):
            resolve_training_target(db, a.id, t1, ag, "phone")
    # Assigning again replaces the expired one instead of clashing with it
    again = assign(a, a.owner, [ag], [t1]).json()
    assert len(again["created"]) == 1
    hist = a.owner.get(f"{a.base}/assignments/{again['created'][0]['id']}").json()["history"]
    assert {h["state"] for h in hist} == {"active", "revoked", "replaced"}


def test_scheduled_assignment_not_usable_before_start(world):
    a = world.a
    ag, _ = publish_agent(a)
    t1 = a.user_id("trainee@alpha.in")
    start = (utcnow() + timedelta(days=1)).isoformat() + "Z"
    assert assign(a, a.owner, [ag], [t1], starts_at=start).json()["created"][0]["state"] == "scheduled"
    assert a.trainee.get(f"{a.base}/my/agents").json() == []
    assert assign(a, a.owner, [ag], [a.user_id("trainee2@alpha.in")],
                  expires_at=(utcnow() - timedelta(days=1)).isoformat() + "Z").status_code == 422


def test_duplicate_open_assignment_is_skipped(world):
    a = world.a
    ag, _ = publish_agent(a)
    t1 = a.user_id("trainee@alpha.in")
    assert len(assign(a, a.owner, [ag], [t1]).json()["created"]) == 1
    r = assign(a, a.owner, [ag], [t1]).json()
    assert r["created"] == [] and len(r["skipped"]) == 1


def test_team_assignment_and_overlap_rules(world):
    a = world.a
    ag, _ = publish_agent(a)
    s_easy, s_hard = scenario(a, ag, name="Easy"), scenario(a, ag, name="Hard")
    team = a.owner.post(f"{a.base}/teams", {"name": "Batch 1"}).json()
    t1, t2 = a.user_id("trainee@alpha.in"), a.user_id("trainee2@alpha.in")
    assert a.trainer.post(f"{a.base}/teams", {"name": "x"}).status_code == 403
    assert a.owner.post(f"{a.base}/teams/{team['id']}/members", {"user_ids": [t1, t2]}).status_code == 200
    assert assign(a, a.trainer, [ag], team_ids=[team["id"]],
                  settings={"allowed_scenario_ids": [s_hard], "max_sessions": 3}).status_code == 201
    e2 = a.trainee2.get(f"{a.base}/my/agents/{ag}").json()
    assert e2["access"]["source"] == "team" and [s["name"] for s in e2["scenarios"]] == ["Hard"]
    # A direct assignment wins over the team one
    assign(a, a.owner, [ag], [t1], settings={"allowed_scenario_ids": [s_easy]})
    e1 = a.trainee.get(f"{a.base}/my/agents/{ag}").json()
    assert e1["access"]["source"] == "direct" and [s["name"] for s in e1["scenarios"]] == ["Easy"]
    assert e1["access"]["max_sessions"] is None
    # Leaving the team ends team access
    assert a.owner.delete(f"{a.base}/teams/{team['id']}/members/{t2}").status_code == 200
    assert a.trainee2.get(f"{a.base}/my/agents").json() == []
    # Archiving the team ends it for everyone left in it
    assert len(a.trainee.get(f"{a.base}/my/assignments").json()) == 2
    a.owner.post(f"{a.base}/teams/{team['id']}/archive")
    assert len(a.trainee.get(f"{a.base}/my/assignments").json()) == 1


def test_trainer_cannot_exceed_permissions(world):
    a = world.a
    ag, _ = publish_agent(a)
    admin_id = a.user_id("admin@alpha.in")
    trainer_id = a.user_id("trainer@alpha.in")
    assert assign(a, a.trainer, [ag], [admin_id]).status_code == 403
    assert assign(a, a.trainer, [ag], [trainer_id]).status_code == 403
    aid = assign(a, a.owner, [ag], [admin_id]).json()["created"][0]["id"]
    assert a.trainer.post(f"{a.base}/assignments/{aid}/revoke").status_code == 403
    assert a.trainer.patch(f"{a.base}/assignments/{aid}", {"clear_expiry": True}).status_code == 403
    t1 = a.user_id("trainee@alpha.in")
    tid = assign(a, a.trainer, [ag], [t1]).json()["created"][0]["id"]
    assert a.trainer.post(f"{a.base}/assignments/{tid}/revoke").status_code == 200
    assert assign(a, a.trainee, [ag], [t1]).status_code == 403


def test_removed_member_loses_assignments(world):
    a = world.a
    ag, _ = publish_agent(a)
    t1 = a.user_id("trainee@alpha.in")
    assign(a, a.owner, [ag], [t1])
    mid = next(m["membership_id"] for m in a.owner.get(f"{a.base}/members").json() if m["user"]["id"] == t1)
    assert a.owner.delete(f"{a.base}/members/{mid}").status_code == 200
    assert a.trainee.get(f"{a.base}/my/agents").status_code == 404
    with SessionLocal() as db:
        row = db.scalars(select(AgentAssignment).where(AgentAssignment.user_id == t1)).one()
        assert row.revoke_reason == "member_removed"


# ---------- tenant isolation ----------
def test_org_a_cannot_reach_org_b_agents_or_assignments(world):
    a, b = world.a, world.b
    b_agent, b_v = publish_agent(b, "beta-app")
    b_scn = scenario(b, b_agent)
    b_team = b.owner.post(f"{b.base}/teams", {"name": "B team"}).json()["id"]
    b_trainee = b.invite("trainee@beta.in", "trainee")
    b_tid = b.user_id("trainee@beta.in")
    b_asg = assign(b, b.owner, [b_agent], [b_tid]).json()["created"][0]["id"]
    # Through Org A's own path, with B's ids
    for url in (f"/agents/{b_agent}", f"/agents/{b_agent}/versions", f"/agents/{b_agent}/versions/{b_v}",
                f"/agents/{b_agent}/scenarios", f"/scenarios/{b_scn}", f"/assignments/{b_asg}",
                f"/teams/{b_team}/members", f"/my/agents/{b_agent}"):
        assert a.owner.get(f"{a.base}{url}").status_code == 404, url
    assert a.owner.patch(f"{a.base}/agents/{b_agent}", {"name": "x"}).status_code == 404
    assert a.owner.post(f"{a.base}/agents/{b_agent}/archive").status_code == 404
    assert a.owner.patch(f"{a.base}/scenarios/{b_scn}", {"name": "x"}).status_code == 404
    assert a.owner.post(f"{a.base}/assignments/{b_asg}/revoke").status_code == 404
    assert a.owner.get(f"{a.base}/assignments?agent_id={b_agent}&state=all").json()["total"] == 0
    # Through Org B's path: not a member
    assert a.owner.get(f"{b.base}/agents").status_code == 404
    assert a.owner.get(f"{b.base}/assignments").status_code == 404
    # Bulk assignment mixing tenants fails whole, creating nothing
    a_agent, _ = publish_agent(a, "alpha-app")
    a_t1 = a.user_id("trainee@alpha.in")
    for body in ({"agent_ids": [a_agent, b_agent], "user_ids": [a_t1]},
                 {"agent_ids": [a_agent], "user_ids": [a_t1, b_tid]},
                 {"agent_ids": [a_agent], "team_ids": [b_team]},
                 {"agent_ids": [a_agent], "user_ids": [a_t1], "settings": {"allowed_scenario_ids": [b_scn]}}):
        assert a.owner.post(f"{a.base}/assignments", body).status_code == 404, body
    assert a.owner.get(f"{a.base}/assignments?state=all").json()["total"] == 0
    # Team membership cannot pull in another tenant's user
    a_team = a.owner.post(f"{a.base}/teams", {"name": "A team"}).json()["id"]
    assert a.owner.post(f"{a.base}/teams/{a_team}/members", {"user_ids": [b_tid]}).status_code == 404
    # B's trainee still sees B's agent, and nothing in A
    assert len(b_trainee.get(f"{b.base}/my/agents").json()) == 1
    assert b_trainee.get(f"{a.base}/my/agents").status_code == 404


def test_resolver_pins_exact_version_and_checks_channel(world):
    a = world.a
    ag, v1 = publish_agent(a, channels=["phone"])
    s1 = scenario(a, ag)
    t1 = a.user_id("trainee@alpha.in")
    assign(a, a.owner, [ag], [t1])
    with SessionLocal() as db:
        t = resolve_training_target(db, a.id, t1, ag, "phone", s1)
        assert (t.agent_version_id, t.provider_app_id, t.provider_app_version) == (v1, "app-sales-1", 3)
        assert t.agent_variables == {"tone": "friendly", "student_name": "Riya", "course": "MBA"}
        ct = t.call_target(world.settings)
        assert isinstance(ct, CallTarget) and ct.app_id == "app-sales-1" and ct.app_version == 3
        with pytest.raises(NotEntitled):
            resolve_training_target(db, a.id, t1, ag, "browser")
        with pytest.raises(NotEntitled):
            resolve_training_target(db, world.b.id, t1, ag, "phone")  # wrong org
        with pytest.raises(NotEntitled):
            resolve_training_target(db, a.id, a.user_id("trainee2@alpha.in"), ag, "phone")


def test_sensitive_changes_are_audited(world):
    a = world.a
    ag, _ = publish_agent(a)
    sid = scenario(a, ag)
    aid = assign(a, a.owner, [ag], [a.user_id("trainee@alpha.in")]).json()["created"][0]["id"]
    a.owner.post(f"{a.base}/assignments/{aid}/revoke")
    with SessionLocal() as db:
        actions = set(db.scalars(select(AuditEvent.action).where(AuditEvent.organization_id == a.id)))
    assert {"agent.registered", "agent_version.draft_updated", "agent_version.published", "scenario.created",
            "assignment.created", "assignment.revoked"} <= actions
    assert sid


def test_dialer_default_agent_unchanged(world):
    """No CallTarget: the outbound dialler still sends the agent from its settings."""
    sent = {}

    class Client:
        def request(self, method, url, json=None, headers=None, **kw):
            sent["body"] = json

            class R:
                status_code = 200
                text = ""

                def json(self):
                    return {"attempt_id": "x"}
            return R()
    s = world.settings
    s.sarvam_app_id, s.sarvam_app_version = "default-app", 7
    Sarvam(s, Client()).start_call("+911234567890", {}, {})
    assert sent["body"]["app_config"]["app_id"] == "default-app"
    assert sent["body"]["app_config"]["app_version"] == 7

"""Identity, RBAC, invitations and tenant isolation for the training SaaS API."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import SessionLocal
from app.main import create_app
from app.saas.cli import create_platform_admin
from app.saas.models import AuditEvent, AuthSession, Invitation, Membership, User
from app.saas.passwords import hash_password, verify_password
from app.service import Automation
from tests.conftest import fresh_db_url

PW = "correct horse battery"


class Mail:
    enabled = True

    def __init__(self):
        self.sent = []

    def send(self, subject, body):
        return self.send_to("alerts@example.in", subject, body)

    def send_to(self, to, subject, body):
        self.sent.append((to, subject, body))
        return True

    def token_for(self, to):
        body = [b for t, _, b in self.sent if t == to][-1]
        return re.search(r"#token=([\w-]+)", body).group(1)


class User_:
    """One browser: its own cookie jar, and the CSRF header on unsafe requests."""

    def __init__(self, app):
        self.c = TestClient(app)

    def _h(self):
        csrf = self.c.cookies.get("didm_csrf")
        return {"X-CSRF-Token": csrf} if csrf else {}

    def get(self, url, **kw):
        return self.c.get(url, **kw)

    def post(self, url, json=None, **kw):
        return self.c.post(url, json=json, headers={**self._h(), **kw.pop("headers", {})}, **kw)

    def patch(self, url, json=None):
        return self.c.patch(url, json=json, headers=self._h())

    def delete(self, url):
        return self.c.delete(url, headers=self._h())

    def login(self, email, pw=PW):
        return self.c.post("/api/v1/auth/login", json={"email": email, "password": pw})


@pytest.fixture
def saas(tmp_path):
    s = Settings()
    for k, v in dict(dry_run=True, database_url=fresh_db_url(tmp_path), admin_token="adm", webhook_secret="hook",
                     public_base_url="https://automation.example.in", cookie_secure=False).items():
        setattr(s, k, v)
    mail = Mail()
    auto = Automation(s, None, None, None, mail)
    app = create_app(s, automation=auto, start_scheduler=False)
    app.state.limiter.reset()
    create_platform_admin("root@platform.in", "Root", PW)

    class World:
        pass
    w = World()
    w.app, w.mail, w.settings = app, mail, s
    w.browser = lambda: User_(app)
    w.root = User_(app)
    assert w.root.login("root@platform.in").status_code == 200

    def make_org(slug, owner_email):
        r = w.root.post("/api/v1/platform/organizations", {"name": slug.title(), "slug": slug, "owner_email": owner_email})
        assert r.status_code == 201, r.text
        owner = User_(app)
        token = mail.token_for(owner_email)
        assert owner.post("/api/v1/invitations/accept", {"token": token, "name": "Owner", "password": PW}).status_code == 200
        return r.json()["organization"]["id"], owner

    def invite(actor, org_id, email, role, password=PW):
        r = actor.post(f"/api/v1/organizations/{org_id}/invitations", {"email": email, "role": role})
        assert r.status_code == 201, r.text
        u = User_(app)
        acc = u.post("/api/v1/invitations/accept", {"token": mail.token_for(email), "name": email, "password": password})
        assert acc.status_code == 200, acc.text
        return u
    w.make_org, w.invite = make_org, invite
    return w


def member_id(actor, org_id, email):
    return next(m["membership_id"] for m in actor.get(f"/api/v1/organizations/{org_id}/members").json()
                if m["user"]["email"] == email)


# ---------- authentication ----------
def test_password_hash_roundtrip_and_salted():
    h1, h2 = hash_password(PW), hash_password(PW)
    assert h1 != h2 and h1.startswith("scrypt$")
    assert verify_password(PW, h1) and not verify_password("wrong password!", h1)
    assert not verify_password(PW, None) and not verify_password(PW, "garbage")


def test_login_sets_httponly_cookie_and_me_works(saas):
    b = saas.browser()
    r = b.login("root@platform.in")
    assert r.status_code == 200
    cookies = r.headers.get_list("set-cookie")
    sess = next(c for c in cookies if c.startswith("didm_session="))
    assert "HttpOnly" in sess and "SameSite=lax" in sess
    assert "HttpOnly" not in next(c for c in cookies if c.startswith("didm_csrf="))
    me = b.get("/api/v1/auth/me").json()
    assert me["user"]["email"] == "root@platform.in" and me["user"]["is_platform_admin"]
    assert "password_hash" not in str(me)


def test_wrong_password_and_unknown_email_give_same_answer(saas):
    b = saas.browser()
    a = b.login("root@platform.in", "wrong password!!")
    c = b.login("nobody@x.in", "wrong password!!")
    assert a.status_code == c.status_code == 401 and a.json() == c.json()
    with SessionLocal() as db:
        assert db.scalars(select(AuditEvent).where(AuditEvent.action == "auth.login_failed")).first()


def test_login_rate_limited(saas):
    b = saas.browser()
    codes = [b.login("root@platform.in", "wrong password!!").status_code for _ in range(6)]
    assert codes[:5] == [401] * 5 and codes[5] == 429
    assert b.login("root@platform.in").status_code == 429  # still blocked inside the window


def test_unauthenticated_requests_rejected(saas):
    b = saas.browser()
    assert b.get("/api/v1/auth/me").status_code == 401
    assert b.get("/api/v1/organizations").status_code == 401


def test_csrf_required_for_cookie_writes(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    r = owner.c.patch(f"/api/v1/organizations/{org_id}", json={"name": "Hacked"})  # no CSRF header
    assert r.status_code == 403
    r = owner.c.patch(f"/api/v1/organizations/{org_id}", json={"name": "Hacked"}, headers={"X-CSRF-Token": "forged"})
    assert r.status_code == 403
    assert owner.patch(f"/api/v1/organizations/{org_id}", {"name": "Acme Ltd"}).json()["name"] == "Acme Ltd"


def test_owner_dashboard_uses_tenant_scoped_real_counts(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    other_id, other = saas.make_org("other", "owner@other.in")
    saas.invite(owner, org_id, "trainee@acme.in", "trainee")
    saas.invite(other, other_id, "trainee@other.in", "trainee")
    pending = owner.post(f"/api/v1/organizations/{org_id}/invitations",
                         {"email": "pending@acme.in", "role": "trainee"})
    assert pending.status_code == 201

    data = owner.get(f"/api/v1/organizations/{org_id}/dashboard").json()
    assert data["total_trainees"] == data["active_trainees"] == 1
    assert data["pending_invitations"] == 1
    assert data["active_agents"] == data["assigned_trainees"] == data["training_sessions"] == 0
    assert data["average_score"] is None
    assert data["recent_activity"]
    assert other.get(f"/api/v1/organizations/{org_id}/dashboard").status_code == 404


def test_logout_revokes_session(saas):
    b = saas.browser()
    b.login("root@platform.in")
    cookie = b.c.cookies.get("didm_session")
    assert b.post("/api/v1/auth/logout").status_code == 200
    stolen = TestClient(saas.app)
    stolen.cookies.set("didm_session", cookie)
    assert stolen.get("/api/v1/auth/me").status_code == 401


def test_password_reset_flow(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    b = saas.browser()
    unknown = b.post("/api/v1/auth/password/forgot", {"email": "ghost@acme.in"})
    known = b.post("/api/v1/auth/password/forgot", {"email": "owner@acme.in"})
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    token = saas.mail.token_for("owner@acme.in")
    assert b.post("/api/v1/auth/password/reset", {"token": token, "new_password": "short"}).status_code == 422
    assert b.post("/api/v1/auth/password/reset", {"token": token, "new_password": "a brand new secret"}).status_code == 200
    assert b.post("/api/v1/auth/password/reset", {"token": token, "new_password": "another new secret"}).status_code == 400
    assert owner.get("/api/v1/auth/me").status_code == 401  # reset logs out every session
    assert saas.browser().login("owner@acme.in", "a brand new secret").status_code == 200
    with SessionLocal() as db:  # only the hash of the reset secret is stored
        assert token not in str(db.execute(select(AuthSession.token_hash)).all())


def test_password_change_keeps_this_session_only(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    other = saas.browser()
    other.login("owner@acme.in")
    assert owner.post("/api/v1/auth/password/change", {"current_password": "nope nope nope",
                                                       "new_password": "a brand new secret"}).status_code == 400
    assert owner.post("/api/v1/auth/password/change", {"current_password": PW,
                                                       "new_password": "a brand new secret"}).status_code == 200
    assert owner.get("/api/v1/auth/me").status_code == 200
    assert other.get("/api/v1/auth/me").status_code == 401


# ---------- organizations and platform admin ----------
def test_only_platform_admin_creates_organizations(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    r = owner.post("/api/v1/platform/organizations", {"name": "X", "slug": "x", "owner_email": "a@x.in"})
    assert r.status_code == 403
    assert saas.root.post("/api/v1/platform/organizations",
                          {"name": "Dup", "slug": "acme", "owner_email": "a@x.in"}).status_code == 409
    assert saas.root.post("/api/v1/platform/organizations",
                          {"name": "Bad", "slug": "Bad Slug!", "owner_email": "a@x.in"}).status_code == 422


def test_platform_admin_has_no_tenant_access_without_membership(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    assert saas.root.get(f"/api/v1/organizations/{org_id}").status_code == 404
    assert saas.root.get(f"/api/v1/organizations/{org_id}/members").status_code == 404


def test_suspended_organization_blocks_members(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    assert saas.root.patch(f"/api/v1/platform/organizations/{org_id}", {"status": "suspended"}).status_code == 200
    assert owner.get(f"/api/v1/organizations/{org_id}").status_code == 403
    saas.root.patch(f"/api/v1/platform/organizations/{org_id}", {"status": "active"})
    assert owner.get(f"/api/v1/organizations/{org_id}").status_code == 200


def test_user_in_two_organizations_has_role_per_org(saas):
    a_id, a_owner = saas.make_org("acme", "owner@acme.in")
    b_id, b_owner = saas.make_org("beta", "owner@beta.in")
    u = saas.invite(a_owner, a_id, "sam@x.in", "organization_admin")
    r = b_owner.post(f"/api/v1/organizations/{b_id}/invitations", {"email": "sam@x.in", "role": "trainee"})
    token = saas.mail.token_for("sam@x.in")
    assert u.post("/api/v1/invitations/accept", {"token": token}).status_code == 200  # logged in as sam
    me = u.get("/api/v1/auth/me").json()
    assert {m["organization"]["slug"]: m["role"] for m in me["memberships"]} == {
        "acme": "organization_admin", "beta": "trainee"}
    assert u.get(f"/api/v1/organizations/{a_id}/invitations").status_code == 200
    assert u.get(f"/api/v1/organizations/{b_id}/invitations").status_code == 403  # trainee there
    assert u.post("/api/v1/auth/active-organization", {"organization_id": b_id}).status_code == 200
    assert r.status_code == 201


# ---------- RBAC ----------
def test_trainee_cannot_use_admin_endpoints(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    t = saas.invite(owner, org_id, "tina@acme.in", "trainee")
    assert t.get(f"/api/v1/organizations/{org_id}").status_code == 200
    assert t.get(f"/api/v1/organizations/{org_id}/members").status_code == 403
    assert t.get(f"/api/v1/organizations/{org_id}/invitations").status_code == 403
    assert t.post(f"/api/v1/organizations/{org_id}/invitations", {"email": "z@acme.in", "role": "trainee"}).status_code == 403
    assert t.patch(f"/api/v1/organizations/{org_id}", {"name": "x"}).status_code == 403
    assert t.get(f"/api/v1/organizations/{org_id}/audit-events").status_code == 403
    assert t.get("/api/v1/platform/organizations").status_code == 403


def test_trainer_can_view_members_but_not_manage(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    tr = saas.invite(owner, org_id, "tom@acme.in", "trainer")
    saas.invite(owner, org_id, "tina@acme.in", "trainee")
    assert tr.get(f"/api/v1/organizations/{org_id}/members").status_code == 200
    mid = member_id(owner, org_id, "tina@acme.in")
    assert tr.patch(f"/api/v1/organizations/{org_id}/members/{mid}", {"role": "trainer"}).status_code == 403


def test_admin_cannot_grant_or_touch_owner(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    adm = saas.invite(owner, org_id, "ann@acme.in", "organization_admin")
    assert adm.post(f"/api/v1/organizations/{org_id}/invitations",
                    {"email": "boss@acme.in", "role": "organization_owner"}).status_code == 403
    owner_mid = member_id(owner, org_id, "owner@acme.in")
    assert adm.patch(f"/api/v1/organizations/{org_id}/members/{owner_mid}", {"role": "trainee"}).status_code == 403
    assert adm.delete(f"/api/v1/organizations/{org_id}/members/{owner_mid}").status_code == 403
    saas.invite(adm, org_id, "tina@acme.in", "trainee")
    mid = member_id(adm, org_id, "tina@acme.in")
    assert adm.patch(f"/api/v1/organizations/{org_id}/members/{mid}", {"role": "trainer"}).json()["role"] == "trainer"
    assert adm.patch(f"/api/v1/organizations/{org_id}/members/{mid}", {"role": "superuser"}).status_code == 422


def test_cannot_change_own_role_or_remove_last_owner(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    me = member_id(owner, org_id, "owner@acme.in")
    assert owner.patch(f"/api/v1/organizations/{org_id}/members/{me}", {"role": "trainee"}).status_code == 403
    assert owner.delete(f"/api/v1/organizations/{org_id}/members/{me}").status_code == 403
    second = saas.invite(owner, org_id, "co@acme.in", "organization_owner")
    first_mid = member_id(owner, org_id, "owner@acme.in")
    assert second.delete(f"/api/v1/organizations/{org_id}/members/{first_mid}").status_code == 200
    second_mid = member_id(second, org_id, "co@acme.in")
    # second is now the only owner and cannot demote themself
    assert second.patch(f"/api/v1/organizations/{org_id}/members/{second_mid}", {"role": "trainee"}).status_code == 403


def test_revoked_membership_loses_access_immediately(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    t = saas.invite(owner, org_id, "tina@acme.in", "trainee")
    assert t.get(f"/api/v1/organizations/{org_id}").status_code == 200
    mid = member_id(owner, org_id, "tina@acme.in")
    assert owner.delete(f"/api/v1/organizations/{org_id}/members/{mid}").status_code == 200
    assert t.get(f"/api/v1/organizations/{org_id}").status_code == 404
    assert all(m["organization"]["id"] != org_id for m in t.get("/api/v1/auth/me").json()["memberships"])
    assert t.post("/api/v1/auth/active-organization", {"organization_id": org_id}).status_code == 404


# ---------- invitations ----------
def test_invitation_lifecycle(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    r = owner.post(f"/api/v1/organizations/{org_id}/invitations", {"email": " Tina@Acme.in ", "role": "trainee"})
    assert r.status_code == 201 and r.json()["email"] == "tina@acme.in" and r.json()["emailed"]
    first = saas.mail.token_for("tina@acme.in")
    assert r.json()["accept_url"].endswith(f"/app/invite/accept/#token={first}")
    # inviting again re-issues the same invitation with a new link; the old link stops working
    again = owner.post(f"/api/v1/organizations/{org_id}/invitations", {"email": "tina@acme.in", "role": "trainer"})
    assert again.json()["id"] == r.json()["id"] and again.json()["role"] == "trainer"
    second = saas.mail.token_for("tina@acme.in")
    b = saas.browser()
    assert b.post("/api/v1/invitations/lookup", {"token": first}).status_code == 400
    look = b.post("/api/v1/invitations/lookup", {"token": second}).json()
    assert look == {**look, "email": "tina@acme.in", "role": "trainer", "has_account": False}
    assert b.post("/api/v1/invitations/accept", {"token": second, "name": "Tina", "password": "short"}).status_code == 422
    assert b.post("/api/v1/invitations/accept", {"token": second, "name": "Tina", "password": PW}).status_code == 200
    assert b.get("/api/v1/auth/me").json()["active_organization_id"] == org_id
    assert saas.browser().post("/api/v1/invitations/accept", {"token": second, "name": "X", "password": PW}).status_code == 400
    assert owner.post(f"/api/v1/organizations/{org_id}/invitations",
                      {"email": "tina@acme.in", "role": "trainee"}).status_code == 409  # already a member
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == "tina@acme.in")).one()
        assert u.email_verified_at is not None
        assert second not in str(db.execute(select(Invitation.token_hash)).all())


def test_revoked_and_expired_invitations_cannot_be_used(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    inv = owner.post(f"/api/v1/organizations/{org_id}/invitations", {"email": "a@acme.in", "role": "trainee"}).json()
    tok = saas.mail.token_for("a@acme.in")
    assert owner.post(f"/api/v1/organizations/{org_id}/invitations/{inv['id']}/revoke").json()["status"] == "revoked"
    assert saas.browser().post("/api/v1/invitations/accept", {"token": tok, "name": "A", "password": PW}).status_code == 400
    owner.post(f"/api/v1/organizations/{org_id}/invitations", {"email": "b@acme.in", "role": "trainee"})
    tok_b = saas.mail.token_for("b@acme.in")
    from datetime import timedelta
    from app.db import utcnow
    with SessionLocal() as db:
        i = db.scalars(select(Invitation).where(Invitation.email == "b@acme.in")).one()
        i.expires_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert saas.browser().post("/api/v1/invitations/accept", {"token": tok_b, "name": "B", "password": PW}).status_code == 400
    listed = {i["email"]: i["status"] for i in owner.get(f"/api/v1/organizations/{org_id}/invitations").json()}
    assert listed["b@acme.in"] == "expired" and listed["a@acme.in"] == "revoked"


def test_existing_account_must_log_in_to_accept(saas):
    a_id, a_owner = saas.make_org("acme", "owner@acme.in")
    b_id, b_owner = saas.make_org("beta", "owner@beta.in")
    b_owner.post(f"/api/v1/organizations/{b_id}/invitations", {"email": "owner@acme.in", "role": "trainer"})
    tok = saas.mail.token_for("owner@acme.in")
    anon = saas.browser()
    assert anon.post("/api/v1/invitations/accept", {"token": tok, "name": "X", "password": PW}).status_code == 401
    wrong = saas.browser()
    wrong.login("owner@beta.in")
    assert wrong.post("/api/v1/invitations/accept", {"token": tok}).status_code == 401
    assert a_owner.c.post("/api/v1/invitations/accept", json={"token": tok}).status_code == 403  # no CSRF header
    assert a_owner.post("/api/v1/invitations/accept", {"token": tok}).status_code == 200
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == "owner@acme.in")).one()
        assert verify_password(PW, u.password_hash)  # the invite did not change the password


def test_invitation_secret_not_logged(saas, caplog):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    caplog.set_level("DEBUG")
    owner.post(f"/api/v1/organizations/{org_id}/invitations", {"email": "a@acme.in", "role": "trainee"})
    tok = saas.mail.token_for("a@acme.in")
    assert tok not in caplog.text


# ---------- tenant isolation (IDOR) ----------
def test_company_a_cannot_reach_company_b(saas):
    a_id, a_owner = saas.make_org("acme", "owner@acme.in")
    b_id, b_owner = saas.make_org("beta", "owner@beta.in")
    saas.invite(b_owner, b_id, "bob@beta.in", "trainee")
    b_inv = b_owner.post(f"/api/v1/organizations/{b_id}/invitations", {"email": "x@beta.in", "role": "trainee"}).json()
    b_mid = member_id(b_owner, b_id, "bob@beta.in")
    # B's organization, users, invitations and audit log are invisible to A's owner
    for url in (f"/api/v1/organizations/{b_id}", f"/api/v1/organizations/{b_id}/members",
                f"/api/v1/organizations/{b_id}/invitations", f"/api/v1/organizations/{b_id}/audit-events"):
        assert a_owner.get(url).status_code == 404, url
    assert a_owner.patch(f"/api/v1/organizations/{b_id}", {"name": "pwned"}).status_code == 404
    # B's ids used inside A's own path are rejected too (the row must belong to the path's org)
    assert a_owner.patch(f"/api/v1/organizations/{a_id}/members/{b_mid}", {"role": "trainer"}).status_code == 404
    assert a_owner.delete(f"/api/v1/organizations/{a_id}/members/{b_mid}").status_code == 404
    assert a_owner.post(f"/api/v1/organizations/{a_id}/invitations/{b_inv['id']}/revoke").status_code == 404
    assert a_owner.post("/api/v1/auth/active-organization", {"organization_id": b_id}).status_code == 404
    # and nothing changed in B
    assert b_owner.get(f"/api/v1/organizations/{b_id}").json()["name"] == "Beta"
    assert any(m["user"]["email"] == "bob@beta.in" and m["role"] == "trainee"
               for m in b_owner.get(f"/api/v1/organizations/{b_id}/members").json())
    assert [o["slug"] for o in a_owner.get("/api/v1/organizations").json()] == ["acme"]


def test_unknown_and_foreign_org_ids_answer_the_same(saas):
    a_id, a_owner = saas.make_org("acme", "owner@acme.in")
    b_id, _ = saas.make_org("beta", "owner@beta.in")
    foreign = a_owner.get(f"/api/v1/organizations/{b_id}")
    unknown = a_owner.get("/api/v1/organizations/00000000-0000-0000-0000-000000000000")
    assert foreign.status_code == unknown.status_code == 404 and foreign.json() == unknown.json()


def test_audit_trail_records_admin_actions(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    saas.invite(owner, org_id, "t@acme.in", "trainee")
    actions = [a["action"] for a in owner.get(f"/api/v1/organizations/{org_id}/audit-events").json()]
    assert {"org.created", "invitation.created", "invitation.accepted"} <= set(actions)
    assert all("token" not in str(a["details"]) for a in owner.get(f"/api/v1/organizations/{org_id}/audit-events").json())


def test_security_headers_on_api(saas):
    r = saas.root.get("/api/v1/auth/me")
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"


def test_cli_promotes_existing_user(saas):
    org_id, owner = saas.make_org("acme", "owner@acme.in")
    create_platform_admin("owner@acme.in", "Owner", "an entirely new password")
    with SessionLocal() as db:
        u = db.scalars(select(User).where(User.email == "owner@acme.in")).one()
        assert u.is_platform_admin
    with pytest.raises(ValueError):
        create_platform_admin("x@y.in", "X", "short")
    with SessionLocal() as db:
        assert db.scalars(select(Membership)).first() is not None

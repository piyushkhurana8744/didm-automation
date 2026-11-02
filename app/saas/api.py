"""HTTP API for the training SaaS, served under /api/v1, plus the built web app under /app."""
import hmac
import logging
import re
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from .auth import (Auth, OrgContext, audit, clear_cookies, current_auth, get_db, ip_of, org_access, platform_admin,
                   revoke_user_sessions, scoped_get, settings_of, start_session)
from .models import (Agent, AgentAssignment, AuditEvent, Invitation, Membership, Organization, PasswordResetToken,
                     TeamMember, TrainingEvaluation, TrainingSession, User)
from .passwords import dummy_verify, hash_password, new_token, password_problem, token_hash, verify_password
from .permissions import OWNER, ROLES, can_grant, can_manage_member, permissions_for

log = logging.getLogger("didm.saas")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?$")


def norm_email(email: str) -> str:
    e = (email or "").strip().lower()
    if len(e) > 320 or not EMAIL_RE.match(e):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    return e


def check_password(pw: str):
    problem = password_problem(pw)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


# ---------- response shapes ----------
def org_out(o: Organization) -> dict:
    return {"id": o.id, "name": o.name, "slug": o.slug, "status": o.status, "settings": o.settings or {},
            "created_at": o.created_at.isoformat()}


def user_out(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "status": u.status,
            "is_platform_admin": bool(u.is_platform_admin)}


def member_out(m: Membership, u: User) -> dict:
    return {"membership_id": m.id, "user": user_out(u), "role": m.role, "status": m.status,
            "joined_at": m.created_at.isoformat()}


def invitation_out(i: Invitation, now) -> dict:
    status = "expired" if i.status == "pending" and i.expires_at <= now else i.status
    return {"id": i.id, "email": i.email, "role": i.role, "status": status,
            "expires_at": i.expires_at.isoformat(), "created_at": i.created_at.isoformat()}


# ---------- request bodies ----------
class LoginIn(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=256)


class ActiveOrgIn(BaseModel):
    organization_id: str = Field(max_length=36)


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: str = Field(max_length=256)


class ForgotIn(BaseModel):
    email: str = Field(max_length=320)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    new_password: str = Field(max_length=256)


class OrgUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict | None = None


class RoleIn(BaseModel):
    role: str


class InviteIn(BaseModel):
    email: str = Field(max_length=320)
    role: str


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class AcceptIn(BaseModel):
    token: str = Field(max_length=200)
    name: str | None = Field(default=None, max_length=200)
    password: str | None = Field(default=None, max_length=256)


class OrgCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str = Field(min_length=1, max_length=80)
    owner_email: str = Field(max_length=320)


class OrgStatusIn(BaseModel):
    status: str


def build_router(mailer, limiter) -> APIRouter:
    r = APIRouter(prefix="/api/v1")

    def rate(request: Request, name: str, limit: int, window: int, extra: str = ""):
        limiter.check(f"{name}:{ip_of(request)}:{extra}", limit, window)

    def send_mail(subject: str, body: str, to: str) -> bool:
        """Sends to one address with the app's SMTP settings. Returns False (and logs) when email is off."""
        if not mailer.enabled:
            log.warning("email not configured; message to %s not sent: %s", to, subject)
            return False
        return mailer.send_to(to, subject, body)

    @r.get("/health")
    def health():
        return {"ok": True}

    # ---------- auth ----------
    @r.post("/auth/login")
    def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
        email = (body.email or "").strip().lower()
        rate(request, "login-ip", 30, 900)
        # Per account, only failed attempts count: 5 wrong passwords lock that email for 15 minutes
        fail_key = f"login-fail:{email}"
        if limiter.over(fail_key, 5, 900):
            raise HTTPException(status_code=429, detail="Too many attempts. Please wait and try again.",
                                headers={"Retry-After": "900"})
        user = db.scalars(select(User).where(User.email == email)).first()
        if user is None:
            dummy_verify(body.password)
            ok = False
        else:
            ok = verify_password(body.password, user.password_hash) and user.status == "active"
        if not ok:
            limiter.hit(fail_key, 5, 900)
            audit(db, request, "auth.login_failed", actor=user, details={"email": email[:320]})
            db.commit()
            raise HTTPException(status_code=401, detail="Email or password is wrong.")
        user.last_login_at = utcnow()
        sess = start_session(db, request, user, response)
        audit(db, request, "auth.login", actor=user)
        db.commit()
        return {"user": user_out(user), "active_organization_id": sess.active_organization_id}

    @r.post("/auth/logout")
    def logout(request: Request, response: Response, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        row = db.merge(auth.session)
        row.revoked_at = utcnow()
        audit(db, request, "auth.logout", actor=auth.user)
        db.commit()
        clear_cookies(request, response)
        return {"ok": True}

    @r.get("/auth/me")
    def me(auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        rows = db.execute(select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
                          .where(Membership.user_id == auth.user.id, Membership.status == "active")
                          .order_by(Organization.name)).all()
        memberships = [{"membership_id": m.id, "organization": org_out(o), "role": m.role,
                        "permissions": permissions_for(m.role) if o.status == "active" else []} for m, o in rows]
        active = auth.session.active_organization_id
        if active not in {o.id for _, o in rows if o.status == "active"}:
            active = None
        return {"user": user_out(auth.user), "memberships": memberships, "active_organization_id": active}

    @r.post("/auth/active-organization")
    def set_active_org(body: ActiveOrgIn, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        m = db.scalars(select(Membership).join(Organization, Organization.id == Membership.organization_id).where(
            Membership.user_id == auth.user.id, Membership.organization_id == body.organization_id,
            Membership.status == "active", Organization.status == "active")).first()
        if m is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        row = db.merge(auth.session)
        row.active_organization_id = m.organization_id
        db.commit()
        return {"active_organization_id": m.organization_id}

    @r.patch("/auth/me")
    def update_profile(body: ProfileIn, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        user = db.merge(auth.user)
        user.name = body.name.strip()
        db.commit()
        return {"user": user_out(user)}

    @r.post("/auth/password/change")
    def change_password(body: PasswordChangeIn, request: Request, auth: Auth = Depends(current_auth),
                        db: Session = Depends(get_db)):
        rate(request, "pw-change", 10, 900, auth.user.id)
        user = db.merge(auth.user)
        if not verify_password(body.current_password, user.password_hash):
            raise HTTPException(status_code=400, detail="Current password is wrong.")
        check_password(body.new_password)
        user.password_hash = hash_password(body.new_password)
        revoke_user_sessions(db, user.id, keep_session_id=auth.session.id)
        audit(db, request, "auth.password_changed", actor=user)
        db.commit()
        return {"ok": True}

    @r.post("/auth/password/forgot", status_code=202)
    def forgot_password(body: ForgotIn, request: Request, db: Session = Depends(get_db)):
        rate(request, "pw-forgot", 5, 3600)
        email = (body.email or "").strip().lower()
        user = db.scalars(select(User).where(User.email == email, User.status == "active")).first()
        if user is not None:
            rate(request, "pw-forgot-user", 3, 3600, user.id)
            token = new_token()
            s = settings_of(request)
            db.add(PasswordResetToken(user_id=user.id, token_hash=token_hash(token),
                                      expires_at=utcnow() + timedelta(minutes=s.password_reset_ttl_minutes)))
            audit(db, request, "auth.password_reset_requested", actor=user)
            db.commit()
            link = f"{s.app_url()}/reset-password/#token={token}"
            send_mail("Reset your DIDM password",
                      f"Open this link to choose a new password. It works once, for "
                      f"{s.password_reset_ttl_minutes} minutes:\n\n{link}\n\nIf you did not ask for this, ignore this email.",
                      user.email)
        # Same answer whether or not the email exists
        return {"ok": True, "message": "If that email has an account, a reset link is on its way."}

    @r.post("/auth/password/reset")
    def reset_password(body: ResetIn, request: Request, db: Session = Depends(get_db)):
        rate(request, "pw-reset", 10, 3600)
        row = db.scalars(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash(body.token))).first()
        if row is None or row.used_at is not None or row.expires_at <= utcnow():
            raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
        check_password(body.new_password)
        user = db.get(User, row.user_id)
        if user is None or user.status != "active":
            raise HTTPException(status_code=400, detail="This reset link is invalid or has expired.")
        user.password_hash = hash_password(body.new_password)
        row.used_at = utcnow()
        revoke_user_sessions(db, user.id)
        audit(db, request, "auth.password_reset", actor=user)
        db.commit()
        return {"ok": True}

    # ---------- my organizations ----------
    @r.get("/organizations")
    def my_organizations(auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        rows = db.execute(select(Membership, Organization).join(Organization, Organization.id == Membership.organization_id)
                          .where(Membership.user_id == auth.user.id, Membership.status == "active")
                          .order_by(Organization.name)).all()
        return [{**org_out(o), "role": m.role} for m, o in rows]

    @r.get("/organizations/{org_id}")
    def get_organization(ctx: OrgContext = Depends(org_access("org.view")), db: Session = Depends(get_db)):
        members = db.scalar(select(func.count(Membership.id)).where(
            Membership.organization_id == ctx.org.id, Membership.status == "active")) or 0
        pending = db.scalar(select(func.count(Invitation.id)).where(
            Invitation.organization_id == ctx.org.id, Invitation.status == "pending",
            Invitation.expires_at > utcnow())) or 0
        return {**org_out(ctx.org), "role": ctx.role, "permissions": permissions_for(ctx.role),
                "active_members": members, "pending_invitations": pending}

    @r.get("/organizations/{org_id}/dashboard")
    def organization_dashboard(ctx: OrgContext = Depends(org_access("org.view")),
                               db: Session = Depends(get_db)):
        """Small, tenant-scoped aggregates for the owner dashboard.

        Keep this separate from the organization response so ordinary navigation does not run the
        heavier training queries. Every query is explicitly constrained to the active organization.
        """
        org_id = ctx.org.id
        now = utcnow()
        trainees = db.scalar(select(func.count(Membership.id)).where(
            Membership.organization_id == org_id, Membership.status == "active",
            Membership.role == "trainee")) or 0
        agents = db.scalar(select(func.count(Agent.id)).where(
            Agent.organization_id == org_id, Agent.status == "active")) or 0
        sessions = db.scalar(select(func.count(TrainingSession.id)).where(
            TrainingSession.organization_id == org_id)) or 0
        average_score = db.scalar(select(func.avg(TrainingEvaluation.overall_score)).where(
            TrainingEvaluation.organization_id == org_id, TrainingEvaluation.status == "completed"))
        pending = db.scalar(select(func.count(Invitation.id)).where(
            Invitation.organization_id == org_id, Invitation.status == "pending",
            Invitation.expires_at > now)) or 0

        direct = set(db.scalars(select(AgentAssignment.user_id).where(
            AgentAssignment.organization_id == org_id, AgentAssignment.user_id.is_not(None),
            AgentAssignment.revoked_at.is_(None), AgentAssignment.starts_at <= now,
            (AgentAssignment.expires_at.is_(None) | (AgentAssignment.expires_at > now)))).all())
        via_team = set(db.scalars(select(TeamMember.user_id).join(
            AgentAssignment, AgentAssignment.team_id == TeamMember.team_id).where(
            AgentAssignment.organization_id == org_id, TeamMember.removed_at.is_(None),
            AgentAssignment.revoked_at.is_(None), AgentAssignment.starts_at <= now,
            (AgentAssignment.expires_at.is_(None) | (AgentAssignment.expires_at > now)))).all())
        trainee_ids = set(db.scalars(select(Membership.user_id).where(
            Membership.organization_id == org_id, Membership.status == "active",
            Membership.role == "trainee")).all())

        recent = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == org_id)
                            .order_by(AuditEvent.created_at.desc()).limit(8)).all()
        return {
            "total_trainees": trainees,
            "active_trainees": trainees,
            "active_agents": agents,
            "assigned_trainees": len((direct | via_team) & trainee_ids),
            "training_sessions": sessions,
            "average_score": round(float(average_score), 1) if average_score is not None else None,
            "pending_invitations": pending,
            "recent_activity": [{"id": str(e.id), "action": e.action,
                                 "target_type": e.target_type, "created_at": e.created_at.isoformat()}
                                for e in recent],
        }

    @r.patch("/organizations/{org_id}")
    def update_organization(body: OrgUpdateIn, request: Request, ctx: OrgContext = Depends(org_access("org.update")),
                            db: Session = Depends(get_db)):
        org = db.merge(ctx.org)
        changed = {}
        if body.name is not None:
            org.name = body.name.strip()
            changed["name"] = org.name
        if body.settings is not None:
            if len(str(body.settings)) > 10000:
                raise HTTPException(status_code=422, detail="Settings are too large.")
            org.settings = body.settings
            changed["settings"] = True
        audit(db, request, "org.updated", actor=ctx.user, organization_id=org.id, target_type="organization",
              target_id=org.id, details=changed)
        db.commit()
        return org_out(org)

    # ---------- members ----------
    @r.get("/organizations/{org_id}/members")
    def list_members(ctx: OrgContext = Depends(org_access("members.view")), db: Session = Depends(get_db)):
        rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id)
                          .where(Membership.organization_id == ctx.org.id, Membership.status == "active")
                          .order_by(User.email)).all()
        return [member_out(m, u) for m, u in rows]

    def _active_owner_count(db: Session, org_id: str) -> int:
        return db.scalar(select(func.count(Membership.id)).where(
            Membership.organization_id == org_id, Membership.role == OWNER, Membership.status == "active")) or 0

    @r.patch("/organizations/{org_id}/members/{membership_id}")
    def change_role(membership_id: str, body: RoleIn, request: Request,
                    ctx: OrgContext = Depends(org_access("members.manage")), db: Session = Depends(get_db)):
        m = scoped_get(db, Membership, ctx.org.id, membership_id)
        if m.status != "active":
            raise HTTPException(status_code=404, detail="Not found.")
        if body.role not in ROLES:
            raise HTTPException(status_code=422, detail="Unknown role.")
        if m.user_id == ctx.user.id:
            raise HTTPException(status_code=403, detail="You cannot change your own role.")
        if not can_manage_member(ctx.role, m.role) or not can_grant(ctx.role, body.role):
            raise HTTPException(status_code=403, detail="Your role does not allow this change.")
        if m.role == OWNER and body.role != OWNER and _active_owner_count(db, ctx.org.id) <= 1:
            raise HTTPException(status_code=409, detail="An organization needs at least one owner.")
        old = m.role
        m.role = body.role
        audit(db, request, "member.role_changed", actor=ctx.user, organization_id=ctx.org.id,
              target_type="membership", target_id=m.id, details={"from": old, "to": body.role})
        db.commit()
        return member_out(m, db.get(User, m.user_id))

    @r.delete("/organizations/{org_id}/members/{membership_id}")
    def remove_member(membership_id: str, request: Request, ctx: OrgContext = Depends(org_access("members.manage")),
                      db: Session = Depends(get_db)):
        m = scoped_get(db, Membership, ctx.org.id, membership_id)
        if m.status != "active":
            raise HTTPException(status_code=404, detail="Not found.")
        if m.user_id == ctx.user.id:
            raise HTTPException(status_code=403, detail="You cannot remove yourself.")
        if not can_manage_member(ctx.role, m.role):
            raise HTTPException(status_code=403, detail="Your role does not allow this change.")
        if m.role == OWNER and _active_owner_count(db, ctx.org.id) <= 1:
            raise HTTPException(status_code=409, detail="An organization needs at least one owner.")
        m.status = "revoked"
        # Leaving the organization also ends team places and direct agent assignments there, so rejoining
        # later starts clean
        now = utcnow()
        db.execute(update(TeamMember).where(TeamMember.organization_id == ctx.org.id, TeamMember.user_id == m.user_id,
                                            TeamMember.removed_at.is_(None)).values(removed_at=now))
        db.execute(update(AgentAssignment).where(
            AgentAssignment.organization_id == ctx.org.id, AgentAssignment.user_id == m.user_id,
            AgentAssignment.revoked_at.is_(None)).values(revoked_at=now, revoked_by=ctx.user.id,
                                                         revoke_reason="member_removed", updated_at=now))
        audit(db, request, "member.revoked", actor=ctx.user, organization_id=ctx.org.id,
              target_type="membership", target_id=m.id, details={"role": m.role})
        db.commit()
        return {"ok": True}

    # ---------- invitations ----------
    def _issue_invitation(db: Session, request: Request, org: Organization, email: str, role: str,
                          actor: User | None) -> tuple[Invitation, str, bool]:
        """Creates a pending invitation, or gives a pending one a new link and expiry (a resend).
        Returns (invitation, secret token, emailed)."""
        s = settings_of(request)
        now = utcnow()
        token = new_token()
        inv = db.scalars(select(Invitation).where(Invitation.organization_id == org.id, Invitation.email == email,
                                                  Invitation.status == "pending")).first()
        if inv is None:
            inv = Invitation(organization_id=org.id, email=email, role=role, status="pending")
            db.add(inv)
            action = "invitation.created"
        else:
            action = "invitation.resent"
        inv.role, inv.token_hash = role, token_hash(token)
        inv.invited_by_user_id = actor.id if actor else None
        inv.expires_at = now + timedelta(hours=s.invitation_ttl_hours)
        db.flush()
        audit(db, request, action, actor=actor, organization_id=org.id, target_type="invitation", target_id=inv.id,
              details={"email": email, "role": role})
        db.commit()
        link = invite_link(s, token)
        emailed = send_mail(f"You're invited to {org.name} on DIDM",
                            f"You have been invited to join {org.name} as {role.replace('_', ' ')}.\n\n"
                            f"Accept here (the link works for {s.invitation_ttl_hours // 24} days):\n{link}\n",
                            email)
        return inv, token, emailed

    @r.get("/organizations/{org_id}/invitations")
    def list_invitations(ctx: OrgContext = Depends(org_access("invitations.manage")), db: Session = Depends(get_db)):
        now = utcnow()
        rows = db.scalars(select(Invitation).where(Invitation.organization_id == ctx.org.id)
                          .order_by(Invitation.created_at.desc()).limit(500)).all()
        return [invitation_out(i, now) for i in rows]

    @r.post("/organizations/{org_id}/invitations", status_code=201)
    def create_invitation(body: InviteIn, request: Request, ctx: OrgContext = Depends(org_access("invitations.manage")),
                          db: Session = Depends(get_db)):
        rate(request, "invite", 60, 3600, ctx.user.id)
        email = norm_email(body.email)
        if body.role not in ROLES:
            raise HTTPException(status_code=422, detail="Unknown role.")
        if not can_grant(ctx.role, body.role):
            raise HTTPException(status_code=403, detail="Your role cannot invite with that role.")
        existing = db.scalars(select(Membership).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == ctx.org.id, User.email == email, Membership.status == "active")).first()
        if existing:
            raise HTTPException(status_code=409, detail="That person is already a member.")
        inv, token, emailed = _issue_invitation(db, request, db.merge(ctx.org), email, body.role, ctx.user)
        # The link is returned once, to the admin who created it, so it can be shared if email is off.
        # It is never stored in plain text or logged.
        return {**invitation_out(inv, utcnow()), "accept_url": invite_link(settings_of(request), token),
                "emailed": emailed}

    @r.post("/organizations/{org_id}/invitations/{invitation_id}/revoke")
    def revoke_invitation(invitation_id: str, request: Request,
                          ctx: OrgContext = Depends(org_access("invitations.manage")), db: Session = Depends(get_db)):
        inv = scoped_get(db, Invitation, ctx.org.id, invitation_id)
        if inv.status != "pending":
            raise HTTPException(status_code=409, detail="Only pending invitations can be revoked.")
        if not can_grant(ctx.role, inv.role):
            raise HTTPException(status_code=403, detail="Your role cannot revoke that invitation.")
        inv.status = "revoked"
        audit(db, request, "invitation.revoked", actor=ctx.user, organization_id=ctx.org.id,
              target_type="invitation", target_id=inv.id, details={"email": inv.email})
        db.commit()
        return invitation_out(inv, utcnow())

    def _valid_invitation(db: Session, token: str) -> Invitation:
        inv = db.scalars(select(Invitation).where(Invitation.token_hash == token_hash(token))).first()
        if inv is None or inv.status != "pending" or inv.expires_at <= utcnow():
            raise HTTPException(status_code=400, detail="This invitation is invalid, used or expired.")
        org = db.get(Organization, inv.organization_id)
        if org is None or org.status != "active":
            raise HTTPException(status_code=400, detail="This invitation is invalid, used or expired.")
        return inv

    @r.post("/invitations/lookup")
    def lookup_invitation(body: TokenIn, request: Request, db: Session = Depends(get_db)):
        rate(request, "invite-lookup", 30, 3600)
        inv = _valid_invitation(db, body.token)
        org = db.get(Organization, inv.organization_id)
        has_account = db.scalars(select(User.id).where(User.email == inv.email)).first() is not None
        return {"organization": {"id": org.id, "name": org.name}, "email": inv.email, "role": inv.role,
                "has_account": has_account, "expires_at": inv.expires_at.isoformat()}

    @r.post("/invitations/accept")
    def accept_invitation(body: AcceptIn, request: Request, response: Response, db: Session = Depends(get_db)):
        rate(request, "invite-accept", 20, 3600)
        inv = _valid_invitation(db, body.token)
        user = db.scalars(select(User).where(User.email == inv.email)).first()
        from .auth import CSRF_HEADER, _load_auth  # the caller may already be logged in
        auth = _load_auth(request, db)
        if auth is not None:
            # Acting with an existing session needs the CSRF token too, so another site cannot make a
            # logged-in user silently join an organization
            sent = request.headers.get(CSRF_HEADER, "")
            if not sent or not hmac.compare_digest(token_hash(sent), auth.session.csrf_hash):
                raise HTTPException(status_code=403, detail="Missing or wrong CSRF token.")
        new_user = False
        if user is not None:
            # An existing account must be logged in, so nobody can attach someone else's account
            if auth is None or auth.user.id != user.id:
                raise HTTPException(status_code=401, detail="Log in as this email to accept the invitation.")
        else:
            if auth is not None:
                raise HTTPException(status_code=409, detail="You are logged in as a different email. Log out first.")
            if not body.password or not (body.name or "").strip():
                raise HTTPException(status_code=422, detail="Enter your name and a password.")
            check_password(body.password)
            user = User(email=inv.email, name=body.name.strip(), password_hash=hash_password(body.password),
                        status="active", is_platform_admin=False, email_verified_at=utcnow())
            db.add(user)
            try:
                db.flush()
            except IntegrityError:
                db.rollback()
                raise HTTPException(status_code=409, detail="An account with this email was just created. Log in.")
            new_user = True
        if user.status != "active":
            raise HTTPException(status_code=403, detail="This account is disabled.")
        if user.email_verified_at is None:
            user.email_verified_at = utcnow()  # the link reached this inbox
        m = db.scalars(select(Membership).where(Membership.organization_id == inv.organization_id,
                                                Membership.user_id == user.id)).first()
        if m is None:
            m = Membership(organization_id=inv.organization_id, user_id=user.id, role=inv.role, status="active")
            db.add(m)
        else:  # rejoining after being removed takes the invitation's role
            m.role, m.status = inv.role, "active"
        inv.status, inv.accepted_at, inv.accepted_user_id = "accepted", utcnow(), user.id
        db.flush()
        audit(db, request, "invitation.accepted", actor=user, organization_id=inv.organization_id,
              target_type="invitation", target_id=inv.id, details={"role": inv.role, "new_user": new_user})
        if new_user:
            sess = start_session(db, request, user, response)
            sess.active_organization_id = inv.organization_id
        else:
            row = db.merge(auth.session)
            row.active_organization_id = inv.organization_id
        db.commit()
        return {"ok": True, "organization_id": inv.organization_id, "role": inv.role, "user": user_out(user)}

    # ---------- audit ----------
    @r.get("/organizations/{org_id}/audit-events")
    def list_audit(limit: int = 100, ctx: OrgContext = Depends(org_access("audit.view")), db: Session = Depends(get_db)):
        rows = db.scalars(select(AuditEvent).where(AuditEvent.organization_id == ctx.org.id)
                          .order_by(AuditEvent.id.desc()).limit(min(max(limit, 1), 500))).all()
        return [{"id": a.id, "action": a.action, "actor_user_id": a.actor_user_id, "target_type": a.target_type,
                 "target_id": a.target_id, "details": a.details, "created_at": a.created_at.isoformat()} for a in rows]

    # ---------- platform administration ----------
    @r.get("/platform/organizations")
    def platform_list_orgs(auth: Auth = Depends(platform_admin), db: Session = Depends(get_db)):
        counts = dict(db.execute(select(Membership.organization_id, func.count(Membership.id))
                                 .where(Membership.status == "active").group_by(Membership.organization_id)).all())
        return [{**org_out(o), "active_members": counts.get(o.id, 0)}
                for o in db.scalars(select(Organization).order_by(Organization.created_at.desc()))]

    @r.post("/platform/organizations", status_code=201)
    def platform_create_org(body: OrgCreateIn, request: Request, auth: Auth = Depends(platform_admin),
                            db: Session = Depends(get_db)):
        slug = body.slug.strip().lower()
        if not SLUG_RE.match(slug):
            raise HTTPException(status_code=422, detail="Slug: lower-case letters, digits and dashes only.")
        owner_email = norm_email(body.owner_email)
        org = Organization(name=body.name.strip(), slug=slug, status="active", settings={})
        db.add(org)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="That slug is already used.")
        audit(db, request, "org.created", actor=auth.user, organization_id=org.id, target_type="organization",
              target_id=org.id, details={"slug": slug})
        inv, token, emailed = _issue_invitation(db, request, org, owner_email, OWNER, auth.user)
        return {"organization": org_out(org), "owner_invitation": {**invitation_out(inv, utcnow()),
                "accept_url": invite_link(settings_of(request), token), "emailed": emailed}}

    @r.patch("/platform/organizations/{org_id}")
    def platform_set_status(org_id: str, body: OrgStatusIn, request: Request, auth: Auth = Depends(platform_admin),
                            db: Session = Depends(get_db)):
        if body.status not in ("active", "suspended"):
            raise HTTPException(status_code=422, detail="Status must be active or suspended.")
        org = db.get(Organization, org_id)
        if org is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        org.status = body.status
        audit(db, request, f"org.{'suspended' if body.status == 'suspended' else 'reactivated'}", actor=auth.user,
              organization_id=org.id, target_type="organization", target_id=org.id)
        db.commit()
        return org_out(org)

    return r


def invite_link(s, token: str) -> str:
    # The secret goes after "#", which browsers never send to servers, so it stays out of access logs
    return f"{s.app_url()}/invite/accept/#token={token}"


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def mount_saas(app: FastAPI, s, mailer, limiter):
    app.include_router(build_router(mailer, limiter))
    from .agents import build_agents_router
    app.include_router(build_agents_router())
    from .knowledge_api import build_knowledge_router
    app.include_router(build_knowledge_router(s))
    from .training_api import build_training_router
    app.include_router(build_training_router(app.state.training))
    from .intelligence_api import build_intelligence_router
    app.include_router(build_intelligence_router(app.state.training, app.state.intelligence, app.state.recordings))

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(("/api/", "/app")):
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
            if request.url.path.startswith("/app"):
                response.headers["Cache-Control"] = "no-cache"
        return response

    dist = Path(s.frontend_dist_dir)
    if not dist.is_absolute():
        dist = Path(__file__).resolve().parent.parent.parent / dist
    if dist.is_dir():
        app.mount("/app", StaticFiles(directory=dist, html=True), name="webapp")
    else:
        log.info("web app not built (%s missing); /app is not served", dist)

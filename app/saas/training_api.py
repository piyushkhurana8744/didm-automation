"""HTTP API for training sessions, usage, limits and trainee phone numbers."""
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from ..db import WebhookEvent, utcnow
from ..leads import to_e164
from .agents import clamp_page, iso, page
from .auth import Auth, OrgContext, audit, current_auth, get_db, org_access, platform_admin, scoped_get
from .models import (OPEN_SESSION_STATUSES, Agent, Membership, Organization, TrainingOrgLimits, TrainingOrgSettings,
                     TrainingScenario,
                     TrainingSession, TrainingSessionEvent, TrainingUsageEvent, User)
from .permissions import has_permission
from .training import TERMINAL, TrainingError, effective_limits, mask_phone, month_start, used_seconds_this_month


def session_out(s: TrainingSession, names: dict | None = None, detail: bool = False) -> dict:
    names = names or {}
    out = {"id": s.id, "user_id": s.user_id, "user_email": names.get(("user", s.user_id)),
           "agent_id": s.agent_id, "agent_name": names.get(("agent", s.agent_id)),
           "agent_version_id": s.agent_version_id, "provider_app_version": s.provider_app_version,
           "scenario_id": s.scenario_id, "scenario_name": names.get(("scenario", s.scenario_id)),
           "channel": s.channel, "status": s.status, "terminal": s.status in TERMINAL,
           "failure_code": s.failure_code, "failure_reason": s.failure_reason,
           "phone": f"******{s.phone_last4}" if s.phone_last4 else None,
           "max_duration_seconds": s.max_duration_seconds, "started_at": iso(s.started_at),
           "connected_at": iso(s.connected_at), "ended_at": iso(s.ended_at), "duration_seconds": s.duration_seconds,
           "billable_seconds": s.billable_seconds, "created_at": iso(s.created_at), "updated_at": iso(s.updated_at)}
    if detail:
        out["access"] = {k: v for k, v in (s.access_snapshot or {}).items() if k != "limits"}
    return out


def _names(db: Session, org_id: str, rows: list[TrainingSession]) -> dict:
    names = {}
    for a in db.scalars(select(Agent).where(Agent.organization_id == org_id, Agent.id.in_({r.agent_id for r in rows}))):
        names[("agent", a.id)] = a.name
    for u in db.scalars(select(User).where(User.id.in_({r.user_id for r in rows}))):
        names[("user", u.id)] = u.email
    sc = {r.scenario_id for r in rows if r.scenario_id}
    for t in db.scalars(select(TrainingScenario).where(TrainingScenario.organization_id == org_id,
                                                       TrainingScenario.id.in_(sc))):
        names[("scenario", t.id)] = t.name
    return names


class StartIn(BaseModel):
    agent_id: str = Field(max_length=36)
    channel: str = Field(max_length=10)
    scenario_id: str | None = Field(default=None, max_length=36)
    client_request_id: str | None = Field(default=None, min_length=8, max_length=64)
    # The consent notice version the trainee accepted for recording this session, if any
    recording_consent_version: str | None = Field(default=None, max_length=64)
    # The practice-call notice version the trainee accepted; required when the organization has a notice
    practice_notice_version: str | None = Field(default=None, max_length=64)
    # Lead name / caller persona name passed to Sarvam agent prompt
    lead_name: str | None = Field(default=None, max_length=100)
    # Additional custom agent variables
    custom_variables: dict[str, Any] | None = Field(default=None)


class BrowserAuthorizeIn(BaseModel):
    session_id: str = Field(max_length=36)


class BrowserEventIn(BaseModel):
    event: str = Field(max_length=30)
    detail: str = Field(default="", max_length=300)


class PhoneIn(BaseModel):
    phone: str | None = Field(default=None, max_length=30)


class VerifyPhoneIn(BaseModel):
    phone: str = Field(max_length=30)


class LimitsIn(BaseModel):
    enabled: bool | None = None
    phone_enabled: bool | None = None
    browser_enabled: bool | None = None
    max_concurrent_sessions: int | None = Field(default=None, ge=0, le=500)
    max_concurrent_per_user: int | None = Field(default=None, ge=0, le=10)
    max_sessions_per_user_per_day: int | None = Field(default=None, ge=0, le=500)
    max_session_minutes: int | None = Field(default=None, ge=1, le=120)
    monthly_minutes: int | None = Field(default=None, ge=0, le=1_000_000)
    evaluation_enabled: bool | None = None
    recording_allowed: bool | None = None
    evaluation_monthly_calls: int | None = Field(default=None, ge=0, le=1_000_000)
    evaluation_monthly_tokens: int | None = Field(default=None, ge=0, le=10_000_000_000)
    clear: list[str] = Field(default_factory=list)  # fields to set back to the platform default


LIMIT_FIELDS = ("max_concurrent_sessions", "max_concurrent_per_user", "max_sessions_per_user_per_day",
                "max_session_minutes", "monthly_minutes")
CLEARABLE = LIMIT_FIELDS + ("evaluation_monthly_calls", "evaluation_monthly_tokens")


def build_training_router(engine) -> APIRouter:
    r = APIRouter(prefix="/api/v1")

    def fail(e: TrainingError):
        raise HTTPException(status_code=e.status, detail=e.message, headers={"X-Error-Code": e.code})

    def own_or_viewer(db: Session, ctx: OrgContext, session_id: str) -> TrainingSession:
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if sess.user_id != ctx.user.id and not has_permission(ctx.role, "training.view"):
            raise HTTPException(status_code=404, detail="Not found.")
        return sess

    # ---------- sessions ----------
    @r.post("/organizations/{org_id}/training/sessions", status_code=201)
    def start_session(body: StartIn, request: Request, ctx: OrgContext = Depends(org_access("training.self")),
                      db: Session = Depends(get_db)):
        """Starts a training session for the caller. Everything that decides what is called (agent
        version, provider app, number, variables) is resolved here on the server."""
        limiter = request.app.state.limiter
        limiter.check(f"training-start:{ctx.user.id}", 20, 3600)
        st = db.get(TrainingOrgSettings, ctx.org.id)
        notice = st.practice_notice_version if st else None
        if notice and body.practice_notice_version != notice:
            # Checked before anything is reserved or dialled
            raise HTTPException(status_code=409, detail="Read and accept the practice call notice first.",
                                headers={"X-Error-Code": "notice_not_accepted"})
        try:
            sess, replayed = engine.request_session(db, db.merge(ctx.org), db.merge(ctx.user), db.merge(ctx.membership),
                                                    body.agent_id, body.channel, body.scenario_id,
                                                    body.client_request_id,
                                                    lead_name=body.lead_name,
                                                    custom_variables=body.custom_variables)
        except TrainingError as e:
            fail(e)
        if not replayed and notice:
            db.execute(update(TrainingSession).where(TrainingSession.id == sess.id)
                       .values(practice_notice_reference=notice))
        if not replayed and body.recording_consent_version:
            policy = request.app.state.recordings.org_policy(db, ctx.org.id)
            if policy["available"] and body.recording_consent_version == policy["consent_version"]:
                db.execute(update(TrainingSession).where(TrainingSession.id == sess.id)
                           .values(recording_consent_reference=policy["consent_version"]))
        if not replayed:
            audit(db, request, "training.session_requested", actor=ctx.user, organization_id=ctx.org.id,
                  target_type="training_session", target_id=sess.id,
                  details={"agent_id": sess.agent_id, "channel": sess.channel, "version": sess.agent_version_id})
            db.commit()
            if sess.channel == "phone":
                engine.launch_phone(sess.id)  # runs in its own DB session
        sid = sess.id
        db.expire_all()
        sess = db.get(TrainingSession, sid)
        return {**session_out(sess, _names(db, ctx.org.id, [sess]), detail=True), "replayed": replayed}

    @r.get("/organizations/{org_id}/training/sessions")
    def list_sessions(status: str = "", channel: str = "", agent_id: str = "", user_id: str = "",
                      since: datetime | None = None, until: datetime | None = None, limit: int = 50, offset: int = 0,
                      ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        limit, offset = clamp_page(limit, offset)
        cond = [TrainingSession.organization_id == ctx.org.id]
        if status == "open":
            cond.append(TrainingSession.status.in_(OPEN_SESSION_STATUSES))
        elif status:
            cond.append(TrainingSession.status == status)
        if channel:
            cond.append(TrainingSession.channel == channel)
        if agent_id:
            cond.append(TrainingSession.agent_id == agent_id)
        if user_id:
            cond.append(TrainingSession.user_id == user_id)
        if since:
            cond.append(TrainingSession.created_at >= since.replace(tzinfo=None))
        if until:
            cond.append(TrainingSession.created_at < until.replace(tzinfo=None))
        total = db.scalar(select(func.count(TrainingSession.id)).where(*cond)) or 0
        rows = db.scalars(select(TrainingSession).where(*cond).order_by(TrainingSession.created_at.desc())
                          .limit(limit).offset(offset)).all()
        names = _names(db, ctx.org.id, rows)
        return page([session_out(s, names) for s in rows], total, limit, offset)

    @r.get("/organizations/{org_id}/my/training/sessions")
    def my_sessions(limit: int = 50, offset: int = 0, ctx: OrgContext = Depends(org_access("training.self")),
                    db: Session = Depends(get_db)):
        limit, offset = clamp_page(limit, offset)
        cond = [TrainingSession.organization_id == ctx.org.id, TrainingSession.user_id == ctx.user.id]
        total = db.scalar(select(func.count(TrainingSession.id)).where(*cond)) or 0
        rows = db.scalars(select(TrainingSession).where(*cond).order_by(TrainingSession.created_at.desc())
                          .limit(limit).offset(offset)).all()
        names = _names(db, ctx.org.id, rows)
        return page([session_out(s, names) for s in rows], total, limit, offset)

    @r.get("/organizations/{org_id}/training/sessions/{session_id}")
    def get_session(session_id: str, ctx: OrgContext = Depends(org_access("training.self")),
                    db: Session = Depends(get_db)):
        sess = own_or_viewer(db, ctx, session_id)
        events = db.scalars(select(TrainingSessionEvent).where(TrainingSessionEvent.session_id == sess.id)
                            .order_by(TrainingSessionEvent.received_at)).all()
        return {**session_out(sess, _names(db, ctx.org.id, [sess]), detail=True),
                "events": [{"type": e.event_type, "at": iso(e.received_at)} for e in events]}

    @r.post("/organizations/{org_id}/training/sessions/{session_id}/cancel")
    def cancel_session(session_id: str, request: Request, ctx: OrgContext = Depends(org_access("training.self")),
                       db: Session = Depends(get_db)):
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if sess.user_id != ctx.user.id and not has_permission(ctx.role, "training.manage"):
            raise HTTPException(status_code=404, detail="Not found.")
        try:
            sess = engine.cancel(db, sess, ctx.user)
        except TrainingError as e:
            fail(e)
        audit(db, request, "training.session_cancelled", actor=ctx.user, organization_id=ctx.org.id,
              target_type="training_session", target_id=sess.id)
        db.commit()
        return session_out(sess, _names(db, ctx.org.id, [sess]))

    # ---------- browser (off until verified) ----------
    @r.post("/organizations/{org_id}/training/browser/authorize")
    def browser_authorize(body: BrowserAuthorizeIn, request: Request,
                          ctx: OrgContext = Depends(org_access("training.self")), db: Session = Depends(get_db)):
        request.app.state.limiter.check(f"training-browser:{ctx.user.id}", 20, 3600)
        try:
            return engine.authorize_browser(db, db.merge(ctx.org), db.merge(ctx.user), body.session_id)
        except TrainingError as e:
            fail(e)

    @r.post("/organizations/{org_id}/training/sessions/{session_id}/browser-events")
    def browser_event(session_id: str, body: BrowserEventIn, ctx: OrgContext = Depends(org_access("training.self")),
                      db: Session = Depends(get_db)):
        sess = scoped_get(db, TrainingSession, ctx.org.id, session_id)
        if sess.user_id != ctx.user.id or sess.channel != "browser":
            raise HTTPException(status_code=404, detail="Not found.")
        try:
            sess = engine.browser_event(db, sess, body.event, body.detail)
        except TrainingError as e:
            fail(e)
        return session_out(sess)

    # ---------- availability, limits and usage ----------
    @r.get("/organizations/{org_id}/training/availability")
    def availability(request: Request, ctx: OrgContext = Depends(org_access("training.self")),
                     db: Session = Depends(get_db)):
        """What the trainee's page needs to show working or unavailable channels truthfully."""
        lim = effective_limits(db, engine.s, ctx.org.id)
        user = db.get(User, ctx.user.id)
        m = db.get(Membership, ctx.membership.id)
        return {"enabled": lim.enabled,
                "phone": {"available": bool(lim.enabled and lim.phone_enabled and engine.phone_available()),
                          "phone_on_file": mask_phone(user.phone_e164),
                          "phone_verified": bool(user.phone_e164 and m.verified_phone_e164 == user.phone_e164)},
                "browser": {"available": bool(lim.enabled and lim.browser_enabled and engine.browser_available()),
                            "reason": None if engine.browser_available() else
                            "Browser voice is waiting for the Sarvam Web SDK to be verified."},
                "max_session_minutes": lim.session_minutes,
                "recording": {k: v for k, v in request.app.state.recordings.org_policy(db, ctx.org.id).items()
                              if k in ("available", "consent_version", "consent_text", "retention_days")},
                "practice_notice": practice_notice(db, ctx.org.id)}

    def practice_notice(db: Session, org_id: str) -> dict | None:
        st = db.get(TrainingOrgSettings, org_id)
        if not st or not st.practice_notice_version:
            return None
        return {"version": st.practice_notice_version, "text": st.practice_notice_text}

    @r.get("/organizations/{org_id}/training/usage")
    def usage(ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        now = utcnow()
        lim = effective_limits(db, engine.s, ctx.org.id)
        billed, held = used_seconds_this_month(db, ctx.org.id, now)
        start = month_start(now)
        base = [TrainingSession.organization_id == ctx.org.id, TrainingSession.created_at >= start]
        by_status = dict(db.execute(select(TrainingSession.status, func.count(TrainingSession.id)).where(*base)
                                    .group_by(TrainingSession.status)).all())
        failures = dict(db.execute(select(TrainingSession.failure_code, func.count(TrainingSession.id)).where(
            *base, TrainingSession.status.in_(("failed", "timed_out"))).group_by(TrainingSession.failure_code)).all())
        agent_rows = db.execute(select(TrainingSession.agent_id, func.count(TrainingSession.id),
                                       func.coalesce(func.sum(TrainingSession.billable_seconds), 0))
                                .where(*base).group_by(TrainingSession.agent_id)).all()
        names = {a.id: a.name for a in db.scalars(select(Agent).where(
            Agent.organization_id == ctx.org.id, Agent.id.in_([x[0] for x in agent_rows])))}
        sessions_metric = db.scalar(select(func.coalesce(func.sum(TrainingUsageEvent.quantity), 0)).where(
            TrainingUsageEvent.organization_id == ctx.org.id, TrainingUsageEvent.metric == "sessions",
            TrainingUsageEvent.created_at >= start)) or 0
        return {"month": start.strftime("%Y-%m"), "limits": lim.as_dict(),
                "billable_minutes": round(billed / 60, 1), "reserved_minutes": round(held / 60, 1),
                "remaining_minutes": max(0, round((lim.monthly_minutes * 60 - billed - held) / 60, 1)),
                "connected_sessions": int(sessions_metric),
                "active_sessions": sum(by_status.get(s, 0) for s in OPEN_SESSION_STATUSES),
                "by_status": by_status, "failure_codes": {k or "unknown": v for k, v in failures.items()},
                "by_agent": [{"agent_id": a, "agent_name": names.get(a), "sessions": n,
                              "billable_minutes": round(int(sec) / 60, 1)} for a, n, sec in agent_rows]}

    # ---------- phone numbers ----------
    @r.put("/auth/me/phone")
    def set_my_phone(body: PhoneIn, request: Request, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
        user = db.merge(auth.user)
        if body.phone in (None, ""):
            user.phone_e164 = None
        else:
            e164 = to_e164(body.phone)
            if not e164:
                raise HTTPException(status_code=422, detail="Enter a 10-digit Indian mobile number.")
            user.phone_e164 = e164
        audit(db, request, "user.phone_changed", actor=user, details={"set": bool(user.phone_e164)})
        db.commit()
        return {"phone": mask_phone(user.phone_e164)}

    @r.get("/organizations/{org_id}/training/phones")
    def list_phones(ctx: OrgContext = Depends(org_access("training.manage")), db: Session = Depends(get_db)):
        rows = db.execute(select(Membership, User).join(User, User.id == Membership.user_id).where(
            Membership.organization_id == ctx.org.id, Membership.status == "active").order_by(User.email)).all()
        return [{"membership_id": m.id, "user_id": u.id, "email": u.email, "name": u.name, "role": m.role,
                 "phone": u.phone_e164, "verified": bool(u.phone_e164 and m.verified_phone_e164 == u.phone_e164),
                 "verified_at": iso(m.phone_verified_at) if m.verified_phone_e164 == u.phone_e164 else None,
                 "verification_method": (m.phone_verification_method or "admin_confirmed")
                 if u.phone_e164 and m.verified_phone_e164 == u.phone_e164 else None}
                for m, u in rows]

    @r.post("/organizations/{org_id}/members/{membership_id}/verify-phone")
    def verify_phone(membership_id: str, body: VerifyPhoneIn, request: Request,
                     ctx: OrgContext = Depends(org_access("training.manage")), db: Session = Depends(get_db)):
        """An admin confirms the trainee's number (for example by calling it). The admin types the number
        they confirmed; it must match what the trainee saved, so neither side can swap it alone."""
        m = scoped_get(db, Membership, ctx.org.id, membership_id)
        user = db.get(User, m.user_id)
        typed = to_e164(body.phone)
        if m.status != "active" or user is None or not user.phone_e164:
            raise HTTPException(status_code=409, detail="This person has not saved a phone number.")
        if typed != user.phone_e164:
            raise HTTPException(status_code=409, detail="That is not the number this person saved.")
        m.verified_phone_e164, m.phone_verified_at, m.phone_verified_by = typed, utcnow(), ctx.user.id
        # This proves an admin confirmed the number, not that the trainee received a code on it
        m.phone_verification_method = "admin_confirmed"
        audit(db, request, "member.phone_verified", actor=ctx.user, organization_id=ctx.org.id,
              target_type="membership", target_id=m.id, details={"method": "admin_confirmed"})
        db.commit()
        return {"ok": True, "verified": True}

    @r.delete("/organizations/{org_id}/members/{membership_id}/verify-phone")
    def unverify_phone(membership_id: str, request: Request, ctx: OrgContext = Depends(org_access("training.manage")),
                       db: Session = Depends(get_db)):
        m = scoped_get(db, Membership, ctx.org.id, membership_id)
        m.verified_phone_e164 = m.phone_verified_at = m.phone_verified_by = m.phone_verification_method = None
        audit(db, request, "member.phone_unverified", actor=ctx.user, organization_id=ctx.org.id,
              target_type="membership", target_id=m.id)
        db.commit()
        return {"ok": True, "verified": False}

    # ---------- platform: limits and health ----------
    def limits_out(db: Session, org_id: str) -> dict:
        row = db.get(TrainingOrgLimits, org_id)
        stored = {f: getattr(row, f) for f in ("enabled", "phone_enabled", "browser_enabled", "evaluation_enabled",
                                               "recording_allowed", *CLEARABLE)} if row else {}
        return {"organization_id": org_id, "stored": stored, "effective": effective_limits(db, engine.s, org_id).as_dict(),
                "platform": {"phone_channel_live": engine.phone_available(),
                             "browser_channel_live": engine.browser_available()}}

    @r.get("/organizations/{org_id}/training/limits")
    def org_limits(ctx: OrgContext = Depends(org_access("training.view")), db: Session = Depends(get_db)):
        return limits_out(db, ctx.org.id)

    @r.get("/platform/organizations/{org_id}/training-limits")
    def platform_get_limits(org_id: str, auth: Auth = Depends(platform_admin), db: Session = Depends(get_db)):
        if db.get(Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        return limits_out(db, org_id)

    @r.put("/platform/organizations/{org_id}/training-limits")
    def platform_set_limits(org_id: str, body: LimitsIn, request: Request, auth: Auth = Depends(platform_admin),
                            db: Session = Depends(get_db)):
        if db.get(Organization, org_id) is None:
            raise HTTPException(status_code=404, detail="Organization not found.")
        row = db.get(TrainingOrgLimits, org_id)
        if row is None:
            row = TrainingOrgLimits(organization_id=org_id, enabled=False, phone_enabled=True, browser_enabled=False,
                                    evaluation_enabled=False, recording_allowed=False)
            db.add(row)
        data = body.model_dump(exclude_none=True, exclude={"clear"})
        for k, v in data.items():
            setattr(row, k, v)
        for k in body.clear:
            if k not in CLEARABLE:
                raise HTTPException(status_code=422, detail=f"Cannot clear {k}.")
            setattr(row, k, None)
        row.updated_by, row.updated_at = auth.user.id, utcnow()
        audit(db, request, "training.limits_changed", actor=auth.user, organization_id=org_id,
              target_type="organization", target_id=org_id, details={**data, "cleared": body.clear})
        db.commit()
        return limits_out(db, org_id)

    @r.get("/platform/training/health")
    def platform_health(auth: Auth = Depends(platform_admin), db: Session = Depends(get_db)):
        """Counts for operators. No user, phone or org names: just states, channels and failure codes."""
        now = utcnow()
        day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        open_by_channel = dict(db.execute(select(TrainingSession.channel, func.count(TrainingSession.id)).where(
            TrainingSession.status.in_(OPEN_SESSION_STATUSES)).group_by(TrainingSession.channel)).all())
        failures = dict(db.execute(select(TrainingSession.failure_code, func.count(TrainingSession.id)).where(
            TrainingSession.created_at >= day, TrainingSession.status.in_(("failed", "timed_out")))
            .group_by(TrainingSession.failure_code)).all())
        done = db.execute(select(func.count(TrainingSession.id), func.avg(TrainingSession.duration_seconds)).where(
            TrainingSession.created_at >= day, TrainingSession.status == "completed")).one()
        hooks = db.execute(select(WebhookEvent.status, func.count(WebhookEvent.id)).where(
            WebhookEvent.source == "training_result", WebhookEvent.created_at >= day)
            .group_by(WebhookEvent.status)).all()
        return {"open_sessions": open_by_channel, "platform_capacity": engine.s.training_max_concurrent_total,
                "today": {"completed": done[0], "avg_duration_seconds": round(float(done[1] or 0), 1),
                          "failures": {k or "unknown": v for k, v in failures.items()}},
                "training_webhooks_today": dict(hooks)}

    return r

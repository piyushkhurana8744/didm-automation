"""Training session engine: one session model for phone and browser, its state machine, capacity
reservations, usage metering and provider result processing.

Phone sessions use the same Sarvam outbound API as the lead dialler, but with their own webhook route and
secret, so a training result can never touch the Google Sheet or send a campaign WhatsApp. Browser voice
sits behind TRAINING_BROWSER_ENABLED (off), because the Sarvam Web SDK contract is not verified yet.
"""
import hashlib
import hmac
import json
import logging
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from ..integrations import CallTarget
from .agents import allowed_scenarios, entitlements, variables_problems
from .models import (OPEN_SESSION_STATUSES, BrowserSessionToken, Membership, Organization, TrainingOrgLimits,
                     TraineeAgentTrainingProfile, TrainingSession, TrainingSessionEvent, TrainingUsageAdjustment, TrainingUsageEvent,
                     TrainingUsageReservation, User)

log = logging.getLogger("didm.training")


def runtime_identity_variables(schema_names: set[str], user_name: str, agent_name: str) -> dict:
    """Map the signed-in trainee to the identity aliases declared by the Sarvam agent.

    Older registrations have an empty local schema even though the DIDM Sarvam agent declares
    ``lead_name``. Keep that established outbound-call contract as the narrow legacy fallback.
    """
    candidates = {
        "agent_name": agent_name,
        "user_name": user_name,
        "trainee_name": user_name,
        "lead_name": user_name,
        "student_name": user_name,
        "customer_name": user_name,
        "name": user_name,
    }
    if not schema_names:
        return {"lead_name": user_name}
    return {key: value for key, value in candidates.items() if key in schema_names}

# ---------- state machine ----------
TERMINAL = ("completed", "failed", "cancelled", "timed_out")
TRANSITIONS = {
    "requested": {"preparing", "failed", "cancelled", "timed_out"},
    # preparing -> completed/failed covers a provider result that arrives before the start call returned
    "preparing": {"connecting", "active", "completed", "failed", "cancelled", "timed_out"},
    "connecting": {"active", "completed", "failed", "cancelled", "timed_out"},
    "active": {"completed", "failed", "cancelled", "timed_out"},
}
for _t in TERMINAL:
    TRANSITIONS[_t] = set()  # terminal states never change

# Sarvam outbound result statuses that mean the trainee talked to the agent. Anything else is a failure
# whose status becomes the failure code (no_answer, busy, failed, ...).
CONNECTED_PROVIDER_STATUSES = ("connected", "completed", "ended")

# Configuration keys a version may use to steer the phone channel. Nothing else from the stored
# configuration, and nothing from the client, reaches the provider's connection settings.
PHONE_CONFIG_KEYS = ("connection_id", "agent_phone_number")

PG_LOCK_KEY = 7340211  # pg_advisory_xact_lock key for training capacity
_local_lock = threading.Lock()


class TrainingError(Exception):
    """A request the engine refuses. status is the HTTP status the API answers with."""

    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def allowed_from(target: str) -> list[str]:
    return [s for s, nxt in TRANSITIONS.items() if target in nxt]


def transition(db: Session, session_id: str, target: str, **values) -> bool:
    """Moves a session to target only from a state that may lead there, in one conditional UPDATE.
    Returns False (and changes nothing) when the session is already past that point, so stale, late or
    duplicate events can never overwrite a terminal state."""
    now = utcnow()
    n = db.execute(update(TrainingSession).where(
        TrainingSession.id == session_id, TrainingSession.status.in_(allowed_from(target))
    ).values(status=target, updated_at=now, **values)).rowcount
    return n == 1


def add_event(db: Session, s: TrainingSession, event_type: str, payload: dict | None = None,
              provider_event_id: str | None = None, processed: bool = True) -> TrainingSessionEvent:
    now = utcnow()
    ev = TrainingSessionEvent(organization_id=s.organization_id, session_id=s.id, event_type=event_type,
                              provider_event_id=provider_event_id, event_payload=payload or {},
                              occurred_at=now, received_at=now, processed_at=now if processed else None)
    db.add(ev)
    return ev


def slog(event: str, **fields):
    """One structured log line. Callers pass ids and codes only: never phone numbers, URLs or keys."""
    log.info("%s %s", event, json.dumps(fields, sort_keys=True, default=str))


# ---------- limits ----------
@dataclass(frozen=True)
class EffectiveLimits:
    enabled: bool
    phone_enabled: bool
    browser_enabled: bool
    org_concurrency: int
    user_concurrency: int
    sessions_per_day: int
    session_minutes: int
    monthly_minutes: int
    platform_concurrency: int

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def effective_limits(db: Session, settings, org_id: str) -> EffectiveLimits:
    row = db.get(TrainingOrgLimits, org_id)

    def pick(field, default):
        v = getattr(row, field, None) if row else None
        return default if v is None else v
    return EffectiveLimits(
        enabled=bool(row and row.enabled),
        phone_enabled=bool(row.phone_enabled) if row else False,
        browser_enabled=bool(row.browser_enabled) if row else False,
        org_concurrency=pick("max_concurrent_sessions", settings.training_default_org_concurrency),
        user_concurrency=pick("max_concurrent_per_user", settings.training_default_user_concurrency),
        sessions_per_day=pick("max_sessions_per_user_per_day", settings.training_default_sessions_per_day),
        session_minutes=pick("max_session_minutes", settings.training_default_session_minutes),
        monthly_minutes=pick("monthly_minutes", settings.training_default_monthly_minutes),
        platform_concurrency=settings.training_max_concurrent_total,
    )


def month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def local_day_start(now: datetime, tz: str) -> datetime:
    """Start of today in the platform timezone, as naive UTC."""
    z = ZoneInfo(tz)
    local = now.replace(tzinfo=ZoneInfo("UTC")).astimezone(z)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start.astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def consumed():
    """SQL condition: sessions that count against session limits. Open sessions count; finished ones count
    only if the trainee was actually connected, so failed starts give their slot back."""
    return or_(TrainingSession.status.in_(OPEN_SESSION_STATUSES), TrainingSession.connected_at.is_not(None),
               TrainingSession.status == "completed")


def used_seconds_this_month(db: Session, org_id: str, now: datetime) -> tuple[int, int]:
    """(billed seconds this calendar month (UTC), seconds held by open reservations). Billed seconds are
    the usage events plus any later corrections (usage adjustments) made this month."""
    billed = db.scalar(select(func.coalesce(func.sum(TrainingUsageEvent.quantity), 0)).where(
        TrainingUsageEvent.organization_id == org_id, TrainingUsageEvent.metric == "billable_seconds",
        TrainingUsageEvent.created_at >= month_start(now))) or 0
    billed += db.scalar(select(func.coalesce(func.sum(TrainingUsageAdjustment.delta), 0)).where(
        TrainingUsageAdjustment.organization_id == org_id, TrainingUsageAdjustment.metric == "billable_seconds",
        TrainingUsageAdjustment.created_at >= month_start(now))) or 0
    held = db.scalar(select(func.coalesce(func.sum(TrainingUsageReservation.reserved_seconds), 0)).where(
        TrainingUsageReservation.organization_id == org_id,
        TrainingUsageReservation.status.in_(("reserved", "confirmed")))) or 0
    return int(billed), int(held)


@contextmanager
def capacity_lock(db: Session):
    """Serializes capacity checks and reservations. On PostgreSQL a transaction-scoped advisory lock
    makes this hold across every backend instance; it is released at commit or rollback. SQLite (local
    development, one process) uses a process lock instead. The caller must commit inside the block."""
    if db.bind.dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": PG_LOCK_KEY})
        yield
    else:
        with _local_lock:
            yield


def mask_phone(phone: str | None) -> str | None:
    return f"******{phone[-4:]}" if phone and len(phone) >= 4 else None


def webhook_signature(secret: str, session_id: str, org_id: str) -> str:
    return hmac.new(secret.encode(), f"{org_id}:{session_id}".encode(), hashlib.sha256).hexdigest()


# ---------- the engine ----------
class TrainingEngine:
    def __init__(self, settings, sarvam=None, browser_provider=None):
        self.s = settings
        self.sarvam = sarvam
        self.browser_provider = browser_provider  # stays None until the Web SDK contract is verified
        self.intelligence = None  # IntelligenceEngine; queues transcript, evaluation and reconciliation jobs

    # ---------- availability ----------
    def phone_available(self) -> bool:
        s = self.s
        return bool(s.training_phone_enabled and s.training_webhook_secret and s.public_base_url
                    and self.sarvam is not None)

    def browser_available(self) -> bool:
        return bool(self.s.training_browser_enabled and self.browser_provider is not None)

    # ---------- start ----------
    def request_session(self, db: Session, org: Organization, user: User, membership: Membership, agent_id: str,
                        channel: str, scenario_id: str | None, client_request_id: str | None) -> tuple[TrainingSession, bool]:
        """Checks everything, reserves capacity and creates the session in state requested.
        Returns (session, replayed). replayed is True when client_request_id matched an earlier request."""
        if client_request_id:
            prev = db.scalars(select(TrainingSession).where(
                TrainingSession.organization_id == org.id, TrainingSession.user_id == user.id,
                TrainingSession.client_request_id == client_request_id)).first()
            if prev is not None:
                return prev, True
        if channel not in ("phone", "browser"):
            raise TrainingError(422, "bad_channel", "Channel must be phone or browser.")
        limits = effective_limits(db, self.s, org.id)
        if not limits.enabled:
            self._reject(db, org, user, "training_disabled")
            raise TrainingError(403, "training_disabled", "Training is not switched on for this organization.")
        if channel == "phone" and not (limits.phone_enabled and self.phone_available()):
            self._reject(db, org, user, "channel_unavailable", channel=channel)
            raise TrainingError(503, "channel_unavailable", "Phone training is not available yet.")
        if channel == "browser" and not (limits.browser_enabled and self.browser_available()):
            self._reject(db, org, user, "channel_unavailable", channel=channel)
            raise TrainingError(503, "channel_unavailable", "Browser training is not available yet.")
        ents = entitlements(db, org.id, user.id, agent_id)
        if not ents:
            self._reject(db, org, user, "not_assigned", agent_id=agent_id)
            raise TrainingError(404, "not_assigned", "This agent is not assigned to you.")
        ent = ents[0]
        if channel not in (ent.agent.channels or []):
            raise TrainingError(409, "channel_not_offered", f"This agent does not offer {channel} training.")
        scenario = None
        if scenario_id:
            scenario = next((x for x in allowed_scenarios(db, ent) if x.id == scenario_id), None)
            if scenario is None:
                self._reject(db, org, user, "scenario_not_allowed", agent_id=agent_id)
                raise TrainingError(404, "scenario_not_allowed", "This scenario is not available to you.")
        schema = ent.version.variable_schema or []
        schema_names = {v.get("name") for v in schema if isinstance(v, dict)}
        defaults = {v["name"]: v["default"] for v in schema if isinstance(v, dict) and "default" in v}
        variables = {**defaults, **(dict(scenario.agent_variables or {}) if scenario else {})}
        personal = db.scalars(select(TraineeAgentTrainingProfile).where(
            TraineeAgentTrainingProfile.organization_id == org.id,
            TraineeAgentTrainingProfile.user_id == user.id,
            TraineeAgentTrainingProfile.agent_id == ent.agent.id)).first()
        reserved = {"agent_name", "user_name", "trainee_name", "trainee_training_context", "user_training_context"}
        if personal:
            variables.update({k: v for k, v in (personal.variable_values or {}).items()
                              if k in schema_names and k not in reserved})
        # Sarvam rejects undeclared agent variables. Inject runtime identity only when this
        # particular published agent version declares the matching variable locally as well. Old
        # DIDM registrations predate local schemas and use the established `lead_name` contract.
        user_name = (user.name or "").strip() or user.email.split("@", 1)[0]
        for key, value in runtime_identity_variables(schema_names, user_name, ent.agent.name).items():
            # An explicit scenario/persona value is intentional and wins over the signed-in identity.
            variables.setdefault(key, value)
        problems = variables_problems(schema, variables, require_all=True)
        if problems:
            raise TrainingError(422, "invalid_variables", "This scenario no longer matches the agent: " + " ".join(problems))
        if personal:
            parts = []
            if (personal.instructions or "").strip():
                parts.append("TRAINEE INSTRUCTIONS:\n" + personal.instructions.strip())
            for source in personal.sources or []:
                value = str(source.get("text") or "").strip()
                if value:
                    parts.append(f"SOURCE: {source.get('title') or 'Training material'}\n{value}")
            context = "\n\n".join(parts)[:12_000]
            if context:
                # The provider agent must declare and reference one of these variables. Never send an
                # undeclared alias: Sarvam rejects the whole outbound request with HTTP 422.
                if "trainee_training_context" in schema_names:
                    variables["trainee_training_context"] = context
                if "user_training_context" in schema_names:
                    variables["user_training_context"] = context
        phone = None
        if channel == "phone":
            phone = user.phone_e164
            if not phone or membership.verified_phone_e164 != phone:
                raise TrainingError(409, "phone_not_verified",
                                    "Add your phone number in your profile and ask an admin to verify it.")
        minutes = limits.session_minutes
        if ent.max_minutes_per_session:
            minutes = min(minutes, ent.max_minutes_per_session)
        max_seconds = max(60, minutes * 60)
        config = {k: v for k, v in (ent.version.configuration_snapshot or {}).items() if k in PHONE_CONFIG_KEYS
                  and isinstance(v, str)} if channel == "phone" else {}
        now = utcnow()
        try:
            with capacity_lock(db):
                self._check_capacity(db, limits, org.id, user.id, ent, max_seconds, now)
                sess = TrainingSession(
                    organization_id=org.id, user_id=user.id, client_request_id=client_request_id,
                    assignment_ids=[a.id for a in ent.assignments],
                    access_snapshot={"source": ent.source, "max_sessions": ent.max_sessions,
                                     "max_minutes_per_session": ent.max_minutes_per_session,
                                     "allowed_scenario_ids": ent.allowed_scenario_ids,
                                     "expires_at": ent.expires_at.isoformat() if ent.expires_at else None,
                                     "limits": limits.as_dict()},
                    agent_id=ent.agent.id, agent_version_id=ent.version.id, scenario_id=scenario.id if scenario else None,
                    channel=channel, provider=ent.agent.provider, provider_app_id=ent.agent.provider_app_id,
                    provider_app_version=ent.version.provider_app_version, resolved_variables=variables,
                    resolved_configuration=config, phone_last4=phone[-4:] if phone else None, status="requested",
                    max_duration_seconds=max_seconds, created_at=now, updated_at=now)
                db.add(sess)
                db.flush()
                db.add(TrainingUsageReservation(
                    organization_id=org.id, user_id=user.id, session_id=sess.id, channel=channel,
                    reserved_seconds=max_seconds, status="reserved",
                    expires_at=now + timedelta(seconds=self.s.training_start_timeout_seconds)))
                add_event(db, sess, "requested", {"channel": channel, "agent_version_id": ent.version.id})
                db.commit()
        except IntegrityError:
            # The same client_request_id was used by a parallel request a moment ago
            db.rollback()
            prev = db.scalars(select(TrainingSession).where(
                TrainingSession.organization_id == org.id, TrainingSession.user_id == user.id,
                TrainingSession.client_request_id == client_request_id)).first() if client_request_id else None
            if prev is None:
                raise
            return prev, True
        except TrainingError as e:
            db.rollback()
            self._reject(db, org, user, e.code, agent_id=agent_id)
            raise
        slog("training.capacity_reserved", session=sess.id, org=org.id, channel=channel, seconds=max_seconds)
        slog("training.session_requested", session=sess.id, org=org.id, agent=ent.agent.id,
             version=ent.version.id, channel=channel)
        return sess, False

    def _check_capacity(self, db: Session, limits: EffectiveLimits, org_id: str, user_id: str, ent,
                        max_seconds: int, now: datetime):
        """Runs under capacity_lock. Organization caps always apply; assignment limits only narrow them."""
        open_all = db.scalar(select(func.count(TrainingSession.id)).where(
            TrainingSession.status.in_(OPEN_SESSION_STATUSES))) or 0
        if open_all >= limits.platform_concurrency:
            raise TrainingError(429, "platform_busy", "All training lines are busy. Try again in a few minutes.")
        open_org = db.scalar(select(func.count(TrainingSession.id)).where(
            TrainingSession.organization_id == org_id, TrainingSession.status.in_(OPEN_SESSION_STATUSES))) or 0
        if open_org >= limits.org_concurrency:
            raise TrainingError(429, "org_concurrency", "Your organization is using all its training sessions right now.")
        open_user = db.scalar(select(func.count(TrainingSession.id)).where(
            TrainingSession.organization_id == org_id, TrainingSession.user_id == user_id,
            TrainingSession.status.in_(OPEN_SESSION_STATUSES))) or 0
        if open_user >= limits.user_concurrency:
            raise TrainingError(409, "user_concurrency", "You already have a training session in progress.")
        today = db.scalar(select(func.count(TrainingSession.id)).where(
            TrainingSession.organization_id == org_id, TrainingSession.user_id == user_id,
            TrainingSession.created_at >= local_day_start(now, self.s.timezone), consumed())) or 0
        if today >= limits.sessions_per_day:
            raise TrainingError(429, "daily_limit", "You have reached today's training limit.")
        if ent.max_sessions is not None:
            since = min(a.starts_at for a in ent.assignments)
            used = db.scalar(select(func.count(TrainingSession.id)).where(
                TrainingSession.organization_id == org_id, TrainingSession.user_id == user_id,
                TrainingSession.agent_id == ent.agent.id, TrainingSession.created_at >= since, consumed())) or 0
            if used >= ent.max_sessions:
                raise TrainingError(429, "assignment_limit", "You have used all the sessions assigned for this agent.")
        billed, held = used_seconds_this_month(db, org_id, now)
        if billed + held + max_seconds > limits.monthly_minutes * 60:
            raise TrainingError(429, "monthly_minutes", "Your organization has used its training minutes for this month.")

    def _reject(self, db: Session, org, user, code: str, **fields):
        from .auth import audit
        try:
            audit(db, None, "training.session_rejected", actor=user, organization_id=org.id,
                  target_type="training_session", details={"code": code, **fields})
            db.commit()
        except Exception:  # an audit failure must not hide the real answer
            db.rollback()
            log.exception("could not audit a rejected training request")
        slog("training.authorization_denied", org=org.id, code=code, **fields)

    # ---------- phone ----------
    def launch_phone(self, session_id: str) -> TrainingSession:
        """Places the call for a requested phone session. Runs outside any lock; the Sarvam request can
        take a few seconds. Returns the session as it stands afterwards."""
        with SessionLocal() as db:
            sess = db.get(TrainingSession, session_id)
            if not transition(db, session_id, "preparing", started_at=utcnow()):
                return sess
            add_event(db, sess, "preparing")
            db.commit()
            user = db.get(User, sess.user_id)
            m = db.scalars(select(Membership).where(Membership.organization_id == sess.organization_id,
                                                    Membership.user_id == sess.user_id,
                                                    Membership.status == "active")).first()
            phone = user.phone_e164 if user else None
            if m is None or not phone or m.verified_phone_e164 != phone or not phone.endswith(sess.phone_last4 or "#"):
                return self._fail(db, sess, "phone_not_verified", "The phone number changed before the call started.")
            s = self.s
            cfg = sess.resolved_configuration or {}
            target = CallTarget(app_id=sess.provider_app_id, app_version=sess.provider_app_version,
                                connection_id=cfg.get("connection_id") or s.sarvam_connection_id,
                                agent_phone=cfg.get("agent_phone_number") or s.sarvam_agent_phone)
            metadata = {"kind": "training", "session_id": sess.id, "org_id": sess.organization_id,
                        "sig": webhook_signature(s.training_webhook_secret, sess.id, sess.organization_id)}
            url = f"{s.public_base_url}/webhooks/sarvam-training/{s.training_webhook_secret}"
            try:
                res = self.sarvam.start_call(phone, dict(sess.resolved_variables or {}), metadata,
                                             target=target, webhook_url=url)
            except Exception as exc:
                log.exception("training call start crashed session=%s", sess.id)
                return self._fail(db, sess, "provider_unreachable", type(exc).__name__)
            if not res.get("ok"):
                code = "provider_unreachable" if res.get("status_code") is None else "provider_rejected"
                slog("training.provider_error", session=sess.id, code=code, http=res.get("status_code"))
                return self._fail(db, sess, code, f"Sarvam answered {res.get('status_code')}: "
                                                  f"{str(res.get('error') or '')[:300]}")
            attempt = str(res.get("attempt_id"))[:200]
            # The result webhook may already have arrived and finished the session; keep its state then
            if transition(db, sess.id, "connecting", provider_attempt_id=attempt):
                pass
            else:
                db.execute(update(TrainingSession).where(TrainingSession.id == sess.id,
                                                         TrainingSession.provider_attempt_id.is_(None))
                           .values(provider_attempt_id=attempt))
            db.execute(update(TrainingUsageReservation).where(TrainingUsageReservation.session_id == sess.id,
                                                              TrainingUsageReservation.status == "reserved")
                       .values(status="confirmed", updated_at=utcnow()))
            add_event(db, sess, "provider_initiated", {"attempt_id": attempt})
            db.commit()
            slog("training.provider_session_initiated", session=sess.id, org=sess.organization_id)
            db.refresh(sess)
            return sess

    def _fail(self, db: Session, sess: TrainingSession, code: str, reason: str) -> TrainingSession:
        now = utcnow()
        if transition(db, sess.id, "failed", failure_code=code, failure_reason=reason[:500], ended_at=now):
            add_event(db, sess, "failed", {"code": code})
            db.commit()
            slog("training.session_failed", session=sess.id, org=sess.organization_id, code=code)
            self.finalize_usage(sess.id)
            if code == "provider_unreachable" and sess.channel == "phone" and self.intelligence is not None:
                # The start request may have timed out after Sarvam placed the call
                self.intelligence.session_uncertain(sess.id)
        db.refresh(sess)
        return sess

    # ---------- provider results ----------
    def handle_provider_result(self, payload: dict) -> dict:
        """Processes one Sarvam outbound result posted to the training webhook. Safe to run twice, in any
        order, and in parallel. Never raises for bad input; returns retryable=True only for our own faults."""
        meta = ((payload.get("webhook_config") or {}).get("metadata") or {}) if isinstance(payload, dict) else {}
        session_id, org_id, sig = str(meta.get("session_id") or ""), str(meta.get("org_id") or ""), str(meta.get("sig") or "")
        if meta.get("kind") != "training" or not session_id or not org_id:
            return {"ok": False, "reason": "not a training result"}
        good = webhook_signature(self.s.training_webhook_secret, session_id, org_id) if self.s.training_webhook_secret else ""
        if not good or not hmac.compare_digest(sig, good):
            log.warning("training webhook with a bad signature for session=%s", session_id[:36])
            return {"ok": False, "reason": "bad signature"}
        attempt = str(payload.get("attempt_id") or "")[:200] or None
        status = str(payload.get("status") or "unknown").lower()[:60]
        with SessionLocal() as db:
            sess = db.scalars(select(TrainingSession).where(TrainingSession.id == session_id,
                                                           TrainingSession.organization_id == org_id)).first()
            if sess is None:
                return {"ok": False, "reason": "unknown session"}
            if sess.provider_attempt_id and attempt and sess.provider_attempt_id != attempt:
                log.warning("training webhook attempt mismatch session=%s", sess.id)
                return {"ok": False, "reason": "attempt mismatch"}
            event_key = hashlib.sha256(f"result:{attempt or ''}:{status}".encode()).hexdigest()
            safe = {"status": status, "attempt_id": attempt, "duration": payload.get("duration"),
                    "failure_reason": str(payload.get("failure_reason") or "")[:300] or None,
                    "interaction_id": payload.get("interaction_id")}
            ev = add_event(db, sess, "provider_result", safe, provider_event_id=event_key, processed=False)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return {"ok": True, "duplicate": True}
            if sess.status in TERMINAL:
                ev.processed_at = utcnow()
                ev.event_payload = {**safe, "late": True, "session_status": sess.status}
                db.commit()
                log.warning("late training result for %s session=%s", sess.status, sess.id)
                # The session stays as it is; what the provider reported is recorded beside it, and usage is
                # corrected with an adjustment event if it differs from what we billed
                self.reconcile(session_id, {"status": status, "duration": payload.get("duration"),
                                            "attempt_id": attempt, "interaction_id": payload.get("interaction_id")},
                               source="late_webhook")
                if self.intelligence is not None:
                    self.intelligence.session_result(session_id, payload.get("interaction_transcript"),
                                                     payload.get("interaction_id"))
                return {"ok": True, "late": True}
            now = utcnow()
            try:
                duration = max(0, int(round(float(payload.get("duration") or 0))))
            except (TypeError, ValueError):
                duration = 0
            values = {"ended_at": now, "duration_seconds": duration, "provider_status": status,
                      "provider_duration_seconds": duration}
            if attempt and not sess.provider_attempt_id:
                values["provider_attempt_id"] = attempt
            inter = payload.get("interaction_id")
            if inter:
                values["provider_session_id"] = str(inter)[:200]
            if status in CONNECTED_PROVIDER_STATUSES and duration > 0:
                values["connected_at"] = now - timedelta(seconds=duration)
                moved = transition(db, sess.id, "completed", **values)
                kind = "completed"
            else:
                values.update(failure_code=status, failure_reason=safe["failure_reason"] or f"Call {status}")
                moved = transition(db, sess.id, "failed", **values)
                kind = "failed"
            ev.processed_at = utcnow()
            db.commit()
        if moved:
            slog(f"training.session_{kind}", session=session_id, org=org_id, duration=duration)
            self.finalize_usage(session_id, source="provider_result")
            if self.intelligence is not None:
                self.intelligence.session_result(session_id, payload.get("interaction_transcript"), inter)
        return {"ok": True, "status": kind if moved else "unchanged"}

    # ---------- browser (behind TRAINING_BROWSER_ENABLED) ----------
    def authorize_browser(self, db: Session, org: Organization, user: User, session_id: str) -> dict:
        """Gets a single-use provider URL for the trainee's own browser session. Re-checks the assignment,
        because time has passed since the session was requested."""
        if not self.browser_available():
            raise TrainingError(503, "channel_unavailable", "Browser training is not available yet.")
        sess = db.scalars(select(TrainingSession).where(TrainingSession.id == session_id,
                                                        TrainingSession.organization_id == org.id,
                                                        TrainingSession.user_id == user.id)).first()
        if sess is None or sess.channel != "browser":
            raise TrainingError(404, "not_found", "Not found.")
        if sess.status != "requested":
            raise TrainingError(409, "already_authorized", "This session was already started. Start a new one.")
        if not entitlements(db, org.id, user.id, sess.agent_id):
            self._fail(db, sess, "not_assigned", "The assignment ended before the session started.")
            raise TrainingError(403, "not_assigned", "This agent is no longer assigned to you.")
        if not transition(db, sess.id, "preparing", started_at=utcnow()):
            raise TrainingError(409, "already_authorized", "This session was already started. Start a new one.")
        db.commit()
        try:
            grant = self.browser_provider.signed_url(app_id=sess.provider_app_id, app_version=sess.provider_app_version)
        except Exception as exc:
            log.exception("browser authorization failed session=%s", sess.id)
            self._fail(db, sess, "provider_unreachable", type(exc).__name__)
            raise TrainingError(502, "provider_unreachable", "Could not reach the voice service. Try again.")
        url = grant["url"]
        now = utcnow()
        db.add(BrowserSessionToken(organization_id=org.id, session_id=sess.id, user_id=user.id,
                                   token_hash=hashlib.sha256(url.encode()).hexdigest(),
                                   provider_reference_id=str(grant.get("reference_id") or "")[:200] or None,
                                   expires_at=now + timedelta(seconds=int(grant.get("ttl_seconds") or 60))))
        # The grant's reference_id is not an interaction id, so it stays on the token row only; storing it as
        # provider_session_id made the transcript lookup search for the wrong id (phase 5 review)
        transition(db, sess.id, "connecting")
        db.execute(update(TrainingUsageReservation).where(TrainingUsageReservation.session_id == sess.id,
                                                          TrainingUsageReservation.status == "reserved")
                   .values(status="confirmed", updated_at=now))
        add_event(db, sess, "browser_authorized")
        db.commit()
        slog("training.provider_session_initiated", session=sess.id, org=org.id, channel="browser")
        # The URL goes to this one response and nowhere else: not stored, not logged
        return {"session_id": sess.id, "signed_url": url, "max_duration_seconds": sess.max_duration_seconds}

    def browser_event(self, db: Session, sess: TrainingSession, event: str, detail: str = "") -> TrainingSession:
        """The trainee's browser reports what the SDK told it. Times are taken from the server clock, and
        the billed duration is capped at the session's maximum."""
        now = utcnow()
        if event == "connected":
            if transition(db, sess.id, "active", connected_at=now):
                db.execute(update(BrowserSessionToken).where(BrowserSessionToken.session_id == sess.id,
                                                             BrowserSessionToken.used_at.is_(None)).values(used_at=now))
                add_event(db, sess, "browser_connected")
                db.commit()
                slog("training.provider_connected", session=sess.id, org=sess.organization_id, channel="browser")
        elif event == "ended":
            db.refresh(sess)
            secs = int((now - sess.connected_at).total_seconds()) if sess.connected_at else 0
            if transition(db, sess.id, "completed", ended_at=now, duration_seconds=min(secs, sess.max_duration_seconds)):
                add_event(db, sess, "browser_ended")
                db.commit()
                slog("training.session_completed", session=sess.id, org=sess.organization_id, channel="browser")
                self.finalize_usage(sess.id, source="browser_client")
        elif event in ("error", "microphone_denied"):
            code = "microphone_denied" if event == "microphone_denied" else "browser_error"
            self._fail(db, sess, code, detail[:300] or code)
        else:
            raise TrainingError(422, "bad_event", "Unknown browser event.")
        db.refresh(sess)
        return sess

    # ---------- cancel ----------
    def cancel(self, db: Session, sess: TrainingSession, actor: User) -> TrainingSession:
        if sess.status in TERMINAL:
            return sess
        if sess.channel == "phone" and sess.status in ("connecting", "active"):
            raise TrainingError(409, "call_in_progress", "The call is already placed. It ends when the call is hung up.")
        now = utcnow()
        secs = int((now - sess.connected_at).total_seconds()) if sess.connected_at else None
        if transition(db, sess.id, "cancelled", ended_at=now,
                      duration_seconds=min(secs, sess.max_duration_seconds) if secs is not None else None,
                      failure_code="cancelled", failure_reason="Cancelled"):
            add_event(db, sess, "cancelled", {"by": actor.id})
            db.commit()
            self.finalize_usage(sess.id, source="cancelled")
        db.refresh(sess)
        return sess

    # ---------- usage ----------
    def finalize_usage(self, session_id: str, source: str = "provider_result") -> bool:
        """Writes the session's usage once. Exactly one caller wins the conditional update; the unique
        (session_id, metric) constraint backs it up. Returns True for the caller that wrote it."""
        with SessionLocal() as db:
            now = utcnow()
            sess = db.get(TrainingSession, session_id)
            if sess is None or sess.status not in TERMINAL:
                return False
            if sess.status == "timed_out" and sess.connected_at is None and sess.channel == "phone" \
                    and sess.provider_attempt_id:
                # The call was placed but no result came: bill the longest allowed call so quotas stay safe
                billable, source = sess.max_duration_seconds, "timeout_estimate"
            else:
                billable = sess.duration_seconds or 0 if sess.connected_at else 0
            n = db.execute(update(TrainingSession).where(TrainingSession.id == session_id,
                                                         TrainingSession.usage_finalized_at.is_(None))
                           .values(usage_finalized_at=now, billable_seconds=billable)).rowcount
            if n != 1:
                return False
            rows = [("billable_seconds", billable)]
            if sess.connected_at is not None:
                rows.append(("sessions", 1))
            for metric, qty in rows:
                db.add(TrainingUsageEvent(organization_id=sess.organization_id, user_id=sess.user_id,
                                          session_id=sess.id, channel=sess.channel, metric=metric, quantity=qty,
                                          source=source))
            settled = "settled" if sess.connected_at is not None or billable else "released"
            db.execute(update(TrainingUsageReservation).where(
                TrainingUsageReservation.session_id == session_id,
                TrainingUsageReservation.status.in_(("reserved", "confirmed"))).values(status=settled, updated_at=now))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return False
        slog("training.usage_finalized", session=session_id, billable=billable, source=source)
        return True

    # ---------- reconciliation ----------
    def reconcile(self, session_id: str, found: dict, source: str) -> str:
        """Records what the provider says happened on a call we no longer track (late webhook, or the
        Analytics lookup) and corrects usage with an adjustment event. The session's own status never
        changes, and usage events are never edited. Safe to run twice: the second run finds the session
        already reconciled, and the adjustment's unique key stops a double correction.

        found: {status, duration, attempt_id, interaction_id, ...} as the provider reported it.
        Returns matched | corrected | unchanged."""
        from .auth import audit
        status = str(found.get("status") or "unknown").lower()[:60]
        try:
            duration = max(0, int(round(float(found.get("duration") or 0))))
        except (TypeError, ValueError):
            duration = 0
        provider_billable = duration if status in CONNECTED_PROVIDER_STATUSES else 0
        with SessionLocal() as db:
            sess = db.get(TrainingSession, session_id)
            if sess is None or sess.status not in TERMINAL or sess.reconciliation_status in ("matched", "corrected"):
                return "unchanged"
            if sess.usage_finalized_at is None:
                return "unchanged"  # finalize_usage runs first; the sweeper retries
            adjusted = db.scalar(select(func.coalesce(func.sum(TrainingUsageAdjustment.delta), 0)).where(
                TrainingUsageAdjustment.session_id == sess.id,
                TrainingUsageAdjustment.metric == "billable_seconds")) or 0
            internal = (sess.billable_seconds or 0) + adjusted
            delta = provider_billable - internal
            evidence = {"provider_status": status, "provider_duration_seconds": duration,
                        "attempt_id": str(found.get("attempt_id") or "")[:200] or None,
                        "interaction_id": str(found.get("interaction_id") or "")[:200] or None,
                        "billed_before_seconds": internal, "reserved_seconds": sess.max_duration_seconds,
                        "source": source}
            for k in ("failure_reason", "ended_by"):
                if found.get(k):
                    evidence[k] = str(found[k])[:300]
            outcome = "corrected" if delta else "matched"
            values = {"provider_status": status, "provider_duration_seconds": duration,
                      "reconciliation_status": outcome, "reconciled_at": utcnow()}
            if evidence["interaction_id"] and not sess.provider_session_id:
                values["provider_session_id"] = evidence["interaction_id"]
            if evidence["attempt_id"] and not sess.provider_attempt_id:
                values["provider_attempt_id"] = evidence["attempt_id"]
            n = db.execute(update(TrainingSession).where(
                TrainingSession.id == sess.id,
                or_(TrainingSession.reconciliation_status.is_(None),
                    TrainingSession.reconciliation_status.in_(("pending", "unresolved")))).values(**values)).rowcount
            if n != 1:
                db.rollback()
                return "unchanged"
            if delta:
                db.add(TrainingUsageAdjustment(organization_id=sess.organization_id, user_id=sess.user_id,
                                               session_id=sess.id, metric="billable_seconds", delta=delta,
                                               reason="provider_reconciliation", source=source, evidence=evidence))
            add_event(db, sess, "reconciliation", {**evidence, "outcome": outcome, "delta_seconds": delta})
            audit(db, None, "training.usage_reconciled", organization_id=sess.organization_id,
                  target_type="training_session", target_id=sess.id,
                  details={"outcome": outcome, "delta_seconds": delta, "source": source})
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                return "unchanged"
        slog("training.reconciled", session=session_id, outcome=outcome, delta=delta, source=source)
        return outcome

    # ---------- housekeeping ----------
    def sweep(self, now: datetime | None = None) -> dict:
        """Fails sessions that never reached the provider, times out sessions whose result never came,
        and reclaims capacity. Run every minute by the scheduler; safe to run anywhere, any number of times."""
        now = now or utcnow()
        out = {"start_timeouts": 0, "timed_out": 0, "reservations_expired": 0}
        start_cutoff = now - timedelta(seconds=self.s.training_start_timeout_seconds)
        grace = timedelta(minutes=self.s.training_end_grace_minutes)
        with SessionLocal() as db:
            stuck = db.scalars(select(TrainingSession).where(
                TrainingSession.status.in_(("requested", "preparing")), TrainingSession.created_at < start_cutoff)).all()
            for sess in stuck:
                if transition(db, sess.id, "failed", failure_code="start_timeout",
                              failure_reason="The session did not start in time.", ended_at=now):
                    add_event(db, sess, "start_timeout")
                    db.execute(update(TrainingUsageReservation).where(
                        TrainingUsageReservation.session_id == sess.id,
                        TrainingUsageReservation.status == "reserved").values(status="expired", updated_at=now))
                    db.commit()
                    out["start_timeouts"] += 1
                    out["reservations_expired"] += 1
                    self.finalize_usage(sess.id, source="timeout")
            running = db.scalars(select(TrainingSession).where(
                TrainingSession.status.in_(("connecting", "active")))).all()
            for sess in running:
                began = sess.connected_at or sess.started_at or sess.created_at
                if began + timedelta(seconds=sess.max_duration_seconds) + grace > now:
                    continue
                secs = int((now - sess.connected_at).total_seconds()) if sess.connected_at else None
                if transition(db, sess.id, "timed_out", ended_at=now, failure_code="timed_out",
                              failure_reason="No result arrived from the voice service.",
                              duration_seconds=min(secs, sess.max_duration_seconds) if secs is not None else None):
                    add_event(db, sess, "timed_out")
                    db.commit()
                    out["timed_out"] += 1
                    slog("training.session_timed_out", session=sess.id, org=sess.organization_id)
                    self.finalize_usage(sess.id, source="timeout")
                    if sess.channel == "phone" and self.intelligence is not None:
                        self.intelligence.session_uncertain(sess.id)
            # A session that ended without finalizing (a crash in between) gets its usage written now
            for sid in db.scalars(select(TrainingSession.id).where(TrainingSession.status.in_(TERMINAL),
                                                                   TrainingSession.usage_finalized_at.is_(None))).all():
                self.finalize_usage(sid, source="recovered")
        return out

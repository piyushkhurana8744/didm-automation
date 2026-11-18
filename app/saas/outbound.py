"""Read-only import of all outbound attempts for registered phone agents.

Never invokes Automation.handle_result: external calls must not change Excel rows,
trigger WhatsApp messages, or advance the calling queue.
"""
import logging
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ..db import SessionLocal, utcnow
from .models import Agent, Organization, OutboundCall, OutboundSyncState
from .intelligence import JobRetry
from .providers import SarvamAnalytics

log = logging.getLogger("didm.outbound")


def parse_time(value):
    if not value:
        return None
    result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return result.astimezone(timezone.utc).replace(tzinfo=None) if result.tzinfo else result


class OutboundHistory:
    def __init__(self, settings, analytics=None):
        self.s = settings
        self.analytics = analytics or SarvamAnalytics(settings)
        self.lock = threading.Lock()

    def configured(self):
        return bool(self.s.sarvam_api_key and self.s.sarvam_org_id and self.s.sarvam_workspace_id)

    def run(self, organization_id=None):
        if not self.configured():
            return {"configured": False, "running": False}
        if not self.lock.acquire(blocking=False):
            return {"configured": True, "running": True}
        try:
            with SessionLocal() as db:
                query = select(Agent).join(Organization, Agent.organization_id == Organization.id).where(
                    Agent.status == "active", Agent.provider == "sarvam", Organization.status == "active")
                if organization_id:
                    query = query.where(Agent.organization_id == organization_id)
                agents = [a for a in db.scalars(query) if "phone" in (a.channels or [])]
            for agent in agents:
                self.sync_agent(agent)
            return {"configured": True, "running": False}
        finally:
            self.lock.release()

    def sync_agent(self, agent):
        now = utcnow()
        try:
            with SessionLocal() as db:
                state = db.get(OutboundSyncState, agent.id)
                if state is None:
                    state = OutboundSyncState(agent_id=agent.id, window_start=now-timedelta(days=30),
                                              window_end=now, offset=0, retry_at=now)
                    db.add(state)
                    db.commit()
                if state.retry_at > now:
                    return
                # Five pages per pass; unfinished windows resume at their saved offset.
                for _ in range(5):
                    page = self.analytics.list_outbound(agent.provider_app_id, state.window_start,
                                                       state.window_end, state.offset)
                    items = page.get("items") or []
                    for item in items:
                        if item.get("channel_direction") != "outbound" or not item.get("attempt_id"):
                            continue
                        started = parse_time(item.get("start_datetime") or item.get("attempted_at"))
                        if not started:
                            continue
                        row = db.scalar(select(OutboundCall).where(OutboundCall.agent_id == agent.id,
                            OutboundCall.attempt_id == str(item["attempt_id"])))
                        if row is None:
                            row = OutboundCall(organization_id=agent.organization_id, agent_id=agent.id,
                                attempt_id=str(item["attempt_id"]), started_at=started, transcript={},
                                transcript_retry_at=now)
                            db.add(row)
                        row.phone = str(item.get("user_contact") or item.get("user_contact_masked") or "")
                        row.status = str(item.get("connectivity_status") or "unknown").lower()
                        row.interaction_id = item.get("interaction_id") or row.interaction_id
                        row.started_at, row.finished_at = started, parse_time(item.get("end_datetime"))
                        duration = item.get("duration_in_seconds")
                        row.duration = round(float(duration)) if duration is not None else None
                        row.campaign_id = item.get("campaign_id")
                        reason = item.get("failure_reason")
                        row.failure_reason = None if reason == "NO_FAILURE_REASON" else reason
                        row.variables = item.get("agent_variables") or {}
                    state.offset += len(items)
                    more = bool(page.get("next_page_uri")) or state.offset < int(page.get("total") or 0)
                    if more and not items:
                        raise JobRetry("provider_invalid_page", "Empty page before the end of history.")
                    if not more:
                        state.last_synced_at = now
                        state.window_start = state.window_end - timedelta(hours=2)
                        state.window_end = now
                        state.offset = 0
                    state.error = None
                    state.retry_at = now + timedelta(seconds=60)
                    db.commit()
                    if not more:
                        break
                # Retry delayed transcripts even when their original list window is already complete.
                pending = db.scalars(select(OutboundCall).where(OutboundCall.agent_id == agent.id,
                    OutboundCall.interaction_id.is_not(None), OutboundCall.finished_at.is_not(None),
                    OutboundCall.transcript_retry_at <= now).order_by(OutboundCall.transcript_retry_at).limit(20)).all()
                for call in pending:
                    if call.transcript:
                        continue
                    sess = SimpleNamespace(provider_app_id=agent.provider_app_id,
                        provider_session_id=call.interaction_id, started_at=call.started_at,
                        max_duration_seconds=max(call.duration or 0, 7200))
                    try:
                        call.transcript = self.analytics.conversation(sess)
                        call.transcript_retry_at = now + timedelta(days=36500)
                    except JobRetry as exc:
                        call.transcript_retry_at = now + timedelta(seconds=max(60, exc.retry_after or 300))
                        if exc.code != "transcript_not_ready":
                            raise
                    db.commit()
        except (JobRetry, IntegrityError) as exc:
            with SessionLocal() as db:
                state = db.get(OutboundSyncState, agent.id)
                if state:
                    state.error = exc.code if isinstance(exc, JobRetry) else "sync_conflict"
                    state.retry_at = now + timedelta(seconds=max(60, getattr(exc, "retry_after", None) or 60))
                    db.commit()
        except Exception:
            log.exception("Outbound history sync failed for agent %s", agent.id)
            with SessionLocal() as db:
                state = db.get(OutboundSyncState, agent.id)
                if state:
                    state.error, state.retry_at = "sync_failed", now + timedelta(minutes=5)
                    db.commit()

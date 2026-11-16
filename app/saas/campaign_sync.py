"""Recover completed campaign results when the provider webhook is delayed or lost."""
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import select

from ..db import Batch, CallAttempt, SessionLocal, utcnow
from .intelligence import JobRetry

log = logging.getLogger("didm.campaign_sync")


class CampaignSync:
    def __init__(self, automation, analytics):
        self.auto, self.analytics = automation, analytics
        self.retry_at = utcnow()

    def run(self):
        now = utcnow()
        if now < self.retry_at:
            return
        with SessionLocal() as db:
            rows = db.execute(select(CallAttempt, Batch).join(Batch, CallAttempt.batch_id == Batch.id)
                .where(CallAttempt.dry_run.is_(False), CallAttempt.attempt_id.is_not(None),
                       Batch.provider_app_id.is_not(None), CallAttempt.state.in_(("calling", "stuck", "done")),
                       CallAttempt.started_at > now - timedelta(hours=24))
                .order_by(CallAttempt.started_at.desc()).limit(20)).all()
        for call, batch in rows:
            raw = call.raw_result or {}
            if call.state == "done" and (raw.get("interaction_transcript") or raw.get("transcript")
                                          or call.status != "connected"):
                continue
            sess = SimpleNamespace(provider_app_id=batch.provider_app_id, provider_attempt_id=call.attempt_id,
                provider_session_id=raw.get("interaction_id"), started_at=call.started_at,
                max_duration_seconds=max(call.duration or 0, 7200))
            try:
                result = self.analytics.find_attempt(sess)
                if not result or not result.get("end_datetime"):
                    continue  # connected alone is not evidence that a call has ended
                ended = datetime.fromisoformat(str(result["end_datetime"]).replace("Z", "+00:00"))
                if ended.tzinfo:
                    ended = ended.astimezone(timezone.utc).replace(tzinfo=None)
                if ended > now or result["status"] not in ("connected", "no_answer", "busy", "failed"):
                    continue
                payload = {**result, "webhook_config": {"metadata": {"call_id": str(call.id)}},
                           "result_source": "analytics"}
                # Persist completion before the separate, potentially slower transcript lookup.
                if call.state != "done":
                    self.auto.handle_result(payload)
                sess.provider_session_id = result.get("interaction_id") or sess.provider_session_id
                if sess.provider_session_id and result["status"] == "connected":
                    transcript = self.analytics.fetch(sess)
                    if transcript:
                        self.auto.handle_result({"attempt_id": call.attempt_id,
                            "interaction_id": sess.provider_session_id, "interaction_transcript": transcript})
            except JobRetry as exc:
                if exc.code != "transcript_not_ready":
                    self.retry_at = now + timedelta(seconds=max(60, exc.retry_after or 0))
                    log.warning("Campaign lookup delayed: %s", exc.code)
                    return
            except Exception:
                log.exception("Campaign result synchronization failed for call %s", call.id)

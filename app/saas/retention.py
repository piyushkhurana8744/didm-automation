"""Data retention: one daily job that removes what each organization's policy says has expired.

Rules:
- Tenant-scoped: every category is counted and removed per organization, and each organization gets its
  own retention_runs row. A legal hold on an organization stops every removal for it, recordings included.
- Report first: with RETENTION_ENFORCEMENT_ENABLED off (the default) the job only counts what is due.
  No category, including recordings, is deleted until enforcement is explicitly enabled.
- Idempotent: removed rows are marked (purged_at, redacted_at, deleted) or gone, so a second run finds
  nothing; a failed deletion is counted, kept and retried on the next run.
- Nothing here touches the lead-calling (legacy) tables except training webhook bodies, which are
  training data that only passed through the shared webhook store.

What each category removes:
- transcripts: the turns of transcripts older than transcript_retention_days (empty keeps them), and the
  quotes and explanations in that session's evaluations. Scores, coaching feedback and usage stay.
- recordings: the audio object and the row's storage details, on retention_until.
- webhook_payloads: raw training webhook bodies (transcript, phone number) older than
  TRAINING_WEBHOOK_PAYLOAD_DAYS, replaced by a summary of ids and keys.
- browser_tokens: browser voice authorization metadata older than BROWSER_TOKEN_RETENTION_DAYS.
- phone_challenges: phone verification codes (hashes) expired more than PHONE_CHALLENGE_RETENTION_DAYS ago.
"""
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ..db import SessionLocal, WebhookEvent, utcnow
from .auth import audit
from .intelligence import redact_evaluation, slog
from .models import (BrowserSessionToken, Organization, PhoneVerificationChallenge, RetentionRun, TrainingEvaluation,
                     TrainingOrgSettings, TrainingRecording, TrainingSession, TrainingTranscript,
                     TrainingTranscriptTurn)

log = logging.getLogger("didm.retention")

CATEGORIES = ("transcripts", "recordings", "webhook_payloads", "browser_tokens", "phone_challenges")
MAX_DELETE_ATTEMPTS = 5
BATCH = 500


def _counts() -> dict:
    return {c: {"due": 0, "removed": 0, "failed": 0} for c in CATEGORIES}


class RetentionService:
    def __init__(self, settings, recordings=None):
        self.s = settings
        self.recordings = recordings

    # ---------- per category: (due rows) ----------
    def _transcripts_due(self, db: Session, org_id: str, st: TrainingOrgSettings | None, now: datetime):
        if not st or not st.transcript_retention_days:
            return []
        cutoff = now - timedelta(days=st.transcript_retention_days)
        return db.scalars(select(TrainingTranscript).join(TrainingSession, TrainingSession.id == TrainingTranscript.session_id)
                          .where(TrainingTranscript.organization_id == org_id, TrainingTranscript.purged_at.is_(None),
                                 func.coalesce(TrainingSession.ended_at, TrainingSession.created_at) < cutoff)
                          .limit(BATCH)).all()

    def _recordings_due(self, db: Session, org_id: str, now: datetime):
        return db.scalars(select(TrainingRecording).where(
            TrainingRecording.organization_id == org_id, TrainingRecording.status == "stored",
            TrainingRecording.retention_until < now,
            TrainingRecording.delete_attempts < MAX_DELETE_ATTEMPTS).limit(BATCH)).all()

    def _webhooks_due(self, db: Session, org_id: str, now: datetime):
        days = self.s.training_webhook_payload_days
        if days <= 0:
            return []
        rows = db.scalars(select(WebhookEvent).where(
            WebhookEvent.source == "training_result", WebhookEvent.redacted_at.is_(None),
            WebhookEvent.status.in_(("done", "dead")), WebhookEvent.created_at < now - timedelta(days=days))
            .limit(BATCH * 4)).all()
        return [r for r in rows if _webhook_org(r.payload) == org_id]

    def _browser_due(self, db: Session, org_id: str, now: datetime):
        return db.scalars(select(BrowserSessionToken).where(
            BrowserSessionToken.organization_id == org_id,
            BrowserSessionToken.expires_at < now - timedelta(days=self.s.browser_token_retention_days)).limit(BATCH)).all()

    def _challenges_due(self, db: Session, org_id: str, now: datetime):
        return db.scalars(select(PhoneVerificationChallenge).where(
            PhoneVerificationChallenge.organization_id == org_id,
            PhoneVerificationChallenge.expires_at < now - timedelta(days=self.s.phone_challenge_retention_days))
            .limit(BATCH)).all()

    # ---------- the run ----------
    def run(self, now: datetime | None = None, enforce: bool | None = None, org_id: str | None = None) -> list[dict]:
        """Runs for every organization (or one). Returns one summary per organization."""
        now = now or utcnow()
        enforce = self.s.retention_enforcement_enabled if enforce is None else enforce
        with SessionLocal() as db:
            q = select(Organization.id)
            if org_id:
                q = q.where(Organization.id == org_id)
            org_ids = list(db.scalars(q))
        out = []
        for oid in org_ids:
            try:
                out.append(self.run_org(oid, now, enforce))
            except Exception as exc:
                log.exception("retention run failed org=%s", oid)
                with SessionLocal() as db:
                    db.add(RetentionRun(organization_id=oid, enforced=enforce, status="failed", counts={},
                                        error=type(exc).__name__, started_at=now, finished_at=utcnow()))
                    db.commit()
                out.append({"organization_id": oid, "status": "failed"})
        # Orphaned training webhook bodies (no organization in their metadata) are only ever reported
        return out

    def preview(self, org_id: str, now: datetime | None = None) -> dict:
        """What a run would find due now. Changes nothing and records nothing."""
        return self.run_org(org_id, now or utcnow(), enforce=False, preview=True)

    def run_org(self, org_id: str, now: datetime, enforce: bool, preview: bool = False) -> dict:
        counts = _counts()
        with SessionLocal() as db:
            st = db.get(TrainingOrgSettings, org_id)
            held = bool(st and st.legal_hold)
            due = {"transcripts": self._transcripts_due(db, org_id, st, now),
                   "recordings": self._recordings_due(db, org_id, now),
                   "webhook_payloads": self._webhooks_due(db, org_id, now),
                   "browser_tokens": self._browser_due(db, org_id, now),
                   "phone_challenges": self._challenges_due(db, org_id, now)}
            for k, rows in due.items():
                counts[k]["due"] = len(rows)
            if preview:
                db.rollback()
                return {"organization_id": org_id, "status": "held" if held else "preview", "enforced": False,
                        "counts": counts}
            if not held and enforce:
                self._remove_recordings(db, due["recordings"], counts["recordings"], now)
                self._purge_transcripts(db, due["transcripts"], counts["transcripts"], now)
                for r in due["webhook_payloads"]:
                    r.payload, r.redacted_at = _webhook_summary(r.payload), now
                    counts["webhook_payloads"]["removed"] += 1
                for k in ("browser_tokens", "phone_challenges"):
                    for r in due[k]:
                        db.delete(r)
                        counts[k]["removed"] += 1
            removed = sum(c["removed"] for c in counts.values())
            failed = sum(c["failed"] for c in counts.values())
            status = "held" if held else ("partial" if failed else "completed")
            run = RetentionRun(organization_id=org_id, enforced=enforce, status=status, counts=counts,
                               started_at=now, finished_at=utcnow())
            db.add(run)
            if removed or failed:
                audit(db, None, "retention.applied", organization_id=org_id, target_type="retention_run",
                      target_id=None, details={"counts": counts, "enforced": enforce})
            db.commit()
            slog("training.retention_run", org=org_id, status=status, enforced=enforce, removed=removed, failed=failed)
            return {"organization_id": org_id, "run_id": run.id, "status": status, "enforced": enforce,
                    "counts": counts}

    def _remove_recordings(self, db: Session, rows, c: dict, now: datetime):
        for rec in rows:
            try:
                if self.recordings is None or self.recordings.provider_for_recording(rec) is None:
                    raise RuntimeError("store_not_configured")
                self.recordings.delete(db, rec, "Retention period ended.")
                db.flush()
                c["removed"] += 1
            except Exception as exc:
                rec.delete_attempts = (rec.delete_attempts or 0) + 1
                rec.last_error = (getattr(exc, "code", None) or str(exc) or type(exc).__name__)[:120]
                rec.updated_at = now
                c["failed"] += 1
                log.warning("recording deletion failed recording=%s attempt=%s", rec.id, rec.delete_attempts)

    def _purge_transcripts(self, db: Session, rows, c: dict, now: datetime):
        for t in rows:
            db.execute(delete(TrainingTranscriptTurn).where(TrainingTranscriptTurn.transcript_id == t.id,
                                                            TrainingTranscriptTurn.organization_id == t.organization_id))
            t.purged_at, t.updated_at = now, now
            for e in db.scalars(select(TrainingEvaluation).where(TrainingEvaluation.session_id == t.session_id,
                                                                 TrainingEvaluation.organization_id == t.organization_id)):
                redact_evaluation(e, now)
            c["removed"] += 1

    # ---------- reporting ----------
    def latest(self, db: Session, org_id: str, limit: int = 10) -> list[dict]:
        rows = db.scalars(select(RetentionRun).where(RetentionRun.organization_id == org_id)
                          .order_by(RetentionRun.started_at.desc()).limit(limit)).all()
        return [{"id": r.id, "status": r.status, "enforced": r.enforced, "counts": r.counts, "error": r.error,
                 "started_at": r.started_at.isoformat(), "finished_at": r.finished_at.isoformat() if r.finished_at else None}
                for r in rows]


def _webhook_org(payload) -> str | None:
    if not isinstance(payload, dict):
        return None
    meta = (payload.get("webhook_config") or {}).get("metadata") or {}
    return meta.get("org_id") if isinstance(meta, dict) else None


def _webhook_summary(payload) -> dict:
    """What stays of a training webhook body: ids for tracing, never transcript text or phone numbers."""
    p = payload if isinstance(payload, dict) else {}
    meta = (p.get("webhook_config") or {}).get("metadata") or {}
    return {"redacted": True, "attempt_id": p.get("attempt_id"), "interaction_id": p.get("interaction_id"),
            "status": p.get("status"), "session_id": meta.get("session_id") if isinstance(meta, dict) else None,
            "org_id": meta.get("org_id") if isinstance(meta, dict) else None, "keys": sorted(map(str, p.keys()))[:50]}

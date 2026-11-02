"""Durable webhook intake.

Every delivery is written to webhook_events before anything else happens. Then either:
- inline mode (default, matches the old behaviour): the event is processed in a worker thread and the
  result is returned to the caller, or
- queued mode: the caller gets 200 "accepted" straight away and a background worker processes it.

In both modes a failed event is retried by the background worker with backoff, up to
WEBHOOK_MAX_ATTEMPTS, then marked "dead" for an admin to retry. Processing is idempotent because the
handlers are: a call result can only move a call to done once, and a WhatsApp needs a unique claim.
"""
import hashlib
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from sqlalchemy import or_, select, update

from .db import SessionLocal, WebhookEvent, utcnow

log = logging.getLogger("didm.webhooks")

SOURCES = ("sarvam_result", "event_call", "training_result")
STALE_LOCK = timedelta(minutes=5)


def _hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def backoff(attempt: int) -> timedelta:
    """30 s, 60 s, 120 s ... capped at 30 minutes."""
    return timedelta(seconds=min(30 * 2 ** max(attempt - 1, 0), 1800))


class WebhookProcessor:
    def __init__(self, automation, max_attempts: int = 5, workers: int = 4, poll_seconds: float = 2.0):
        self.auto = automation
        self.max_attempts = max_attempts
        self.workers = max(1, workers)
        self.poll_seconds = poll_seconds
        self._stop = threading.Event()
        self._thread = None
        self._pool = None
        # Extra sources registered by other modules (the training engine registers "training_result")
        self.handlers = {}

    # ---------- intake ----------
    def record(self, source: str, payload: dict) -> str:
        """Stores one delivery and returns its id. Raises if the database write fails, so the caller
        answers with an error and the provider can redeliver."""
        if source not in SOURCES:
            raise ValueError(f"unknown webhook source {source}")
        event_id = str(uuid.uuid4())
        attempt_id = payload.get("attempt_id") if isinstance(payload, dict) else None
        with SessionLocal() as session:
            session.add(WebhookEvent(id=event_id, source=source, payload=payload, payload_hash=_hash(payload),
                                     attempt_id=str(attempt_id)[:64] if attempt_id else None, status="pending",
                                     attempts=0, next_attempt_at=utcnow()))
            session.commit()
        log.info("webhook accepted event=%s source=%s attempt=%s", event_id, source, attempt_id)
        return event_id

    # ---------- processing ----------
    def _claim(self, event_id: str) -> bool:
        now = utcnow()
        with SessionLocal() as session:
            n = session.execute(update(WebhookEvent).where(
                WebhookEvent.id == event_id,
                or_(WebhookEvent.status.in_(("pending", "failed")),
                    (WebhookEvent.status == "processing") & (WebhookEvent.locked_at < now - STALE_LOCK)),
            ).values(status="processing", locked_at=now, attempts=WebhookEvent.attempts + 1,
                     updated_at=now)).rowcount
            session.commit()
        return n == 1

    def process(self, event_id: str) -> dict | None:
        """Runs one event. Returns the handler result, or None if another worker holds it."""
        if not self._claim(event_id):
            return None
        with SessionLocal() as session:
            ev = session.get(WebhookEvent, event_id)
            source, payload, attempts = ev.source, ev.payload, ev.attempts
        if source in self.handlers:
            handler = self.handlers[source]
        elif source == "sarvam_result":
            handler = self.auto.handle_result
        elif source == "event_call":
            handler = self.auto.handle_event_call
        else:
            raise ValueError(f"no handler for webhook source {source}")
        try:
            result = handler(payload)
            error = "handler asked for a retry" if result.get("retryable") else None
        except Exception as exc:  # recorded and retried, never swallowed
            log.exception("webhook failed event=%s source=%s try=%s", event_id, source, attempts)
            result, error = {"ok": False, "reason": "processing error, will retry"}, f"{type(exc).__name__}: {exc}"
        self._finish(event_id, attempts, result, error)
        return result

    def _finish(self, event_id: str, attempts: int, result: dict, error: str | None):
        now = utcnow()
        values = {"locked_at": None, "updated_at": now, "result": result}
        if error is None:
            values["status"] = "done"
            values["last_error"] = None
        elif attempts >= self.max_attempts:
            values.update(status="dead", last_error=error[:2000])
            log.error("webhook dead event=%s after %s tries: %s", event_id, attempts, error)
        else:
            values.update(status="failed", last_error=error[:2000], next_attempt_at=now + backoff(attempts))
            log.warning("webhook retry scheduled event=%s try=%s: %s", event_id, attempts, error)
        with SessionLocal() as session:
            session.execute(update(WebhookEvent).where(WebhookEvent.id == event_id).values(**values))
            session.commit()

    def due_events(self, limit: int = 50) -> list[str]:
        now = utcnow()
        with SessionLocal() as session:
            return list(session.scalars(select(WebhookEvent.id).where(or_(
                (WebhookEvent.status.in_(("pending", "failed"))) & (WebhookEvent.next_attempt_at <= now),
                (WebhookEvent.status == "processing") & (WebhookEvent.locked_at < now - STALE_LOCK),
            )).order_by(WebhookEvent.created_at).limit(limit)))

    def drain(self, max_rounds: int = 100) -> int:
        """Processes every due event now, in parallel, 50 at a time. Used by the worker loop and by tests."""
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="webhook")
        done = 0
        for _ in range(max_rounds):
            ids = self.due_events()
            if not ids:
                break
            n = sum(1 for r in self._pool.map(self.process, ids) if r is not None)
            done += n
            if n == 0:  # everything due is held by another worker
                break
        return done

    def retry(self, event_id: str) -> bool:
        """Admin action: puts a dead or failed event back in the queue with a fresh try count."""
        with SessionLocal() as session:
            n = session.execute(update(WebhookEvent).where(
                WebhookEvent.id == event_id, WebhookEvent.status.in_(("dead", "failed"))
            ).values(status="pending", attempts=0, next_attempt_at=utcnow(), updated_at=utcnow())).rowcount
            session.commit()
        return n == 1

    # ---------- background loop ----------
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="webhook-worker", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=10)
        if self._pool:
            self._pool.shutdown(wait=False)
            self._pool = None

    def _run(self):
        while not self._stop.is_set():
            try:
                self.drain()
            except Exception:
                log.exception("webhook worker loop error")
            self._stop.wait(self.poll_seconds)

"""The automation itself: dial batches, take call results, send WhatsApp, retry, alert, report."""
import logging
import threading
import uuid
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .db import (Alert, Batch, CallAttempt, SessionLocal, WhatsAppClaim, WhatsAppMessage, get_flag, set_flag,
                 utcnow)
from .leads import BLOCK_OUTCOMES, Lead, digits_only, pick_next, to_e164

log = logging.getLogger("didm")


class Automation:
    def __init__(self, settings: Settings, sheet, sarvam, veblika, mailer, clock=None):
        self.s = settings
        self.sheet = sheet
        self.sarvam = sarvam
        self.veblika = veblika
        self.mailer = mailer
        self.tz = ZoneInfo(settings.timezone)
        self._clock = clock  # tests pass a fixed clock
        self._lock = threading.RLock()

    # ---------- time and limits ----------
    def now_local(self) -> datetime:
        if self._clock:
            return self._clock()
        return datetime.now(self.tz).replace(tzinfo=None)

    def within_calling_hours(self) -> bool:
        h = self.now_local().hour
        return self.s.calling_start_hour <= h < self.s.calling_end_hour

    def _today_start_utc(self) -> datetime:
        local_midnight = self.now_local().replace(hour=0, minute=0, second=0, microsecond=0)
        return local_midnight.replace(tzinfo=self.tz).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)

    def calls_today(self, session) -> int:
        return session.scalar(select(func.count(CallAttempt.id)).where(
            CallAttempt.started_at >= self._today_start_utc())) or 0

    def is_stopped(self, session) -> bool:
        return get_flag(session, "stopped", "0") == "1"

    # ---------- alerts ----------
    def alert(self, session, level: str, message: str):
        log.log(logging.ERROR if level == "error" else logging.WARNING if level == "warn" else logging.INFO, message)
        a = Alert(level=level, message=message)
        session.add(a)
        session.commit()
        if level == "error":
            a.emailed = self.mailer.send(f"[DIDM automation] {message[:80]}", message)
            session.commit()

    # ---------- reading leads ----------
    def load_leads(self) -> list[Lead]:
        return [Lead.from_row(r, vals) for r, vals in self.sheet.read_rows()]

    # ---------- batches ----------
    def start_batch(self, count: int, min_row: int | None = None, max_row: int | None = None) -> dict:
        with self._lock, SessionLocal() as session:
            if self.is_stopped(session):
                return {"ok": False, "reason": "Stopped. Send resume first."}
            if not self.within_calling_hours():
                return {"ok": False, "reason": f"Outside calling hours ({self.s.calling_start_hour}:00 to {self.s.calling_end_hour}:00)."}
            if not self.s.dry_run:
                missing = self.s.missing_for_live()
                if missing:
                    return {"ok": False, "reason": "Missing settings: " + ", ".join(missing)}
            for b in session.scalars(select(Batch).where(Batch.active.is_(True))):
                b.active, b.finished_at, b.note = False, utcnow(), "replaced by a new batch"
            batch = Batch(requested=max(1, int(count)), min_row=min_row, max_row=max_row)
            session.add(batch)
            session.commit()
            batch_id = batch.id
        started = self.fill_slots()
        return {"ok": True, "batch_id": batch_id, "dialled_now": started, "dry_run": self.s.dry_run}

    def auto_dial(self) -> dict:
        """Timer job: keeps calling new leads on its own during calling hours, like Make's schedule."""
        with self._lock, SessionLocal() as session:
            if self.is_stopped(session) or not self.within_calling_hours():
                return {"ok": False, "reason": "stopped or outside calling hours"}
            if session.scalars(select(Batch).where(Batch.active.is_(True))).first():
                active = True
            else:
                active = False
                if self.calls_today(session) >= self.s.daily_call_cap:
                    return {"ok": False, "reason": "daily cap reached"}
                try:
                    leads = self.load_leads()
                except Exception as exc:
                    self.alert(session, "error", f"Could not read the Leads sheet: {exc}")
                    return {"ok": False, "reason": "sheet unreadable"}
                busy_rows, busy_phones = self._busy(session)
                if pick_next(leads, self.now_local(), self.s.max_attempts,
                             timedelta(minutes=self.s.retry_gap_minutes),
                             exclude_rows=busy_rows, exclude_phones=busy_phones) is None:
                    return {"ok": False, "reason": "no leads waiting"}
        if active:
            return {"ok": True, "dialled_now": self.fill_slots()}
        return self.start_batch(self.s.auto_dial_batch)

    def stop(self) -> dict:
        with self._lock, SessionLocal() as session:
            set_flag(session, "stopped", "1")
            for b in session.scalars(select(Batch).where(Batch.active.is_(True))):
                b.active, b.finished_at, b.note = False, utcnow(), "stopped"
            session.commit()
            self.alert(session, "info", "Calling stopped by admin.")
        return {"ok": True, "stopped": True}

    def resume(self) -> dict:
        with SessionLocal() as session:
            set_flag(session, "stopped", "0")
        return {"ok": True, "stopped": False}

    def fill_slots(self) -> int:
        """Dials leads from the active batch until parallel, daily and batch limits are reached."""
        started = 0
        with self._lock, SessionLocal() as session:
            batch = session.scalars(select(Batch).where(Batch.active.is_(True)).order_by(Batch.id.desc())).first()
            if not batch:
                return 0

            def close(note):
                batch.active, batch.finished_at, batch.note = False, utcnow(), note
                session.commit()

            if self.is_stopped(session):
                close("stopped")
                return 0
            leads = None
            failures_in_a_row = 0
            while True:
                if batch.dialled >= batch.requested:
                    if self._in_flight(session) == 0:
                        close("finished")
                    return started
                if not self.within_calling_hours():
                    close("calling hours ended")
                    self.alert(session, "info", f"Batch {batch.id} paused: calling hours ended.")
                    return started
                if self.calls_today(session) >= self.s.daily_call_cap:
                    close("daily cap reached")
                    self.alert(session, "warn", f"Daily call cap of {self.s.daily_call_cap} reached.")
                    return started
                if self._in_flight(session) >= self.s.max_parallel_calls:
                    return started
                if leads is None:
                    try:
                        leads = self.load_leads()
                    except Exception as exc:
                        self.alert(session, "error", f"Could not read the Leads sheet: {exc}")
                        return started
                busy_rows, busy_phones = self._busy(session)
                lead = pick_next(leads, self.now_local(), self.s.max_attempts,
                                 timedelta(minutes=self.s.retry_gap_minutes),
                                 exclude_rows=busy_rows, exclude_phones=busy_phones,
                                 min_row=batch.min_row, max_row=batch.max_row)
                if lead is None:
                    if self._in_flight(session) == 0:
                        close("no more leads to call")
                    return started
                if self._dial(session, batch, lead):
                    failures_in_a_row = 0
                else:
                    failures_in_a_row += 1
                    if failures_in_a_row >= 3:
                        close("3 calls in a row failed to start")
                        self.alert(session, "error", f"Batch {batch.id} stopped: 3 calls in a row failed to start. Check Sarvam.")
                        return started
                # keep the local copy in step so the same lead is not picked twice
                lead.status, lead.attempts = "Calling", lead.attempts + 1
                started += 1

    def _in_flight(self, session) -> int:
        return session.scalar(select(func.count(CallAttempt.id)).where(CallAttempt.state == "calling")) or 0

    def _busy(self, session):
        rows = session.execute(select(CallAttempt.sheet_row, CallAttempt.phone)
                               .where(CallAttempt.state == "calling")).all()
        return {r for r, _ in rows}, {p for _, p in rows}

    def _dial(self, session, batch: Batch, lead: Lead) -> bool:
        phone = to_e164(lead.phone)
        stamp = self.now_local().strftime("%Y-%m-%d %H:%M")
        call = CallAttempt(sheet_row=lead.row, phone=phone, name=lead.name, batch_id=batch.id,
                           dry_run=self.s.dry_run)
        session.add(call)
        batch.dialled += 1
        session.commit()
        try:
            self.sheet.update_row(lead.row, {"status": "Calling", "called_at": stamp,
                                             "attempts": lead.attempts + 1})
        except Exception as exc:
            call.state, call.error, call.finished_at = "start_failed", f"sheet: {exc}", utcnow()
            session.commit()
            self.alert(session, "error", f"Row {lead.row}: could not mark Calling in the sheet, call not placed. {exc}")
            return False
        variables = {
            "lead_name": lead.name,
            "course_interest": lead.course or "digital marketing course",
            "lead_source": lead.source or "our website",
            "lead_city": lead.city,
            "lead_note": lead.note,
        }
        metadata = {"src": "didm-app", "row": str(lead.row), "call_id": str(call.id)}
        if self.s.dry_run:
            result = {"ok": True, "status_code": 200, "attempt_id": f"dry-{uuid.uuid4()}", "error": None}
        else:
            result = self.sarvam.start_call(phone, variables, metadata)
        call.attempt_id = result["attempt_id"]
        if not result["ok"]:
            call.state, call.error, call.finished_at = "start_failed", result["error"], utcnow()
        session.commit()
        self._safe_sheet(session, lead.row, {
            "status": f"HTTP {result['status_code']}" if result["status_code"] else "HTTP error",
            "attempt_id": result["attempt_id"] or "",
            **({"summary": result["error"] or ""} if not result["ok"] else {}),
        })
        if not result["ok"]:
            self.alert(session, "error", f"Row {lead.row} ({lead.name}): Sarvam did not start the call. {result['error']}")
        return result["ok"]

    def _safe_sheet(self, session, row: int, updates: dict) -> bool:
        try:
            self.sheet.update_row(row, updates)
            return True
        except Exception as exc:
            self.alert(session, "error", f"Row {row}: sheet update failed ({', '.join(updates)}): {exc}")
            return False

    # ---------- call results from Sarvam ----------
    def handle_result(self, payload: dict) -> dict:
        """Saves one call result. Safe to run twice for the same result, and safe to run in parallel.

        Only the database claim of the call row runs under the dialler lock. The sheet write and the
        WhatsApp message happen outside it, so one slow request no longer holds up every other result.
        """
        meta = ((payload.get("webhook_config") or {}).get("metadata") or {})
        attempt_id = payload.get("attempt_id")
        try:
            row = int(meta.get("row"))
        except (TypeError, ValueError):
            row = None
        fav = payload.get("final_agent_variables") or {}
        status = payload.get("status") or "unknown"
        outcome = fav.get("disposition") or ("hung_up_early" if status == "connected" else status)
        summary = fav.get("call_summary") or payload.get("failure_reason") or ""
        duration = round(payload.get("duration") or 0)
        with SessionLocal() as session:
            call = None
            if attempt_id:
                call = session.scalars(select(CallAttempt).where(CallAttempt.attempt_id == attempt_id)).first()
            if call is None and meta.get("call_id"):
                call = session.get(CallAttempt, int(meta["call_id"]))
            if call and call.state == "done":
                return {"ok": True, "duplicate": True}
            if row is None:
                row = call.sheet_row if call else None
            if row is None:
                self.alert(session, "warn", f"Call result without a sheet row ignored (attempt {attempt_id}).")
                return {"ok": False, "reason": "no row"}
            if call is None:
                call = CallAttempt(attempt_id=attempt_id, sheet_row=row, phone="", name="", state="calling")
                session.add(call)
                try:
                    session.commit()
                except IntegrityError:  # another worker saved the same attempt a moment ago
                    session.rollback()
                    return {"ok": True, "duplicate": True}
            # The conditional update is the duplicate guard: only one delivery can move the call to done.
            claimed = session.execute(
                update(CallAttempt).where(CallAttempt.id == call.id, CallAttempt.state != "done").values(
                    state="done", status=status, outcome=outcome, duration=duration, summary=summary,
                    finished_at=utcnow(), raw_result=payload)).rowcount
            session.commit()
            if not claimed:
                return {"ok": True, "duplicate": True}
            name = call.name
            updates = {
                "status": f"Done: {status}", "attempt_id": attempt_id or "", "outcome": outcome,
                "program": fav.get("interested_program", ""), "mode": fav.get("preferred_mode", ""),
                "centre": fav.get("preferred_centre", ""), "goal": fav.get("user_goal", ""),
                "callback": fav.get("callback_details", ""), "summary": summary, "duration": duration,
            }
            sheet_ok = self._safe_sheet(session, row, updates)
            if outcome == "callback_requested":
                self.alert(session, "info", f"Callback requested: row {row} {name} {fav.get('callback_details', '')}")
            wa = self._whatsapp_followup(session, row, outcome)
        self.fill_slots()
        return {"ok": True, "sheet_updated": sheet_ok, "whatsapp": wa}

    # ---------- WhatsApp send claims ----------
    def _claim_whatsapp(self, session, phone: str, kind: str) -> bool:
        """Reserves the right to send one message kind to one number. Returns False if someone else has it.

        A failed send can be claimed again. A send stuck in "sending" for 10 minutes (the worker died)
        can be claimed again too, which in that rare case may repeat one message.
        """
        try:
            session.add(WhatsAppClaim(phone=phone, kind=kind, state="sending", updated_at=utcnow()))
            session.commit()
            return True
        except IntegrityError:
            session.rollback()
        stale = utcnow() - timedelta(minutes=10)
        n = session.execute(update(WhatsAppClaim).where(
            WhatsAppClaim.phone == phone, WhatsAppClaim.kind == kind,
            (WhatsAppClaim.state == "failed") | ((WhatsAppClaim.state == "sending") & (WhatsAppClaim.updated_at < stale))
        ).values(state="sending", updated_at=utcnow())).rowcount
        session.commit()
        return n == 1

    def _finish_claim(self, session, phone: str, kind: str, ok: bool):
        session.execute(update(WhatsAppClaim).where(WhatsAppClaim.phone == phone, WhatsAppClaim.kind == kind)
                        .values(state="sent" if ok else "failed", updated_at=utcnow()))
        session.commit()

    def _whatsapp_followup(self, session, row: int, outcome: str) -> str:
        if not self.s.whatsapp_enabled:
            return "disabled"
        if outcome.lower().startswith(BLOCK_OUTCOMES):
            return "skipped: do-not-call or wrong number"
        try:
            lead = next((l for l in self.load_leads() if l.row == row), None)
        except Exception as exc:
            self.alert(session, "error", f"Row {row}: could not read the sheet before WhatsApp: {exc}")
            return "error"
        if lead is None:
            return "skipped: row not found"
        if lead.followup:
            return "skipped: already sent"
        e164 = to_e164(lead.phone)
        if not e164:
            return "skipped: bad phone"
        already = session.scalar(select(func.count(WhatsAppMessage.id)).where(
            WhatsAppMessage.phone == e164, WhatsAppMessage.http_status == 200)) or 0
        if already or not self._claim_whatsapp(session, e164, "followup"):
            return "skipped: already sent to this number"
        if self.s.dry_run:
            res = {"ok": True, "status_code": 200, "error": None}
        else:
            try:
                res = self.veblika.send_template(digits_only(e164))
            except Exception:
                self._finish_claim(session, e164, "followup", False)
                raise
        session.add(WhatsAppMessage(sheet_row=row, phone=e164, template=self.s.veblika_template,
                                    http_status=res["status_code"], error=res["error"], dry_run=self.s.dry_run))
        session.commit()
        self._finish_claim(session, e164, "followup", res["ok"])
        stamp = self.now_local().strftime("%Y-%m-%d %H:%M")
        note = f"WA {self.s.veblika_template} {stamp} HTTP {res['status_code']}" + ("" if res["ok"] else f" {res['error']}")
        self._safe_sheet(session, row, {"followup": note})
        if not res["ok"]:
            self.alert(session, "error", f"Row {row}: WhatsApp follow-up failed. {res['error']}")
            return "error"
        return "sent"

    # ---------- event invites (Sarvam campaign webhook) ----------
    def handle_event_call(self, payload: dict) -> dict:
        """After each finished campaign call, send the event's WhatsApp template once per number.

        Safe to run in parallel: the unique (phone, template) claim lets only one worker send.
        """
        s = self.s
        if payload.get("next_action_status"):
            return {"ok": True, "whatsapp": "skipped: call will be retried"}
        e164 = to_e164(payload.get("user_phone_number") or "")
        if not e164:
            return {"ok": False, "whatsapp": "skipped: bad phone"}
        if not s.event_template:
            return {"ok": False, "whatsapp": "skipped: EVENT_TEMPLATE not set"}
        with SessionLocal() as session:
            already = session.scalar(select(func.count(WhatsAppMessage.id)).where(
                WhatsAppMessage.phone == e164, WhatsAppMessage.template == s.event_template,
                WhatsAppMessage.http_status == 200, WhatsAppMessage.dry_run.is_(False))) or 0
            if already:
                return {"ok": True, "whatsapp": "skipped: already sent to this number"}
            live = s.event_whatsapp_live
            if not live:
                session.add(WhatsAppMessage(sheet_row=None, phone=e164, template=s.event_template,
                                            http_status=200, error=None, dry_run=True))
                session.commit()
                return {"ok": True, "whatsapp": "test mode"}
            if not self._claim_whatsapp(session, e164, s.event_template):
                return {"ok": True, "whatsapp": "skipped: already sent to this number"}
            extra = None
            if s.event_name_param:
                agent_vars = payload.get("final_agent_variables") or {}
                name = str(agent_vars.get("lead_name") or "").strip() or "Trainee"
                extra = {s.event_name_param: name}
            try:
                res = self.veblika.send_template(digits_only(e164), template=s.event_template,
                                                 language=s.event_language,
                                                 header_image_url=s.event_header_image_url,
                                                 extra_params=extra)
            except Exception:
                self._finish_claim(session, e164, s.event_template, False)
                raise
            session.add(WhatsAppMessage(sheet_row=None, phone=e164, template=s.event_template,
                                        http_status=res["status_code"], error=res["error"], dry_run=False))
            session.commit()
            self._finish_claim(session, e164, s.event_template, res["ok"])
            if not res["ok"]:
                self.alert(session, "error", f"Event WhatsApp to {e164} failed. {res['error']}")
                return {"ok": False, "whatsapp": "error", "retryable": True}
        return {"ok": True, "whatsapp": "sent"}

    # ---------- watchdog ----------
    def check_stuck_calls(self) -> int:
        """Calls with no result after STUCK_CALL_MINUTES are closed so the queue keeps moving."""
        cutoff = utcnow() - timedelta(minutes=self.s.stuck_call_minutes)
        n = 0
        with self._lock, SessionLocal() as session:
            for call in session.scalars(select(CallAttempt).where(
                    CallAttempt.state == "calling", CallAttempt.started_at < cutoff)):
                call.state, call.finished_at, call.error = "stuck", utcnow(), "no result from Sarvam"
                session.commit()
                self._safe_sheet(session, call.sheet_row, {"status": "Done: no_result"})
                self.alert(session, "warn", f"Row {call.sheet_row}: no call result after {self.s.stuck_call_minutes} minutes.")
                n += 1
        if n:
            self.fill_slots()
        return n

    # ---------- reports ----------
    def daily_summary(self) -> dict:
        start = self._today_start_utc()
        with SessionLocal() as session:
            calls = session.scalars(select(CallAttempt).where(CallAttempt.started_at >= start)).all()
            wa = session.scalars(select(WhatsAppMessage).where(WhatsAppMessage.sent_at >= start)).all()
            alerts = session.scalars(select(Alert).where(Alert.created_at >= start, Alert.level == "error")).all()
            stopped = self.is_stopped(session)
        done = [c for c in calls if c.state == "done"]
        return {
            "date": self.now_local().strftime("%Y-%m-%d"),
            "calls_started": len(calls),
            "connected": sum(1 for c in done if c.status == "connected"),
            "by_status": dict(Counter(c.status for c in done)),
            "by_outcome": dict(Counter(c.outcome for c in done)),
            "talk_minutes": round(sum(c.duration or 0 for c in done) / 60, 1),
            "start_failures": sum(1 for c in calls if c.state == "start_failed"),
            "no_result": sum(1 for c in calls if c.state == "stuck"),
            "whatsapp_sent": sum(1 for w in wa if w.http_status == 200),
            "whatsapp_failed": sum(1 for w in wa if w.http_status != 200),
            "errors": [a.message for a in alerts][:20],
            "stopped": stopped,
            "dry_run": self.s.dry_run,
            "auto_dial_minutes": self.s.auto_dial_minutes,
        }

    def send_daily_report(self) -> bool:
        r = self.daily_summary()
        lines = [
            f"DIDM calling report for {r['date']}" + (" (TEST MODE)" if r["dry_run"] else ""),
            "",
            f"Calls started: {r['calls_started']}",
            f"Connected: {r['connected']}",
            f"Talk time: {r['talk_minutes']} minutes",
            f"Outcomes: " + (", ".join(f"{k} {v}" for k, v in r["by_outcome"].items()) or "none"),
            f"WhatsApp sent: {r['whatsapp_sent']} (failed {r['whatsapp_failed']})",
            f"Calls that failed to start: {r['start_failures']}",
            f"Calls with no result: {r['no_result']}",
        ]
        if r["errors"]:
            lines += ["", "Errors today:"] + [f"- {e}" for e in r["errors"]]
        return self.mailer.send(f"DIDM calling report {r['date']}", "\n".join(lines))

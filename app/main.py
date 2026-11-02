"""Web app: admin controls, Sarvam webhook, dashboard and scheduled jobs."""
import html
import hmac
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy import select

from .config import Settings, settings as default_settings
from .db import Alert, Batch, CallAttempt, SessionLocal, WebhookEvent, init_db
from .integrations import GoogleSheet, Mailer, Sarvam, Veblika
from .leads import digits_only, to_e164
from .security import RateLimiter, client_ip, install_log_redaction
from .service import Automation
from .webhooks import WebhookProcessor

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("didm")


class DryRunSheet:
    """In test mode the sheet is read but never written; intended writes are logged."""

    def __init__(self, real):
        self.real = real
        self.writes: list[tuple[int, dict]] = []

    def read_rows(self):
        return self.real.read_rows() if self.real else []

    def update_row(self, row, updates):
        self.writes.append((row, updates))
        log.info("TEST MODE sheet write skipped: row %s %s", row, updates)


def build_automation(s: Settings, sheet=None, sarvam=None, veblika=None, mailer=None, clock=None) -> Automation:
    if sheet is None:
        real = GoogleSheet(s) if s.spreadsheet_id and s.google_service_account_json else None
        sheet = DryRunSheet(real) if s.dry_run else real
    return Automation(s, sheet, sarvam or Sarvam(s), veblika or Veblika(s), mailer or Mailer(s), clock=clock)


def create_app(s: Settings | None = None, automation: Automation | None = None, start_scheduler: bool = True) -> FastAPI:
    s = s or default_settings
    install_log_redaction()
    init_db(s.database_url, migrate=s.migrate_on_start)
    auto = automation or build_automation(s)
    webhooks = WebhookProcessor(auto, max_attempts=s.webhook_max_attempts, workers=s.webhook_workers)
    limiter = RateLimiter()
    from .saas.training import TrainingEngine
    # NO-GO (Phase 6): current Sarvam browser SDK configuration remains client-controlled. Keep the
    # provider absent even if an environment variable is set accidentally; tests may inject a fake.
    training = TrainingEngine(s, sarvam=auto.sarvam, browser_provider=None)
    webhooks.handlers["training_result"] = lambda payload: training.handle_provider_result(payload)
    from .saas.intelligence import IntelligenceEngine
    from .saas.recordings import RecordingService
    from .saas import providers
    analytics = providers.SarvamAnalytics(s) if s.training_provider_lookups_enabled and s.sarvam_api_key else None
    evaluator = (providers.SarvamChatEvaluator(s.sarvam_chat_api_key, s.evaluator_model,
                                               timeout=s.evaluator_timeout_seconds,
                                               max_output_tokens=s.evaluator_max_output_tokens)
                 if s.evaluator_provider == "sarvam" and s.sarvam_chat_api_key else None)
    if s.evaluator_provider and evaluator is None:
        log.warning("EVALUATOR_PROVIDER=%s is not usable (unknown provider or no key); evaluation stays off",
                    s.evaluator_provider)
    from .saas.s3store import build_stores
    from .saas.readiness import config_problems
    stores, store_problems = build_stores(s)
    store = stores.get(s.recording_store)  # compatibility for readiness and historical callers
    store_problem = "; ".join(store_problems) or None
    if store_problems:
        log.error("Recording storage configuration: %s", store_problem)
    source = (providers.SarvamRecordingSource(s) if stores and s.recording_source_enabled and s.sarvam_api_key
              and s.sarvam_org_id and s.sarvam_workspace_id else None)
    recordings = RecordingService(s, store=store, stores=stores, source=source)
    for p in config_problems(s):
        log.warning("Configuration: %s", p["message"])
    intelligence = IntelligenceEngine(s, training=training, evaluator=evaluator, transcript_provider=analytics,
                                      recordings=recordings, attempts_provider=analytics)
    training.intelligence = intelligence
    scheduler = None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal scheduler
        if start_scheduler:
            from apscheduler.schedulers.background import BackgroundScheduler
            scheduler = BackgroundScheduler(timezone=s.timezone)
            scheduler.add_job(auto.check_stuck_calls, "interval", minutes=5, id="stuck")
            scheduler.add_job(auto.send_daily_report, "cron", hour=s.daily_report_hour,
                              minute=s.daily_report_minute, id="report")
            scheduler.add_job(training.sweep, "interval", minutes=1, id="training_sweep")
            scheduler.add_job(intelligence.run_due_jobs, "interval", minutes=1, id="training_jobs")
            # Retention for every category (retention.py): reports only, unless RETENTION_ENFORCEMENT_ENABLED
            scheduler.add_job(recordings.sweep_retention, "cron", hour=3, minute=30, id="retention")
            scheduler.add_job(recordings.verify_storage, "cron", hour=4, minute=15, id="recording_verify")
            if s.auto_dial_minutes > 0:
                scheduler.add_job(auto.auto_dial, "interval", minutes=s.auto_dial_minutes, id="auto_dial")
            scheduler.start()
            webhooks.start()  # retries failed events in both modes, and processes queued ones
        log.info("DIDM automation started. Test mode: %s. Auto calling every %s min (0 = off)",
                 s.dry_run, s.auto_dial_minutes)
        yield
        webhooks.stop()
        if scheduler:
            scheduler.shutdown(wait=False)

    app = FastAPI(title="DIDM Automation", lifespan=lifespan)
    app.state.automation = auto
    app.state.webhooks = webhooks
    app.state.settings = s
    app.state.limiter = limiter
    app.state.training = training
    app.state.intelligence = intelligence
    app.state.recordings = recordings

    def require_admin(request: Request, authorization: str = Header(default=""), token: str = Query(default="")):
        # Legacy shared admin token. The ?token= form stays for the existing dashboard links; the new
        # web app uses cookie logins instead. Log lines have the token removed (security.py).
        # A "+" in a token typed into the address bar arrives as a space
        given = authorization.removeprefix("Bearer ").strip() or token.replace(" ", "+")
        if not s.admin_token or not hmac.compare_digest(given, s.admin_token):
            # Only failures count, so normal dashboard use is never throttled
            limiter.check(f"admin-fail:{client_ip(request, s.trust_proxy_headers)}", 20, 900)
            raise HTTPException(status_code=401, detail="Admin token required")

    class DialRequest(BaseModel):
        count: int = 10
        min_row: int | None = None
        max_row: int | None = None

    class ResultSimulation(BaseModel):
        row: int
        status: str = "connected"
        disposition: str = "interested"
        summary: str = "Test call result"

    @app.get("/")
    def home():
        dist = Path(s.frontend_dist_dir)
        if not dist.is_absolute():
            dist = Path(__file__).resolve().parent.parent / dist
        if dist.is_dir():
            return RedirectResponse(url="/app/")
        return {"ok": True, "message": "DIDM automation is running. Open /app/ once built, or /dashboard?token=YOUR_ADMIN_TOKEN"}

    @app.get("/healthz")
    def healthz():
        """Liveness: the process answers. Render's health check uses this, so it never touches the database."""
        return {"ok": True, "dry_run": s.dry_run}

    def _readiness():
        from .saas.readiness import readiness
        return readiness(s, scheduler=scheduler, webhooks=webhooks, store=store, store_problem=store_problem)

    @app.get("/readyz")
    def readyz():
        """Readiness: database reachable and the schema at the code's migration head. Public, so it says
        nothing about configuration; /admin/readiness has the detail."""
        from fastapi.responses import JSONResponse
        body = _readiness()
        return JSONResponse({"ok": body["ok"], "database": body["database"],
                             "schema_up_to_date": bool(body.get("schema", {}).get("up_to_date"))},
                            status_code=200 if body["ok"] else 503)

    @app.post("/admin/dial", dependencies=[Depends(require_admin)])
    def dial(req: DialRequest):
        return auto.start_batch(req.count, req.min_row, req.max_row)

    @app.post("/admin/stop", dependencies=[Depends(require_admin)])
    def stop():
        return auto.stop()

    @app.post("/admin/resume", dependencies=[Depends(require_admin)])
    def resume():
        return auto.resume()

    @app.get("/admin/summary", dependencies=[Depends(require_admin)])
    def summary():
        return auto.daily_summary()

    @app.post("/admin/send-report", dependencies=[Depends(require_admin)])
    def send_report():
        return {"emailed": auto.send_daily_report()}

    @app.get("/admin/readiness", dependencies=[Depends(require_admin)])
    def admin_readiness():
        """Everything the deployment checklist needs: schema, queues, workers, features, configuration problems."""
        return _readiness()

    @app.get("/admin/check", dependencies=[Depends(require_admin)])
    def check():
        """Shows which settings are still missing before going live."""
        return {"dry_run": s.dry_run, "missing_for_live": s.missing_for_live(),
                "email_alerts": auto.mailer.enabled}

    @app.get("/admin/test-whatsapp", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def test_whatsapp_page(phone: str):
        """Opening the old link no longer sends anything: it shows a button that sends with POST."""
        e164 = to_e164(phone)
        if not e164:
            raise HTTPException(status_code=400, detail="Bad phone number")
        return _confirm_page(e164)

    @app.post("/admin/test-whatsapp", dependencies=[Depends(require_admin)])
    def test_whatsapp(phone: str):
        """Sends the event WhatsApp to one number and shows Veblika's answer, to check the key."""
        e164 = to_e164(phone)
        if not e164:
            raise HTTPException(status_code=400, detail="Bad phone number")
        res = auto.veblika.send_template(digits_only(e164), template=s.event_template or None,
                                         language=s.event_language, header_image_url=s.event_header_image_url)
        return {"phone": e164, "ok": res["ok"], "status_code": res["status_code"], "error": res["error"]}

    @app.post("/admin/simulate-result", dependencies=[Depends(require_admin)])
    def simulate(req: ResultSimulation):
        """Test mode only: pretend Sarvam finished a call, to test the whole flow."""
        if not s.dry_run:
            raise HTTPException(status_code=400, detail="Only available in test mode")
        with SessionLocal() as session:
            call = session.scalars(select(CallAttempt).where(CallAttempt.sheet_row == req.row,
                                                            CallAttempt.state == "calling")).first()
        payload = {"attempt_id": call.attempt_id if call else f"sim-{req.row}", "status": req.status,
                   "duration": 60, "final_agent_variables": {"disposition": req.disposition,
                                                             "call_summary": req.summary},
                   "webhook_config": {"metadata": {"row": str(req.row)}}}
        return auto.handle_result(payload)

    async def accept_webhook(source: str, request: Request) -> dict:
        try:
            payload = await request.json()
        except ValueError:
            raise HTTPException(status_code=400, detail="Body must be JSON")
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Body must be a JSON object")
        # Blocking work (database, sheet, WhatsApp) runs in worker threads, never on the event loop.
        # If storing fails this raises and the caller gets a 500, so the provider can deliver again.
        event_id = await run_in_threadpool(webhooks.record, source, payload)
        if s.webhook_processing == "queued":
            return {"ok": True, "accepted": True, "event_id": event_id}
        result = await run_in_threadpool(webhooks.process, event_id)
        if result is None:  # the background worker picked it up first
            return {"ok": True, "accepted": True, "event_id": event_id}
        return {**result, "event_id": event_id}

    @app.post("/webhooks/sarvam/{secret}")
    async def sarvam_webhook(secret: str, request: Request):
        if not s.webhook_secret or not hmac.compare_digest(secret, s.webhook_secret):
            raise HTTPException(status_code=404)
        return await accept_webhook("sarvam_result", request)

    @app.post("/webhooks/sarvam-training/{secret}")
    async def sarvam_training_webhook(secret: str, request: Request):
        """Training call results only. Its own secret, its own handler: nothing here reaches the lead
        dialler, the Google Sheet or campaign WhatsApp. Each result also carries a per-session HMAC."""
        if not s.training_webhook_secret or not hmac.compare_digest(secret, s.training_webhook_secret):
            raise HTTPException(status_code=404)
        return await accept_webhook("training_result", request)

    @app.post("/webhooks/event/{secret}")
    async def event_webhook(secret: str, request: Request):
        allowed = [k for k in (s.webhook_secret, s.event_webhook_token) if k]
        if not any(hmac.compare_digest(secret, k) for k in allowed):
            raise HTTPException(status_code=404)
        return await accept_webhook("event_call", request)

    @app.get("/admin/webhook-events", dependencies=[Depends(require_admin)])
    def webhook_events(status: str = "dead", limit: int = 50):
        """Lists stored webhook deliveries by status (pending, processing, done, failed, dead)."""
        with SessionLocal() as session:
            rows = session.scalars(select(WebhookEvent).where(WebhookEvent.status == status)
                                   .order_by(WebhookEvent.created_at.desc()).limit(min(max(limit, 1), 200))).all()
        return [{"id": r.id, "source": r.source, "attempt_id": r.attempt_id, "status": r.status,
                 "attempts": r.attempts, "last_error": r.last_error, "created_at": r.created_at.isoformat(),
                 "next_attempt_at": r.next_attempt_at.isoformat() if r.next_attempt_at else None} for r in rows]

    @app.post("/admin/webhook-events/{event_id}/retry", dependencies=[Depends(require_admin)])
    def retry_webhook_event(event_id: str):
        if not webhooks.retry(event_id):
            raise HTTPException(status_code=404, detail="No failed or dead event with that id")
        return {"ok": True, "queued": event_id}

    media_dir = Path(__file__).parent / "media"

    @app.get("/media/{name}")
    def media(name: str):
        """Public images used as WhatsApp template headers."""
        path = media_dir / name
        if path.parent != media_dir or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path)

    @app.get("/dashboard", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
    def dashboard():
        r = auto.daily_summary()
        with SessionLocal() as session:
            calls = session.scalars(select(CallAttempt).order_by(CallAttempt.id.desc()).limit(50)).all()
            alerts = session.scalars(select(Alert).order_by(Alert.id.desc()).limit(20)).all()
            batch = session.scalars(select(Batch).order_by(Batch.id.desc())).first()
        return _render_dashboard(r, calls, alerts, batch)

    from .saas.api import mount_saas
    mount_saas(app, s, auto.mailer, limiter)
    return app


def _confirm_page(e164: str) -> str:
    e = html.escape
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Send test WhatsApp</title><style>body{{font-family:system-ui,sans-serif;margin:16px}}button{{padding:8px 12px}}</style></head><body>
<h3>Send the event WhatsApp to {e(e164)}?</h3>
<button id="b">Send now</button> <pre id="out"></pre>
<script>
const q=new URLSearchParams(location.search);const tok=(q.get('token')||'').replace(/ /g,'+');
document.getElementById('b').onclick=async()=>{{
  const r=await fetch('/admin/test-whatsapp?phone='+encodeURIComponent(q.get('phone')||''),{{method:'POST',headers:{{'Authorization':'Bearer '+tok}}}});
  document.getElementById('out').textContent=JSON.stringify(await r.json());
}};
</script></body></html>"""


def _render_dashboard(r, calls, alerts, batch) -> str:
    e = html.escape
    tiles = [("Calls today", r["calls_started"]), ("Connected", r["connected"]),
             ("Talk minutes", r["talk_minutes"]), ("WhatsApp sent", r["whatsapp_sent"]),
             ("Failed to start", r["start_failures"]), ("No result", r["no_result"])]
    tile_html = "".join(f'<div class="tile"><div class="n">{v}</div><div class="l">{e(k)}</div></div>' for k, v in tiles)
    outcome_html = "".join(f"<li>{e(str(k))}: {v}</li>" for k, v in r["by_outcome"].items()) or "<li>None yet</li>"
    rows = "".join(
        f"<tr><td>{c.sheet_row}</td><td>{e(c.name or '')}</td><td>{e(c.state)}</td><td>{e(c.status or '')}</td>"
        f"<td>{e(c.outcome or '')}</td><td>{c.duration or ''}</td><td>{e((c.summary or c.error or '')[:140])}</td></tr>"
        for c in calls)
    alert_rows = "".join(f"<li class='{e(a.level)}'>{a.created_at:%d %b %H:%M} UTC: {e(a.message)}</li>" for a in alerts) or "<li>No alerts</li>"
    batch_line = (f"Batch {batch.id}: {batch.dialled} of {batch.requested} dialled, "
                  f"{'running' if batch.active else 'finished (' + e(batch.note or '') + ')'}") if batch else "No batch yet"
    mode = "TEST MODE: no real calls or messages" if r["dry_run"] else "LIVE"
    state = "STOPPED" if r["stopped"] else "Ready"
    auto_line = (f"Auto calling every {r['auto_dial_minutes']} min" if r.get("auto_dial_minutes")
                 else "Auto calling off")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DIDM Calling Dashboard</title><style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#f7f7f8;color:#1a1a1a}}
.tiles{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px}}
.tile{{background:#fff;border-radius:10px;padding:12px;box-shadow:0 1px 2px #0001}}
.n{{font-size:26px;font-weight:600}}.l{{color:#666;font-size:13px}}
.badge{{display:inline-block;padding:3px 8px;border-radius:6px;background:#eef;margin-right:6px}}
table{{width:100%;border-collapse:collapse;background:#fff;font-size:13px}}td,th{{border-bottom:1px solid #eee;padding:6px;text-align:left}}
.wrap{{overflow-x:auto}}.controls{{margin:12px 0;display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
button{{padding:8px 12px;border-radius:8px;border:1px solid #ccd;background:#fff;cursor:pointer}}input{{width:70px;padding:6px}}li.error{{color:#b00020}}li.warn{{color:#a05a00}}
</style></head><body>
<h2>DIDM calling dashboard, {e(r['date'])}</h2>
<p><span class="badge">{mode}</span><span class="badge">{state}</span><span class="badge">{e(auto_line)}</span>{batch_line}</p>
<div class="controls">
<label>Calls in batch <input id="cnt" type="number" min="1" value="10"></label>
<button onclick="act('dial',{{count:+document.getElementById('cnt').value}})">Start calling</button>
<button onclick="act('stop')">Stop all calling</button>
<button onclick="act('resume')">Allow calling again</button>
<button onclick="act('send-report')">Email today's report</button>
<span id="msg"></span></div>
<div class="tiles">{tile_html}</div>
<h3>Outcomes today</h3><ul>{outcome_html}</ul>
<h3>Latest calls</h3><div class="wrap"><table><tr><th>Row</th><th>Name</th><th>State</th><th>Status</th><th>Outcome</th><th>Secs</th><th>Summary</th></tr>{rows}</table></div>
<h3>Alerts</h3><ul>{alert_rows}</ul>
<script>
const tok=(new URLSearchParams(location.search).get('token')||'').replace(/ /g,'+');
const cnt=document.getElementById('cnt');try{{const v=localStorage.getItem('didm_cnt');if(v)cnt.value=v;}}catch(_){{}}
cnt.addEventListener('change',()=>{{try{{localStorage.setItem('didm_cnt',cnt.value);}}catch(_){{}}}});
async function act(path,body){{
  if(path==='dial'&&!confirm('Start a calling batch now?'))return;
  const r=await fetch('/admin/'+path,{{method:'POST',headers:{{'Content-Type':'application/json','Authorization':'Bearer '+tok}},body:JSON.stringify(body||{{}})}});
  const j=await r.json();document.getElementById('msg').textContent=j.reason||(j.ok===false?'Failed':'Done');
  setTimeout(()=>location.reload(),1500);
}}
</script></body></html>"""

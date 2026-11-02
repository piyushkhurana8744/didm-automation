"""Configuration checks and the readiness report behind /readyz and the deployment checklist.

Nothing here prints a secret: settings are reported as set or not set, never by value.
"""
import logging

from sqlalchemy import func, select, text

from ..db import SessionLocal, WebhookEvent
from .models import EvaluationJob

log = logging.getLogger("didm.readiness")


def config_problems(s) -> list[dict]:
    """Settings that contradict each other or switch a feature on without what it needs.
    level "error" means the feature stays off; "warn" is advice."""
    out = []

    def add(level, key, message):
        out.append({"level": level, "key": key, "message": message})
    if s.training_phone_enabled and not s.training_webhook_secret:
        add("error", "TRAINING_WEBHOOK_SECRET", "Phone training is on but TRAINING_WEBHOOK_SECRET is empty, so "
                                                "results can never arrive.")
    if s.training_phone_enabled and not (s.sarvam_api_key and s.sarvam_org_id and s.sarvam_workspace_id):
        add("error", "SARVAM_API_KEY", "Phone training is on but the Sarvam account settings are incomplete.")
    if s.training_phone_enabled and not s.public_base_url:
        add("error", "PUBLIC_BASE_URL", "Phone training is on but PUBLIC_BASE_URL is empty, so Sarvam has no "
                                        "address to send results to.")
    if s.training_provider_lookups_enabled and not (s.sarvam_api_key and s.sarvam_org_id and s.sarvam_workspace_id):
        add("error", "TRAINING_PROVIDER_LOOKUPS_ENABLED", "Provider lookups are on but the Sarvam account settings "
                                                          "are incomplete, so they stay off.")
    if s.phone_otp_provider:
        add("warn", "PHONE_OTP_PROVIDER", "No phone code sender is built in; numbers stay admin-confirmed.")
    if s.training_browser_enabled:
        add("error", "TRAINING_BROWSER_ENABLED", "Browser training is security-disabled in Phase 6 even when this "
                                                 "flag is set; see docs/PHASE6_PRODUCTION_AUDIT.md.")
    if s.evaluator_provider and s.evaluator_provider != "sarvam":
        add("error", "EVALUATOR_PROVIDER", f"EVALUATOR_PROVIDER={s.evaluator_provider} is not supported.")
    if s.evaluator_provider == "sarvam" and not s.sarvam_chat_api_key:
        add("error", "SARVAM_CHAT_API_KEY", "EVALUATOR_PROVIDER=sarvam but SARVAM_CHAT_API_KEY is empty.")
    if s.evaluation_max_calls_per_session < 1:
        add("error", "EVALUATION_MAX_CALLS_PER_SESSION", "Must be at least 1.")
    if s.recording_store and s.recording_store not in ("s3", "cloudinary"):
        add("error", "RECORDING_STORE", f"RECORDING_STORE={s.recording_store} is not supported.")
    if s.recording_store == "s3":
        missing = [k for k, v in {"S3_ENDPOINT": s.s3_endpoint, "S3_BUCKET": s.s3_bucket, "S3_REGION": s.s3_region,
                                  "S3_ACCESS_KEY_ID": s.s3_access_key_id,
                                  "S3_SECRET_ACCESS_KEY": s.s3_secret_access_key}.items() if not v]
        if missing:
            add("error", "S3_*", "Recording storage needs " + ", ".join(missing) + ".")
        if s.s3_endpoint and not s.s3_endpoint.startswith("https://"):
            add("error", "S3_ENDPOINT", "S3_ENDPOINT must start with https://.")
        if s.s3_sse == "none":
            add("warn", "S3_SSE", "Uploads do not ask for server-side encryption; use only with a store that "
                                  "encrypts every object at rest by default.")
    if s.recording_store == "cloudinary" or "cloudinary" in s.recording_allowed_providers.split(","):
        missing = [k for k, v in {"CLOUDINARY_CLOUD_NAME": s.cloudinary_cloud_name,
                                  "CLOUDINARY_API_KEY": s.cloudinary_api_key,
                                  "CLOUDINARY_API_SECRET": s.cloudinary_api_secret}.items() if not v]
        if missing:
            add("error", "CLOUDINARY_*", "Cloudinary recording storage needs " + ", ".join(missing) + ".")
    if s.recording_source_enabled and not s.recording_store:
        add("warn", "RECORDING_SOURCE_ENABLED", "Recording copies are on but no store is set, so recordings stay off.")
    if s.recording_source_enabled and not s.training_provider_lookups_enabled:
        add("warn", "TRAINING_PROVIDER_LOOKUPS_ENABLED", "Recordings come from Sarvam Analytics; lookups are off.")
    if s.migrate_on_start:
        add("warn", "MIGRATE_ON_START", "Migrations run when the app starts. Prefer the controlled step "
                                        "(python -m app.migrate) before deploying; see docs/phase5_deployment.md.")
    if not s.cookie_secure:
        add("warn", "COOKIE_SECURE", "Login cookies are sent over plain HTTP. Only for local development.")
    if s.database_url.startswith("sqlite") and not s.dry_run:
        add("warn", "DATABASE_URL", "SQLite in live mode loses data on every Render deploy; use PostgreSQL.")
    if s.webhook_processing not in ("inline", "queued"):
        add("error", "WEBHOOK_PROCESSING", "Must be inline or queued.")
    return out


def readiness(s, scheduler=None, webhooks=None, store=None, store_problem=None) -> dict:
    checks = {}
    ok = True
    try:
        from ..db import _engine
        from ..migrate import schema_status
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            checks["database"] = "ok"
            checks["queues"] = {
                "webhooks_pending": db.scalar(select(func.count(WebhookEvent.id)).where(
                    WebhookEvent.status.in_(("pending", "failed")))),
                "webhooks_dead": db.scalar(select(func.count(WebhookEvent.id)).where(WebhookEvent.status == "dead")),
                "jobs_queued": db.scalar(select(func.count(EvaluationJob.id)).where(EvaluationJob.status == "queued")),
                "jobs_dead": db.scalar(select(func.count(EvaluationJob.id)).where(EvaluationJob.status == "dead")),
            }
        schema = schema_status(_engine)
        checks["schema"] = schema
        ok = ok and schema["up_to_date"]
    except Exception as exc:
        log.warning("readiness: database check failed (%s)", type(exc).__name__)
        checks["database"] = "unreachable"
        ok = False
    checks["scheduler"] = "running" if scheduler is not None and getattr(scheduler, "running", False) else "stopped"
    thread = getattr(webhooks, "_thread", None)
    checks["webhook_worker"] = "running" if thread is not None and thread.is_alive() else "stopped"
    checks["features"] = {
        "dry_run": s.dry_run, "phone_training": s.training_phone_enabled, "browser_training": s.training_browser_enabled,
        "provider_lookups": s.training_provider_lookups_enabled, "evaluator": s.evaluator_provider or None,
        "recording_store": (store.name if store is not None else None), "recording_store_problem": store_problem,
        "retention_enforced": s.retention_enforcement_enabled,
    }
    problems = config_problems(s)
    checks["config"] = [{"level": p["level"], "key": p["key"], "message": p["message"]} for p in problems]
    return {"ok": ok, **checks}

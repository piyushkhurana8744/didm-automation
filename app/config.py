"""All settings come from environment variables, so no key is ever stored in code."""
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
LOCAL_ENV_FILE = REPOSITORY_ROOT / ".env"


def load_repository_env(path: Path = LOCAL_ENV_FILE) -> bool:
    """Load the repository's local .env before Settings is constructed.

    Real process variables always win. Deployments can set DIDM_LOAD_DOTENV=false; production images
    do not contain .env, but the explicit opt-out makes that boundary enforceable. Demo/template files
    are deliberately never considered.
    """
    enabled = os.getenv("DIDM_LOAD_DOTENV", "true").strip().lower() in ("1", "true", "yes", "on")
    return bool(enabled and path.is_file() and load_dotenv(dotenv_path=path, override=False))


load_repository_env()


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    v = os.getenv(name)
    return int(v) if v not in (None, "") else default


def _clean_secret(name: str, default: str = "") -> str:
    """Normalize secrets from env: strip whitespace, newlines, surrounding quotes, and Bearer prefix."""
    v = os.getenv(name, default)
    if not v:
        return ""
    v = v.strip()
    if len(v) >= 2 and ((v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'"))):
        v = v[1:-1].strip()
    if v.lower().startswith("bearer "):
        v = v[7:].strip()
    return v


@dataclass
class Settings:
    # Safety switches
    dry_run: bool = field(default_factory=lambda: _bool("DRY_RUN", True))
    calling_start_hour: int = field(default_factory=lambda: _int("CALLING_START_HOUR", 9))
    calling_end_hour: int = field(default_factory=lambda: _int("CALLING_END_HOUR", 21))
    daily_call_cap: int = field(default_factory=lambda: _int("DAILY_CALL_CAP", 100))
    max_parallel_calls: int = field(default_factory=lambda: _int("MAX_PARALLEL_CALLS", 1))
    max_attempts: int = field(default_factory=lambda: _int("MAX_ATTEMPTS", 3))
    retry_gap_minutes: int = field(default_factory=lambda: _int("RETRY_GAP_MINUTES", 120))
    auto_dial_minutes: int = field(default_factory=lambda: _int("AUTO_DIAL_MINUTES", 0))  # 0 = off
    auto_dial_batch: int = field(default_factory=lambda: _int("AUTO_DIAL_BATCH", 20))
    stuck_call_minutes: int = field(default_factory=lambda: _int("STUCK_CALL_MINUTES", 30))
    timezone: str = field(default_factory=lambda: os.getenv("TIMEZONE", "Asia/Kolkata"))

    # App access
    admin_token: str = field(default_factory=lambda: _clean_secret("ADMIN_TOKEN", ""))
    webhook_secret: str = field(default_factory=lambda: _clean_secret("WEBHOOK_SECRET", ""))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./didm.db").strip())

    # Google Sheet
    spreadsheet_id: str = field(default_factory=lambda: os.getenv("SPREADSHEET_ID", "").strip())
    leads_sheet: str = field(default_factory=lambda: os.getenv("LEADS_SHEET", "Leads").strip())
    google_service_account_json: str = field(default_factory=lambda: os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip())

    # Sarvam
    sarvam_api_key: str = field(default_factory=lambda: _clean_secret("SARVAM_API_KEY", ""))
    sarvam_org_id: str = field(default_factory=lambda: _clean_secret("SARVAM_ORG_ID", ""))
    sarvam_workspace_id: str = field(default_factory=lambda: _clean_secret("SARVAM_WORKSPACE_ID", ""))
    sarvam_app_id: str = field(default_factory=lambda: _clean_secret("SARVAM_APP_ID", ""))
    sarvam_app_version: int = field(default_factory=lambda: _int("SARVAM_APP_VERSION", 0))
    sarvam_connection_id: str = field(default_factory=lambda: _clean_secret("SARVAM_CONNECTION_ID", ""))
    sarvam_agent_phone: str = field(default_factory=lambda: _clean_secret("SARVAM_AGENT_PHONE", ""))
    sarvam_base_url: str = field(default_factory=lambda: os.getenv("SARVAM_BASE_URL", "https://apps.sarvam.ai/api/outbounds").strip().rstrip("/"))
    # Encrypts the organization-scoped, short-lived Sarvam MCP OAuth token. Use a random value of at
    # least 32 characters. It is deliberately separate from webhook/API credentials.
    # WEBHOOK_SECRET is already a deployment-generated secret, so it is a safe compatibility fallback
    # for existing services whose blueprint has not yet synced the dedicated key. Rotating either key
    # only invalidates the short-lived OAuth connection; the user can reconnect Sarvam.
    sarvam_mcp_encryption_key: str = field(default_factory=lambda: (
        _clean_secret("SARVAM_MCP_ENCRYPTION_KEY", "") or _clean_secret("WEBHOOK_SECRET", "")))
    sarvam_mcp_url: str = field(default_factory=lambda: os.getenv(
        "SARVAM_MCP_URL", "https://mcp.sarvam.ai/voice-agents").strip().rstrip("/"))
    # Knowledge authoring is a separate trust boundary from existing training. It is permanently
    # zero-touch unless an operator explicitly enables a future, separately reviewed adapter.
    knowledge_sarvam_sync_enabled: bool = field(default_factory=lambda: _bool("KNOWLEDGE_SARVAM_SYNC_ENABLED", False))

    # Veblika WhatsApp
    whatsapp_enabled: bool = field(default_factory=lambda: _bool("WHATSAPP_ENABLED", True))
    veblika_api_key: str = field(default_factory=lambda: _clean_secret("VEBLIKA_API_KEY", ""))
    veblika_auth_name: str = field(default_factory=lambda: (os.getenv("VEBLIKA_AUTH_NAME", "").strip() or "x-api-key"))
    veblika_auth_in: str = field(default_factory=lambda: (os.getenv("VEBLIKA_AUTH_IN", "").strip().lower() or "header"))  # header | query
    # Optional: send through a Make webhook that holds the Veblika key instead of calling Veblika directly
    veblika_make_hook_url: str = field(default_factory=lambda: os.getenv("VEBLIKA_MAKE_HOOK_URL", "").strip())
    veblika_url: str = field(default_factory=lambda: os.getenv("VEBLIKA_URL", "https://automate.veblika.com/api/v2/whatsapp-business/messages"))
    veblika_phone_no_id: str = field(default_factory=lambda: os.getenv("VEBLIKA_PHONE_NO_ID", ""))
    veblika_template: str = field(default_factory=lambda: os.getenv("VEBLIKA_TEMPLATE", ""))
    veblika_language: str = field(default_factory=lambda: os.getenv("VEBLIKA_LANGUAGE", "en_US"))
    veblika_header_image_url: str = field(default_factory=lambda: os.getenv("VEBLIKA_HEADER_IMAGE_URL", ""))

    # Event invites (e.g. convocation): a Sarvam campaign posts each finished call to
    # /webhooks/event/{WEBHOOK_SECRET or EVENT_WEBHOOK_TOKEN}, and the app sends this WhatsApp template to that number.
    # EVENT_WHATSAPP_LIVE is separate from DRY_RUN so lead calling can stay in test mode.
    event_webhook_token: str = field(default_factory=lambda: os.getenv("EVENT_WEBHOOK_TOKEN", ""))
    event_whatsapp_live: bool = field(default_factory=lambda: _bool("EVENT_WHATSAPP_LIVE", False))
    event_template: str = field(default_factory=lambda: os.getenv("EVENT_TEMPLATE", ""))
    event_language: str = field(default_factory=lambda: os.getenv("EVENT_LANGUAGE", "en"))
    event_header_image_url: str = field(default_factory=lambda: os.getenv("EVENT_HEADER_IMAGE_URL", ""))
    # Veblika query key that fills the template's {{1}} with the trainee's name, e.g. bodyValues
    event_name_param: str = field(default_factory=lambda: os.getenv("EVENT_NAME_PARAM", ""))

    # Webhook intake: every delivery is stored first. "inline" processes it during the request (the old
    # behaviour, the reply carries the result); "queued" replies at once and a background worker processes it.
    webhook_processing: str = field(default_factory=lambda: (os.getenv("WEBHOOK_PROCESSING", "").strip().lower() or "inline"))
    webhook_workers: int = field(default_factory=lambda: _int("WEBHOOK_WORKERS", 4))
    webhook_max_attempts: int = field(default_factory=lambda: _int("WEBHOOK_MAX_ATTEMPTS", 5))
    # Run Alembic migrations when the app starts (one worker, so no two processes migrate at once)
    migrate_on_start: bool = field(default_factory=lambda: _bool("MIGRATE_ON_START", True))
    # Behind Render's proxy the client address is the last X-Forwarded-For entry. Leave off when not behind a proxy.
    trust_proxy_headers: bool = field(default_factory=lambda: _bool("TRUST_PROXY_HEADERS", False))

    # Training SaaS: browser logins and links in emails
    public_app_url: str = field(default_factory=lambda: os.getenv("PUBLIC_APP_URL", "").rstrip("/"))
    session_ttl_hours: int = field(default_factory=lambda: _int("SESSION_TTL_HOURS", 72))
    session_idle_hours: int = field(default_factory=lambda: _int("SESSION_IDLE_HOURS", 24))
    cookie_secure: bool = field(default_factory=lambda: _bool("COOKIE_SECURE", True))
    invitation_ttl_hours: int = field(default_factory=lambda: _int("INVITATION_TTL_HOURS", 168))
    password_reset_ttl_minutes: int = field(default_factory=lambda: _int("PASSWORD_RESET_TTL_MINUTES", 60))
    frontend_dist_dir: str = field(default_factory=lambda: os.getenv("FRONTEND_DIST_DIR", "frontend/out"))

    # Training sessions (phase 3). Both channels are off until a platform admin switches them on, because
    # every session is a paid Sarvam call. Organizations also need training enabled in their limits.
    training_phone_enabled: bool = field(default_factory=lambda: _bool("TRAINING_PHONE_ENABLED", False))
    # Browser voice stays off until the Sarvam Web SDK contract is verified with real credentials
    training_browser_enabled: bool = field(default_factory=lambda: _bool("TRAINING_BROWSER_ENABLED", False))
    # Secret in the training webhook path. Separate from WEBHOOK_SECRET so training results can never
    # reach the lead dialler (Google Sheet, campaign WhatsApp)
    training_webhook_secret: str = field(default_factory=lambda: os.getenv("TRAINING_WEBHOOK_SECRET", ""))
    # Platform-wide cap on open training sessions: keep it within the Sarvam plan's concurrency, minus
    # what the lead dialler uses (MAX_PARALLEL_CALLS)
    training_max_concurrent_total: int = field(default_factory=lambda: _int("TRAINING_MAX_CONCURRENT_TOTAL", 2))
    # Defaults for organizations whose limits leave a field empty
    training_default_org_concurrency: int = field(default_factory=lambda: _int("TRAINING_DEFAULT_ORG_CONCURRENCY", 1))
    training_default_user_concurrency: int = field(default_factory=lambda: _int("TRAINING_DEFAULT_USER_CONCURRENCY", 1))
    training_default_sessions_per_day: int = field(default_factory=lambda: _int("TRAINING_DEFAULT_SESSIONS_PER_DAY", 3))
    training_default_session_minutes: int = field(default_factory=lambda: _int("TRAINING_DEFAULT_SESSION_MINUTES", 10))
    training_default_monthly_minutes: int = field(default_factory=lambda: _int("TRAINING_DEFAULT_MONTHLY_MINUTES", 120))
    # A session that has not reached the provider within this many seconds is failed and its capacity freed
    training_start_timeout_seconds: int = field(default_factory=lambda: _int("TRAINING_START_TIMEOUT_SECONDS", 120))
    # Extra wait for the provider's final result after the longest allowed session, before timing it out
    training_end_grace_minutes: int = field(default_factory=lambda: _int("TRAINING_END_GRACE_MINUTES", 15))

    # Training intelligence (phase 4). Everything here is off until set.
    # Read-only Sarvam Analytics lookups: missing transcripts and calls whose outcome we never got
    training_provider_lookups_enabled: bool = field(default_factory=lambda: _bool("TRAINING_PROVIDER_LOOKUPS_ENABLED", False))
    # Scoring transcripts against rubrics. "sarvam" uses Sarvam chat completions, billed per token;
    # empty means no evaluator, so sessions show "not evaluated" and no score
    evaluator_provider: str = field(default_factory=lambda: os.getenv("EVALUATOR_PROVIDER", "").strip().lower())
    evaluator_model: str = field(default_factory=lambda: os.getenv("EVALUATOR_MODEL", "sarvam-105b"))
    sarvam_chat_api_key: str = field(default_factory=lambda: _clean_secret("SARVAM_CHAT_API_KEY", ""))
    # Evaluator cost controls (phase 5). Every provider call is metered in evaluation_usage. Organization
    # limits override the monthly defaults; the daily cap is platform-wide, across all organizations.
    evaluator_timeout_seconds: int = field(default_factory=lambda: _int("EVALUATOR_TIMEOUT_SECONDS", 60))
    evaluator_max_output_tokens: int = field(default_factory=lambda: _int("EVALUATOR_MAX_OUTPUT_TOKENS", 4096))
    evaluation_max_calls_per_session: int = field(default_factory=lambda: _int("EVALUATION_MAX_CALLS_PER_SESSION", 3))
    evaluation_default_monthly_calls: int = field(default_factory=lambda: _int("EVALUATION_DEFAULT_MONTHLY_CALLS", 200))
    evaluation_default_monthly_tokens: int = field(default_factory=lambda: _int("EVALUATION_DEFAULT_MONTHLY_TOKENS", 2_000_000))
    evaluation_platform_daily_calls: int = field(default_factory=lambda: _int("EVALUATION_PLATFORM_DAILY_CALLS", 300))

    # Private object storage for recordings. Empty means no store, so recordings stay off. "s3" is any
    # S3-compatible store (AWS S3, Cloudflare R2, MinIO); the bucket must be private.
    recording_store: str = field(default_factory=lambda: os.getenv("RECORDING_STORE", "").strip().lower())
    # Providers that organization admins may select. Credentials remain platform-owned environment
    # variables; tenants never submit provider secrets. If omitted, only RECORDING_STORE is allowed.
    recording_allowed_providers: str = field(default_factory=lambda: os.getenv("RECORDING_ALLOWED_PROVIDERS", "").strip().lower())
    s3_endpoint: str = field(default_factory=lambda: os.getenv("S3_ENDPOINT", "").strip().rstrip("/"))
    s3_bucket: str = field(default_factory=lambda: os.getenv("S3_BUCKET", "").strip())
    s3_region: str = field(default_factory=lambda: os.getenv("S3_REGION", "").strip())
    s3_access_key_id: str = field(default_factory=lambda: os.getenv("S3_ACCESS_KEY_ID", "").strip())
    s3_secret_access_key: str = field(default_factory=lambda: os.getenv("S3_SECRET_ACCESS_KEY", "").strip())
    s3_session_token: str = field(default_factory=lambda: os.getenv("S3_SESSION_TOKEN", "").strip())
    s3_sse: str = field(default_factory=lambda: os.getenv("S3_SSE", "").strip() or "AES256")  # AES256 | aws:kms | none
    s3_kms_key_id: str = field(default_factory=lambda: os.getenv("S3_KMS_KEY_ID", "").strip())
    s3_path_style: bool = field(default_factory=lambda: _bool("S3_PATH_STYLE", True))
    cloudinary_cloud_name: str = field(default_factory=lambda: os.getenv("CLOUDINARY_CLOUD_NAME", "").strip())
    cloudinary_api_key: str = field(default_factory=lambda: os.getenv("CLOUDINARY_API_KEY", "").strip())
    cloudinary_api_secret: str = field(default_factory=lambda: os.getenv("CLOUDINARY_API_SECRET", "").strip())
    cloudinary_folder: str = field(default_factory=lambda: os.getenv("CLOUDINARY_FOLDER", "didm-recordings").strip().strip("/"))
    # Copy recordings from Sarvam (needs the Sarvam analytics settings). Off unless a store is set too.
    recording_source_enabled: bool = field(default_factory=lambda: _bool("RECORDING_SOURCE_ENABLED", False))

    # Data retention (phase 5). The daily job always reports what it would remove; it only removes
    # anything when RETENTION_ENFORCEMENT_ENABLED is on. Recordings follow their own retention date.
    retention_enforcement_enabled: bool = field(default_factory=lambda: _bool("RETENTION_ENFORCEMENT_ENABLED", False))
    # Raw training webhook bodies hold the transcript and phone number; after this many days only a
    # redacted summary is kept. 0 keeps them.
    training_webhook_payload_days: int = field(default_factory=lambda: _int("TRAINING_WEBHOOK_PAYLOAD_DAYS", 30))
    browser_token_retention_days: int = field(default_factory=lambda: _int("BROWSER_TOKEN_RETENTION_DAYS", 30))
    phone_challenge_retention_days: int = field(default_factory=lambda: _int("PHONE_CHALLENGE_RETENTION_DAYS", 7))
    # Sends phone verification codes. No sender is built in yet, so numbers stay admin-confirmed
    phone_otp_provider: str = field(default_factory=lambda: os.getenv("PHONE_OTP_PROVIDER", "").strip().lower())

    # Alerts and reports by email
    smtp_host: str = field(default_factory=lambda: os.getenv("SMTP_HOST", ""))
    smtp_port: int = field(default_factory=lambda: _int("SMTP_PORT", 587))
    smtp_user: str = field(default_factory=lambda: os.getenv("SMTP_USER", ""))
    smtp_password: str = field(default_factory=lambda: os.getenv("SMTP_PASSWORD", ""))
    alert_email_to: str = field(default_factory=lambda: os.getenv("ALERT_EMAIL_TO", ""))
    daily_report_hour: int = field(default_factory=lambda: _int("DAILY_REPORT_HOUR", 21))
    daily_report_minute: int = field(default_factory=lambda: _int("DAILY_REPORT_MINUTE", 15))

    def app_url(self) -> str:
        """Base address of the web app, used in invitation and password-reset links."""
        return self.public_app_url or (self.public_base_url + "/app" if self.public_base_url else "")

    def google_credentials_info(self) -> dict:
        return json.loads(self.google_service_account_json) if self.google_service_account_json else {}

    def missing_for_live(self) -> list[str]:
        """Settings that must be filled before DRY_RUN can be switched off."""
        need = {
            "ADMIN_TOKEN": self.admin_token,
            "WEBHOOK_SECRET": self.webhook_secret,
            "PUBLIC_BASE_URL": self.public_base_url,
            "SPREADSHEET_ID": self.spreadsheet_id,
            "GOOGLE_SERVICE_ACCOUNT_JSON": self.google_service_account_json,
            "SARVAM_API_KEY": self.sarvam_api_key,
            "SARVAM_ORG_ID": self.sarvam_org_id,
            "SARVAM_WORKSPACE_ID": self.sarvam_workspace_id,
            "SARVAM_APP_ID": self.sarvam_app_id,
            "SARVAM_APP_VERSION": self.sarvam_app_version,
            "SARVAM_CONNECTION_ID": self.sarvam_connection_id,
            "SARVAM_AGENT_PHONE": self.sarvam_agent_phone,
        }
        if self.whatsapp_enabled:
            need.update({
                "VEBLIKA_API_KEY": self.veblika_api_key,
                "VEBLIKA_PHONE_NO_ID": self.veblika_phone_no_id,
                "VEBLIKA_TEMPLATE": self.veblika_template,
            })
        return [k for k, v in need.items() if not v]


settings = Settings()

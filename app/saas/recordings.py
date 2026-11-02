"""Call recordings: consent, private storage, short-lived playback links, retention and deletion.

Recordings stay off unless all of these hold: the platform allows recordings for the organization
(TrainingOrgLimits.recording_allowed), the organization's admins switched them on with a consent notice
(TrainingOrgSettings), the trainee accepted that exact notice when starting the session, a private object
store is configured, and a provider recording source is configured. Until then a session simply has no
recording, and the page says why.

Audio never goes into the database. A playback link is a presigned URL from the private store that
expires in minutes; the store's own URL or the provider's URL is never shown to anyone.
"""
import hashlib
import ipaddress
import logging
from datetime import timedelta
from urllib.parse import urlparse

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..db import SessionLocal, utcnow
from .intelligence import JobGiveUp, JobRetry
from .models import TrainingOrgLimits, TrainingOrgSettings, TrainingRecording, TrainingSession

log = logging.getLogger("didm.recordings")

ALLOWED_CONTENT_TYPES = ("audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/wave", "audio/ogg", "audio/webm",
                         "audio/mp4")
MAX_RECORDING_BYTES = 50 * 1024 * 1024
PLAYBACK_TTL_SECONDS = 300


def valid_audio_bytes(data: bytes, content_type: str) -> bool:
    """Cheap signature check before paid storage. The provider MIME header alone is not trusted."""
    if content_type in ("audio/wav", "audio/x-wav", "audio/wave"):
        return data.startswith((b"RIFF", b"RF64")) and data[8:12] == b"WAVE"
    if content_type in ("audio/mpeg", "audio/mp3"):
        return data.startswith(b"ID3") or (len(data) >= 2 and data[0] == 0xff and data[1] & 0xe0 == 0xe0)
    if content_type == "audio/ogg":
        return data.startswith(b"OggS")
    if content_type == "audio/webm":
        return data.startswith(b"\x1aE\xdf\xa3")
    if content_type == "audio/mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    return False


class RecordingStore:
    """Private object storage. A real store must keep objects private (no public ACL), encrypt them at
    rest, and serve them only through presigned URLs over HTTPS."""

    name = "none"

    def put(self, key: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def presign(self, key: str, ttl_seconds: int) -> str:
        raise NotImplementedError

    def delete(self, key: str) -> None:
        raise NotImplementedError

    # Provider-neutral API. Legacy S3 adapters only need put/presign/delete; these defaults preserve
    # that contract while richer providers can return their own immutable asset metadata.
    def upload_recording(self, asset_id: str, data: bytes, content_type: str) -> dict:
        self.put(asset_id, data, content_type)
        return {"asset_id": asset_id, "resource_type": "object", "delivery_type": "private",
                "version": None, "status": "stored"}

    def get_secure_playback(self, rec, ttl_seconds: int) -> str:
        return self.presign(rec.storage_asset_id or rec.storage_key, ttl_seconds)

    def delete_recording(self, rec) -> None:
        self.delete(rec.storage_asset_id or rec.storage_key)

    def check_health(self) -> dict:
        return {"ok": True, "provider": self.name}

    def get_metadata(self, rec) -> dict:
        size = self.head(rec.storage_asset_id or rec.storage_key) if hasattr(self, "head") else None
        return {"size_bytes": size}


class RecordingSource:
    """Where the provider's audio comes from. fetch_url returns an HTTPS URL for the session's recording,
    or None when the provider has none. Sarvam's is SarvamRecordingSource in providers.py; main.py only
    builds it when RECORDING_SOURCE_ENABLED is on and a store is configured."""

    allowed_hosts: tuple = ()

    def fetch_url(self, sess: TrainingSession, job_input: dict) -> str | None:
        raise NotImplementedError

    def download(self, url: str, max_bytes: int) -> tuple[bytes, str]:
        raise NotImplementedError


def safe_provider_url(url: str, allowed_hosts: tuple) -> bool:
    """Only HTTPS, only the provider's own hosts, never an IP address or a local name."""
    try:
        u = urlparse(url)
    except ValueError:
        return False
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host or u.username or u.password or u.port not in (None, 443):
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return any(host == h or host.endswith("." + h) for h in allowed_hosts)


class RecordingService:
    def __init__(self, settings, store: RecordingStore | None = None, source: RecordingSource | None = None,
                 stores: dict[str, RecordingStore] | None = None):
        self.s = settings
        self.store = store
        self.stores = dict(stores or ({store.name: store} if store else {}))
        self.source = source

    def allowed_providers(self) -> list[str]:
        raw = [x.strip() for x in (self.s.recording_allowed_providers or "").split(",") if x.strip()]
        wanted = raw or ([self.s.recording_store] if self.s.recording_store else [])
        available = set(self.stores)
        if self.store is not None:  # preserves test/custom adapters assigned after application startup
            available.add(self.store.name)
        if not wanted and self.store is not None:
            wanted = [self.store.name]
        return [x for x in wanted if x in available]

    def provider_for_org(self, db: Session, org_id: str) -> str | None:
        st = db.get(TrainingOrgSettings, org_id)
        selected = st.storage_provider if st and st.storage_provider else (self.s.recording_store or
                   (self.store.name if self.store is not None else None))
        return selected if selected in self.allowed_providers() else None

    def provider_for_recording(self, rec: TrainingRecording) -> RecordingStore | None:
        # Pre-Phase-6 rows have only storage_key and are historical S3 recordings.
        name = rec.storage_provider or ("s3" if rec.storage_key else None)
        if self.store is not None and self.store.name == name:
            return self.store
        return self.stores.get(name)

    # ---------- policy ----------
    def configured(self) -> bool:
        return bool(self.stores or self.store) and self.source is not None

    def org_policy(self, db: Session, org_id: str) -> dict:
        lim = db.get(TrainingOrgLimits, org_id)
        st = db.get(TrainingOrgSettings, org_id)
        allowed = bool(lim and lim.recording_allowed)
        provider = self.provider_for_org(db, org_id)
        enabled = bool(allowed and st and st.recording_enabled and st.consent_version and provider)
        reason = None
        if not self.configured():
            reason = "Recording storage or the provider's recording download is not set up."
        elif not allowed:
            reason = "Recordings are not allowed for this organization."
        elif not enabled:
            reason = "Recordings are switched off for this organization."
        return {"available": enabled and self.configured(), "allowed": allowed, "enabled": enabled,
                "provider": provider, "allowed_providers": self.allowed_providers(),
                "consent_version": st.consent_version if st else None, "consent_text": st.consent_text if st else "",
                "retention_days": st.recording_retention_days if st else 30, "reason": reason}

    def wanted(self, db: Session, sess: TrainingSession) -> bool:
        p = self.org_policy(db, sess.organization_id)
        return bool(p["available"] and sess.recording_consent_reference
                    and sess.recording_consent_reference == p["consent_version"])

    # ---------- copy ----------
    def copy_for_session(self, session_id: str, job_input: dict) -> tuple[str, str | None]:
        with SessionLocal() as db:
            sess = db.get(TrainingSession, session_id)
            if not self.wanted(db, sess):
                return "skipped", "not_allowed"
            p = self.org_policy(db, sess.organization_id)
            rec = db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sess.id)).first()
            if rec is None:
                rec = TrainingRecording(organization_id=sess.organization_id, session_id=sess.id, status="pending",
                                        consent_reference=sess.recording_consent_reference)
                db.add(rec)
                db.commit()
            if rec.status != "pending":
                return "skipped", "already_done"
            provider_name = self.provider_for_org(db, sess.organization_id)
            store = self.store if self.store is not None and self.store.name == provider_name else self.stores.get(provider_name or "")
            if store is None:
                raise JobRetry("store_not_configured", provider_name or "disabled")
            url = self.source.fetch_url(sess, job_input)  # may raise JobRetry
            if url is None:
                rec.status, rec.status_reason, rec.updated_at = "unavailable", "The provider has no recording.", utcnow()
                db.commit()
                return "succeeded", None
            if not safe_provider_url(url, self.source.allowed_hosts):
                rec.status, rec.status_reason, rec.updated_at = "failed", "The provider URL was not trusted.", utcnow()
                db.commit()
                raise JobGiveUp("untrusted_url")
            data, content_type = self.source.download(url, MAX_RECORDING_BYTES)
            if not data:
                rec.status, rec.status_reason, rec.updated_at = "unavailable", "The provider has no recording.", utcnow()
                db.commit()
                return "succeeded", None
            content_type = (content_type or "").split(";")[0].strip().lower()
            if content_type not in ALLOWED_CONTENT_TYPES:
                rec.status, rec.status_reason, rec.updated_at = "failed", "The provider file is not audio.", utcnow()
                db.commit()
                raise JobGiveUp("bad_content_type")
            if not valid_audio_bytes(data, content_type):
                rec.status, rec.status_reason, rec.updated_at = "failed", "The provider file is not valid audio.", utcnow()
                db.commit()
                raise JobGiveUp("bad_audio_signature")
            if len(data) > MAX_RECORDING_BYTES:
                rec.status, rec.status_reason, rec.updated_at = "failed", "The provider file has a bad size.", utcnow()
                db.commit()
                raise JobGiveUp("bad_size")
            key = f"training/{sess.organization_id}/{sess.id}/{hashlib.sha256(data).hexdigest()[:16]}"
            try:
                metadata = store.upload_recording(key, data, content_type)
            except Exception as exc:
                if getattr(exc, "retryable", True) is False:
                    raise JobGiveUp(getattr(exc, "code", "store_failed"), type(exc).__name__)
                raise JobRetry("store_failed", type(exc).__name__)
            now = utcnow()
            rec.storage_key, rec.content_type, rec.size_bytes = key, content_type, len(data)
            rec.storage_provider = provider_name
            rec.storage_asset_id = metadata.get("asset_id") or key
            rec.storage_resource_type = metadata.get("resource_type")
            rec.storage_delivery_type = metadata.get("delivery_type")
            rec.storage_version = str(metadata["version"]) if metadata.get("version") is not None else None
            rec.storage_status = metadata.get("status") or "stored"
            rec.uploaded_at = now
            rec.sha256, rec.status, rec.status_reason = hashlib.sha256(data).hexdigest(), "stored", None
            rec.duration_seconds = sess.provider_duration_seconds or sess.duration_seconds
            rec.provider_reference = (job_input.get("interaction_id") or sess.provider_session_id or None)
            rec.retention_until = now + timedelta(days=p["retention_days"])
            rec.updated_at = now
            db.commit()
        log.info("recording stored session=%s bytes=%s", session_id, len(data))
        return "succeeded", None

    # ---------- playback and deletion ----------
    def playback_url(self, rec: TrainingRecording) -> str:
        store = self.provider_for_recording(rec)
        if store is None:
            raise RuntimeError("store_not_configured")
        return store.get_secure_playback(rec, PLAYBACK_TTL_SECONDS)

    def delete(self, db: Session, rec: TrainingRecording, reason: str) -> bool:
        if rec.status != "stored":
            return False
        store = self.provider_for_recording(rec)
        if store is None:
            raise RuntimeError("store_not_configured")  # never mark a file deleted that we could not delete
        if rec.storage_asset_id or rec.storage_key:
            store.delete_recording(rec)
        rec.storage_status = "deleted"
        rec.status, rec.status_reason, rec.deleted_at, rec.updated_at = "deleted", reason[:300], utcnow(), utcnow()
        return True

    def sweep_retention(self, now=None) -> int:
        """Runs the daily retention job (retention.py) and returns how many recordings it deleted.
        Legal holds are respected, and a failed deletion is counted and retried on the next run."""
        from .retention import RetentionService

        now = now or utcnow()
        runs = RetentionService(self.s, self).run(now)
        with SessionLocal() as db:
            # Rows whose audio never arrived do not need to wait for retention
            db.execute(update(TrainingRecording).where(TrainingRecording.status == "pending",
                                                       TrainingRecording.created_at < now - timedelta(days=7))
                       .values(status="failed", status_reason="The recording never arrived.", updated_at=now))
            db.commit()
        return sum(r.get("counts", {}).get("recordings", {}).get("removed", 0) for r in runs)

    def verify_storage(self, now=None, limit: int = 100) -> dict:
        """Metadata reconciliation: checks that each stored row's object still exists with the same size.
        A missing object marks the row failed so nobody is offered a playback link that cannot work."""
        now = now or utcnow()
        out = {"checked": 0, "missing": 0, "errors": 0}
        if not self.stores and self.store is None:
            return out
        with SessionLocal() as db:
            rows = db.scalars(select(TrainingRecording).where(
                TrainingRecording.status == "stored",
                (TrainingRecording.verified_at.is_(None)) | (TrainingRecording.verified_at < now - timedelta(days=7)))
                .order_by(TrainingRecording.verified_at.is_(None).desc(), TrainingRecording.verified_at)
                .limit(limit)).all()
            for rec in rows:
                try:
                    store = self.provider_for_recording(rec)
                    if store is None:
                        raise RuntimeError("store_not_configured")
                    size = store.get_metadata(rec).get("size_bytes")
                except Exception:
                    out["errors"] += 1
                    continue
                out["checked"] += 1
                if size is None or (rec.size_bytes is not None and size != rec.size_bytes):
                    rec.status, rec.status_reason = "failed", "The stored file is missing or changed."
                    out["missing"] += 1
                    log.warning("recording object missing recording=%s", rec.id)
                rec.verified_at, rec.updated_at = now, now
            db.commit()
        return out

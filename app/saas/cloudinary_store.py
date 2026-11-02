"""Private Cloudinary recording storage.

Audio is uploaded as an authenticated `video` resource. Playback uses Cloudinary's
`private_download_url` with an explicit expiry; ordinary signed delivery URLs are deliberately not
used because their signature does not impose a lifetime. Credentials never leave this server.
"""
import io
import time

from .recordings import RecordingStore


class CloudinaryStoreError(Exception):
    def __init__(self, code: str, retryable: bool = True):
        super().__init__(code)
        self.code, self.retryable = code, retryable


class CloudinaryRecordingStore(RecordingStore):
    name = "cloudinary"

    def __init__(self, *, cloud_name: str, api_key: str, api_secret: str, folder: str = "didm-recordings",
                 sdk=None, clock=None):
        if not (cloud_name and api_key and api_secret):
            raise ValueError("CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET are required")
        if not folder or ".." in folder.split("/"):
            raise ValueError("CLOUDINARY_FOLDER is invalid")
        if sdk is None:
            import cloudinary
            import cloudinary.api
            import cloudinary.uploader
            import cloudinary.utils
            cloudinary.config(cloud_name=cloud_name, api_key=api_key, api_secret=api_secret, secure=True,
                              signature_algorithm="sha256")
            sdk = cloudinary
        self.sdk, self.folder = sdk, folder.strip("/")
        self.clock = clock or time.time

    def __repr__(self):
        return f"CloudinaryRecordingStore(folder={self.folder!r})"

    def _public_id(self, asset_id: str) -> str:
        if not asset_id or asset_id.startswith("/") or ".." in asset_id.split("/"):
            raise CloudinaryStoreError("bad_asset_id", retryable=False)
        return f"{self.folder}/{asset_id}"

    def upload_recording(self, asset_id: str, data: bytes, content_type: str) -> dict:
        public_id = self._public_id(asset_id)
        try:
            result = self.sdk.uploader.upload(io.BytesIO(data), public_id=public_id, resource_type="video",
                                              type="authenticated", overwrite=False, unique_filename=False)
        except Exception as exc:
            status = getattr(exc, "http_status", None)
            if status == 409:  # upload succeeded earlier but the worker restarted before committing metadata
                try:
                    result = self.sdk.api.resource(public_id, resource_type="video", type="authenticated")
                except Exception as lookup:
                    raise CloudinaryStoreError("duplicate_lookup_failed", retryable=True) from lookup
            else:
                raise CloudinaryStoreError("upload_auth" if status in (401, 403) else "upload_failed",
                                           retryable=status not in (400, 401, 403, 404)) from exc
        if result.get("resource_type") != "video" or result.get("type") != "authenticated":
            raise CloudinaryStoreError("privacy_validation_failed", retryable=False)
        return {"asset_id": result.get("public_id") or public_id, "resource_type": "video",
                "delivery_type": "authenticated", "version": result.get("version"), "status": "stored"}

    def get_secure_playback(self, rec, ttl_seconds: int) -> str:
        if not 1 <= ttl_seconds <= 900:
            raise CloudinaryStoreError("bad_ttl", retryable=False)
        fmt = (rec.content_type or "audio/mpeg").split("/")[-1].replace("mpeg", "mp3").replace("x-wav", "wav")
        return self.sdk.utils.private_download_url(
            rec.storage_asset_id, fmt, resource_type=rec.storage_resource_type or "video",
            type=rec.storage_delivery_type or "authenticated", expires_at=int(self.clock()) + ttl_seconds)

    def delete_recording(self, rec) -> None:
        try:
            result = self.sdk.uploader.destroy(rec.storage_asset_id, resource_type=rec.storage_resource_type or "video",
                                               type=rec.storage_delivery_type or "authenticated", invalidate=True)
        except Exception as exc:
            raise CloudinaryStoreError("delete_failed", retryable=True) from exc
        if result.get("result") not in ("ok", "not found"):
            raise CloudinaryStoreError("delete_failed", retryable=result.get("result") != "unauthorized")

    def get_metadata(self, rec) -> dict:
        try:
            result = self.sdk.api.resource(rec.storage_asset_id, resource_type=rec.storage_resource_type or "video",
                                           type=rec.storage_delivery_type or "authenticated")
            return {"size_bytes": result.get("bytes"), "version": result.get("version"),
                    "format": result.get("format")}
        except Exception as exc:
            # A missing asset is represented as missing metadata; transport/auth failures remain retryable.
            status = getattr(exc, "http_status", None)
            if status == 404:
                return {"size_bytes": None}
            raise CloudinaryStoreError("metadata_failed", retryable=status in (None, 408, 429) or status >= 500) from exc

    def check_health(self) -> dict:
        try:
            self.sdk.api.ping()
            return {"ok": True, "provider": self.name}
        except Exception:
            return {"ok": False, "provider": self.name}

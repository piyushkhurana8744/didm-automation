"""Cloudinary adapter tests use a fake SDK and never make paid or network calls."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from app.saas.cloudinary_store import CloudinaryRecordingStore, CloudinaryStoreError
from app.saas.recordings import RecordingService, RecordingStore


class FakeCloudinary:
    def __init__(self):
        self.assets, self.uploads, self.deletes = {}, [], []
        self.fail_upload = None
        self.uploader = SimpleNamespace(upload=self.upload, destroy=self.destroy)
        self.api = SimpleNamespace(resource=self.resource, ping=lambda: {"status": "ok"})
        self.utils = SimpleNamespace(private_download_url=self.private_download_url)

    def upload(self, stream, **options):
        if self.fail_upload:
            raise self.fail_upload
        data = stream.read()
        self.uploads.append((data, options))
        result = {"public_id": options["public_id"], "resource_type": options["resource_type"],
                  "type": options["type"], "version": 7, "bytes": len(data), "format": "wav"}
        self.assets[options["public_id"]] = result
        return result

    def destroy(self, public_id, **options):
        self.deletes.append((public_id, options))
        return {"result": "ok" if self.assets.pop(public_id, None) else "not found"}

    def resource(self, public_id, **options):
        if public_id not in self.assets:
            exc = RuntimeError("missing")
            exc.http_status = 404
            raise exc
        return self.assets[public_id]

    @staticmethod
    def private_download_url(public_id, fmt, **options):
        return f"https://api.cloudinary.test/download/{public_id}.{fmt}?expires_at={options['expires_at']}&type={options['type']}"


def store(clock=lambda: 1_800_000_000):
    sdk = FakeCloudinary()
    return CloudinaryRecordingStore(cloud_name="cloud", api_key="key", api_secret="secret", sdk=sdk,
                                    folder="private/recordings", clock=clock), sdk


def recording(asset_id="private/recordings/training/o/s/hash"):
    return SimpleNamespace(storage_asset_id=asset_id, storage_resource_type="video",
                           storage_delivery_type="authenticated", content_type="audio/wav", storage_key=None)


def test_cloudinary_upload_is_authenticated_audio_and_idempotent_identifier():
    st, sdk = store()
    meta = st.upload_recording("training/o/s/hash", b"RIFFdata", "audio/wav")
    assert meta == {"asset_id": "private/recordings/training/o/s/hash", "resource_type": "video",
                    "delivery_type": "authenticated", "version": 7, "status": "stored"}
    _, options = sdk.uploads[0]
    assert options["type"] == "authenticated" and options["resource_type"] == "video"
    assert options["overwrite"] is False and options["unique_filename"] is False


def test_cloudinary_playback_has_enforced_expiry_and_no_credentials():
    st, _ = store()
    url = st.get_secure_playback(recording(), 300)
    query = parse_qs(urlparse(url).query)
    assert query["expires_at"] == ["1800000300"] and query["type"] == ["authenticated"]
    assert "secret" not in url and "key" not in url
    for ttl in (0, 901):
        with pytest.raises(CloudinaryStoreError) as err:
            st.get_secure_playback(recording(), ttl)
        assert err.value.code == "bad_ttl" and not err.value.retryable


def test_cloudinary_metadata_delete_and_duplicate_delete_are_safe():
    st, sdk = store()
    meta = st.upload_recording("training/o/s/hash", b"1234", "audio/wav")
    rec = recording(meta["asset_id"])
    assert st.get_metadata(rec)["size_bytes"] == 4
    st.delete_recording(rec)
    st.delete_recording(rec)
    assert sdk.deletes[0][1] == {"resource_type": "video", "type": "authenticated", "invalidate": True}
    assert st.get_metadata(rec)["size_bytes"] is None


def test_cloudinary_auth_or_transport_failure_is_wrapped_without_secret():
    st, sdk = store()
    sdk.fail_upload = RuntimeError("401 secret must never be propagated")
    with pytest.raises(CloudinaryStoreError) as err:
        st.upload_recording("training/o/s/hash", b"x", "audio/wav")
    assert err.value.code == "upload_failed" and "secret" not in str(err.value)


@pytest.mark.parametrize("asset_id", ["", "/absolute", "training/../escape"])
def test_cloudinary_rejects_unsafe_asset_ids(asset_id):
    st, _ = store()
    with pytest.raises(CloudinaryStoreError):
        st.upload_recording(asset_id, b"x", "audio/wav")


class NamedStore(RecordingStore):
    def __init__(self, name):
        self.name = name


def test_provider_switch_preserves_rows_and_historical_s3_compatibility():
    settings = SimpleNamespace(recording_store="s3", recording_allowed_providers="s3,cloudinary")
    s3, cloud = NamedStore("s3"), NamedStore("cloudinary")
    service = RecordingService(settings, store=s3, stores={"s3": s3, "cloudinary": cloud})
    pinned = SimpleNamespace(storage_provider="cloudinary", storage_key="old-key")
    historical = SimpleNamespace(storage_provider=None, storage_key="legacy-key")
    assert service.provider_for_recording(pinned) is cloud
    settings.recording_store = "cloudinary"
    assert service.provider_for_recording(pinned) is cloud
    assert service.provider_for_recording(historical) is s3

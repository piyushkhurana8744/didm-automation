"""Private S3-compatible storage for training recordings (AWS S3, Cloudflare R2, MinIO and the like).

Signed with AWS Signature Version 4 over httpx, so no extra SDK is needed. What it guarantees:
- objects are never given a public ACL; the bucket must also block public access (deployment checklist);
- every upload asks for server-side encryption (S3_SSE, default AES256) and sends Content-MD5 and the
  payload's SHA-256, so the store rejects a corrupted body;
- keys come from the caller (training/{org}/{session}/{content hash}), so a retried upload writes the same
  object again instead of a second copy;
- playback is a presigned GET over HTTPS that expires within PRESIGN_MAX_SECONDS;
- credentials are only read from settings, never logged and never part of repr().
"""
import base64
import hashlib
import hmac
import logging
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import httpx

from .recordings import RecordingStore

log = logging.getLogger("didm.s3")

PRESIGN_MAX_SECONDS = 900
SSE_CHOICES = ("AES256", "aws:kms", "none")


class StoreError(Exception):
    def __init__(self, code: str, message: str = "", retryable: bool = True):
        super().__init__(message or code)
        self.code, self.retryable = code, retryable


def _uri_encode(s: str, keep_slash: bool) -> str:
    return quote(s, safe="-_.~/" if keep_slash else "-_.~")


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def signing_key(secret: str, date: str, region: str, service: str = "s3") -> bytes:
    k = _hmac(("AWS4" + secret).encode(), date)
    k = _hmac(k, region)
    k = _hmac(k, service)
    return _hmac(k, "aws4_request")


def canonical_query(params: dict) -> str:
    return "&".join(f"{_uri_encode(k, False)}={_uri_encode(str(v), False)}" for k, v in sorted(params.items()))


def sign(method: str, host: str, path: str, query: dict, headers: dict, payload_hash: str, *, access_key: str,
         secret: str, region: str, amz_date: str) -> tuple[str, str, str]:
    """Returns (signature, signed_headers, credential_scope) for one request. headers must include host."""
    date = amz_date[:8]
    scope = f"{date}/{region}/s3/aws4_request"
    lower = {k.lower(): " ".join(str(v).split()) for k, v in headers.items()}
    signed_headers = ";".join(sorted(lower))
    canonical = "\n".join([method, _uri_encode(path, True), canonical_query(query),
                           "".join(f"{k}:{lower[k]}\n" for k in sorted(lower)), signed_headers, payload_hash])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, _sha256_hex(canonical.encode())])
    sig = hmac.new(signing_key(secret, date, region), to_sign.encode(), hashlib.sha256).hexdigest()
    return sig, signed_headers, scope


class S3RecordingStore(RecordingStore):
    name = "s3"

    def __init__(self, *, endpoint: str, bucket: str, region: str, access_key_id: str, secret_access_key: str,
                 session_token: str = "", sse: str = "AES256", kms_key_id: str = "", path_style: bool = True,
                 client: httpx.Client | None = None, clock=None, timeout: float = 60):
        u = urlparse(endpoint)
        if u.scheme != "https" or not u.hostname or u.path not in ("", "/") or u.query or u.username:
            raise ValueError("S3_ENDPOINT must be a bare https:// address")
        if sse not in SSE_CHOICES:
            raise ValueError(f"S3_SSE must be one of {', '.join(SSE_CHOICES)}")
        if not (bucket and region and access_key_id and secret_access_key):
            raise ValueError("S3_BUCKET, S3_REGION, S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY are required")
        self.endpoint_host = u.netloc
        self.bucket, self.region, self.path_style = bucket, region, path_style
        self._access_key, self._secret, self._token = access_key_id, secret_access_key, session_token
        self.sse, self.kms_key_id = sse, kms_key_id
        self.client = client or httpx.Client(timeout=timeout)
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def __repr__(self):
        return f"S3RecordingStore(host={self.endpoint_host!r}, bucket={self.bucket!r}, sse={self.sse!r})"

    # ---------- addressing ----------
    def _host_path(self, key: str) -> tuple[str, str]:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise StoreError("bad_key", retryable=False)
        if self.path_style:
            return self.endpoint_host, f"/{self.bucket}/{key}"
        return f"{self.bucket}.{self.endpoint_host}", f"/{key}"

    def _amz_date(self) -> str:
        return self.clock().astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    def _request(self, method: str, key: str, body: bytes = b"", extra: dict | None = None) -> httpx.Response:
        host, path = self._host_path(key)
        amz_date = self._amz_date()
        payload_hash = _sha256_hex(body)
        headers = {"host": host, "x-amz-date": amz_date, "x-amz-content-sha256": payload_hash, **(extra or {})}
        if self._token:
            headers["x-amz-security-token"] = self._token
        sig, signed, scope = sign(method, host, path, {}, headers, payload_hash, access_key=self._access_key,
                                  secret=self._secret, region=self.region, amz_date=amz_date)
        headers["authorization"] = (f"AWS4-HMAC-SHA256 Credential={self._access_key}/{scope}, "
                                    f"SignedHeaders={signed}, Signature={sig}")
        send = {k: v for k, v in headers.items() if k != "host"}
        try:
            return self.client.request(method, f"https://{host}{_uri_encode(path, True)}", content=body or None,
                                       headers=send)
        except httpx.TransportError as exc:
            raise StoreError("store_unreachable", type(exc).__name__)

    @staticmethod
    def _check(resp: httpx.Response, ok: tuple, what: str):
        if resp.status_code in ok:
            return
        retryable = resp.status_code >= 500 or resp.status_code in (408, 429)
        # The body can name the bucket or key but never holds credentials; only the code is logged
        raise StoreError(f"{what}_failed", f"store answered {resp.status_code}", retryable=retryable)

    # ---------- RecordingStore ----------
    def put(self, key: str, data: bytes, content_type: str) -> None:
        md5 = hashlib.md5(data).digest()
        extra = {"content-type": content_type, "content-md5": base64.b64encode(md5).decode()}
        if self.sse != "none":
            extra["x-amz-server-side-encryption"] = self.sse
            if self.sse == "aws:kms" and self.kms_key_id:
                extra["x-amz-server-side-encryption-aws-kms-key-id"] = self.kms_key_id
        resp = self._request("PUT", key, data, extra)
        self._check(resp, (200,), "upload")
        if self.sse != "none" and resp.headers.get("x-amz-server-side-encryption") not in (None, self.sse):
            raise StoreError("encryption_mismatch", retryable=False)
        etag = resp.headers.get("etag", "").strip('"')
        if self.sse in ("AES256", "none") and etag and "-" not in etag and etag != md5.hex():
            raise StoreError("checksum_mismatch")
        log.info("s3 upload ok bytes=%s", len(data))

    def head(self, key: str) -> int | None:
        """Size of the stored object, or None when it does not exist."""
        resp = self._request("HEAD", key)
        if resp.status_code == 404:
            return None
        self._check(resp, (200,), "head")
        try:
            return int(resp.headers.get("content-length", ""))
        except ValueError:
            return None

    def delete(self, key: str) -> None:
        resp = self._request("DELETE", key)
        self._check(resp, (200, 204, 404), "delete")

    def presign(self, key: str, ttl_seconds: int) -> str:
        if not 1 <= ttl_seconds <= PRESIGN_MAX_SECONDS:
            raise StoreError("bad_ttl", retryable=False)
        host, path = self._host_path(key)
        amz_date = self._amz_date()
        query = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256",
                 "X-Amz-Credential": f"{self._access_key}/{amz_date[:8]}/{self.region}/s3/aws4_request",
                 "X-Amz-Date": amz_date, "X-Amz-Expires": str(ttl_seconds), "X-Amz-SignedHeaders": "host"}
        if self._token:
            query["X-Amz-Security-Token"] = self._token
        sig, _, _ = sign("GET", host, path, query, {"host": host}, "UNSIGNED-PAYLOAD", access_key=self._access_key,
                         secret=self._secret, region=self.region, amz_date=amz_date)
        return f"https://{host}{_uri_encode(path, True)}?{canonical_query(query)}&X-Amz-Signature={sig}"


def build_store(settings) -> tuple[RecordingStore | None, str | None]:
    """The configured store, or (None, why not). A bad setting turns recordings off instead of stopping
    the app, and /readyz reports it."""
    kind = settings.recording_store
    if not kind:
        return None, None
    if kind != "s3":
        return None, f"RECORDING_STORE={kind} is not supported (use s3)"
    try:
        return S3RecordingStore(endpoint=settings.s3_endpoint, bucket=settings.s3_bucket, region=settings.s3_region,
                                access_key_id=settings.s3_access_key_id,
                                secret_access_key=settings.s3_secret_access_key,
                                session_token=settings.s3_session_token, sse=settings.s3_sse,
                                kms_key_id=settings.s3_kms_key_id, path_style=settings.s3_path_style), None
    except ValueError as exc:
        return None, str(exc)


def build_stores(settings) -> tuple[dict[str, RecordingStore], list[str]]:
    """Build every platform-configured provider without allowing one bad provider to hide the others."""
    stores, problems = {}, []
    allowed = {x.strip() for x in (settings.recording_allowed_providers or "").split(",") if x.strip()}
    if settings.recording_store:
        allowed.add(settings.recording_store)
    if "s3" in allowed:
        # build_store is tied to RECORDING_STORE for backwards compatibility, so construct S3 directly.
        try:
            stores["s3"] = S3RecordingStore(endpoint=settings.s3_endpoint, bucket=settings.s3_bucket,
                region=settings.s3_region, access_key_id=settings.s3_access_key_id,
                secret_access_key=settings.s3_secret_access_key, session_token=settings.s3_session_token,
                sse=settings.s3_sse, kms_key_id=settings.s3_kms_key_id, path_style=settings.s3_path_style)
        except ValueError as exc:
            problems.append(f"s3: {exc}")
    if "cloudinary" in allowed:
        from .cloudinary_store import CloudinaryRecordingStore
        try:
            stores["cloudinary"] = CloudinaryRecordingStore(
                cloud_name=settings.cloudinary_cloud_name, api_key=settings.cloudinary_api_key,
                api_secret=settings.cloudinary_api_secret, folder=settings.cloudinary_folder)
        except (ValueError, ImportError) as exc:
            problems.append(f"cloudinary: {exc}")
    unknown = allowed - {"s3", "cloudinary"}
    problems.extend(f"{name}: unsupported recording provider" for name in sorted(unknown))
    return stores, problems

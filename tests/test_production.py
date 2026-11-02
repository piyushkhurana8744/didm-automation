"""Phase 5: S3 store, evaluator metering and budgets, retention, practice notice, SQL analytics and CSV,
readiness, and an end-to-end phone flow against a fake Sarvam and a fake S3 at the HTTP level."""
import base64
import csv
import hashlib
import io
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from sqlalchemy import func, select

from app.db import SessionLocal, WebhookEvent, utcnow
from app.saas import providers
from app.saas.analytics import safe_cell
from app.saas.intelligence import EvaluatorError, ImmutableRecord
from app.saas.models import (AuditEvent, BrowserSessionToken, EvaluationJob, EvaluationUsage, Membership,
                             PhoneVerificationChallenge, RetentionRun, TrainingEvaluation,
                             TrainingRecording, TrainingSession, TrainingTranscript, TrainingTranscriptTurn)
from app.saas.readiness import config_problems
from app.saas.retention import RetentionService
from app.saas.s3store import PRESIGN_MAX_SECONDS, S3RecordingStore, StoreError, build_store, sign
from tests.test_intelligence import (TRANSCRIPT, FakeEvaluator, FakeSource, FakeStore, card, enable_recordings,  # noqa: F401
                                     finished_session, good_answer, put, result, run, ti)
from tests.test_saas import saas  # noqa: F401  (fixture)
from tests.test_training import SECRET, row, set_limits, start, tw  # noqa: F401  (fixture)

AK, SK = "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


# ---------- fake S3 over HTTP ----------
class FakeS3:
    """Keeps objects in memory and checks what a real S3 would: a SigV4 Authorization header, the body's
    SHA-256 and MD5, and the encryption header."""

    def __init__(self):
        self.objects, self.requests, self.fail_next = {}, [], []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0))
        auth = request.headers.get("authorization", "")
        assert auth.startswith(f"AWS4-HMAC-SHA256 Credential={AK}/") and "Signature=" in auth
        assert "x-amz-acl" not in request.headers  # never a public ACL
        key = request.url.path
        if request.method == "PUT":
            body = request.content
            assert request.headers["x-amz-content-sha256"] == hashlib.sha256(body).hexdigest()
            assert base64.b64decode(request.headers["content-md5"]) == hashlib.md5(body).digest()
            sse = request.headers.get("x-amz-server-side-encryption")
            self.objects[key] = (body, request.headers.get("content-type"), sse)
            return httpx.Response(200, headers={"etag": f'"{hashlib.md5(body).hexdigest()}"',
                                                **({"x-amz-server-side-encryption": sse} if sse else {})})
        if request.method == "HEAD":
            if key not in self.objects:
                return httpx.Response(404)
            return httpx.Response(200, headers={"content-length": str(len(self.objects[key][0]))})
        if request.method == "DELETE":
            self.objects.pop(key, None)
            return httpx.Response(204)
        return httpx.Response(405)


def s3_store(fake=None, **kw):
    fake = fake or FakeS3()
    st = S3RecordingStore(endpoint="https://s3.test", bucket="recordings", region="ap-south-1", access_key_id=AK,
                          secret_access_key=SK, client=httpx.Client(transport=httpx.MockTransport(fake)), **kw)
    return st, fake


# ---------- S3 store ----------
def test_sigv4_matches_aws_published_examples():
    """Both examples from AWS's Signature Version 4 documentation for S3."""
    host = "examplebucket.s3.amazonaws.com"
    h = {"host": host, "range": "bytes=0-9", "x-amz-date": "20130524T000000Z",
         "x-amz-content-sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"}
    sig, signed, _ = sign("GET", host, "/test.txt", {}, h, h["x-amz-content-sha256"], access_key=AK, secret=SK,
                          region="us-east-1", amz_date="20130524T000000Z")
    assert sig == "f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41"
    assert signed == "host;range;x-amz-content-sha256;x-amz-date"
    q = {"X-Amz-Algorithm": "AWS4-HMAC-SHA256", "X-Amz-Credential": f"{AK}/20130524/us-east-1/s3/aws4_request",
         "X-Amz-Date": "20130524T000000Z", "X-Amz-Expires": "86400", "X-Amz-SignedHeaders": "host"}
    sig, _, _ = sign("GET", host, "/test.txt", q, {"host": host}, "UNSIGNED-PAYLOAD", access_key=AK, secret=SK,
                     region="us-east-1", amz_date="20130524T000000Z")
    assert sig == "aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"


def test_s3_upload_is_private_encrypted_checked_and_retry_safe():
    st, fake = s3_store()
    key = "training/org1/sess1/abcd"
    st.put(key, b"RIFFdata", "audio/wav")
    st.put(key, b"RIFFdata", "audio/wav")  # a retried upload writes the same object, not a second one
    assert list(fake.objects) == ["/recordings/" + key]
    data, ctype, sse = fake.objects["/recordings/" + key]
    assert data == b"RIFFdata" and ctype == "audio/wav" and sse == "AES256"
    assert st.head(key) == 8 and st.head("training/org1/other") is None
    st.delete(key)
    st.delete(key)  # deleting twice is fine
    assert fake.objects == {}


def test_s3_errors_are_classified_and_never_leak_credentials():
    st, fake = s3_store()
    fake.fail_next = [503]
    with pytest.raises(StoreError) as e:
        st.put("training/o/s/k", b"x", "audio/wav")
    assert e.value.retryable and e.value.code == "upload_failed"
    fake.fail_next = [403]
    with pytest.raises(StoreError) as e:
        st.put("training/o/s/k", b"x", "audio/wav")
    assert not e.value.retryable
    for bad in ("../etc/passwd", "/abs", "training/../x", ""):
        with pytest.raises(StoreError):
            st.put(bad, b"x", "audio/wav")
    assert SK not in repr(st) and AK not in repr(st)
    for r in fake.requests:
        assert SK not in str(r.url) and SK not in str(r.headers)


def test_s3_presigned_links_are_short_lived_https():
    now = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
    st, _ = s3_store(clock=lambda: now)
    url = st.presign("training/o/s/k", 300)
    u = urlparse(url)
    q = parse_qs(u.query)
    assert u.scheme == "https" and u.netloc == "s3.test" and u.path == "/recordings/training/o/s/k"
    assert q["X-Amz-Expires"] == ["300"] and q["X-Amz-Date"] == ["20261021T120000Z"] and len(q["X-Amz-Signature"][0]) == 64
    assert SK not in url
    for ttl in (0, PRESIGN_MAX_SECONDS + 1, 86400):
        with pytest.raises(StoreError):
            st.presign("training/o/s/k", ttl)


def test_s3_config_is_validated(saas):
    s = saas.settings
    s.recording_store = "s3"
    store, why = build_store(s)
    assert store is None and why
    assert any(p["key"] == "S3_*" for p in config_problems(s))
    s.s3_endpoint, s.s3_bucket, s.s3_region, s.s3_access_key_id, s.s3_secret_access_key = (
        "http://s3.test", "b", "r", "k", "secret")
    assert build_store(s)[0] is None
    assert any(p["key"] == "S3_ENDPOINT" for p in config_problems(s))
    s.s3_endpoint = "https://s3.test"
    store, why = build_store(s)
    assert store is not None and why is None and "secret" not in repr(store)
    s.s3_sse = "none"
    assert any(p["key"] == "S3_SSE" and p["level"] == "warn" for p in config_problems(s))
    s.recording_store = "ftp"
    assert build_store(s)[0] is None


def test_storage_reconciliation_marks_missing_objects(ti):
    a = ti.a
    version = enable_recordings(ti, a)
    rec = ti.app.state.recordings
    rec.store, fake = s3_store()
    sid = start(a, a.t1, recording_consent_version=version).json()["id"]
    result(ti, sid, a.id, attempt=row(sid).provider_attempt_id)
    run(ti)
    assert card(a, a.t1, sid).json()["recording"]["status"] == "stored"
    assert rec.verify_storage() == {"checked": 1, "missing": 0, "errors": 0}
    fake.objects.clear()  # someone deleted the object outside the app
    assert rec.verify_storage(now=utcnow() + timedelta(days=8))["missing"] == 1
    r = card(a, a.t1, sid).json()["recording"]
    assert r["status"] == "failed" and r["can_play"] is False


# ---------- evaluator: provider adapter ----------
def chat_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sarvam_evaluator_reports_usage_and_caps_output():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["key"] = req.headers.get("api-subscription-key")
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": '{"a": 1}'}}],
                                         "usage": {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}})
    ev = providers.SarvamChatEvaluator("key-1", "sarvam-105b", client=chat_client(handler), max_output_tokens=1234)
    raw, usage = ev.evaluate_metered("sys", "user", {"type": "object"})
    assert raw == {"a": 1} and usage == {"prompt_tokens": 900, "completion_tokens": 100, "total_tokens": 1000}
    b = seen["body"]
    assert b["max_tokens"] == 1234 and b["temperature"] == 0 and b["response_format"]["json_schema"]["strict"] is True
    assert seen["key"] == "key-1" and "key-1" not in repr(ev)


@pytest.mark.parametrize("resp,code,retryable", [
    (httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": "{"}}],
                               "usage": {"total_tokens": 4096}}), "output_truncated", True),
    (httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]}), "invalid_output", True),
    (httpx.Response(401, json={}), "evaluator_auth", False),
    (httpx.Response(400, json={}), "evaluator_rejected", False),
    (httpx.Response(429, headers={"Retry-After": "7"}), "evaluator_rate_limited", True),
    (httpx.Response(502), "evaluator_error", True),
])
def test_sarvam_evaluator_errors(resp, code, retryable):
    ev = providers.SarvamChatEvaluator("k", "m", client=chat_client(lambda req: resp))
    with pytest.raises(EvaluatorError) as e:
        ev.evaluate_metered("s", "u", {})
    assert e.value.code == code and e.value.retryable is retryable
    if code == "output_truncated":
        assert e.value.usage["total_tokens"] == 4096


def test_sarvam_evaluator_timeout():
    def handler(req):
        raise httpx.ReadTimeout("slow", request=req)
    with pytest.raises(EvaluatorError) as e:
        providers.SarvamChatEvaluator("k", "m", client=chat_client(handler)).evaluate_metered("s", "u", {})
    assert e.value.code == "evaluator_timeout" and e.value.retryable


# ---------- evaluator: metering and budgets ----------
class MeteredEvaluator(FakeEvaluator):
    def __init__(self, tokens=1000):
        super().__init__()
        self.tokens = tokens

    def evaluate_metered(self, system, user, schema):
        return self.evaluate(system, user, schema), {"prompt_tokens": self.tokens - 100, "completion_tokens": 100,
                                                     "total_tokens": self.tokens}


def usage_rows(sid=None):
    with SessionLocal() as db:
        q = select(EvaluationUsage)
        if sid:
            q = q.where(EvaluationUsage.session_id == sid)
        return db.scalars(q.order_by(EvaluationUsage.created_at)).all()


def test_every_evaluator_call_is_metered_with_tokens(ti):
    a = ti.a
    ti.intel.evaluator = MeteredEvaluator(tokens=1500)
    ti.intel.evaluator.answer = good_answer()
    sid = finished_session(ti, a, a.t1)
    run(ti)
    run(ti)
    rows = usage_rows(sid)
    assert len(rows) == 1 and rows[0].outcome == "ok" and rows[0].total_tokens == 1500
    assert rows[0].organization_id == a.id and rows[0].latency_ms is not None
    with SessionLocal() as db:
        assert db.scalars(select(TrainingEvaluation).where(TrainingEvaluation.session_id == sid)).one().total_tokens == 1500
    b = a.admin.get(f"{a.base}/training/settings").json()["evaluation"]["budget"]
    assert b["calls"] == 1 and b["tokens"] == 1500 and b["call_limit"] == 200


def test_invalid_output_stops_at_the_per_session_call_cap(ti):
    a = ti.a
    ti.settings.evaluation_max_calls_per_session = 2
    ti.intel.evaluator.answer = lambda s, u: {"nonsense": True}
    sid = finished_session(ti, a, a.t1)
    for i in range(8):
        run(ti, now=utcnow() + timedelta(hours=7 * (i + 1)))
    assert len(ti.intel.evaluator.calls) == 2  # never more paid calls than the cap
    assert [r.outcome for r in usage_rows(sid)] == ["invalid_output", "invalid_output"]
    ev = card(a, a.t1, sid).json()["evaluation"]
    assert ev["status"] == "failed" and ev["overall_score"] is None


def test_retryable_errors_also_count_toward_the_cap(ti):
    a = ti.a
    ti.settings.evaluation_max_calls_per_session = 3

    def boom(s, u):
        raise EvaluatorError("evaluator_error", "answered 502")
    ti.intel.evaluator.answer = boom
    sid = finished_session(ti, a, a.t1)
    for i in range(10):
        run(ti, now=utcnow() + timedelta(hours=7 * (i + 1)))
    assert len(ti.intel.evaluator.calls) == 3
    with SessionLocal() as db:
        ev = db.scalars(select(TrainingEvaluation).where(TrainingEvaluation.session_id == sid)).one()
        assert ev.status == "failed" and ev.error_code == "evaluator_error"


def test_monthly_call_budget_skips_evaluation_and_says_why(ti):
    a = ti.a
    set_limits(ti, a, evaluation_monthly_calls=1)
    s1 = finished_session(ti, a, a.t1)
    run(ti)
    run(ti)
    s2 = finished_session(ti, a, a.t2)
    run(ti)
    run(ti)
    assert len(ti.intel.evaluator.calls) == 1
    assert card(a, a.t1, s1).json()["evaluation"]["status"] == "completed"
    ev = card(a, a.t2, s2).json()["evaluation"]
    assert ev["status"] == "not_evaluated" and "monthly evaluation limit" in ev["reason"]
    st = a.admin.get(f"{a.base}/training/settings").json()["evaluation"]
    assert "monthly evaluation limit" in st["reason"]
    # Next month the budget is fresh, and an admin can evaluate the skipped session again
    assert ti.intel.budget_problem(SessionLocal(), a.id, now=utcnow() + timedelta(days=32)) is None
    set_limits(ti, a, clear=["evaluation_monthly_calls"])
    assert a.admin.post(f"{a.base}/training/sessions/{s2}/evaluate", {}).status_code == 200
    run(ti)
    assert card(a, a.t2, s2).json()["evaluation"]["status"] == "completed"


def test_token_budget_and_platform_daily_cap(ti):
    a, b = ti.a, ti.b
    ti.intel.evaluator = MeteredEvaluator(tokens=5000)
    ti.intel.evaluator.answer = good_answer()
    set_limits(ti, a, evaluation_monthly_tokens=4000)
    finished_session(ti, a, a.t1)
    run(ti)
    run(ti)
    finished_session(ti, a, a.t2)
    run(ti)
    run(ti)
    assert len(ti.intel.evaluator.calls) == 1  # the first call used the whole token budget
    with SessionLocal() as db:
        assert ti.intel.budget_problem(db, a.id) == "monthly_token_limit"
        assert ti.intel.budget_problem(db, b.id) is None  # budgets are per organization
        ti.settings.evaluation_platform_daily_calls = 1
        assert ti.intel.budget_problem(db, b.id) == "platform_daily_limit"


def test_budgets_are_set_by_platform_admins_only(ti):
    a = ti.a
    r = a.admin.c.put(f"/api/v1/platform/organizations/{a.id}/training-limits", json={"evaluation_monthly_calls": 9},
                      headers={"X-CSRF-Token": a.admin.c.cookies.get("didm_csrf")})
    assert r.status_code in (401, 403)
    assert set_limits(ti, a, evaluation_monthly_calls=9)["stored"]["evaluation_monthly_calls"] == 9


# ---------- practice-call notice ----------
def test_practice_notice_must_be_accepted_before_anything_is_reserved(ti):
    a = ti.a
    r = put(a.admin, f"{a.base}/training/settings", {"practice_notice_text": "This call is transcribed and scored by AI."})
    version = r.json()["practice_notice"]["version"]
    assert version and a.t1.get(f"{a.base}/training/availability").json()["practice_notice"]["version"] == version
    before = len(ti.eng.sarvam.calls)
    r = start(a, a.t1)
    assert r.status_code == 409 and r.headers["X-Error-Code"] == "notice_not_accepted"
    assert start(a, a.t1, practice_notice_version="old").status_code == 409
    with SessionLocal() as db:
        assert db.scalar(select(func.count(TrainingSession.id))) == 0
    assert len(ti.eng.sarvam.calls) == before
    r = start(a, a.t1, practice_notice_version=version)
    assert r.status_code == 201
    assert row(r.json()["id"]).practice_notice_reference == version
    # Another organization has no notice, so nothing changes there
    assert start(ti.b, ti.b.t1).status_code == 201
    put(a.admin, f"{a.base}/training/settings", {"practice_notice_text": ""})
    assert a.t2.get(f"{a.base}/training/availability").json()["practice_notice"] is None


# ---------- retention ----------
def evaluated_session(w, org, who):
    sid = finished_session(w, org, who)
    run(w)  # imports the transcript and queues the evaluation
    run(w)
    return sid


def age_session(sid, days):
    with SessionLocal() as db:
        s = db.get(TrainingSession, sid)
        s.ended_at = s.created_at = utcnow() - timedelta(days=days)
        db.commit()


def turns(sid):
    with SessionLocal() as db:
        t = db.scalars(select(TrainingTranscript).where(TrainingTranscript.session_id == sid)).one()
        return db.scalar(select(func.count(TrainingTranscriptTurn.id)).where(TrainingTranscriptTurn.transcript_id == t.id))


def test_retention_reports_first_then_enforces(ti):
    a, b = ti.a, ti.b
    old, new = evaluated_session(ti, a, a.t1), evaluated_session(ti, a, a.t2)
    other = evaluated_session(ti, b, b.t1)
    for sid in (old, other):
        age_session(sid, 100)
    put(a.admin, f"{a.base}/training/settings", {"transcript_retention_days": 90})
    svc = RetentionService(ti.settings, ti.app.state.recordings)
    report = {r["organization_id"]: r for r in svc.run(enforce=False)}
    assert report[a.id]["counts"]["transcripts"] == {"due": 1, "removed": 0, "failed": 0}
    assert report[b.id]["counts"]["transcripts"]["due"] == 0  # beta set no retention period
    assert turns(old) == 8
    score = card(a, a.t1, old).json()["evaluation"]["overall_score"]
    assert score is not None
    done = {r["organization_id"]: r for r in svc.run(enforce=True)}
    assert done[a.id]["counts"]["transcripts"]["removed"] == 1 and done[a.id]["status"] == "completed"
    assert turns(old) == 0 and turns(new) == 8 and turns(other) == 8
    c = card(a, a.t1, old).json()
    assert c["transcript"]["status"] == "removed" and c["transcript"]["turns"] == []
    assert c["evaluation"]["overall_score"] == score  # scores and coaching stay
    assert all("evidence" not in x and "explanation" not in x for x in c["evaluation"]["criteria"])
    assert c["evaluation"]["feedback"]["summary"]
    again = {r["organization_id"]: r for r in svc.run(enforce=True)}
    assert again[a.id]["counts"]["transcripts"] == {"due": 0, "removed": 0, "failed": 0}
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "retention.applied",
                                                                 AuditEvent.organization_id == a.id)) == 1
        assert db.scalar(select(func.count(RetentionRun.id)).where(RetentionRun.organization_id == a.id)) == 3


def test_evaluation_redaction_is_the_only_allowed_change(ti):
    a = ti.a
    sid = evaluated_session(ti, a, a.t1)
    with SessionLocal() as db:
        ev = db.scalars(select(TrainingEvaluation).where(TrainingEvaluation.session_id == sid)).one()
        ev.overall_score = 1
        ev.evidence_redacted_at = utcnow()
        with pytest.raises(ImmutableRecord):
            db.commit()


def test_legal_hold_stops_every_deletion(ti):
    a = ti.a
    version = enable_recordings(ti, a)
    sid = start(a, a.t1, recording_consent_version=version).json()["id"]
    result(ti, sid, a.id, attempt=row(sid).provider_attempt_id)
    run(ti)
    age_session(sid, 100)
    assert put(a.admin, f"{a.base}/training/settings", {"legal_hold": True}).status_code == 422  # needs a reason
    r = put(a.admin, f"{a.base}/training/settings", {"legal_hold": True, "legal_hold_reason": "Dispute 42",
                                                     "transcript_retention_days": 30})
    assert r.json()["retention"]["legal_hold"] is True
    assert put(a.trainer, f"{a.base}/training/settings", {"legal_hold": False}).status_code == 403
    svc = RetentionService(ti.settings, ti.app.state.recordings)
    later = utcnow() + timedelta(days=60)
    out = {x["organization_id"]: x for x in svc.run(now=later, enforce=True)}[a.id]
    assert out["status"] == "held" and out["counts"]["recordings"]["due"] == 1
    assert out["counts"]["transcripts"]["due"] == 1 and turns(sid) == 8
    assert card(a, a.t1, sid).json()["recording"]["status"] == "stored"
    put(a.admin, f"{a.base}/training/settings", {"legal_hold": False})
    out = {x["organization_id"]: x for x in svc.run(now=later, enforce=True)}[a.id]
    assert out["counts"]["recordings"]["removed"] == 1 and out["counts"]["transcripts"]["removed"] == 1
    with SessionLocal() as db:
        acts = set(db.scalars(select(AuditEvent.action).where(AuditEvent.organization_id == a.id)))
    assert {"training.legal_hold_set", "training.legal_hold_released"} <= acts


def test_failed_recording_deletion_is_counted_and_retried(ti):
    a = ti.a
    version = enable_recordings(ti, a)
    rec = ti.app.state.recordings
    rec.store, fake = s3_store()
    sid = start(a, a.t1, recording_consent_version=version).json()["id"]
    result(ti, sid, a.id, attempt=row(sid).provider_attempt_id)
    run(ti)
    ti.settings.retention_enforcement_enabled = True
    later = utcnow() + timedelta(days=31)
    fake.fail_next = [500]
    assert rec.sweep_retention(now=later) == 0
    with SessionLocal() as db:
        r = db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sid)).one()
        assert r.status == "stored" and r.delete_attempts == 1 and r.last_error == "delete_failed"
        run_row = db.scalars(select(RetentionRun).where(RetentionRun.organization_id == a.id)).first()
        assert run_row.status == "partial" and run_row.counts["recordings"]["failed"] == 1
    assert rec.sweep_retention(now=later) == 1
    assert fake.objects == {}
    assert card(a, a.t1, sid).json()["recording"]["status"] == "deleted"


def test_recording_deletion_needs_a_store(ti):
    a = ti.a
    version = enable_recordings(ti, a)
    sid = start(a, a.t1, recording_consent_version=version).json()["id"]
    result(ti, sid, a.id, attempt=row(sid).provider_attempt_id)
    run(ti)
    ti.app.state.recordings.store = None
    r = a.admin.delete(f"{a.base}/training/sessions/{sid}/recording")
    assert r.status_code == 503
    with SessionLocal() as db:
        assert db.scalars(select(TrainingRecording).where(TrainingRecording.session_id == sid)).one().status == "stored"


def test_webhook_bodies_tokens_and_codes_follow_retention(ti):
    a, b = ti.a, ti.b
    sid = evaluated_session(ti, a, a.t1)
    bsid = evaluated_session(ti, b, b.t1)
    old = utcnow() - timedelta(days=40)
    with SessionLocal() as db:
        for e in db.scalars(select(WebhookEvent)):
            e.created_at = old
        db.add(WebhookEvent(id="legacy-1", source="sarvam_result", payload={"phone": "+919800000000"},
                            payload_hash="x", status="done", created_at=old))
        m = db.scalars(select(Membership).where(Membership.organization_id == a.id)).first()
        db.add(PhoneVerificationChallenge(organization_id=a.id, membership_id=m.id, user_id=m.user_id,
                                          phone_e164="+919800000001", code_hash="h", expires_at=old))
        db.add(BrowserSessionToken(organization_id=a.id, session_id=sid, user_id=m.user_id, token_hash="t" * 64,
                                   expires_at=old))
        db.commit()
    put(b.owner, f"{b.base}/training/settings", {"legal_hold": True, "legal_hold_reason": "Audit"})
    svc = RetentionService(ti.settings, ti.app.state.recordings)
    out = {x["organization_id"]: x for x in svc.run(enforce=True)}
    assert out[a.id]["counts"]["webhook_payloads"]["removed"] == 1
    assert out[a.id]["counts"]["phone_challenges"]["removed"] == 1
    assert out[a.id]["counts"]["browser_tokens"]["removed"] == 1
    assert out[b.id]["status"] == "held" and out[b.id]["counts"]["webhook_payloads"]["due"] == 1
    with SessionLocal() as db:
        events = {e.id: e for e in db.scalars(select(WebhookEvent))}
        assert events["legacy-1"].payload == {"phone": "+919800000000"}  # lead-calling data is not touched
        redacted = [e for e in events.values() if e.redacted_at is not None]
        assert len(redacted) == 1
        p = redacted[0].payload
        assert p["redacted"] and p["session_id"] == sid and "interaction_transcript" not in p
        assert "instalments" not in json.dumps(p) and "+91" not in json.dumps(p)
        assert db.scalar(select(func.count(PhoneVerificationChallenge.id))) == 0
        assert db.scalar(select(func.count(BrowserSessionToken.id))) == 0
    assert card(b, b.t1, bsid).json()["transcript"]["turns"]


def test_retention_report_endpoint_changes_nothing(ti):
    a = ti.a
    sid = evaluated_session(ti, a, a.t1)
    age_session(sid, 100)
    put(a.admin, f"{a.base}/training/settings", {"transcript_retention_days": 30})
    r = a.admin.get(f"{a.base}/training/retention")
    assert r.status_code == 200
    body = r.json()
    assert body["due_now"]["transcripts"]["due"] == 1 and body["enforcement_enabled"] is False
    assert turns(sid) == 8 and body["runs"] == []
    assert a.trainer.get(f"{a.base}/training/retention").status_code == 403
    assert ti.b.owner.get(f"{ti.b.base}/training/retention").json()["due_now"]["transcripts"]["due"] == 0
    assert put(a.admin, f"{a.base}/training/settings", {"keep_transcripts": True}).json()["retention"][
        "transcript_retention_days"] is None


# ---------- analytics ----------
def test_analytics_pagination_and_rules(ti):
    a = ti.a
    evaluated_session(ti, a, a.t1)
    ti.intel.evaluator.answer = lambda s, u: {"bad": 1}
    ti.settings.evaluation_max_calls_per_session = 1
    finished_session(ti, a, a.t2)
    run(ti)
    run(ti)
    r = a.trainer.get(f"{a.base}/training/analytics?page_size=1").json()
    assert r["trainees_page"] == {"page": 1, "page_size": 1, "total": 2}
    assert len(r["trainees"]) == 1 and r["trainees"][0]["average_score"] is not None  # scored trainee first
    r2 = a.trainer.get(f"{a.base}/training/analytics?page_size=1&page=2").json()
    assert r2["trainees"][0]["average_score"] is None and r2["trainees"][0]["evaluated"] == 0
    assert r["totals"]["evaluated_sessions"] == 1 and r["totals"]["practice_sessions"] == 2
    assert r["totals"]["average_score"] == r["trainees"][0]["average_score"]  # the failed one is not averaged
    assert sum(r["score_distribution"].values()) == 1


def test_csv_export_is_tenant_scoped_audited_and_formula_safe(ti):
    a, b = ti.a, ti.b
    with SessionLocal() as db:
        from app.saas.models import User
        u = db.scalars(select(User).where(User.email == "t1@alpha.in")).one()
        u.name = "=HYPERLINK(\"http://evil\",\"x\")"
        db.commit()
    evaluated_session(ti, a, a.t1)
    evaluated_session(ti, b, b.t1)
    r = a.trainer.get(f"{a.base}/training/analytics/export.csv?kind=sessions")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0][0] == "session_id" and len(rows) == 2
    assert rows[1][2] == "t1@alpha.in" and rows[1][3].startswith("'=HYPERLINK")
    assert "beta" not in r.text
    t = list(csv.reader(io.StringIO(a.trainer.get(f"{a.base}/training/analytics/export.csv?kind=trainees").text)))
    assert t[0][0] == "user_id" and len(t) == 2
    assert a.t1.get(f"{a.base}/training/analytics/export.csv").status_code == 403
    assert b.owner.get(f"{a.base}/training/analytics/export.csv").status_code in (403, 404)
    assert a.trainer.get(f"{a.base}/training/analytics/export.csv?kind=users").status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(func.count(AuditEvent.id)).where(AuditEvent.action == "training.analytics_exported")) == 2


@pytest.mark.parametrize("value,expected", [("=1+1", "'=1+1"), ("+91 98", "'+91 98"), ("-2", "'-2"), ("@SUM(A1)", "'@SUM(A1)"),
                                            ("\tx", "'\tx"), ("\rx", "'\rx"), ("plain", "plain"), (5, "5"), (-3, "-3"),
                                            (None, ""), (True, "yes")])
def test_safe_cell(value, expected):
    assert safe_cell(value) == expected


# ---------- readiness ----------
def test_readiness_endpoints(ti):
    c = ti.browser().c
    r = c.get("/readyz")
    assert r.status_code == 200 and r.json() == {"ok": True, "database": "ok", "schema_up_to_date": True}
    assert c.get("/admin/readiness").status_code == 401
    d = c.get("/admin/readiness", headers={"Authorization": "Bearer adm"}).json()
    assert d["schema"]["current"] == d["schema"]["head"] == "0009_knowledge_domain"
    assert "queues" in d and "features" in d
    text = json.dumps(d)
    for secret in ("adm", "hook", SECRET):
        assert f'"{secret}"' not in text


def test_config_problems_flag_contradictions(saas):
    s = saas.settings
    s.training_phone_enabled, s.training_webhook_secret = True, ""
    s.evaluator_provider, s.sarvam_chat_api_key = "sarvam", ""
    keys = {p["key"] for p in config_problems(s)}
    assert {"TRAINING_WEBHOOK_SECRET", "SARVAM_CHAT_API_KEY", "SARVAM_API_KEY"} <= keys


# ---------- end to end: phone training against fake Sarvam and fake S3 over HTTP ----------
class FakeSarvamHTTP:
    """Answers the Sarvam endpoints we use, with the shapes from docs/phase4_sarvam_capabilities.md."""

    def __init__(self):
        self.outbounds, self.chat, self.fail_outbound = [], [], []
        self.attempts = {}  # attempt_id -> analytics row
        self.wav = b"RIFF" + (100).to_bytes(4, "little") + b"WAVE" + b"\0" * 100

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path = req.url.path
        if req.url.host == "apps.sarvam.ai" and path.startswith("/api/outbounds/") and path.endswith("/outbounds"):
            assert req.headers["x-api-key"] == "sk-test"
            if self.fail_outbound:
                f = self.fail_outbound.pop(0)
                if f == "timeout":
                    raise httpx.ReadTimeout("slow", request=req)
                return httpx.Response(f, json={"error": "busy"})
            body = json.loads(req.content)
            attempt = f"att-{len(self.outbounds) + 1}"
            self.outbounds.append({"attempt_id": attempt, **body})
            return httpx.Response(200, json={"attempt_id": attempt})
        if req.url.host == "apps.sarvam.ai" and "/api/analytics/v1/" in path:
            assert req.headers["x-api-key"] == "sk-test"
            if path.endswith("/attempts"):
                f = json.loads(req.url.params["filter_conditions"])[0]
                item = self.attempts.get(f["value"])
                return httpx.Response(200, json={"items": [item] if item else []})
            if "/recordings/" in path:
                return httpx.Response(200, content=self.wav, headers={"content-type": "audio/wav"})
        if req.url.host == "api.sarvam.ai" and path == "/v1/chat/completions":
            body = json.loads(req.content)
            self.chat.append(body)
            content = json.dumps(good_answer()(None, None))
            return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                                             "usage": {"prompt_tokens": 2000, "completion_tokens": 400,
                                                       "total_tokens": 2400}})
        return httpx.Response(404)

    def deliver(self, w, out, status="connected", duration=95, transcript=TRANSCRIPT, attempt=None):
        """Posts the result webhook exactly where and how the outbound request told Sarvam to."""
        u = urlparse(out["webhook_config"]["url"])
        payload = {"attempt_id": attempt or out["attempt_id"], "status": status, "duration": duration,
                   "interaction_id": f"int-{out['attempt_id']}", "interaction_transcript": transcript,
                   "webhook_config": out["webhook_config"]}
        return w.browser().c.post(u.path, json=payload)


@pytest.fixture
def e2e(ti, monkeypatch):
    from app.integrations import Sarvam
    s = ti.settings
    s.sarvam_api_key, s.sarvam_org_id, s.sarvam_workspace_id = "sk-test", "org-x", "ws-x"
    monkeypatch.setattr("app.integrations.time.sleep", lambda _: None)
    fake = FakeSarvamHTTP()
    client = httpx.Client(transport=httpx.MockTransport(fake))
    ti.eng.sarvam = Sarvam(s, client=client)
    analytics = providers.SarvamAnalytics(s, client=client)
    intel = ti.intel
    intel.evaluator = providers.SarvamChatEvaluator("chat-key", "sarvam-105b", client=client)
    intel.transcript_provider = intel.attempts_provider = analytics
    rec = ti.app.state.recordings
    ti.fake, ti.s3 = fake, None
    version = enable_recordings(ti, ti.a)
    rec.store, ti.s3 = s3_store()
    rec.source = providers.SarvamRecordingSource(s, client=client)
    ti.consent = version
    return ti


def test_end_to_end_phone_session_transcript_evaluation_recording(e2e):
    w, a = e2e, e2e.a
    r = start(a, a.t1, recording_consent_version=w.consent)
    assert r.status_code == 201, r.text
    sid = r.json()["id"]
    out = w.fake.outbounds[-1]
    assert out["user_config"]["user_phone_number"].startswith("+91")
    meta = out["webhook_config"]["metadata"]
    assert meta["session_id"] == sid and meta["org_id"] == a.id and out["webhook_config"]["url"].endswith(SECRET)
    assert row(sid).provider_attempt_id == out["attempt_id"] and row(sid).status == "connecting"
    assert w.fake.deliver(w, out).status_code == 200
    assert w.fake.deliver(w, out).status_code == 200  # Sarvam retries the same delivery: processed once
    assert row(sid).status == "completed" and row(sid).billable_seconds == 95
    run(w)
    run(w)
    c = card(a, a.t1, sid).json()
    assert c["transcript"]["status"] == "complete" and c["transcript"]["turn_count"] == 8
    assert c["evaluation"]["status"] == "completed" and c["evaluation"]["evaluator"]["model"] == "sarvam-105b"
    assert len(w.fake.chat) == 1 and w.fake.chat[0]["response_format"]["json_schema"]["strict"] is True
    assert c["recording"]["status"] == "stored" and c["recording"]["can_play"]
    (key, (data, ctype, sse)), = w.s3.objects.items()
    assert key.startswith(f"/recordings/training/{a.id}/{sid}/") and data == w.fake.wav and sse == "AES256"
    url = a.t1.post(f"{a.base}/training/sessions/{sid}/recording/playback").json()["url"]
    assert url.startswith("https://s3.test/recordings/training/") and "X-Amz-Expires=300" in url
    assert [u.total_tokens for u in usage_rows(sid)] == [2400]
    with SessionLocal() as db:
        jobs = {j.kind: j.status for j in db.scalars(select(EvaluationJob).where(EvaluationJob.session_id == sid))}
    assert jobs == {"transcript": "succeeded", "evaluation": "succeeded", "recording": "succeeded"}
    assert "chat-key" not in json.dumps(c) and "sk-test" not in json.dumps(c)


def test_end_to_end_webhook_auth_and_attempt_correlation(e2e):
    w, a = e2e, e2e.a
    sid = start(a, a.t1).json()["id"]
    out = w.fake.outbounds[-1]
    u = urlparse(out["webhook_config"]["url"])
    c = w.browser().c
    assert c.post(u.path.replace(SECRET, "wrong"), json={"attempt_id": out["attempt_id"]}).status_code == 404
    forged = json.loads(json.dumps(out))
    forged["webhook_config"]["metadata"]["org_id"] = w.b.id  # moving the result to another organization
    w.fake.deliver(w, forged)
    assert row(sid).status == "connecting"
    w.fake.deliver(w, out, attempt="att-999")  # right session, someone else's attempt
    assert row(sid).status == "connecting"
    w.fake.deliver(w, out)
    assert row(sid).status == "completed"


def test_end_to_end_start_retry_timeout_and_late_reconciliation(e2e):
    w, a = e2e, e2e.a
    w.fake.fail_outbound = [503]  # one server error, then the retry succeeds
    sid = start(a, a.t1).json()["id"]
    assert row(sid).status == "connecting" and len(w.fake.outbounds) == 1
    w.fake.deliver(w, w.fake.outbounds[-1], status="connected", duration=40)
    # The start request times out on every try: the session fails and capacity is released
    w.fake.fail_outbound = ["timeout"] * 3
    sid2 = start(a, a.t2).json()["id"]
    s2 = row(sid2)
    assert s2.status == "failed" and s2.failure_code == "provider_unreachable"
    assert s2.reconciliation_status == "pending"
    # Without an attempt id the call cannot be matched safely, so it is left unresolved, not guessed
    run(w)
    assert row(sid2).reconciliation_status == "unresolved"


def test_end_to_end_late_result_after_timeout_is_reconciled_through_lookup(e2e):
    w, a = e2e, e2e.a
    sid = start(a, a.t1).json()["id"]
    out = w.fake.outbounds[-1]
    w.eng.sweep(now=utcnow() + timedelta(minutes=60))  # no result in time: timed out at the maximum
    s = row(sid)
    assert s.status == "timed_out" and s.billable_seconds == s.max_duration_seconds
    w.fake.attempts[out["attempt_id"]] = {"attempt_id": out["attempt_id"], "connectivity_status": "Connected",
                                          "duration_in_seconds": 70, "interaction_id": "int-x"}
    for i in range(3):
        run(w, now=utcnow() + timedelta(minutes=5 * (i + 1)))
    s = row(sid)
    assert s.reconciliation_status == "corrected" and s.provider_duration_seconds == 70
    u = card(a, a.t1, sid).json()["usage"]
    assert u["quota_seconds"] == 70 and u["adjustment_seconds"] == 70 - s.max_duration_seconds


def test_end_to_end_caps_stop_calls_before_dialling(e2e):
    w, a = e2e, e2e.a
    set_limits(w, a, monthly_minutes=1)
    before = len(w.fake.outbounds)
    r = start(a, a.t1)
    assert r.status_code == 429 or r.status_code == 409
    assert len(w.fake.outbounds) == before

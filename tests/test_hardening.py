"""Migrations, durable webhooks, parallel processing, log redaction and the Sarvam client's defaults."""
import json
import logging
import threading
import time
from datetime import timedelta

import httpx
import pytest
import respx
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Base, SessionLocal, WebhookEvent, WhatsAppClaim, WhatsAppMessage, init_db, make_engine, utcnow
from app.integrations import CallTarget, Sarvam
from app.main import create_app
from app.migrate import alembic_config
from app.security import RedactSecretsFilter, redact
from app.service import Automation
from app.webhooks import WebhookProcessor, backoff
from tests.conftest import fresh_db_url
from tests.test_automation import FakeMailer, FakeSarvam, FakeSheet, FakeVeblika, H, live_settings, result, row

LEGACY_TABLES = {"call_attempts", "whatsapp_messages", "batches", "alerts", "settings"}


# ---------- migrations ----------
def _tables(url):
    return set(sa.inspect(make_engine(url)).get_table_names())


def test_fresh_database_migrates_to_models_exactly(tmp_path):
    url = fresh_db_url(tmp_path)
    eng = init_db(url)
    assert LEGACY_TABLES | {"webhook_events", "organizations", "users", "memberships", "invitations",
                            "auth_sessions", "audit_events", "alembic_version"} <= _tables(url)
    with eng.connect() as c:
        assert compare_metadata(MigrationContext.configure(c, opts={"compare_type": True}), Base.metadata) == []


def test_existing_create_all_database_keeps_its_rows(tmp_path):
    """A database made by the old app (create_all, no alembic_version) upgrades without losing data."""
    url = fresh_db_url(tmp_path)
    eng = make_engine(url)
    legacy = sa.MetaData()
    for name in LEGACY_TABLES:
        Base.metadata.tables[name].to_metadata(legacy)
    legacy.create_all(eng)
    with eng.begin() as c:
        c.execute(sa.text("INSERT INTO call_attempts (attempt_id, sheet_row, phone, name, state) "
                          "VALUES ('att-old', 5, '+919800000000', 'Old Lead', 'done')"))
        c.execute(sa.text("INSERT INTO settings (key, value) VALUES ('stopped', '1')"))
    init_db(url)
    with make_engine(url).connect() as c:
        assert c.execute(sa.text("SELECT name FROM call_attempts WHERE attempt_id='att-old'")).scalar() == "Old Lead"
        assert c.execute(sa.text("SELECT value FROM settings WHERE key='stopped'")).scalar() == "1"
        assert c.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "0011_trainee_training_variables"
    init_db(url)  # running again is a no-op


def test_downgrade_keeps_original_tables_and_upgrade_is_repeatable(tmp_path):
    url = fresh_db_url(tmp_path)
    init_db(url)
    cfg = alembic_config(url)
    command.downgrade(cfg, "0001_baseline")
    t = _tables(url)
    assert LEGACY_TABLES <= t and "users" not in t and "webhook_events" not in t
    command.upgrade(cfg, "head")
    assert "users" in _tables(url)


# ---------- webhooks ----------
@pytest.fixture
def hook_env(tmp_path):
    def make(rows=(), **kw):
        s = live_settings(tmp_path, **kw)
        sheet, sarvam, veb, mail = FakeSheet(list(rows)), FakeSarvam(), FakeVeblika(), FakeMailer()
        auto = Automation(s, sheet, sarvam, veb, mail, clock=lambda: __import__("tests.test_automation").test_automation.NOW)
        app = create_app(s, automation=auto, start_scheduler=False)
        return TestClient(app), app, auto, sheet, veb
    return make


def event_payload(phone="9810000001", **extra):
    return {"attempt_id": f"a-{phone}", "user_phone_number": "+91" + phone,
            "final_agent_variables": {"lead_name": "T"}, **extra}


def test_every_delivery_is_stored_before_processing(hook_env):
    client, app, auto, sheet, veb = hook_env([row("Riya", "9810512345")])
    client.post("/admin/dial", json={"count": 1}, headers=H)
    r = client.post("/webhooks/sarvam/hook", json=result("att-1", 2)).json()
    assert r["whatsapp"] == "sent" and r["event_id"]
    with SessionLocal() as db:
        ev = db.get(WebhookEvent, r["event_id"])
        assert ev.status == "done" and ev.attempt_id == "att-1" and ev.payload["status"] == "connected"


def test_queued_mode_acknowledges_then_worker_processes(hook_env):
    client, app, auto, sheet, veb = hook_env(event_template="obt", event_whatsapp_live=True, webhook_processing="queued")
    r = client.post("/webhooks/event/hook", json=event_payload())
    assert r.status_code == 200 and r.json()["accepted"] and veb.sent == []
    assert app.state.webhooks.drain() == 1
    assert veb.sent == ["919810000001"]


def test_bad_json_rejected_and_nothing_stored(hook_env):
    client, *_ = hook_env()
    assert client.post("/webhooks/event/hook", content=b"not json",
                       headers={"content-type": "application/json"}).status_code == 400
    assert client.post("/webhooks/event/hook", json=[1, 2]).status_code == 400
    with SessionLocal() as db:
        assert db.scalars(select(WebhookEvent)).first() is None


def test_storage_failure_is_not_acknowledged(hook_env, monkeypatch):
    client, app, *_ = hook_env(event_template="obt")
    monkeypatch.setattr(app.state.webhooks, "record", lambda *a: (_ for _ in ()).throw(RuntimeError("db down")))
    c = TestClient(app, raise_server_exceptions=False)
    assert c.post("/webhooks/event/hook", json=event_payload()).status_code == 500


def test_failures_retry_with_backoff_then_go_dead_and_admin_can_retry(hook_env):
    client, app, auto, sheet, veb = hook_env(event_template="obt", event_whatsapp_live=True, webhook_max_attempts=2)
    proc = app.state.webhooks
    proc.max_attempts = 2
    veb.ok = False  # Veblika answers 500: the handler asks for a retry
    r = client.post("/webhooks/event/hook", json=event_payload()).json()
    eid = r["event_id"]
    with SessionLocal() as db:
        ev = db.get(WebhookEvent, eid)
        assert ev.status == "failed" and ev.attempts == 1 and ev.next_attempt_at > utcnow()
    assert proc.drain() == 0  # not due yet
    with SessionLocal() as db:
        db.get(WebhookEvent, eid).next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert proc.drain() == 1
    with SessionLocal() as db:
        assert db.get(WebhookEvent, eid).status == "dead"
    dead = client.get("/admin/webhook-events?status=dead", headers=H).json()
    assert [d["id"] for d in dead] == [eid]
    assert client.get("/admin/webhook-events").status_code == 401
    veb.ok = True
    assert client.post(f"/admin/webhook-events/{eid}/retry", headers=H).json()["queued"] == eid
    assert proc.drain() == 1
    with SessionLocal() as db:
        assert db.get(WebhookEvent, eid).status == "done"
    assert veb.sent.count("919810000001") == 3  # two failed sends, one good one, no duplicates after success
    assert client.post(f"/admin/webhook-events/{eid}/retry", headers=H).status_code == 404


def test_handler_exception_is_recorded_not_swallowed(hook_env, monkeypatch, caplog):
    client, app, auto, *_ = hook_env(event_template="obt")
    monkeypatch.setattr(auto, "handle_event_call", lambda p: (_ for _ in ()).throw(ValueError("boom")))
    r = client.post("/webhooks/event/hook", json=event_payload()).json()
    assert r["ok"] is False
    with SessionLocal() as db:
        ev = db.get(WebhookEvent, r["event_id"])
        assert ev.status == "failed" and "ValueError: boom" in ev.last_error
    assert "webhook failed" in caplog.text


def test_backoff_is_bounded():
    assert backoff(1) == timedelta(seconds=30) and backoff(2) == timedelta(seconds=60)
    assert backoff(20) == timedelta(minutes=30)


def test_seventy_parallel_event_webhooks_send_once_each(hook_env):
    """The 19 Oct campaign shape: 70 results at once, some delivered twice. Each number gets one message."""
    client, app, auto, sheet, veb = hook_env(event_template="obt", event_whatsapp_live=True,
                                             webhook_processing="queued", webhook_workers=8)
    phones = [f"98100{i:05d}" for i in range(70)]
    for p in phones + phones[:10]:  # ten duplicate deliveries
        assert client.post("/webhooks/event/hook", json=event_payload(p)).status_code == 200
    proc = app.state.webhooks
    proc.workers = 8
    assert proc.drain() == 80
    assert sorted(veb.sent) == sorted("91" + p for p in phones)
    with SessionLocal() as db:
        assert db.scalar(select(sa.func.count(WhatsAppClaim.id))) == 70
        assert db.scalar(select(sa.func.count(WebhookEvent.id)).where(WebhookEvent.status == "done")) == 80


def test_parallel_duplicate_call_results_processed_once(hook_env):
    client, app, auto, sheet, veb = hook_env([row("Riya", "9810512345")], webhook_processing="queued")
    client.post("/admin/dial", json={"count": 1}, headers=H)
    for _ in range(6):
        client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    proc = app.state.webhooks
    proc.workers = 6
    assert proc.drain() == 6
    assert veb.sent == ["919810512345"]
    assert sum(1 for _, u in sheet.writes if u.get("status") == "Done: connected") == 1


def test_slow_webhook_does_not_block_other_requests(hook_env):
    client, app, auto, sheet, veb = hook_env(event_template="obt", event_whatsapp_live=True)
    gate = threading.Event()
    original = veb.send_template

    def slow(digits, *a, **k):
        if digits == "919810000001":  # only the first number is slow
            gate.wait(5)
        return original(digits, *a, **k)
    veb.send_template = slow
    t = threading.Thread(target=lambda: TestClient(app).post("/webhooks/event/hook", json=event_payload()))
    t.start()
    time.sleep(0.3)
    started = time.monotonic()
    assert TestClient(app).get("/healthz").status_code == 200
    second = TestClient(app).post("/webhooks/event/hook", json=event_payload("9810000002")).json()
    elapsed = time.monotonic() - started
    gate.set()
    t.join(5)
    assert elapsed < 2.5, f"other requests waited {elapsed:.1f}s behind a slow webhook"
    assert second["whatsapp"] == "sent"


def test_stale_whatsapp_claim_can_be_reclaimed(hook_env):
    client, app, auto, sheet, veb = hook_env(event_template="obt", event_whatsapp_live=True)
    with SessionLocal() as db:
        db.add(WhatsAppClaim(phone="+919810000001", kind="obt", state="sending", updated_at=utcnow() - timedelta(hours=1)))
        db.commit()
    assert client.post("/webhooks/event/hook", json=event_payload()).json()["whatsapp"] == "sent"
    with SessionLocal() as db:
        db.add(WhatsAppClaim(phone="+919810000009", kind="obt", state="sending", updated_at=utcnow()))
        db.commit()
    assert client.post("/webhooks/event/hook", json=event_payload("9810000009")).json()["whatsapp"].startswith("skipped")


# ---------- security ----------
def test_secrets_redacted_from_access_logs():
    assert redact('"POST /webhooks/sarvam/s3cr3t HTTP/1.1" 200') == '"POST /webhooks/sarvam/*** HTTP/1.1" 200'
    assert redact("GET /dashboard?token=abc+def&x=1") == "GET /dashboard?token=***&x=1"
    rec = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s"', ("1.2.3.4", "GET",
                            "/admin/check?token=topsecret"), None)
    RedactSecretsFilter().filter(rec)
    assert "topsecret" not in rec.getMessage()


def test_admin_token_failures_rate_limited(hook_env):
    client, *_ = hook_env()
    codes = [client.get("/admin/check", headers={"Authorization": "Bearer wrong"}).status_code for _ in range(21)]
    assert codes[:20] == [401] * 20 and codes[20] == 429
    assert client.get("/admin/check", headers=H).status_code == 200  # the right token still works


def test_legacy_query_token_still_works_for_dashboard(hook_env):
    client, *_ = hook_env()
    assert client.get("/dashboard?token=adm").status_code == 200


# ---------- Sarvam client backward compatibility ----------
@respx.mock
def test_sarvam_default_request_unchanged_and_target_override(tmp_path):
    s = live_settings(tmp_path)
    route = respx.post("https://apps.sarvam.ai/api/outbounds/v1/orgs/o/workspaces/w/outbounds").mock(
        return_value=httpx.Response(200, json={"attempt_id": "abc"}))
    Sarvam(s).start_call("+919810512345", {"lead_name": "Riya"}, {"row": "2"})
    assert json.loads(route.calls[0].request.content) == {
        "app_config": {"app_id": "a", "app_version": 7,
                       "connection_config": {"connection_id": "c", "agent_phone_number": "+917965853567"},
                       "agent_variables": {"lead_name": "Riya"}},
        "user_config": {"user_phone_number": "+919810512345"},
        "webhook_config": {"url": "https://automation.example.in/webhooks/sarvam/hook", "metadata": {"row": "2"}},
    }
    target = CallTarget(app_id="training-agent", app_version=3, connection_id="c2", agent_phone="+911111111111")
    Sarvam(s).start_call("+919810512345", {}, {"session_id": "s1"}, target=target,
                         webhook_url="https://automation.example.in/webhooks/training/x")
    body = json.loads(route.calls[1].request.content)
    assert body["app_config"]["app_id"] == "training-agent" and body["app_config"]["app_version"] == 3
    assert body["app_config"]["connection_config"] == {"connection_id": "c2", "agent_phone_number": "+911111111111"}
    assert body["webhook_config"] == {"url": "https://automation.example.in/webhooks/training/x",
                                      "metadata": {"session_id": "s1"}}
    assert CallTarget.from_settings(s) == CallTarget("a", 7, "c", "+917965853567")

from datetime import datetime, timedelta

import httpx
import pytest
import respx
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db import Batch, CallAttempt, SessionLocal, WhatsAppMessage
from app.integrations import Sarvam, Veblika
from app.leads import Lead, pick_next, to_e164
from app.main import create_app
from app.service import Automation
from tests.conftest import fresh_db_url

NOW = datetime(2026, 10, 16, 11, 0)


def row(name, phone, call="YES", status="", called_at="", outcome="", attempts="", followup="", course="", source=""):
    r = [""] * 22
    r[0], r[1], r[2], r[3], r[5], r[6], r[7], r[9], r[19], r[21] = (
        name, phone, course, source, call, status, called_at, outcome, attempts, followup)
    return r


class FakeSheet:
    def __init__(self, rows):
        self.rows = {i + 2: r for i, r in enumerate(rows)}
        self.writes = []
        self.fail_writes = False

    def read_rows(self):
        return sorted(self.rows.items())

    def update_row(self, r, updates):
        if self.fail_writes:
            raise RuntimeError("sheet down")
        from app.leads import COL
        self.writes.append((r, updates))
        for k, v in updates.items():
            self.rows[r][COL[k]] = str(v)


class FakeSarvam:
    def __init__(self, ok=True):
        self.ok = ok
        self.calls = []

    def start_call(self, phone, variables, metadata):
        self.calls.append((phone, variables, metadata))
        n = len(self.calls)
        if self.ok:
            return {"ok": True, "status_code": 200, "attempt_id": f"att-{n}", "error": None}
        return {"ok": False, "status_code": 400, "attempt_id": None, "error": "bad request"}


class FakeVeblika:
    def __init__(self, ok=True):
        self.ok, self.sent, self.calls = ok, [], []

    def send_template(self, digits, template=None, language=None, header_image_url=None, extra_params=None):
        self.sent.append(digits)
        self.calls.append((digits, template, header_image_url))
        self.extra = extra_params
        return {"ok": self.ok, "status_code": 200 if self.ok else 500, "error": None if self.ok else "boom"}


class FakeMailer:
    enabled = True

    def __init__(self):
        self.sent = []

    def send(self, subject, body):
        self.sent.append((subject, body))
        return True


def live_settings(tmp_path, **kw):
    s = Settings()
    vals = dict(dry_run=False, database_url=fresh_db_url(tmp_path), admin_token="adm", webhook_secret="hook",
                public_base_url="https://automation.example.in", spreadsheet_id="sheet", google_service_account_json="{}",
                sarvam_api_key="k", sarvam_org_id="o", sarvam_workspace_id="w", sarvam_app_id="a", sarvam_app_version=7,
                sarvam_connection_id="c", sarvam_agent_phone="+917965853567", veblika_api_key="v",
                veblika_phone_no_id="p", veblika_template="tpl", max_parallel_calls=1, daily_call_cap=100)
    vals.update(kw)
    for k, v in vals.items():
        setattr(s, k, v)
    return s


@pytest.fixture
def env(tmp_path):
    def make(rows, clock=lambda: NOW, sarvam_ok=True, wa_ok=True, **kw):
        s = live_settings(tmp_path, **kw)
        sheet, sarvam, veb, mail = FakeSheet(rows), FakeSarvam(sarvam_ok), FakeVeblika(wa_ok), FakeMailer()
        auto = Automation(s, sheet, sarvam, veb, mail, clock=clock)
        app = create_app(s, automation=auto, start_scheduler=False)
        client = TestClient(app)
        return client, auto, sheet, sarvam, veb, mail
    return make


H = {"Authorization": "Bearer adm"}


def result(att, rownum, status="connected", disposition="interested", **fav):
    return {"attempt_id": att, "status": status, "duration": 75.4,
            "final_agent_variables": {"disposition": disposition, "call_summary": "Talked about MIDM", **fav} if status == "connected" else None,
            "failure_reason": None, "webhook_config": {"metadata": {"row": str(rownum)}}}


# ---------- lead rules ----------
def test_phone_formats():
    assert to_e164("98105 12345") == "+919810512345"
    assert to_e164("+91-98105-12345") == "+919810512345"
    assert to_e164("09810512345") == "+919810512345"
    assert to_e164("12345") is None


def test_queue_rules_match_sheet_formula():
    gap = timedelta(hours=2)
    leads = [
        Lead.from_row(2, row("Old retry", "9000000001", status="Done: no_answer", called_at="2026-10-16 08:00", attempts="1")),
        Lead.from_row(3, row("New", "9000000002")),
        Lead.from_row(4, row("Not yes", "9000000003", call="")),
        Lead.from_row(5, row("Connected", "9000000004", status="Done: connected", outcome="interested", attempts="1")),
    ]
    assert pick_next(leads, NOW, 3, gap).name == "New"  # new leads first
    leads.pop(1)
    assert pick_next(leads, NOW, 3, gap).name == "Old retry"


def test_retry_waits_gap_and_max_attempts():
    gap = timedelta(hours=2)
    recent = Lead.from_row(2, row("R", "9000000001", status="Done: busy", called_at="2026-10-16 10:00", attempts="1"))
    maxed = Lead.from_row(3, row("M", "9000000002", status="Done: no_answer", called_at="2026-10-16 07:00", attempts="3"))
    voicemail = Lead.from_row(4, row("V", "9000000003", status="Done: connected", outcome="voicemail_left",
                                     called_at="2026-10-16 07:00", attempts="1"))
    assert pick_next([recent, maxed], NOW, 3, gap) is None
    assert pick_next([recent, maxed, voicemail], NOW, 3, gap).name == "V"


def test_do_not_call_blocks_every_row_with_that_number():
    leads = [Lead.from_row(2, row("A", "9000000001", status="Done: connected", outcome="do_not_call")),
             Lead.from_row(3, row("A again", "+91 90000 00001"))]
    assert pick_next(leads, NOW, 3, timedelta(hours=2)) is None


# ---------- dialling ----------
def test_dial_marks_sheet_and_sends_variables(env):
    client, auto, sheet, sarvam, *_ = env([row("Riya", "9810512345", course="Master course", source="Facebook")])
    r = client.post("/admin/dial", json={"count": 5}, headers=H).json()
    assert r["ok"] and r["dialled_now"] == 1
    phone, variables, meta = sarvam.calls[0]
    assert phone == "+919810512345"
    assert variables["lead_name"] == "Riya" and variables["course_interest"] == "Master course"
    assert meta["row"] == "2"
    assert sheet.rows[2][6] == "HTTP 200" and sheet.rows[2][8] == "att-1" and sheet.rows[2][19] == "1"


def test_admin_token_required(env):
    client, *_ = env([row("Riya", "9810512345")])
    assert client.post("/admin/dial", json={"count": 1}).status_code == 401
    assert client.post("/admin/dial", json={"count": 1}, headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_outside_calling_hours_no_calls(env):
    client, auto, sheet, sarvam, *_ = env([row("Riya", "9810512345")], clock=lambda: NOW.replace(hour=21, minute=5))
    r = client.post("/admin/dial", json={"count": 1}, headers=H).json()
    assert not r["ok"] and "calling hours" in r["reason"]
    assert sarvam.calls == []


def test_live_refuses_when_settings_missing(env):
    client, auto, sheet, sarvam, *_ = env([row("Riya", "9810512345")], sarvam_api_key="")
    r = client.post("/admin/dial", json={"count": 1}, headers=H).json()
    assert not r["ok"] and "SARVAM_API_KEY" in r["reason"]


def test_batch_chains_next_call_after_result(env):
    client, auto, sheet, sarvam, veb, _ = env([row("A", "9000000001"), row("B", "9000000002"), row("C", "9000000003")])
    client.post("/admin/dial", json={"count": 2}, headers=H)
    assert len(sarvam.calls) == 1  # one at a time
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    assert len(sarvam.calls) == 2 and sarvam.calls[1][2]["row"] == "3"
    client.post("/webhooks/sarvam/hook", json=result("att-2", 3, status="no_answer"))
    assert len(sarvam.calls) == 2  # batch of 2 done, C not called
    with SessionLocal() as s:
        assert s.scalars(select(Batch)).first().active is False


def test_parallel_calls(env):
    client, auto, sheet, sarvam, *_ = env([row(n, f"900000000{i}") for i, n in enumerate("ABCD")], max_parallel_calls=3)
    client.post("/admin/dial", json={"count": 10}, headers=H)
    assert len(sarvam.calls) == 3
    assert len({c[0] for c in sarvam.calls}) == 3


def test_daily_cap(env):
    client, auto, sheet, sarvam, _, mail = env([row(n, f"900000000{i}") for i, n in enumerate("ABC")],
                                               daily_call_cap=1, max_parallel_calls=5)
    client.post("/admin/dial", json={"count": 10}, headers=H)
    assert len(sarvam.calls) == 1


def test_stop_and_resume(env):
    client, auto, sheet, sarvam, *_ = env([row("A", "9000000001"), row("B", "9000000002")])
    client.post("/admin/dial", json={"count": 5}, headers=H)
    client.post("/admin/stop", headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    assert len(sarvam.calls) == 1  # no new call after stop
    assert not client.post("/admin/dial", json={"count": 1}, headers=H).json()["ok"]
    client.post("/admin/resume", headers=H)
    assert client.post("/admin/dial", json={"count": 1}, headers=H).json()["ok"]
    assert len(sarvam.calls) == 2


def test_start_failures_alert_and_stop_after_three(env):
    client, auto, sheet, sarvam, _, mail = env([row(n, f"900000000{i}") for i, n in enumerate("ABCDE")], sarvam_ok=False)
    client.post("/admin/dial", json={"count": 5}, headers=H)
    assert len(sarvam.calls) == 3
    assert any("3 calls in a row" in subj for subj, _ in mail.sent)
    assert sheet.rows[2][6] == "HTTP 400" and sheet.rows[2][15] == "bad request"


def test_sheet_down_no_call_placed(env):
    client, auto, sheet, sarvam, _, mail = env([row("A", "9000000001")])
    sheet.fail_writes = True
    client.post("/admin/dial", json={"count": 1}, headers=H)
    assert sarvam.calls == []
    assert mail.sent


# ---------- results ----------
def test_result_written_like_make(env):
    client, auto, sheet, sarvam, veb, _ = env([row("Riya", "9810512345")])
    client.post("/admin/dial", json={"count": 1}, headers=H)
    payload = result("att-1", 2, disposition="callback_requested", interested_program="MIDM",
                     preferred_mode="classroom", preferred_centre="Rajouri Garden", user_goal="job",
                     callback_details="tomorrow 5pm")
    r = client.post("/webhooks/sarvam/hook", json=payload).json()
    assert r["ok"] and r["whatsapp"] == "sent"
    v = sheet.rows[2]
    assert v[6] == "Done: connected" and v[9] == "callback_requested" and v[10] == "MIDM"
    assert v[12] == "Rajouri Garden" and v[14] == "tomorrow 5pm" and v[16] == "75"
    assert v[21].startswith("WA tpl") and "HTTP 200" in v[21]
    assert veb.sent == ["919810512345"]


def test_no_answer_outcome_and_whatsapp(env):
    client, auto, sheet, sarvam, veb, _ = env([row("Riya", "9810512345")])
    client.post("/admin/dial", json={"count": 1}, headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2, status="no_answer"))
    assert sheet.rows[2][6] == "Done: no_answer" and sheet.rows[2][9] == "no_answer"
    assert len(veb.sent) == 1


def test_connected_without_disposition_is_hung_up_early(env):
    client, auto, sheet, *_ = env([row("Riya", "9810512345")])
    client.post("/admin/dial", json={"count": 1}, headers=H)
    p = result("att-1", 2)
    p["final_agent_variables"] = {}
    client.post("/webhooks/sarvam/hook", json=p)
    assert sheet.rows[2][9] == "hung_up_early"


def test_duplicate_webhook_ignored(env):
    client, auto, sheet, sarvam, veb, _ = env([row("Riya", "9810512345")])
    client.post("/admin/dial", json={"count": 1}, headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    r = client.post("/webhooks/sarvam/hook", json=result("att-1", 2)).json()
    assert r.get("duplicate") and len(veb.sent) == 1


def test_no_whatsapp_for_do_not_call_or_already_sent(env):
    client, auto, sheet, sarvam, veb, _ = env([row("A", "9000000001"), row("B", "9000000002", followup="WA earlier")])
    client.post("/admin/dial", json={"count": 2}, headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2, disposition="do_not_call"))
    client.post("/webhooks/sarvam/hook", json=result("att-2", 3))
    assert veb.sent == []


def test_whatsapp_failure_alerts(env):
    client, auto, sheet, sarvam, veb, mail = env([row("A", "9000000001")], wa_ok=False)
    client.post("/admin/dial", json={"count": 1}, headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    assert "HTTP 500" in sheet.rows[2][21]
    assert any("WhatsApp" in s for s, _ in mail.sent)


def test_wrong_webhook_secret_rejected(env):
    client, *_ = env([row("A", "9000000001")])
    assert client.post("/webhooks/sarvam/nope", json=result("x", 2)).status_code == 404


def test_stuck_call_closed_and_queue_moves(env):
    client, auto, sheet, sarvam, *_ = env([row("A", "9000000001"), row("B", "9000000002")])
    client.post("/admin/dial", json={"count": 2}, headers=H)
    with SessionLocal() as s:
        c = s.scalars(select(CallAttempt)).first()
        c.started_at = c.started_at - timedelta(hours=1)
        s.commit()
    assert auto.check_stuck_calls() == 1
    assert sheet.rows[2][6] == "Done: no_result"
    assert len(sarvam.calls) == 2


# ---------- reports and dashboard ----------
def test_summary_report_and_dashboard(env):
    client, auto, sheet, sarvam, veb, mail = env([row("A", "9000000001"), row("B", "9000000002")])
    client.post("/admin/dial", json={"count": 2}, headers=H)
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    client.post("/webhooks/sarvam/hook", json=result("att-2", 3, status="busy"))
    sm = client.get("/admin/summary", headers=H).json()
    assert sm["calls_started"] == 2 and sm["connected"] == 1 and sm["whatsapp_sent"] == 2
    assert client.post("/admin/send-report", headers=H).json()["emailed"]
    assert "Calls started: 2" in mail.sent[-1][1]
    page = client.get("/dashboard?token=adm")
    assert page.status_code == 200 and "Connected" in page.text


# ---------- test mode ----------
def test_dry_run_never_calls_out(tmp_path):
    s = live_settings(tmp_path, dry_run=True)
    from app.main import DryRunSheet
    real = FakeSheet([row("A", "9000000001")])
    sheet, sarvam, veb = DryRunSheet(real), FakeSarvam(), FakeVeblika()
    auto = Automation(s, sheet, sarvam, veb, FakeMailer(), clock=lambda: NOW)
    client = TestClient(create_app(s, automation=auto, start_scheduler=False))
    assert client.post("/admin/dial", json={"count": 1}, headers=H).json()["dialled_now"] == 1
    r = client.post("/admin/simulate-result", json={"row": 2}, headers=H).json()
    assert r["ok"] and r["whatsapp"] == "sent"
    assert sarvam.calls == [] and veb.sent == [] and real.writes == []
    assert sheet.writes  # intended writes were recorded


# ---------- real HTTP clients ----------
@respx.mock
def test_sarvam_client_request_shape(tmp_path):
    s = live_settings(tmp_path)
    route = respx.post("https://apps.sarvam.ai/api/outbounds/v1/orgs/o/workspaces/w/outbounds").mock(
        return_value=httpx.Response(200, json={"attempt_id": "abc"}))
    res = Sarvam(s).start_call("+919810512345", {"lead_name": "Riya"}, {"row": "2"})
    assert res["ok"] and res["attempt_id"] == "abc"
    req = route.calls[0].request
    assert req.headers["X-API-Key"] == "k"
    body = __import__("json").loads(req.content)
    assert body["app_config"]["app_version"] == 7
    assert body["webhook_config"]["url"] == "https://automation.example.in/webhooks/sarvam/hook"


@respx.mock
def test_sarvam_client_retries_server_errors(tmp_path, monkeypatch):
    monkeypatch.setattr("app.integrations.time.sleep", lambda *_: None)
    s = live_settings(tmp_path)
    route = respx.post("https://apps.sarvam.ai/api/outbounds/v1/orgs/o/workspaces/w/outbounds").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"attempt_id": "x"})])
    assert Sarvam(s).start_call("+919810512345", {}, {})["ok"]
    assert route.call_count == 2


@respx.mock
def test_veblika_client(tmp_path):
    s = live_settings(tmp_path, veblika_auth_name="apikey", veblika_auth_in="query")
    route = respx.get(s.veblika_url).mock(return_value=httpx.Response(200, json={"ok": True}))
    assert Veblika(s).send_template("919810512345")["ok"]
    q = route.calls[0].request.url.params
    assert q["to"] == "919810512345" and q["name"] == "tpl" and q["apikey"] == "v"


@respx.mock
def test_google_sheet_client(tmp_path, monkeypatch):
    from app.integrations import GoogleSheet
    s = live_settings(tmp_path)
    g = GoogleSheet(s)
    monkeypatch.setattr(g, "_token", lambda: "tok")
    base = "https://sheets.googleapis.com/v4/spreadsheets/sheet"
    respx.get(f"{base}/values/Leads!A2:V").mock(return_value=httpx.Response(200, json={"values": [["A", "9000000001"]]}))
    up = respx.post(f"{base}/values:batchUpdate").mock(return_value=httpx.Response(200, json={}))
    assert g.read_rows() == [(2, ["A", "9000000001"])]
    g.update_row(5, {"status": "Calling", "followup": "WA"})
    body = __import__("json").loads(up.calls[0].request.content)
    assert {d["range"] for d in body["data"]} == {"Leads!G5", "Leads!V5"}
    assert up.calls[0].request.headers["Authorization"] == "Bearer tok"


def test_admin_token_with_plus_in_address_bar(tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    s = Settings(admin_token="ab+cd", database_url=f"sqlite:///{tmp_path}/t.db")
    client = TestClient(create_app(s, start_scheduler=False))
    assert client.get("/admin/check?token=ab+cd").status_code == 200
    assert client.get("/admin/check?token=wrong").status_code == 401


def test_auto_dial_starts_batch_only_when_leads_wait(env):
    client, auto, sheet, sarvam, *_ = env([row("A", "9000000001"), row("B", "9000000002")],
                                          auto_dial_minutes=15, auto_dial_batch=5)
    assert auto.auto_dial()["ok"]
    assert len(sarvam.calls) == 1
    # a batch is running: the timer only tops it up, no second batch
    auto.auto_dial()
    with SessionLocal() as s:
        assert len(s.scalars(select(Batch)).all()) == 1
    client.post("/webhooks/sarvam/hook", json=result("att-1", 2))
    client.post("/webhooks/sarvam/hook", json=result("att-2", 3))
    # everyone called: the timer does nothing and opens no empty batch
    r = auto.auto_dial()
    assert not r["ok"] and r["reason"] == "no leads waiting"
    assert len(sarvam.calls) == 2


def test_auto_dial_respects_hours_and_stop(env):
    client, auto, sheet, sarvam, *_ = env([row("A", "9000000001")], clock=lambda: NOW.replace(hour=22))
    assert not auto.auto_dial()["ok"]
    client2, auto2, _, sarvam2, *_ = env([row("A", "9000000001")])
    client2.post("/admin/stop", headers=H)
    assert not auto2.auto_dial()["ok"]
    assert sarvam.calls == [] and sarvam2.calls == []


# ---------- event invites ----------
def event_payload(phone="+919810000001", next_action=None, rsvp="coming"):
    return {"app_id": "conv", "app_version": 1, "attempt_id": "e1", "campaign_id": "camp", "cohort_id": "c",
            "completion_status": "completed", "connectivity_status": "connected", "user_identifier": "u",
            "user_phone_number": phone, "next_action_status": next_action,
            "final_agent_variables": {"rsvp": rsvp}}


def test_event_whatsapp_sent_once_per_number(env):
    client, auto, sheet, sarvam, veb, mail = env([], event_template="convocation_invite", event_whatsapp_live=True,
                                                 event_header_image_url="https://x/media/convocation.jpg")
    r = client.post("/webhooks/event/hook", json=event_payload()).json()
    assert r["whatsapp"] == "sent"
    assert veb.calls == [("919810000001", "convocation_invite", "https://x/media/convocation.jpg")]
    r = client.post("/webhooks/event/hook", json=event_payload()).json()
    assert r["whatsapp"] == "skipped: already sent to this number"
    assert len(veb.calls) == 1


def test_event_whatsapp_waits_for_final_attempt_and_test_mode(env):
    client, auto, sheet, sarvam, veb, mail = env([], event_template="convocation_invite")
    assert client.post("/webhooks/event/hook", json=event_payload(next_action="retry")).json()["whatsapp"].startswith("skipped")
    assert client.post("/webhooks/event/hook", json=event_payload()).json()["whatsapp"] == "test mode"
    assert veb.calls == []
    assert client.post("/webhooks/event/wrong", json=event_payload()).status_code == 404


def test_event_whatsapp_fills_name(env):
    client, auto, sheet, sarvam, veb, mail = env([], event_template="convocation_invite", event_whatsapp_live=True,
                                                 event_name_param="bodyValues")
    p = event_payload()
    p["final_agent_variables"]["lead_name"] = "Riya"
    assert client.post("/webhooks/event/hook", json=p).json()["whatsapp"] == "sent"
    assert veb.extra == {"bodyValues": "Riya"}


def test_event_webhook_accepts_event_token(env):
    client, *_ = env([], event_template="convocation_invite", event_webhook_token="evt")
    assert client.post("/webhooks/event/evt", json=event_payload()).status_code == 200


def test_media_served(env):
    client, *_ = env([])
    assert client.get("/media/convocation.jpg").status_code == 200
    assert client.get("/media/../config.py").status_code == 404


def test_admin_test_whatsapp_reports_veblika_answer(env):
    client, auto, sheet, sarvam, veb, mail = env([], wa_ok=False)
    assert client.get("/admin/test-whatsapp?phone=8909240668").status_code == 401
    # Opening the link only shows a confirm button; nothing is sent on GET
    page = client.get("/admin/test-whatsapp?phone=8909240668", headers=H)
    assert page.status_code == 200 and "Send now" in page.text and veb.sent == []
    assert client.post("/admin/test-whatsapp?phone=8909240668").status_code == 401
    r = client.post("/admin/test-whatsapp?phone=8909240668", headers=H).json()
    assert r == {"phone": "+918909240668", "ok": False, "status_code": 500, "error": "boom"}
    assert veb.sent == ["918909240668"]


@respx.mock
def test_veblika_can_send_through_make_hook(tmp_path):
    from app.integrations import Veblika
    s = live_settings(tmp_path)
    s.veblika_make_hook_url = "https://hook.example/abc"
    route = respx.post("https://hook.example/abc").mock(return_value=httpx.Response(200, json={"status": "success"}))
    res = Veblika(s).send_template("918909240668", template="t1")
    assert res["ok"] and "to=918909240668" in route.calls[0].request.content.decode()
    respx.post("https://hook.example/abc").mock(return_value=httpx.Response(401, json={"message": "bad key"}))
    assert Veblika(s).send_template("918909240668")["error"] == "bad key"

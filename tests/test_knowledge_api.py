"""Local knowledge workflows and Sarvam zero-touch enforcement."""
from app.config import Settings
from app.integrations import Sarvam, SarvamWebAuth
from app.saas.knowledge_provider import KnowledgeProviderDisabled, PreparedRelease, build_knowledge_provider
from tests.test_agents import register, world  # noqa: F401
from tests.test_saas import saas  # noqa: F401


def put(actor, url, body):
    return actor.c.put(url, json=body, headers=actor._h())


def setup_manual(a):
    lib = a.owner.post(f"{a.base}/knowledge/libraries", {"name": "Admissions", "description": "Approved facts"})
    assert lib.status_code == 201, lib.text
    doc = a.owner.post(f"{a.base}/knowledge/manual", {
        "library_id": lib.json()["id"], "title": "MBA fees", "kind": "faq",
        "content": "The approved MBA tuition fee is INR 250000. Applications close on 30 June.",
        "locale": "en-IN",
    })
    assert doc.status_code == 201, doc.text
    return lib.json(), doc.json()


def test_manual_library_permissions_isolation_and_content_audit(world):
    a, b = world.a, world.b
    lib, doc = setup_manual(a)
    assert a.trainer.get(f"{a.base}/knowledge/libraries").status_code == 200
    assert a.trainer.get(f"{a.base}/knowledge/documents/{doc['id']}/content").status_code == 403
    assert a.trainee.get(f"{a.base}/knowledge/libraries").status_code == 403
    assert b.owner.get(f"{b.base}/knowledge/documents?library_id={lib['id']}").json() == []
    assert b.owner.get(f"{b.base}/knowledge/documents/{doc['id']}/content").status_code == 404
    content = a.owner.get(f"{a.base}/knowledge/documents/{doc['id']}/content")
    assert content.status_code == 200 and "250000" in content.json()["content"]


def test_attach_behavior_offline_retrieval_validation_and_snapshot_are_local(world, monkeypatch):
    calls = []
    def forbidden(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("knowledge workflow attempted a Sarvam request")
    monkeypatch.setattr(Sarvam, "start_call", forbidden)
    monkeypatch.setattr(SarvamWebAuth, "signed_url", forbidden)
    a = world.a
    _, doc = setup_manual(a)
    agent = register(a, "knowledge-local-only", name="Knowledge Agent")
    aid, vid = agent["id"], agent["draft_version"]["id"]
    base = f"{a.base}/agents/{aid}/versions/{vid}"
    assert put(a.owner, f"{base}/knowledge-items", {"revision_ids": [doc["revision"]["id"]]}).status_code == 200
    behavior = {"role": "ai_admissions_counsellor", "persona": "Helpful DIDM counsellor",
                "objective": "Answer approved admissions questions", "instructions": "Use approved knowledge only.",
                "languages": ["en-IN", "hi-IN"], "default_language": "en-IN",
                "unknown_answer": "I do not have approved information.",
                "escalation": "Offer an authorized DIDM representative."}
    assert put(a.owner, f"{base}/behavior", behavior).status_code == 200
    found = a.trainer.post(f"{base}/knowledge-search", {"query": "What is the MBA tuition fee?"})
    assert found.status_code == 200 and found.json()["unknown"] is False
    assert "250000" in found.json()["results"][0]["text"]
    unknown = a.trainer.post(f"{base}/knowledge-search", {"query": "What is the hostel swimming pool size?"})
    assert unknown.status_code == 200 and unknown.json()["unknown"] is True
    valid = a.owner.post(f"{base}/knowledge-validate")
    assert valid.status_code == 200 and valid.json()["status"] == "passed"
    snap = a.owner.post(f"{base}/knowledge-snapshot")
    assert snap.status_code == 201 and snap.json()["provider_sync"] == "disabled"
    assert a.owner.post(f"{base}/provider-sync").status_code == 409
    assert calls == []


def test_zero_touch_flag_defaults_off_and_no_live_adapter_can_be_constructed():
    settings = Settings()
    settings.knowledge_sarvam_sync_enabled = False
    provider = build_knowledge_provider(settings)
    try:
        provider.synchronize(PreparedRelease("v", "s", "h"))
        assert False, "disabled adapter unexpectedly synchronized"
    except KnowledgeProviderDisabled:
        pass
    settings.knowledge_sarvam_sync_enabled = True
    try:
        build_knowledge_provider(settings)
        assert False, "enabled flag unexpectedly constructed a live adapter"
    except KnowledgeProviderDisabled:
        pass


def test_file_upload_and_sarvam_sync_capabilities_fail_closed(world):
    a = world.a
    caps = a.owner.get(f"{a.base}/knowledge/capabilities").json()
    assert caps["file_upload"] is False and caps["sarvam_sync"] is False
    assert "zero-touch" in caps["sarvam_sync_reason"].lower()

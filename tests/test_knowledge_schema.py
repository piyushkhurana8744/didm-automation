"""Phase 1 knowledge-domain schema: additive migration, tenant constraints and immutable artifacts."""
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import init_db, utcnow
from app.saas.models import (Agent, AgentVersion, ImmutableKnowledgeArtifact, KnowledgeDocument,
                             KnowledgeDocumentRevision, KnowledgeLibrary, KnowledgeSnapshot,
                             KnowledgeSnapshotItem, Organization, User)
from tests.conftest import fresh_db_url


def seeded(tmp_path):
    url = fresh_db_url(tmp_path)
    engine = init_db(url)
    with Session(engine) as db:
        user = User(email="owner@example.test", status="active")
        a, b = Organization(name="A", slug="knowledge-a"), Organization(name="B", slug="knowledge-b")
        db.add_all([user, a, b])
        db.flush()
        agent = Agent(organization_id=a.id, name="Agent", provider="sarvam", provider_app_id="kb-schema-agent",
                      channels=["phone"], status="active", created_by=user.id)
        db.add(agent)
        db.flush()
        version = AgentVersion(organization_id=a.id, agent_id=agent.id, internal_version=1,
                               provider_app_version=1, configuration_snapshot={}, variable_schema=[], status="draft",
                               behavior_snapshot={}, release_state="draft", created_by=user.id)
        db.add(version)
        db.commit()
        return engine, a.id, b.id, user.id, agent.id, version.id


def test_additive_migration_creates_complete_phase1_domain(tmp_path):
    engine, *_ = seeded(tmp_path)
    tables = set(inspect(engine).get_table_names())
    assert {"knowledge_libraries", "knowledge_documents", "knowledge_document_revisions",
            "knowledge_text_blocks", "knowledge_chunks", "knowledge_embeddings", "knowledge_faq_entries",
            "knowledge_faq_revisions", "knowledge_jobs", "agent_version_knowledge_items",
            "knowledge_snapshots", "knowledge_snapshot_items", "agent_validation_runs", "provider_connections",
            "provider_syncs", "retrieval_credentials", "knowledge_retrieval_events"} <= tables
    columns = {c["name"] for c in inspect(engine).get_columns("agent_versions")}
    assert {"behavior_snapshot", "knowledge_snapshot_id", "provider_sync_id", "validation_report_id",
            "release_state", "content_hash"} <= columns


def test_composite_foreign_keys_reject_cross_tenant_library_and_revision(tmp_path):
    engine, org_a, org_b, user, *_ = seeded(tmp_path)
    with Session(engine) as db:
        lib = KnowledgeLibrary(organization_id=org_a, name="A library", created_by=user)
        db.add(lib)
        db.commit()
        bad = KnowledgeDocument(organization_id=org_b, library_id=lib.id, kind="file", title="cross tenant",
                                created_by=user)
        db.add(bad)
        with pytest.raises(IntegrityError):
            db.commit()


def test_ready_revisions_and_snapshots_are_immutable(tmp_path):
    engine, org, _, user, agent, version = seeded(tmp_path)
    with Session(engine) as db:
        lib = KnowledgeLibrary(organization_id=org, name="Admissions", created_by=user)
        db.add(lib)
        db.flush()
        doc = KnowledgeDocument(organization_id=org, library_id=lib.id, kind="manual", title="Fees",
                                created_by=user)
        db.add(doc)
        db.flush()
        rev = KnowledgeDocumentRevision(organization_id=org, document_id=doc.id, revision_no=1,
                                        source_kind="manual", processing_state="processing",
                                        malware_state="not_applicable", created_by=user)
        db.add(rev)
        db.flush()
        rev.processing_state, rev.ready_at = "ready", utcnow()
        db.commit()
        rev.failure_code = "rewrite"
        with pytest.raises(ImmutableKnowledgeArtifact):
            db.commit()
        db.rollback()

        snap = KnowledgeSnapshot(organization_id=org, agent_id=agent, agent_version_id=version,
                                 manifest={"revisions": [rev.id]}, manifest_hash="a" * 64,
                                 chunker_version="v1", retrieval_policy_version="v1", item_count=1,
                                 chunk_count=0, created_by=user)
        db.add(snap)
        db.flush()
        db.add(KnowledgeSnapshotItem(organization_id=org, snapshot_id=snap.id, revision_id=rev.id,
                                     ordinal=0, content_hash="b" * 64))
        db.commit()
        snap.item_count = 2
        with pytest.raises(ImmutableKnowledgeArtifact):
            db.commit()
        db.rollback()
        assert db.scalar(select(KnowledgeSnapshot.item_count).where(KnowledgeSnapshot.id == snap.id)) == 1

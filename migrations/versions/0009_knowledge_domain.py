"""Tenant-isolated agent knowledge and immutable release domain.

This migration is additive. It does not backfill, rewrite, publish, or otherwise change existing agents,
assignments, sessions, or provider mappings.

Revision ID: 0009_knowledge_domain
Revises: 0008_recording_providers
"""
from alembic import op
import sqlalchemy as sa

revision = "0009_knowledge_domain"
down_revision = "0008_recording_providers"
branch_labels = None
depends_on = None


def _id():
    return sa.Column("id", sa.String(36), primary_key=True)


def _org():
    return sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id"), nullable=False)


def _user(name):
    return sa.Column(name, sa.String(36), sa.ForeignKey("users.id"), nullable=True)


def _times(updated=False):
    cols = [sa.Column("created_at", sa.DateTime(), nullable=False)]
    if updated:
        cols.append(sa.Column("updated_at", sa.DateTime(), nullable=False))
    return cols


def upgrade():
    with op.batch_alter_table("agent_versions") as b:
        b.add_column(sa.Column("behavior_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        b.add_column(sa.Column("knowledge_snapshot_id", sa.String(36), nullable=True))
        b.add_column(sa.Column("provider_sync_id", sa.String(36), nullable=True))
        b.add_column(sa.Column("validation_report_id", sa.String(36), nullable=True))
        # Existing versions predate the knowledge release workflow; label them honestly instead of
        # pretending that they passed its future validation/provider-sync gates.
        b.add_column(sa.Column("release_state", sa.String(30), nullable=False, server_default="legacy"))
        b.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        b.create_check_constraint("ck_agent_versions_release_state",
                                  "release_state IN ('legacy', 'draft', 'validating', 'validation_failed', "
                                  "'ready', 'provider_sync_pending', 'provider_sync_failed', "
                                  "'provider_synced', 'published')")

    op.create_table(
        "knowledge_libraries", _id(), _org(), sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        _user("created_by"), *_times(updated=True), sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "name", name="uq_knowledge_libraries_org_name"),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_libraries_org_id"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_knowledge_libraries_status"))
    op.create_index("ix_knowledge_libraries_org_status", "knowledge_libraries", ["organization_id", "status"])

    op.create_table(
        "knowledge_documents", _id(), _org(), sa.Column("library_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False), sa.Column("title", sa.String(300), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("current_revision_id", sa.String(36)),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("retention_policy", sa.String(40), nullable=False), _user("created_by"), *_times(updated=True),
        sa.Column("archived_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["organization_id", "library_id"],
                                ["knowledge_libraries.organization_id", "knowledge_libraries.id"]),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_documents_org_id"),
        sa.CheckConstraint("kind IN ('file', 'faq', 'manual')", name="ck_knowledge_documents_kind"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_knowledge_documents_status"))
    op.create_index("ix_knowledge_documents_org_library", "knowledge_documents", ["organization_id", "library_id"])

    op.create_table(
        "knowledge_document_revisions", _id(), _org(), sa.Column("document_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False), sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("original_filename", sa.String(300)), sa.Column("declared_mime", sa.String(150)),
        sa.Column("detected_mime", sa.String(150)), sa.Column("size_bytes", sa.Integer()),
        sa.Column("sha256", sa.String(64)), sa.Column("storage_provider", sa.String(30)),
        sa.Column("storage_key", sa.String(500)), sa.Column("source_locale", sa.String(30)),
        sa.Column("effective_from", sa.DateTime()), sa.Column("effective_until", sa.DateTime()),
        sa.Column("processing_state", sa.String(30), nullable=False),
        sa.Column("malware_state", sa.String(20), nullable=False), sa.Column("parser_name", sa.String(80)),
        sa.Column("parser_version", sa.String(40)), sa.Column("ocr_metadata", sa.JSON(), nullable=False),
        sa.Column("extracted_text_hash", sa.String(64)), sa.Column("failure_code", sa.String(60)),
        sa.Column("failure_detail", sa.String(300)), _user("created_by"), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("ready_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["organization_id", "document_id"],
                                ["knowledge_documents.organization_id", "knowledge_documents.id"]),
        sa.UniqueConstraint("document_id", "revision_no", name="uq_knowledge_revisions_number"),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_revisions_org_id"),
        sa.CheckConstraint("processing_state IN ('quarantined', 'uploaded', 'scanning', 'processing', "
                           "'review_required', 'ready', 'failed', 'rejected')",
                           name="ck_knowledge_revisions_processing_state"),
        sa.CheckConstraint("malware_state IN ('pending', 'clean', 'infected', 'error', 'not_applicable')",
                           name="ck_knowledge_revisions_malware_state"))
    op.create_index("ix_knowledge_revisions_org_state", "knowledge_document_revisions",
                    ["organization_id", "processing_state"])

    op.create_table(
        "knowledge_text_blocks", _id(), _org(), sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("block_type", sa.String(30), nullable=False),
        sa.Column("page_number", sa.Integer()), sa.Column("section_path", sa.JSON(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False), sa.Column("text_hash", sa.String(64), nullable=False),
        sa.Column("extraction_confidence", sa.Integer()), sa.Column("source_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "revision_id"],
                                ["knowledge_document_revisions.organization_id", "knowledge_document_revisions.id"]),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_knowledge_blocks_ordinal"))
    op.create_index("ix_knowledge_blocks_org_revision", "knowledge_text_blocks", ["organization_id", "revision_id"])

    op.create_table(
        "knowledge_chunks", _id(), _org(), sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("block_id", sa.String(36), sa.ForeignKey("knowledge_text_blocks.id")),
        sa.Column("ordinal", sa.Integer(), nullable=False), sa.Column("text", sa.Text(), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False), sa.Column("page_number", sa.Integer()),
        sa.Column("section_path", sa.JSON(), nullable=False), sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("chunker_name", sa.String(80), nullable=False),
        sa.Column("chunker_version", sa.String(40), nullable=False),
        sa.Column("search_terms", sa.Text(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "revision_id"],
                                ["knowledge_document_revisions.organization_id", "knowledge_document_revisions.id"]),
        sa.UniqueConstraint("revision_id", "ordinal", name="uq_knowledge_chunks_ordinal"),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_chunks_org_id"))
    op.create_index("ix_knowledge_chunks_org_revision", "knowledge_chunks", ["organization_id", "revision_id"])

    op.create_table(
        "knowledge_embeddings", _id(), _org(), sa.Column("chunk_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False), sa.Column("model", sa.String(120), nullable=False),
        sa.Column("model_version", sa.String(60), nullable=False), sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("vector_data", sa.JSON(), nullable=False), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "chunk_id"],
                                ["knowledge_chunks.organization_id", "knowledge_chunks.id"]),
        sa.UniqueConstraint("chunk_id", "model", "model_version", name="uq_knowledge_embeddings_model"))
    op.create_index("ix_knowledge_embeddings_org_chunk", "knowledge_embeddings", ["organization_id", "chunk_id"])

    op.create_table(
        "knowledge_faq_entries", _id(), _org(), sa.Column("library_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(300), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("current_revision_id", sa.String(36)), _user("created_by"), *_times(updated=True),
        sa.ForeignKeyConstraint(["organization_id", "library_id"],
                                ["knowledge_libraries.organization_id", "knowledge_libraries.id"]),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_faq_entries_org_id"))
    op.create_index("ix_knowledge_faq_entries_org_library", "knowledge_faq_entries", ["organization_id", "library_id"])

    op.create_table(
        "knowledge_faq_revisions", _id(), _org(), sa.Column("faq_entry_id", sa.String(36), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False), sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=False), sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("locale", sa.String(30), nullable=False), sa.Column("effective_from", sa.DateTime()),
        sa.Column("effective_until", sa.DateTime()), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), _user("created_by"), _user("approved_by"),
        sa.Column("created_at", sa.DateTime(), nullable=False), sa.Column("approved_at", sa.DateTime()),
        sa.ForeignKeyConstraint(["organization_id", "faq_entry_id"],
                                ["knowledge_faq_entries.organization_id", "knowledge_faq_entries.id"]),
        sa.UniqueConstraint("faq_entry_id", "revision_no", name="uq_knowledge_faq_revisions_number"),
        sa.CheckConstraint("status IN ('draft', 'approved', 'superseded')",
                           name="ck_knowledge_faq_revisions_status"))
    op.create_index("ix_knowledge_faq_revisions_org_entry", "knowledge_faq_revisions",
                    ["organization_id", "faq_entry_id"])

    op.create_table(
        "knowledge_jobs", _id(), _org(),
        sa.Column("revision_id", sa.String(36), sa.ForeignKey("knowledge_document_revisions.id")),
        sa.Column("job_type", sa.String(40), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False), sa.Column("locked_until", sa.DateTime()),
        sa.Column("locked_by", sa.String(100)), sa.Column("progress", sa.JSON(), nullable=False),
        sa.Column("error_code", sa.String(60)), sa.Column("last_error", sa.String(300)), *_times(updated=True),
        sa.Column("finished_at", sa.DateTime()),
        sa.CheckConstraint("status IN ('queued', 'running', 'retry', 'completed', 'failed', 'cancelled')",
                           name="ck_knowledge_jobs_status"))
    op.create_index("ix_knowledge_jobs_claim", "knowledge_jobs", ["status", "next_attempt_at", "locked_until"])
    op.create_index("ix_knowledge_jobs_org_created", "knowledge_jobs", ["organization_id", "created_at"])

    op.create_table(
        "knowledge_snapshots", _id(), _org(),
        sa.Column("agent_id", sa.String(36), sa.ForeignKey("agents.id"), nullable=False),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False), sa.Column("manifest_hash", sa.String(64), nullable=False),
        sa.Column("chunker_version", sa.String(80), nullable=False), sa.Column("embedding_model", sa.String(160)),
        sa.Column("retrieval_policy_version", sa.String(80), nullable=False),
        sa.Column("item_count", sa.Integer(), nullable=False), sa.Column("chunk_count", sa.Integer(), nullable=False),
        _user("created_by"), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("organization_id", "manifest_hash", name="uq_knowledge_snapshots_manifest"),
        sa.UniqueConstraint("organization_id", "id", name="uq_knowledge_snapshots_org_id"))
    op.create_index("ix_knowledge_snapshots_org_created", "knowledge_snapshots", ["organization_id", "created_at"])

    op.create_table(
        "knowledge_snapshot_items", _id(), _org(), sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False), sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False), sa.Column("extracted_text_hash", sa.String(64)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "snapshot_id"],
                                ["knowledge_snapshots.organization_id", "knowledge_snapshots.id"]),
        sa.ForeignKeyConstraint(["organization_id", "revision_id"],
                                ["knowledge_document_revisions.organization_id", "knowledge_document_revisions.id"]),
        sa.UniqueConstraint("snapshot_id", "revision_id", name="uq_knowledge_snapshot_items_revision"))
    op.create_index("ix_knowledge_snapshot_items_org_snapshot", "knowledge_snapshot_items",
                    ["organization_id", "snapshot_id"])

    op.create_table(
        "agent_version_knowledge_items", _id(), _org(),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False), sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("locale", sa.String(30)), sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False), _user("created_by"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id", "revision_id"],
                                ["knowledge_document_revisions.organization_id", "knowledge_document_revisions.id"]),
        sa.UniqueConstraint("agent_version_id", "revision_id", name="uq_agent_version_knowledge_revision"))
    op.create_index("ix_agent_version_knowledge_org_version", "agent_version_knowledge_items",
                    ["organization_id", "agent_version_id"])

    op.create_table(
        "agent_validation_runs", _id(), _org(),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("validator_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("findings", sa.JSON(), nullable=False),
        sa.Column("golden_total", sa.Integer(), nullable=False), sa.Column("golden_passed", sa.Integer(), nullable=False),
        _user("started_by"), sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime()),
        sa.CheckConstraint("status IN ('queued', 'running', 'passed', 'failed', 'error')",
                           name="ck_agent_validation_runs_status"))
    op.create_index("ix_agent_validation_runs_org_version", "agent_validation_runs",
                    ["organization_id", "agent_version_id"])

    op.create_table(
        "provider_connections", _id(), _org(), sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("organization_reference", sa.String(200)),
        sa.Column("workspace_reference", sa.String(200), nullable=False),
        sa.Column("secret_reference", sa.String(300)), sa.Column("capabilities", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False), sa.Column("verified_at", sa.DateTime()),
        _user("created_by"), *_times(updated=True),
        sa.UniqueConstraint("organization_id", "provider", "workspace_reference",
                            name="uq_provider_connections_workspace"))
    op.create_index("ix_provider_connections_org_provider", "provider_connections", ["organization_id", "provider"])

    op.create_table(
        "provider_syncs", _id(), _org(),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(36), sa.ForeignKey("knowledge_snapshots.id")),
        sa.Column("connection_id", sa.String(36), sa.ForeignKey("provider_connections.id")),
        sa.Column("provider", sa.String(30), nullable=False), sa.Column("mode", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False), sa.Column("provider_app_id", sa.String(200)),
        sa.Column("provider_app_version", sa.Integer()),
        sa.Column("provider_kb_references", sa.JSON(), nullable=False),
        sa.Column("desired_manifest_hash", sa.String(64), nullable=False),
        sa.Column("observed_manifest_hash", sa.String(64)),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False), sa.Column("error_code", sa.String(60)),
        sa.Column("last_error", sa.String(300)), _user("created_by"), *_times(updated=True),
        sa.Column("synced_at", sa.DateTime()),
        sa.UniqueConstraint("organization_id", "idempotency_key", name="uq_provider_syncs_idempotency"),
        sa.CheckConstraint("status IN ('pending', 'running', 'attestation_required', 'synced', 'failed', 'cancelled')",
                           name="ck_provider_syncs_status"))
    op.create_index("ix_provider_syncs_org_version", "provider_syncs", ["organization_id", "agent_version_id"])

    op.create_table(
        "retrieval_credentials", _id(), _org(),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(36), sa.ForeignKey("knowledge_snapshots.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False), sa.Column("status", sa.String(20), nullable=False),
        sa.Column("expires_at", sa.DateTime()), sa.Column("rotated_at", sa.DateTime()),
        sa.Column("revoked_at", sa.DateTime()), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_retrieval_credentials_hash"))
    op.create_index("ix_retrieval_credentials_org_snapshot", "retrieval_credentials",
                    ["organization_id", "knowledge_snapshot_id"])

    op.create_table(
        "knowledge_retrieval_events", _id(), _org(),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("training_sessions.id")),
        sa.Column("agent_version_id", sa.String(36), sa.ForeignKey("agent_versions.id"), nullable=False),
        sa.Column("knowledge_snapshot_id", sa.String(36), sa.ForeignKey("knowledge_snapshots.id"), nullable=False),
        sa.Column("query_hash", sa.String(64), nullable=False),
        sa.Column("selected_chunk_ids", sa.JSON(), nullable=False), sa.Column("latency_ms", sa.Integer()),
        sa.Column("result_count", sa.Integer(), nullable=False), sa.Column("outcome", sa.String(30), nullable=False),
        sa.Column("error_code", sa.String(60)), sa.Column("created_at", sa.DateTime(), nullable=False))
    op.create_index("ix_knowledge_retrieval_events_org_created", "knowledge_retrieval_events",
                    ["organization_id", "created_at"])
    op.create_index("ix_knowledge_retrieval_events_snapshot", "knowledge_retrieval_events",
                    ["knowledge_snapshot_id", "created_at"])


def downgrade():
    # Downgrade removes only the unused knowledge-domain structures. Production rollback must first prove
    # that no release references them; Alembic cannot safely make that product decision automatically.
    for table in ("knowledge_retrieval_events", "retrieval_credentials", "provider_syncs",
                  "provider_connections", "agent_validation_runs", "agent_version_knowledge_items",
                  "knowledge_snapshot_items", "knowledge_snapshots", "knowledge_jobs",
                  "knowledge_faq_revisions", "knowledge_faq_entries", "knowledge_embeddings",
                  "knowledge_chunks", "knowledge_text_blocks", "knowledge_document_revisions",
                  "knowledge_documents", "knowledge_libraries"):
        op.drop_table(table)
    with op.batch_alter_table("agent_versions") as b:
        b.drop_constraint("ck_agent_versions_release_state", type_="check")
        for name in ("content_hash", "release_state", "validation_report_id", "provider_sync_id",
                     "knowledge_snapshot_id", "behavior_snapshot"):
            b.drop_column(name)

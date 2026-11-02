# Knowledge database schema

Status: implemented locally in `migrations/versions/0009_knowledge_domain.py`; not migrated to production.

## Existing table extension

`agent_versions` gains nullable/defaulted release fields: `behavior_snapshot`, `knowledge_snapshot_id`, `provider_sync_id`, `validation_report_id`, `release_state`, and `content_hash`. Historical rows remain valid. Published-version ORM guards now cover these fields.

## Library and ingestion tables

- `knowledge_libraries`: tenant-scoped named library, active/archive lifecycle.
- `knowledge_documents`: logical file/manual/FAQ-derived item and current revision pointer.
- `knowledge_document_revisions`: immutable-ready source metadata, hashes, private storage reference, processing/malware state, parser/OCR provenance and effective dates.
- `knowledge_text_blocks`: page/heading/table-aware immutable extracted blocks.
- `knowledge_chunks`: deterministic chunk text, provenance, hashes and chunker version. `search_terms` is a portable lexical precursor; PostgreSQL `tsvector` is deferred to Phase 4.
- `knowledge_embeddings`: provider/model/dimension metadata and neutral JSON vector. pgvector is deliberately deferred pending approval and staging proof.
- `knowledge_faq_entries` / `knowledge_faq_revisions`: structured, revisioned FAQ knowledge.
- `knowledge_jobs`: leased, retryable durable processing jobs.

## Release and provider tables

- `agent_version_knowledge_items`: exact document revisions selected by an agent draft.
- `knowledge_snapshots` / `knowledge_snapshot_items`: immutable manifest and exact revision hashes.
- `agent_validation_runs`: versioned validation findings and golden-test totals.
- `provider_connections`: organization/workspace references, capabilities and secret references only.
- `provider_syncs`: idempotent desired/observed manifest and provider app/version evidence.
- `retrieval_credentials`: SHA-256 token hashes scoped to one organization/version/snapshot.
- `knowledge_retrieval_events`: bounded query hash, selected chunk IDs, latency and outcome; no full source content.

## Isolation and integrity

All domain rows carry `organization_id`. New parent tables expose unique `(organization_id, id)` keys; dependent library/document/revision/chunk/snapshot relations use composite foreign keys so a valid ID from another organization is still rejected. Global IDs remain UUID strings for SQLite/PostgreSQL parity.

State check constraints, scoped uniqueness, claim indexes and release lookup indexes are included. SQLite foreign-key enforcement is enabled in `app/db.py`, matching PostgreSQL behavior in offline tests.

Ready document revisions, approved/superseded FAQ revisions, extraction artifacts, embeddings and snapshots are ORM-immutable. Published agent versions remain immutable. Future production hardening should add PostgreSQL database triggers if writes outside SQLAlchemy are allowed.

## Migration safety

Upgrade is additive and contains no data rewrite. Downgrade is structurally available but destructive to knowledge-domain data; production downgrade must first prove no release references these tables. No production downgrade should be run automatically.

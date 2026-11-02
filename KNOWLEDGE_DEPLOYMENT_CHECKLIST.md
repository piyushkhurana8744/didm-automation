# Knowledge deployment checklist

Current verdict: **DO NOT DEPLOY MIGRATION 0009 TO PRODUCTION YET.** Phase 1 is locally verified, but later services and operational decisions are unresolved.

## Before staging migration

- Approve schema and retention classification.
- Create a scrubbed Neon staging clone and verified backup/restore point.
- Run `alembic upgrade 0009_knowledge_domain` with lock/timing observation.
- Compare schema against SQLAlchemy metadata and run full PostgreSQL tests.
- Verify downgrade in disposable staging only; never downgrade after knowledge data exists without a reference audit.
- Confirm existing agents, assignments, sessions and published versions are unchanged.

## Before enabling uploads

- Approve/configure private R2 bucket, CORS, lifecycle, encryption and least-privilege credentials.
- Approve a real malware scanner and prove fail-closed outage behavior.
- Approve upload/page/character/OCR quotas and retention/legal-hold policy.
- Deploy isolated workers and shared job monitoring before exposing UI.

## Before retrieval/publish

- Approve embedding/OCR providers and data-processing terms.
- Verify pgvector extension/index/backup behavior or approve alternative.
- Approve grounded-answer/unknown/escalation policy in supported languages.
- Choose Sarvam adapter mode and verify non-production plan capabilities.
- Prove desired/observed provider version matching using synthetic content and no phone calls.
- Require all validation gates and provider sync before current-version pointer advances.

## Production verification

Canary one internal organization, monitor job queues/quarantine/retrieval latency, inspect audit logs for leakage, verify rollback-as-new-release, and only then widen access. Real provider writes require a separately approved runbook.

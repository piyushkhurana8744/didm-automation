# Knowledge security audit

## Implemented and verified locally

- Tenant ID is present on every new domain table.
- Composite tenant foreign keys protect the new library/document/revision/chunk/snapshot graph.
- SQLite now enforces foreign keys in CI instead of masking violations PostgreSQL rejects.
- Ready/approved/extracted/snapshot artifacts are immutable through SQLAlchemy guards.
- Provider connection rows contain only secret references; retrieval credentials contain token hashes only.
- Existing published-version immutability includes all new release fields.
- Existing organization RBAC remains intact; new knowledge source-content access is admin-only.

## Designed but not implemented

- Private R2 upload intents and object isolation.
- Magic-MIME/hash verification, quarantine, malware scanning and parser sandbox.
- OCR/embedding data-residency controls.
- Prompt-injection-resistant extraction and grounded-answer enforcement.
- Retrieval endpoint authentication, replay/rate limiting and telemetry retention.
- Legal hold and physical deletion workflow.
- Two-person publish approval.

## Threat register

Highest risks are cross-tenant ID mixing, malicious files/parser escape, archive/decompression bombs, document prompt injection, signed URL leakage, provider credential theft, SSRF in provider tools, poisoned or mismatched provider sync, retrieval credential replay and mutable provider KB drift.

The system must remain fail-closed until a production malware scanner is healthy. A fake/disabled scanner may exist only in tests and may never produce a production `clean` result.

## Required production controls

Private bucket policy, per-object encryption, no public ACL, narrowly scoped service credentials, malware/parser worker isolation, egress controls, content and OCR limits, safe error codes, audit without content/secrets, rate limits in shared infrastructure, backup/restore proof and incident credential rotation.

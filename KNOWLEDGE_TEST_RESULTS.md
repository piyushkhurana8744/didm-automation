# Knowledge test results

Date: 31 October 2026

## New coverage

`tests/test_knowledge_schema.py` verifies:

- all Phase 1 tables and agent-version fields are created by an additive fresh migration;
- composite tenant foreign keys reject an organization-B document referencing organization-A's library;
- a ready document revision cannot be rewritten;
- a knowledge snapshot cannot be rewritten after insertion.

Existing agent tests verify published-version immutability and historical session version pinning. Hardening tests verify legacy database upgrade behavior.

## Results

Focused schema/agent/hardening run: **44 passed**, one pre-existing Starlette/httpx deprecation warning.

Full backend suite: **233 passed**, with the same single deprecation warning.

Frontend: `npm run typecheck` passed; `npm run build` passed and generated all 34 routes.

No external provider, object store, OCR, embedding or production database was used.

## Not tested

PostgreSQL/Neon migration timing and locking, pgvector, R2, malware scanning, extraction/OCR, retrieval quality, provider sync, paid Sarvam tests and production rollback are not implemented or approved and therefore not claimed as tested.

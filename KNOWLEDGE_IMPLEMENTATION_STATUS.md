# Knowledge implementation status

Date: 31 October 2026

## Summary

Phase 0 (audit/decision validation) and the safe, infrastructure-neutral part of Phase 1 (domain schema) are implemented locally. No production migration has run. Phases 2-9 are not implemented because their production prerequisites require owner decisions or external-service approval.

| Phase | Status | Evidence |
|---|---|---|
| 0 Repository audit and decisions | Implemented and verified | `AGENT_KNOWLEDGE_TRAINING_ARCHITECTURE.md`; blocker register below |
| 1 Knowledge domain/database | Implemented and verified locally | migration `0009_knowledge_domain`; models; schema/isolation/immutability tests |
| 2 Secure storage | Partially implemented; upload blocked | local manual/FAQ revisions work; file upload fails closed pending R2/scanner |
| 3 Extraction/OCR | Partially implemented | deterministic manual/FAQ extraction; PDF/DOCX/OCR blocked pending dependencies/sandbox |
| 4 Search/retrieval | Implemented locally, not integration-tested | deterministic lexical chunks/search and unknown handling; vector path blocked |
| 5 Admin frontend | Implemented locally | functional Knowledge Library page; upload/sync clearly unavailable |
| 6 Structured behavior/preview | Implemented locally | explicit roles, behavior, attachments, retrieval preview, validation and snapshot |
| 7 Sarvam adapter | Disabled by critical override | provider-neutral disabled adapter; zero live calls |
| 8 Release workflow | Partially implemented | immutable local snapshot preparation only; activation/provider sync prohibited |
| 9 Production verification | Not implemented | prior phases and staging environment required |

## Implemented changes

- Added 17 tenant-owned knowledge/release tables and six backward-compatible `agent_versions` fields.
- Added composite tenant foreign keys among new library/document/revision/chunk/snapshot relationships.
- Added durable job, provider connection/sync, hashed retrieval credential and redacted retrieval event records.
- Added ORM immutability guards for ready revisions, approved FAQ revisions, extracted artifacts and snapshots.
- Extended published-agent immutability to the new release fields.
- Added knowledge/content/preview/provider-test/publish permissions without weakening existing roles.
- Enabled SQLite foreign keys so offline tests detect failures PostgreSQL would reject.
- Added migration, cross-tenant and immutable-artifact tests.
- Added local library/manual/FAQ APIs, content audit, draft attachment, structured behavior, lexical retrieval,
  validation and snapshot preparation.
- Added a functional `/knowledge` frontend route and explicit unavailable states for uploads/provider sync.
- Added a zero-touch provider boundary that cannot construct a live adapter.

No routes or buttons were added because storage, scanning and processing do not yet have approved production implementations.

## Phase 0 decisions

| Decision | Recommended default | Approval state |
|---|---|---|
| Document storage | private Cloudflare R2, separate bucket/prefix from recordings | Required |
| Malware scanning | fail-closed scanner service or isolated ClamAV worker | Required |
| Worker topology | separate durable worker; database leases initially, shared queue before horizontal scale | Required |
| OCR | disabled by default; page-level OCR through approved local/provider adapter | Required |
| Embeddings | approved provider/model with residency and budget, deterministic fake in CI | Required |
| Vector index | Neon pgvector after staging extension/index/backup proof | Required |
| Sarvam mode | manual attestation first; native KB/MCP or runtime tool only after plan verification | Required |
| Retention | organization policy plus legal hold and published-snapshot references | Required |
| Publishing approval | admin publish; optional two-person approval for production tenants | Required |
| Provider cost controls | platform caps plus explicit paid-test approval | Required |

## Preservation statement

Migration `0009` is additive. It does not update, delete, publish or backfill existing agents, assignments, sessions, versions or audit rows. It has not been executed against Neon.

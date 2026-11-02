# Knowledge remaining blockers

Implementation correctly stops after Phase 1 because these decisions materially change security, cost or architecture:

1. Cloudflare R2 account/bucket/region, retention lifecycle, encryption and credential approval.
2. Production malware scanner choice and isolated execution topology.
3. Durable worker deployment/lease ownership and horizontal-scaling plan.
4. OCR engine/provider, data residency, cost ceiling and low-confidence review policy.
5. Embedding provider/model/dimensions, residency, budget and rotation policy.
6. Approval to enable/test pgvector in Neon staging, including index and backup/restore design.
7. Sarvam synchronization mode and non-production workspace capability verification.
8. Document classification, retention, legal hold, deletion and trainer content-access policy.
9. Whether production publishing requires two-person approval.
10. Paid provider test/eval budgets and who may authorize them.
11. Final structured behavior schema/copy for AI Student/Customer versus AI Admissions Counsellor.
12. Approval for a staging migration rehearsal. Production Neon remains explicitly out of scope.

Until these are resolved, enabling file upload, marking uploaded files clean, producing embeddings, synchronizing Sarvam or activating knowledge-backed releases would be unsafe or misleading. Manual/FAQ knowledge, local lexical retrieval, offline validation and local snapshot preparation are available.

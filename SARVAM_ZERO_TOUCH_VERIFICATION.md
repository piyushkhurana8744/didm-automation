# Sarvam zero-touch verification

Date: 31 October 2026

## Verdict

The new DIDM Knowledge System is locally isolated from Sarvam. No live Sarvam API, SDK or MCP request was executed during implementation or testing. No live Sarvam state was read or verified, as required.

No Sarvam agent, knowledge base, file, prompt, tool, variable, voice, language, workspace setting, committed version, deployment, credential, provider App ID or mapping was created, changed, deleted, committed, attached, synchronized or rotated.

Existing Sarvam-backed training code remains enabled according to its pre-existing platform and organization switches. It was not globally disabled or replaced. The zero-touch boundary applies only to the new Knowledge System.

## Technical protection

- `KNOWLEDGE_SARVAM_SYNC_ENABLED=false` is documented in `.env.example` and defaults to false in `app/config.py`.
- `app/saas/knowledge_provider.py` contains no HTTP, Sarvam SDK or MCP import.
- `build_knowledge_provider()` returns only `DisabledKnowledgeProvider` while the flag is false.
- If the flag is set true, construction still raises `KnowledgeProviderDisabled`; no live adapter ships in this phase.
- The knowledge provider-sync API always returns HTTP 409 and imports/calls no Sarvam client.
- Knowledge capability responses label synchronization unavailable with zero-touch protection active.
- No scheduler/background job references knowledge provider synchronization.
- Migrations contain no network/startup/provider operation.
- Tests use no real Sarvam credential.

## Files changed that touch the provider boundary

- `app/config.py`: new default-off knowledge-only flag; existing training settings unchanged.
- `.env.example`: documents the false default.
- `app/saas/knowledge_provider.py`: provider-neutral disabled adapter only.
- `app/saas/knowledge_api.py`: local preparation plus fail-closed `/provider-sync`; no provider import.
- `app/saas/api.py`: mounts the local knowledge router; existing agent/training routers remain.
- `tests/test_knowledge_api.py`: makes legacy Sarvam call methods raise during a complete knowledge workflow and proves zero calls.
- `KNOWLEDGE_SARVAM_INTEGRATION.md`: design/status documentation only.

No existing provider implementation in `app/integrations.py`, `app/saas/providers.py`, `app/saas/training.py` or `app/saas/training_api.py` was changed for this override.

## Regression evidence

- New knowledge API/schema suite: 7 tests passed before the final full run.
- Frontend typecheck and production build passed; `/knowledge` is generated as route 35.
- The final full-suite result is recorded in `KNOWLEDGE_TEST_RESULTS.md` after completion.
- Existing agent and training regression suites are included in the full run; no tests were weakened.

The zero-request test covers library/manual content creation, agent-draft attachment, structured behavior, offline retrieval, offline validation, immutable local snapshot preparation and a rejected provider-sync request while both legacy `Sarvam.start_call` and `SarvamWebAuth.signed_url` are patched to fail immediately. Neither is invoked.

## Local features and deliberate limits

Implemented locally: libraries, manual/FAQ knowledge, immutable ready revisions, deterministic chunks, content access auditing, draft attachments, explicit agent roles, offline lexical retrieval, unknown handling, validation, local manifest snapshots and a functional Knowledge Library UI.

File upload remains locked because no approved private R2 configuration and production malware scanner exist. PDF/DOCX parsing remains blocked because PyMuPDF/python-docx and a parser sandbox are not approved/installed. Vector retrieval remains blocked pending pgvector and embedding-provider approval. These are not replaced by unsafe mocks in production.

## Future steps requiring separate explicit approval

1. Select and approve a non-production Sarvam workspace and provider mode.
2. Re-verify official provider capabilities without touching production.
3. Implement a live adapter in a separate reviewed change; the current flag alone cannot enable one.
4. Add secret-manager references and plan/cost/rate controls.
5. Run mock contract tests, then request explicit approval for any staging read/write, KB upload, commit or test.
6. Only after observed provider version/manifest verification may knowledge-backed release activation be designed.

Existing Sarvam production state was intentionally not inspected, so this report does not claim live-state verification.

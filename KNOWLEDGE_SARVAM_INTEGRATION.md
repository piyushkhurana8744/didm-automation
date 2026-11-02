# Knowledge Sarvam integration

Status: verified design; no provider integration implemented or invoked.

## Officially verified

Sarvam Voice Agents documents native KBs supporting PDF, DOC/DOCX, CSV/TSV, TXT and Markdown; asynchronous ingestion; an attached KB Query tool; embedded query search, reranking and source-tagged chunks. KB edits apply everywhere the KB is used, making a shared mutable KB unsuitable as DIDM's immutable release record.

Sarvam documents draft, committed and deployed agent states, version pinning and rollback. Its API Tool can call an external HTTP service during a conversation. Its official OAuth MCP server exposes agent configuration, KB creation/upload/search, evals and commits, but is fixed to one workspace and documents a 24-hour token without refresh.

The public REST introduction lists deployment, campaign/cohort, instant outbound, analytics/boards, tests and BYOK. It does not publish general agent-authoring/KB REST endpoints. DIDM must not use private browser APIs.

Sources:

- https://docs.sarvam.ai/voice-agents/build/knowledge-base
- https://docs.sarvam.ai/voice-agents/build/tools/core-tools
- https://docs.sarvam.ai/voice-agents/build/tools/https-tool
- https://docs.sarvam.ai/voice-agents/build/agent/versioning
- https://docs.sarvam.ai/voice-agents/mcp
- https://docs.sarvam.ai/voice-agents/api/introduction

## Adapter modes

1. Manual synchronization/attestation: initial safe bridge compatible with current manually registered app IDs/versions.
2. Native release-specific Sarvam KB: only through an official approved interface; never edit a KB referenced by a published DIDM release.
3. DIDM runtime retrieval through an API Tool: release-scoped hashed credential, server-derived tenant/snapshot, strict latency/response limits.
4. MCP-assisted operation: operator-assisted unless Sarvam provides a suitable unattended OAuth/service-account contract.

All modes store provider IDs separately from DIDM IDs. Provider sync must record desired and observed manifest hashes and verify the committed provider app version before local publish. No silent fallback to ungrounded behavior is allowed.

## Blockers

Owner must choose a mode and provide a non-production workspace/plan capability inventory. Any real KB upload, commit, eval or test requires separate explicit approval and cost disclosure.

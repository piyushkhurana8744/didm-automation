# Knowledge API contracts

Status: design only; no endpoints are implemented. This avoids exposing upload or processing controls backed by fake production services.

All management routes will live under `/api/v1/organizations/{org_id}` and use `org_access`. IDs never establish authorization.

## Planned management contracts

- `GET/POST /knowledge/libraries`
- `GET/PATCH/POST .../archive /knowledge/libraries/{id}`
- `GET/POST /knowledge/documents`
- `GET /knowledge/documents/{id}` and `/revisions`
- `POST /knowledge/uploads/intents`: validates permission/quota/name/declared MIME and returns a single-object short-lived upload intent.
- `POST /knowledge/uploads/{revision_id}/finalize`: verifies ownership, expiry, object head, size, magic MIME and SHA-256; queues scan only.
- `GET /knowledge/jobs/{id}` and explicit retry for retryable failures.
- `GET /knowledge/documents/{id}/content`: requires `knowledge.content.view`, audits access, never exposes storage keys.
- FAQ/manual CRUD creates revisions rather than overwriting approved content.
- `POST /knowledge/search/preview`: organization and selected draft/snapshot scope are server-resolved.

## Planned agent contracts

- `GET/PUT /agents/{agent_id}/versions/{version_id}/knowledge-items`
- `GET/PUT .../behavior`
- `POST .../validate`, `/offline-preview`, `/provider-sync`, `/publish`
- `POST /agents/{agent_id}/versions/{published_id}/rollback`: creates a new draft/release; never mutates the selected version.

## Provider retrieval contract

A separate rate-limited endpoint will authenticate a random release credential by hash. Organization, agent version and snapshot are derived exclusively from that credential. Request bodies cannot select a tenant/snapshot. Responses contain bounded evidence records (citation label, title, page/section, excerpt, confidence), never private object URLs or keys.

## Error and idempotency rules

- `404` for missing or out-of-scope resources without tenant disclosure.
- `409` for state conflicts/duplicate active operations.
- `422` for safe validation findings.
- `429` with `Retry-After` for quotas/rate limits.
- Idempotency keys required for upload finalize, job retry, provider sync and publish.
- Unprocessed, quarantined, infected, provider-mismatched or unsynchronized knowledge fails closed.

# Phase 6 production audit

Audit date: 2026-10-25 (Asia/Kolkata)

## 1. Executive summary

Phase 6 adds provider-neutral recording storage, an authenticated Cloudinary adapter, additive migration
`0008_recording_providers`, provider-pinned recording metadata, organization provider selection, private
five-minute playback, provider-aware retention/deletion, and mocked Cloudinary tests. Existing S3/R2
storage remains supported. Historical rows with `storage_key` and no `storage_provider` resolve to S3.

One high-severity defect was fixed: `RETENTION_ENFORCEMENT_ENABLED=false` previously still deleted expired
recordings. Report mode is now non-destructive for every category.

Browser voice remains deliberately disabled. Sarvam's current official Web SDK documentation tells the
browser to supply identity, application and agent variables. Its documented backend proxy protects the API
key but does not document a server-bound grant that prevents the browser changing those values. The backend
therefore does not construct a browser provider even if the feature flag is accidentally enabled.

This is not a production approval. No paid Cloudinary/Sarvam call, live PostgreSQL test, Docker build, browser
click-through, deployment or production migration was performed.

## 2. Git branch and commit

The supplied workspace has no `.git` directory. Branch, commit, diff base and clean-tree status are **NOT
TESTED / unavailable**. Create a commit in the source repository before review or deployment.

## 3. Full feature inventory

Evidence labels distinguish implementation from mocked and live verification.

| Capability | State | Evidence |
|---|---|---|
| Legacy Sheets dialler, Sarvam outbound, WhatsApp, reports | TESTED WITH MOCKS | `tests/test_automation.py`; no live provider call |
| Durable webhook ingestion/retry/dead-letter | TESTED WITH MOCKS | `app/webhooks.py`; automation/hardening tests |
| Login, logout, idle/absolute expiry, revocation | TESTED WITH MOCKS | `app/saas/auth.py`, `tests/test_saas.py` |
| CSRF, invitation and password-reset tokens | TESTED WITH MOCKS | hashed server records; fragment links; auth tests |
| Organizations and RBAC | TESTED WITH MOCKS | tenant/permission regression tests |
| Agents, immutable versions, scenarios, teams, assignments | TESTED WITH MOCKS | `tests/test_agents.py` |
| Phone training state machine and quotas | TESTED WITH MOCKS | `tests/test_training.py`; no paid call |
| Browser training | BLOCKED | security-disabled; provider contract insufficient |
| Transcripts and reconciliation | TESTED WITH MOCKS | intelligence/production tests |
| AI rubric evaluation and budgets | TESTED WITH MOCKS | fake evaluator only; live Sarvam not verified |
| S3/R2 recording storage | TESTED WITH MOCKS | SigV4 HTTP fake and end-to-end test |
| Cloudinary recording storage | TESTED WITH MOCKS | `tests/test_cloudinary_storage.py`; no asset uploaded |
| Retention and legal hold | TESTED WITH MOCKS | cross-provider service, retry and hold tests |
| Analytics and CSV export | TESTED WITH MOCKS | SQL and CSV-injection tests |
| Readiness and migration integrity | TESTED WITH MOCKS | fresh migration/model comparison at 0008 |
| Next.js UI | IMPLEMENTED | typecheck and static production build pass |
| Browser click-through / responsive visual check | NOT TESTED | no Playwright/Cypress suite or interactive browser run |
| Docker image | BLOCKED | Docker daemon unavailable |
| PostgreSQL integration/concurrency | NOT TESTED in this run | `TEST_POSTGRES_URL` not provided; SQLite suite passed |
| CI/CD | NOT IMPLEMENTED | no `.github` workflow or equivalent CI configuration found |
| Live integrations | NOT TESTED | credentials and paid calls intentionally not used |

## 4. Architecture assessment

The code keeps the legacy automation and SaaS routes logically separated while sharing one FastAPI process.
Tenant-owned SaaS rows carry `organization_id`, tenant routes use `org_access`/`scoped_get`, and recording
playback re-authorizes the session owner or `recordings.view` permission before issuing access.

Recording flow after Phase 6:

`completed session -> idempotent recording job -> trusted Sarvam HTTPS download -> MIME, size and signature
validation -> selected allowed provider -> provider metadata persisted -> server-authorized expiring playback ->
report-only or enforced retention deletion through the pinned provider`.

The largest operational constraint is the single-process topology. APScheduler, legacy dialler locking and
rate limiting are process-local. Evaluation/webhook jobs have database claims, but horizontally scaling the
web service would still duplicate scheduler work and weaken rate limits. Keep one instance until jobs and
rate limiting move to shared infrastructure with leader election.

## 5. Critical defects

No known unmitigated critical code defect was found by the automated suite.

Fixed in this phase:

- **High — destructive report mode:** expired recordings were deleted even with retention enforcement off.
  All categories now remain untouched until explicit enforcement.
- **High — unsafe browser flag:** the environment flag could instantiate an undocumented browser provider.
  Browser provider construction is now hard-disabled and readiness treats the flag as an error.

## 6. High-priority defects and risks

- Process-local rate limits are bypassable across instances and reset on restart.
- APScheduler runs inside the web process without distributed leader election. The Docker/Render design must
  remain one instance and one worker.
- Webhook authentication uses secret URLs and a per-session HMAC but no documented Sarvam request signature.
  Provider event authenticity therefore depends on secret possession and session metadata verification.
- Platform storage credentials are deployment environment secrets, not editable in the UI. This is safer than
  persisting tenant credentials, but a future secrets-manager-backed platform-admin workflow is incomplete.
- No automated browser E2E/accessibility/responsive suite exists.
- No CI gate runs tests, typecheck, build, dependency scanning or image scanning.
- Backups, point-in-time recovery and restore drills are deployment-provider responsibilities and were not
  evidenced in this workspace.

## 7. Cloudinary implementation

- Official Python SDK dependency: `cloudinary>=1.44,<2`.
- Audio uses `resource_type=video`, as required by Cloudinary's upload API.
- Assets use `type=authenticated`; neither original nor derived assets are anonymously available.
- Playback uses `private_download_url(..., expires_at=now+300)`. Ordinary signed delivery URLs were rejected
  because a signature alone does not enforce expiry.
- Public IDs are deterministic (`folder/training/org/session/hash`) and `overwrite=false`; a 409 retry retrieves
  existing metadata, covering a worker restart between provider upload and database commit.
- Upload responses are privacy-checked before a row becomes `stored`.
- Deletion uses the pinned resource/delivery type with cache invalidation and treats `not found` idempotently.
- Metadata lookup supports reconciliation; auth/non-retryable errors are distinguished from transient errors.
- API secret and signed playback URL are never logged. No Cloudinary value is exposed through `NEXT_PUBLIC_*`.

Official evidence: [audio upload and authenticated delivery](https://cloudinary.com/documentation/image_upload_api_reference),
[time-limited private downloads and access control](https://cloudinary.com/documentation/control_access_to_media),
and [Admin API rate limits](https://cloudinary.com/documentation/asset_management). Account upload, storage,
bandwidth, transformation, rate and billing limits are plan-dependent and **NOT LIVE VERIFIED**.

## 8. Storage provider comparison

| Property | S3 / R2 compatible | Cloudinary |
|---|---|---|
| Privacy | private bucket + SigV4 | authenticated asset |
| Playback | five-minute presigned GET | five-minute private download URL |
| Integrity | SHA-256 + Content-MD5 | HTTPS SDK upload + returned metadata |
| Encryption | requested SSE / provider default | provider-managed at rest |
| Identifier | object key | public/asset ID (stored separately) |
| Deletion | object DELETE | authenticated destroy + invalidate |
| Health/metadata | HEAD | Admin API resource lookup |
| Live verification | NOT TESTED | NOT TESTED |

`RECORDING_ALLOWED_PROVIDERS` restricts organization choices to platform-configured adapters. Organizations
cannot supply credentials. Changing the default does not move or reinterpret prior recordings.

## 9. Recording security review

Playback authorization is server-side and tenant scoped. Stored provider URLs are never returned directly;
only a fresh expiring URL is created after authorization and rate limiting. Downloads accept HTTPS provider
hosts only, reject IP/local/credentialed URLs, cap bytes at 50 MiB, allow known audio MIME types, and verify
basic container signatures. Upload failure never marks a recording ready. Delete failures retain `stored`
state, increment attempts, record an audit summary and remain retryable. Legal holds prevent every deletion.

Production operators must additionally verify private S3 bucket policy, Cloudinary authenticated delivery,
clock synchronization, Cloudinary plan limits and deletion permissions using a non-production asset.

## 10. Browser voice feasibility — NO-GO

The current [official Sarvam Web SDK documentation](https://docs.sarvam.ai/voice-agents/deploy/sdks/web)
documents browser-supplied `org_id`, `workspace_id`, `app_id`, `user_identifier`, `version` and optional
`agent_variables`. It says `start()` fetches a single-use signed WebSocket URL and documents `stop()` cleanup,
microphone HTTPS requirements and a backend `baseUrl` proxy so the API key remains server-side. It does **not**
document that the proxy can bind the signed grant to server-selected identity, app/version and variables, nor
does it state grant lifetime, concurrency enforcement, billing semantics or signed terminal event verification.

Questions requiring written Sarvam answers and a sandbox test:

1. Can a server create a one-time browser grant cryptographically bound to app/version, immutable variables,
   trusted user ID, maximum duration and callback metadata?
2. What are pre-connect and connected expiration times, replay rules and revocation/termination APIs?
3. Can the SDK avoid logging URLs/tokens, and which versions have been security reviewed?
4. Which provider event proves start/end/duration, and how is its signature verified?
5. How are browser sessions counted and billed, and what account concurrency/rate limits apply?
6. Can the server forcibly terminate a live session and receive an authoritative terminal event?

Future supported design: authenticated app requests a backend session; backend checks assignment/quota and
reserves capacity; backend requests a provider grant bound to immutable claims; browser receives only that
one-time short-lived grant; provider-signed events drive the existing state machine; server timeout/termination
releases capacity. Until this contract exists, phone training is the supported channel.

## 11. Authentication review

PASS with mocked regression evidence: scrypt hashes, generic login/reset responses, absolute and idle expiry,
HttpOnly SameSite session cookie, CSRF token bound to the server session, logout/session revocation, reset-time
revocation, hashed invitation/reset tokens and fragment-based secret links. Rate limiting exists but is in-memory
and therefore PARTIAL for multi-instance production. Cookie security depends on `COOKIE_SECURE=true`.

## 12. Tenant isolation review

PASS in mocked cross-tenant tests for organizations, memberships, teams, agents, assignments, sessions,
transcripts, evaluations and recordings. Recording lookups include both session ownership/permission and
organization ID. Provider asset paths include organization/session IDs, but authorization never trusts the path.
Bulk operations reviewed in this repository are organization filtered. A database-level RLS layer is not used.

## 13. Background worker review

Webhook and evaluation jobs use durable rows, conditional claims, retries and dead states. Session capacity uses
PostgreSQL advisory transaction locks. Recording uploads are deterministic and deletions retry. Recovery after a
restart is supported for queued rows. The scheduler itself has no shared job store/leader election, so multi-
instance operation is FAIL. Retention enforcement remains off by default.

## 14. Database review

Migration 0008 is additive. Fresh SQLite upgrade reaches one head and Alembic/model comparison is clean.
Indexes cover tenant IDs and recording provider/asset reconciliation. Unique session recording and storage key
constraints support idempotency. PostgreSQL pool behavior uses `pool_pre_ping`; migration startup is advisory-
locked. Live PostgreSQL migrations, rollback timing, lock duration and concurrent load are NOT TESTED in this run.

Rollback: deploy the prior application without downgrading first; new nullable columns are backwards compatible.
Only after backup and verification should `alembic downgrade 0007_production` remove Phase 6 metadata. Never
downgrade while Phase 6 writes are active.

## 15. Frontend audit

All 34 static routes compile. The recording settings UI lists only platform-allowed Cloudinary/S3-compatible
providers and explains that existing recordings remain pinned. Disabled browser behavior remains represented by
backend availability. API route/type consistency passed TypeScript compilation. Button behavior, mobile layout,
microphone UX and error visuals were source-reviewed but not browser-click verified.

## 16. Test results

| Check | Result |
|---|---|
| Python suite | PASS — 215 tests after Phase 6 changes (mocked providers) |
| Cloudinary adapter | PASS — upload/privacy/expiry/metadata/delete/error/unsafe-ID mocks |
| Migration consistency | PASS — one head, 0008; fresh schema equals models |
| Security/tenant regressions | PASS in Python suite |
| Concurrency | PASS for existing mocked/threaded cases; live PostgreSQL NOT TESTED |
| Frontend typecheck | PASS |
| Frontend production build | PASS — 34 static routes |
| API smoke tests | PASS in TestClient suite |
| Docker build | BLOCKED — Docker daemon not running |
| Browser E2E | NOT TESTED — no framework present |
| Live Sarvam/Cloudinary | NOT TESTED — intentionally no paid calls |

The only warning is Starlette's TestClient/httpx deprecation notice; track it before the next dependency upgrade.

## 17. Environment variables

New/changed:

- `RECORDING_STORE`: `s3`, `cloudinary`, or empty/disabled.
- `RECORDING_ALLOWED_PROVIDERS`: comma-separated `s3,cloudinary`; defaults to `RECORDING_STORE`.
- `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET`.
- `CLOUDINARY_FOLDER` (default `didm-recordings`).

Existing S3/R2 variables remain unchanged. `RECORDING_SOURCE_ENABLED` and Sarvam Analytics configuration are
still required to retrieve provider audio. `RETENTION_ENFORCEMENT_ENABLED` defaults false. Secrets belong in the
deployment secret store, must not use `NEXT_PUBLIC_*`, and must be rotated if exposed.

## 18. Deployment readiness

PARTIAL. Code/tests/typecheck/build are green, but the release requires: source-control review/commit; Docker
build and vulnerability scan; staging PostgreSQL upgrade/rollback rehearsal; backup and restore proof; staging
Cloudinary authenticated upload/playback-expiry/delete test; S3 regression against the chosen provider; Render
secret configuration; one-worker/one-instance confirmation; and explicit retention-enforcement approval.

## 19. Live integration blockers

- No Cloudinary test product environment/credentials or approval for a real asset.
- No Sarvam paid-call approval; browser provider security contract remains insufficient.
- No `TEST_POSTGRES_URL` for PostgreSQL integration tests.
- Docker daemon unavailable.
- No browser automation framework.
- Provider concurrency, pricing and account quotas were not available from account-specific consoles.

## 20. Recommended next steps

1. Review and commit this patch in the real Git repository.
2. Run the full suite against disposable PostgreSQL and build/scan the Docker image in CI.
3. With explicit approval, test one non-sensitive audio fixture in a non-production Cloudinary environment,
   including anonymous rejection, expiry, metadata and deletion.
4. Keep retention report-only until an owner reviews due counts and approves enforcement.
5. Obtain written Sarvam answers above; do not enable browser training before a bound-grant sandbox test.
6. Move scheduler/queues/rate limits to shared infrastructure before adding a second web instance.
7. Add Playwright coverage for login, admin setup, phone training, scorecard playback and permission failures.

## Acceptance matrix

| Area | Result | Concrete evidence |
|---|---|---|
| Phone training | PARTIAL | Full fake-provider E2E passes; no paid live call |
| Browser training | FAIL | Deliberately security-disabled; provider grant contract blocked |
| Cloudinary recordings | PARTIAL | Adapter and security mocks pass; live asset not tested |
| S3 recordings | PARTIAL | SigV4/fake HTTP E2E passes; selected live store not tested |
| AI evaluation | PARTIAL | Deterministic/metered mocked tests pass; live evaluator not tested |
| Transcripts | PARTIAL | Webhook/analytics mocks pass; live provider payload not tested here |
| Analytics | PASS | SQL/CSV automated tests pass for repository scope |
| Production deployment | FAIL | Docker/PostgreSQL/staging/live checks and backup proof outstanding |

# Trainee agent visibility root-cause report

Date: 31 October 2026 (Asia/Kolkata)

## Outcome

`antther-test` is not currently eligible for trainee visibility. Its agent row is active and its direct assignment to `demotrainee@didm.in` is active, but the agent has no published version. The only version is draft version 1 (provider app version 7). The trainee read path correctly fails closed on that condition.

The defect was in the Organization Admin write experience: it offered active-but-unpublished agents and `POST /assignments` accepted them. That produced an assignment labelled active even though the trainee API is required to hide it. The fix prevents new misleading assignments in both the frontend picker and backend API. It does not alter the existing assignment, publish the agent, weaken permissions, or touch Neon data.

Production will continue to hide `antther-test` until an administrator validates and publishes its draft through the normal publish workflow. This is intentional and is the remaining operational blocker, not a caching or deduplication issue.

## End-to-end flow

### Organization Admin creation

1. `frontend/src/app/(app)/assignments/new/page.tsx:27-29` loads active agents, members, and teams.
2. The form converts local start/end values to ISO timestamps and posts `agent_ids`, `user_ids`/`team_ids`, the window, and settings to `POST /api/v1/organizations/{organization_id}/assignments`.
3. `app/saas/agents.py:1090-1170` deduplicates submitted IDs, scopes every agent/person/team to the authenticated organization, checks role delegation, validates the time window and scenario settings, then inserts one `agent_assignments` row for each agent/target pair.
4. `AgentAssignment` stores the organization ID, agent ID, user ID or team ID, assignment window, revocation fields, settings, and actor. Assignments point to an agent, not directly to a version. At training time the current immutable published version is resolved from `Agent.published_version_id`.

### Trainee read

The exact endpoint is:

`GET /api/v1/organizations/{organization_id}/my/agents`

The dashboard calls it at `frontend/src/app/(app)/my-training/page.tsx:15-18`. It maps every returned object directly at lines 39-59; it performs no client-side eligibility filtering or deduplication.

The endpoint is defined at `app/saas/agents.py:1223-1225` and uses `entitlements()` (`app/saas/agents.py:348-374`). Eligibility requires:

- an authenticated user with active membership and `training.self` permission in the path organization;
- a direct assignment to that user, or an assignment to one of the user's active teams;
- the same assignment organization ID as the authenticated organization;
- no revocation, `starts_at <= now`, and no expiry or `expires_at > now`;
- an active agent in that organization;
- a non-null `Agent.published_version_id` that resolves to a `published` version in the same organization.

Results are grouped by `agent_id`, so overlapping direct/team assignments for one agent combine into one entitlement. Different agent IDs remain separate. A direct assignment takes precedence over team assignments; otherwise team limits/scenarios are combined (`app/saas/agents.py:319-345`). `max_sessions` is returned as access metadata and enforced when a session starts; it is not a visibility predicate.

By contrast, the admin list at `GET /assignments` (`app/saas/agents.py:1049-1076`) reports assignment lifecycle state only. Before this fix, creation checked `Agent.status == active` but did not check the published-version invariant. Thus “assignment active” and “agent eligible for trainee use” were incorrectly presented as equivalent.

## Read-only Neon evidence

No Neon rows were changed. No Sarvam endpoint was called. Values below came from read-only ORM selects against the configured Neon database.

Identity and tenant:

- user ID: `428d4ec0-8336-40f6-acb5-6daa86744540`; user status `active`;
- membership ID: `1e78145d-d0b7-43d6-bbd0-bb33b9c3c2b4`; role `trainee`; membership status `active`;
- organization ID: `439799da-8a8e-4ff9-a490-7ffcfcd65564`; organization `DIDM`; status `active`.

Direct assignments:

| Agent | Assignment | Window (UTC) | Limit | Agent/version result |
|---|---|---|---:|---|
| Ananya - Admissions Counsellor | `de879ca8-9ddb-44e1-87f4-54ed6e0f7174` | 31 Oct 10:55 to 2 Nov 10:55 | 1 session | active; published pointer resolves to a same-tenant published version |
| DIDM_TESt | `253c7089-ab73-4604-b5b5-c01179df2c5f` | 31 Oct 12:19 to 7 Nov 12:19 | 10 sessions | active; published pointer resolves to a same-tenant published version |
| antther-test | `1a09a9b0-39a2-4649-b1cc-495802a1d6b4` | 31 Oct 12:31 to 7 Nov 12:31 | 10 sessions | active; **published pointer is null** |

`antther-test` agent ID is `3078f806-6962-44bd-9e1c-e09e69d0f41c`. Its only version is `3e352f73-37c0-43a7-a04c-0cf25a0cf1fc`, internal version 1, provider version 7, status `draft`, `published_at = NULL`, in the correct organization. Therefore the user ID, organization ID, membership, assignment target, status, dates, and limit all pass; publication alone fails.

The frontend HTTP client explicitly uses `cache: 'no-store'` (`frontend/src/lib/api.ts`), and `useLoad` stores the complete returned array without entity deduplication. Caching and frontend filtering are not causes.

## Code changes

### Backend invariant

`app/saas/agents.py:1107-1117` now makes assignment creation enforce the same version invariant as trainee entitlement resolution. Every selected agent must have a current version that exists, is `published`, belongs to the same organization, and belongs to that agent. Otherwise the entire bulk request fails with HTTP 409. Existing tenant and role checks remain unchanged and no publication rule is bypassed.

### Frontend prevention

`frontend/src/app/(app)/assignments/new/page.tsx:42-45,152-165` now offers only active agents with a published-version pointer and directs the admin to publish first when none are available. The backend check remains authoritative against crafted/stale requests.

### Regression coverage

`tests/test_agents.py:247-280` adds a single API-level visibility matrix proving that:

- two different active, published agents assigned to the same trainee are both returned;
- session limits remain metadata and do not hide agents;
- new unpublished assignments are rejected;
- a historical unpublished assignment is hidden;
- an expired assignment is hidden;
- even a deliberately malformed cross-tenant assignment cannot expose the other tenant's agent.

Existing tests also cover revoked assignments, scheduled assignments, direct/team overlap, removed memberships, bulk cross-tenant rejection, role enforcement, and published-version pinning.

## Verification

Before (production data, read-only): the eligibility resolver has three active direct assignment rows but can return only `Ananya - Admissions Counsellor` and `DIDM_TESt`; `antther-test` fails at `published_version_id IS NOT NULL` (`app/saas/agents.py:366-372`). An authenticated production HTTP response could not be captured without the trainee's unrecoverable session cookie/password, and no session or credential was created as a workaround.

After (local API integration): `GET /my/agents` returned HTTP 200 with both eligible published agents exactly once, while excluding the unpublished, expired, and cross-tenant rows. The dashboard maps this response one-for-one, and its production build completed successfully. This verifies the API and render path without claiming that untouched production data has changed.

Commands/results:

- `.venv/bin/pytest -q tests/test_agents.py` — **23 passed**;
- `.venv/bin/pytest -q` — **230 passed**, one pre-existing Starlette/httpx deprecation warning;
- `npm run typecheck` — passed;
- `npm run build` — passed; `/my-training` and `/assignments/new` generated successfully.

## Remaining blockers and safe production next step

1. Deploy these code changes so future draft assignments cannot be created.
2. An authorized Organization Admin must review and publish `antther-test` version 1 through the existing agent publish workflow. That is a production mutation and was deliberately not performed here.
3. After publication, log in as the trainee (or use an explicitly supplied authorized session) and capture `GET /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/my/agents`; it should include all three eligible agents. Then reload `/my-training` and confirm the three cards. If it does not, preserve the response/status for follow-up.

The existing assignment must not be deleted or recreated: publishing sets the agent's current published-version pointer, after which the unchanged active assignment becomes eligible automatically.

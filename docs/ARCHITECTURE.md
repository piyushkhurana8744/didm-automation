# DIDM platform: architecture, security and operations

This repository runs two things in one FastAPI process:

1. **The calling automation**: the existing lead dialler and event campaigns. It uses Google Sheets, Sarvam outbound calls, Veblika WhatsApp and email. Its code is in `app/service.py`, `app/leads.py`, `app/integrations.py` and the routes in `app/main.py`. Its behaviour is unchanged by this work, apart from the hardening listed below.
2. **The training SaaS foundation** (`app/saas/`): multi-tenant organizations, users, roles, invitations, login sessions and an audit log, served under `/api/v1`. The Next.js web app in `frontend/` is built to static files and served at `/app`.

The two parts share the database and the process. They share no tables and no routes. New SaaS code never imports the dialler, and the dialler never imports SaaS code. The one shared piece is the `Mailer`.

```
app/
  main.py            routes for the automation, webhook intake, mounts the SaaS API and /app
  service.py         dialler, call results, WhatsApp follow-ups, event WhatsApp (automation)
  webhooks.py        durable webhook store, processing, retries, background worker
  security.py        client IP, in-memory rate limiter, log redaction
  migrate.py         runs Alembic from code
  db.py              engine, sessions, automation tables
  saas/
    models.py        organizations, users, memberships, invitations, auth_sessions, password_reset_tokens, audit_events
    passwords.py     scrypt hashing, random tokens, token hashing
    permissions.py   roles and permissions
    auth.py          cookie sessions, CSRF, org access dependency, scoped_get
    api.py           /api/v1 routes, security headers, static web app
    agents.py        teams, agent registry, versions, scenarios, assignments, training target resolver
    training.py      training session engine: state machine, capacity, phone start, provider results, sweeper
    training_api.py  training session, usage, limits and phone-number routes
    cli.py           create the first platform admin
migrations/          Alembic environment and revisions 0001-0005
frontend/            Next.js + TypeScript web app (static export, basePath /app)
docs/                this file, browser voice feasibility report
```

## Webhooks

`POST /webhooks/sarvam/{WEBHOOK_SECRET}` and `POST /webhooks/event/{token}` work in three steps:

1. **Store.** The JSON body is saved as a `webhook_events` row with status `pending` before anything else happens. The event id doubles as the correlation id in logs (`event=<id> attempt=<attempt_id>`). If saving fails, the route answers 500 and the provider can deliver again. An event is never acknowledged unless it was stored.
2. **Process.** Work runs in worker threads, never on the asyncio event loop, so one slow sheet or WhatsApp call no longer stalls other requests.
   - `WEBHOOK_PROCESSING=inline` (default) processes the event during the request and returns the handler's result, exactly as before.
   - `WEBHOOK_PROCESSING=queued` answers `{"ok": true, "accepted": true, "event_id": ...}` immediately, and the background worker (`WEBHOOK_WORKERS` threads, polling every 2 s) processes it.
3. **Retry.** If a handler raises, or asks for a retry (an event WhatsApp that Veblika rejected), the event becomes `failed`.
   - It is retried after 30 s, 60 s, 120 s and so on, capped at 30 minutes.
   - After `WEBHOOK_MAX_ATTEMPTS` tries it becomes `dead`.
   - Admins list events with `GET /admin/webhook-events?status=dead` and requeue one with `POST /admin/webhook-events/{id}/retry`. Both take the admin token.
   - An event stuck in `processing` for 5 minutes (the process died) is picked up again.

**Idempotency.** Every delivery is stored, including exact repeats. Correctness comes from the handlers:

- A call result moves a `call_attempts` row to `done` with a conditional `UPDATE ... WHERE state != 'done'`. Only one delivery can win; the others return `{"duplicate": true}`.
- A WhatsApp send first inserts a `whatsapp_claims` row that is unique on `(phone, kind)`. Kind is `followup` for lead follow-ups, or the template name for event messages. Only the worker that inserted the claim sends. A failed send releases the claim so a retry can send.
- A claim left in `sending` for 10 minutes is treated as abandoned. In that rare case (the process died mid-send) one message may be repeated.

**Locking.** The dialler lock (`Automation._lock`) now covers only picking and dialling leads. Result handling, sheet writes and WhatsApp sends run outside it, so 70 results arriving together are processed in parallel. `tests/test_hardening.py` checks this: 70 parallel deliveries plus 10 duplicates produce exactly 70 messages, on SQLite and on PostgreSQL 16.

## Database schema

The schema is managed by Alembic. `init_db()` runs `alembic upgrade head` at start-up when `MIGRATE_ON_START=true`, the default.

| Revision | Creates |
|---|---|
| `0001_baseline` | The five original tables (`call_attempts`, `whatsapp_messages`, `batches`, `alerts`, `settings`), **only if missing**. On the live database, which the old `create_all` built, it changes nothing and keeps every row. |
| `0002_webhook_events` | `webhook_events`, `whatsapp_claims` |
| `0003_identity` | `organizations`, `users`, `memberships`, `invitations`, `auth_sessions`, `password_reset_tokens`, `audit_events` |
| `0005_training` | `training_org_limits`, `training_sessions`, `training_session_events`, `training_usage_events`, `training_usage_reservations`, `browser_session_tokens`; nullable `users.phone_e164` and `memberships.verified_phone_e164`, `phone_verified_at`, `phone_verified_by` |
| `0004_agents` | `teams`, `team_members`, `agents`, `agent_versions`, `training_scenarios`, `agent_assignments` (additive only) |
| `0006_intelligence` | `evaluation_rubrics`, `evaluation_rubric_versions`, `training_org_settings`, `training_transcripts`, `training_transcript_turns`, `training_recordings`, `training_evaluations`, `evaluation_jobs`, `training_usage_adjustments`, `phone_verification_challenges`; nullable columns on `training_sessions`, `training_scenarios.rubric_id`, `memberships.phone_verification_method`, and two switches on `training_org_limits` that default to false (additive only) |
| `0007_production` | `evaluation_usage`, `retention_runs`; nullable or defaulted columns for evaluator budgets, the practice-call notice, transcript retention and legal hold, recording deletion retries, `purged_at`, `evidence_redacted_at`, `webhook_events.redacted_at` (additive only; downgrade drops them) |

Identity tables (UUID string ids):

- `organizations`: name, unique `slug`, `status` (active or suspended), `settings` JSON.
- `users`: unique lower-case `email`, `name`, `password_hash` (scrypt), `status`, `is_platform_admin`, `email_verified_at`, `last_login_at`.
- `memberships`: `organization_id`, `user_id` (unique pair), `role`, `status` (active or revoked).
- `invitations`: `organization_id`, `email`, `role`, `token_hash` (SHA-256 only), `status` (pending, accepted or revoked; "expired" is computed), `expires_at`, `invited_by_user_id`, `accepted_user_id`.
- `auth_sessions`: `token_hash`, `csrf_hash`, `user_id`, `active_organization_id`, `ip`, `user_agent`, `expires_at`, `last_seen_at`, `revoked_at`.
- `password_reset_tokens`: `token_hash`, `expires_at`, `used_at`.
- `audit_events`: `organization_id`, `actor_user_id`, `action`, `target_type`, `target_id`, `details` (no secrets), `ip`.

### Migration procedure

- **New migration:** edit the models, then run `DATABASE_URL=... alembic revision --autogenerate -m "what changed"`. Review the generated file and run the tests. The test `test_fresh_database_migrates_to_models_exactly` fails if models and migrations disagree.
- **Apply manually:** `DATABASE_URL=... alembic upgrade head`. Or let the app do it at start-up.
- **Check without applying:** `alembic upgrade head --sql` prints the SQL.
- **Before production:** take a Render Postgres backup or snapshot first. The first deploy runs 0001, a no-op on the live tables, then creates the new tables. No existing column is changed.
- **Rollback:** `alembic downgrade 0001_baseline` drops only the tables and columns added by 0002-0006. 0001's downgrade deliberately drops nothing. To roll back the code, deploy the previous commit. The old code ignores the extra tables. After rolling back, run `alembic stamp` with the revision that matches the code, or downgrade first.

## Authentication

- **Browser logins** use an opaque 256-bit session token in an `HttpOnly`, `SameSite=Lax` cookie `didm_session`. The cookie is `Secure` unless `COOKIE_SECURE=false`. Only the SHA-256 of the token is stored.
  - Sessions end after `SESSION_TTL_HOURS` (72) or `SESSION_IDLE_HOURS` (24) without use.
  - Logout revokes the session row.
  - A password change revokes the user's other sessions; a password reset revokes all of them.
- **CSRF:** login also sets a readable cookie `didm_csrf`. Every POST, PUT, PATCH or DELETE made with the session cookie must send the same value in `X-CSRF-Token`. The server compares its hash with the one stored on the session (a double-submit token bound to the session).
- **Passwords:** scrypt with N=2^15, r=8, p=3, a 16-byte salt and parameters stored in the hash (Python standard library, no extra dependency).
  - The minimum length is 10 characters.
  - Login takes the same time and gives the same answer for unknown emails and wrong passwords.
- **Password reset:** `POST /auth/password/forgot` always answers 202. If the account exists, a one-use link valid for `PASSWORD_RESET_TTL_MINUTES` is emailed.
- **Invitations:** links look like `.../app/invite/accept/#token=...`. The secret is in the URL fragment, which browsers never send to servers, so it cannot reach access logs. It is posted in a JSON body to `/invitations/lookup` and `/invitations/accept`.
  - A new person sets a name and password. Accepting the emailed link marks the email as verified.
  - An existing account must be logged in as the invited email.
  - Re-inviting a pending email re-issues the invitation with a new link and expiry, and the old link stops working.
  - Invitations can be revoked, and expire after `INVITATION_TTL_HOURS`.
- **Platform admins** are created on the command line only (`python -m app.saas.cli create-platform-admin --email ...`). There is no web sign-up for that role.
- **Legacy admin token:** `ADMIN_TOKEN` still protects `/admin/*` and `/dashboard`, through a Bearer header or `?token=`. That keeps today's dashboard links working. Failed attempts are rate limited (20 per 15 minutes per IP), and `?token=` values are removed from log lines. The new web app does not use this token.

## Authorization

| Permission | trainee | trainer | organization_admin | organization_owner |
|---|---|---|---|---|
| org.view | ✓ | ✓ | ✓ | ✓ |
| members.view | | ✓ | ✓ | ✓ |
| members.manage, invitations.manage, org.update, audit.view | | | ✓ | ✓ |
| training.self (my assigned agents) | ✓ | ✓ | ✓ | ✓ |
| agents.view, scenarios.manage, assignments.manage, teams.view | | ✓ | ✓ | ✓ |
| agents.manage, teams.manage | | | ✓ | ✓ |
| training.view (all sessions, usage) | | ✓ | ✓ | ✓ |
| training.manage (cancel any session, verify phone numbers) | | | ✓ | ✓ |
| rubrics.manage (create and publish rubrics) | | ✓ | ✓ | ✓ |
| recordings.view (play any session's recording; trainees always their own) | | ✓ | ✓ | ✓ |
| evaluations.manage (re-run evaluation or reconciliation) | | | ✓ | ✓ |
| recordings.manage (delete recordings, recording and consent settings) | | | ✓ | ✓ |

Rules enforced on the server:

- Admins cannot grant `organization_owner`, and cannot change or remove owners.
- Nobody changes their own role or removes themself.
- An organization always keeps at least one active owner.
- Platform admins can list, create, suspend and reactivate organizations. This gives them **no** access to an organization's data; that needs a membership.
- A suspended organization answers 403 to its members.

**Tenant isolation:**

- Every tenant route is under `/api/v1/organizations/{org_id}/...` and depends on `org_access(permission)`. That dependency looks up the caller's **own active membership** for that org on the server. The org id in the path only selects which organization; it is never proof of access.
- Organizations the caller does not belong to answer 404, the same as ids that do not exist.
- Resource ids from the client are loaded with `scoped_get(db, Model, org_id, id)`, which also filters by `organization_id`. Another tenant's id inside your own path is a 404.
- Revoking a membership takes effect on the next request.
- `tests/test_saas.py` checks these rules: company A cannot read or change company B's organization, users, invitations or audit log, by direct path or by mixing ids.
- Agents, versions, scenarios, teams and assignments follow the same rule; `tests/test_agents.py` repeats the cross-tenant checks for each. Sessions, recordings and evaluations do not exist yet; their tables must do the same.
- PostgreSQL row-level security is **not** enabled yet. It is planned as defence in depth once tenant data such as transcripts exists. It needs a per-request `SET app.organization_id` on the connection.

**Rate limits** (in memory, per process):

| What | Limit |
|---|---|
| Login | 30 per 15 min per IP, plus 5 failed attempts per 15 min per email |
| Forgot password | 5 per hour per IP, 3 per user |
| Reset | 10 per hour per IP |
| Invitation lookup | 30 per hour per IP |
| Invitation accept | 20 per hour per IP |
| Invitation create | 60 per hour per admin |

Behind Render, set `TRUST_PROXY_HEADERS=true`, so the last `X-Forwarded-For` entry is used as the client IP. With more than one instance these counters must move to a shared store such as Redis.

**Headers:** `/api` and `/app` responses carry `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. API responses also carry `Cache-Control: no-store`.

## API (prefix `/api/v1`)

| Method & path | Who |
|---|---|
| `GET /health` | anyone |
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me`, `PATCH /auth/me`, `POST /auth/active-organization` | user |
| `POST /auth/password/change`, `POST /auth/password/forgot`, `POST /auth/password/reset` | user, or anyone with a reset link |
| `GET /organizations` | user (own memberships) |
| `GET /organizations/{org_id}`, `PATCH ...` | org.view, org.update |
| `GET /organizations/{org_id}/members`, `PATCH /members/{membership_id}`, `DELETE /members/{membership_id}` | members.view, members.manage |
| `GET/POST /organizations/{org_id}/invitations`, `POST /invitations/{id}/revoke` | invitations.manage |
| `GET /organizations/{org_id}/audit-events` | audit.view |
| `POST /invitations/lookup`, `POST /invitations/accept` | anyone with the link |
| `GET/POST /platform/organizations`, `PATCH /platform/organizations/{org_id}` | platform admin |
| `GET /organizations/{org_id}/teams`, `GET /teams/{id}/members` | teams.view |
| `POST /teams`, `PATCH /teams/{id}`, `POST /teams/{id}/archive`, `POST/DELETE /teams/{id}/members[/{user_id}]` | teams.manage |
| `GET /agents` (paged: `status`, `q`, `category`, `limit`, `offset`), `GET /agents/{id}`, `GET /agents/{id}/versions[/{vid}]`, `GET /agents/{id}/scenarios`, `GET /scenarios/{id}` | agents.view |
| `POST /agents`, `PATCH /agents/{id}`, `POST /agents/{id}/archive`, `/restore`, `POST /agents/{id}/versions`, `PATCH`/`DELETE /versions/{vid}` (drafts), `POST /versions/{vid}/validate`, `/publish` | agents.manage |
| `POST /agents/{id}/scenarios`, `PATCH /scenarios/{id}` | scenarios.manage |
| `GET/POST /assignments` (paged: `agent_id`, `user_id`, `team_id`, `state`), `GET/PATCH /assignments/{id}`, `POST /assignments/{id}/revoke` | assignments.manage |
| `GET /my/agents`, `GET /my/agents/{id}`, `GET /my/assignments` | training.self |
| `POST /training/sessions`, `GET /training/sessions/{id}` (own, or training.view), `POST /training/sessions/{id}/cancel` (own, or training.manage), `GET /my/training/sessions`, `GET /training/availability` | training.self |
| `POST /training/browser/authorize`, `POST /training/sessions/{id}/browser-events` (off: 503) | training.self, own session |
| `GET /training/sessions` (paged: `status` incl. `open`, `channel`, `agent_id`, `user_id`, `since`, `until`), `GET /training/usage`, `GET /training/limits` | training.view |
| `GET /training/phones`, `POST/DELETE /members/{membership_id}/verify-phone` | training.manage |
| `PUT /auth/me/phone` | user |
| `GET/PUT /platform/organizations/{org_id}/training-limits`, `GET /platform/training/health` | platform admin |
| `POST /webhooks/sarvam-training/{TRAINING_WEBHOOK_SECRET}` | Sarvam (secret path + per-session HMAC) |

Agent routes keep the existing `/organizations/{org_id}/...` prefix instead of a bare `/agents`, so they use the same membership check as everything else. Paged lists answer `{items, total, limit, offset}` (limit at most 200). Errors answer `{"detail": "..."}`.

New automation admin routes: `GET /admin/webhook-events` and `POST /admin/webhook-events/{id}/retry`. The test-WhatsApp link is now `GET` to show a confirm page and `POST` to send.

## Voice agents (Phase 2)

Code: `app/saas/agents.py`. Tables: migration `0004_agents`.

**Registry.**
- Sarvam has no verified public API for creating or editing agents. So an agent here is a **link** to an app already built in Sarvam's dashboard: an admin pastes its app id. Registering creates nothing at Sarvam, and nothing in this phase calls Sarvam.
- No provider credentials are stored per agent. The platform's `SARVAM_API_KEY` stays in server settings. A version's configuration rejects any key that looks like a credential (`api_key`, `secret`, `token`, `password`, `credential`).
- A provider app id can be registered by one organization only (`uq_agents_provider_app`). The 409 answer does not say which organization holds it.
- Agents are archived, never deleted. Archived agents disappear from trainees and cannot be assigned or changed until restored.

**Versioning rules.**
- Versions are numbered 1, 2, 3 per agent. An agent has at most one draft at a time (a partial unique index).
- Drafts can be edited, validated and discarded.
- Publishing needs a Sarvam app version (a whole number of at least 1), at least one channel, an active agent, a valid configuration and a valid variable schema.
- Publishing is one transaction. A conditional `UPDATE ... WHERE status = 'draft'` flips the version, and the agent's `published_version_id` moves with it. A concurrent second publish gets 409.
- Published versions never change. The API answers 409, and an ORM `before_update`/`before_delete` guard raises `PublishedVersionImmutable` if any code tries to change or delete one. A check constraint also requires a published row to carry its provider app version and publish time.
- A new draft copies the published version, or any version the admin picks.
- Publishing a new version leaves older versions exactly as they were. A future session that stored `agent_version_id` therefore keeps its exact `provider_app_id` + `provider_app_version`.
- The agent's provider app id is fixed once any version is published. A different Sarvam app means registering a new agent.

**Variable schema.** A list of `{name, type, required?, description?, options?, max_length?, min?, max?, default?}`.
- `type` is one of `string`, `number`, `integer`, `boolean` or `enum`.
- There are at most 50 variables. Names are lower-case letters, digits and underscores.

**Scenarios.**
- A scenario belongs to one agent, with status `draft`, `active` or `archived`.
- Its variables are checked against the agent's published version, or the draft when nothing is published yet. Unknown names and wrong types always fail.
- Missing required variables (ones without a default) fail only when a scenario becomes active. Activating also needs a published version.
- `validated_version_id` records which version the check used. Scenario variables are not sent to Sarvam in this phase.

**Teams.** Teams are per organization. Removing a person from a team sets `removed_at`, so history is kept. Archiving a team ends access through it for everyone in it.

**Assignment resolution** (`entitlements()`, used by `/my/*`):
- **Who:** an assignment targets one user or one team, never both (a check constraint). A user is covered by their direct assignments plus those of every active team they are actively in.
- **Duplicates:** there can be only one open (unrevoked) assignment per agent and user, and per agent and team (partial unique indexes).
  - Assigning again while one is open skips it and reports it under `skipped`.
  - Assigning again after the open one expired closes the old one as `replaced` and creates a new one, so history stays.
- **When it counts:** only when it is not revoked, `starts_at <= now`, and `expires_at` is empty or in the future. The agent must also be active and have a published version. Scheduled (future) and expired assignments give no access.
- **Overlap:** a direct assignment, when there is one, decides everything and team assignments are ignored. Otherwise team assignments add up:
  - allowed scenarios are the union, and any team allowing all means all;
  - limits take the most generous value, and no limit beats any limit;
  - the expiry is the latest one.
- **Allowed scenarios:** `settings.allowed_scenario_ids` set to null means every active scenario of the agent. A list narrows it. Only active scenarios are ever shown.
- **Revocation and removal:**
  - A revoked assignment stops counting on the next request.
  - Removing someone from the organization ends their access immediately, because `org_access` fails. It also revokes their direct assignments (`member_removed`) and ends their team places, so rejoining starts clean.
- **Role changes:** a role change does not touch assignments. Everyone has `training.self`.
- **Trainers:** trainers can assign to trainees and to teams only. They can change or revoke only assignments of trainees and teams. Admins and owners can assign to anyone.
- **Bulk assign is all or nothing.** An agent, user, team or scenario id outside the organization answers 404, and no row is written.
- **Limits:** `max_sessions` and `max_minutes_per_session` are stored now. They will be enforced by the session phase.

**Phase 3 entry point.** `resolve_training_target(db, org_id, user_id, agent_id, channel, scenario_id)` returns a `TrainingTarget`. It walks organization → open assignment → published version → provider app id/version → channel, and merges schema defaults with scenario variables. It raises `NotEntitled` otherwise.

`TrainingTarget.call_target(settings)` builds the `CallTarget` for the phone channel. Connection and number come from the version's configuration, falling back to the platform defaults. It calls nobody.

**Outbound dialler.** This is unchanged. `Sarvam.start_call` without a `target` still sends the settings' agent; `tests/test_agents.py::test_dialer_default_agent_unchanged` and the earlier body-pinning test check this. The browser channel is assessed in [browser_voice_feasibility.md](browser_voice_feasibility.md).

## Training sessions (Phase 3)

Code: `app/saas/training.py` (engine) and `app/saas/training_api.py` (routes). Tables: migration `0005_training`. Sarvam facts used here are checked in [phase3_sarvam_verification.md](phase3_sarvam_verification.md).

**One model for both channels.** A `training_sessions` row records:
- who and which organization;
- the assignments that authorized it, plus a snapshot of the access rules at start;
- the agent, the exact published `agent_version_id`, and the Sarvam app id and app version copied from it;
- the scenario and the resolved variables;
- the allowlisted phone configuration (`connection_id`, `agent_phone_number` only);
- the channel, the state, the times, the duration and the billed seconds.

Later edits to the agent or a new published version never change an existing session. Only the last 4 digits of the trainee's number are stored on the session.

**State machine** (`TRANSITIONS`; every change is one conditional `UPDATE ... WHERE status IN (allowed sources)`):

```
requested -> preparing -> connecting -> active -> completed
any open state -> failed | cancelled | timed_out
preparing -> completed/failed   (provider result arrived before our start call returned)
connecting -> completed         (phone: Sarvam reports the end only, never "connected")
```

- `completed`, `failed`, `cancelled` and `timed_out` are terminal. A stale, late, duplicate or out-of-order event finds no allowed source state and changes nothing.
- A refused start (no assignment, a limit, an unverified phone) creates no session. It is written as a `training.session_rejected` audit event.
- **Result before the start response:** the webhook metadata carries our session id, so correlation never depends on the attempt id. If the result arrives first, it finishes the session, and the start call only fills in the attempt id.

**Starting a session** (`POST /organizations/{org}/training/sessions`):
1. The caller's cookie session and their active membership are checked (`org_access`); a suspended organization answers 403.
2. Training must be enabled for the organization (`training_org_limits.enabled`, which only platform admins set).
3. The channel must be switched on by the platform flag, by the organization's limits, and by the agent.
4. `entitlements()` must find an open assignment; the agent must be active and have a published version.
5. The scenario must be among the allowed active scenarios. Its variables are checked again against the pinned version's schema, with required variables enforced.
6. Phone only: `users.phone_e164` must equal the number an admin of this organization verified (`memberships.verified_phone_e164`). Changing the number makes it unverified.
7. Capacity is checked and reserved under `capacity_lock` (below), and the session is created as `requested`.
8. Phone: `launch_phone` moves the session to `preparing` and calls `Sarvam.start_call` with a `CallTarget` built from the pinned values. It uses the training webhook URL and metadata `{kind: "training", session_id, org_id, sig}`. Success means `connecting` and a confirmed reservation. A refusal or network error means `failed`, and the reservation is released.

No client value reaches Sarvam's connection settings. The agent version, app id, phone number and variables all come from the server. A `client_request_id` (unique per user and organization) makes a repeated or double-clicked start return the same session.

**Limits.** The effective limit is the strictest of these:
- the platform cap `TRAINING_MAX_CONCURRENT_TOTAL`, counted across all organizations;
- the organization's concurrent sessions, per-user concurrent sessions, sessions per day (counted from midnight in `TIMEZONE`), maximum session minutes and monthly minutes (calendar month, UTC). Platform admins set these; unset fields use the `TRAINING_DEFAULT_*` values;
- the assignment's `max_sessions` and `max_minutes_per_session`. These only narrow the limits above, never widen them.

What counts:
- **Session limits:** open sessions plus finished sessions that connected. Failed starts give their slot back.
- **Monthly minutes:** minutes billed this month plus the seconds held by open reservations, plus the new session's maximum.

*Phase 2 merging, checked:* several team assignments give the most generous single grant, never the sum. A user in two teams that each allow 1 session still gets 1 (tested). Organization caps always win.

**Atomicity.** Under `capacity_lock`, every count and the reservation run in one transaction:
- On PostgreSQL that is `pg_advisory_xact_lock`, so it holds across every backend instance and is released at commit or rollback.
- On SQLite (local development, one process) it is a process lock.
- No in-memory counters are used.
- Race tests start 6 trainees at once against an org limit of 2, and 5 starts by one user. Exactly 2 and exactly 1 succeed, on both databases.

**Reservations.** `reserved` (at request) → `confirmed` (the provider accepted) → `settled` (usage written), or `released` (ended without use) or `expired` (never started; reclaimed by the sweeper).

**Usage.** `finalize_usage` runs once per session: a conditional update on `usage_finalized_at`, backed by the unique `(session_id, metric)` constraint.
- It writes `billable_seconds`, and `sessions = 1` when the trainee was connected.
- Phone duration comes from Sarvam's `duration`.
- Browser duration is the server-clock time from `connected` to `ended`, capped at the maximum.
- A phone call that was placed but whose result never came is billed at the session maximum (`timeout_estimate`), so quotas err on the safe side.

**Sweeper** (`TrainingEngine.sweep`, every minute):
- `requested`/`preparing` sessions older than `TRAINING_START_TIMEOUT_SECONDS` become `failed`/`start_timeout`, with the reservation `expired`.
- `connecting`/`active` sessions past the maximum duration plus `TRAINING_END_GRACE_MINUTES` become `timed_out`.
- Terminal sessions whose usage was never written are finalized.

**Provider results** (`POST /webhooks/sarvam-training/{TRAINING_WEBHOOK_SECRET}`):
- Each result is stored first in `webhook_events` (source `training_result`) and then processed and retried by the existing `WebhookProcessor`, with dead-letter handling and admin retry. It never runs the lead dialler handler, so the Google Sheet and campaign WhatsApp cannot be touched (tested).
- Sarvam documents no webhook signing, so protection is layered:
  - a separate secret in the path;
  - an HMAC of `org_id:session_id` in the call metadata, checked with `compare_digest`;
  - the session is looked up by id **and** organization;
  - the `attempt_id` must match once it is known.
- Each result is deduplicated by a unique `(session_id, provider_event_id)` event. Its stored payload keeps only status, attempt id, duration, interaction id and a short failure reason: no transcript, no phone number.
- Status mapping: `connected` with a duration above 0 → `completed`; anything else (`no_answer`, `busy`, `failed`) → `failed`, with that status as the failure code.
- A result for an already terminal session is kept as a `late` event and changes neither state nor usage. Reconciling it with Sarvam's analytics attempts API is a Phase 4 item.

**Cancelling.** Owners (and `training.manage`) can cancel `requested`/`preparing` sessions. A placed phone call cannot be cancelled: no verified hang-up API exists, so it answers 409.

**Mid-session changes.**
- Removing a member, revoking an assignment or suspending the organization blocks new sessions immediately.
- A phone call already ringing or connected runs to its natural end, within the agent's own time limit and our timeout.
- Browser authorization re-checks the assignment.

**Browser voice: implemented foundation, switched off.**
- Behind `TRAINING_BROWSER_ENABLED=false`, the code covers starting a browser session, `POST /training/browser/authorize` and `POST /training/sessions/{id}/browser-events`.
- Authorizing:
  - re-checks the assignment;
  - moves the session `requested` → `preparing` → `connecting`;
  - fetches a single-use signed URL server-side with `SarvamWebAuth`, so the API key never reaches the browser;
  - stores only the URL's SHA-256 in `browser_session_tokens`, with one token per session;
  - returns the URL once.
- Blockers before switching it on:
  - The signed-URL endpoint appears only in the npm package source, not in the docs.
  - The SDK lets the browser set `agent_variables`, `initial_state_name`, `initial_bot_message` and the user identifier when the session starts, and Sarvam documents no server-side lock. A trainee could therefore change the scenario.
  - The SDK writes the signed URL to the browser console.
  - The URL's lifetime, whether web sessions count toward plan concurrency, and how they are billed are undocumented.
  - These need a live test with credentials and approval.
- The web app installs no SDK. It shows browser voice as unavailable with that reason.

**Observability.**
- Structured log lines carry ids and codes only, never numbers, URLs or keys: `training.session_requested`, `training.authorization_denied`, `training.capacity_reserved`, `training.provider_session_initiated`, `training.provider_connected`, `training.session_completed`, `training.session_failed`, `training.session_timed_out`, `training.usage_finalized` and `training.provider_error`.
- `GET /api/v1/platform/training/health` gives open sessions by channel, today's completions and average duration, failures by code, and training webhook states.
- Webhook paths, `?token=` values and httpx request lines are redacted from logs.

**Sarvam Bulbul V4.** Bulbul V3 reaches end of life on Voice Agents on **10 November 2026** (verified; see the verification doc).
- **Who switches:** the switch is made per agent in Sarvam's dashboard (Settings → Speaking), and only the account owner can do it. This code never changes provider agents.
- **After switching:** commit the new Sarvam version, then publish a new agent version here with the new `provider_app_version`. Old sessions stay pinned to the old version.
- **What to re-test:** pronunciation of names and course titles, the opening line, and language switching.

## Training intelligence (Phase 4)

What happens after a training call ends. Provider facts behind every choice are in `docs/phase4_sarvam_capabilities.md`.

**Post-call jobs (`evaluation_jobs`).** One row per session and kind: `transcript`, `evaluation`, `recording`, `reconcile`.
- A job is claimed with a conditional update, so two workers never run the same job. A job whose worker died is picked up again after its 5-minute lock.
- Retries back off exponentially (1, 2, 4 … minutes, at most 6 hours), or wait for the provider's `Retry-After`. After 6 attempts a job is `dead` and leaves an honest final state behind: a `missing` transcript, an `unresolved` reconciliation or a `failed` recording.
- The scheduler runs due jobs every minute (`training_jobs`) and deletes expired recordings daily (`recording_retention`).

**Transcripts.**
- The source is the `interaction_transcript` on Sarvam's result webhook: `[{role: agent|user, en_text}]`. When that is empty and provider lookups are on, the job reads `translate_transcript` from Sarvam's List interactions API, retrying while it is not ready.
- Turns keep the provider's order. `agent` maps to agent, `user` to trainee, anything else to unknown (the raw role is kept).
- Text is stored exactly as sent, marked `text_variant = en_text`: English, translated by Sarvam when the call was in another language. Sarvam gives no turn timings, so `start_ms` and `end_ms` stay empty.
- Imports are idempotent: the same content changes nothing, and a complete transcript is never replaced. Malformed turns make the transcript `partial`, with the reason; no transcript at all is `missing`.

**Rubrics and evaluations.**
- A rubric has versions. A draft can be edited; a published version never changes (the API answers 409, and an ORM guard raises on any write or delete). Each version has 1-12 weighted criteria, a 0-N scale (3, 4, 5 or 10), scoring instructions and a minimum number of trainee turns.
- A session is evaluated with its scenario's rubric, else the organization's default rubric, using the latest published version at that moment. The evaluation row records the rubric version, evaluator provider, model, our prompt/schema version (`rubric-eval-v1`) and the scoring settings.
- Evaluation runs only when the platform switched it on for the organization (`evaluation_enabled`) and an evaluator is configured. The only built-in evaluator is Sarvam chat completions with a strict JSON schema.
- **Insufficient evidence:** if the trainee spoke fewer times than the rubric needs, or fewer than 20 words, the result is `insufficient_evidence` with no score, and the evaluator is not called.
- **Prompt injection:** the transcript is escaped and fenced in the user message as data; the rules say to ignore instructions inside it. The answer must match the schema exactly (unknown or missing fields are rejected). Every score must be backed by quotes that really appear in a trainee turn; a score without such a quote is dropped. The overall score is computed here from the weights, never taken from the model.
- **Score:** weighted mean of the scored criteria, as 0-100. If less than half of the rubric's weight could be scored, the result is `insufficient_evidence`. Confidence is the model's confidence times the share of weight scored.
- Invalid output is retried twice, then stored as `failed` with no score. Evaluations are never edited; re-evaluating with another rubric version adds a row.

**Recordings.** Off unless the platform allows them (`recording_allowed`), the organization switched them on with a consent notice, the trainee ticked that exact notice when starting, a private store is configured, and a recording source is configured.
- None of the last two exist in production yet, so recordings stay off. The source would be Sarvam's `GET .../recordings/{interaction_id}`, which returns a WAV.
- When on: only HTTPS URLs on Sarvam's own host are followed; the file must be audio and at most 50 MB; it is stored under `training/{org}/{session}/…` in the private store, never in the database.
- Playback is a presigned store URL that lasts 5 minutes. It is made only on request, for the trainee who owns the session or `recordings.view` (trainer and up). Every playback is audited. Admins (`recordings.manage`) can delete. Recordings are deleted when their retention period (1-365 days, default 30) ends.

**Reconciliation.** Fixes the gaps Phase 3 left open. A session's status never changes after it ends, and usage events are never edited.
- **Start request timed out after Sarvam placed the call:** the session fails (`provider_unreachable`) and a reconcile job is queued. Without an attempt id the lookup cannot match the call safely, so it is marked `unresolved` instead of guessing by phone number. When the real result arrives later, it carries our signed metadata, so it is matched and usage is corrected.
- **Late result after a local timeout:** we billed the session's maximum. The provider's duration is recorded beside the session (`provider_status`, `provider_duration_seconds`), and the difference is written as a `training_usage_adjustments` row (`reason = provider_reconciliation`), with the raw evidence, an audit row and a session event.
- **No result at all:** with provider lookups on, the job asks Sarvam's List attempts API by attempt id and reconciles the same way.
- **Duplicates:** the adjustment has a unique key per session, metric and reason, and a reconciled session is never reconciled again.
- Quota consumption is usage events plus adjustments. The scorecard shows reserved seconds, billed seconds, adjustments, quota seconds and the provider-reported duration separately. Sarvam reports no per-call billing, so no number is shown as provider billing.

**Phone verification.** Admin confirmation stays the method and is labelled `admin_confirmed`; it proves an admin confirmed the number, not that the trainee holds it. The OTP flow is built (6-digit codes, stored only as an HMAC, 10-minute expiry, 5 tries, 3 sends an hour) but needs a code sender. Sarvam has no SMS or OTP API, and WhatsApp through Veblika would need an approved authentication template, so none is configured.

**Analytics rules.**
- A practice session is one where the trainee talked to the agent: connected here, or connected according to the provider after reconciliation.
- Scores come only from `completed` evaluations, one per session (its latest). Unevaluated and insufficient-evidence sessions never enter an average.
- Practice minutes use the provider-reported duration when known, otherwise ours.
- Skills average each criterion's score as 0-100; strongest and weakest skills need at least two scored sessions.
- Score buckets: 0-39, 40-59, 60-74, 75-89, 90-100.
- Participation: active trainees in the organization (or team) against those with at least one practice session in the period.

**API (under `/api/v1/organizations/{org_id}`).**

| Method and path | Who |
|---|---|
| `GET /training/sessions/{id}/scorecard` | the trainee who owns it, or `training.view` |
| `POST /training/sessions/{id}/recording/playback` | the owner, or `recordings.view` |
| `DELETE /training/sessions/{id}/recording` | `recordings.manage` |
| `POST /training/sessions/{id}/evaluate`, `POST .../reconcile` | `evaluations.manage` |
| `GET /my/training/progress` | `training.self` |
| `GET /training/analytics`, `GET /training/analytics/trainees/{user_id}` | `training.view` |
| `GET /rubrics`, `GET /rubrics/{id}`, `GET /rubric-template` | `training.view` |
| `POST /rubrics`, `PATCH /rubrics/{id}`, `POST /rubrics/{id}/versions`, `PATCH`/`DELETE /rubric-versions/{id}`, `POST /rubric-versions/{id}/publish` | `rubrics.manage` |
| `PUT /scenarios/{id}/rubric` | `scenarios.manage` |
| `GET /training/settings` / `PUT /training/settings` | `training.view` / `recordings.manage` |
| `POST /me/phone/verification-code`, `POST /me/phone/verify` | `training.self` (503 `otp_unavailable` without a sender) |

New permissions: `rubrics.manage` (trainer), `evaluations.manage` (admin), `recordings.view` (trainer), `recordings.manage` (admin). The platform limits endpoint also takes `evaluation_enabled` and `recording_allowed`.

## Production readiness (Phase 5)

- **Recording store:** `app/saas/s3store.py`, any S3-compatible bucket, SigV4 over httpx (checked against AWS's published signatures). Private objects, server-side encryption, Content-MD5 and SHA-256 on upload, content-addressed keys `training/{org}/{session}/{hash}`, presigned GET of at most 15 minutes (playback uses 5). A daily job checks objects still exist.
- **Evaluator cost controls:** every call is a row in `evaluation_usage` with tokens. Before each call: per session and rubric version call cap, per-organization monthly calls and tokens (platform limits), platform daily cap. Output tokens and timeout are capped. A budget stop skips the job and the scorecard says why.
- **Retention:** `app/saas/retention.py`, see `docs/phase5_data_retention.md`.
- **Analytics:** aggregated in SQL (`app/saas/analytics.py`), trainee list paginated, CSV export with formula-injection protection, audited.
- **Readiness:** `/readyz` (public) and `/admin/readiness` (admin token); `python -m app.migrate` is the controlled migration step. See `docs/phase5_deployment.md`.
- **Browser voice:** still off; `docs/phase5_browser_voice.md` has the review and the NO-GO.

## Environment variables (new)

| Variable | Default | Purpose |
|---|---|---|
| `WEBHOOK_PROCESSING` | `inline` | `inline` or `queued` (see Webhooks) |
| `WEBHOOK_WORKERS` | `4` | Background worker threads |
| `WEBHOOK_MAX_ATTEMPTS` | `5` | Tries before an event is `dead` |
| `MIGRATE_ON_START` | `true` | Run Alembic at start-up |
| `TRUST_PROXY_HEADERS` | `false` | Use the last `X-Forwarded-For` hop as the client IP (set `true` on Render) |
| `PUBLIC_APP_URL` | `PUBLIC_BASE_URL` + `/app` | Base of links in invitation and reset emails |
| `COOKIE_SECURE` | `true` | `false` only for local http |
| `SESSION_TTL_HOURS` / `SESSION_IDLE_HOURS` | `72` / `24` | Session lifetime |
| `INVITATION_TTL_HOURS` | `168` | Invitation lifetime |
| `PASSWORD_RESET_TTL_MINUTES` | `60` | Reset link lifetime |
| `FRONTEND_DIST_DIR` | `frontend/out` | Built web app served at `/app` |
| `TRAINING_PHONE_ENABLED` | `false` | Platform switch for phone training (paid Sarvam calls) |
| `TRAINING_BROWSER_ENABLED` | `false` | Platform switch for browser voice; keep off until the Web SDK is verified |
| `TRAINING_WEBHOOK_SECRET` | empty | Secret in `/webhooks/sarvam-training/{secret}` and the per-session HMAC key; phone training is unavailable without it |
| `TRAINING_MAX_CONCURRENT_TOTAL` | `2` | Open training sessions across all organizations |
| `TRAINING_DEFAULT_*` | 1 / 1 / 3 / 10 / 120 | Org concurrency, user concurrency, sessions per day, session minutes, monthly minutes when an org has no value |
| `TRAINING_START_TIMEOUT_SECONDS` / `TRAINING_END_GRACE_MINUTES` | `120` / `15` | When a stuck start fails, and how long after the maximum duration a missing result times out |
| `TRAINING_PROVIDER_LOOKUPS_ENABLED` | `false` | Read-only Sarvam Analytics lookups: transcripts the webhook did not carry, and outcomes of calls we never heard back about |
| `EVALUATOR_PROVIDER` | empty | `sarvam` scores transcripts with Sarvam chat completions (billed per token). Empty: no evaluation |
| `EVALUATOR_MODEL` | `sarvam-105b` | Model for the evaluator |
| `SARVAM_CHAT_API_KEY` | empty | Key for Sarvam chat completions (`api-subscription-key`). Kept separate because it is not confirmed that the Voice Agents key works there |
| `RECORDING_STORE` | empty | Reserved. No private object store is built in yet, so recordings stay off |
| `PHONE_OTP_PROVIDER` | empty | Reserved. No SMS or WhatsApp code sender is built in yet, so phone numbers stay admin-confirmed |

Email for invitations and resets uses the existing `SMTP_*` settings. Without SMTP, invitation links are still returned once to the admin who created them. Reset emails cannot be sent, and the API says nothing that would reveal whether an account exists.

## Local development

```
pip install -r requirements-dev.txt
cp .env.example .env            # fill in what you need; DRY_RUN=true keeps the dialler in test mode
export COOKIE_SECURE=false ADMIN_TOKEN=dev WEBHOOK_SECRET=dev
uvicorn app.server:app --reload  # migrates the SQLite file, API on :8000
python -m app.saas.cli create-platform-admin --email you@example.com --name You

cd frontend && npm ci && npm run dev   # http://localhost:3000/app, /api is proxied to :8000
```

## Testing

```
pytest                                   # whole suite on SQLite
TEST_POSTGRES_URL=postgresql://user@host:5432/postgres pytest   # same suite on PostgreSQL (creates a database per test)
cd frontend && npm run typecheck && npm run build
```

No test calls Sarvam, Veblika, Google or SMTP: they are faked or mocked with respx. The suite covers:

- **Migrations:** a fresh database, an old database built by create_all, downgrade then upgrade, and a check that models match migrations.
- **Webhooks:** durable storage, queued mode, retries and dead events, parallel and duplicate deliveries, and the event loop staying free.
- **Authentication:** cookies, CSRF, rate limits, password reset and password change.
- **Roles and invitations:** RBAC, the invitation lifecycle, and cross-tenant IDOR checks.
- **Compatibility:** log redaction and the Sarvam request shape.

## Deployment prerequisites (not done; need approval)

1. **Backup:** back up the Render Postgres database before the first deploy of this branch.
2. **Plans:** Render free plans sleep and limit the database, so move to paid plans for production.
3. **Environment:** set `PUBLIC_APP_URL`, `TRUST_PROXY_HEADERS=true` and the SMTP settings. Keep `WEBHOOK_PROCESSING=inline` for the first deploy, then switch to `queued` once the dead-event endpoint has been checked.
4. **Docker build:** the image now has a Node stage that builds the web app, so `frontend/package-lock.json` must be committed.
5. **First platform admin:** create it from a Render shell with the CLI.
6. **Single worker:** keep one instance and one worker. The dialler lock, scheduler, webhook worker and rate limits live in the process. Several instances need a shared queue and lock, and a shared rate-limit store.

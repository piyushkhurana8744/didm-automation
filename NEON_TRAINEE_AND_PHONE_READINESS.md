# DIDM SaaS — Neon Trainee and Phone Readiness

Date: 2026-10-31 (Asia/Kolkata)

Status: **NOT READY FOR A PHONE PILOT**

This assessment used read-only database queries, local/public health checks, and source inspection. It did not create or modify users, invitations, agents, scenarios, assignments, limits, or phone verification records. It made no Sarvam request and initiated no call.

## Runtime and database

- Runtime configuration selects PostgreSQL database `neondb`; it is not using SQLite.

- Database role observed: `neondb_owner` (password and URL were not displayed).
- Alembic revision is exactly `0008_recording_providers`.
- Local `GET /readyz` returned `{"ok":true,"database":"ok","schema_up_to_date":true}`.
- `MIGRATE_ON_START=false`.
- **Security blocker:** `pg_stat_ssl` reported `ssl=false` for the inspected live connection. Before operational use, the configured Neon URL/driver must enforce TLS (and channel binding if supported), then this must be rechecked from the actual runtime connection.

## Organization and owner

- Organization: `DIDM` (`didm`), status `active`.
- Organization ID: `439799da-8a8e-4ff9-a490-7ffcfcd65564`.
- One accepted owner invitation exists.
- Owner membership is `organization_owner`, membership `active`, user `active`, and email verified.
- The owner phone is not stored/verified; this does not block a trainee's call.
- Source permission evaluation gives an owner every organization permission, including dashboard/org view, invitations, agents, assignments, training management, phone verification, and limits view.
- A credentialed browser/dashboard request was not made, so UI access itself was not session-tested in this read-only audit.

## Trainee onboarding

- A trainee already exists, so no new invitation was sent.
- Trainee: `de***@didm.in`, name `demotraineee`.
- Invitation status: `accepted`.
- Membership: `trainee`, `active`; user: `active`; email verified.
- Membership belongs only to the DIDM organization in the observed data.
- The role grants `org.view` and `training.self`, which are the permissions used by My Training.
- Login/My Training was not credential-tested because no trainee credentials or authenticated session were used.

## Phone verification

- The trainee currently has no phone stored on the user and no verified phone on the membership.
- Supported flow: the trainee first saves their own phone; an authorized organization admin/owner then confirms the same number through `POST /api/v1/organizations/{org_id}/members/{membership_id}/verify-phone`.
- The application checks that the saved user phone equals the membership's verified phone. No phone was marked verified during this audit.

## Organization training limits

- There is **no `training_org_limits` row** for DIDM.
- Code behavior for a missing row is explicit: `enabled=false`, `phone_enabled=false`, and `browser_enabled=false`; only numeric limits inherit platform defaults.
- Effective numeric defaults are configured in `TRAINING_DEFAULT_ORG_CONCURRENCY`, `TRAINING_DEFAULT_USER_CONCURRENCY`, `TRAINING_DEFAULT_SESSIONS_PER_DAY`, `TRAINING_DEFAULT_SESSION_MINUTES`, and `TRAINING_DEFAULT_MONTHLY_MINUTES`.
- Platform-wide concurrency is `TRAINING_MAX_CONCURRENT_TOTAL=2`.
- Therefore organization training and phone practice are currently blocked even though the platform phone adapter is configured.

## Sarvam agent, version, scenario, and assignment

- No agents exist for the organization.
- No agent versions are published.
- No training scenarios exist.
- No assignments exist.
- Consequently the trainee cannot see an assigned agent or start training.
- Provider credentials (`SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`) are present, without exposing their values.
- A real Sarvam App ID and provider app version must be supplied through the supported agent/version workflow. They must not be invented.
- A scenario is not universally required by the session endpoint, but an assignment may restrict access via `allowed_scenario_ids`; any selected scenario must be active/valid for the published version.

## Platform phone readiness

- `TRAINING_PHONE_ENABLED=true`.
- `TRAINING_WEBHOOK_SECRET` is configured.
- `PUBLIC_BASE_URL` is configured.
- Sarvam server configuration is present, so source evaluation of `TrainingEngine.phone_available()` is `true`; this is the value rendered as platform `phone_channel_live=true` by the limits API.
- `TRAINING_BROWSER_ENABLED=false`.
- The configured Cloudflare HTTPS origin (`fourth-bit-attitude-funeral.trycloudflare.com`) returned HTTP 200 at `/readyz` during this audit.
- The exact call-creation endpoint is `POST /api/v1/organizations/{org_id}/training/sessions` with channel `phone` and an assigned `agent_id`.
- `DRY_RUN=true` applies to the legacy dialer workflow. The SaaS training engine does not consult `DRY_RUN` before placing its provider call. Calling the session-start endpoint after prerequisites are met can therefore initiate a real paid call.

## Exact blockers

1. Current PostgreSQL connection was observed without TLS.
2. Organization has no limits row, so training and phone practice both evaluate disabled.
3. Trainee has no saved phone and no verified phone.
4. No Sarvam agent is registered.
5. No immutable agent version is published.
6. No assignment exists for the trainee.
7. No scenario exists; optional unless the intended assignment/version requires one, but one is recommended for controlled training.
8. Owner and trainee browser-login flows were not credential-tested.

## Safe remediation order

1. Enforce TLS/channel binding in the Neon connection and verify `pg_stat_ssl.ssl=true` from the application connection.
2. As Platform Admin, create/update DIDM training limits: enable training and phone practice and select conservative organization/user/daily/monthly limits. Keep browser disabled.
3. Have the trainee log in, confirm My Training access, and save their own phone number.
4. After actually confirming that number with the trainee, have the owner/admin use the supported phone-verification action. Do not bypass this check.
5. Register the real Sarvam agent using its genuine provider App ID; create a version using the genuine provider App version; then publish it.
6. Create and activate a scenario if the intended training needs one. If assignment access is restricted, include that scenario ID.
7. Assign the published phone-capable agent to the existing trainee with an explicit expiry, `max_sessions=1`, and a conservative per-session minute limit.
8. Recheck authenticated `/training/availability` and My Training. It must show training enabled, phone available, phone on file/verified, and the assigned agent.
9. Stop before POSTing the training-session endpoint and obtain separate explicit approval for one paid call.

## Safe single-call pilot checklist

- [ ] Neon runtime connection shows TLS enabled and approved target identity.
- [ ] Local and Cloudflare `/readyz` are healthy.
- [ ] Platform reports `phone_channel_live=true`.
- [ ] DIDM training enabled; phone enabled; browser disabled.
- [ ] Platform/org/user concurrency leaves one slot available.
- [ ] Daily/monthly quota has capacity.
- [ ] Trainee is active, can log in, and is isolated to DIDM.
- [ ] Trainee phone was self-supplied and subsequently confirmed/verified.
- [ ] Genuine Sarvam App ID and version are mapped; credentials remain server-side.
- [ ] Agent version is published and offers the `phone` channel.
- [ ] Assignment is active, unexpired, one-session limited, and scenario-compatible.
- [ ] Webhook origin is HTTPS and reachable; webhook secret is configured.
- [ ] Trainee understands recording/practice notices and applicable consent.
- [ ] Separate approval for one paid call has been received.
- [ ] Only then send one idempotent session-start request and monitor its terminal state before allowing another.

## Environment variables relevant to readiness

`DATABASE_URL`, `MIGRATE_ON_START`, `TRAINING_PHONE_ENABLED`, `TRAINING_BROWSER_ENABLED`, `TRAINING_WEBHOOK_SECRET`, `PUBLIC_BASE_URL`, `PUBLIC_APP_URL`, `SARVAM_API_KEY`, `SARVAM_ORG_ID`, `SARVAM_WORKSPACE_ID`, `TRAINING_MAX_CONCURRENT_TOTAL`, `TRAINING_DEFAULT_ORG_CONCURRENCY`, `TRAINING_DEFAULT_USER_CONCURRENCY`, `TRAINING_DEFAULT_SESSIONS_PER_DAY`, `TRAINING_DEFAULT_SESSION_MINUTES`, `TRAINING_DEFAULT_MONTHLY_MINUTES`, and `DRY_RUN`.


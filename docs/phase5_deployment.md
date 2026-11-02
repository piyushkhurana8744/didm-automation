# Phase 5: deployment readiness, checklist and rollback plan

*Written 2026-10-21. Nothing here has been deployed. Every step that changes production needs the owner's approval.*

Labels: **IMPLEMENTED** (in code, tested), **MOCK-TESTED** (tested against fakes only), **NOT VERIFIED** (taken from a provider's public docs, not checked against our account), **DECISION** (needs the owner).

## 1. Review of the current setup

| Area | What is there | Finding | Status |
|---|---|---|---|
| Image | Two-stage Dockerfile: Node 22 builds the static web app, Python 3.12 runs uvicorn with one worker | Now runs as an unprivileged user, unbuffered logs, a 20 s graceful shutdown so in-flight webhooks finish. `docker build` could not run here (no Docker daemon in this environment) | IMPLEMENTED, build NOT RUN |
| Workers | One process: APScheduler (sweep, post-call jobs, retention, storage check, reports), the webhook worker thread, in-memory rate limits | Must stay one instance and one worker. Two instances would double scheduled jobs (post-call jobs are claim-safe, the lead dialler lock and rate limits are not) | IMPLEMENTED (documented limit) |
| Migrations at start-up | `MIGRATE_ON_START=true` by default | Now wrapped in a PostgreSQL advisory lock, so two starting processes cannot migrate at once (tested: three concurrent runs on an empty PostgreSQL 16 database all finish at head). A failed migration still stops the new instance from starting, and Render keeps the old one serving | IMPLEMENTED |
| Controlled migration | `python -m app.migrate` | Runs the same locked upgrade and prints current and head revisions. Preferred: run it as a deploy step, then start the app with `MIGRATE_ON_START=false` | IMPLEMENTED |
| Health | `/healthz` (liveness, no database) | Kept for Render's health check, so a database blip does not restart the app | IMPLEMENTED |
| Readiness | `/readyz` (public: database reachable and schema at head, 503 otherwise) and `/admin/readiness` (admin token: queues, dead jobs and webhooks, scheduler and worker state, features, configuration problems) | No secret values are returned, only whether settings are set | IMPLEMENTED |
| Configuration | `config_problems()` | Logged at start-up and shown in `/admin/readiness`. A bad optional setting (for example an incomplete S3 configuration) turns that feature off with an error instead of stopping the app | IMPLEMENTED |
| Secrets | Render `sync: false` env vars | New S3 and chat keys are `sync: false`. Keys never appear in logs, reprs or API responses (tests check the store, evaluator, scorecard and readiness output) | IMPLEMENTED |
| Logging | Structured `event {json}` lines with ids and codes only | Presigned URLs, signed browser URLs and codes are never logged | IMPLEMENTED |
| Queue durability | Webhooks stored before processing; post-call jobs in `evaluation_jobs` with claim and backoff | Both survive restarts. Jobs only run while the process is awake (see the free plan below) | IMPLEMENTED |
| Database connections | One engine per process | Pool now `DB_POOL_SIZE=5` + `DB_MAX_OVERFLOW=5`, `pool_pre_ping`, recycled every 30 minutes | IMPLEMENTED |
| Static export | Built in the image, served at `/app` | Unchanged | IMPLEMENTED |

### Render plan findings (from Render's public docs, NOT VERIFIED against this account)

1. **Free web services sleep after about 15 minutes without traffic.** While asleep, no scheduler job runs (session sweep, post-call jobs, retention, reports), and the first webhook after a sleep waits for a cold start. A Sarvam result could time out and rely on Sarvam's retry. **Production needs a paid, always-on instance.**
2. **Free PostgreSQL databases expire after a fixed period and have no backups.** Render's docs give 30 days at the time of writing. **Production needs a paid database with backups** before any customer data is stored.
3. **Pre-deploy commands are a paid-plan feature.** On a paid plan, set the pre-deploy command to `python -m app.migrate` and `MIGRATE_ON_START=false`. On the free plan, keep `MIGRATE_ON_START=true` (now lock-protected).
4. **`autoDeploy: true`** deploys every push to the connected branch. Merging the stacked PRs into that branch therefore deploys. **DECISION:** keep it, or switch it off and deploy by hand during the rollout.

## 2. Deployment checklist

Do these in order. Stop at any failed check.

**Before (needs approval)**
1. Decide merge order: PRs 1 to 5 are stacked; merge them in order into the deploy branch, or merge PR 5's branch once all are reviewed.
2. Move the web service and database to paid plans (see the findings above). **DECISION, costs money.**
3. Take a database backup (Render dashboard, or `pg_dump` from a Render shell) and note its time. Test that it restores into a scratch database.
4. Set new secrets in Render (none are needed for the first deploy; all Phase 5 features are off by default): leave `RECORDING_STORE`, `EVALUATOR_PROVIDER` empty and `RETENTION_ENFORCEMENT_ENABLED=false`.
5. Check `TRUST_PROXY_HEADERS=true`, `COOKIE_SECURE=true`, `PUBLIC_BASE_URL` and `PUBLIC_APP_URL`.

**Deploy**
6. Paid plan: pre-deploy `python -m app.migrate`, `MIGRATE_ON_START=false`. Free plan: leave the default.
7. Deploy. Watch the log for `Configuration:` warnings and errors.
8. Check `/healthz` answers 200 and `/readyz` answers `{"ok": true, "schema_up_to_date": true}`.
9. With the admin token, check `/admin/readiness`: `schema.current == "0007_production"`, scheduler and webhook worker running, no `error` items in `config`, dead job and webhook counts as expected.
10. Check the lead dialler is untouched: `/admin/check`, `/dashboard`, and that `DRY_RUN` is what it was.
11. Log in to `/app` as the platform admin; open an organization's training settings and the retention report (it should only show counts).

**After**
12. Leave training channels off. Enable features one at a time, each after its own approval: phone pilot, provider lookups, evaluator, recordings, retention enforcement. Each has a manual pilot in `docs/phase4_security_privacy.md` §5 and the Phase 5 report.

## 3. Rollback plan

| Situation | Action | Data impact |
|---|---|---|
| New instance fails to start or `/readyz` stays 503 | Render keeps the previous instance serving. Fix forward or roll back the code | None |
| Bug after deploy, schema fine | Roll back the code in Render (redeploy the previous commit). Old code ignores the new tables and columns: every Phase 5 column is nullable or defaulted | None |
| Need to remove the Phase 5 schema | `alembic downgrade 0006_intelligence` (tested on SQLite and PostgreSQL). Take a backup first: it drops `evaluation_usage` and `retention_runs` | Loses usage metering and retention history |
| A migration damaged data | Restore the backup from step 3 into a new database, point `DATABASE_URL` at it, redeploy the matching commit | Loses writes since the backup |
| A feature misbehaves | Turn its switch off (env var or the organization's limits). No redeploy of code needed for org limits | None |

After a code rollback that leaves the schema at 0007, nothing else is needed. After a downgrade, run the old code's matching revision with `alembic stamp` only if the code and schema disagree.

## 4. What is still not production-grade

- One process only: horizontal scaling needs a shared lock for the dialler, a shared rate-limit store and a separate worker process.
- No error tracking or metrics service; logs are the only signal.
- The Docker image has not been built in this environment.
- Backups and restore drills depend on the paid database plan.

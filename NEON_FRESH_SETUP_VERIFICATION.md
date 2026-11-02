a# Neon fresh setup verification

## Current verdict

**APPROVAL REQUIRED.** Preflight passed for connectivity, TLS and emptiness. Schema, authentication and SaaS workflow verification are pending migration approval.

## Checks completed

| Check | Result |
|---|---|
| Configured URL parsed without exposing credentials | PASS |
| Neon hostname and PostgreSQL scheme | PASS |
| `sslmode=require` and channel binding required | PASS |
| Driver reports TLS in use | PASS |
| Read-only transaction enforced | PASS |
| Target database reachable | PASS |
| Non-system table count | PASS: 0 |
| Alembic table absent | PASS: fresh target |
| Migration chain linear | PASS: 8 revisions, head `0008_recording_providers` |
| Automatic startup migrations disabled locally | PASS |
| SQLite files unchanged | PASS |
| Offline Alembic SQL generation | NOT SUPPORTED by baseline inspection logic |
| Neon migrations applied | PENDING APPROVAL |
| PostgreSQL schema/index/FK verification | PENDING MIGRATION |
| Platform Admin bootstrap/login | PENDING CREDENTIAL DECISION |
| Organization/RBAC/isolation verification | PENDING BOOTSTRAP |
| Agent/assignment/training availability | PENDING ORGANIZATION SETUP |
| Sarvam paid call | NOT ATTEMPTED |

## Verification after approved migration

1. Confirm `alembic_version.version_num = 0008_recording_providers`.
2. Compare PostgreSQL tables, columns, indexes, foreign keys, checks and unique constraints against SQLAlchemy metadata and migrations.
3. Run the backend suite normally and, only against an approved disposable PostgreSQL test database, run `TEST_POSTGRES_URL` integration tests.
4. Bootstrap the chosen Platform Admin through the supported CLI.
5. Verify login/session cookie behavior, organization creation, secure owner invitation, RBAC and cross-tenant isolation.
6. Register/publish an agent and create an assignment without calling Sarvam.
7. Verify `/readyz`, Platform Admin phone-channel status, trainee availability and public tunnel health.

## Stop conditions

Abort before migration if the repeated inventory finds any table, if the host/database differs, if credential rotation is unconfirmed, or if the owner does not explicitly approve this target.


# Neon database schema verification

## Current state

The target is fresh and empty. Schema verification is therefore **pending migration approval**.

## Pre-migration evidence

| Check | Result |
|---|---|
| PostgreSQL driver | psycopg 3 |
| TLS active according to driver | Yes |
| URL SSL mode | require |
| Channel binding | require |
| Transaction read-only | Yes |
| Non-system tables | 0 |
| Unexpected schemas | 0 |
| Alembic version table | Absent |
| Automatic startup migration | Disabled |
| SQLite files changed | No |

## Expected migration chain

Linear revisions: `0001_baseline`, `0002_webhook_events`, `0003_identity`, `0004_agents`, `0005_training`, `0006_intelligence`, `0007_production`, `0008_recording_providers`.

The official implementation is `python -m app.migrate`; it uses Alembic plus a PostgreSQL advisory transaction lock. `create_all` will not be used. Offline SQL mode is not supported because the baseline migration inspects the live connection.

## Post-migration checks pending

- Revision equals `0008_recording_providers`.
- All legacy dialer and SaaS tables exist.
- Columns/types match SQLAlchemy metadata.
- Foreign keys and tenant-scoped relationships exist.
- Unique, partial and ordinary indexes exist.
- Check constraints exist.
- Authentication, invitations, agents, assignments, sessions, webhook events, transcripts, evaluations, usage, analytics and recording metadata tables persist correctly.
- No application rows exist before administrator bootstrap.


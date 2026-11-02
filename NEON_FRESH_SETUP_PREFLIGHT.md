# Neon fresh setup preflight

Date: 2026-10-31 (Asia/Kolkata)

## Verdict

**APPROVAL REQUIRED.** The configured Neon target is reachable over TLS and contains zero non-system tables. It is technically fresh, but its database name is `neondb`, so the repository alone cannot prove that it is the user's intended dedicated database/project/branch. Credential rotation also cannot be independently confirmed from a connection string alone.

No database write, migration, schema creation, seed, or account bootstrap was performed.

## Target validation

- Scheme: PostgreSQL.
- Host: Neon domain; a credential-free abbreviated fingerprint was checked during execution.
- Database name: `neondb`.
- Username and password fields: present.
- URL policy: `sslmode=require`, channel binding required.
- psycopg driver connection: successful.
- Driver-reported TLS in use: true.
- Explicit transaction mode during inspection: read only.
- Non-system tables: 0.
- `alembic_version`: absent.
- Application/user rows inspected: none; there are no application tables.

The database is empty, but approval must identify this exact project/branch/database as the intended dedicated target. A default database named `neondb` is not self-evidently dedicated.

## Credential rotation

The database accepts the credential currently stored in `.env`. This proves usability, not that the previously exposed password was rotated. Confirm rotation in the Neon console by revoking the old role password/connection string and issuing a new one. Do not paste either value into chat or reports.

## Automatic migration safety

`.env` originally had `MIGRATE_ON_START=true`. It was changed locally to `false` during preflight to prevent an accidental external schema write. The running development server continues to use explicit local SQLite and migrations-off process overrides.

## Driver and Alembic compatibility

- SQLAlchemy 2.x and `psycopg[binary]` 3.x are configured.
- `make_engine()` accepts PostgreSQL URLs.
- Migration chain is linear: `0001_baseline` through head `0008_recording_providers` (8 revisions).
- `app.migrate.upgrade_head()` uses a PostgreSQL advisory transaction lock.
- The official controlled command is `python -m app.migrate` with an explicit process `DATABASE_URL`.
- `create_all` is not used as a migration substitute.

Alembic offline SQL generation is not supported by the current baseline migration because `0001_baseline` inspects the live connection with `sa.inspect(op.get_bind()).has_table(...)`. The attempted offline command failed before producing a usable migration script and made no connection/write. Online migration is therefore the required path after approval.

## SQLite preservation

The SHA-256 hashes of `didm.db` and `demo.db` were recorded before and after preflight and were unchanged. Neither file was migrated, reset, copied, or deleted.

## Required approval statement

Before migration, confirm all of the following:

1. The configured abbreviated Neon host is the intended project and branch.
2. Database `neondb` is intentionally the dedicated DIDM database, despite its default-style name.
3. The previously exposed database password has been rotated and the old credential revoked.
4. Apply migrations `0001_baseline` through `0008_recording_providers` to this currently empty target.

If a separately named database is preferred, create it in the Neon console or explicitly approve a safe `CREATE DATABASE` action first. Do not migrate the current target and then rename the decision afterward.


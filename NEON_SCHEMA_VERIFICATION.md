# Neon schema verification

## Result

**PASS — revision `0008_recording_providers`.**

All verification queries ran read-only after migration.

| Check | Result |
|---|---:|
| Expected application tables | 38 |
| Actual application tables | 38 |
| Missing tables | None |
| Unexpected tables | None |
| Critical SaaS/training tables missing | None |
| Public indexes | 132 |
| Primary-key constraints | 39 (includes Alembic table) |
| Foreign-key constraints | 84 |
| Unique constraints | 23 |
| Check constraints | 15 |

Verified critical structures include users, organizations, memberships, invitations, audit events, agents, immutable agent versions, scenarios, assignments, training sessions, usage, webhooks, transcripts, evaluations and recording metadata.

The schema is empty of application records pending the separately approved administrator bootstrap. Schema verification used PostgreSQL catalogs plus SQLAlchemy metadata table comparison; no destructive compatibility test targeted `neondb`.


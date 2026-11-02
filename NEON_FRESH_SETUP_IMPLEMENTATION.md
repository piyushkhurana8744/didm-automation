# Neon fresh setup implementation

## Status

**Pending explicit target and migration approval.** No Neon writes have occurred.

## Controlled migration plan

After approval, stop any runtime that could race the controlled step. Keep `MIGRATE_ON_START=false`. Run the official migration module once with the approved Neon URL supplied through process environment, without printing it:

```bash
DATABASE_URL="<approved Neon URL>" \
DIDM_LOAD_DOTENV=false \
MIGRATE_ON_START=false \
./.venv/bin/python -m app.migrate
```

Before executing, repeat the read-only table inventory and abort if any non-system table exists. After executing, query the revision and schema read-only. Never call `Base.metadata.create_all()`.

## Administrator bootstrap

The supported bootstrap is:

```bash
DATABASE_URL="<approved Neon URL>" \
DIDM_LOAD_DOTENV=false \
MIGRATE_ON_START=false \
./.venv/bin/python -m app.saas.cli create-platform-admin \
  --email "<chosen admin email>" \
  --name "<chosen admin name>"
```

The command prompts twice for a password without echoing it, validates password policy, hashes it with scrypt, and records an audit event. No administrator was created because an email/name/password decision has not been supplied and bootstrap is a separate write requiring approval.

## Organization bootstrap after admin

Use the existing Platform Admin UI/API to create the organization and issue a secure owner invitation. The invitation stores only a token hash, expires, and requires the owner to set a password. Do not create demo users or copy SQLite data.

Then configure, in order:

1. Organization training limits.
2. Owner activation and login.
3. Trainee invitation, phone capture and verification.
4. Sarvam agent registration and immutable published version.
5. Direct/team assignment and scenario access.
6. Trainee availability checks.

No provider call is required for these setup checks.

## Local runtime after schema verification

Only after the Neon schema is at head should the temporary SQLite `DATABASE_URL` process override be removed. Continue using:

```text
MIGRATE_ON_START=false
COOKIE_SECURE=false  # localhost HTTP only
TRAINING_BROWSER_ENABLED=false
```

Phone training may remain enabled only when the public HTTPS tunnel, webhook secret, Sarvam settings, organization limits and verified trainee phone all pass availability checks.


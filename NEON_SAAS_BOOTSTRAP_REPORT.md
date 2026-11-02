# Neon SaaS bootstrap report

## Status

**Pending schema migration and user decisions.** No Neon users or demo data were created.

## Supported administrator path

The repository-supported command is:

```bash
DATABASE_URL="<approved Neon URL>" \
DIDM_LOAD_DOTENV=false \
MIGRATE_ON_START=false \
./.venv/bin/python -m app.saas.cli create-platform-admin \
  --email "<chosen email>" --name "<chosen display name>"
```

It prompts securely for the password twice, validates policy, hashes with scrypt, grants Platform Admin and creates an audit event. An email, display name and interactive password are still required, followed by explicit bootstrap approval.

## Fresh SaaS workflow pending

After Platform Admin login:

1. Create the intended organization through the supported Platform Admin UI/API.
2. Issue an owner invitation and verify truthful email delivery or the authorized one-time fallback.
3. Activate the owner through the invitation flow.
4. Configure training limits.
5. Invite and activate a trainee.
6. Capture and verify the trainee phone.
7. Register the existing Sarvam agent identifiers without copying any SQLite record.
8. Publish the confirmed provider version.
9. Create scenarios only where needed and assign the agent.
10. Verify trainee entitlement and quota through read-only APIs.

Names, emails, phones, provider identifiers and scenario content will not be invented.


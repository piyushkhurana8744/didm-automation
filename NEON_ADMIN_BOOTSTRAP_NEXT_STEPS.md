# Neon administrator bootstrap next steps

## Status

**Prepared, not executed.** Administrator creation is a separate Neon write and was not included in migration approval.

## Supported command

After the owner supplies an administrator email and display name and separately approves bootstrap:

```bash
DATABASE_URL="<approved Neon URL>" \
DIDM_LOAD_DOTENV=false \
MIGRATE_ON_START=false \
./.venv/bin/python -m app.saas.cli create-platform-admin \
  --email "<administrator email>" \
  --name "<administrator display name>"
```

The password is requested twice using `getpass`, is never echoed or passed as a command argument, is checked against the application password policy, and is stored as a salted scrypt hash. The command creates/promotes the user, grants Platform Admin and writes `platform.admin_granted` to the audit log.

## Inputs and approval still required

1. Administrator email.
2. Administrator display name.
3. Explicit approval for the bootstrap write.
4. Password entered interactively by the owner; never send it in chat.

After bootstrap, verify Platform Admin login before creating the organization and secure owner invitation. Do not create demo accounts or copy SQLite data.

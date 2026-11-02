# Platform Admin bootstrap report

Date: 2026-10-31 (Asia/Kolkata)

## Result

**Platform Admin bootstrap completed successfully.**

The account was created through the repository-supported interactive command against the approved Neon PostgreSQL database. The password was entered by the owner through the terminal's hidden `getpass` prompts; it was not supplied through command arguments, source files or this report.

## Pre-bootstrap gate

- Target database: PostgreSQL `neondb`.
- Credential-free approved fingerprint matched.
- Alembic revision: `0008_recording_providers`.
- Existing account with the requested email: none.
- Existing Platform Admin count: zero.

## Read-only post-bootstrap evidence

- Requested email exists exactly once.
- Requested display name stored.
- User status: active.
- Platform Admin flag: true.
- Password hash present.
- Password hash scheme: scrypt.
- Email marked verified by the supported bootstrap path.
- Matching `platform.admin_granted` audit event count: 1.
- Total Neon users: 1.
- Total organizations: 0.
- Alembic revision remains `0008_recording_providers`.

No organization, owner, trainee, demo account, agent, assignment or training session was created. No Sarvam API request or phone call occurred.

## Runtime and login flow

- Local Neon-backed `/readyz`: HTTP 200, database OK, schema current.
- Login page: HTTP 200.
- Actual password authentication must be completed by the owner in the browser because the password was intentionally never disclosed to the agent. A successful browser login is the remaining end-user verification.

Login URL:

```text
http://127.0.0.1:8000/app/login/
```

Use the approved administrator email and the password entered directly in Terminal.

## Next steps requiring separate approval/input

1. Verify browser login and Platform Admin navigation.
2. Choose the organization name, slug and owner email.
3. Create the organization through the supported Platform Admin workflow.
4. Deliver and accept the secure owner invitation.
5. Configure organization training limits before onboarding trainees or agents.

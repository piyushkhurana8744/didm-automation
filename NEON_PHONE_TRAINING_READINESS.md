# Neon phone training readiness

## Verdict

**APPROVAL REQUIRED.** Platform-level local phone availability was previously verified on SQLite, but the fresh Neon database has no schema or SaaS records yet. It cannot be declared ready for a one-call pilot.

## Platform configuration already established

- `.env` loading works before settings/provider initialization.
- Process variables override `.env`.
- Phone training flag is configured true.
- Browser training is configured false.
- Webhook secret and Sarvam settings are present (presence only; provider validity untested).
- Configured Cloudflare HTTPS origin previously matched the active tunnel and returned HTTP 200.
- Webhook route exists at `/webhooks/sarvam-training/{secret}`.
- No Sarvam call has been made.

## Neon-dependent readiness pending

- Schema migration and revision verification.
- Platform Admin and organization bootstrap.
- Organization training and phone limits.
- Activated trainee and verified phone.
- Active published agent with confirmed provider App ID/version and phone channel.
- Active assignment, permitted scenarios and remaining quota.
- Runtime confirmed against Neon rather than SQLite.
- `/readyz`, `phone_channel_live`, trainee availability and capacity checks against the fresh Neon state.

`DRY_RUN` protects legacy dialer actions but is not treated as proof that training calls are fake. No session-start endpoint will be invoked without separate paid-call approval.

## Security prerequisites

- Rotate and revoke the exposed Neon password before migration.
- Rotate the exposed training webhook secret before any pilot.
- Keep `MIGRATE_ON_START=false` permanently; migrations are a controlled step.
- Keep `COOKIE_SECURE=false` only for localhost HTTP and true for HTTPS deployments.


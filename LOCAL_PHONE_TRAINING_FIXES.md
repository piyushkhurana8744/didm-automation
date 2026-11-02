# Local phone training fixes

## Implemented code fix

Deterministic local `.env` loading now runs before the module-level `Settings()` is created in `app/config.py`.

Required behavior:

1. Resolve `.env` relative to the repository/application source, never the caller's current directory.
2. Do not load `.env.demo`, `demo.env`, or `.env.example`.
3. Preserve real process environment precedence (`override=False` semantics).
4. Run before `settings = Settings()` and therefore before provider construction.
5. Work identically in the Uvicorn reload parent and child.
6. Add tests for loading, process precedence, absent file and demo-file exclusion.
7. Document an opt-out for deployment environments if a local `.env` is accidentally included, while noting that the Docker image currently does not copy `.env`.

`python-dotenv>=1.0,<2` is now a runtime dependency. The loader uses `load_dotenv(repository_env, override=False)`. `DIDM_LOAD_DOTENV=false` is the explicit deployment and test opt-out.

## Safe application sequence

The old reload server was stopped before editing. The repaired server was started with process-level `DATABASE_URL=sqlite:///./didm.db`, `MIGRATE_ON_START=false`, and `COOKIE_SECURE=false`. Process precedence therefore prevented selection of the external database and no migrations ran.

## Required local configuration correction

Set `PUBLIC_BASE_URL` to the detected public HTTPS tunnel origin. Do not include the webhook path or secret. Set `PUBLIC_APP_URL` to the same origin plus `/app` if invitation links should traverse the tunnel.

Because the active tunnel is a Cloudflare quick tunnel, repeat hostname detection after every tunnel restart. A named tunnel is preferable for a stable callback origin.

## Required restart verification

After the code change and intentional database selection, all seven checks below passed:

1. Start Uvicorn normally.
2. Confirm the worker environment reports required settings as present without printing values.
3. Confirm the active database is the intended database.
4. Confirm the Platform Admin limits API reports `phone_channel_live=true`.
5. Confirm trainee availability reports `enabled=true`, `phone.available=true`, phone present and verified.
6. Confirm the public health endpoint reaches this exact process.
7. Confirm no open sessions consume capacity.

## Changes actually made

- Added `LOCAL_PHONE_TRAINING_DIAGNOSTIC.md`.
- Added deterministic `.env` loading and the deployment opt-out.
- Added and installed `python-dotenv`.
- Added loader, precedence, reload-child, database-selection and phone-availability tests.
- Forced tests to opt out before importing application configuration.
- Removed the duplicate Cloudinary block after confirming every duplicate value was identical.
- Sanitized `.env.example` after discovering actual-looking credentials/configuration in the template; `.env` was preserved.
- Did not modify database records, phone verification, assignments or provider configuration.
- Did not invoke Sarvam or initiate a call.

## Credential rotation

Rotate the exposed Neon database password and `TRAINING_WEBHOOK_SECRET`. Update the owning secret stores and `.env` without copying values into logs or chat. Testing a replacement Neon credential requires separate approval for a read-only external connection with migrations disabled; this repair intentionally never connected to Neon. After rotating the webhook secret, restart locally with the SQLite overrides and confirm `phone_channel_live=true`; do not send a synthetic webhook or start a call.


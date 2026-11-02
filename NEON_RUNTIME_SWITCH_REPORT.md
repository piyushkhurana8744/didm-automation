# Neon runtime switch report

## Status

**PASS — local runtime now uses Neon PostgreSQL `neondb`.**

The local server was started without a SQLite `DATABASE_URL` override and with:

```text
MIGRATE_ON_START=false
COOKIE_SECURE=false  (localhost HTTP only)
```

The repository `.env` supplies the approved Neon URL and phone/provider configuration. Browser training remains disabled.

## Runtime evidence

- `/readyz`: HTTP 200, database OK, schema up to date.
- `/api/v1/health`: HTTP 200.
- `/app/`: HTTP 200.
- Configured database scheme: PostgreSQL.
- Configured database name: `neondb`.
- Runtime process has no SQLite database file open.
- Active Cloudflare hostname matches `PUBLIC_BASE_URL`.
- Public `/api/v1/health`: HTTP 200.
- Automatic startup migrations: false.
- Local HTTP session cookies: `COOKIE_SECURE=false`; deployed HTTPS must use true.

## Phone platform state

- `TRAINING_PHONE_ENABLED=true`.
- `TRAINING_BROWSER_ENABLED=false`.
- Training webhook secret present.
- Public HTTPS base present.
- Sarvam account and call-target fields present.
- Sarvam adapter constructed.
- Global phone availability resolver: true.
- `DRY_RUN=true` for the legacy dialer.

Important: training phone session launch does not use `DRY_RUN` as a fake-call guarantee. No session-start endpoint was invoked. Organization and trainee availability remain pending because the fresh Neon database intentionally has no organization or users yet.

## Regression verification

- Backend suite: 222 passed, one existing Starlette deprecation warning.
- Tests ran with `DIDM_LOAD_DOTENV=false` and an empty `TEST_POSTGRES_URL`, using isolated temporary SQLite databases rather than `neondb`.
- Frontend TypeScript check: passed.
- No paid provider request occurred.


# Local phone training diagnostic

Date: 2026-10-31 (Asia/Kolkata)

## Executive summary

**Verdict: READY for UI/availability testing; no paid call was attempted.**

The original Uvicorn reload worker did not load `.env`. It therefore used default `TRAINING_PHONE_ENABLED=false`, empty provider/webhook settings, and `sqlite:///./didm.db`. Organization switches were enabled, but global phone availability was false.

The old server was stopped, deterministic repository `.env` loading was added before `Settings()` construction, and the server was restarted with explicit process overrides selecting the existing `didm.db`, disabling migrations, and allowing local HTTP cookies. The external Neon database was never contacted.

The running Platform Admin API now reports `phone_channel_live=true`. The trainee availability API reports training enabled, phone available, phone present and verified. No Sarvam API was called and no phone call was placed.

## Root cause and environment behavior

- `.env` exists and is now loaded from a path derived from `app/config.py`, not the current directory.
- `python-dotenv` loads it with `override=False`; process variables retain precedence.
- `DIDM_LOAD_DOTENV=false` explicitly disables loading for deployments/tests.
- `.env.demo`, `demo.env`, and `.env.example` are never considered.
- Loading runs before the module-level `settings = Settings()` and therefore before Sarvam/training construction.
- Uvicorn reload parent and child inherit explicit overrides and each imports the same deterministic loader.

## Runtime status matrix

| Setting | `.env` | Effective local runtime | Result |
|---|---:|---:|---|
| `TRAINING_PHONE_ENABLED` | true | true | PASS |
| `TRAINING_BROWSER_ENABLED` | false | false | PASS; intentionally disabled |
| `TRAINING_WEBHOOK_SECRET` | set | set | PASS |
| `PUBLIC_BASE_URL` | HTTPS tunnel | same active tunnel | PASS |
| `PUBLIC_APP_URL` | set | set | PASS |
| Sarvam API/org/workspace | set | loaded | PASS (presence only) |
| Sarvam connection/agent phone | set | loaded | PASS (presence only) |
| `DATABASE_URL` | external PostgreSQL | overridden to `sqlite:///./didm.db` | PASS; Neon untouched |
| `MIGRATE_ON_START` | true | overridden false | PASS |
| `COOKIE_SECURE` | deployment value | overridden false | PASS for localhost HTTP only |

No credential values or secret-bearing URLs are included.

## Active process and database

- Command: repository `.venv` Uvicorn, `app.server:app --reload`, bound to `127.0.0.1:8000`.
- Database: existing local SQLite `didm.db`.
- Migrations: disabled for this restart.
- `/readyz`: database and schema healthy.
- The frontend and APIs are served by this same FastAPI process.

The same database contains active Demo Academy limits, the verified trainee phone, two assigned published phone agents, and no open sessions. `demo.db` is not active.

## Cloudflare tunnel

- `cloudflared tunnel --url localhost:8000` is running.
- One healthy tunnel connection is registered with zero proxy errors at inspection time.
- The configured hostname exactly matches Cloudflared's active hostname.
- Public `/api/v1/health` returned HTTP 200.
- FastAPI registers `/webhooks/sarvam-training/{secret}` and constructs the callback from `PUBLIC_BASE_URL` plus the training webhook secret.
- The secret-bearing route was not invoked.

Quick-tunnel hostnames are temporary. Recheck after every Cloudflared restart or use a named stable tunnel.

## Phone availability breakdown

`TrainingEngine.phone_available()` now evaluates:

| Boolean | Result |
|---|---:|
| `training_phone_enabled` | true |
| training webhook secret non-empty | true |
| public base URL non-empty | true |
| Sarvam adapter constructed | true |
| Global phone channel | **true** |
| Organization training enabled | true |
| Organization phone enabled | true |
| Trainee phone present | true |
| Trainee phone verified against membership | true |
| Trainee API `phone.available` | **true** |

The trainee sees two assigned phone agents. Demo Admissions Coach has one active allowed scenario; new agent has zero. A scenario is not inherently required because the backend accepts `scenario_id=null`, and the inspected published agents have no required variable-schema fields.

## Cookie behavior

With `COOKIE_SECURE=true`, browsers do not send the session cookie over ordinary `http://localhost`, so local authentication appears broken. The safe local-only remedy is the process override `COOKIE_SECURE=false`. Do not put this override in deployed HTTPS configuration. The inspected local login cookie correctly omitted `Secure`; deployed environments should retain secure cookies.

## Files changed

- `app/config.py`: deterministic, precedence-preserving `.env` loader and opt-out.
- `requirements.txt`: `python-dotenv>=1.0,<2`.
- `tests/conftest.py`: test-process opt-out before app imports.
- `tests/test_config_env.py`: loader, precedence, opt-out, reload child, database and phone tests.
- `.env.example`: opt-out documentation and removal of actual-looking configuration/credentials.
- `README.md`: automatic loading and safe local SQLite launch.
- `.env`: removed only a second byte-identical Cloudinary block; values preserved.
- `LOCAL_PHONE_TRAINING_FIXES.md`: implementation and rotation notes.

## Tests

- New and training-targeted tests: **34 passed**.
- Full backend suite: **222 passed**, one existing Starlette deprecation warning.
- Frontend TypeScript: passed.
- Python compile/import check: passed.
- Runtime Platform Admin phone status: true.
- Runtime trainee availability: true.
- Public tunnel health: HTTP 200.

## Remaining blockers and security actions

1. Rotate the exposed Neon database password. Do not test it from this local process without separate approval; any validation must be read-only with migrations disabled.
2. Rotate `TRAINING_WEBHOOK_SECRET`, update the relevant environment/secret stores, restart with the same SQLite safety overrides, and recheck availability. Do not send a synthetic webhook.
3. Rotate the Sarvam API key too if it was exposed anywhere outside its intended secret store.
4. A successful availability check does not prove provider-side IDs, billing, telephony routing or webhook delivery. Those require the separately approved one-call pilot.

## Safe restart command

```bash
DATABASE_URL=sqlite:///./didm.db \
MIGRATE_ON_START=false \
COOKIE_SECURE=false \
./.venv/bin/uvicorn app.server:app --host 127.0.0.1 --port 8000 --reload
```

This preserves `.env` for phone/Sarvam/tunnel settings while process precedence guarantees local SQLite and prevents external migrations.

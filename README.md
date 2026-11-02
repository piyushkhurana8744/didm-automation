# DIDM Automation App

This app replaces Make for the Ananya admission calls. It does everything the Make dialer does today, plus safety checks, alerts, a dashboard and a daily report. Sarvam still makes the calls, the Google Sheet stays your lead list, and Veblika still sends the WhatsApp messages.

## What it does

| Job | How |
|---|---|
| Picks the next lead | Same rules as the Queue sheet: Call = YES, never-called first, retries for no answer, busy, failed, voicemail or no conversation, max 3 attempts, 2 hours apart, and never a number that said do-not-call |
| Starts the call | Sends the lead's name, course, source, city and note to Ananya (app version 7) |
| Saves the result | Writes Status, Outcome, Program, Mode, Centre, Goal, Callback, Summary and Duration into the same Leads columns as Make |
| WhatsApp follow-up | Sends your Veblika template once per number after the call. Skips do-not-call, wrong numbers and anyone already messaged |
| Batches | Calls one by one, or several at a time if you raise MAX_PARALLEL_CALLS, until the batch is done |
| Safety | Calls only 9 am to 9 pm IST, has a daily call cap and a Stop button, stops a batch if 3 calls in a row fail to start, retries network errors, and ignores duplicate results |
| Stuck calls | If Sarvam sends no result within 30 minutes, the call is closed and the queue moves on |
| Alerts | Emails you on any error: a call that did not start, sheet trouble or a WhatsApp failure |
| Daily report | Emails calls, connects, outcomes, talk minutes and WhatsApp counts at 9:15 pm |
| Dashboard | One page with today's numbers, the last 50 calls, alerts and buttons: Start calling, Stop, Allow again, Email report |

It starts in **test mode** (DRY_RUN=true). In test mode it reads the sheet but makes no calls, sends no WhatsApp and writes nothing to the sheet. Real calling starts only when you switch test mode off.

## Setup steps (no coding needed)

**Step 1. GitHub (stores the code)**
1. Sign up or log in at github.com with a DIDM email.
2. Click **New repository**, name it `didm-automation`, choose **Private**, and click **Create**.
3. Connect GitHub in this Claude project so Claude can upload the code. Or click **uploading an existing file** and drag in everything from this folder.

**Step 2. Google service account (lets the app use the sheet)**
1. Open console.cloud.google.com with the DIDM Google account and create a project called `didm-automation`.
2. Search for **Google Sheets API** and click **Enable**.
3. Go to **IAM & Admin → Service accounts → Create service account**, name it `didm-automation`, and click **Done**.
4. Open it, go to **Keys → Add key → JSON**. A file downloads. Keep it private.
5. Open the Leads Google Sheet, click **Share**, paste the service account's email (it ends in `iam.gserviceaccount.com`) and give it **Editor** access.

**Step 3. Hosting on Render (runs the app 24x7)**
1. Sign up at render.com with GitHub.
2. Click **New → Blueprint**, choose the `didm-automation` repository, and click **Apply**. This creates the app and its database.
3. When asked for the values marked *sync: false*, paste:
   - `GOOGLE_SERVICE_ACCOUNT_JSON`: open the downloaded JSON file in Notepad, copy everything, paste.
   - `SARVAM_API_KEY`: from Sarvam dashboard **Settings → API Key** (a new key is fine).
   - `VEBLIKA_API_KEY`, `VEBLIKA_AUTH_NAME`, `VEBLIKA_AUTH_IN`: the same key Make uses for Veblika. In Make, open **Keys → the Veblika key** to see its name and whether it goes in the header or the query.
   - `SMTP_USER` / `SMTP_PASSWORD`: a Gmail address and its **app password** (Google Account → Security → App passwords).
   - `ALERT_EMAIL_TO`: where alerts and reports go.
   - `PUBLIC_BASE_URL`: leave it for now. Fill it in after step 4.
4. `ADMIN_TOKEN` and `WEBHOOK_SECRET` are created automatically. Open the app's **Environment** tab to copy `ADMIN_TOKEN`. It is your dashboard password.

**Step 4. Your domain**
1. In Render, open the app, go to **Settings → Custom domain** and add `automation.didm.in`.
2. Render shows a CNAME record. Add it where didm.in's DNS is managed (GoDaddy, Cloudflare and so on).
3. Once it shows *Verified*, set `PUBLIC_BASE_URL` to `https://automation.didm.in` and save.

**Step 5. Test mode check**
1. Open `https://automation.didm.in/dashboard?token=YOUR_ADMIN_TOKEN`. It should say **TEST MODE**.
2. Open `https://automation.didm.in/admin/check?token=YOUR_ADMIN_TOKEN`. `missing_for_live` must be an empty list `[]`.
3. Click **Start calling** with 2 calls. The dashboard shows 2 calls; no one is actually called.

**Step 6. Go live**
1. In Make, turn off **DIDM_Ananya_Dialer_and_Results**, so the two systems never call the same lead.
2. In Render **Environment**, set `DRY_RUN` to `false` and save. The app restarts.
3. On the dashboard, set the batch to 1 and click **Start calling**. Check the sheet row and the WhatsApp message.
4. If all is fine, run normal batches. To go back to Make at any time, set `DRY_RUN` to `true` and turn the Make scenario on again.

## Daily use
- **Start calls:** dashboard → enter the number → **Start calling**.
- **Stop at once:** dashboard → **Stop all calling**. No new call starts until you click **Allow calling again**.
- **Change limits:** in Render Environment, change `DAILY_CALL_CAP`, `MAX_PARALLEL_CALLS`, `CALLING_START_HOUR` or `CALLING_END_HOUR`.
- **New Ananya version:** change `SARVAM_APP_VERSION`.

## For a developer
- Python 3.12, FastAPI, SQLAlchemy (Postgres on Render, SQLite locally), Alembic migrations, APScheduler. Web app: Next.js + TypeScript in `frontend/`, served at `/app`.
- Architecture, database schema, login and permission rules, migrations, environment and deployment notes: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Browser voice research: [docs/browser_voice_feasibility.md](docs/browser_voice_feasibility.md).
- Run the tests with `pip install -r requirements-dev.txt && pytest` (set `TEST_POSTGRES_URL` to run them on PostgreSQL). Web app: `cd frontend && npm ci && npm run typecheck && npm run build`.
- Run locally with `cp .env.example .env`, fill it in, then `uvicorn app.server:app --reload`. The repository `.env` loads automatically and process variables win. Set `DIDM_LOAD_DOTENV=false` to opt out. When `.env` points at an external database, a safe local SQLite launch is `DATABASE_URL=sqlite:///./didm.db MIGRATE_ON_START=false COOKIE_SECURE=false uvicorn app.server:app --reload`.
- Sarvam result webhook: `POST /webhooks/sarvam/{WEBHOOK_SECRET}`. Every delivery is stored first and retried if processing fails; see `GET /admin/webhook-events`. Admin endpoints need `Authorization: Bearer ADMIN_TOKEN`.
- Keep one worker only. The batch lock, scheduler, webhook worker and rate limits live in the process.
# didm-automation

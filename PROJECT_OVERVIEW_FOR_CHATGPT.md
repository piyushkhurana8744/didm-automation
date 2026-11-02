# Project Context: DIDM Automation & Voice Training SaaS Platform

> **Purpose of this Document:**  
> This document provides a complete, end-to-end technical context of the codebase for ChatGPT (or any AI assistant / developer). It details the architecture, all features implemented across phases, database schemas, APIs, security mechanisms, current status, and pending items.

---

## 1. Executive Summary: What is this Project?

This repository houses a unified system containing **two major components** running in a single **FastAPI** backend with a **Next.js** frontend:

1. **The Outbound Lead Dialler & Campaign Automation (Original System):**
   - Replaced Make.com scenarios for DIDM (Delhi Institute of Digital Marketing) admission counselling calls.
   - Automatically reads leads from **Google Sheets**, initiates outbound AI voice calls via **Sarvam AI (Ananya voice agent)**, saves outcomes back to Google Sheets, sends WhatsApp messages via **Veblika**, and sends daily email reports via SMTP.
2. **The Voice Training SaaS Platform (Multi-Tenant System - Built across Phases 1–5):**
   - A full-featured enterprise training platform where students / trainees practice admissions or sales calls with AI voice agents.
   - Features multi-tenancy, RBAC roles (Platform Admin, Org Owner, Org Admin, Trainer, Trainee), AI voice agent registry and versioning, scenario management, team assignments, phone-call practice sessions with real-time capacity locks, automated post-call audio transcription, AI rubric-based evaluation via LLM, audio recording storage (S3/Cloudflare R2), automated data retention/legal holds, and detailed analytics.

---

## 2. Tech Stack & Directory Structure

- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic (database migrations), APScheduler, httpx, scrypt (passwords), SHA-256 HMAC tokens.
- **Database:** PostgreSQL (production on Render) / SQLite (local dev), connection pooling with `pool_pre_ping`.
- **Frontend:** Next.js (App Router), TypeScript, Vanilla CSS design system, exported as static files to `frontend/out` and served by FastAPI at `/app`.
- **Integrations:**
  - **Sarvam AI:** Outbound calling API, Chat completions LLM (for transcript evaluation), Voice Agent Webhook intake.
  - **Google Sheets API:** Service account authentication for lead queue read/write.
  - **Veblika:** WhatsApp Business API for automated message delivery.
  - **SMTP:** Transactional emails (Daily reports, error alerts, password resets, user invitations).
  - **AWS S3 / S3-Compatible (Cloudflare R2):** Private audio recording storage with AWS SigV4 signed requests.

### Project Layout
```
didm-automation/
├── app/
│   ├── main.py              # Automation routes, mounts SaaS API (/api/v1) and Next.js static app (/app)
│   ├── server.py            # Uvicorn entry point
│   ├── config.py            # Pydantic environment configuration and validation
│   ├── db.py                # Database engine, session factories, automation ORM models
│   ├── service.py           # Core dialler engine, Google Sheets sync, Veblika WhatsApp sender
│   ├── leads.py             # Google Sheet lead queue parsing and outcome updating
│   ├── integrations.py      # Sarvam, Veblika, Google Sheets & Mailer API clients
│   ├── webhooks.py          # Durable webhook intake, retry queue, background worker
│   ├── security.py          # IP extraction, in-memory rate limiting, sensitive data log redaction
│   ├── migrate.py           # Advisory-locked Alembic migration runner
│   └── saas/                # Full Training SaaS package:
│       ├── models.py        # All SaaS SQLAlchemy models (Tenants, Users, Sessions, Rubrics, etc.)
│       ├── auth.py          # Cookie sessions, CSRF double-submit validation, org tenant isolation
│       ├── permissions.py   # RBAC permission matrix and enforcement
│       ├── passwords.py     # scrypt password hashing, secure token generation
│       ├── agents.py        # Agent registry, immutability, versioning, scenarios, team assignments
│       ├── training.py      # Training session state machine, capacity locks, provider result processing
│       ├── training_api.py  # Endpoints for practice sessions, phone numbers, trainee my-training
│       ├── intelligence.py  # Transcripts, LLM rubric evaluation, anti-hallucination quote check, reconcile
│       ├── intelligence_api.py # Scorecard endpoints, rubric management, recording playback
│       ├── recordings.py    # Recording download, validation, retention, and deletion
│       ├── s3store.py       # Zero-dependency AWS SigV4 S3-compatible client
│       ├── retention.py     # Automated data retention, anonymization, and legal hold engine
│       ├── analytics.py     # SQL-aggregated analytics and CSV export
│       ├── readiness.py     # Health, readiness (/readyz), and diagnostic checks (/admin/readiness)
│       └── cli.py           # CLI tool to create the initial platform admin
├── frontend/                # Next.js TypeScript Web Application
│   ├── src/
│   │   ├── app/             # App router pages (login, dashboard, agents, rubrics, training, analytics, etc.)
│   │   ├── components/      # UI components (AppShell, Tables, Forms, Scorecards, Rubrics, Modals)
│   │   └── lib/             # API client, session context, types, roles, intelligence utilities
├── migrations/              # Alembic revisions (0001 through 0007)
├── tests/                   # 7 full test suites (unit, concurrency, tenant isolation, mocked APIs)
└── docs/                    # Architecture documents, feasibility reports, and deployment guides
```

---

## 3. What Has Been Built (Phase-by-Phase Breakdown)

### Phase 0: The Original Admission Call Dialer
- Replaced Make.com dialer scenario.
- Reads `Queue` from Google Sheets: filters leads (Call = YES, max 3 attempts, 2 hours apart, skips Do-Not-Call).
- Initiates outbound calls via Sarvam AI API using prompt/agent Ananya.
- Receives call outcome webhook, maps outcome (Connected, Busy, No Answer, etc.), updates Google Sheets row.
- Triggers Veblika WhatsApp template once per lead.
- Safety: Only calls between 9 AM to 9 PM IST, daily call cap, global stop button, batch concurrency limit.
- Daily summary email report sent at 9:15 PM IST.

### Phase 0.5: Webhook Hardening & Idempotency
- **Durable Webhook Ingestion:** All incoming Sarvam / event webhooks are immediately persisted to `webhook_events` table before processing.
- **Workers:** Switchable mode (`inline` or `queued` with background worker threads).
- **Exponential Backoff:** Failed webhooks automatically retry (30s, 60s, 120s up to 30 mins); dead-letter queue after max attempts with manual retry API.
- **Strict Idempotency:**
  - Call attempts updated with conditional SQL (`WHERE state != 'done'`).
  - WhatsApp sends claim-guarded via `whatsapp_claims` table with unique `(phone, kind)` constraint.
- **Lock Separation:** Automation dialer lock decoupled from webhook and WhatsApp processing.

### Phase 1: SaaS Multi-Tenancy & Identity Foundation
- **Multi-Tenant Architecture:** Complete logical isolation by `organization_id`.
- **Identity & Auth:**
  - Password hashing with standard library `scrypt` (N=32768, r=8, p=3).
  - Secure, `HttpOnly`, `SameSite=Lax` cookie sessions (`didm_session`) with 72-hour TTL.
  - CSRF protection via double-submit `didm_csrf` cookie + `X-CSRF-Token` header validated against session hash.
  - Secure password reset token email flow.
  - Invitation workflow with token fragments (`#token=...`) so tokens are never exposed in server logs.
- **Role-Based Access Control (RBAC):**
  - Roles: `platform_admin`, `organization_owner`, `organization_admin`, `trainer`, `trainee`.
  - Server-side dependency `org_access(permission)` ensures users only see their own organization's data. Cross-tenant IDs yield 404 (anti-enumeration).
- **Audit Logging:** Every administrative action, invite, role change, and deletion is recorded in `audit_events`.
- **Rate Limiting:** In-memory sliding-window rate limiters for login, reset, and invitations.

### Phase 2: Voice Agent Registry & Team Assignments
- **Agent Registry:** Admins link Sarvam Voice Agent App IDs (no vendor secrets stored in agent records).
- **Strict Versioning:**
  - Version numbering (1, 2, 3...) with at most one active draft.
  - Variable schema validation (types: string, number, integer, boolean, enum; max 50 variables).
  - **Immutability:** Once published, versions are permanently immutable (guarded by ORM hooks and check constraints).
- **Scenarios:** Practice scenarios linked to agents, defining specific customer personas and variables.
- **Teams & Entitlement Resolver:**
  - Trainees can be assigned agents/scenarios directly OR via Teams.
  - `entitlements()` resolution engine computes unions of allowed scenarios, taking the most generous session limits and latest expiration dates.

### Phase 3: Training Sessions & Execution Engine
- **Session State Machine:** `requested` → `preparing` → `connecting` → `active` → `completed` (or `failed`, `cancelled`, `timed_out`).
- **Atomic Capacity Locks:**
  - PostgreSQL transaction-level advisory locks (`pg_advisory_xact_lock`) prevent quota and concurrency races across distributed instances.
  - Enforces platform global concurrency, organization concurrent limits, user daily limits, and monthly minute quotas.
- **Phone Channel Execution:**
  - Trainees must have an admin-verified phone number (`memberships.verified_phone_e164`).
  - Server invokes Sarvam outbound call targeting trainee's phone with session-pinned agent version.
  - Webhook URL contains a dedicated secret path plus SHA-256 HMAC token (`sig = HMAC(org_id:session_id)`) to prevent webhook spoofing.
- **Sweeper:** Scheduled background job cleans up stuck sessions (unstarted calls fail after timeout; calls running past max duration are timed out).
- **Browser Voice Channel:** Foundation implemented (`SarvamWebAuth` signed URL generation), but **deliberately kept OFF** due to security/SDK verification blockers (detailed in docs).

### Phase 4: Training Intelligence & AI Evaluation
- **Async Post-Call Pipeline:** As soon as a practice call completes, jobs are created in `evaluation_jobs`:
  1. `transcript`: Extracts turn-by-turn dialogue (`agent` vs `trainee`) from Sarvam webhook payload or analytics API.
  2. `evaluation`: Evaluates performance using LLMs.
  3. `recording`: Fetches and stores audio recording (if enabled).
  4. `reconcile`: Reconciles late or missing provider callbacks against Sarvam analytics.
- **Rubric-Based Evaluation Engine:**
  - Admins/Trainers build weighted scoring rubrics (1–12 criteria, 0–10 scale, custom evaluation instructions).
  - Evaluator calls **Sarvam Chat Completion LLM** with a strict JSON schema.
  - **Anti-Hallucination & Prompt Injection Defense:**
    - Fenced and escaped transcript data.
    - System verifies that every quote cited by the LLM as evidence *actually exists verbatim* in the trainee's transcript turns. Non-existent quotes are discarded.
    - Score is calculated deterministically on the backend from criteria weights, never blindly trusted from the LLM.
    - Handles `insufficient_evidence` when trainee spoke fewer than required turns or under 20 words.
- **Reconciliation Engine:**
  - Matches late-arriving provider events or polls Sarvam attempt records.
  - Adjusts quota discrepancies without altering immutable session records (`training_usage_adjustments`).

### Phase 5: Production Readiness, S3 Storage, Retention & Analytics
- **Zero-Dependency S3 Client (`app/saas/s3store.py`):**
  - Full AWS Signature Version 4 (SigV4) implementation over `httpx`.
  - Supports AWS S3, Cloudflare R2, MinIO, or Ceph without heavy `boto3` dependencies.
  - Content-MD5 and SHA-256 verification on upload; generates 5-minute presigned playback URLs.
- **Evaluator Cost & Budget Controls:**
  - Tracks token usage in `evaluation_usage`.
  - Strict caps: Per-session rubric call limit, monthly organization token & cost budgets, daily platform budget ceiling.
- **Automated Data Retention & Legal Hold (`app/saas/retention.py`):**
  - Nightly job (03:30 AM) purges old transcripts, deletes expired S3 audio files, redacts sensitive webhook payloads, and clears temporary tokens.
  - **Legal Hold:** Org admins can toggle a legal hold on an organization to halt all retention purges immediately.
  - Default mode: `RETENTION_ENFORCEMENT_ENABLED=false` (report-only mode so existing data is never wiped unexpectedly).
- **SQL Aggregated Analytics:**
  - Computes practice time, score distributions (0-39, 40-59, etc.), skill strengths/weaknesses, and participation rates entirely in SQL.
  - Trainee performance CSV export protected against CSV formula-injection (sanitizes `=, +, -, @`).
- **Readiness & Health System:**
  - `/healthz`: Lightweight liveness probe for load balancer.
  - `/readyz`: Verifies database connection and checks Alembic migrations are at `head`.
  - `/admin/readiness`: Deep inspection endpoint showing queue lengths, dead jobs, scheduler status, worker health, and configuration warnings.
- **Concurrency-Safe Migrations:**
  - Alembic migrations at startup use PostgreSQL advisory locks so multiple restarting pods do not race.

### Frontend (Next.js TypeScript Application)
Located in `frontend/`, compiles to static HTML/JS and is served at `/app`:
- **Auth:** Login, Password Reset request and completion, Invitation onboarding.
- **Platform Management:** Organization list, Org limits editor, System Health monitor.
- **Organization Admin:** Members list, Invitation sender, Teams manager, Audit log viewer.
- **Voice Agents:** Agent list, Version publisher, Variable schema builder, Scenario manager.
- **Assignments:** Trainee and team assignment manager with date and session limit controls.
- **Training (Trainee):**
  - "My Training" portal: Browse assigned agents/scenarios, view remaining quota.
  - Practice call launcher: Practice-call notice acceptance, recording consent checkbox, live call status polling.
  - Trainee session history & progress scorecard.
- **Evaluation & Rubrics:** Rubric builder with criterion weight sliders, Scorecard with audio player, turn-by-turn dialogue viewer, and AI feedback.
- **Analytics:** Interactive score distribution charts, skill mastery bars, team filters, and CSV export.
- **Settings:** Practice call disclaimer setup, recording consent policy, retention report, legal hold toggle.

---

## 4. Database Schema Summary (Alembic Migrations)

| Migration | Key Tables Created | Details |
|---|---|---|
| `0001_baseline` | `call_attempts`, `whatsapp_messages`, `batches`, `alerts`, `settings` | Preserves existing dialer tables without altering live rows. |
| `0002_webhook_events` | `webhook_events`, `whatsapp_claims` | Durable intake store, dead-letter queue, WhatsApp deduplication claims. |
| `0003_identity` | `organizations`, `users`, `memberships`, `invitations`, `auth_sessions`, `password_reset_tokens`, `audit_events` | Multi-tenant auth, session tokens, audit logging. |
| `0004_agents` | `teams`, `team_members`, `agents`, `agent_versions`, `training_scenarios`, `agent_assignments` | Voice agent catalog, immutable versions, assignment rules. |
| `0005_training` | `training_org_limits`, `training_sessions`, `training_session_events`, `training_usage_events`, `training_usage_reservations`, `browser_session_tokens` | Training state machine, quota reservations, phone verification metadata. |
| `0006_intelligence` | `evaluation_rubrics`, `evaluation_rubric_versions`, `training_org_settings`, `training_transcripts`, `training_transcript_turns`, `training_recordings`, `training_evaluations`, `evaluation_jobs`, `training_usage_adjustments`, `phone_verification_challenges` | Rubrics, post-call queues, transcripts, AI evaluations, reconciliation. |
| `0007_production` | `evaluation_usage`, `retention_runs` + audit & retention columns | S3 recording tracking, token cost metering, retention runs, legal hold. |

---

## 5. Security, Isolation & Safety Architecture

1. **Tenant Isolation:** Every route validates that the requesting session belongs to the URL's `organization_id`. `scoped_get` ensures resource IDs belonging to other tenants return 404 (preventing IDOR and resource scanning).
2. **Double-Submit CSRF:** Cookie `didm_csrf` must match header `X-CSRF-Token`, cross-checked against the server session record.
3. **Log Sanitization:** Sensitive query parameters (`?token=`), webhook path secrets, passwords, and phone numbers are automatically redacted from console logs.
4. **Race-Condition Safety:** Critical paths (lead dialing, session quota reservation, version publishing, webhook claims, job claims) use atomic database constraints or advisory locks.
5. **Prompt Injection & AI Guardrails:** Student dialogue cannot inject instructions into LLM evaluation prompts; evidence citations must match transcript turn text.
6. **Feature Isolation:** The legacy lead dialer and the new SaaS code run in the same process and database, but share **zero tables** and **zero routes**.

---

## 6. Current Operational Status & Feature Flags

| Feature | State | Why / Notes |
|---|---|---|
| **Lead Dialer Automation** | Active / Production-Ready | Can run in `DRY_RUN=true` (test mode) or `DRY_RUN=false` (live). |
| **SaaS Identity & Roles** | Active / Fully Tested | Multi-tenant login, session cookies, invitations working. |
| **Agent & Scenario Registry** | Active / Fully Tested | Agents link to Sarvam App IDs; versioning is immutable. |
| **Phone Training Practice** | Active (Flagged: `TRAINING_PHONE_ENABLED`) | Disabled by default in dev until enabled in environment. |
| **AI LLM Evaluation** | Active (Flagged: `EVALUATOR_PROVIDER=sarvam`) | Requires `SARVAM_CHAT_API_KEY`. Off by default. |
| **S3 Audio Storage** | Implemented (Flagged: `RECORDING_STORE=s3`) | Requires S3 bucket & credentials. Off by default. |
| **Data Retention Purging** | Report Mode (`RETENTION_ENFORCEMENT_ENABLED=false`) | Only logs counts by default; does not delete until switched on. |
| **Browser Voice Channel** | **DISABLED / NO-GO** (`TRAINING_BROWSER_ENABLED=false`) | Sarvam Web SDK has client-side security leaks (client can override variables, exposes signed URL in console). Phone channel is the approved method. |

---

## 7. How to Run & Test Locally

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt

# 2. Configure environment
cp .env.example .env
export COOKIE_SECURE=false ADMIN_TOKEN=dev WEBHOOK_SECRET=dev

# 3. Start backend (auto-applies Alembic migrations to SQLite)
uvicorn app.server:app --reload

# 4. Create initial platform admin user
python -m app.saas.cli create-platform-admin --email admin@example.com --name "Platform Admin"

# 5. Run tests (100% mocked, no external API calls)
pytest

# 6. Run Next.js frontend
cd frontend
npm ci
npm run dev   # Runs on http://localhost:3000/app
```

---

## 8. Summary for ChatGPT: What You Can Ask Next

When working with ChatGPT on this codebase, you can ask for assistance on:
- Writing new API endpoints or enhancing existing SaaS features.
- Extending frontend UI pages in `frontend/src/app`.
- Adding new evaluation models or rubric metrics.
- Setting up production deployment on Render, AWS, or Docker.
- Designing an automated OTP phone verification provider (Twilio, SMS, or WhatsApp).
- Creating test cases or debugging specific background worker behavior.

# DIDM SaaS — Final Phone Pilot Readiness Assessment

**Date:** 2026-10-31  
**Target Environment:** Neon PostgreSQL (`neondb`) / Production SaaS Platform  
**Organization:** DIDM (`didm` - `439799da-8a8e-4ff9-a490-7ffcfcd65564`)  
**Trainee:** `demotrainee@didm.in` (`428d4ec0-8336-40f6-acb5-6daa86744540`)

---

## 1. Executive Summary & Verdict

### Final Verdict: **APPROVAL REQUIRED**

The primary security concern regarding Neon database encryption has been thoroughly investigated and resolved with definitive proof: **the application connection to Neon PostgreSQL is fully encrypted with TLSv1.3 and SCRAM channel binding.**

All technical subsystems (FastAPI backend, Alembic migrations, database models, RBAC authentication, and Sarvam phone adapter) are healthy and operating as expected. To transition from the current state to a live single-call pilot, three administrative approvals / actions are required from the user.

---

## 2. 11-Point Readiness Verification Matrix

| # | Dimension | Status | Live Evidence / Verification |
|---|---|---|---|
| **1** | **Actual Neon Connection TLS** | **VERIFIED (Active)** | `libpq.PQsslInUse = True`, `protocol = TLSv1.3`, `cipher = TLS_AES_256_GCM_SHA384`, `channel_binding = require`. Non-TLS rejected by Neon edge. |
| **2** | **Database Target Identity** | **VERIFIED** | Database: `neondb`, User: `neondb_owner`, Engine: `PostgreSQL 18.6`, Alembic revision: `0008_recording_providers`. |
| **3** | **Organization Training Enabled** | **APPROVAL REQUIRED** | Currently `false` because `training_org_limits` row is not yet inserted. Proposed settings ready. |
| **4** | **Phone Practice Enabled** | **APPROVAL REQUIRED** | Evaluates `false` at org level pending limits row insertion. Platform engine adapter is ready. |
| **5** | **Browser Practice Disabled** | **VERIFIED (Disabled)** | `TRAINING_BROWSER_ENABLED=false`. Availability API returns `browser.available=false`. |
| **6** | **Trainee Phone Verified** | **ACTION REQUIRED** | Trainee self-saved `+918744045668` on `users.phone_e164`. Awaiting authorized owner confirmation. |
| **7** | **Sarvam Agent Published** | **APPROVAL REQUIRED** | Genuine Sarvam App ID & Version 7 present in trusted configuration. Registration payload prepared. |
| **8** | **Assignment Active** | **APPROVAL REQUIRED** | 0 assignments currently exist. Conservative single-session assignment payload prepared. |
| **9** | **Quotas Available** | **APPROVAL REQUIRED** | Will provide 1 session/day, 10 min max duration, 1 concurrent session upon limits approval. |
| **10** | **Cloudflare Webhook Origin** | **CONFIGURED** | `PUBLIC_BASE_URL=https://fourth-bit-attitude-funeral.trycloudflare.com` configured on server. |
| **11** | **Platform phone_channel_live** | **VERIFIED (True)** | `engine.phone_available() == True` (Sarvam outbound calling adapter live and ready). |
| **12** | **Trainee phone.available** | **CURRENTLY FALSE** | Authenticated `/training/availability` returns `phone.available=false`, awaiting limits and verification. |

---

## 3. Authenticated API Verification Evidence

We executed an authenticated test against the live backend and database using trainee `demotrainee@didm.in`'s credentials:

### `GET /api/v1/auth/me`
```json
{
  "user": {
    "id": "428d4ec0-8336-40f6-acb5-6daa86744540",
    "email": "demotrainee@didm.in",
    "name": "demotraineee",
    "status": "active",
    "is_platform_admin": false
  },
  "memberships": [
    {
      "membership_id": "1e78145d-d0b7-43d6-bbd0-bb33b9c3c2b4",
      "organization": {
        "id": "439799da-8a8e-4ff9-a490-7ffcfcd65564",
        "name": "DIDM",
        "slug": "didm",
        "status": "active"
      },
      "role": "trainee",
      "permissions": ["org.view", "training.self"]
    }
  ],
  "active_organization_id": "439799da-8a8e-4ff9-a490-7ffcfcd65564"
}
```

### `GET /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/training/availability`
```json
{
  "enabled": false,
  "phone": {
    "available": false,
    "phone_on_file": "******5668",
    "phone_verified": false
  },
  "browser": {
    "available": false,
    "reason": "Browser voice is waiting for the Sarvam Web SDK to be verified."
  },
  "max_session_minutes": 10,
  "recording": {
    "available": false,
    "consent_version": null,
    "consent_text": "",
    "retention_days": 30
  },
  "practice_notice": null
}
```

---

## 4. Remaining Actions & Approvals Required

To achieve **READY FOR APPROVED SINGLE-CALL PILOT**, please review and grant approval for the following 3 steps:

### Approval 1: Apply Conservative Organization Limits
- **Action:** Platform Admin updates DIDM limits.
- **Parameters:**
  - `enabled`: `true`
  - `phone_enabled`: `true`
  - `browser_enabled`: `false`
  - `max_concurrent_sessions`: `1`
  - `max_concurrent_per_user`: `1`
  - `max_sessions_per_user_per_day`: `1`
  - `max_session_minutes`: `10`
  - `monthly_minutes`: `60`
  - `evaluation_enabled`: `false`
  - `recording_allowed`: `false`

### Approval 2: Confirm Trainee Phone Number
- **Action:** Organization Owner confirms trainee number.
- **Trainee Number on File:** `+918744045668` (demotraineee)
- **Endpoint:** `POST /api/v1/organizations/{org_id}/members/1e78145d-d0b7-43d6-bbd0-bb33b9c3c2b4/verify-phone`

### Approval 3: Register Sarvam Agent and Create Assignment
- **Action:** Organization Owner registers Ananya voice agent.
- **App ID:** Confirmed from trusted `.env` (25 characters).
- **Version:** `7` (Phone channel enabled).
- **Assignment Settings:** `max_sessions = 1`, `max_minutes_per_session = 10`, 48-hour expiration.

---

## 5. Safe Pilot Execution Protocol

Once Approvals 1–3 are granted and executed:
1. The authenticated `/training/availability` endpoint will reflect:
   - `enabled = true`
   - `phone.phone_verified = true`
   - `phone.available = true`
2. The trainee will see the agent listed under `/my/agents`.
3. **Guardrail Enforced:** We will stop immediately before initiating the call (`POST /training/sessions`), present the final readiness confirmation, and request explicit authorization for the single test phone call.


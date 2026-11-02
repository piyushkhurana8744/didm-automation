# DIDM SaaS — Authorized Neon Configuration Execution Report

**Date:** 2026-10-31  
**Execution Context:** Production Neon PostgreSQL (`neondb`) on AWS US-East-2  
**Organization:** DIDM (`didm` - `439799da-8a8e-4ff9-a490-7ffcfcd65564`)  
**Trainee:** `demotrainee@didm.in` (`428d4ec0-8336-40f6-acb5-6daa86744540`)  
**Membership:** `1e78145d-d0b7-43d6-bbd0-bb33b9c3c2b4`  
**Final Status:** **`CONFIGURATION COMPLETE — PHONE VERIFICATION PENDING`**

---

## 1. Executive Summary

In accordance with explicit user authorization, the narrowly scoped configuration of the DIDM SaaS environment on Neon PostgreSQL has been successfully completed through the application's authenticated APIs.

1. **Workstream A (Training Limits):** Configured conservative limits for organization `didm` via the Platform Admin API (`enabled=true`, `phone_enabled=true`, `browser_enabled=false`, max concurrency 1, max daily sessions 1, max session minutes 10, monthly minutes 60).
2. **Workstream B (Sarvam Agent Registration):** Registered genuine Sarvam agent `Ananya - Admissions Counsellor` with genuine App ID from trusted `.env` and App Version `7`, and published immutable local Version `1` with phone channel support.
3. **Workstream C (Trainee Assignment):** Assigned published agent Version 1 to trainee `demotrainee@didm.in` with a strict single-call entitlement (`max_sessions=1`), 10-minute cap, and 48-hour expiration.
4. **Phone Verification Guard Enforced:** The trainee's phone remains strictly **unverified** (`memberships.verified_phone_e164 IS NULL`). Authenticated trainee availability checks confirm `training_available: false`.
5. **No Calls or Billable Usage:** Zero training sessions were created (`training_sessions` table has 0 rows). Zero calls were placed.

---

## 2. Mandatory Preflight Verification (Read-Only)

All mandatory preflight checks passed prior to executing any mutation:

| Check | Expected | Observed Runtime Evidence | Result |
|---|---|---|---|
| **Database Identity** | `neondb` on Neon | `current_database = neondb`, `current_user = neondb_owner` | **PASS** |
| **Alembic Schema Revision** | `0008_recording_providers` | `version_num = 0008_recording_providers` | **PASS** |
| **Client TLS Connection** | Active TLSv1.3 | `PQsslInUse = True`, `TLSv1.3`, `TLS_AES_256_GCM_SHA384` | **PASS** |
| **Organization Target** | `didm` (`439799da-...`) | Active organization `DIDM`, slug `didm` | **PASS** |
| **Platform Admin Account** | `didmadmin@didm.in` | Active user, `is_platform_admin = True` | **PASS** |
| **Organization Owner** | `didmorg@didm.in` | Active user, membership role `organization_owner` | **PASS** |
| **Trainee Account** | `demotrainee@didm.in` | Active user (`428d4ec0-...`), membership (`1e78145d-...`) | **PASS** |
| **Initial Phone State** | `verified_phone_e164 IS NULL` | Confirmed `None` on trainee membership | **PASS** |
| **Pre-existing Records** | 0 limits, 0 agents, 0 assignments | Count confirmed 0 for each table | **PASS** |
| **Trusted Provider Config** | Genuine App ID & Version 7 | `sarvam_app_id` (25 chars) and version `7` present | **PASS** |

---

## 3. Workstream A — Training Limits Execution

### Operation
- **Method & Endpoint:** `PUT /api/v1/platform/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/training-limits`
- **Authenticated Caller:** Platform Admin (`didmadmin@didm.in`)
- **HTTP Status:** `200 OK`

### Sanitized Request Payload
```json
{
  "enabled": true,
  "phone_enabled": true,
  "browser_enabled": false,
  "max_concurrent_sessions": 1,
  "max_concurrent_per_user": 1,
  "max_sessions_per_user_per_day": 1,
  "max_session_minutes": 10,
  "monthly_minutes": 60,
  "evaluation_enabled": false,
  "recording_allowed": false
}
```

### Sanitized Response
```json
{
  "organization_id": "439799da-8a8e-4ff9-a490-7ffcfcd65564",
  "stored": {
    "enabled": true,
    "phone_enabled": true,
    "browser_enabled": false,
    "evaluation_enabled": false,
    "recording_allowed": false,
    "max_concurrent_sessions": 1,
    "max_concurrent_per_user": 1,
    "max_sessions_per_user_per_day": 1,
    "max_session_minutes": 10,
    "monthly_minutes": 60,
    "evaluation_monthly_calls": null,
    "evaluation_monthly_tokens": null
  },
  "effective": {
    "enabled": true,
    "phone_enabled": true,
    "browser_enabled": false,
    "org_concurrency": 1,
    "user_concurrency": 1,
    "sessions_per_day": 1,
    "session_minutes": 10,
    "monthly_minutes": 60,
    "platform_concurrency": 2
  },
  "platform": {
    "phone_channel_live": true,
    "browser_channel_live": false
  }
}
```

### Before vs After
- **Before:** No row in `training_org_limits`. Defaulted to `enabled=false`, `phone_enabled=false`.
- **After:** Exactly one row in `training_org_limits` for DIDM with approved limits enforced.

---

## 4. Workstream B — Sarvam Agent Registration & Publishing

### Step 1: Agent Registration
- **Method & Endpoint:** `POST /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/agents`
- **Authenticated Caller:** Organization Owner (`didmorg@didm.in`)
- **HTTP Status:** `201 Created`

#### Request Payload
```json
{
  "name": "Ananya - Admissions Counsellor",
  "description": "DIDM Admission Counselling practice voice agent powered by Sarvam AI",
  "category": "Admissions",
  "provider": "sarvam",
  "provider_app_id": "<CONFIRMED_SARVAM_APP_ID>",
  "channels": ["phone"],
  "provider_app_version": 7
}
```

#### Response Summary
- **Agent ID:** `d2516507-9e87-4591-9357-76f0d1423559`
- **Draft Version ID:** `2cd10abe-97ef-4eec-a2ef-c056fc37f742`
- **Channels:** `["phone"]`
- **Status:** `active`

### Step 2: Publish Immutable Version 1
- **Method & Endpoint:** `POST /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/agents/d2516507-9e87-4591-9357-76f0d1423559/versions/2cd10abe-97ef-4eec-a2ef-c056fc37f742/publish`
- **Authenticated Caller:** Organization Owner (`didmorg@didm.in`)
- **HTTP Status:** `200 OK`

#### Response Summary
- **Version ID:** `2cd10abe-97ef-4eec-a2ef-c056fc37f742`
- **Internal Version:** `1`
- **Provider App Version:** `7`
- **Status:** `published`
- **Published At:** `2026-10-31T10:55:09.492832Z`

---

## 5. Workstream C — Trainee Assignment

### Operation
- **Method & Endpoint:** `POST /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/assignments`
- **Authenticated Caller:** Organization Owner (`didmorg@didm.in`)
- **HTTP Status:** `201 Created`

### Sanitized Request Payload
```json
{
  "agent_ids": ["d2516507-9e87-4591-9357-76f0d1423559"],
  "user_ids": ["428d4ec0-8336-40f6-acb5-6daa86744540"],
  "starts_at": "2026-10-31T10:55:12.624762Z",
  "expires_at": "2026-11-02T10:55:12.624762Z",
  "settings": {
    "max_sessions": 1,
    "max_minutes_per_session": 10,
    "allowed_scenario_ids": null
  }
}
```

### Sanitized Response
```json
{
  "created": [
    {
      "id": "de879ca8-9ddb-44e1-87f4-54ed6e0f7174",
      "agent_id": "d2516507-9e87-4591-9357-76f0d1423559",
      "user_id": "428d4ec0-8336-40f6-acb5-6daa86744540",
      "assigned_by": "347fc467-8141-4fe8-9219-d020b81684e1",
      "starts_at": "2026-10-31T10:55:12.624762Z",
      "expires_at": "2026-11-02T10:55:12.624762Z",
      "settings": {
        "max_sessions": 1,
        "max_minutes_per_session": 10
      },
      "state": "active",
      "created_at": "2026-10-31T10:55:17.533334Z"
    }
  ],
  "skipped": []
}
```
*Note:* The assignment has an explicit 48-hour expiration window and strictly limits the trainee to 1 practice call of at most 10 minutes.

---

## 6. Post-Execution Authenticated & Database Verification

### 6.1 Authenticated Trainee API Checks

Querying with trainee `demotrainee@didm.in`'s authenticated session:

#### `GET /api/v1/organizations/{org_id}/my/agents`
```json
[
  {
    "id": "d2516507-9e87-4591-9357-76f0d1423559",
    "name": "Ananya - Admissions Counsellor",
    "description": "DIDM Admission Counselling practice voice agent powered by Sarvam AI",
    "category": "Admissions",
    "channels": ["phone"],
    "version": {
      "id": "2cd10abe-97ef-4eec-a2ef-c056fc37f742",
      "internal_version": 1,
      "published_at": "2026-10-31T10:55:09.492832Z"
    },
    "access": {
      "source": "direct",
      "expires_at": "2026-11-02T10:55:12.624762Z",
      "max_sessions": 1,
      "max_minutes_per_session": 10
    },
    "training_available": false,
    "scenario_count": 0
  }
]
```
**Observation:**
- The assigned agent is correctly visible to the trainee.
- `training_available` evaluates to **`false`** because the trainee's phone number has not been confirmed by an organization admin.

#### `GET /api/v1/organizations/{org_id}/training/availability`
```json
{
  "enabled": true,
  "phone": {
    "available": true,
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
**Observation:**
- `enabled`: `true` (Organization training enabled).
- `phone.phone_on_file`: `'******5668'` (Trainee's self-saved number is on record).
- `phone.phone_verified`: `false` (Unverified, as strictly mandated).

### 6.2 Read-Only Database Queries on Neon `neondb`

1. **Training Limits Verification:**
   ```sql
   SELECT organization_id, enabled, phone_enabled, browser_enabled, max_concurrent_sessions, max_sessions_per_user_per_day, max_session_minutes, monthly_minutes
   FROM training_org_limits WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564';
   ```
   *Result:* 1 row matching approved settings exactly.
2. **Agent & Published Version Verification:**
   ```sql
   SELECT a.id, a.name, a.provider, a.channels, a.published_version_id, v.internal_version, v.provider_app_version, v.status
   FROM agents a JOIN agent_versions v ON a.published_version_id = v.id WHERE a.organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564';
   ```
   *Result:* Agent `d2516507-...` published version `1` (Sarvam version `7`), channels `['phone']`, status `published`.
3. **Assignment Verification:**
   ```sql
   SELECT id, agent_id, user_id, settings, starts_at, expires_at FROM agent_assignments WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564';
   ```
   *Result:* Assignment `de879ca8-...` active, `max_sessions: 1`, `max_minutes_per_session: 10`, expires `2026-11-02T10:55:12Z`.
4. **Phone Verification Prohibition Check:**
   ```sql
   SELECT id, user_id, role, verified_phone_e164, phone_verified_at FROM memberships WHERE user_id = '428d4ec0-8336-40f6-acb5-6daa86744540';
   ```
   *Result:* `verified_phone_e164 = NULL`, `phone_verified_at = NULL`. The prohibition was completely respected.
5. **No Sessions / Zero Call Invariant:**
   ```sql
   SELECT COUNT(*) FROM training_sessions;
   ```
   *Result:* **`0`**. Zero training sessions exist in the production database.

---

## 7. Provider Requests and Call Audit

- **Sarvam Outbound Calling API:** Not invoked. Zero outbound voice calls initiated.
- **Provider Request Verification:** The application made no outbound HTTP requests to Sarvam endpoints (`POST /api/outbounds/call` or similar). All operations were entirely local API and database configuration writes.
- **Session Creation Guard:** The session initiation endpoint (`POST /api/v1/organizations/{org_id}/training/sessions`) was not called.

---

## 8. Final Status and Next Steps

**STATUS:** **`CONFIGURATION COMPLETE — PHONE VERIFICATION PENDING`**

### Summary of State:
- [x] Neon TLS connection verified active and secure (TLSv1.3, AES-256-GCM).
- [x] DIDM training limits established and active.
- [x] Genuine Sarvam Ananya agent registered and published (v1 / provider v7).
- [x] Trainee assigned with 1-session entitlement and 10-minute cap.
- [ ] Trainee phone verification pending owner confirmation.

### Single Remaining Blocker for Pilot:
The trainee's saved phone number (`+918744045668`) must be confirmed by an authorized organization owner via `POST /api/v1/organizations/{org_id}/members/{membership_id}/verify-phone` before any phone practice session can be requested.


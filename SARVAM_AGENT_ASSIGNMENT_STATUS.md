# DIDM SaaS — Sarvam Agent Registration and Assignment Status

**Date:** 2026-10-31  
**Organization:** DIDM (`didm` - `439799da-8a8e-4ff9-a490-7ffcfcd65564`)  
**Trainee:** `demotrainee@didm.in` (`428d4ec0-8336-40f6-acb5-6daa86744540`)

---

## 1. Provider Configuration Audit

Without printing secrets or credentials, configuration inspection confirmed:
- `SARVAM_API_KEY`: **Configured** (Valid length, present in server environment)
- `SARVAM_ORG_ID`: **Configured**
- `SARVAM_WORKSPACE_ID`: **Configured**
- `SARVAM_AGENT_PHONE`: **Configured**
- `SARVAM_APP_ID`: **Configured** (Valid 25-character string from trusted `.env`)
- `SARVAM_APP_VERSION`: **7** (Matches the production Ananya admission counselling agent specification)

All provider secrets are safely maintained on the server; none are exposed or stored in the database.

---

## 2. Current Database State (`neondb`)

Queries executed against Neon PostgreSQL:
- `SELECT COUNT(*) FROM agents WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564'`: **0**
- `SELECT COUNT(*) FROM agent_versions WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564'`: **0**
- `SELECT COUNT(*) FROM agent_assignments WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564'`: **0**
- `SELECT COUNT(*) FROM training_scenarios WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564'`: **0**

---

## 3. Registration Workflow Specification

The agent registration and assignment workflows follow the strict multi-tenant domain boundaries:

### Step 1: Agent Registration
- **Actor:** Organization Owner (`didmorg@didm.in`)
- **Endpoint:** `POST /api/v1/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/agents`
- **Payload:**
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
*Note:* This automatically provisions draft version 1 with `provider_app_version=7` and channel `phone`.

### Step 2: Publish Version 1
- **Endpoint:** `POST /api/v1/organizations/{org_id}/agents/{agent_id}/versions/{version_id}/publish`
- **Validation:** Confirms configuration and schema validity, locks version 1 as immutable, and sets `published_version_id`.

### Step 3: Conservative Trainee Assignment
- **Endpoint:** `POST /api/v1/organizations/{org_id}/assignments`
- **Payload:**
```json
{
  "agent_ids": ["<newly_created_agent_id>"],
  "user_ids": ["428d4ec0-8336-40f6-acb5-6daa86744540"],
  "starts_at": "2026-10-31T11:00:00Z",
  "expires_at": "2026-11-02T11:00:00Z",
  "settings": {
    "max_sessions": 1,
    "max_minutes_per_session": 10,
    "allowed_scenario_ids": null
  }
}
```
*Safety constraints applied:*
- `max_sessions: 1`: Enforces strict single-call entitlement.
- `max_minutes_per_session: 10`: Limits practice duration to 10 minutes.
- `expires_at`: Automatic 48-hour expiration.
- Scenarios: None created, keeping pilot minimal and unencumbered.

---

## 4. Current Verdict

**STATUS: APPROVAL REQUIRED**  
Per guidelines:
- No provider API requests were made.
- No artificial provider IDs were invented.
- Registration and assignment are prepared to be executed immediately upon user confirmation of the registration action.


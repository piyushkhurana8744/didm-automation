# DIDM SaaS — Organization Training Limits Status and Proposal

**Date:** 2026-10-31  
**Organization:** DIDM (`didm`)  
**Organization ID:** `439799da-8a8e-4ff9-a490-7ffcfcd65564`  
**Database:** `neondb` (PostgreSQL 18.6)

---

## 1. Existing Workflow & Architecture

In DIDM SaaS, training limits are partitioned into:
1. **Platform Settings (Environment):** Defaults configured in `TRAINING_DEFAULT_*` and global concurrency cap `TRAINING_MAX_CONCURRENT_TOTAL=2`.
2. **Organization Limits Table (`training_org_limits`):**
   - Controlled exclusively by Platform Administrators via:
     `PUT /api/v1/platform/organizations/{org_id}/training-limits`
   - Verified via:
     `GET /api/v1/organizations/{org_id}/training/limits` and `GET /api/v1/platform/organizations/{org_id}/training-limits`.

### Current Code Behavior When No Row Exists
In `app/saas/training.py`:
```python
def effective_limits(db: Session, settings, org_id: str) -> EffectiveLimits:
    row = db.get(TrainingOrgLimits, org_id)
    return EffectiveLimits(
        enabled=bool(row and row.enabled),
        phone_enabled=bool(row.phone_enabled) if row else False,
        browser_enabled=bool(row.browser_enabled) if row else False,
        ...
    )
```
Because no row currently exists for DIDM in `training_org_limits`, both `enabled` and `phone_enabled` evaluate to **`false`**.

---

## 2. Current State in `neondb`

Query executed:
```sql
SELECT * FROM training_org_limits WHERE organization_id = '439799da-8a8e-4ff9-a490-7ffcfcd65564';
```
**Result:** `[]` (Empty — 0 rows).

Consequently:
- Organization Training: **DISABLED**
- Phone Practice: **DISABLED**
- Browser Practice: **DISABLED**

---

## 3. Proposed Conservative Limits for Pilot

To safely enable the single-call pilot without risk of unbounded usage or billing surprises, we propose the following configuration:

| Limit Setting | Proposed Value | Description / Safety Rationale |
|---|---|---|
| `enabled` | `true` | Enables training features for the organization |
| `phone_enabled` | `true` | Allows outbound Sarvam voice practice calls |
| `browser_enabled` | `false` | Keeps browser channel disabled (security guideline) |
| `max_concurrent_sessions` | `1` | Strict organization-level concurrency: only 1 call at a time |
| `max_concurrent_per_user` | `1` | Strict user-level concurrency: trainee can only have 1 active call |
| `max_sessions_per_user_per_day` | `1` | Limits trainee to 1 practice call per day |
| `max_session_minutes` | `10` | Caps call duration at 10 minutes maximum |
| `monthly_minutes` | `60` | Conservative organization monthly bucket (1 hour total) |
| `evaluation_enabled` | `false` | Keeps LLM evaluation disabled for pilot |
| `recording_allowed` | `false` | Keeps recording storage disabled for pilot |

---

## 4. Execution API Payload (Ready for Submission upon Approval)

Once approved, the settings will be applied via the existing Platform Admin API:

- **Endpoint:** `PUT /api/v1/platform/organizations/439799da-8a8e-4ff9-a490-7ffcfcd65564/training-limits`
- **Method:** `PUT` (Authenticated as Platform Admin: `didmadmin@didm.in`)
- **Body:**
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

---

## 5. Current Verdict

**STATUS: APPROVAL REQUIRED**  
Per instructions ("Request approval before changing organization limits"), no direct SQL modification or API update has been executed yet. Awaiting explicit user confirmation to apply these proposed limits.


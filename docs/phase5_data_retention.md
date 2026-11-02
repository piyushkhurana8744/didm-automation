# Phase 5: data retention and consent

*Written 2026-10-21. Code: `app/saas/retention.py`, settings in `training_org_settings`, runs in `retention_runs`.*

## How it works

One job runs daily at 03:30 (server time zone). For each organization it counts what is due in each category, removes it only when allowed, writes one `retention_runs` row, and writes an audit event when anything was removed or failed.

| Category | Due when | What is removed | What stays | Switch |
|---|---|---|---|---|
| Transcripts | Session ended more than `transcript_retention_days` ago (empty: never) | Transcript turns; the quotes and explanations inside that session's evaluations | Scores, coaching feedback, transcript status and counts, usage | Org setting + `RETENTION_ENFORCEMENT_ENABLED` |
| Recordings | `retention_until` passed (1-365 days, default 30) | Audio object in the bucket; the row becomes `deleted` | Row metadata (who, when, size, consent reference) | Always on (see below) |
| Training webhook bodies | Older than `TRAINING_WEBHOOK_PAYLOAD_DAYS` (default 30; 0 keeps) | Raw body (transcript, phone number) replaced by ids and key names | The webhook row and its status | `RETENTION_ENFORCEMENT_ENABLED` |
| Browser authorization metadata | Expired more than `BROWSER_TOKEN_RETENTION_DAYS` ago (30) | The token row (hash, reference id) | Session and its events | `RETENTION_ENFORCEMENT_ENABLED` |
| Phone verification codes | Expired more than `PHONE_CHALLENGE_RETENTION_DAYS` ago (7) | The challenge row (code hash, number) | The membership's verified state | `RETENTION_ENFORCEMENT_ENABLED` |

- **Report first.** With `RETENTION_ENFORCEMENT_ENABLED=false` (the default) the job only counts. Existing production data is never removed by deploying this code. Admins see the counts on the settings page (`GET /training/retention`).
- **Recordings are the exception.** They are deleted on their retention date even in report mode, because that date is what the trainee was told when consenting, and recordings only exist where an organization switched them on. No recordings exist in production today.
- **Legal hold.** An organization admin can set a hold with a reason. While it is on, nothing for that organization is removed, recordings included. Setting and releasing are audited.
- **Idempotent.** Removed items are marked (`purged_at`, `redacted_at`, `deleted`) or gone, so a second run finds nothing.
- **Failures.** A recording the bucket refused to delete stays `stored`, its `delete_attempts` and `last_error` are updated, the run is `partial`, and it is retried next day, up to 5 times.
- **Storage check.** A second daily job checks stored recordings still exist in the bucket with the same size; missing ones are marked failed so nobody gets a broken playback link.
- **Lead calling is untouched.** Webhook bodies from the lead dialler (`sarvam_result`, `event_call`) are not part of this job.

## Consent and notices

- **Recording consent** (Phase 4): the admin's notice text is hashed; the trainee must accept that exact version per session.
- **Practice-call notice** (new): an optional notice shown before every practice call (for example that the call is transcribed and scored by AI). When set, the server refuses to start a session (409 `notice_not_accepted`) unless the trainee sends the current version; nothing is reserved or dialled first. The accepted version is stored on the session.

## Decisions for the product owner

1. **Transcript retention period.** Suggested default: 365 days for training history, or shorter if organizations ask. Currently empty (kept).
2. **When to switch on enforcement.** Suggested: after one week of report-only runs with the counts reviewed.
3. **Webhook body retention.** Suggested: 30 days, which is long enough to debug a delivery.
4. **Who may set a legal hold.** Currently organization admins. Platform admins may also need to be able to.
5. **Notice wording.** The practice-call and recording notices are written by each organization. A platform template may help; it should be checked by legal advice.
6. **Sarvam's own copy.** Sarvam keeps call data until the account owner sets a retention period in its dashboard. Deleting here does not delete there. That setting is the owner's action.
7. **Account deletion.** Removing a trainee's data on request (right to erasure) is not built yet.

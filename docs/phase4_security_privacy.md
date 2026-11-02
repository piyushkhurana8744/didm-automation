# Phase 4: security, privacy and browser voice review

*Written 2026-10-21. Provider facts come from `docs/phase4_sarvam_capabilities.md` and `docs/phase3_sarvam_verification.md`. No live provider call was made.*

## 1. What data we now hold, and who can see it

| Data | Where | Who can read it |
|---|---|---|
| Transcript turns (provider text, English or translated) | `training_transcripts`, `training_transcript_turns` | The trainee who owns the session; `training.view` (trainer and up) in the same organization |
| Evaluations: scores, explanations, quotes, feedback | `training_evaluations` | Same as transcripts |
| Recording metadata | `training_recordings` | Same as transcripts |
| Recording audio | Private object store only, never the database | Through a 5-minute presigned link: the owner, or `recordings.view` (trainer and up). Every playback is audited |
| Provider outcome and usage corrections | `training_sessions` columns, `training_usage_adjustments` | `training.view` |
| Raw webhook bodies (include the transcript and the trainee's phone number) | `webhook_events`, as in Phase 3 | Nobody through the API; operators with database access |
| Phone codes | `phone_verification_challenges`, HMAC of the code only | Nobody |

Every id from a client is loaded with the organization filter (`scoped_get`), so a foreign id answers 404. Tests cover scorecards, playback, analytics, rubrics and settings across two organizations.

## 2. Assumptions to confirm before switching anything on

1. **Consent.** Recording needs a notice written by the organization's admin, and the trainee must tick that exact notice (its hash is stored on the session). We assume a practice call with an AI agent, where the trainee knowingly takes part, needs only this notice. The organization should confirm this with its own legal advice.
2. **Sarvam keeps its own copy.** Sarvam records every connected call and keeps data until the account owner sets a retention period (`docs/phase4_sarvam_capabilities.md`, item 8). Deleting a recording here does not delete Sarvam's copy. Setting a retention period in Sarvam's dashboard is the owner's action.
3. **Evaluator sees the transcript.** With `EVALUATOR_PROVIDER=sarvam`, transcripts go to Sarvam's chat completions API, the same company that already holds them. Choosing another evaluator would send them to a new processor and needs a decision first.
4. **Retention here.** Recordings: 1-365 days, default 30, deleted daily. Transcripts and evaluations are kept as training history; there is no automatic deletion for them yet. `webhook_events` also keeps raw bodies with phone numbers indefinitely, as in Phase 3. Both need a retention decision.
5. **Translated text.** Sarvam's transcript text is English and may be a translation. Scores judge that text, which can lose tone or wording from a Hindi or Hinglish call. The scorecard says so.

## 3. Controls in place

- **Prompt injection:** the transcript is escaped and fenced as data; the rubric and rules sit in the system prompt; the answer must match a strict schema; each score must quote a real trainee turn or it is dropped; the overall score is computed from rubric weights here. A test feeds an injection that a compliant model would follow, and checks that no score survives.
- **No fake scores:** too little conversation gives `insufficient_evidence` without calling the evaluator; invalid output is retried, then stored as `failed`. The database rejects an overall score on any result that is not `completed`.
- **Immutability:** published rubric versions and finished evaluations cannot be updated or deleted (ORM guards, tested).
- **Provider URLs:** only HTTPS on Sarvam's own API host, no IP addresses, no credentials in URLs, no other ports; downloads are capped at 50 MB and must be audio.
- **Storage:** keys are `training/{org}/{session}/{hash}`. A store adapter must keep objects private, encrypt at rest and serve only presigned HTTPS links. None is built in yet.
- **Logs:** structured lines carry ids and codes only. Presigned links and codes are never logged or stored.
- **Audit:** rubric changes, settings changes, playbacks, deletions, re-evaluations, reconciliations and phone verification (with its method).

## 4. Browser voice: reassessment of the Phase 3 blockers

Browser training stays off (`TRAINING_BROWSER_ENABLED=false`). The SDK is still `sarvam-conv-ai-sdk@0.0.42` (2026-03-30), and the docs have not changed on any blocker.

| Blocker | Status on 2026-10-21 | What would resolve it |
|---|---|---|
| Client-controlled agent variables (`interaction_start` carries `agent_variables`, `initial_state_name`, `initial_bot_message`) | Unchanged. No documented server-side lock | Sarvam confirming that the on-start hook overrides client values for web sessions, or a signed-URL option that binds variables. Until then, nothing that affects scoring may be a browser variable |
| Client-controlled identity (`user_identifier` appended after signing) | Unchanged | A live test showing the signature rejects a changed `user_identifier`, or Sarvam confirming it |
| Signed URL printed to the console | Unchanged in 0.0.42 | A newer SDK without the log, or a documented, reviewed patch. Patching the vendored SDK would mean re-applying it on every upgrade and reviewing each release; we have not done that |
| Unknown URL lifetime | Undocumented | Live test: mint one URL and try it after 30 s, 2 min and 10 min |
| Unknown concurrency and billing for web sessions | Undocumented | Live test: one web session, then check the plan's concurrent count and the minutes billed |
| No reconnection | Documented as not supported | Accept it: a dropped session ends; the trainee starts a new one |

## 5. Manual pilot plan (needs your approval; uses billed minutes)

Run on a separate test agent in Sarvam, not a production agent, with one internal tester.

**Phone training, transcript and evaluation (about 3 billed minutes):**
1. Set `TRAINING_WEBHOOK_SECRET`, `TRAINING_PHONE_ENABLED=true`, `TRAINING_PROVIDER_LOOKUPS_ENABLED=true`; enable training for a test organization only, with `max_session_minutes=3`.
2. Start one phone practice to the tester's verified number and talk for about a minute.
3. Check: the session completes, the transcript is imported from the webhook, the turns match what was said, and List attempts returns the same duration.
4. With approval for token spend, set `EVALUATOR_PROVIDER=sarvam` and `SARVAM_CHAT_API_KEY`, switch on evaluation for the test organization, and re-evaluate that one session. Check the scores, quotes and cost on the Sarvam bill.

**Browser voice (about 3 billed minutes, only after the phone pilot):**
1. On a test deployment only, set `TRAINING_BROWSER_ENABLED=true` and enable the browser channel for the test organization.
2. Mint a signed URL and record its lifetime (30 s, 2 min, 10 min).
3. Change `user_identifier` on the URL and confirm whether the connection is refused.
4. Send changed `agent_variables` in `interaction_start` and check whether the agent uses them.
5. Hold one session and check concurrency and billing in Sarvam's dashboard.
6. Switch the flag back off. Browser training is enabled for real only if steps 3 and 4 show the server ignores client values, or Sarvam confirms a lock in writing.

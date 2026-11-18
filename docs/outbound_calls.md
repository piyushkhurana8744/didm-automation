# Sarvam outbound call history

Open **Insights → Outbound calls** (`/app/outbound-calls/`). Owners, organization admins and trainers can review their organization's calls. Trainees cannot access the full business call history. Calling campaigns also links to this page.

The page imports outbound attempts for active Sarvam agents registered under **Agents** with the **phone** channel. Calls can originate in this panel, the Sarvam dashboard or another integration using the same agent. Agents do not need a published local training version for history import. Calls for unregistered agents are not imported; register each agent's Sarvam app ID in the appropriate organization first. The registry prevents linking the same provider app to two organizations.

## Backend connection and rollout

Use the existing backend settings `SARVAM_API_KEY`, `SARVAM_ORG_ID` and `SARVAM_WORKSPACE_ID`. The key must have Analytics API access to the registered agents in that workspace. No frontend secret or new call webhook is required. Do not point external calls at the legacy campaign-result webhook: that handler belongs to locally tracked lead campaigns.

Deploy the backend and rebuilt frontend together. Apply migration `0015_outbound_history` with `python -m app.migrate` before starting the new backend, or use the existing `MIGRATE_ON_START=true` workflow. `npm run build` in `frontend/` produces the static `/app/outbound-calls/` page. Run the existing single-worker scheduler deployment; `create_app(start_scheduler=False)` disables automatic importing as well as other scheduled jobs.

The scheduler checks once per minute. **Sync Sarvam calls** queues an immediate pass; per-agent persisted cooldowns still apply. The browser refreshes history every ten seconds. Initial import covers the previous 30 days. Each pass processes up to five pages of 100 attempts per agent; larger histories resume at the saved offset on subsequent passes, preserving a fixed date window. After that, overlapping incremental windows recover calls across downtime. Old imported rows remain searchable. Pending transcripts are retried separately, including rows outside the incremental date window. Sarvam's Analytics API caches list responses for 60 seconds, so sync is not instantaneous.

## Data and recordings

The database saves attempt/interaction IDs, caller number, timing, status, campaign ID, failure reason, final agent variables, and original/English transcripts. Repeated imports update the same agent/attempt record. Importing never invokes the lead-queue completion handler, sends WhatsApp messages or starts calls. The history page supports agent/status filters, phone/attempt searches, pagination and transcript text downloads.

Recordings are fetched on demand through the backend's authenticated Sarvam recording API and can be played or downloaded. Audio is **not archived in our storage** by this feature; availability depends on Sarvam's processing and retention. Both voices, individual caller/agent channels and original stereo reuse the existing audio player. Unanswered/failed attempts may have no interaction or recording. Transcripts may arrive later than the attempt. New outbound history is separate from the training transcript-retention service.

API keys and provider media URLs never reach the browser. List and recording routes verify the active organization; recording reads are audited and rate limited. Provider auth/rate-limit errors are visible per agent and retried with backoff. Archiving an agent stops new imports while preserving its existing history.

API reference: [Sarvam Analytics](https://docs.sarvam.ai/voice-agents/api/analytics/overview).

Validation uses isolated databases and mocked provider responses; it does not place real calls. Account-level Analytics access and recording availability still need verification after deployment.

# Phase 4: Sarvam Voice Agents Capability Matrix

*Checked on 2026-10-21. This was read-only research. I called no paid API, used no API key and signed up for nothing. Sources: the Markdown versions of docs.sarvam.ai pages (fetched with `curl`, `.md` appended) and the npm registry metadata. This file builds on `docs/phase3_sarvam_verification.md` and does not repeat it except where needed.*

## Status labels

| Label | Meaning |
|---|---|
| **VERIFIED** | Stated on an official docs.sarvam.ai page (URL and quote given). We have not run it. |
| **DOCUMENTED-AMBIGUOUS** | The docs mention it, but the wording leaves a gap or two pages disagree. |
| **UNVERIFIED** | Not found in the docs. Needs Sarvam to confirm or a live test. |
| **UNSUPPORTED** | The docs say it is not offered. |

## Summary table

| # | Topic | Finding (short) | Status |
|---|---|---|---|
| 1 | Attempts lookup | `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/attempts`. `start_datetime` and `end_datetime` are required. Filter with `filter_conditions=[{"field":"attempt_id","operator":"equals","value":"<id>"}]`. | VERIFIED |
| 2 | Interaction detail | `GET .../{app_id}/interactions`, with the same params plus `include_transcript`, `include_forwarded_calls` and `forwarded_only`. There is no get-one-interaction endpoint. `job_id` on an interaction is the `attempt_id`. | VERIFIED (no single GET: UNVERIFIED) |
| 3 | Transcripts | Webhook: `interaction_transcript: [{role, en_text}]`, English or translated. `GET .../transcripts/{interaction_id}` returns `messages: [{turn_id, role, content, language_name}]`. The List interactions option returns `original_transcript` and `translate_transcript` as `[{role, text}]`. There are **no per-turn timestamps**. | VERIFIED (timestamps: UNVERIFIED, absent) |
| 4 | Speaker roles | `agent`/`user` in webhooks and in inline transcripts. `assistant`/`user` in Get transcript. | VERIFIED |
| 5 | Recording | `GET .../recordings/{interaction_id}` returns `audio/wav`, stereo (user on left, agent on right). It needs `X-API-Key`. The list items also carry `audio_url`, which is a dashboard media link. Its signing and TTL are not stated. A signed `recording_url` exists only for forwarded legs. | Endpoint: VERIFIED. `audio_url` signing/TTL: DOCUMENTED-AMBIGUOUS. Consent setting: UNVERIFIED |
| 6 | Pagination | `limit` (1–1000, default 20), `offset`, and the response fields `items`, `total`, `limit`, `offset`, `next_page_uri`, `prev_page_uri` (`""` when there is no page). Responses are cached 60 s. | VERIFIED |
| 7 | Post-call analysis | Output variables (LLM extraction after the call) come back in `agent_variables` / `final_agent_variables`. One goal per agent, shown in the dashboard. There is no summary field and no goal field in the API. | VERIFIED (goal/summary in API: UNVERIFIED) |
| 8 | Data retention | Retention is set per workspace, with a Voice Agents override. The default is "retained indefinitely". Zero retention is "not yet supported for Voice Agents". | VERIFIED |
| 9 | Webhook events | Instant outbound has one POST per completed attempt. There are no other event types and no list/retry endpoint for instant outbound. | VERIFIED (others: UNVERIFIED) |
| 10 | Analytics rate limits | "rate-limited per API key; the limit is configured per organization". The API returns `429` + `Retry-After`. No number is stated. | VERIFIED (numbers: UNVERIFIED) |
| 11 | Auth | `X-API-Key` header. "Bearer tokens are not accepted on these endpoints." No key scopes are documented. Keys belong to a workspace. | VERIFIED (scopes: UNVERIFIED) |
| 12 | Billing per call | There is no cost or billed-minutes field. Only `duration_in_seconds` (and webhook `duration`) exist. Pricing is per 60-second pulse, rounded up. | Field: UNVERIFIED (absent). Rule: VERIFIED |
| 13 | Chat completions | `POST https://api.sarvam.ai/v1/chat/completions`, header `api-subscription-key`, models `sarvam-105b` / `sarvam-105b-conversations`, `response_format` `json_schema` supported. Price ₹15 input / ₹5 cached / ₹60 output per 1M tokens. `sarvam-m` is deprecated. | VERIFIED |
| 14 | SMS/OTP | No SMS or OTP API. | UNVERIFIED (none found) |
| 15 | Web SDK / docs changes | Still `0.0.42` (2026-03-30). There are no doc changes on variable locking, signed URL TTL, reconnection or web billing. | VERIFIED (no change) |

---

## 1. Outbound call attempt lookup (List attempts)

Source: https://docs.sarvam.ai/voice-agents/api/analytics/attempts.md and https://docs.sarvam.ai/voice-agents/api/analytics/overview.md. **VERIFIED**.

**Endpoint.** `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/attempts`. The path has no `orgs/` or `workspaces/` segments. "Analytics is **agent-scoped**: every path carries the `app_id` of one agent."

**Query parameters.**
- `start_datetime` (required) and `end_datetime` (required). "Both are inclusive, and the end must be later than the start. Send ISO 8601 with an offset, such as `2026-10-01T00:00:00+05:30`, and encode the `+` as `%2B`. Without an offset, UTC is assumed."
- `limit` (1–1000, default 20) and `offset` (default 0).
- `sort_by`: one of `attempt_id` (default), `effective_datetime`, `start_datetime`, `end_datetime`, `duration_in_seconds`, `user_identifier`, `ended_by`.
- `sort_order`: `asc` (default) or `desc`.
- `filter_conditions`: a "URL-encoded JSON array of `{field, operator, value}` conditions".

**Filter syntax.**
- "`value` is always a string, even for numbers."
- "Conditions on the same field are ORed; conditions on different fields are ANDed."
- Operators: `equals`, `not_equals`, `includes`, `starts_with`, `ends_with`, `greater_than`, `less_than`, `greater_than_or_equal`, `less_than_or_equal`, `is_empty`, `is_not_empty`. "Use `"null"` to match empty fields."
- Filterable fields:
  - Identifiers: `interaction_id`, `attempt_id`, `job_id`, `user_id`, `user_identifier`, `user_contact_identifier`, `campaign_id`, `cohort_id`.
  - Call details: `language_name`, `channel_type`, `channel_direction`, `channel_protocol`, `channel_provider`, `connectivity_status`, `num_messages`, `duration_in_seconds`.
  - Outcome: `failure_reason`, `end_reason`, `ended_by`, `has_log_issues`, `is_debug_call`.
  - Agent variables: `agent_variables.<key>` and `initial_agent_variables.<key>`.
- "An unknown field returns `422`. Invalid JSON, an unknown operator, or a missing `value` returns `400`."

Lookup for one attempt: `filter_conditions=[{"field":"attempt_id","operator":"equals","value":"<attempt_id>"}]`. The date window is still required. It must cover the attempt.

**Response item fields (`ExternalAttemptsAPIResponse`).** All of them are optional and nullable:
- Identity: `attempt_id`, `interaction_id`, `user_identifier`, `user_contact`, `user_contact_masked`, `user_contact_hashed`.
- Outcome: `connectivity_status` (e.g. `connected`, `no_answer`, `failed`), `failure_reason` (`NO_FAILURE_REASON` when nothing failed), `ended_by` (e.g. `USER_ENDS`, `AGENT_ENDS`, `VOICEMAIL`, `NO_END_REASON`), `next_action_status`.
- Timing: `duration_in_seconds` (double), `start_datetime`, `end_datetime`, `attempted_at`. All are UTC and have no offset.
- Conversation: `language_name`, `num_messages`, `average_agent_response_time_in_seconds`, `average_user_response_time_in_seconds`.
- Channel: `channel_type`, `channel_direction`, `channel_protocol`.
- Campaign: `retry_attempt`, `server_retry_attempt`, `campaign_id`, `cohort_id`.
- Flags: `is_debug_call` and `has_log_issues`. Both are the integers `0`/`1`, "An integer, not a boolean."
- Data: `audio_url` and `agent_variables` (final values).
- `channel_provider`: "**Deprecated.** Always `null`".

Errors: `400`, `401`, `403`, `422`, `429`, `500`, `503`. Each has a `detail` field.

**Example response (from the page):**

```json
{
  "items": [
    {
      "attempt_id": "6d3a9e2f-1b7c-4c58-9f04-8e2b5d7a1c93",
      "interaction_id": "20261007/9f1c2a7e-4b3d-4e8a-a1f0-6c2d9b7e5a14",
      "user_identifier": "LN-2026-004817",
      "user_contact": "+919876543210",
      "user_contact_masked": "+91******3210",
      "user_contact_hashed": "4f9a2c7e1b8d3f60a5c4e2b19d7f8a3c6e1b5d9f2a7c4e8b0d3f6a1c9e5b2d7f",
      "connectivity_status": "connected",
      "failure_reason": "NO_FAILURE_REASON",
      "ended_by": "USER_ENDS",
      "next_action_status": "UNKNOWN",
      "duration_in_seconds": 142.6,
      "start_datetime": "2026-10-07T05:12:08",
      "end_datetime": "2026-10-07T05:14:31",
      "attempted_at": "2026-10-07T05:11:57",
      "language_name": "Hindi",
      "num_messages": 14,
      "average_agent_response_time_in_seconds": 1.18,
      "average_user_response_time_in_seconds": 2.46,
      "channel_type": "v2v",
      "channel_direction": "outbound",
      "channel_protocol": "websocket",
      "retry_attempt": 1,
      "server_retry_attempt": 0,
      "campaign_id": "emi-reminder-oct-2026",
      "cohort_id": "cohort-0921-overdue",
      "is_debug_call": 0,
      "has_log_issues": 0,
      "audio_url": "https://agents.sarvam.ai/media?org_id=acme-corp-7c2e9f&workspace_id=support-ws-4b1d8a&app_id=support-bot-3f9a1c2e-7b4d&interaction_id=20261007/9f1c2a7e-4b3d-4e8a-a1f0-6c2d9b7e5a14&audio_hash=merged_audio",
      "agent_variables": {
        "customer_name": "Priya Sharma",
        "emi_amount": "4500",
        "loan_status": "overdue",
        "promised_payment_date": "2026-10-10"
      },
      "channel_provider": null
    }
  ],
  "total": 37,
  "limit": 1,
  "offset": 0,
  "next_page_uri": "?start_datetime=2026-10-01T00%3A00%3A00%2B05%3A30&end_datetime=2026-10-07T23%3A59%3A59%2B05%3A30&limit=1&offset=1",
  "prev_page_uri": ""
}
```

Note that the webhook `status` (`connected`/`no_answer`/`busy`/`failed`) and the analytics `connectivity_status` are separate fields. The attempts page gives only examples ("e.g. `connected`, `no_answer` or `failed`"). It does not give a full enum. Treat unknown values as possible (**DOCUMENTED-AMBIGUOUS**).

## 2. Interaction detail retrieval (List interactions)

Source: https://docs.sarvam.ai/voice-agents/api/analytics/interactions.md. **VERIFIED**.

**Endpoint.** `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/interactions`.

**Query parameters.** The same as for attempts (`start_datetime`, `end_datetime`, `limit`, `offset`, `sort_by`, `sort_order`, `filter_conditions`). The `sort_by` default is `interaction_id`. This endpoint adds:
- `include_transcript` (bool, default false): "Add `original_transcript` and its English translation `translate_transcript` to each item."
- `include_forwarded_calls` (bool, default false): adds `forwarded_calls`.
- `forwarded_only` (bool, default false): "Return only interactions that were forwarded. Implies `include_forwarded_calls`."

**Item fields (`ExternalInteractionsAPIResponse`).** These are the same as an attempt item, with these differences:
- It has `job_id` in place of `attempt_id`: "ID of the attempt that produced this interaction (the `attempt_id` in List attempts)".
- It has no `connectivity_status` and no `next_action_status`.
- It adds `original_transcript`, `translate_transcript` and `forwarded_calls`.

`ForwardedCall` fields: `status`, `transfer_type` (`blind`/`warm`), `forwarded_to {type: phone|sip_uri, value}`, `initiated_at`, `hangup_source`, `has_recording`, `transfer_id`, `started_at`, `ended_at`, `duration_in_seconds`, `hangup_cause`, `recording_url`.

**Single interaction.** There is no `GET .../interactions/{interaction_id}` endpoint in the docs index. To fetch one interaction, use List interactions with a filter on `interaction_id` or `job_id` (both are listed as filterable). **UNVERIFIED** that a single-GET endpoint exists. The overview says the filter fields apply to "Both list endpoints". It does not say whether every field works on each endpoint, so filtering interactions by `job_id` is **DOCUMENTED-AMBIGUOUS** until tested.

## 3. Transcript retrieval

**a. Webhook `interaction_transcript`** (https://docs.sarvam.ai/voice-agents/api/instant-outbound/webhook-payload.md). **VERIFIED**.
- Shape: `array | null`, with items `{ "role": "agent" | "user", "en_text": string }`.
- `en_text`: "English text of the turn (translated if the conversation was in another language)." So it is **not verbatim** for non-English calls.
- It is `null` "if the call did not connect".
- The inbound deployments payload adds an optional `indic_text` (https://docs.sarvam.ai/voice-agents/api/deployments/webhooks/webhook-payload.md). The instant-outbound page does **not** list `indic_text`.

**b. Get transcript API** (https://docs.sarvam.ai/voice-agents/api/analytics/transcripts.md). **VERIFIED**.
- `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/transcripts/{interaction_id}`.
- "Send the slash as is or as `%2F`." An ID without `/` returns `400`.
- Response: `{ "interaction_id": string, "messages": [ { "turn_id": int, "role": "assistant" | "user", "content": string, "language_name": string } ] }`.
- "An unknown `interaction_id` returns `200` with an empty `messages` array." So an empty list does not mean the call failed.
- The page example has Hindi script in `content` with `language_name: "Hindi"`. This suggests `content` is the original-language text. The field description says only "What was said." (**DOCUMENTED-AMBIGUOUS** on whether it is ever translated.)

**c. Inline transcripts** (List interactions with `include_transcript=true`). **VERIFIED**.
- `original_transcript`: "The conversation in its original language, in order. … Aligned 1:1 with `translate_transcript`."
- `translate_transcript`: "English translation of `original_transcript`: entry *i* here translates entry *i* there."
- Each entry is `TranscriptEntry {role: "agent" | "user", text}`.

**Per-turn timestamps.** None of the three shapes has a timestamp field. Get transcript has only `turn_id` (an ordinal). **UNVERIFIED (absent)**.

## 4. Speaker attribution

**VERIFIED.**
- Webhook payloads and inline `original_transcript` / `translate_transcript` use `agent` and `user`.
- Get transcript uses `assistant` and `user`: "Roles here are `assistant` and `user`. Inline transcripts from List interactions use `agent` and `user`."
- The Web SDK `transcriptCallback` uses `Role.USER | Role.BOT` (from phase 3).

Normalise all of these to one internal enum.

## 5. Recording retrieval

**Get recording** (https://docs.sarvam.ai/voice-agents/api/analytics/recordings.md). **VERIFIED**.
- `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/recordings/{interaction_id}`, with header `X-API-Key`.
- "Returns the call recording as a WAV file (`audio/wav`), not JSON. Returns `404` if the interaction has no recording."

**Format** (https://docs.sarvam.ai/voice-agents/monitor/call-recordings.md, and changelog https://docs.sarvam.ai/changelog/2026/10/16.md). **VERIFIED**.
- "one continuous WAV file covering the whole call".
- "Recordings are **dual-channel (stereo)**: the **user is recorded on the left channel** and the **agent on the right channel**." The changelog adds: "This is now enabled for all calls."
- "telephony audio is kept at the legacy 11.025 kHz rate."

**`audio_url` field** (on attempt and interaction items). **DOCUMENTED-AMBIGUOUS**.
- Description: "Link to the call recording. To download audio from code, use [Get recording]."
- The example is `https://agents.sarvam.ai/media?org_id=…&workspace_id=…&app_id=…&interaction_id=…&audio_hash=merged_audio`. It has no visible signature or expiry parameter, and appears to be a dashboard link.
- The docs do not say whether it is signed, whether it needs a login, or what its TTL is. Do not depend on it. Use Get recording.

**Signed recording links.** These exist only for forwarded legs: `forwarded_calls[].recording_url` is a "Signed link to the forwarded-leg recording (mp3 or wav), usable without an API key. Null unless `has_recording` is true and signed recording links are enabled for your workspace." The TTL is not stated (**UNVERIFIED**). How to enable "signed recording links" is not documented (**UNVERIFIED**).

**Enabling recording.** "Every connected call handled by a voice agent is recorded". The page also says: "Recording requires stitched audio to be enabled (`enable_stitched_audio` is on by default)." Where `enable_stitched_audio` is set is not documented (**DOCUMENTED-AMBIGUOUS**).

**Consent.**
- No recording-consent or announcement setting was found (**UNVERIFIED**).
- Consent appears only for dialling: "Make sure you have consent to call each contact" (https://docs.sarvam.ai/voice-agents/deploy/campaigns/dnd.md).
- Access control: "who can … view recordings/transcripts" is a Policy setting (https://docs.sarvam.ai/voice-agents/settings/policy.md).

## 6. Pagination

Source: https://docs.sarvam.ai/voice-agents/api/analytics/overview.md. **VERIFIED**.
- "List responses carry `items`, `total`, `limit`, `offset`, `next_page_uri`, and `prev_page_uri`. `limit` defaults to `20` and goes up to `1000`."
- "`next_page_uri` and `prev_page_uri` are relative query strings that repeat your parameters with the new offset … Append them to the endpoint path … They are an empty string (`""`, not `null`) when there is no such page."
- "List responses are cached for 60 seconds, so repeating an identical request within that window returns the same result."

## 7. Provider-side evaluations, extraction and summaries

**Output variables** (https://docs.sarvam.ai/voice-agents/build/variables-personalization.md). **VERIFIED**.
- "Output variables are extracted from the conversation after the call ends." Each has a "**Data type**: **String** or **Enum**" and an "**Extraction prompt**".
- At call end: "Output variables are extracted by the LLM via their extraction prompts. The on-end hook fires and pushes final variable values to your endpoint."
- In the API, these values arrive in `agent_variables` (analytics) and `final_agent_variables` (webhook). There is no separate field for "extracted" values. Input and output variables "share storage".
- The docs do not say whether extraction finishes before the webhook fires (**UNVERIFIED**). Reconcile against List interactions to be safe.

**Goal** (https://docs.sarvam.ai/voice-agents/build/process.md and https://docs.sarvam.ai/voice-agents/monitor/agent-analytics/goals.md). **VERIFIED** in the dashboard.
- "You can set **one goal per agent**."
- Rules use `equals`, `not_equals`, `in`, `gt`, `lt`.
- "every connected call is evaluated against it."
- No goal-result field appears in the webhook or Analytics API schemas (**UNVERIFIED**). Call Logs mentions "goal status when configured for your org" as a dashboard column only.

**Summaries.** No summary field is documented in any webhook or Analytics response (**UNVERIFIED, absent**).

**Other signals.** `has_log_issues` (0/1) and `ended_by` are available. The Tests API (`https://apps.sarvam.ai/api/evals`) runs simulated test calls, at ₹2 per run. It does not score live calls.

**Boards SQL** (https://docs.sarvam.ai/voice-agents/api/boards/sql.md) can query `EngagementFactsBoardsView`. The available columns are per workspace ("Call [Get query schema] before writing anything"). A goal column might exist there, but this is not documented (**UNVERIFIED**).

## 8. Data retention

Source: https://docs.sarvam.ai/api/platform/data-retention.md (linked from call-recordings.md and settings/policy.md). **VERIFIED**.
- "**Data retention is set per workspace**, on **Settings → Workspace → Data retention**."
- "Until an Owner sets a retention period, your workspace's data is retained indefinitely."
- "Only a workspace's org **Owner** can change retention settings."
- Voice Agents supports a product override. "Zero data retention (**No retention**, 0 days) is supported for **Model APIs**. It is not yet supported for **Voice Agents**".
- Periods offered: 1 day, 15 days, 30, 45, 60, 90, 180, 365 and 730 days, plus 0 days (Model APIs only).
- "It is not retroactive".
- The docs do not say whether calls, transcripts and recordings can have different periods. One period covers the Voice Agents product.

## 9. Webhook events (instant outbound)

Source: https://docs.sarvam.ai/voice-agents/api/instant-outbound/webhook-payload.md. **VERIFIED**.
- There is one event: "After each instant outbound call attempt completes — whether or not it connected — Sarvam sends a `POST` request". The payload has no event-type field.
- There are no ringing, answered or in-progress events, and no separate "analysis ready" event (**UNVERIFIED, absent**).
- Delivery retries and the list/retry endpoints exist for campaigns and deployments (`webhooks/list`, `webhooks/retry`), but not for instant outbound.
- Signing is still undocumented (see phase 3).
- The webhook `duration` is a decimal number of seconds (example `16.83`).

## 10. Rate limits (analytics)

**VERIFIED** (https://docs.sarvam.ai/voice-agents/api/analytics/overview.md): "Requests are rate-limited per API key; the limit is configured per organization. Exceeding it returns `429` with a `Retry-After` header giving the seconds to wait". The example is `Retry-After: 60`. "Honour `Retry-After` … back off exponentially".

There is no numeric limit for the analytics endpoints (**UNVERIFIED**).

For comparison, Boards publishes numbers (https://docs.sarvam.ai/voice-agents/api/boards/overview.md): 20 requests/minute per organisation for `POST /query-preview`, 20/min for `POST /widgets/{widget_id}/run` and 50/min for `POST /tabs/{tab_id}/run`.

## 11. Authentication and permissions

**VERIFIED.**
- https://docs.sarvam.ai/voice-agents/api/analytics/overview.md: "Send your API key in the `X-API-Key` header on every request. Bearer tokens are not accepted on these endpoints."
- Keys are managed under **Settings → API Key** (https://docs.sarvam.ai/voice-agents/settings/api-key.md).
- Keys belong to a workspace: "To the **workspace**." There is a limit of "Up to **50 active keys** per organisation" (https://docs.sarvam.ai/api/platform/faq.md).
- A `403` means "The API key is valid but not authorized for this organization or workspace."

No per-key scopes or read-only keys are documented (**UNVERIFIED**). The Policy page covers dashboard user permissions, not key scopes.

## 12. Billing per call

- **Rule (VERIFIED,** https://docs.sarvam.ai/voice-agents/pricing.md): "A minute is one 60-second pulse, and each call is rounded up to whole pulses."
- "Only calls that connect are charged." Voicemail that connects is billed.
- Sarvam telephony (Vobiz) is ₹0.20 per 30-second pulse. Bring-your-own telephony is free on Sarvam.
- **Per-call cost or billed-minutes field: UNVERIFIED (absent).** No webhook or Analytics field gives cost, billed minutes or pulses. The only inputs are `duration_in_seconds` (analytics) and `duration` (webhook).
- Whether `duration_in_seconds` equals the billed duration is not stated (**DOCUMENTED-AMBIGUOUS**). Any per-call cost we show is an estimate: `ceil(duration_in_seconds / 60) × plan rate`.

## 13. Sarvam chat completions API

Sources: https://docs.sarvam.ai/api-reference/chat/chat-completions-v1.md, https://docs.sarvam.ai/api-reference/chat/chat-completions-v2.md, https://docs.sarvam.ai/api-reference/beta-apis.md, https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview.md, https://docs.sarvam.ai/api-reference/authentication.md, https://docs.sarvam.ai/api/getting-started/pricing.md, https://docs.sarvam.ai/api/getting-started/ratelimits.md. **VERIFIED** unless noted.

**Endpoint (use V1).** `POST https://api.sarvam.ai/v1/chat/completions`. "This endpoint serves **only** `sarvam-105b` and `sarvam-105b-conversations`."
- V2 (`POST https://api.sarvam.ai/v2/chat/completions`) "Requires `api-subscription-key` with beta access". Beta access is "granted **per API key**". A key without it gets `400 invalid_request_error`.
- `sarvam-m` "has been deprecated and is no longer available through the Chat Completions API" (https://docs.sarvam.ai/api/getting-started/models/sarvam-m.md).

**Auth.** Header `api-subscription-key: <key>`. "The API also accepts the same key as a standard `Authorization: Bearer` header on all endpoints."

Whether a Voice Agents `X-API-Key` works as a Model API `api-subscription-key` is **DOCUMENTED-AMBIGUOUS**. Both are workspace keys under one organisation, and the docs say credits are shared "across every Sarvam product". But the Model API docs send users to `dashboard.sarvam.ai` for keys, and the Voice Agents docs send them to Voice Agents **Settings → API Key**.

**Request body (V1).**
- `messages` (required; roles `system`, `developer`, `user`, `assistant`, `tool`).
- `model` (required): `sarvam-105b` (128K context) or `sarvam-105b-conversations` (32K).
- `temperature` (default 0.2), `top_p` (default 1).
- `reasoning_effort`: allowed `low` / `high` / `max`, but the text says "Default is 'medium'". This is **DOCUMENTED-AMBIGUOUS**.
- `max_tokens` (default 2048), `stream`, `stop`, `n`, `seed`, `frequency_penalty`, `presence_penalty`, `tools`, `tool_choice`, `response_format`.

**Structured output.** `response_format: {"type": "json_schema", "json_schema": {"name", "schema", "strict", "description"}}` "enables Structured Outputs which guarantees the model generates output matching the supplied JSON Schema". `{"type": "json_object"}` is "JSON mode". "The structured reply arrives as a JSON **string** in `message.content`, parse it before use." The guide's cURL example uses `sarvam-105b` on `/v1` with `strict: true`.

**Response.** `id`, `choices[]` (`finish_reason`: `stop`/`length`/`tool_calls`/`content_filter`/`function_call`; `index`; `message{content, role, tool_calls, …}`; `logprobs`), `created`, `model`, `object: "chat.completion"`, `service_tier`, `system_fingerprint`, and `usage{completion_tokens, prompt_tokens, total_tokens, completion_tokens_details{reasoning_tokens}, prompt_tokens_details{cached_tokens}}`.

The V2 notes warn that "a low limit can yield `finish_reason: "length"` with little or no visible `content` if reasoning consumes the budget". Set `max_tokens` generously.

Errors: `400`, `403`, `422`, `429`, `500`, as `{error: {message, code, request_id}}`. `code` is one of `invalid_request_error`, `internal_server_error`, `unprocessable_entity_error`, `insufficient_quota_error`, `invalid_api_key_error`, `authentication_error`, `rate_limit_exceeded_error`, `not_found_error`.

Example response (V1 page):

```json
{
  "id": "20250101_0a1b2c3d-1234-5678-9abc-def012345678",
  "choices": [
    {
      "finish_reason": "stop",
      "index": 0,
      "message": { "content": "नमस्ते! मैं आपकी कैसे मदद कर सकता हूँ?", "role": "assistant" },
      "logprobs": {}
    }
  ],
  "created": 1735689600,
  "model": "sarvam-105b",
  "object": "chat.completion",
  "service_tier": null,
  "system_fingerprint": null,
  "usage": { "completion_tokens": 18, "prompt_tokens": 12, "total_tokens": 30 }
}
```

**Pricing** (updated October 10, 2026, https://docs.sarvam.ai/changelog/2026/10/10.md). `sarvam-105b` and `sarvam-105b-conversations` cost ₹15 input, ₹5 cached input and ₹60 output per 1M tokens. This is billed on top of the Voice Agents per-minute rate, because it is a separate Model API call.

**Rate limits.** Sarvam-105B: 40 / 60 / 120 requests per minute on Starter / Pro / Business. "Rate limits are measured per account, not per API key." A `429` carries `code: rate_limit_exceeded_error`.

**Retention.** Model API data follows the workspace retention setting, and zero retention is supported for Model APIs (see section 8).

## 14. SMS / OTP

**UNVERIFIED (none found).** The root index (https://docs.sarvam.ai/llms.txt), the Model APIs index and every Voice Agents page have no SMS or OTP sending API. The only SMS mention is internal to the dashboard: "Genie first sends a one-time code by SMS to verify your number" (https://docs.sarvam.ai/voice-agents/build/genie.md). `channel_type` can be `"whatsapp"`, but WhatsApp campaigns are an Enterprise feature (pricing page) and are not an OTP API. Use a separate SMS provider.

## 15. Web SDK and related docs changes

- https://registry.npmjs.org/sarvam-conv-ai-sdk: `dist-tags.latest` = `0.0.42`. The last `time` entries are `0.0.42` at `2026-03-30T11:19:16.625Z` and `modified` at `2026-03-30T11:19:16.752Z`. There has been **no release after 0.0.42**. **VERIFIED**.
- https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md still says "Reconnection is not supported: each WebSocket URL is single-use." It says nothing about TTL, server-side locking of `agent_variables`, web session concurrency or billing (**UNVERIFIED**, unchanged since phase 3).
- The September–October 2026 changelog entries have nothing on these topics. I checked 9/1, 9/2, 9/3, 9/9, 9/15–9/18, 9/21–9/23, 9/26, 10/1, 10/4, 10/6, 10/10, 10/12, 10/14 and 10/16. Relevant entries: 9/2 Inbound Webhooks, 9/15 Data Retention Controls, 9/16 Voice Agents MCP Server and Boards API, 10/16 Dual-Channel Call Recordings.

---

## What this means for implementation

**Safe to build now, against documented contracts:**

1. **Attempt reconciliation job.** After each webhook, or on a timer for attempts with no webhook:
   - Call `GET /api/analytics/v1/{org}/{ws}/{app}/attempts` with `start_datetime`/`end_datetime` around the call time (with an offset, `+` encoded) and `filter_conditions=[{"field":"attempt_id","operator":"equals","value":"<id>"}]`.
   - Read `connectivity_status`, `failure_reason`, `ended_by`, `duration_in_seconds`, `interaction_id` and `agent_variables`.
   - Respect the 60-second cache. Wait at least 60 s before re-polling the same query.
2. **Interaction and transcript fetch.**
   - Preferred: one call to List interactions with `include_transcript=true` and a filter on `interaction_id`. This gives the original-language and English transcripts aligned 1:1.
   - Fallback: `GET .../transcripts/{interaction_id}`. Treat an empty `messages` as "not ready or unknown" and retry later. It is not a final empty transcript.
   - Map roles `assistant`/`agent`/`user` to one enum. Store `language_name`.
   - No timestamps exist, so do not design scoring around per-turn timing. Use `average_agent_response_time_in_seconds` and `average_user_response_time_in_seconds` instead.
3. **Recording download.** Use `GET .../recordings/{interaction_id}` on the server with `X-API-Key`, and store the file ourselves (stereo WAV, user on left). Handle `404` as "no recording". Do not hand `audio_url` to clients.
4. **Pagination helper.** Follow `next_page_uri` until it is `""`. Use `limit` up to 1000.
5. **429 handling.** Read the `Retry-After` header in seconds, then back off exponentially with jitter. The same pattern works for Analytics, Boards and chat completions.
6. **Evaluation with Sarvam LLM.**
   - Call `POST https://api.sarvam.ai/v1/chat/completions` with `model: "sarvam-105b"`, header `api-subscription-key`, and `response_format: {type: "json_schema", json_schema: {name, strict: true, schema}}`.
   - Parse `choices[0].message.content` as JSON and validate it.
   - Check `finish_reason == "length"`.
   - Record `usage` for cost at ₹15/₹60 per 1M input/output tokens.
   - Keep the provider pluggable, because the key question below is open.
7. **Use provider extraction too.** Define output variables (Enum where possible) in the agent. Read them from `final_agent_variables` / `agent_variables`. Treat them as a second opinion next to our own evaluation.
8. **Cost display.** Show "estimated minutes = ceil(duration_in_seconds / 60)". Label it as an estimate.
9. **Retention.** Ask the org Owner to set a Voice Agents retention period. The default is indefinite. Our copy of transcripts and recordings needs its own retention policy.

**Needs a live test or Sarvam confirmation (uses the API key):**

1. Does a Voice Agents API key work as `api-subscription-key` on `api.sarvam.ai`? Or is a separate Model API key needed?
2. Does the `job_id` (or `attempt_id`) filter work on List interactions?
3. How long after the webhook do transcript, recording and output variables become available in Analytics?
4. Is `audio_url` usable without a dashboard session? Does it expire?
5. How are "signed recording links" enabled, and what is their TTL?
6. What is the analytics rate-limit number for our org?
7. Does `duration_in_seconds` match the billed duration on the invoice?
8. Is a goal result exposed anywhere through the API (for example a Boards schema column)?

## Sources (all fetched 2026-10-21)

- https://docs.sarvam.ai/voice-agents/llms.txt, https://docs.sarvam.ai/llms.txt, https://docs.sarvam.ai/api/llms.txt, https://docs.sarvam.ai/api-reference/llms.txt, https://docs.sarvam.ai/changelog/llms.txt
- https://docs.sarvam.ai/voice-agents/api/analytics/overview.md
- https://docs.sarvam.ai/voice-agents/api/analytics/attempts.md
- https://docs.sarvam.ai/voice-agents/api/analytics/interactions.md
- https://docs.sarvam.ai/voice-agents/api/analytics/transcripts.md
- https://docs.sarvam.ai/voice-agents/api/analytics/recordings.md
- https://docs.sarvam.ai/voice-agents/api/introduction.md
- https://docs.sarvam.ai/voice-agents/api/instant-outbound/webhook-payload.md, https://docs.sarvam.ai/voice-agents/api/campaigns/webhooks/webhook-payload.md, https://docs.sarvam.ai/voice-agents/api/deployments/webhooks/webhook-payload.md
- https://docs.sarvam.ai/voice-agents/api/boards/overview.md, https://docs.sarvam.ai/voice-agents/api/boards/sql.md, https://docs.sarvam.ai/voice-agents/api/boards/best-practices.md, https://docs.sarvam.ai/voice-agents/api/boards/query/schema.md
- https://docs.sarvam.ai/voice-agents/api/tests/overview.md
- https://docs.sarvam.ai/voice-agents/monitor/call-recordings.md, https://docs.sarvam.ai/voice-agents/monitor/agent-analytics/call-logs.md, https://docs.sarvam.ai/voice-agents/monitor/agent-analytics/goals.md
- https://docs.sarvam.ai/voice-agents/build/variables-personalization.md, https://docs.sarvam.ai/voice-agents/build/process.md, https://docs.sarvam.ai/voice-agents/build/on-start-on-end-hooks.md, https://docs.sarvam.ai/voice-agents/build/genie.md
- https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md, https://docs.sarvam.ai/voice-agents/deploy/campaigns/dnd.md
- https://docs.sarvam.ai/voice-agents/settings/api-key.md, https://docs.sarvam.ai/voice-agents/settings/policy.md, https://docs.sarvam.ai/voice-agents/mcp.md
- https://docs.sarvam.ai/voice-agents/pricing.md
- https://docs.sarvam.ai/api/platform/data-retention.md, https://docs.sarvam.ai/api/platform/faq.md, https://docs.sarvam.ai/api/platform/organisations-and-workspaces.md, https://docs.sarvam.ai/api/platform/create-a-workspace.md
- https://docs.sarvam.ai/api-reference/chat/chat-completions-v1.md, https://docs.sarvam.ai/api-reference/chat/chat-completions-v2.md, https://docs.sarvam.ai/api-reference/beta-apis.md, https://docs.sarvam.ai/api-reference/authentication.md
- https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview.md, https://docs.sarvam.ai/api/getting-started/models/sarvam-m.md, https://docs.sarvam.ai/api/getting-started/pricing.md, https://docs.sarvam.ai/api/getting-started/ratelimits.md
- Changelog: https://docs.sarvam.ai/changelog/2026/10/16.md, https://docs.sarvam.ai/changelog/2026/10/10.md, https://docs.sarvam.ai/changelog/2026/9/15.md, https://docs.sarvam.ai/changelog/2026/9/2.md (also scanned every other September–October 2026 entry)
- https://registry.npmjs.org/sarvam-conv-ai-sdk

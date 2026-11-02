# Phase 3: Sarvam Voice Agents Verification

*Checked on 2026-10-21. This was read-only research. I called no paid API, used no API key and signed up for nothing. Sources: the Markdown versions of docs.sarvam.ai pages (fetched with `curl`), the npm registry metadata, and the published tarball `https://registry.npmjs.org/sarvam-conv-ai-sdk/-/sarvam-conv-ai-sdk-0.0.42.tgz`, which I unpacked and read. The proxy blocked `unpkg.com` (connect refused), so I listed files from the registry tarball instead. The npm package has `repository: null`, so there is no public GitHub source to check.*

This report re-checks `docs/browser_voice_feasibility.md`. In general that report holds up. Corrections and additions are marked **[NEW]** or **[CORRECTION]**.

## Status labels

| Label | Meaning |
|---|---|
| **VERIFIED** | Stated on an official docs.sarvam.ai page (URL given). We have not run it. |
| **PACKAGE-SOURCE** | Seen only in the published npm code (`dist/*.js`, `*.d.ts`, `README.md`), not in the docs. It may change without notice. |
| **UNVERIFIED** | Not found in the docs or the package. Needs Sarvam to confirm or a live test. |

## Summary table

| # | Topic | Finding (short) | Status |
|---|---|---|---|
| 1 | Web SDK | `sarvam-conv-ai-sdk@0.0.42` (published 2026-03-30T11:19:16Z, still the latest). Import from `sarvam-conv-ai-sdk/browser`. Use `ConversationAgent` + `BrowserAudioInterface`, with `start()` / `stop()` and seven documented callbacks. | VERIFIED (docs), with extras that are PACKAGE-SOURCE |
| 2 | Signed URL | `GET {baseUrl}orgs/{org_id}/workspaces/{workspace_id}/apps/{app_id}/url?interaction_type=call[&version=N]`, header `X-API-Key`, response `{url, reference_id}`. `baseUrl` and `customHeaders` can be overridden. There is **no token-fetcher callback**. The URL is single-use; its TTL is unknown. | Endpoint: PACKAGE-SOURCE. Single-use and the `baseUrl` proxy: VERIFIED. TTL: UNVERIFIED |
| 3 | Client to socket | The SDK 0.0.42 has **no public method** to send `variable_update` or `state_transition`. The enum values exist, though. The client **does** send `agent_variables`, `initial_state_name`, `initial_language_name` and `initial_bot_message` in `interaction_start`. No server-side lock is documented. | PACKAGE-SOURCE / UNVERIFIED |
| 4 | Outbound webhook | Fields: `attempt_id`, `status` (`connected`/`no_answer`/`busy`/`failed`), `channel_info`, `duration`, `interaction_id`, `failure_reason`, `final_agent_variables`, `webhook_config` (echoed, with `metadata`), `interaction_transcript`. **No webhook signature or HMAC is documented**, and `WebhookConfig` has only `url` + `metadata`. There is no per-attempt GET API. Use Analytics `List attempts` filtered by `attempt_id`. | VERIFIED (payload). Signing: UNVERIFIED (absent) |
| 5 | Bulbul V3 EOL | "Bulbul V3 reaches end of life on Voice Agents on **November 10, 2026**." Changelog entry dated October 14, 2026. This applies to Voice Agents only; V3 stays on the TTS API. | VERIFIED |
| 6 | Concurrency | PAYG 4 / Pro 10 / Growth 30 / Business (coming soon) 120 / Enterprise custom concurrent calls; 20 / 50 / 150 / 600 / custom calls started per minute. The limits are shared org-wide. Web/SDK sessions are not mentioned. | VERIFIED (web share: UNVERIFIED) |

---

## 1. Web SDK

**Package and version.** npm package `sarvam-conv-ai-sdk`. `dist-tags.latest` is `0.0.42`, published `2026-03-30T11:19:16.625Z`. The earlier versions were 0.0.41 (2026-03-23) and 0.0.40 (2026-03-04). There has been no release in about seven months. Its license is MIT. The same package also serves Node and React Native, and the tarball even ships Android build intermediates. Source: https://registry.npmjs.org/sarvam-conv-ai-sdk. Status: **PACKAGE-SOURCE** (registry). The docs name the package: **VERIFIED**.

**Entry point.** `import { ConversationAgent, BrowserAudioInterface, InteractionType, AgentState, Role } from "sarvam-conv-ai-sdk/browser";`. In `package.json`, `exports["./browser"]` points to `./dist/browser.js` and its types to `./dist/browser.d.ts`. The root export also maps `browser` to `./dist/browser.js`, and `ws`, `speaker` and `node-record-lpcm16` are set to `false` for browsers. Docs: https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md — **VERIFIED**. `dist/browser.js` also exports `createConversation` and the typed errors `SDKError`, `RateLimitError`, `AuthenticationError`, `ForbiddenError`, `NotFoundError` and `ServerError` (**PACKAGE-SOURCE**).

**Start and stop.** `new ConversationAgent({ apiKey, config, audioInterface, ...callbacks, baseUrl?, customHeaders?, platform? })`. Then use `await agent.start()`, `await agent.waitForConnect(timeoutSeconds)` (returns `false` on timeout), `await agent.stop()` and `await agent.waitForDisconnect()`. Other methods are `sendAudio(Uint8Array)`, `isConnected()`, `getInteractionId()`, `getState()`, `mute()`, `unmute()` and `isMuted()`. **VERIFIED** (web.md "Session methods"). The package also has `sendText()`, `getAgentType()` and the `reference_id` getter (**PACKAGE-SOURCE**). `stop()` only closes the socket. It does not send `client.action.interaction_end`, because no code path sends that message (**PACKAGE-SOURCE**).

**Config (`InteractionConfig`).** All of these are **VERIFIED** in web.md and match `dist/types/config.d.ts`:
- Required: `org_id`, `workspace_id`, `app_id` (the agent/app id), `user_identifier`, `user_identifier_type` (`'custom' | 'email' | 'phone_number' | 'unknown'`), `interaction_type` (`InteractionType.CALL` = `"call"`), `input_sample_rate` (`8000 | 16000`) and `output_sample_rate` (`16000 | 22050`).
- Optional: `version` (a number). The docs say it "Pins a specific committed agent version. If omitted, the SDK uses the latest committed version, and the connection fails if the agent has no committed version". The other optional fields are `agent_variables` (`Record<string, any>`), `initial_language_name`, `initial_state_name` and `initial_bot_message`.

**Callbacks and events.**
- Documented (**VERIFIED**, web.md): `transcriptCallback` (`{role: Role.USER | Role.BOT, content}`), `audioCallback`, `audioLevelCallback`, `eventCallback` ("Session events such as connect, barge-in, and end"), `stateCallback` (`AgentState`: `IDLE`, `CONNECTING`, `CONNECTED`, `LISTENING`, `SPEAKING`, `ERROR`; the string values are lowercase, e.g. `"listening"`), `startCallback` and `endCallback`.
- Only in the package (**PACKAGE-SOURCE**):
  - `textCallback` (chat mode).
  - `telemetryCallback`, which receives `{name, timestamp, sessionId, interactionId, properties}`. Event names include `session_started`, `signed_url_requested`, `signed_url_received`, `signed_url_failed`, `ws_connecting`, `ws_connected`, `ws_disconnected` (`code`, `reason`), `ws_error`, `interaction_connected`, `first_audio_packet_sent`, `first_audio_packet_received`, `user_interrupted`, `user_muted`, `user_unmuted`, `network_offline`, `network_online`, `state_changed` and `session_ended` (`durationMs`, `initiatedBy`: `user`/`agent`/`network`/`error`).
  - The `stateCallback` signature is `(newState, previousState)`.
- **User speaking vs agent speaking.** `AgentState.SPEAKING` is set when agent audio chunks arrive. `LISTENING` is set after playback drains or when a `server.event.user_interrupt` arrives (barge-in). There is no dedicated "user is speaking" state. The raw server events `server.event.user_speech_start` and `server.event.user_speech_end` are declared in the enum and would reach `eventCallback` as raw objects if the server sends them, because every unhandled type is passed to `eventCallback`. Whether the server actually sends them is **UNVERIFIED**.
- **Transcript.** `server.event.transcription` goes to `transcriptCallback`.
- **Connected.** `server.action.interaction_connected` carries `interaction_id` and `reference_id`. It sets `getInteractionId()`.
- **End.** `server.action.interaction_end`, or a socket close, triggers `endCallback`.
- **Errors.** There is no `errorCallback`. HTTP failures while fetching the signed URL throw typed errors from `start()`: 429 throws `RateLimitError` (it reads `x-retry-after`, default 60), 401 throws `AuthenticationError`, 403 `ForbiddenError`, 404 `NotFoundError`, and 5xx `ServerError`. Socket errors set `AgentState.ERROR` and emit `ws_error` telemetry. **PACKAGE-SOURCE**.

**Other facts.**
- `BrowserAudioInterface(sampleRate=16000, {prebufferMs=700, bufferSizeMs=8000, outputLevelCallback})` — **VERIFIED**.
- It calls `getUserMedia` with `echoCancellation: true, noiseSuppression: true, autoGainControl: true` — **PACKAGE-SOURCE**. This resolves an open question in the earlier report.
- **[NEW] Security note.** The SDK writes `console.log("[SDK] Got signed URL:", ...)` and `"[SDK] Final WebSocket URL:"`, so the signed URL appears in the browser console. This is low risk because the URL is single-use, but it should be noted.

## 2. Signed URL / token flow

**Endpoint (PACKAGE-SOURCE, `dist/modules/socket-manager.js`):**
- Default `baseUrl = "https://apps.sarvam.ai/api/app-runtime/"`.
- The request is `GET ${baseUrl}orgs/${org_id}/workspaces/${workspace_id}/apps/${app_id}/url`, with `?interaction_type=call` appended, plus `&version=N` if `version` is set.
- Headers: `{"X-API-Key": apiKey, ...customHeaders}`. Note that `X-API-Key` is always sent, as an empty string when `apiKey: ""`, so our proxy must strip or overwrite it.
- Response: JSON `{ url, reference_id }`. If either field is missing, the SDK throws "Expected object with 'url' and 'reference_id' properties … This may indicate the app has no committed version or the app_id/org_id/workspace_id is incorrect."
- After the response, the SDK appends these query params to the returned `url` **on the client, after signing**: `user_identifier`, `user_identifier_type`, `input_sample_rate`, `output_sample_rate`, and then `interaction_type=call` again. It then opens the WebSocket directly to that URL.
- The docs do not publish this endpoint path. The WebSocket contract is only referenced ("according to the API contract", https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code.md). The `X-API-Key` header itself is the documented auth for Voice Agents APIs (https://docs.sarvam.ai/voice-agents/api/introduction.md): **VERIFIED**.

**TTL and single use.** Single use is **VERIFIED** (web.md): "Reconnection is not supported: each WebSocket URL is single-use. If the connection drops, call `stop()` and create a new `ConversationAgent`." The package source comment says only "time-limited signed URL" (**PACKAGE-SOURCE**). The TTL value is **UNVERIFIED** (not documented).

**Keeping the key server-side.** The **`baseUrl` override is VERIFIED** (web.md): "Point `baseUrl` at a backend you control and leave `apiKey` empty so the proxy adds the Sarvam key server-side". The example is `apiKey: "", baseUrl: "/api/sarvam/"`. `customHeaders` is also **VERIFIED**: "For a cross-origin proxy, pass your app's auth in `customHeaders` (for example `Authorization: Bearer` plus your session token)." There is **no token-fetcher or signed-URL callback** in 0.0.42 (**PACKAGE-SOURCE**, constructor options listed in `dist/conversation.d.ts`). `modifySignedUrlString()` is a protected subclass hook, not a public option. So our proxy must serve the exact path shape `{baseUrl}orgs/{org}/workspaces/{ws}/apps/{app}/url` and return `{url, reference_id}`.

Our proxy can, and should, **ignore the `org_id`, `workspace_id`, `app_id` and `version` sent by the browser**. It should substitute the server-configured values itself, so a user cannot point our key at another agent. Whether the signature binds `user_identifier` and the sample rates, which are appended after signing, remains **UNVERIFIED**.

## 3. What the client can send over the socket

**PACKAGE-SOURCE** (`dist/types/types.d.ts`, `dist/utils/message.js`):
- **Sent by the SDK:**
  - `client.action.interaction_start`, which carries `agent_variables`, `initial_language_name`, `initial_bot_message` and `initial_state_name` taken straight from the browser config.
  - `client.media.audio_chunk`.
  - `client.media.text` (chat mode).
  - `client.system.pong`, sent in reply to `server.system.ping`.
- **[CORRECTION] Declared in the enum but never sent by any public SDK method in 0.0.42:** `client.action.variable_update`, `client.action.state_transition`, `client.action.language_change` and `client.action.interaction_end`. The `ClientMsg` union type does not even include them. The earlier report's wording "the client can send `variable_update`" is therefore true only of a hand-crafted WebSocket message. Whether the server accepts such messages is **UNVERIFIED**.
- **The more practical risk** is `interaction_start` itself. Any browser user can edit `agent_variables`, `initial_state_name` or `initial_bot_message` before connecting, because the browser builds this message after it receives the signed URL.

**Server-side locking.** **UNVERIFIED**: no docs page describes locking client-supplied variables or states.
- The only "read-only" statement is about **Sarvam system variables** (`current_date`, `start_datetime`, …): "Sarvam variables are read-only." (https://docs.sarvam.ai/voice-agents/build/variables-personalization.md, **VERIFIED**). It does not cover agent variables.
- Docs list the input-variable sources as telephony metadata, the **on-start hook** and campaign CSV columns, and say tools "can read and write any agent variable mid-call".
- A server-authoritative option is the on-start hook (https://docs.sarvam.ai/voice-agents/build/on-start-on-end-hooks.md, **VERIFIED** to exist). It is "an API call fired at call start" whose response is mapped into agent variables. The docs do not say whether it fires for web/SDK sessions, or whether its values override client-sent `agent_variables` (**UNVERIFIED**).

## 4. Outbound call webhook

**Create call (VERIFIED, https://docs.sarvam.ai/voice-agents/api/instant-outbound/create.md):**
- Request: `POST https://apps.sarvam.ai/api/outbounds/v1/orgs/{org_id}/workspaces/{workspace_id}/outbounds` with header `X-API-Key`.
- Body:
  - `app_config`: `app_id`, `app_version` (required), `connection_config{connection_id, agent_phone_number}`, `agent_variables`, `app_type` (default `agent`) and `app_overrides` (`initial_bot_message`, `initial_state_name`, `initial_language_name`).
  - `user_config`: `user_phone_number`.
  - `webhook_config`: `url` (required) and `metadata` (an optional map).
- Response: `200 {attempt_id}`. Errors: `422`.

**Webhook payload (VERIFIED, https://docs.sarvam.ai/voice-agents/api/instant-outbound/webhook-payload.md).** Sarvam POSTs "After each instant outbound call attempt completes — whether or not it connected". The fields are:

| Field | Notes |
|---|---|
| `attempt_id` | "Matches the `attempt_id` returned in the Create Instant Outbound Call response." |
| `status` | `connected`, `no_answer`, `busy`, `failed` |
| `channel_info` | `channel_type` (`"v2v"` or `"whatsapp"`), `channel_provider` (e.g. `"exotel"`), `agent_phone_number` (E.164) |
| `duration` | seconds (number) or `null` if not connected |
| `interaction_id` | e.g. `"20250920/1ae056a30013510b66a6a0"`, or `null` if not connected |
| `failure_reason` | e.g. `"exotel: Phone number is registered under TRAI NDNC"`, or `null` |
| `final_agent_variables` | object or `null` |
| `webhook_config` | `{url, metadata}`, "echoed back in every payload" for correlation |
| `interaction_transcript` | `[{role: "agent" or "user", en_text}]` or `null` (English or translated text only) |

**Webhook authentication.** **UNVERIFIED, and I believe it is not offered.** No page I fetched mentions a signature, HMAC, signing secret or verification header for any Voice Agents webhook. I checked the instant-outbound, campaigns and deployments payload pages, the campaigns and inbounds pages, and the webhook list page. `WebhookConfig` has only `url` and `metadata`, with no headers field. The Secrets page says "Use **Settings → Secrets** for Webhook authentication headers and tokens" (https://docs.sarvam.ai/voice-agents/settings/secrets.md). That is the only hint, and from context it applies to tool/hook configs. It is not shown on `webhook_config` for instant outbound. Our safest approach:
- Put an unguessable per-call token in the webhook URL path or query, and/or in `metadata`.
- Check `attempt_id` against our own stored record.
- Never trust `final_agent_variables` without cross-checking through the Analytics API.

**Status / get-attempt API.**
- There is no instant-outbound GET-by-id endpoint. The only instant-outbound reference page is "Create outbound call".
- There is no delivery-list or retry endpoint for instant outbound. Campaigns and deployments have `webhooks/list` and `webhooks/retry`, which re-deliver up to 200 attempts per request.
- The documented substitute is **Analytics `List attempts`**: `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/attempts?start_datetime=…&end_datetime=…&filter_conditions=[{"field":"attempt_id","operator":"equals","value":"<id>"}]` with `X-API-Key`. `attempt_id` is a filterable identifier.
- The response returns `connectivity_status`, `failure_reason`, `ended_by`, `duration_in_seconds`, `interaction_id` and more. Responses are "cached for 60 seconds" and include "full, unmasked" `user_contact`. The API is rate-limited per key with `429` + `Retry-After`.
- Sources: **VERIFIED**, https://docs.sarvam.ai/voice-agents/api/analytics/attempts.md and https://docs.sarvam.ai/voice-agents/api/analytics/overview.md.

## 5. Bulbul V3 end of life / V4 migration

**VERIFIED.** The deadline is **November 10, 2026**.
- https://docs.sarvam.ai/voice-agents/build/voice-language.md (banner): "Bulbul V3 reaches end of life on Voice Agents on **November 10, 2026**. Switch your agents to **Bulbul V4** before then in the [Model] setting, and use the [V3 to V4 name mapping] to keep the voice you use today. Bulbul V3 stays available on the Text-to-Speech API."
- Changelog, **October 14, 2026** (https://docs.sarvam.ai/changelog/2026/10/14.md), "Bulbul V3 End of Life for Voice Agents": "Switch every agent that speaks with Bulbul V3 to Bulbul V4 before that date. In the agent's **Settings**, set the model under **Speaking** to **Bulbul V4** and pick a voice. … This change applies to Voice Agents only."
- Changelog, **October 6, 2026** (https://docs.sarvam.ai/changelog/2026/10/6.md): Bulbul V4 became available for Voice Agents. V4 voices have new display names, e.g. "**Shubh** is now **Shubh - Hinglish Ad Voice**" and "**Ritu** is now **Ritu - Hindi Support Agent**".

As of 2026-10-21 that leaves **20 days**. The change is made in the dashboard, on the agent's Settings, and probably creates a new committed version. Any code that pins `app_version` or `version` must then be bumped to the new committed version.

## 6. Concurrency limits per plan

**VERIFIED**, https://docs.sarvam.ai/voice-agents/pricing.md ("Rate limits"):

| Plan | Concurrent calls | Calls started per minute |
|---|---:|---:|
| Pay as you go | 4 | 20 |
| Pro | 10 | 50 |
| Growth | 30 | 150 |
| Business (coming soon) | 120 | 600 |
| Enterprise | Custom | Custom |

The pricing page says: "Limits apply across your organisation. Every campaign, instant outbound call, and inbound call counts toward them, and a call that would go past a limit is rejected." The dialing-rate page (https://docs.sarvam.ai/voice-agents/deploy/campaigns/dialing-rate.md) says ceilings are "shared across everything that dials". A separate "concurrent agent campaign limit" exists, and upgrading the plan does not raise it. Whether **web/SDK sessions** count against the same pool is **UNVERIFIED**, because neither page mentions them. The Analytics API has its own per-key rate limit (configured per org; `429` + `Retry-After`).

---

## What this means for implementation

**Safe to build now, without credentials or any paid call:**
1. **Signed-URL proxy route** (for example FastAPI `GET /api/sarvam/orgs/{org}/workspaces/{ws}/apps/{app}/url`):
   - Authenticate our user.
   - Ignore the path IDs and `version` sent by the browser, and substitute the server-configured `org_id`, `workspace_id`, `app_id` and pinned `version`.
   - Drop the incoming `X-API-Key` and add the real key from the server environment.
   - Forward `interaction_type=call`.
   - Return `{url, reference_id}` unchanged.
   - Add a per-tenant concurrency gate and a rate limit.
   - Map Sarvam 401/403/404/429/5xx to the same codes so the SDK's typed errors still work.
   - Unit-test it with a mocked upstream.
2. **React component** using `ConversationAgent` and `BrowserAudioInterface` from `sarvam-conv-ai-sdk/browser`. Pin the version to exactly `0.0.42`, since the package is 0.0.x with no changelog. Set `apiKey: ""`, `baseUrl: "/api/sarvam/"` and `customHeaders: {Authorization: "Bearer <session>"}`. Drive the UI from `stateCallback`, the transcript from `transcriptCallback` and metrics from `telemetryCallback`. Call `start()` on a click and `stop()` on unmount. Handle a drop by building a new agent (no reconnect).
3. **Do not pass scoring-relevant data as browser `agent_variables`.** Treat anything sent in `interaction_start` as user-controlled.
4. **Outbound webhook receiver** built against the documented payload:
   - Make it idempotent on `attempt_id`.
   - Put a random per-call token in the URL or `metadata`, and verify it.
   - Validate `status` against the four documented values.
   - Treat the null fields as possible.
   - Reconcile through Analytics `List attempts` filtered by `attempt_id`, allowing for the 60-second cache.
   - Unit-test with the three example payloads from the docs page.
5. **Bulbul V4 migration checklist.** List every agent and pinned `app_version` in our config so the versions can be bumped once the dashboard change is committed.

**Needs a live test, with the user's approval (uses the API key and billed minutes):**
1. Mint one signed URL through the proxy. Record the response shape, TTL (retry after 30 s, 2 min, 10 min), and single-use behaviour.
2. Check whether changing `user_identifier` or sample-rate params on the signed URL is rejected, i.e. whether the signature binds them.
3. Check whether a hand-crafted `client.action.variable_update` or `state_transition` is accepted, and whether browser `agent_variables` override the on-start hook. Run this on a test agent only.
4. Check whether a web session counts toward plan concurrency and is billed per 60-second pulse. Check whether it appears in Call Logs and the recordings API, and which `channel_type` and `channel_protocol` it reports.
5. Capture a real instant-outbound webhook to see the delivery headers (any signature or user-agent) and the retry behaviour when our endpoint returns non-2xx.
6. Commit Bulbul V4 on each agent in the dashboard before **2026-11-10** and test one call per agent. This is the user's action, and it is time-critical.

## Sources (all fetched 2026-10-21)

- https://docs.sarvam.ai/voice-agents/llms.txt, https://docs.sarvam.ai/llms.txt, https://docs.sarvam.ai/changelog/llms.txt
- https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md
- https://docs.sarvam.ai/voice-agents/deploy/sdks/python.md
- https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code.md
- https://docs.sarvam.ai/voice-agents/api/introduction.md
- https://docs.sarvam.ai/voice-agents/api/instant-outbound/create.md
- https://docs.sarvam.ai/voice-agents/api/instant-outbound/webhook-payload.md
- https://docs.sarvam.ai/voice-agents/api/campaigns/webhooks/webhook-payload.md, https://docs.sarvam.ai/voice-agents/api/campaigns/webhooks/list.md
- https://docs.sarvam.ai/voice-agents/api/deployments/webhooks/webhook-payload.md
- https://docs.sarvam.ai/voice-agents/api/analytics/attempts.md, https://docs.sarvam.ai/voice-agents/api/analytics/overview.md
- https://docs.sarvam.ai/voice-agents/deploy/campaigns.md, https://docs.sarvam.ai/voice-agents/deploy/inbounds.md, https://docs.sarvam.ai/voice-agents/deploy/campaigns/dialing-rate.md
- https://docs.sarvam.ai/voice-agents/settings/secrets.md
- https://docs.sarvam.ai/voice-agents/build/variables-personalization.md, https://docs.sarvam.ai/voice-agents/build/states-conversation-flow.md, https://docs.sarvam.ai/voice-agents/build/on-start-on-end-hooks.md
- https://docs.sarvam.ai/voice-agents/build/voice-language.md, https://docs.sarvam.ai/voice-agents/build/models.md
- https://docs.sarvam.ai/voice-agents/pricing.md
- https://docs.sarvam.ai/changelog/2026/10/14.md, https://docs.sarvam.ai/changelog/2026/10/6.md (also scanned 10/16, 10/12, 10/10)
- https://registry.npmjs.org/sarvam-conv-ai-sdk and the 0.0.42 tarball. Files read: `package.json`, `README.md`, `dist/browser.d.ts`, `dist/conversation.d.ts`, `dist/modules/socket-manager.js`, `dist/modules/voice-agent.js`, `dist/utils/message.js`, `dist/types/{types,config,events,actions,state,telemetry,errors,text}.d.ts`, `dist/interfaces/browser.js`
- Not reachable: https://unpkg.com/sarvam-conv-ai-sdk@0.0.42/ (the egress proxy refused it). I did not try jsdelivr because the registry tarball covered the same files.

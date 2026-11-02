# Phase 5: Browser voice (Sarvam Web SDK) security review

*Checked on 2026-10-21. This was read-only research. I called no Sarvam API, used no credentials and made no paid request. Builds on `docs/phase3_sarvam_verification.md`, `docs/phase4_sarvam_capabilities.md` and `docs/phase4_security_privacy.md` (section 4).*

**Decision: NO-GO** for browser voice training, in both its current form and the "signed URL to the browser" design. Section 7 gives the reasons and what would change the decision.

## 1. Date and sources

**npm registry (fetched 2026-10-21):**
- `npm view sarvam-conv-ai-sdk time --json`: the last version is `0.0.42`, published `2026-03-30T11:19:16.625Z`. `modified` is `2026-03-30T11:19:16.752Z`. `dist-tags.latest` is `0.0.42`. **There is nothing newer than 0.0.42.** That is about 7 months with no release.
- Tarball: `https://registry.npmjs.org/sarvam-conv-ai-sdk/-/sarvam-conv-ai-sdk-0.0.42.tgz`. Its sha512 matches the registry `dist.integrity` (`sha512-8JfpHNln…D1mag==`). I unpacked it into `/tmp/claude-0/-home-user-didm-automation/ef37ba3f-3b71-5fd0-af12-b7ad3be07a60/scratchpad/sdk-0.0.42/x/package/` and only read it. Nothing was installed or run.
- Not inspected, but relevant to section 4: the Python SDK `sarvam-conv-ai-sdk` on PyPI is at `1.1.1`, uploaded `2026-09-22T13:01:27Z`. It is maintained more recently than the JS SDK.

**Sarvam docs** (Markdown versions, fetched 2026-10-21):
- https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md (`/conversations/...` redirects here with a 308)
- https://docs.sarvam.ai/voice-agents/deploy/sdks/python.md
- https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code.md
- https://docs.sarvam.ai/voice-agents/build/on-start-on-end-hooks.md
- https://docs.sarvam.ai/voice-agents/build/variables-personalization.md
- https://docs.sarvam.ai/voice-agents/build/conversation-settings.md
- https://docs.sarvam.ai/voice-agents/build/states-conversation-flow.md
- https://docs.sarvam.ai/voice-agents/build/tools/core-tools.md
- https://docs.sarvam.ai/voice-agents/pricing.md (I used only its billing-unit and rate-limit rules)
- https://docs.sarvam.ai/voice-agents/settings/api-key.md
- https://docs.sarvam.ai/voice-agents/deploy/overview.md
- https://docs.sarvam.ai/voice-agents/api/analytics/interactions.md
- https://docs.sarvam.ai/voice-agents/api/analytics/overview.md
- https://docs.sarvam.ai/voice-agents/llms.txt
- https://docs.sarvam.ai/changelog/llms.txt. The newest entry is still October 16, 2026, so nothing has been added since Phase 4.

**Web search:** "Sarvam voice agents web SDK signed URL agent_variables server-side lock" returned only the SDK, API-key and deploy-with-code pages above. None of them mentions a lock.

**Our code** (paths relative to the repo):
- `app/integrations.py:144-168` (`SarvamWebAuth`)
- `app/saas/training.py:483-547` (browser authorize/events) and `:672-713` (sweep)
- `app/saas/training_api.py:197-216`
- `app/saas/providers.py:80-95`
- `Dockerfile:21`, `render.yaml`

In the tables below, `sm.js` means `dist/modules/socket-manager.js`, `va.js` means `dist/modules/voice-agent.js`, `bi.js` means `dist/interfaces/browser.js` and `msg.js` means `dist/utils/message.js`. All are in the 0.0.42 tarball.

## 2. Status labels

| Label | Meaning |
|---|---|
| **VERIFIED** | Stated on a docs.sarvam.ai page (quoted), or seen in the 0.0.42 tarball at the file:line given. Package-source facts can change in any release. |
| **UNDOCUMENTED** | Neither the docs nor the package settle it. Needs Sarvam to answer in writing, or a live test. |
| **CONTRADICTED** | The docs say one thing and the 0.0.42 source does another, or an earlier finding of ours is wrong. |
| *Inferred* | My own reasoning from the evidence, not a stated fact. It is marked in the text. |

## 3. Verified SDK capability matrix (sarvam-conv-ai-sdk 0.0.42)

| Capability | What the SDK / docs say | Evidence | Status |
|---|---|---|---|
| **Server-enforced variables** | The browser builds `client.action.interaction_start` from its own config, with `agent_variables`, `initial_language_name`, `initial_bot_message` and `initial_state_name`. It sends this as soon as the socket opens. Docs: `agent_variables` "Seed agent variables at session start". The documented input-variable sources are "Telephony metadata", the "On-start hook" and "Campaign row fields". No page says whether client-sent values are locked, ignored or overridden by the on-start hook. The only read-only statement is "Sarvam variables are read-only", which covers system variables such as `current_date`. Tools "can read and write any agent variable mid-call". | `msg.js:5-15`; `sm.js:651-658` (send), `sm.js:500` (called on `open`); web.md InteractionConfig table; variables-personalization.md | Client control: **VERIFIED**. Server lock: **UNDOCUMENTED** |
| **Server-enforced identity** | `user_identifier` and `user_identifier_type` are appended to the URL in the browser *after* the signed URL is returned (`addUserIdentifierParamsToString(signedUrl)`). Then `interaction_type` is appended. Docs: `user_identifier` is "also what you search by in Log Analyser". Nothing says whether the signature covers these parameters. | `sm.js:281-285`, `sm.js:382`, `sm.js:290-292` | Appended client-side: **VERIFIED**. Signature binding: **UNDOCUMENTED** |
| **Signed URL secrecy** | The SDK prints the signed URL twice: `console.log("[SDK] Got signed URL:", signedUrl)` and `console.log("[SDK] Final WebSocket URL:", wsUrl)`. It also prints the request URL (`sm.js:312`). It writes any server message type that `parseServerMessage` does not list to the console in full: `console.warn("[SDK] Full message:", JSON.stringify(data…))`. That list leaves out `server.event.transcription`, `variable_update`, `tool_call`, `kb_query`, `state_transition` and `user_speech_*`, so if the server sends them (*inferred*), every transcript turn and any variable or tool event ends up in the console. No docs page mentions this logging. | `sm.js:125`, `sm.js:130`, `sm.js:312`; `msg.js:27-41`; enum `dist/types/types.d.ts:81-97` | **VERIFIED** (URL is logged) |
| **URL lifetime** | Source comment: "a time-limited signed URL". Docs: "each WebSocket URL is single-use." No TTL value is given anywhere. Our code assumes 60 s (`app/integrations.py:153`). | `sm.js:296`; web.md Note | Single use: **VERIFIED**. TTL: **UNDOCUMENTED** |
| **Billing for web sessions** | Pricing: "billed per minute of conversation"; "A minute is one 60-second pulse, and each call is rounded up to whole pulses"; "Only calls that connect are charged." Every example is a phone call. Web/SDK sessions are not mentioned. Analytics `List interactions` exposes `channel_protocol` (e.g. `websocket`) and `duration_in_seconds`, but no cost field. | pricing.md; interactions.md | **UNDOCUMENTED** for web |
| **Concurrency** | "Limits apply across your organisation. Every campaign, instant outbound call, and inbound call counts toward them, and a call that would go past a limit is rejected." Web/SDK sessions are not listed. The signed-URL endpoint can answer 429, which the SDK maps to `RateLimitError` and reads `x-retry-after` (default 60). | pricing.md "Rate limits"; `sm.js:334-342` | **UNDOCUMENTED** for web |
| **End-of-session callback / webhook** | Documented webhooks are instant outbound, campaigns and deployments (inbound) only. The generic on-end hook exists ("The on-end hook fires and pushes final variable values to your endpoint"), but no page says whether it fires for SDK/web sessions. Instead we could poll Analytics `List interactions` filtered by `interaction_id` or `user_identifier`. `reference_id` is not in the filterable identifier list (`interaction_id`, `attempt_id`, `job_id`, `user_id`, `user_identifier`, …). | llms.txt webhook pages; variables-personalization.md lifecycle table; analytics overview.md "Identifiers" | **UNDOCUMENTED** for web |
| **Server termination** | There is no documented API to end a live interaction. The index has no terminate/hang-up endpoint. One agent-level setting is server-side: "Max call length ends the call after a set number of minutes (up to 60). When the limit is reached, the agent wraps up and hangs up." Also "Hang up after unanswered nudges", and the core tool "End call: Lets the agent hang up". The docs do not say whether these apply to web sessions (*inferred*: probably, since they are agent settings). | llms.txt; conversation-settings.md; core-tools.md | API: **UNDOCUMENTED** (absent). Agent cap: **VERIFIED** to exist, web applicability **UNDOCUMENTED** |
| **Client termination** | `stop()` sets `sessionEndInitiator="user"`, stops the audio interface, calls `ws.close()`, sets `IDLE` and calls `endCallback`. It never sends `client.action.interaction_end`, which is declared in the enum but has no sender. `endCallback` fires **only** from `stop()` or when a `server.action.interaction_end` message arrives. The socket `close` handler does neither: it emits `ws_disconnected` / `session_ended` telemetry only. So a network drop or a server-side close without that message gives no `endCallback` and no state change. Phase 3 wrote "`server.action.interaction_end`, or a socket close, triggers `endCallback`", and the socket-close part is wrong. | `sm.js:148-169`; `sm.js:542-569`; `sm.js:759-767`; `types.d.ts:108` | stop(): **VERIFIED**. Phase 3 endCallback claim: **CONTRADICTED** |
| **Mic permission handling** | `getUserMedia` is tried 3 times: with `sampleRate`, then without it, then `{audio:true}`. Constraints are `channelCount:1, echoCancellation, noiseSuppression, autoGainControl`. The mic is requested **only after the WebSocket opens and `interaction_start` has been sent** (`onWebSocketOpen`, `va.js:251-273`, called at `sm.js:502` after `sm.js:500`). `start()` does not await the socket loop (`sm.js:134`), so a `NotAllowedError` rejects an un-awaited promise (`sm.js:507-510`) and is never thrown from `start()`. The socket is not closed on that path. The docs' troubleshooting example wraps `await agent.start()` in `try/catch` and checks `err.name === "NotAllowedError"`. In 0.0.42 that catch cannot see a mic denial. *Inferred:* a denied mic leaves a connected session open (and possibly billed) until the agent's nudge/max-length settings or `stop()` end it. | `bi.js:243-263`; `va.js:251-273`; `sm.js:134`, `sm.js:492-510`; web.md "Microphone permission errors" | **CONTRADICTED** |
| **Browser compatibility** | Uses `fetch`, `WebSocket` (`sm.js:486`), two `new AudioContext()` (no `webkitAudioContext` fallback, `bi.js:68-69`), `AudioWorklet` loaded from a `blob:` URL with a `data:` URL fallback (`bi.js:228-241`), `AudioWorkletNode` (`bi.js:197`) and `navigator.mediaDevices.getUserMedia` (`bi.js:251`). Docs: "HTTPS is required for the microphone in production"; "Firefox requires a user gesture before playing audio". No supported-browser list is published. *Inferred, from general web-platform knowledge, not checked in this research:* current Chrome, Edge, Firefox and Safari 14.1+ (desktop and iOS) support all of these. Older Safari without `AudioWorklet`, or a page whose CSP blocks `blob:`/`data:` scripts, will fail at start. Our CSP would need `script-src`/`worker-src` to allow `blob:` (*inferred*), plus `connect-src` for the WebSocket host. | as listed; web.md Troubleshooting | APIs used: **VERIFIED**. Browser list: **UNDOCUMENTED** |
| **Reconnection** | "Reconnection is not supported: each WebSocket URL is single-use. If the connection drops, call `stop()` and create a new `ConversationAgent`." There is no reconnect code in the package. The SDK only emits `network_offline` / `network_online` telemetry. | web.md Note; `sm.js:431-470` | **VERIFIED** (not supported) |

**What changed since 0.0.42:** nothing. No new npm version has been published, and the docs and changelog have nothing on these topics after 2026-10-16. This session found three new things in the 0.0.42 source: the `endCallback` correction, the mic-after-connect ordering, and full-message console logging of unknown server events.

## 4. Server-controlled gateway evaluation

**Idea.** The browser never receives Sarvam's signed URL. Our server opens the upstream Sarvam WebSocket itself, writes the start message, and relays audio both ways.

**Protocol facts I verified:**
1. **The browser SDK connects to whatever `url` our proxy returns.** The SDK fetches `{baseUrl}orgs/{org}/workspaces/{ws}/apps/{app}/url`, reads `url` and `reference_id`, and opens `new WebSocket(url + params)` (`sm.js:268-270`, `sm.js:367-386`, `sm.js:486`). `baseUrl` is ours ("Point `baseUrl` at a backend you control", web.md). So our endpoint can return `wss://<our-host>/…/<one-time-id>`, and the unmodified SDK connects to our gateway instead of to Sarvam. VERIFIED from source, client side.
2. **Sarvam documents server-side sessions and a backend proxy.** Python docs: "This is also the pattern for a backend proxy: terminate the caller's audio stream on your server, forward frames to `send_audio`, and relay `transcript_callback` / `audio_callback` output back to the client." Also: "run `AsyncSamvaadAgent` itself on your server and proxy audio to the frontend". Deploy with Code: "Keep secrets server-side and proxy WebSocket connections through your backend when building client-facing applications." So the server can write the session start, including `agent_variables` and `initial_state_name`. This is VERIFIED from the Python `InteractionConfig` table, which has the same fields. The Python table does **not** list `initial_bot_message`.
3. The browser messages that 0.0.42 actually sends are `client.action.interaction_start`, `client.media.audio_chunk` and `client.system.pong` (`msg.js:5-15`, `va.js:195-205`, `sm.js:772-783`). A gateway can parse every frame. VERIFIED: the messages are JSON with a `type` field.

**What a gateway would secure:**
- **The signed URL never reaches the browser.** The console log at `sm.js:125` and `sm.js:130` would print only our one-time gateway URL.
- **The start message.** The gateway drops the browser's `interaction_start` and sends its own, built from `training_sessions.resolved_variables`, the pinned version, and our own `user_identifier` (e.g. the session id).
- **Later client messages, but only if the gateway filters.** It must forward only `client.media.audio_chunk` and `client.system.pong`, and close the connection on anything else. A pass-through relay would forward a hand-made `client.action.variable_update` or `state_transition`. Whether Sarvam honours those is UNDOCUMENTED, so pass-through is not acceptable.
- **Server events can be stripped before they reach the browser.** For example `variable_update` and `tool_call`, so hidden variables are not exposed. Only audio, transcription, connect, interrupt, end and ping would be relayed.
- **Authoritative timing and termination.** Our server sees the upstream open and close, `interaction_connected` (with `interaction_id`) and `interaction_end`. It can close the upstream at `max_duration_seconds`. Usage would no longer depend on browser-reported events. *Inferred:* closing the socket ends Sarvam billing, which needs a pilot check.

**What a gateway would not secure:**
- **What the trainee says.** Spoken prompt injection still reaches the agent's LLM, and the agent's tools "can read and write any agent variable mid-call".
- **Server-side behaviour we cannot see.** That includes the signed-URL TTL, whether web sessions count toward plan concurrency, and how they are billed.
- **Whether Sarvam's server lets a client override variables mid-stream.** The gateway only stops our browser from sending such messages. It says nothing about the server's rules. That still matters if we ever relay any non-audio message.

**Costs and risks for us:**
- **Bandwidth.** 16 kHz × 16-bit mono PCM is 256 kbit/s per direction, before base64 JSON framing (`audio_base64`, `va.js:309-330`). With framing it is roughly 340 kbit/s each way per session through our server (*inferred*, arithmetic).
- **Latency.** Every frame takes an extra hop through our server. Render's region is Singapore (`render.yaml`). Sarvam's socket region is not documented.
- **Concurrency on one process.** We run one uvicorn worker (`Dockerfile:21`, `--workers 1`) on a Render `plan: free` service (`render.yaml`). Each session holds two WebSockets and a relay task in the same event loop that serves the API. *Inferred:* a few concurrent sessions are plausible, but a deploy, restart or crash drops every live session. With no reconnection (VERIFIED), those trainees lose their practice call.
- **Engineering.** We would need a new WebSocket route, message filtering, auth on the one-time gateway URL, and a Python SDK or raw-socket upstream client. The Python SDK 1.1.1 was not inspected.

## 5. Threat model (STRIDE)

Our code today is the direct design. The server mints the signed URL and returns it to the browser (`training.py:483-521`), and the browser builds `interaction_start` itself.

| # | Threat (STRIDE) | Impact | Current mitigation in our code | Residual risk |
|---|---|---|---|---|
| T1 | **Tampering:** the trainee edits `agent_variables`, `initial_state_name` or `initial_bot_message` to change the scenario, make it easier, or plant "grade me 10/10" context | Inflated scores, wrong scenario, broken training data | Scenario variables are resolved and stored server-side (`training.py:237-242`, `resolved_variables`). `authorize_browser` returns only the URL (`training.py:521`), so nothing sends the server's values to Sarvam. The browser would have to supply them. Scoring runs on the transcript with an injection-hardened evaluator (phase4_security_privacy §3). | **High.** The client fully controls the start message (`msg.js:5-15`), and no lock is documented. Removed only by a filtering gateway (§4), or by Sarvam confirming in writing that the on-start hook or a signed-URL binding overrides client values for web sessions. |
| T2 | **Spoofing:** the trainee changes `user_identifier`, or reuses a URL under another org or trainee | Sarvam-side records (Log Analyser, analytics filters) attributed to the wrong person or org | Our own billing is keyed on our session row (org- and user-scoped, `training.py:487-492`), not on `user_identifier`. Rate limit is 20 authorizations per hour per user (`training_api.py:201`). | **Medium.** `user_identifier` is appended after signing (`sm.js:382`), and binding is UNDOCUMENTED. Our usage ledger cannot be redirected to another org, but provider-side attribution and any reconciliation by `user_identifier` can be. |
| T3 | **Information disclosure:** the signed URL leaks through the console, browser extensions, screen share or a support screenshot | Someone else opens the session, which uses our minutes and our agent | URL is not stored or logged by us (`training.py:509-521`, only a SHA-256 is kept). TTL is assumed 60 s. Single-use is VERIFIED. | **Medium.** The SDK logs it (`sm.js:125`, `sm.js:130`). With single use, a leaked URL helps only if it is used before the trainee's own connect. The TTL is unknown. The SDK also logs whole unknown server events (`msg.js:39-40`), which may include transcripts or variables. |
| T4 | **Spoofing / elevation:** URL replay | A second session on one authorization | `already_authorized` state check (`training.py:493-497`); one token row per session | **Low to medium.** Depends on Sarvam's single-use enforcement (VERIFIED in docs, untested) and the unknown TTL. |
| T5 | **Denial of service / cost:** concurrency exhaustion or a running bill. Many tabs, a never-closed tab, mic denied after connect, or the client never reporting "ended" | Plan concurrency used up, which blocks phone training org-wide (*inferred*, if web shares the pool). Minutes billed that our ledger does not record. | Org and user capacity caps with reservations (`_check_capacity`); the sweep times out `connecting`/`active` sessions after `max_duration_seconds` + grace (`training.py:693-706`). Billable time comes from client-reported `connected`/`ended` (`training.py:523-541`). | **High.** We have no server-side way to end a web session (no API documented). A client that never sends `connected` produces 0 billable seconds while Sarvam may bill. The mic-denial path leaves the socket open (§3). Partial fix: set the agent's **Max call length** to our session cap, and enable "Hang up after unanswered nudges". |
| T6 | **Tampering (in-band):** prompt injection by the trainee speaking | The agent leaves its role, reveals instructions, or a tool writes variables mid-call | The evaluator treats the transcript as fenced data, quotes must be real trainee turns, and the overall score is computed by us (phase4_security_privacy §3) | **Medium.** This is the same as on phone. No gateway can filter speech. Keep scoring out of the voice agent's variables entirely. |
| T7 | **Repudiation / integrity:** transcript attached to the wrong session | Wrong scorecard or the wrong trainee's words | Phone uses `attempt_id` from our own create call. For browser, `authorize_browser` stores the signed-URL `reference_id` as `provider_session_id` (`training.py:513`), and `SarvamTranscriptSource.fetch` looks it up as an **`interaction_id`** (`providers.py:84-90`). | **High (bug).** `reference_id` and `interaction_id` are separate fields in the SDK (`interaction_connected` carries both: `dist/types/events.d.ts:26`, `sm.js:740-742`). `reference_id` is not a documented analytics filter. Today the lookup would find nothing or something else. The real `interaction_id` is known only to the browser (`getInteractionId()`), or to a gateway. |
| T8 | **Denial of service:** no end-of-call webhook leaves capacity reserved | Capacity held until the sweep, and usage under-counted | The sweep releases the session after max duration + grace (`training.py:693-706`). Usage is then finalized as `timeout` with the measured or capped duration. | **Medium.** No web webhook is documented. Release waits on our timer rather than on the real end, and the real duration is unknown unless reconciled through `List interactions` by `interaction_id` (see T7). |

## 6. Safe architecture proposal

Browser voice may be enabled only when **all** of the following are true:

1. **Gateway, not signed URL.** The browser never receives a Sarvam URL. Our `baseUrl` endpoint returns a one-time `wss://` URL for our gateway. That URL is bound to the session row, valid for one connection, short-lived, and checked against the login cookie.
2. **Server-written start.** The gateway discards the browser's `interaction_start` and sends its own, built from `resolved_variables`, the pinned `provider_app_version`, and `user_identifier = training session id`.
3. **Allow-list filtering in both directions.** Client to Sarvam: `client.media.audio_chunk` and `client.system.pong` only, and anything else closes the session. Sarvam to client: audio, transcription, `interaction_connected`, `user_interrupt`, `interaction_end` and ping only.
4. **Server-owned lifecycle.** The gateway records `interaction_id` from `interaction_connected`, stores it as `provider_session_id` (this fixes T7), takes connect and end times from the upstream socket, and closes the upstream at `max_duration_seconds`. Usage is finalized from these times, not from browser events.
5. **Agent-side caps.** On the Sarvam agent, set "Max call length" to at most our largest `session_minutes`, and enable "Hang up after unanswered nudges". This is a backstop if our gateway dies.
6. **Reconciliation.** After each session, look it up in `List interactions` by `interaction_id` and record `duration_in_seconds`, `channel_protocol` and `ended_by`.
7. **Capacity.** Count web sessions in the same org-wide pool as phone until Sarvam says otherwise. Set a hard per-instance gateway limit sized after a load test. On Render free/one worker, keep it to a small number, or move the gateway to its own paid instance.
8. **Front end.** Pin the SDK to exactly `0.0.42` and review the tarball before any upgrade. Request the mic *before* calling `start()`, with our own `getUserMedia` pre-check, so a denial never opens a session. Call `stop()` on unmount and on `pagehide`.
9. **Written answers from Sarvam** to the questions below on TTL, web billing and concurrency, or pilot results that settle them.

### Questions to send Sarvam

1. Does the app-runtime signed URL (`GET …/apps/{app_id}/url?interaction_type=call&version=N`) have a fixed TTL? What is it, and is single use enforced on the server?
2. Does the URL signature cover `user_identifier`, `user_identifier_type`, `input_sample_rate`, `output_sample_rate` and `interaction_type`, which the SDK appends after signing? If not, can the signing request take `user_identifier` so it is bound?
3. Can the signed-URL request bind `agent_variables`, `initial_state_name` and `initial_bot_message` server-side, so values in `client.action.interaction_start` are ignored?
4. Does the on-start hook fire for SDK/WebSocket sessions? If it does, do its mapped values override `agent_variables` sent by the client?
5. Does the server accept `client.action.variable_update`, `client.action.state_transition` and `client.action.language_change` from a client? Can an agent be set to reject them?
6. Are web/SDK sessions billed like calls, per 60-second pulse from `interaction_connected`, and do they count toward the plan's concurrent-call and calls-per-minute limits?
7. Is there a webhook, or an on-end hook delivery, for SDK/WebSocket sessions? Is there an API to end a live interaction by `interaction_id`?
8. Do "Max call length" and "Hang up after unanswered nudges" apply to SDK/WebSocket sessions?
9. Is `reference_id` (from the signed-URL response) queryable in Analytics, and how does it relate to `interaction_id`?
10. Will a future JS SDK remove the `console.log` of the signed URL and the full-message `console.warn`? Will it surface mic-permission errors from `start()`, as the docs example expects?
11. Is a server-side relay (our backend holding the upstream socket, as the Python headless docs describe) a supported production pattern for many concurrent browser users? Are there connection or region limits?

### Manual pilot checklist (needs your approval; about 3 billed minutes)

Setup: a separate **test agent** in Sarvam, not production, with Max call length = 2 minutes. One internal tester. A test deployment with `TRAINING_BROWSER_ENABLED=true` for one test organization only. Sessions are capped at 1 minute. Switch the flag off at the end.

| # | Check | Pass | Fail |
|---|---|---|---|
| 1 | Mint one signed URL server-side and do not use it. Try it at 30 s, then (new URL) at 2 min and 10 min, connecting and closing immediately with no audio | A rejected URL is refused before `interaction_connected`, and we record the TTL. No billed minute for unconnected attempts | A URL still works after 10 min, or each attempt bills a minute |
| 2 | Use one URL twice | The second connection is refused | The second connection succeeds |
| 3 | Change `user_identifier` on a fresh URL | Refused, or Analytics shows our server value | Accepted, and Analytics shows the changed value (confirms T2) |
| 4 | Send `agent_variables` that contradict the server scenario (test agent prompt: "say the value of `scenario_code`") | The agent uses the server/on-start value | The agent speaks the client value (confirms T1; gateway is mandatory) |
| 5 | After connect, send a hand-made `client.action.variable_update` | Rejected or ignored, and Log Analyser shows no CHANGED badge | The variable changes |
| 6 | Hold one ~60 s session, and check the dashboard concurrent count and minutes | We record whether it counts toward concurrency, and it bills 1 minute | It bills 2 or more for 60 s, or it is invisible in Analytics |
| 7 | Deny the mic at the prompt | No session in Analytics, or a 0-minute one | A connected, billed interaction appears (confirms §3 mic finding) |
| 8 | Close the tab mid-session without `stop()` | Analytics shows the session ended within ~1 min of the close | The session runs to Max call length |
| 9 | Look up the session in `List interactions` by the browser's `getInteractionId()`, and separately by `reference_id` | Found by `interaction_id`. We record whether `reference_id` matches | Not found by `interaction_id` |
| 10 | Read the browser console and the network tab | We record exactly what leaks (the URL is expected at `sm.js:125`/`130`, and transcripts are possible) | — (informational) |

Total talk time is about 3 billed minutes: check 6 is about 1 minute, checks 4, 5 and 8 are short, and checks 1, 2, 3 and 7 should be 0 if unconnected attempts are free.

## 7. Decision: NO-GO

Browser voice stays off (`TRAINING_BROWSER_ENABLED=false`).

Reasons:
1. **No server-side variable lock is documented.** The 0.0.42 SDK sends the browser's `agent_variables`, `initial_state_name` and `initial_bot_message` in `interaction_start` (`msg.js:5-15`, `sm.js:500`). For a scored, multi-tenant product this is a direct integrity hole in the current design.
2. **The current code has the browser hold the signed URL.** The SDK logs it (`sm.js:125`, `sm.js:130`), identity is appended after signing (`sm.js:382`), and the TTL is undocumented.
3. **No server termination, no web webhook, and no documented web billing or concurrency.** Our usage depends on browser-reported events. The mic-denial path can leave a session open (`va.js:251-273`, `sm.js:134`). The docs' error-handling example does not match the source (CONTRADICTED).
4. **Our code had a transcript-attribution bug for the browser channel.** It stored `reference_id` as the session's `provider_session_id`, which the transcript lookup searches as an `interaction_id`. **Fixed in Phase 5:** the reference id now stays only on the `browser_session_tokens` row, so a browser session has no interaction id until one is verified, and the lookup returns nothing rather than someone else's call.
5. **No SDK release in ~7 months.** None of the above has been fixed upstream.

**What would change this to GO:** first, the gateway design in §6, which Sarvam documents as a pattern. Then pilot checks 4–9 passing through the gateway, and written answers to questions 1, 6 and 7. The gateway alone removes T1, T3 and T7 on our side. T5 (billing and concurrency) and T8 (end-of-session) still need Sarvam's answers or pilot evidence.

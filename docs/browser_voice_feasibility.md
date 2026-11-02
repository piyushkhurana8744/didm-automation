# Browser Voice Feasibility: Sarvam AI

*Research date: 2026-10-21. Method: read-only review of Sarvam's public docs, fetched as Markdown with `curl` from `docs.sarvam.ai` (index: `https://docs.sarvam.ai/llms.txt`). I called no paid API, used no API key and signed up for nothing. I also downloaded and read the public npm tarball of `sarvam-conv-ai-sdk@0.0.42` to see how the SDK fetches its signed URL. WebSearch was a secondary source only.*

> Note: `https://docs.sarvam.ai/llms-full.txt` returns HTTP 301 and redirects to `llms.txt`. There is no full-text dump, so I fetched each page on its own.

## Evidence classification

| Label | Meaning |
|---|---|
| **VERIFIED** | We ran it and saw it work. **Nothing in this report is VERIFIED.** |
| **DOCUMENTED BUT NOT TESTED** | Stated on an official Sarvam doc page I fetched (quoted below). |
| **UNVERIFIED** | Comes only from search snippets, third parties, SDK source code, or inference, or I could not find it. |
| **UNSUPPORTED** | Sarvam's docs say it is not supported. |

---

## 0. TL;DR

1. **Sarvam documents a hosted browser channel for Voice Agents.** It comes in two forms: an embeddable website widget, and a browser TypeScript SDK (`sarvam-conv-ai-sdk/browser`, `ConversationAgent` + `BrowserAudioInterface`). The SDK wraps a Voice Agents WebSocket interface and connects through a **signed, single-use WebSocket URL**. The docs say voice agents are "generally available on every channel except WhatsApp". *(DOCUMENTED BUT NOT TESTED)*
2. **Browser security pattern:** the docs tell us to point the SDK's `baseUrl` at our backend and leave `apiKey` empty, so our server adds the Sarvam key. Our backend only mints the signed URL. Then, per the SDK source (UNVERIFIED as a documented contract), **the browser opens the media WebSocket directly to Sarvam**. The API key never reaches the browser.
3. **The pieces for Option B also exist.** Sarvam documents realtime STT over WebSocket with server VAD (`saaras:v3-realtime` / `saaras:v4`), streaming TTS over WebSocket (`bulbul:v3` / `bulbul:v4-flash`) and an OpenAI-style chat API with SSE streaming and tool calling. But the Model APIs have **no ephemeral token mechanism**. The only documented browser auth for STT puts the raw API key in the WebSocket subprotocol, which we must not do. So Option B has to be fully server-proxied.
4. **Recommendation:** start with **Option A via a backend token-minting proxy ("A1")**. It reuses the hosted agents we already run for outbound calls and gets turn-taking, barge-in, recording and analytics for free. If we need server-side control of the audio (integrity, metering, our own recording), use the documented **server-side relay ("A2")**: our FastAPI gateway runs the Python SDK headless. Keep Option B as a fallback only if Sarvam can't answer the questions in §8, or if we need our own LLM or orchestration. Voice Agents does not support bring-your-own models.

---

## 1. Hosted browser / web voice agent channel

| # | Finding | Status | Evidence |
|---|---|---|---|
| 1.1 | A website widget (embed snippet) exists for voice or chat agents | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code.md: "To put a voice or chat agent on your website, embed the widget: … Copy the embed snippet from the dashboard … Paste it into your site, typically before `</body>`." |
| 1.2 | The web channel is GA for voice agents | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/voice-agents/overview.md: "Voice agents are generally available on every channel except WhatsApp." Channel table: "Web: A voice or chat widget embedded in your site". |
| 1.3 | The widget needs no phone number | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/voice-agents/deploy/overview.md: "Copy the ready-made snippet of code from Deploy with Code and paste it into your web page — no phone number needed." |
| 1.4 | How the widget authenticates, whether it allows per-user identity or variables, and its CORS/domain allow-listing | UNVERIFIED (not found in docs) | The docs only say to customize "launcher position, theme, and which agent the widget uses from the dashboard". The api-key page says: "Never embed production keys in client-side widget code". |
| 1.5 | An embeddable **browser SDK**: `npm install sarvam-conv-ai-sdk`, entry point `sarvam-conv-ai-sdk/browser`, classes `ConversationAgent`, `BrowserAudioInterface` | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md: "the TypeScript SDK (`sarvam-conv-ai-sdk/browser`) wraps the WebSocket interface in a typed client, `ConversationAgent`, with `BrowserAudioInterface` for microphone capture and playback." |
| 1.6 | Session setup uses a **signed WebSocket URL** | DOCUMENTED BUT NOT TESTED | Web SDK page: "`agent.start()` fetches a signed WebSocket URL, sends the session start message, and begins streaming." |
| 1.7 | A raw Voice Agents **WebSocket** interface exists (audio frames, turn events, tool-call signals) | DOCUMENTED BUT NOT TESTED (contract not published) | deploy-with-code: "For real-time voice sessions, connect over the Voice Agents WebSocket interface. Handle audio frames, turn events, and tool-call signals according to the API contract." The contract itself is not in the public docs. The page links to the dashboard ("Open Deploy with Code", indus.sarvam.ai/samvaad/deploy/with-code). |
| 1.8 | Signed-URL endpoint: `GET https://apps.sarvam.ai/api/app-runtime/orgs/{org}/workspaces/{ws}/apps/{app_id}/url?interaction_type=call[&version=N]` with header `X-API-Key`, returning `{url, reference_id}`. The SDK then appends `user_identifier`, `user_identifier_type`, `interaction_type`, `input_sample_rate`, `output_sample_rate` as query params on the client side | **UNVERIFIED** (from the public npm package source `sarvam-conv-ai-sdk@0.0.42`, `dist/modules/socket-manager.js` and `voice-agent.js`; not on any doc page) | Source comment: "Makes an HTTP GET request to get a time-limited signed URL for secure WebSocket connections without exposing the API key." Default `baseUrl = "https://apps.sarvam.ai/api/app-runtime/"`. |
| 1.9 | WebSocket message types seen in the SDK: `client.media.audio_chunk`, `client.action.interaction_start/interaction_end/variable_update/language_change/state_transition`; `server.media.audio_chunk`, `server.event.user_speech_start/user_speech_end/user_interrupt/transcription/tool_call/variable_update/state_transition`, `server.action.interaction_connected/interaction_end`, `server.system.ping` | UNVERIFIED (SDK source `dist/types/types.js`) | Not documented. Note that the **client can send `variable_update` and `state_transition`**. This has integrity implications for a training/scoring product (§7). |
| 1.10 | WebRTC for hosted agents | UNVERIFIED (not found) | No Voice Agents page mentions WebRTC. The browser path is a WebSocket carrying 16-bit PCM. |
| 1.11 | Other SDKs: Python (`AsyncSamvaadAgent`), React Native, Flutter (`SamvaadAgent`) | DOCUMENTED BUT NOT TESTED | deploy-with-code SDK list; https://docs.sarvam.ai/voice-agents/deploy/sdks/python.md |

**About our existing analytics:** our outbound-call analytics show `channel_type: "v2v"` and `channel_protocol: "websocket"`. That **hints** that the hosted runtime already carries media over WebSocket, consistent with the "Streaming" telephony channel type on the dialing-rate page. It **does not prove** that a browser can use the same media path, or that the same contract applies. The browser contract is the signed-URL WebSocket above.

### Web SDK session details (DOCUMENTED BUT NOT TESTED, https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md)

- Audio is 16-bit PCM mono. `input_sample_rate` is "`8000` or `16000` Hz"; `output_sample_rate` is "`16000` or `22050` Hz".
- `version` "Pins a specific committed agent version. If omitted, the SDK uses the latest committed version". This maps to the `app_version` we already pass for outbound calls.
- Optional session fields: `agent_variables`, `initial_language_name`, `initial_state_name`, `initial_bot_message`.
- Callbacks: `transcriptCallback`, `audioCallback`, `audioLevelCallback`, `eventCallback` ("Session events such as connect, barge-in, and end"), `stateCallback` (`IDLE`, `CONNECTING`, `CONNECTED`, `LISTENING`, `SPEAKING`, `ERROR`), `startCallback`, `endCallback`.
- Jitter: "`BrowserAudioInterface` uses adaptive buffering to handle network jitter." `prebufferMs` defaults to 700 (300–500 on good networks, 1000–1500 on unstable ones).
- Mute: "While muted, the SDK sends silence so VAD stays stable".
- **Reconnection: UNSUPPORTED.** "Reconnection is not supported: each WebSocket URL is single-use. If the connection drops, call `stop()` and create a new `ConversationAgent`."
- `start()` must be called from a user gesture. The microphone requires HTTPS.

---

## 2. Authentication

| # | Finding | Status | Evidence |
|---|---|---|---|
| 2.1 | Voice Agents platform APIs use the `X-API-Key` header | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/voice-agents/api/introduction.md: "All requests are authenticated with an API key sent in the `X-API-Key` header." |
| 2.2 | Model APIs use the `api-subscription-key` header, or `Authorization: Bearer <key>` | DOCUMENTED BUT NOT TESTED | https://docs.sarvam.ai/api-reference/authentication.md: "`api-subscription-key: YOUR_SARVAM_API_KEY`" … "The API also accepts the same key as a standard `Authorization: Bearer` header on all endpoints". |
| 2.3 | Auth failures on Model APIs return 403 (`invalid_api_key_error`), not 401 | DOCUMENTED BUT NOT TESTED | Same page: "Auth failures return HTTP `403`, not `401`." The Voice Agents analytics API documents 401 and 403 separately. |
| 2.4 | **Browser-safe pattern for Voice Agents:** proxy the signed-URL fetch through our backend | DOCUMENTED BUT NOT TESTED | Web SDK page: "Never embed your API key in client-side code. Point `baseUrl` at a backend you control and leave `apiKey` empty so the proxy adds the Sarvam key server-side." … "For a cross-origin proxy, pass your app's auth in `customHeaders` (for example `Authorization: Bearer` plus your session token)." Python SDK page: "Fetch the signed WebSocket URL from a backend you control, or run `AsyncSamvaadAgent` itself on your server and proxy audio to the frontend". |
| 2.5 | Lifetime of the signed URL (TTL) | UNVERIFIED | The docs say only "single-use". The SDK source says "time-limited". The TTL value is not documented. |
| 2.6 | Whether the signature covers `user_identifier`, `input/output_sample_rate` and the like (the SDK appends these **after** signing) | UNVERIFIED | Inferred from SDK source. If the signature doesn't cover them, a browser could change its own `user_identifier`. Ask Sarvam. |
| 2.7 | **Ephemeral or short-lived tokens for the Model APIs (STT/TTS/LLM)** | UNVERIFIED (not found in docs) | No such mechanism is documented. The only "short-lived JWT" in the docs is for BYOK, where *Sarvam* calls *our* `/auth` endpoint (https://docs.sarvam.ai/voice-agents/api/byok/auth.md). That is unrelated to browser auth. |
| 2.8 | Browser auth for realtime STT puts the **raw key in the WebSocket subprotocol** | DOCUMENTED BUT NOT TESTED. **Do not use**: it exposes the key | https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws.md: "Pass your API subscription key via the `API-SUBSCRIPTION-KEY` header, or (in browsers) via the WebSocket subprotocol `api-subscription-key.<key>` — the server echoes the subprotocol back." |
| 2.9 | Keys are per account. Org-level keys are not supported yet | DOCUMENTED BUT NOT TESTED | authentication.md: "Creating Organisational level keys is not currently supported and will be available soon." |

---

## 3. Streaming STT (for Option B)

All rows below are **DOCUMENTED BUT NOT TESTED**. Sources: https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws.md and https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming.md.

| Item | Detail |
|---|---|
| Endpoint | `wss://api.sarvam.ai/speech-to-text-realtime/ws` ("GET /speech-to-text-realtime/ws"). Legacy: `GET /speech-to-text/ws` (`saaras:v3`, no partials). |
| Models | `saaras:v3-realtime` (default), `saaras:v4` |
| Encoding | "`linear16`, `linear32`, `mulaw`, or `alaw`. Mono only." **No Opus/WebM.** The browser's Opus must be decoded to PCM. |
| Sample rates | "`8000` or `16000` only; any other value closes the connection (code `4000`)." The browser's 48 kHz audio must be resampled to 16 kHz. |
| Audio framing | JSON `{"event": "audio_input", "audio": "<base64>"}`. The example sends about 100 ms chunks (3200 bytes at 16 kHz/16-bit). |
| Partials | `transcript.partial`. `stream_type`: `fast` ("Conversational voice agents where snappy barge-in matters most"), `balanced` (default), `simulated` (no partials). |
| VAD / end of speech | `endpointing=vad` (default) emits `vad.speech_start` / `vad.speech_end`. Tuning: `threshold` 0.3, `silence_duration_ms` 500, `min_speech_duration_ms` 250, `prefix_padding_ms` 300. `endpointing=manual` uses client `speech_start` / `speech_end` / `flush`. |
| Barge-in guidance | "Drive barge-in off `vad.speech_start` or early partials, not `transcript.final`." |
| Mid-stream config | `config.update` → `config.updated` (language, prompt, mode, stream_type, endpointing, and VAD params) |
| Keepalive / lifecycle | `ping`/`pong`, `end`, `session.end` (with `audio_duration_s`, "the billed audio quantity"). Close codes: `1003` (rate limit, quota or invalid key), `1008` (inactivity timeout), `1011` (internal error), `4000` ("Invalid model/language_code/parameter, or account not enabled"). |
| Inactivity timeout / max duration values | UNVERIFIED (not found). The docs list them as close reasons but give no values. |
| Beta / access gating | Close code `4000` includes "beta denied" / "account not enabled", so access may be gated per account. I found **no explicit statement** that realtime STT is beta. Ask Sarvam. |
| Languages | 23 languages plus `auto`: en, hi, bn, kn, ml, mr, or, pa, ta, te, gu, as, ur, ne, kok, ks, sd, sa, sat, mni, brx, mai, doi (all `-IN`). Odia is `or-IN` here and `od-IN` on legacy/TTS. |
| Keyterms | `keyterms` (up to 50, `saaras:v4` only) |
| Third-party latency notes | https://docs.sarvam.ai/api/integration/livekit-production-best-practices.md (official doc about the LiveKit plugin): the plugin buffers "1000 ms on the default `stream_type="balanced"`, 500 ms on `"fast"`". It recommends "Use 16000 for WebRTC" and skipping a local Silero VAD in favour of Sarvam's server VAD. |

## 4. Streaming TTS (for Option B)

All rows are **DOCUMENTED BUT NOT TESTED** unless marked otherwise. Sources: https://docs.sarvam.ai/api-reference/text-to-speech/stream.md, https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket.md, https://docs.sarvam.ai/api/getting-started/models/bulbul.md.

| Item | Detail |
|---|---|
| Endpoint | `wss://api.sarvam.ai/text-to-speech/ws` ("GET /text-to-speech/ws"). Header `Api-Subscription-Key`. |
| Models | `bulbul:v2`, `bulbul:v3`, `bulbul:v4-flash`. The reference marks v4-flash as "Latest model, recommended for new integrations". The bindings default is listed as `bulbul:v2`, while the description calls v3 the "API default when omitted". The defaults conflict, so always pass `model`. |
| Voices | v3: 30+ named speakers (e.g. `shubh`, `aditya`, `ritu`, `priya`, `simran`, `anand`, `roopa`). v4-flash: "200+ persona voices (222 IDs)", e.g. `simran_en_customer`, default `shubh_enhi_ads`. "Malayalam and Odia are not yet offered on v4 Flash." Speaker names are lowercase and must match the model. |
| Sample rates (streaming) | "8000, 16000, 22050, 24000 Hz", default 22050. REST goes up to 48000; "Above 24000 is REST only". |
| Output codec | **Docs conflict.** The API reference says "Audio codec (currently supports MP3 only, optimized for real-time playback)", default `mp3`. The streaming guide and the how-to page list `mp3`, `wav`, `aac`, `opus`, `flac`, `linear16`, `mulaw`, `alaw`. The LiveKit guide recommends `output_audio_codec="linear16"` to cut TTFB. Status: DOCUMENTED (conflicting). This must be tested. |
| Bitrate | 32k/64k/96k/128k/192k (default 128k) |
| Protocol | `config` (must be first; can be resent, and a resend flushes the buffer), `text` (1–2500 chars, "<500 characters" recommended), `flush` ("Forces the text buffer to process immediately"), `ping` ("The connection automatically closes after one minute of inactivity"). Server sends `audio` (base64) and an `event` of type `final` when `send_completion_event=true`. |
| Buffering knobs | `min_buffer_size` 30–200 (default 50), `max_chunk_length` 50–500 (default 150) |
| Cancel / interrupt mid-utterance | UNVERIFIED (not found). There is no documented "cancel" message. For barge-in we would have to stop playback locally and probably close or reopen the socket, or drop the remaining chunks. |
| Latency figures | UNVERIFIED (no numeric TTFB published). The LiveKit guide says: "TTS time-to-first-byte is dominated by connection state, not model speed … Call `prewarm()`". |
| Languages | 11: bn, en, gu, hi, kn, ml, mr, od, pa, ta, te (`-IN`) |

## 5. LLM / chat completions (for Option B)

All rows are **DOCUMENTED BUT NOT TESTED**. Sources: https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview.md, https://docs.sarvam.ai/api-reference/beta-apis.md.

| Item | Detail |
|---|---|
| Endpoints | `POST https://api.sarvam.ai/v1/chat/completions` serves `sarvam-105b` and `sarvam-105b-conversations` ("post-trained for real-time dialogue and voice-agent workloads"). `POST /v2/chat/completions` and `/v2/responses` are **beta, whitelisted per key** ("Beta access is not enabled by default"). V2 adds `gemma4`, `glm5.3`, `deepseekv4.1-flash`. |
| Context | `sarvam-105b`: 128K. `max_tokens` defaults to 2048, and reasoning tokens count toward it. |
| Streaming | "Set `stream: true` to receive the response incrementally over server-sent events". Thinking tokens arrive via `delta.reasoning_content` when `reasoning_effort` is set. |
| Tool calling | OpenAI-style `tools` / `tool_choice`, `finish_reason: "tool_calls"`, then a `role: "tool"` message. Documented for V1. The V2 per-model feature table lost its check-mark icons in the Markdown export, so I couldn't read per-model support. |
| Session affinity | `x-session-affinity` header ("currently supported on the **`gemma4`** model") |
| What Option B must orchestrate | The turn state machine (listening, thinking, speaking), conversation history, prompt/persona per training scenario, tool execution, sentence chunking of LLM deltas into TTS `text`/`flush`, cancelling the LLM stream and TTS playback on barge-in, language switching, and end-of-call logic (max length, nudges). Voice Agents does all of this for us today: https://docs.sarvam.ai/voice-agents/build/run-time.md lists "Interruptions and barge-in", "Long silence", "Language switching", "Pronunciations". |
| BYO model inside hosted agents | **UNSUPPORTED.** https://docs.sarvam.ai/voice-agents/build/models.md: "Voice Agents does **not** support bringing your own models at any part of the stack (ASR, LLM, or TTS)." Also: "The underlying model is managed internally, there is no model picker" (conversation-settings). |

## 6. Languages, concurrency, sessions, recordings, pricing

### Languages (DOCUMENTED BUT NOT TESTED)
- **Voice Agents:** "11 languages: Hindi, Tamil, Telugu, Bengali, Marathi, Gujarati, Kannada, Malayalam, Punjabi, Odia, and Assamese, plus English", including code-mixed speech (https://docs.sarvam.ai/voice-agents/overview.md).
- **Realtime STT:** 23 plus auto. **TTS:** 11 (v4-flash has no Malayalam or Odia voices yet). **Voice Agents TTS:** "Bulbul V3 reaches end of life on Voice Agents on **November 10, 2026**. Switch your agents to **Bulbul V4**" (https://docs.sarvam.ai/voice-agents/build/voice-language.md). **Action item for our existing outbound agents.**

### Concurrency / rate limits (DOCUMENTED BUT NOT TESTED)
- **Voice Agents** (https://docs.sarvam.ai/voice-agents/pricing.md):

  | Plan | Concurrent calls | Calls started per minute |
  |---|---|---|
  | Pay as you go | 4 | 20 |
  | Pro | 10 | 50 |
  | Growth | 30 | 150 |
  | Business (coming soon) | 120 | 600 |
  | Enterprise | custom | custom |

  "Limits apply across your organisation. Every campaign, instant outbound call, and inbound call counts toward them, and a call that would go past a limit is rejected." **The page doesn't say whether web/SDK sessions count against the same pool** (UNVERIFIED). It probably does. Browser sessions would share this pool with our outbound campaigns.
- Platform scale claim: "scale beyond **20,000+ concurrent calls**", "sub-second latencies" (run-time page; marketing-level claim).
- **Model APIs** (https://docs.sarvam.ai/api/getting-started/ratelimits.md): STT WebSocket is 20 / 100 / 100 concurrent (Starter / Pro / Business). TTS WebSocket is 60 / 200 / 1,000 concurrent (bulbul:v3 Starter is 30). Chat is 60 / 200 / 1,000 req/min, but `sarvam-105b(-conversations)` is only 40 / 60 / 120 req/min. **Limits are counted per account, not per key.** WebSocket limiting is burst-sensitive: "Connections opened in a fast burst can be rejected well below the concurrent ceilings … A rejected connection is closed, not queued. The close code is `1003`". For Option B at 100 concurrent sessions, STT tops out at 100 concurrent and the 105B LLM at 120 req/min. With a conversational agent doing roughly 4–6 turns per minute per session, **the LLM rate limit binds first**: about 20–30 concurrent sessions on Business. That is my estimate, so it is UNVERIFIED.

### Session lifecycle and interruptions
- Hosted agent: "**Let callers interrupt** lets the caller talk over the agent while it's speaking; the agent stops and listens", plus "Sound sensitivity" and "Eagerness to respond" sliders. "**Max call length** ends the call after a set number of minutes (up to **60**)". Also "Nudge quiet callers" and "Hang up after unanswered nudges". (https://docs.sarvam.ai/voice-agents/build/conversation-settings.md, DOCUMENTED BUT NOT TESTED.)
- SDK events: Python SDK lists "`interaction_connected`, `user_interrupt` (barge-in), and `interaction_end`". The Web SDK `eventCallback` covers "connect, barge-in, and end". (DOCUMENTED BUT NOT TESTED.)
- Reconnect after a drop: **UNSUPPORTED** (signed URL is single-use; start a new session).
- Echo: the LiveKit guide notes `aec_warmup_duration` of 3.0 s is "Right for WebRTC with a speaker and mic". Whether the hosted runtime does its own echo handling for browser audio is **UNVERIFIED**. In a browser we should enable `getUserMedia` `echoCancellation: true`. It isn't clear whether `BrowserAudioInterface` already does this (UNVERIFIED).

### Recordings (DOCUMENTED BUT NOT TESTED)
- "Every connected call handled by a voice agent is recorded as a single stitched audio file". It is dual-channel WAV: "the **user is recorded on the left channel** and the **agent on the right channel**". "Recording requires stitched audio to be enabled (`enable_stitched_audio` is on by default)." (https://docs.sarvam.ai/voice-agents/monitor/call-recordings.md)
- API: `GET https://apps.sarvam.ai/api/analytics/v1/{org_id}/{workspace_id}/{app_id}/recordings/{interaction_id}` with `X-API-Key`, returns `audio/wav`, 404 if no recording (https://docs.sarvam.ai/voice-agents/api/analytics/recordings.md). The Web SDK exposes `agent.getInteractionId()`, so we can join a browser session to its recording and transcript.
- The docs don't say explicitly that web/SDK sessions get recorded the same way as telephony ("every connected call" suggests yes). UNVERIFIED for the browser channel.
- Retention: per workspace. "Until an Owner sets a retention period, your workspace's data is retained indefinitely." "Zero data retention … is not yet supported for **Voice Agents**" (https://docs.sarvam.ai/api/platform/data-retention.md).

### Pricing (DOCUMENTED BUT NOT TESTED; INR, excluding GST)
- **Voice Agents:** "₹3.50 per minute on pay as you go", Pro ₹3.25 (₹9,999/mo), Growth ₹3.15 (₹49,999/mo), Business ₹3.00 (coming soon), Enterprise custom. "There is no separate model or token charge." Calls are billed in "one 60-second pulse, and each call is rounded up". Telephony is extra, so **browser sessions should cost only the agent minutes**. That is an inference (UNVERIFIED) because the docs don't describe web billing explicitly.
- **Model APIs** (https://docs.sarvam.ai/api/getting-started/pricing.md): STT ₹30/hour (billed per second), Bulbul v3 TTS ₹30 per 10K characters, `sarvam-105b(-conversations)` ₹15 input / ₹5 cached / ₹60 output per 1M tokens. **Bulbul v4-flash pricing is not listed** (UNVERIFIED). New users get ₹100 in free credits.

---

## 7. Option A vs Option B

**Option A: Browser → Sarvam hosted voice agent.** Two sub-variants:
- **A1 (token-mint proxy):** the browser runs the Web SDK with `baseUrl=/api/sarvam/`. Our FastAPI endpoint authenticates our user, picks `app_id`/`version`, adds `X-API-Key` and forwards `GET …/apps/{app_id}/url` to Sarvam. The browser then streams PCM **directly to Sarvam** over the signed WebSocket.
- **A2 (server relay):** the browser streams audio to our FastAPI WebSocket. Our gateway runs `AsyncSamvaadAgent` headless (documented: "terminate the caller's audio stream on your server, forward frames to `send_audio`, and relay `transcript_callback` / `audio_callback` output back to the client"). We are in the media path, but Sarvam still runs the agent.

**Option B: Browser → our gateway → Sarvam STT → LLM → Sarvam TTS → browser.**

| Dimension | A1 (hosted, direct media) | A2 (hosted, relayed media) | B (self-orchestrated) |
|---|---|---|---|
| **Latency** | Best. One hop to Sarvam; models are co-located ("no external network hops between stages"). Playback prebuffer defaults to 700 ms. | Adds one network hop to our gateway (+10–50 ms, region-dependent; estimate). Gateway region matters (Sarvam is India-hosted). | Worst. Each turn crosses the network 3+ times (STT → our server → LLM → our server → TTS), plus TTS cold starts. Getting under a second takes tuning (`stream_type=fast`, VAD silence, prewarmed TTS, LLM TTFT). |
| **Build complexity** | Low. Token endpoint, React component, mapping session to `interaction_id`. | Medium. WebSocket relay, PCM framing, our own jitter buffer and playback, mapping SDK callbacks. | High. Everything listed in "What B requires" below. |
| **Security** | Key stays server-side. Open risks: the browser holds a signed URL (TTL unknown); `user_identifier` is appended after signing; **the client can send `variable_update` / `state_transition`**, so a user could tamper with scenario state or scoring inputs. Needs Sarvam to confirm or allow locking. | Strongest. The browser never talks to Sarvam, and we filter which client messages get through. | Strong (all server-side), but more surface we own: audio parsing, prompt injection into our LLM, tool execution. |
| **Cost** | ₹3.15–3.50 per started minute, all models included; no telephony. | Same Sarvam cost plus gateway bandwidth and compute (a 16 kHz PCM stream is about 256 kbit/s each way). | Model costs, roughly estimated (UNVERIFIED): STT ₹0.50 per minute of streamed audio, TTS about ₹1–1.5 per minute (assuming about 400 chars/min of agent speech at ₹30/10K), LLM about ₹0.1–0.3 per minute. Roughly **₹1.7–2.3/min plus our infra and engineering**. Savings over A are modest and swallowed by engineering effort at our scale. |
| **Observability** | Sarvam Call Logs, Log Analyser (searchable by `user_identifier`), transcripts and recordings APIs, Boards (SQL). Plus our own client telemetry. | Same, plus our own server-side metrics and audio tap. | We build all of it: per-stage latency (STT final, LLM TTFT, TTS TTFB), errors, transcripts. Full control, full cost. |
| **Scalability** | Sarvam plan concurrency (4/10/30/120/custom), probably shared with outbound campaigns. Upgrade or go Enterprise. | Same Sarvam limits, plus scaling our WebSocket gateway (sticky, long-lived connections). | Model API limits: STT WS 100 concurrent (Pro/Business), and 105B at 120 req/min caps us at roughly 20–30 live sessions on Business; burst-sensitive 1003 rejections. We scale the gateway ourselves. |
| **Feature parity with our phone agents** | Same agent, same `app_id`/version, same prompts, tools and knowledge base. | Same. | Must reimplement or port prompts, tools, knowledge base, language switching, nudges, max length, and pronunciation. Behaviour will drift from the phone agents. |
| **Reconnection** | Unsupported. A dropped session means a new session, a new `interaction_id` and a new billed minute. | Browser↔gateway can reconnect, but the gateway↔Sarvam session can't resume. | We could design resume (history lives with us), but STT/TTS sockets restart. |

### What Option B requires us to build
1. **Browser capture:** `getUserMedia` with `echoCancellation`, `noiseSuppression`, `autoGainControl`; an AudioWorklet producing 20–100 ms frames.
2. **Resampling and transcoding:** browser audio is typically 48 kHz float32, and MediaRecorder output is Opus/WebM. STT accepts only 8/16 kHz mono PCM/µ-law/A-law. Either resample to 16 kHz Int16 in the worklet (cheaper) or decode Opus server-side (ffmpeg/libopus, per-session CPU). Base64 the frames into `audio_input` JSON.
3. **Gateway:** FastAPI WebSocket per session with authenticated session tokens (our own short-lived JWT); one STT socket, one TTS socket (prewarmed) and one LLM SSE stream per session; backpressure handling.
4. **VAD and turn-taking:** use Sarvam server VAD (`vad.speech_start/end`, tune `silence_duration_ms`), plus an endpointing hold and handling of false starts. Optionally run client-side VAD only for UI hints. Don't run two VADs that disagree (per the LiveKit guide).
5. **Barge-in:** on `vad.speech_start` or an early partial while the agent is speaking, stop browser playback right away (flush the jitter buffer), cancel the LLM stream, and drop or close the TTS stream (no documented TTS cancel). Mark the truncated agent turn in history. Guard against echo-triggered false interruptions (min words, warm-up window).
6. **LLM orchestration:** turn state machine, history trimming, scenario/persona prompts, tool calls, sentence-boundary chunking into TTS with `flush`, language switching, and handling of `reasoning_content` (disable or keep reasoning low for latency).
7. **TTS playback:** choose a codec (`linear16` at 16/22.05/24 kHz is simplest; MP3 if the "MP3 only" note turns out true), stream to the browser, and run a jitter/prebuffer playout via an AudioWorklet with sample-rate conversion to the AudioContext rate.
8. **Reconnection:** heartbeats (`ping` on STT and TTS; TTS closes after 60 s idle), reconnect with backoff, connection spacing to avoid burst `1003`, session-resume semantics.
9. **Recording and mixdown:** tap user PCM (16 kHz) and agent PCM (TTS rate) on the server, align on a shared timeline including overlaps, resample to a common rate, write stereo WAV (user left, agent right, to match Sarvam's format), upload to object storage, and apply retention.
10. **Metering and billing:** per-session wall-clock minutes; reconcile STT against `session.end.audio_duration_s`; count TTS characters and LLM tokens (`usage` in the final SSE chunk); enforce per-tenant quotas and concurrency to stay under account-wide Sarvam limits.
11. **Observability:** per-turn latency spans, error and close-code dashboards (1003/1008/1011/4000), transcript storage.

### What A1/A2 still require
- A backend endpoint that mints the signed URL (A1) or runs the relay (A2), authenticated with our app session, plus a per-tenant concurrency gate in front of Sarvam's org-wide limits.
- Mapping each training session to `interaction_id`, then pulling transcripts and recordings through the Analytics API for scoring.
- Passing scenario data as `agent_variables` *from the server* (A2, or a server-set mechanism in A1 if Sarvam offers one).
- A UI that handles single-use URLs and no reconnect ("session dropped, start again").

## Recommendation

1. **Pilot Option A1 now.** Use the Web SDK with `baseUrl` pointing at a FastAPI route that checks our user session and adds `X-API-Key` server-side. Reuse the same `app_id` and pinned `version` as the phone agents. This is the path Sarvam documents, it needs the least code, and it inherits barge-in, VAD, recordings and analytics.
2. **Move to A2 (server relay) if** Sarvam confirms that clients can send `variable_update` / `state_transition` unauthenticated, if the signed URL doesn't bind `user_identifier`, or if we need our own audio tap or metering. The design keeps the hosted brain and moves only the media path behind our gateway.
3. **Don't build Option B now.** Reconsider only if we need our own LLM or prompt orchestration (BYO models are unsupported in Voice Agents), if Sarvam can't lift web concurrency limits, or if volume makes the roughly ₹1–1.5/min difference matter. If we do build it, budget for the 11 items above and for the 105B rate limit.
4. **Housekeeping:** migrate the existing agents to Bulbul V4 before 2026-11-10, and set a data-retention period (the default is indefinite).

## 8. Questions for the Sarvam account manager

1. Is the Voice Agents **WebSocket contract** (signed-URL endpoint `…/api/app-runtime/orgs/{org}/workspaces/{ws}/apps/{app_id}/url`, message schema) officially supported and versioned for third-party use? Can we get the document behind "according to the API contract"?
2. **Signed URL:** what is the TTL? Is it bound to `app_id`/`version`? Does the signature cover `user_identifier`, `interaction_type` and sample-rate params, which the SDK appends after signing? Can it be restricted by origin or IP?
3. Can we **lock client-originated messages** (`client.action.variable_update`, `state_transition`, `language_change`) per agent, or set `agent_variables` server-side when minting the URL, so browser users can't tamper with scenario or scoring state?
4. Do **web/SDK sessions count toward the same org concurrency pool** (4/10/30/120) as campaigns, inbound and instant outbound? Can we reserve capacity per channel? What is the Enterprise ceiling?
5. **Billing for web/SDK sessions:** same per-minute rate, 60-second pulses, no telephony charge? Is a session that drops and gets re-created billed as two calls?
6. Are web/SDK sessions **recorded** (stereo WAV via the Analytics recordings API) and do they appear in Call Logs with the same `channel_type` / `channel_protocol` fields? What values should we expect (e.g. `v2v` / `websocket`)?
7. **Embed widget:** how does it authenticate? Is there domain allow-listing? Can we pass a per-user identifier or variables? Is there per-widget rate limiting to stop abuse of our minutes?
8. Is **WebRTC** (or Opus input) on the roadmap for the browser channel? Currently it's 16-bit PCM at 8/16 kHz in and 16/22.05 kHz out over WebSocket.
9. What latency should we expect (p50/p95 user-stop to agent-audio) for browser sessions from India and from outside India? Which regions serve the runtime?
10. **Echo cancellation and barge-in** for laptop speakers: does the runtime apply AEC or a warm-up window for browser audio, or should we rely on browser `echoCancellation`?
11. Is there an **ephemeral or scoped token** for Model APIs (STT/TTS) suitable for browsers, or is server-side proxying the only supported pattern?
12. Is **realtime STT** (`/speech-to-text-realtime/ws`, `saaras:v4`) gated or beta per account (close code 4000 "account not enabled")? What are its inactivity timeout and max session duration?
13. **TTS streaming codecs:** the API reference says "MP3 only", while the guides list linear16/opus and others. Which is correct for `bulbul:v4-flash`? What is v4-flash pricing? Is there a supported way to **cancel** an in-flight TTS stream?
14. Can we raise the `sarvam-105b-conversations` rate limit (120 req/min on Business) if we go with Option B?
15. Can data retention for Voice Agents be set below 1 day, or can recordings be excluded, for training sessions with PII?

---

## Sources

Official Sarvam docs (fetched with `curl`, Markdown):
- https://docs.sarvam.ai/llms.txt
- https://docs.sarvam.ai/llms-full.txt (301 redirect to llms.txt)
- https://docs.sarvam.ai/voice-agents/llms.txt
- https://docs.sarvam.ai/api/llms.txt
- https://docs.sarvam.ai/api-reference/llms.txt
- https://docs.sarvam.ai/openapi.json (an HTML index, not a spec)
- https://docs.sarvam.ai/voice-agents/overview.md
- https://docs.sarvam.ai/voice-agents/build/concepts/introduction.md
- https://docs.sarvam.ai/voice-agents/deploy/overview.md
- https://docs.sarvam.ai/voice-agents/deploy/deploy-with-code.md
- https://docs.sarvam.ai/voice-agents/deploy/sdks/web.md
- https://docs.sarvam.ai/voice-agents/deploy/sdks/python.md
- https://docs.sarvam.ai/voice-agents/settings/api-key.md
- https://docs.sarvam.ai/voice-agents/api/introduction.md
- https://docs.sarvam.ai/api-reference/conversations.md
- https://docs.sarvam.ai/voice-agents/api/analytics/recordings.md
- https://docs.sarvam.ai/voice-agents/api/byok/auth.md
- https://docs.sarvam.ai/voice-agents/api/byok/overview.md
- https://docs.sarvam.ai/voice-agents/monitor/call-recordings.md
- https://docs.sarvam.ai/voice-agents/deploy/campaigns.md
- https://docs.sarvam.ai/voice-agents/deploy/campaigns/dialing-rate.md
- https://docs.sarvam.ai/voice-agents/pricing.md
- https://docs.sarvam.ai/voice-agents/build/conversation-settings.md
- https://docs.sarvam.ai/voice-agents/build/voice-language.md
- https://docs.sarvam.ai/voice-agents/build/models.md
- https://docs.sarvam.ai/voice-agents/build/run-time.md
- https://docs.sarvam.ai/api-reference/authentication.md
- https://docs.sarvam.ai/api-reference/beta-apis.md
- https://docs.sarvam.ai/api-reference/speech-to-text/transcribe/realtime/ws.md
- https://docs.sarvam.ai/api-reference/legacy/speech-to-text/transcribe/ws.md
- https://docs.sarvam.ai/api-reference/text-to-speech/stream.md
- https://docs.sarvam.ai/api-reference/text-to-speech/convert-stream.md
- https://docs.sarvam.ai/api-reference/chat/chat-completions-v1.md
- https://docs.sarvam.ai/api-reference/chat/chat-completions-v2.md
- https://docs.sarvam.ai/api-reference/chat/models-v2.md
- https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/realtime-streaming.md
- https://docs.sarvam.ai/api/api-guides-tutorials/speech-to-text/streaming-api.md
- https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/streaming-api/web-socket.md
- https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/how-to/set-audio-format-for-output.md
- https://docs.sarvam.ai/api/api-guides-tutorials/text-to-speech/voices.md
- https://docs.sarvam.ai/api/api-guides-tutorials/chat-completion/overview.md
- https://docs.sarvam.ai/api/getting-started/pricing.md
- https://docs.sarvam.ai/api/getting-started/ratelimits.md
- https://docs.sarvam.ai/api/getting-started/models/bulbul.md
- https://docs.sarvam.ai/api/getting-started/models/saaras.md
- https://docs.sarvam.ai/api/platform/data-retention.md
- https://docs.sarvam.ai/api/integration/livekit-production-best-practices.md

Public package source (not documentation; findings marked UNVERIFIED):
- https://registry.npmjs.org/sarvam-conv-ai-sdk (metadata; latest 0.0.42, published 2026-03-30)
- https://registry.npmjs.org/sarvam-conv-ai-sdk/-/sarvam-conv-ai-sdk-0.0.42.tgz (`dist/modules/socket-manager.js`, `dist/modules/voice-agent.js`, `dist/types/types.js`)

Secondary (WebSearch, standard mode; snippets are weaker evidence):
- Search "Sarvam Samvaad voice agent web widget browser SDK sarvam-conv-ai-sdk" returned docs.sarvam.ai pages already listed above, plus https://docs.sarvam.ai/conversations/overview.md and https://docs.sarvam.ai/conversations/deploy/sdks/flutter.md (an alternate/older URL tree; not fetched).

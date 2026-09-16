# Phase 8 — Voice: Gemini dictation for the tutor, Gemini batch option for lectures

Branch: `phase-8-voice`. Depends on Phase 3 (transcription seam, jobs table) and Phase 5 (Cloud Run, Secret Manager — the tutor option needs a server endpoint that mints short-lived tokens).

## Decisions — revised (2026-09-15)
- **Vertex AI catalogue check (2026-09-15, publisher-model API, read-only):** `gemini-3.5-transcribe` is **not** on Vertex
  (404 for the publisher model and at `global`, `us-central1`, `europe-west4`); `gemini-3.5-transcribe-live` is not found
  either; **`gemini-3.5-transcribe-live-preview` is** (`PUBLIC_PREVIEW`). The GA models are Gemini Developer API only (API key).
- **Ephemeral tokens are a Gemini Developer API feature.** On Vertex the only credential a browser could hold is an OAuth
  access token for the service account — it would carry every permission `cognitioflow-run` has (the whole bucket), so it
  must never reach the browser.
- **Matej's decision:** keep **service account only, no API key**. Build **Part A (tutor mic) only**, with
  `gemini-3.5-transcribe-live-preview` on Vertex, through a **server-side WebSocket relay** (`/api/voice/live`): the browser
  streams audio to our server, the server talks to Vertex with ADC. No token of any kind reaches the browser.
- **Part B (Gemini lecture provider) is deferred** until `gemini-3.5-transcribe` is offered on Vertex. Lectures stay on
  Speech-to-Text `chirp_2`; `ffmpeg` is not added to the image yet. When Part B returns: **word-level timestamps** win over
  `custom_vocabulary` (the files API can't combine them); Clean garble keeps fixing terms from the glossary afterwards.
- **Security prerequisite:** `AuthMiddleware` passes non-HTTP scopes straight through, so it must also gate WebSocket
  connections (signed-out → closed before any audio is accepted) before the relay route exists.
- `google-genai>=2.23` is required (1.66 has no transcription config fields and no interim transcription events).

## Decisions — settled (2026-09-12)
- **Tutor mic has two modes.** **Browser** (today's Web Speech API: free, Chrome/Safari, no server) stays the **default**. **Gemini** uses `gemini-3.5-transcribe-live`. The choice is a per-browser view preference (`localStorage` `cf.micMode`), which CLAUDE.md allows for small view prefs.
- **Lecture recordings get a second batch provider**, `gemini-3.5-transcribe`, next to the Phase 3 default (Google Speech-to-Text `chirp_2`).
- **US-hosted models are acceptable**; EU data residency is not a constraint for now. The bucket and Cloud Run stay in `europe-west4` for co-location, not residency.
- **Gemini access through the service account** (Vertex AI, ADC): no API key and no new secret; `cognitioflow-run` gets `roles/aiplatform.user` and `aiplatform.googleapis.com` is enabled (added to `infra/setup.sh`). Before building, confirm both models are offered on Vertex AI and in which region — a US region is fine.
- **Lecture provider is environment-wide:** `STT_PROVIDER=google|gemini` (CLAUDE.md: environment selects the backend). `google` (`chirp_2`) stays the default.
- **Custom vocabulary:** the course glossary (`_glossary(cid)`: case names, citations and terms from ticked files), capped at 100 terms, for both the tutor mic and lecture transcription.
- **Long lectures on Gemini are split** into ≤30-minute pieces server-side with `ffmpeg`, added to the Cloud Run image (and to the local dev prerequisites). One piece is transcribed per poll; offsets are added back so `[mm:ss]` anchors stay absolute.

## Verified facts (September 2026)
- `gemini-3.5-transcribe` (files) and `gemini-3.5-transcribe-live` (streaming); GA since August 2026. [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe)
- **Files:** Files API upload; the call is **synchronous**; up to **1 hour per request, 30 minutes with word-level timestamps or diarization**; WebM and Opus accepted; word timings arrive as `word_info` annotations with `start_offset`; `custom_vocabulary` in `generation_config.transcription_config` (up to 1,000 terms, best ≤100). [transcription guide](https://ai.google.dev/gemini-api/docs/transcribe)
- **Live:** WebSocket; browsers should use **ephemeral tokens**; raw 16-bit PCM at 16 kHz mono in 100 ms chunks; sessions up to **10 minutes**; **utterance-level timestamps only**. [live transcription guide](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe)
- **Estimated price:** ~$0.005/min for files, ~$0.009/min live ([coverage](https://mlq.ai/news/google-launches-gemini-35-transcribe-at-an-estimated-0005-per-minute/)) — re-check the official pricing page before building.

## Part A — tutor dictation
- **UI:** a small Browser | Gemini switch beside `#micBtn` (keep the hook and `🎙 Talk` behaviour); sentence case, existing tokens, no new colours. Browser mode is untouched.
- **Gemini mode (revised 2026-09-15):** the browser opens `wss://<app>/api/voice/live?course=<id>` (signed-in only), streams
  16 kHz mono PCM16 downsampled from the mic, and receives `{"interim": …}` / `{"final": …}` messages to show in `#q`; on
  stop it sends `{"stop": true}`, waits for the last final text and calls the existing `send()` — same flow as today. The
  server holds one Vertex Live session per socket (ADC, `gemini-3.5-transcribe-live-preview`) and closes it before the
  10-minute limit.
- Custom vocabulary from the course glossary; `en-GB`.
- No credential of any kind reaches the browser; no audio is stored.
- If the token or socket fails: toast, and fall back to Browser mode for that attempt.
- Cost: add dictation minutes to the existing session cost readout (`#costState`).

## Part B — lecture batch provider
- `transcribe/providers/gemini.py` implementing the Phase 3 seam (`check_ready / submit / poll`), so jobs, retries, the collect-on-reopen flow and `format_capture` stay unchanged and output stays byte-identical.
- Because the Gemini files call is synchronous and capped at 30 minutes with word timings, the audio is split with `ffmpeg` into ≤30-minute pieces (stored under the recording's key prefix) and a job advances **one piece per poll** (progress in `jobs.payload`). No threads, no in-memory state (CLAUDE.md).
- Word timings → `group_words()`; chunk start offsets added so `[mm:ss]` anchors are absolute.
- `executor`/provider recorded on the job so the note's history shows which engine produced a transcript.

## Acceptance
- [ ] Browser mode is the default and behaves exactly as before.
- [ ] Gemini mode: speak a question with case names (e.g. "Dassonville", "Keck") → interim text appears → the question is sent; works in Firefox; the Network tab shows no API key.
- [ ] The WebSocket refuses signed-out connections before accepting audio; no key, token or service-account credential reaches the browser.
- [ ] ~~`docker build` includes `ffmpeg`; splitting the 90-minute fixture…~~ deferred with Part B (2026-09-15).
- [ ] ~~Lecture: the 90-minute fixture with the Gemini provider…~~ deferred with Part B (2026-09-15).
- [ ] Unit tests: WebSocket auth gate, relay message flow with a mocked Live session (interim/final/stop, errors, time limit), glossary vocabulary capped at 100.

# Phase 8 — Voice: Gemini dictation for the tutor, Gemini batch option for lectures

Branch: `phase-8-voice`. Depends on Phase 3 (transcription seam, jobs table) and Phase 5 (Cloud Run, Secret Manager — the tutor option needs a server endpoint that mints short-lived tokens).

## Decisions — settled (2026-09-12)
- **Tutor mic has two modes.** **Browser** (today's Web Speech API: free, Chrome/Safari, no server) stays the **default**. **Gemini** uses `gemini-3.5-transcribe-live`. The choice is a per-browser view preference (`localStorage` `cf.micMode`), which CLAUDE.md allows for small view prefs.
- **Lecture recordings get a second batch provider**, `gemini-3.5-transcribe`, next to the Phase 3 default (Google Speech-to-Text `chirp_2`).
- **US-hosted models are acceptable**; EU data residency is not a constraint for now. The bucket and Cloud Run stay in `europe-west4` for co-location, not residency.

## Decisions [Matej] — open
1. **Gemini access:** Gemini Developer API with a `GEMINI_API_KEY` secret, or Vertex AI with ADC (no new secret, same service account; confirm both models are offered there).
2. **Choosing the lecture provider:** environment-wide `STT_PROVIDER=google|gemini` (CLAUDE.md: "environment selects the backend"), or a per-recording choice in the UI.
3. **Custom vocabulary:** reuse the course glossary (`_glossary(cid)`: case names, citations, terms from ticked files), capped at 100 terms — for both modes.
4. **Long lectures on Gemini:** word timestamps cap a request at 30 minutes (below). Choose: split audio into ≤30-minute chunks server-side (needs `ffmpeg` in the Cloud Run image), or use an asynchronous batch route if one exists for this model (verify first).

## Verified facts (September 2026)
- `gemini-3.5-transcribe` (files) and `gemini-3.5-transcribe-live` (streaming); GA since August 2026. [model page](https://ai.google.dev/gemini-api/docs/models/gemini-3.5-transcribe)
- **Files:** Files API upload; the call is **synchronous**; up to **1 hour per request, 30 minutes with word-level timestamps or diarization**; WebM and Opus accepted; word timings arrive as `word_info` annotations with `start_offset`; `custom_vocabulary` in `generation_config.transcription_config` (up to 1,000 terms, best ≤100). [transcription guide](https://ai.google.dev/gemini-api/docs/transcribe)
- **Live:** WebSocket; browsers should use **ephemeral tokens**; raw 16-bit PCM at 16 kHz mono in 100 ms chunks; sessions up to **10 minutes**; **utterance-level timestamps only**. [live transcription guide](https://ai.google.dev/gemini-api/docs/live-api/live-transcribe)
- **Estimated price:** ~$0.005/min for files, ~$0.009/min live ([coverage](https://mlq.ai/news/google-launches-gemini-35-transcribe-at-an-estimated-0005-per-minute/)) — re-check the official pricing page before building.

## Part A — tutor dictation
- **UI:** a small Browser | Gemini switch beside `#micBtn` (keep the hook and `🎙 Talk` behaviour); sentence case, existing tokens, no new colours. Browser mode is untouched.
- **Gemini mode:** `POST /api/voice/token` (signed-in only) returns a short-lived, single-session token; the browser opens the Live API WebSocket, streams 16 kHz PCM (downsampled from the mic), shows interim text in `#q`, and on stop calls the existing `send()` — same flow as today.
- Custom vocabulary from the course glossary; `en-GB`.
- The API key never reaches the browser; no audio is stored.
- If the token or socket fails: toast, and fall back to Browser mode for that attempt.
- Cost: add dictation minutes to the existing session cost readout (`#costState`).

## Part B — lecture batch provider
- `transcribe/providers/gemini.py` implementing the Phase 3 seam (`check_ready / submit / poll`), so jobs, retries, the collect-on-reopen flow and `format_capture` stay unchanged and output stays byte-identical.
- Because the Gemini files call is synchronous and capped at 30 minutes with word timings, a job advances **one chunk per poll** (progress in `jobs.payload`), unless decision 4 finds an asynchronous route. No threads, no in-memory state (CLAUDE.md).
- Word timings → `group_words()`; chunk start offsets added so `[mm:ss]` anchors are absolute.
- `executor`/provider recorded on the job so the note's history shows which engine produced a transcript.

## Acceptance (draft — finalise when the open decisions are settled)
- [ ] Browser mode is the default and behaves exactly as before.
- [ ] Gemini mode: speak a question with case names (e.g. "Dassonville", "Keck") → interim text appears → the question is sent; works in Firefox; the Network tab shows no API key.
- [ ] Token endpoint refuses signed-out requests; tokens expire.
- [ ] Lecture: the 90-minute fixture with the Gemini provider completes as one Live capture block in the same format; chunk boundaries don't duplicate or drop lines.
- [ ] Unit tests: token endpoint, Gemini provider mapping (word annotations → segments, chunk offsets), poll-per-chunk state machine with a mocked client.

# Phase 12 — Voice agent: `/speech` grading, EdgeTTS and Kokoro, one voice across the app

Branch: `phase-12-voice-agent`. **Contains PR #33** (`recover-endpoints`), which restores the voice and
oral routes that #32 removed; this phase depends on them. Asked for on 2026-09-17.

Two sessions built this phase in parallel. This branch combines them: the first commits
(`/api/speech`, the `/speech` alias, the tutor sharing the Advocate's voice) plus the second session's
EdgeTTS backend, own-question panel, fallbacks, fixes and tests.

## What Matej asked for

1. An endpoint that grades a spoken answer — `/speech`, as the spec names it.
2. A natural voice: first Kokoro, then **Microsoft EdgeTTS** ("free, excellent legal term
   pronunciation"). Both are kept: EdgeTTS as the natural voice, Kokoro as the offline one.
3. "Wire it all together" — including the page: "This is all the backend not the UI!!!"

Asked where the new grading should appear, he chose **an Advocate "Your own question" panel**: type
or say any question, pick one of the course's notes to grade against, answer aloud, hear the verdict.

## Decisions

- **`/speech` and `/api/speech` are one handler.** `/speech` is the spec's name; the page calls
  `/api/speech`, because the sign-in middleware answers 401 JSON only under `/api/` and redirects
  everything else to the login page, which a `fetch()` cannot read.
- **Contract:** `question` and `answer` are required (400 if blank, before any model call);
  `notes` and `model_answer` are optional references. With neither, the grader is told there is no
  reference and to label its note `[OUTSIDE FILES]` — the course rule for anything not from the
  student's own material. The own-question panel always sends a note. Recording anchors (`<!-- -->`)
  are stripped from notes; caps are 600 / 2,000 / 12,000 characters.
- **One grader, one cache.** `/speech` and `/oral/grade` send exactly the same system blocks
  (`_grader_system()`), so they share one cache entry and one marking standard, and return the same
  `oral.normalise()` shape.
- **Model is auto-routed** (`pick_model("drill", None)`), as for every oral route. A caller cannot
  choose one, so Fable stays unreachable.
- **Stateless — a deliberate difference from Phase 11.** Phase 11 said answers with no card behind
  them "create a card first, then get rated". Here Matej chose "nothing is rescheduled": the
  own-question panel is a quick check, so `/speech` writes nothing. Misses still land in the session's
  weak-point notes on screen.
- **EdgeTTS (`TTS=edge`) is the natural voice, and it can run in production.** Free, no key, five
  British neural voices (`en-GB-SoniaNeural` by default); measured 45 KB of MP3 in 2.3 s for a legal
  sentence. `edge-tts` is in `requirements.txt`. It is Microsoft's unofficial read-aloud endpoint and
  each spoken line is sent to Microsoft, so it stays opt-in: production keeps `TTS=browser` until the
  Cloud Run env is changed.
- **Kokoro (`TTS=kokoro`) is the offline voice, local only.** Model 320 MB + voices 27 MB, 672 MB peak
  memory against Cloud Run's 1 GiB — not in `requirements.txt`, not in the image. Loads in 0.9 s,
  synthesises at about a quarter of real time, `bf_alice` by default.
- **A voice that fails is silence nowhere.** `tts.say()` turns any backend exception into "no audio",
  so `/api/speak` answers 204 and the page speaks the rest itself. Kokoro loads under a lock, is
  marked ready only once loaded, and a failed load is remembered rather than retried.
- **One voice for the whole page.** The tutor's "Read aloud", the Advocate and the courtroom share one
  helper: the server voice when configured, one sentence fetched ahead at a time, and the browser voice
  for the rest of a reply the moment a sentence fails. Tutor replies over 1,500 characters are read by
  the browser.
- **`google-genai` is back in `requirements.txt`.** #32 removed it while adding `fsrs`/`fastembed`;
  Gemini dictation (`transcribe/live.py`) imports it, so the production image and CI both lacked it.

## Bugs fixed along the way

- The Advocate locked up if you pressed the mic while a server-voice verdict was playing.
- With the browser voice, the next question cut the verdict off about 0.7 s in.
- A request arriving while Kokoro was still loading was told the voice was unavailable.
- A server sentence that failed silenced the rest of the reply instead of falling back.
- `TTS=` in `.env.local` was ignored unless the app was started with `make dev`, because `tts` was
  imported before the env files were read.

## Setup

```
# .env.local — natural voice (also works on Cloud Run)
TTS=edge
EDGE_VOICE=en-GB-SoniaNeural        # optional

# .env.local — offline voice, local only
pip install kokoro-onnx soundfile
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
TTS=kokoro
KOKORO_MODEL_PATH=/abs/path/kokoro-v1.0.onnx
KOKORO_VOICES_PATH=/abs/path/voices-v1.0.bin
KOKORO_VOICE=bf_alice               # optional
```

## Acceptance (run 2026-09-17)

- [x] `make test` passes — 232 passed, 13 skipped (system Python); 234 passed, 11 skipped in a clean venv
      built from `requirements.txt` with the real Kokoro model and real EdgeTTS (both real-audio tests ran).
- [x] `POST /speech` and `POST /api/speech` grade the answer they were sent; an unreadable grade is `missed`
      (`tests/test_speech.py`, `tests/test_ui_routes.py`, model stubbed).
- [x] Blank question or answer → 400 with no model call; a grader outage → 502 (tests, and curl on a live server).
- [x] `/speech` never changes a card's `due` date or writes a review (`test_speech_writes_nothing`).
- [x] With the server voice off, no `/api/speak` request is made (browser check).
- [x] `TTS=edge` and `TTS=kokoro` each return playable `audio/mpeg` — live server: `/api/speak` 200,
      33 KB, `file` reports MPEG layer III; Kokoro via its gated real-synthesis test.
- [x] A misconfigured or failing voice reports `server: false` or answers 204, and the page uses the browser voice (tests).
- [x] Stopping silences both kinds of audio (`cfHush` paused the server audio mid-reply in the browser check);
      interrupted-verdict lock-up covered by the shared `busy` reset.
- [x] Own question works: note picker lists the course's notes; "Ask it" needs a question and a note; the
      question and verdict are spoken by EdgeTTS; the verdict, counts, mastery and weak-point note update.
- [x] "Back to my cards" leaves own-question mode (browser check); Start and switching course call the same exit.
- [x] Signed out, `POST /api/speech` returns 401 JSON; `/speech` redirects to sign-in (`tests/test_auth.py`).
- [x] Panel checked light and dark at 1440px and 1190px; zero JavaScript errors with the voice on or off.
- [x] `Dockerfile` and `.github/` unchanged; `requirements.txt` only adds `edge-tts` and restores `google-genai`.

The browser checks mocked the grader, so no Anthropic call was made; the voice was real EdgeTTS.

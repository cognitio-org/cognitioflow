# Phase 12 — Voice agent: Kokoro voice, spoken-answer grading, one voice across the app

Branch: `phase-12-voice-agent`, based on `phase-12-kokoro` (the commit that restores the eight endpoints
#32 removed, which this phase depends on: `/api/speak` and the oral routes). Depends on Phase 11c (oral tutor).
Asked for on 2026-09-17.

## What Matej asked for

1. An endpoint that grades a spoken answer.
2. Kokoro TTS as a natural, local voice.
3. Wire it together.

## Decisions

- **The endpoint is `POST /api/speech`, not `/speech`.** Under `AuthMiddleware`, a signed-out request to
  a non-`/api/` path gets a 302 to the login page. A 401 is the right answer for a JSON call.
- **One grader, not two.** `/api/speech` sends the same `GRADER_RULES` + cached `GRADER_CONTRACT` system
  blocks as `/oral/grade`, and returns the same `oral.normalise()` shape. The difference is that there is
  no card: nothing is rescheduled, and the question and (optional) model answer or notes come from the caller.
- **Model is auto-routed** (`pick_model("drill", None)`), as for every oral route. A caller cannot pick a
  model, so Fable stays unreachable.
- **Kokoro is `TTS=kokoro`, local dev only.** kokoro-onnx plus two model files (about 340MB) are not in
  `requirements.txt` or the Cloud Run image. When the package or files are missing, the backend reports
  `server: false` and the page falls back to the browser voice. A failed load is remembered for the life
  of the process, not retried on every request.
- **One voice across the app.** The tutor's read-aloud (`speak()`) now goes through the Advocate's
  `advSpeak()`: the server voice when one is configured, otherwise the browser voice with the same en-GB
  preference. Starting the mic or turning speech off stops either kind of voice.

## Setup (Kokoro, local)

```
pip install kokoro-onnx soundfile
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
curl -LO https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
# .env.local
TTS=kokoro
KOKORO_MODEL_PATH=/abs/path/kokoro-v1.0.onnx
KOKORO_VOICES_PATH=/abs/path/voices-v1.0.bin
KOKORO_VOICE=bf_alice   # optional
```

## Acceptance
- [ ] `POST /api/speech` grades the answer it was sent. Filler words are tolerated, and an unreadable grade is `missed`.
- [ ] `/api/speech` never changes a card's `due` date.
- [ ] `/api/speech` returns 400 on an empty answer (no model call) and 502 on a grader outage.
- [ ] `TTS=kokoro` with no model files: `/api/config` shows `server: false`, and `/api/speak` returns 204.
- [ ] `TTS=kokoro` with the model files: `/api/speak` returns playable `audio/mpeg`.
- [ ] Tutor read-aloud and Advocate speak with the same voice. Mic start and speech-off silence both.
- [ ] `make test` has no new failures.

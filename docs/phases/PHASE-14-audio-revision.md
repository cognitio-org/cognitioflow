# Phase 14 — Notes you can listen to

Branch: `phase-14-audio-revision`. Depends on Phase 12 (`tts.py`, the voice seam) and Phase 2 (`storage.py`). Migration number reserved: **012**.

Idea taken from `cognitio-org/ALLMS` — `app/services/podcast_service.py` (676 lines): note → script → audio, with follow-up questions. Read it for the script structure only. It is legacy, it writes to Firestore, and it builds its own Anthropic client; none of that comes across.

## Decisions — settled
- **It reads a note, it does not invent one.** Input is an existing note id. Nothing is generated from the course files — the note has already been through `draft` or `reconcile` and carries its provenance tags.
- **One voice, the app's voice.** `tts.py` already picks the voice for the whole app (Phase 12). This phase adds no voice picker.
- **Audio is a `storage.py` key, never a filesystem path.** `run.py` must not build a path to it. The `jobs` table holds the state, not process memory.
- **Generation is a job.** A long note is minutes of audio; the request returns a job id and the UI polls, exactly as transcription does.
- **`CF_CHEAP_MODEL` writes the script.** Turning existing prose into spoken prose is mechanical.
- **No follow-up Q&A in this phase.** ALLMS has it; it is a second feature and it belongs to the tutor, which already answers questions about notes.

## Objective
A note becomes something you can listen to on the walk to campus: a spoken script that keeps the note's structure, rendered to audio, stored in the bucket, playable from the note view.

## What exists today
- `tts.py` — the voice seam from Phase 12; EdgeTTS and Kokoro voices, one voice across the app.
- `/api/speak` and `/api/speech` — speech out and graded speech in, for oral practice.
- `storage.py` — `put/get/url/delete`. The only place that touches user content.
- `jobs` table (migration `003`) — job state for transcription; the same pattern applies here.
- `recordings` — audio the student made; this phase adds audio the app made, which is a different thing and gets its own key prefix.

## Scope
`run.py` (three routes: start, status, fetch), `tts.py` (a script-to-audio helper if one is missing), `static/index.html` (a play control in the note view), `tests/test_ui_routes.py`, `migrations/012_*.sql`.

## Definition of done
- [ ] `POST /api/notes/{nid}/audio` returns a job id and writes no audio synchronously.
- [ ] The script keeps the note's headings and order, drops mermaid blocks and provenance tags (they do not read aloud), and never adds material the note does not contain.
- [ ] Audio is written through `storage.py` under its own key prefix; `run.py` builds no filesystem path.
- [ ] Job state lives in `jobs`. Restarting the app mid-generation leaves a job that is still readable.
- [ ] Re-requesting audio for an unchanged note returns the existing key rather than regenerating.
- [ ] Editing the note invalidates it; the next request regenerates.
- [ ] A failure is a job in `error` with a sanitised message — no key, no bucket, no traceback.
- [ ] The play control has a visible focus ring and a tap target ≥ 32px, and respects `prefers-reduced-motion`.

## Acceptance
```
bash scripts/runtests.sh tests/test_ui_routes.py -q
```
Screenshots of the note view with the control, light and dark, 1440px and 1190px.

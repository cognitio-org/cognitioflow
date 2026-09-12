# Phase 3 — Jobs table + hosted transcription

Branch: `phase-3-transcription`. Depends on Phases 1 and 2.

## Decisions — settled
- **Provider: Google Cloud Speech-to-Text v2, `BatchRecognize`**, reading the audio straight from the GCS bucket (`gs://` URI — no signed URL needed, same project). Recognizer in `europe-west4`; model **`chirp_2`** (verified Sep 2026: GA in europe-west4, BatchRecognize 1 min–8 h, word-level timestamps). **Not `chirp_3`**: it lives in the `eu` multi-region rather than europe-west4, and its batch mode is capped at 20 minutes when word-level timestamps are enabled — unusable for a 90-minute lecture with `[mm:ss]` anchors. Re-check the model/region matrix via the locations API if this is revisited. Cost ~€0.016/min → a 90-minute lecture ≈ €1.40. Enable `speech.googleapis.com`; the Cloud Run service account needs `roles/speech.client` (locally, ADC covers it). **No API key secret** — remove `STT_API_KEY` from the Phase 4/5 secret lists.
- Request features: `enable_word_time_offsets=true` (segment start = first word's offset), `enable_automatic_punctuation=true`, language `en-GB` by default (the UI's `lang` param maps to BCP-47), `inline_response_config` so results come back in the operation rather than a second bucket object. Audio is WebM/Opus from `MediaRecorder` — set `auto_decoding_config`.
- **Auto-clean stays on** (`CF_AUTO_CLEAN=1`, Haiku garble pass after transcription).
- A second provider is not built now; `transcribe/providers/` keeps the folder shape so one could be.

## Objective
Transcription is a durable job whose state lives in a `jobs` table and whose heavy lifting runs at the provider. No thread, no in-process model, no scheduler. The UI's existing status polling drives the job to completion. **No local worker** — dropped 2026-09-12; hosted STT is the only transcription path.

## What exists today (verified, `run.py` L570–621)
- `_jobs` dict in memory; `threading.Thread` runs `_transcribe()`; lazy `WhisperModel("small", cpu, int8)`.
- Output format is load-bearing: lines `[mm:ss] text <!--r:{rid}:{secs}-->`, appended to the note under `## Live capture — transcript {stamp}` (`(cleaned)` suffix when the Haiku pass ran) via `clean_text(cid, text)`. The `<!--r:…-->` anchors drive audio-linked playback in the UI. **Preserve byte-for-byte.**
- UI polls `GET /api/recordings/{rid}/transcribe` for `{status, stage, chars, language, cleaned, error}`.

## Schema — `migrations/003_jobs.sql`
```sql
CREATE TABLE jobs(
  id TEXT PRIMARY KEY, kind TEXT NOT NULL,              -- 'transcribe'
  ref_id TEXT NOT NULL,                                -- recording id
  status TEXT NOT NULL DEFAULT 'queued',               -- queued|submitted|running|done|failed
  stage TEXT DEFAULT '', executor TEXT DEFAULT 'hosted',
  payload JSONB DEFAULT '{}',                          -- provider op id, language, etc.
  result JSONB DEFAULT '{}', error TEXT DEFAULT '',
  attempts INTEGER DEFAULT 0,
  created DOUBLE PRECISION, updated DOUBLE PRECISION
);
CREATE INDEX ON jobs(ref_id, kind);
```

## `transcribe.py` contract
```python
class Segment(TypedDict): start: float; text: str
def submit(audio_key: str, language: str | None) -> str          # returns provider operation id
def poll(op_id: str) -> tuple[str, list[Segment] | None, str]   # ('running'|'done'|'failed', segments, detected_language)
def format_capture(segments, rid) -> str      # the exact [mm:ss] … <!--r:…--> lines
def finish_job(job_id, segments, language)    # append block to note, optional clean, mark done
```
Provider in `transcribe/providers/google.py` (`STT_PROVIDER=google`). `submit` passes the `gs://bucket/key` URI; `poll` calls `operations.get` on the long-running operation and, when done, maps `results[].alternatives[0].words[]` into segments (new segment on sentence-ending punctuation or every ~30 s, whichever first — keep segments short so the `[mm:ss]` anchors stay useful).

## Flow
1. `POST /api/recordings/{rid}/transcribe`: if a non-failed job exists for `rid`, return it. Else insert `jobs` (`queued`), call `submit`, store the op id in `payload`, set `submitted`, return the row. Fast — no waiting.
2. `GET /api/recordings/{rid}/transcribe`: load the job. If `submitted`/`running`, call `poll`; on `done` run `finish_job` **in the request** (it's a DB write plus one Haiku call, a few seconds at most) and set `stage='cleaning'` → `done`; on `failed` record the error. Return the same fields the UI expects, plus `executor`.
3. Retry: `POST …/transcribe?retry=1` re-submits a `failed` job (`attempts += 1`, max 3).
4. Because completion happens on poll, a closed tab simply completes on the next open of the note. Document this in the UI status text ("Transcribing in Google Cloud — reopen this note any time to collect").

## Removals
- `_jobs`, `threading`, `_warm`, `_model`, `_transcribe`, the `faster-whisper` requirement, `CF_WHISPER`. The `worker/` package is **not** created.

## UI (`index.html`, minimal)
Status line shows stage and the "reopen to collect" hint. Keep all hooks.

## Acceptance
- [ ] Record → transcribe → block appears in note, byte-identical format to the current build (diff a fixture recording's output against the old build's output, ignoring timestamp).
- [ ] A 90-minute fixture file completes; `jobs` shows `submitted → running → done`; note has one block, not two.
- [ ] Close the tab during a job; reopen the note later; block is present, job `done`.
- [ ] Provider error (revoked `speech.client` role) → job `failed` with readable error; `?retry=1` works; fourth attempt refused.
- [ ] `grep -n "threading\|_jobs\|faster_whisper\|WhisperModel" run.py` returns nothing; `faster-whisper` gone from `requirements.txt`.
- [ ] Unit tests: `format_capture`; `poll` state machine with a mocked provider; double-`POST` returns the same job.

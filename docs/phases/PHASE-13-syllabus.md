# Phase 13 — Syllabus in, weeks and topics out

Branch: `phase-13-syllabus`. Depends on Phase 1 and Phase 6 (`courses.brief`, migration `005`). Migration number reserved: **011**.

Idea taken from `cognitio-org/ALLMS` — `app/services/syllabus_extractor.py` (387 lines) and `syllabus_parser.py` (216). That app is legacy and is **not** a dependency: read it for the shape of the extraction prompt and the JSON it asks for, then write this from scratch against CognitioFlow's own seams. Do not copy Firestore, its `Dict[str, Any]` return style, or its usage-tracking calls.

## Decisions — settled
- **One upload, one extraction.** The syllabus is an ordinary file uploaded through the existing `/api/courses/{cid}/files`. Extraction is a separate explicit action, never automatic on upload: a syllabus is not always recognisable and a silent rewrite of every file's week would be worse than nothing.
- **Extraction writes a proposal, never the live data.** It returns weeks, topics and readings for review. Applying it is a second call. `infer-weeks` already taught us that a wrong week tag is expensive to undo.
- **`CF_CHEAP_MODEL`.** Structured extraction from one document is exactly the cheap tier's job. It must never reach `CF_STRONG_MODEL` — see the model rules in `CLAUDE.md`.
- **Topics live in `courses.brief`**, the JSONB column migration `005` already added, under a `syllabus` key. No new table unless the acceptance work proves one is needed; if it is, it takes migration `011`.

## Objective
Uploading a course syllabus and pressing one button gives the weeks, their topics and their readings, reviewed and then applied — replacing the guesswork in `/api/courses/{cid}/infer-weeks`, which reads filenames and asks the model to guess.

## What exists today
- `/api/courses/{cid}/infer-weeks` — tags files by filename pattern, falls back to one model call, warns when the model step fails. It sets `files.week` only.
- `courses.brief` (JSONB, migration `005`) — the structured tutor brief; `courses.tutor_prompt` is compiled from it.
- `files.week` — free text (`"3"`, `"Week 3"`); `/api/courses/{cid}/cards` and the card generator filter on it.
- `course_brief.py` — compiles the brief into the tutor prompt.

## Scope
`run.py` (two routes), `course_brief.py`, `static/index.html` (a panel in the course screen), `tests/test_ui_routes.py`, `migrations/011_*.sql` **only if proven necessary**.

## Definition of done
- [ ] `POST /api/courses/{cid}/syllabus/extract` takes a `file_id`, returns `{weeks: [{week, title, topics[], readings[]}]}` and writes nothing.
- [ ] `POST /api/courses/{cid}/syllabus/apply` takes that structure, writes it to `courses.brief.syllabus`, and sets `files.week` only where the file is unambiguously matched by name.
- [ ] Re-applying is idempotent: the same payload twice leaves the same state.
- [ ] A document that is not a syllabus returns an empty `weeks` list and an explanation, never invented weeks.
- [ ] The model call uses `pick_model("summarise", …)` or `CHEAP_MODEL`; a test asserts it is never `STRONG_MODEL`.
- [ ] A malformed model reply is a 502 with a readable message, not a traceback — follow `_model_json`.
- [ ] `infer-weeks` still works unchanged; this is an addition, not a replacement.
- [ ] Extracted topics reach the tutor prompt through `course_brief.py`.

## Acceptance
```
bash scripts/runtests.sh tests/test_ui_routes.py -q     # or: make test
```
Screenshots of the review panel in light and dark at 1440px and 1190px, per `CLAUDE.md`.

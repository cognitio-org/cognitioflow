# Phase 16 — The case law, in order

Branch: `phase-16-case-timeline`. Depends on Phase 1 and Phase 10 (`retrieval.py`, chunks). Migration number reserved: **014**.

Idea taken from `cognitio-org/ALLMS` — `app/services/timeline_service.py` (103 lines). Small enough to read in full; take the idea, not the code.

## Decisions — settled
- **Cases come from the notes, not from the model's memory.** The timeline is built from cases already cited in this course's notes and files, with the citation that appears there. A case the model recalls but the course never mentions is not on it — that is the `[OUTSIDE FILES]` rule from `CLAUDE.md` applied to a new surface.
- **Year is the axis, and a missing year is shown as missing.** An undated case sits in an explicit "undated" group. It is never guessed, and never quietly dropped.
- **Read-only.** No editing cases in this phase. It is a lens on existing notes.
- **Reuse the note renderer's vocabulary.** Case names are already italicised and tagged in notes by `chipify()`; the timeline styles `.prov` and the existing chip classes rather than inventing a parallel set.

## Objective
A doctrine that developed over forty years reads as forty years, not as a list in the order someone happened to write it down. For a law student, chronology *is* the argument: *Van Gend* → *Costa* → *Simmenthal* is a sentence.

## What exists today
- `retrieval.py` + `chunks` (migration `007`) — the course's text, chunked and embedded.
- `/api/courses/{cid}/cases` — already returns cases for a course. **Read this first**: this phase may be an ordering and a view over it rather than new extraction.
- `render()` → `chipify()` → `priomark()` in `static/index.html` — the note renderer. `CLAUDE.md` forbids editing these functions for a visual change; style `.prov`, `.prio`, `.noteview`, `.callout` instead.
- The seven Blackstone tab colours map to legal function and must not be repurposed.

## Scope
`run.py` (one route, or an extension of `/api/courses/{cid}/cases`), `retrieval.py` if extraction needs it, `static/index.html` (a timeline view), `tests/test_ui_routes.py`, `migrations/014_*.sql` **only if a cache proves necessary** — prefer computing it.

## Definition of done
- [ ] The timeline lists only cases that appear in this course's notes or ticked files, with the citation as written there.
- [ ] Cases are ordered by year; undated ones are grouped and labelled, never interleaved by guess.
- [ ] Two cases from the same year keep a stable order across reloads.
- [ ] Clicking a case reaches the note it came from.
- [ ] A course with no cases renders an empty state, not an error.
- [ ] `render()`, `chipify()` and `priomark()` are unmodified.
- [ ] Every `id` and `data-` attribute in `index.html` is preserved.

## Acceptance
```
bash scripts/runtests.sh tests/test_ui_routes.py -q
```
Screenshots light and dark, 1440px and 1190px — the sidebar collapses at 1300px.

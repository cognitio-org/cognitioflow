# Phase 6 — Course scaffolding

Branch: `phase-6-courses`. Depends on Phase 1. Can run in parallel with 2–5.

## Decisions — settled (2026-09-12)
- **Property Law details [Matej, after this phase ships]:** exam format, WG tutor name, permitted materials. Entered through the new course dialog, not into code. Does not block the phase.
- **Course prompt template:** field list below confirmed, plus `course_code`, `period`, `exam_date`, `assessment_weighting`.

## Objective
Adding a course is an in-app action: name, colour, slug, and a structured tutor brief that the app compiles into the course prompt. No code, no redeploy. Existing hard-coded `EU_PROMPT` / `PROP_PROMPT` and `prompts/*.md` become seed data only.

## What exists today (verified)
`courses(id, name, accent, tutor_prompt, created[, user_id])`; `POST/PUT /api/courses` already exist (L131, L137) but the UI has no create dialog; `init()` seeds two courses and back-fills Property Law's prompt from `prompts/property_law.md`. Every other table keys on `course_id`, so nothing else needs to change.

## Schema — `migrations/005_course_brief.sql`
Add `brief JSONB DEFAULT '{}'` to `courses`. Fields: `lecturer`, `wg_tutor`, `textbook`, `exam_format`, `permitted_materials`, `authority_order` (list), `method` (free text, e.g. Villanueva's three steps), `provenance_tags` (list), `notes` (free text), `course_code` (e.g. RGBUBEU003), `period` (e.g. Block 2a), `exam_date` (ISO date, date input in the form), `assessment_weighting` (free text, e.g. "written exam 80%, assignment 20%"). Empty fields render nothing in the compiled prompt, so adding them doesn't disturb the EU equivalence test. `tutor_prompt` becomes derived: `compile_prompt(brief)` renders it from a template so every course's prompt has the same shape as the current EU one. If `brief` is empty, fall back to the stored `tutor_prompt` (keeps existing courses working).

## Code
- `compile_prompt(brief) -> str` with a unit test that compiling the EU brief reproduces the current `EU_PROMPT` semantics (same instructions, same authority order).
- `PUT /api/courses/{cid}` accepts `brief`; recompiles and stores `tutor_prompt`.
- `POST /api/courses` creates with a slug derived from the name, unique per user; default accent from a small palette that avoids the seven Blackstone tab colours.
- `DELETE /api/courses/{cid}` — only when the course has no files/notes/cards, or with `?force=1` after a confirm. Cascades.
- Seeding: on empty DB, seed EU and Property Law from `prompts/eu_law.md` and `prompts/property_law.md` **as briefs** (convert the current prompts into brief JSON once, commit the JSON as `prompts/*.json`).

## UI (`index.html`)
- A "New course" entry in the course switcher and a course settings panel (reachable from Overview) with the brief fields as a form and a read-only preview of the compiled prompt. Style with existing tokens; sans for the form, no new colours. Keep every hook; the course switcher's `data-` attributes stay.
- Nothing else on any screen changes.

## Acceptance
- [ ] Create "Constitutional Law" from the UI with a filled brief → it appears in the switcher; Files/Notes/Recall/Planner/Progress all work for it; tutor's system prompt (log it at debug level) contains the compiled brief.
- [ ] Editing Property Law's brief with the three owed fields updates the prompt; a Drill question reflects the new exam format.
- [ ] Existing EU course: compiled prompt passes the equivalence test; a saved Drill transcript before/after shows no behaviour change on a fixed question.
- [ ] Delete guard works; force-delete cascades and leaves no orphan rows (assert counts).
- [ ] Light + dark, wide + half-screen screenshots of the new panel in the PR.

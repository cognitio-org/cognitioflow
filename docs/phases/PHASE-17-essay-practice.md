# Phase 17 — Practise the essay, not just the recall

Branch: `phase-17-essay-practice`. Depends on Phase 1 and Phase 11 (the oral tutor and `oral.py`). Migration number reserved: **015**.

Idea taken from `cognitio-org/ALLMS` — `app/services/essay_practice_service.py` (130 lines), banked essay practice. Read it for how it banks questions; the grading here follows this app's own exam method.

## Decisions — settled
- **Grading follows the Villanueva method already encoded in the tutor**: applicability → restriction/scope → justification and proportionality; IRAC. `CLAUDE.md` says the exam method and the tutor prompts are not to be "improved" without an explicit instruction, and this phase has none. Read the method, apply it, do not rewrite it.
- **Questions come from the course's own material**, banked per course and week, the way the oral bank already works.
- **The student writes, then sees the model answer — in that order, always.** Showing the structure first teaches recognition, not production.
- **`CF_MODEL` for grading, `CF_CHEAP_MODEL` for banking questions.** Grading is the analytical call; generating a question from a topic is not.
- **A grade is feedback, not a number to optimise.** Per-limb comments against the method. No score out of 100 and no leaderboard.

## Objective
The gap between "I know the cases" and "I can write the answer" is where marks are lost. Recall is already covered by cards; this covers the thing exams actually test.

## What exists today
- `oral.py` and `/api/courses/{cid}/oral/bank|next|grade` — banked questions, served one at a time, graded. **This is the pattern to follow**, and possibly to extend rather than duplicate.
- `/api/courses/{cid}/lawyer-pack`, `/api/courses/{cid}/court` — existing application-mode surfaces.
- The tutor's rules block already carries the exam method and the provenance tags.

## Scope
`run.py` (bank, next, grade — mirroring the oral routes), `oral.py` **or** a sibling module if the shapes genuinely differ, `static/index.html` (a writing surface), `tests/test_ui_routes.py`, `migrations/015_*.sql`.

## Definition of done
- [ ] A question bank is generated per course and week from ticked files only; anything outside them is labelled `[OUTSIDE FILES]`.
- [ ] The student's answer is saved before grading, and survives a reload mid-write.
- [ ] Grading returns comments per limb of the method, not a single verdict.
- [ ] The model answer is reachable only after an answer is submitted.
- [ ] Grading uses `pick_model(...)` and never `STRONG_MODEL`; a test asserts it.
- [ ] An empty or whitespace-only answer is rejected before any model call.
- [ ] Re-grading the same answer twice does not create a second bank entry.
- [ ] The writing surface is keyboard-reachable with a visible focus ring.

## Acceptance
```
bash scripts/runtests.sh tests/test_ui_routes.py -q
```
Screenshots light and dark, 1440px and 1190px.

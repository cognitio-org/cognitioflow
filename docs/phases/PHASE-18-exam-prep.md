# Phase 18 — Ready for the exam

Branch: `phase-18-exam-prep`, one slice per branch (18a to 18d; they are independent and run in parallel
worktrees through the swarm dispatcher). Depends on Phases 1, 10 (FSRS and `schedule.py`), 13 (syllabus topics),
15 (the review log), 16 (the case timeline) and 17 (essay practice). Migration number reserved: **023**, used only if
a slice proves it needs a table.

Asked for by Matej, 2026-09-26 ("go exam prep"): Property Law is on **21 October 2026** and EU Law on
**4 November 2026**. Every course already stores its exam date (`courses.exam_date`, migration 017); this phase is
what the app does with it.

## Decisions — for Matej, before any slice starts

Each has a proposal. Answer "as proposed", or change it. Claude Code does not guess these.

1. **What a revision day holds (18a).** Proposed: the cards FSRS says are due, then the weakest topic's material
   (18b), then one timed essay every second day; the day's length is your usual study minutes (from `sessions`),
   never more than 20% above it. *Alternatives: a fixed number of minutes a day; no essays in the last three days.*
2. **Rest days (18a).** Proposed: none scheduled, but a missed day is absorbed (the plan re-flows; the streak freeze
   of Phase 15 already forgives one). *Alternative: Sundays off.*
3. **Two exams, one calendar (18a).** Proposed: until 21 October, Property Law gets two thirds of each day and EU Law
   one third; from 22 October, EU Law gets all of it. *Alternative: a split you choose.*
4. **What "weak" means (18b).** Proposed: a topic is weak when, over its last 20 reviews, recall is below 80%, or an
   essay on it missed a Villanueva limb in the last two attempts; a topic with fewer than 5 reviews is "not yet
   known", not weak.
5. **Past papers (18c).** Do you have past exam papers for either course to upload? Proposed: if yes, questions are
   banked from them as the course's own material; if not, exam-style questions are banked from the syllabus topics,
   labelled "written for practice, not a past paper".
6. **Exam conditions (18c).** Proposed: the paper's real length and question count, a visible timer, no tutor and no
   notes while the clock runs, marking only after time is up. How long is each paper, and how many questions?
7. **The printed pack (18d).** Your exams allow tabs but not annotations in the statute book. Proposed: the pack is
   for revising before the exam, never for taking in: a page per topic (the rule, the leading cases with years from
   the Phase 16 timeline, the Villanueva steps where they apply), plus a sheet of tab labels (article numbers and
   one-word headings only, nothing that counts as an annotation). Is that the right reading of the tab rule?

## 18a — The countdown plan

- A per-course plan from today to `courses.exam_date`: each day's cards due, topic to revise, and essay if any;
  shown on the home screen as "Property Law: 25 days · today: …", and as a calendar.
- Built from what the app already knows: FSRS due dates (`schedule.py`), syllabus weeks and topics (`courses.brief`),
  the weak topics of 18b, study minutes from `sessions`. Computed, never stored: a plan that is stored can be wrong.
- Re-flows every morning from what was actually done.
- **Done when:** both courses show a plan to their exam date; a day skipped re-flows; the two exams share the days
  as decided; tests for the scheduler over a fixed review history.

## 18b — Weak topics

- Per topic: reviews and recall over the last 20, the essay limbs missed, oral grades; ranked weakest first, with
  "not yet known" apart. One click opens that topic's cards, notes and an essay question.
- From `reviews` (the Phase 15 log), `essay_attempts.criteria` (Phase 17) and oral grades; computed on request.
- **Done when:** the ranking matches a fixed history in tests; no score out of 100 anywhere (Phase 17's rule).

## 18c — Exam conditions

- A mock paper: the real paper's length and number of questions (decision 6), from past papers or banked
  exam-style questions (decision 5), timed, tutor and notes locked while the clock runs, marked per Villanueva limb
  after time is up, the model answer shown last (Phase 17's order).
- Reuses essay banking and marking (`essay.py`); `essay_attempts.seconds` already records the time.
- **Done when:** a mock can be sat and marked for each course; the timer survives a reload; nothing is marked before
  time is up.

## 18d — The printed pack

- `Print pack` on a course: the topic pages and the tab-label sheet of decision 7, printed through the browser like
  notes are (the PR #69 print path), light theme, page breaks between topics, every case with its year and the note
  it came from.
- **Done when:** a printed PDF of each course, checked by eye on paper (the printing rule: a real print, not a
  screenshot).

## Working rules

- `CLAUDE.md` applies in full: the three seams, the golden rules, the model rules (`CF_CHEAP_MODEL` for banking,
  `CF_MODEL` for marking, never `CF_STRONG_MODEL` or Fable).
- `static/index.html` changes only in the regions a slice names, with every `id` and `data-` hook kept.
- Each slice is a plan run by the swarm dispatcher (`swarm dispatch add …`, `Base: origin/main`, `Private:
  trusted`), in its own worktree; each merges by PR when its checklist passes, rebased onto `main`.
- The exam method is not to be changed by this phase.

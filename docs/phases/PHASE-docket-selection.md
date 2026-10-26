# Phase — docket game source selection (exam-anchored)

## What was asked
Broad-scope docket games (several weeks, or the whole course — shipped in the scope PR) can exceed the writer's
source budget. Choose the material that best prepares for the exam, rather than filling the budget by authority and
week coverage alone.

## What was built
A tiny, dependency-free TF-IDF ranker (`relevance.py`) and its use inside the broad-scope file selection:

- **Query = what the course examines.** The text of the scope's past-exam files (role `exam`), and working-group
  files (`wg`) when there are no exams, becomes the relevance query.
- **Score = every other file against that query** (TF-IDF cosine, pure stdlib). Exam and WG files keep their place
  at the top by authority; lectures, readers and slides are then ordered by how closely they match the exam language.
- **Coverage is kept.** `_budget_across_weeks` still round-robins across weeks, but within each week it now orders by
  (authority, then exam-relevance), so a whole-course game still touches every week and, within a week, picks the
  exam-relevant material first.
- **No regression.** When there is no exam/WG signal (query empty), every score is 0.0 and selection falls back to
  the authority+coverage order from the scope PR. Single-week games are unchanged (no ranking).

## Why lexical, local, now
- CF runs on Cloud Run (scale-to-zero) and cannot reach the home-fleet MLX embedder; the docket writer runs wherever
  `CF_DOCKET_AUTO=1` (the Mac). A self-contained, local ranker runs the same in both places, sends nothing anywhere,
  adds no dependency, and keeps student/law data local — the CF contract.
- `relevance.rank(query, docs)` is the single seam. A later phase can swap the lexical score for the shared RAG's
  embeddings without changing any caller, once CF↔newsglobe is wired.

## Deliberately not built
- Shared-RAG / embedding similarity (future upgrade behind the same seam).
- Chunk-level selection — docket writes whole files; selection stays at file granularity.

## Acceptance checklist
- [ ] `tests/test_relevance.py` — on-topic doc outranks off-topic; empty query and empty docs fall back to 0.0.
- [ ] `tests/test_docket_drafts.py` — a whole-course game whose budget fits one lecture picks the exam-relevant one.
- [ ] Existing docket/scope tests still pass; full suite green.
- [ ] Copy rule: no forbidden words in any new copy (ranker is internal; no UI copy added).

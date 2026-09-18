# Phase 15 — Keep the streak honest, and keep it alive

Branch: `phase-15-streak-protection`. Depends on Phase 1 and Phase 10 (FSRS, migration `008`). Migration number reserved: **013**.

Idea taken from `cognitio-org/ALLMS` — `streak_maintenance.py` (411 lines) and `badge_service.py` (610). **Read the first, ignore the second.** ALLMS's badges are a leaderboard feature for a multi-user app; this app has one user and a leaderboard of one is not motivation, it is decoration.

## Decisions — settled
- **The streak already exists and is not being rebuilt.** `run.py:1789` counts consecutive days backwards from today over review history; `static/index.html` shows it as `#h-streak`. This phase changes what it *means*, not where it comes from.
- **What counts is a real review, not opening the app.** Today it counts a day with any review row. That stays. Do not widen it to page views — a streak you cannot break is not a streak.
- **One freeze per seven days, earned, not bought.** A missed day is forgiven if the seven days before it were unbroken. This is the whole feature: it stops one bad day erasing six weeks, which is the thing that actually makes people stop.
- **No badges, no points, no levels.** If motivation needs more than this, that is a conversation, not a backlog item.
- **The streak is never written, only computed.** It is derived from `reviews`. A stored counter is a thing that can be wrong; a derived one cannot. The freeze ledger is the only new state.

## Objective
A six-week streak survives one missed Tuesday. The number on the home screen stops being a thing you lose to a dentist appointment, and starts being a thing you can trust.

## What exists today
- `run.py:1789` — the streak loop: walk back from today over distinct review dates.
- `static/index.html:416` — `#h-streak`, the "day streak" stat.
- `/api/courses/{cid}/stats` — returns `streak` along with due, files, accuracy, minutes.
- `reviews` (migration `001`, extended by `008` for FSRS) — the source of truth.

## Scope
`run.py` (the streak computation and `stats`), `static/index.html` (the stat, and a freeze indicator), `tests/test_ui_routes.py`, `migrations/013_*.sql` (the freeze ledger).

## Definition of done
- [ ] A gap of one day, preceded by seven unbroken days, does not break the streak, and the freeze is recorded.
- [ ] A second gap within the same seven days does break it.
- [ ] A gap of two or more consecutive days always breaks it, however long the run before.
- [ ] The freeze is consumed once; the same gap re-evaluated later gives the same answer.
- [ ] The streak stays derived; no counter column anywhere.
- [ ] Time zone: days are the dates already used by `reviews`, unchanged. Do not introduce a second notion of "today".
- [ ] The UI says when a freeze was used, so the number is never quietly wrong.
- [ ] A user with no reviews gets 0, not a crash and not 1.

## Acceptance
```
bash scripts/runtests.sh tests/test_ui_routes.py -q
```
Tests must cover the boundary cases above by constructing review dates directly, not by waiting.

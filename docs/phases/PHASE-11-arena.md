# Phase 11 — The arena: oral tutor, application mode, and two games

Branch: `phase-11-arena`. Depends on Phase 8 (voice), Phase 10 (retrieval + FSRS) and the existing
quiz endpoint. Asked for on 2026-09-16.

## What Matej asked for, in his words

1. "a full whisper tutor that can quiz you orally, it can go over explaining exam/wg questions. It
   focuses on ensuring what you missed is prioritiized to remember."
2. "who wants to be a millionare (lawyer written instead) it works if you can get to all correct from
   content you win and its very well modern animated."
3. "an actual court scenario, when then haiku or any low model detects through files for revision
   something that is a case, we can create a court based on the case, it should be 3d and modern."
4. "the AI Tutor should have a mode on how to apply cases and articles to question facts."
5. "The book is also not fully rendered."

## Formats are inherited, not invented

The old ALLMS build (`~/Desktop/ALLMS/ALLMS`) already settled how questions, lessons and marking work.
Phase 11 reuses those shapes so the two apps agree:

- **Question** — `{question, options[4], correct_index, explanation}`
  (`app/data/micro_lessons/iel_strategy.py`). CognitioFlow's `/api/courses/{cid}/quiz` already returns
  `{id, question, options, correct}`; the games consume it as-is rather than forking a second quiz path.
- **Micro-lesson** — `{introduction, key_points, example_scenario, examiner_tips, common_mistakes,
  quick_reference}` plus a short quiz. This is the shape of the Application mode's output.
- **Marking an applied answer** — IRAC weights from `app/services/anthropic_client.py`:
  issue spotting 25, rule statement 25, **application 30**, conclusion 20, scored out of 100.
  Application carries the most marks, which is exactly what ask (4) is about.
- **Socratic-first** — ALLMS asks guiding questions *before* giving answers
  (`ai_tutor_prompts.py: IEL_SOCRATIC_PROMPTS`). The oral tutor keeps that order.

## Decisions

- **"What you missed" is not a new memory system.** A miss writes rating `0` (Again) to the card
  through the existing `POST /api/cards/{kid}/review` → `schedule.next_review()`. FSRS then brings it
  back on its own. Anything else would be a second, competing scheduler — forbidden by CLAUDE.md and
  worse for Matej.
- **Answers that don't map to a card** (an oral exam answer, an applied problem) create a card first,
  then get rated. That is how a missed *idea* becomes a scheduled one.
- **Course materials stay supreme.** Every question, case and courtroom fact comes from ticked files
  through Phase 10 retrieval. Anything the model adds is labelled `[OUTSIDE FILES]`, as today.
- **Models:** question writing and case detection use `CF_CHEAP_MODEL` (Haiku). Marking an applied
  answer uses `CF_MODEL`. Fable stays unreachable by auto-routing.
- **No new front-end framework.** The game and the courtroom are CSS 3D and canvas in
  `static/index.html`, the same way the book is. No React, no bundler, no Three.js dependency unless a
  later slice proves CSS 3D cannot carry the courtroom — and that decision gets written down here first.
- **Voice:** the oral tutor rides Phase 8's existing mic switch. Browser speech stays the default;
  Gemini Live is the upgrade. It needs `roles/aiplatform.user` on `cognitioflow-run`, still ungranted.

## Slices, in build order

### 11a — The book, finished (ask 5)
The Overview book is a flat SVG: a red rectangle, a cream panel, seven tabs. The finished object
already exists in `static/showcase.html` (cover with gold rules and lettering, spine with bands,
fore-edge, head and tail page blocks, opening cover, tab leaves). Port it, keeping `#book`, `#tabname`
and the seven tab colours and their legal meanings. Tilt stays calmer than the showcase's, per that
page's own PORT note. `prefers-reduced-motion` turns motion off.

### 11b — Application mode (ask 4)
A new tutor mode, `apply`, beside `drill` and `explain`. Given a set of facts it walks the exam method
Villanueva teaches — applicability → restriction/scope → justification and proportionality — and for
each step names the article or case *from the ticked files* and says why it bites on these facts.
Output follows the micro-lesson shape. When Matej writes his own answer, it is marked on the IRAC
weights above, and each component under 60% becomes a card.

### 11c — Oral tutor (ask 1)
Talk mode in the tutor: it asks one question aloud, listens, and corrects. Socratic order. It can also
be pointed at a WG or exam question from the files and talk through it. Every answer is scored; misses
rate the card `Again`. The session ends with "these five come back tomorrow".

### 11d — Who Wants to Be a Millionaire, Lawyer (ask 2)
Fifteen questions from `/api/courses/{cid}/quiz`, easiest first, drawn only from the course's own
cards. Three lifelines: fifty-fifty, ask the tutor (a hint, never the answer), and skip. All fifteen
correct wins. Every wrong answer rates that card `Again`. Modern, animated, but motion respects
`prefers-reduced-motion` and the accent stays the course colour.

### 11e — Courtroom (ask 3)
Haiku scans ticked files for cases (name, court, year, parties, the point of law) and offers to build
a hearing from one. The room is CSS 3D: bench, two counsel tables, a gallery. Matej argues one side;
the tutor argues the other and the bench interrupts with questions drawn from the file's own reasoning.
It closes with the real outcome and what the court actually held, quoted from the materials.

### 11f — The Arena in 3D (decision, 2026-09-17)
Asked for on 2026-09-17: the two games "in the same 3D style" as the Case Docket player (the three.js
story games built outside the app). **Decision:** the Arena gets a 3D mode on vendored three.js r170.
This is the exception the Decisions block above reserves, written down before the code:

- **Why CSS 3D cannot carry it.** The courtroom and the show need lit sets, shadows, fog, posed
  characters and camera moves between shots. CSS 3D has no lighting and no depth buffer (faces sort
  wrongly once a room has furniture), and it cannot pose a character. The CSS room in 11e stays a shallow
  stage; the player needs a scene graph.
- **How it stays inside the rules.** three.js is vendored as plain ES modules (`play/player/vendor/`) and
  loaded with an import map. No npm, no bundler, no build step, no framework. The player is its own page in
  an iframe overlay, so `static/index.html` gains only a button per tab and the overlay.
- **Behind sign-in.** The player lives in `play/`, mounted at `/play/`, *not* under `/static/`: the middleware
  treats `/static/*` as public, and the Case Docket games contain lecture quotes. Game JSON is served only
  through `/api/courses/{cid}/docket…`, and only the games that belong to that course.
- **No new generation path.** The show's question pack (`GET /api/courses/{cid}/lawyer-pack`) uses the same
  cards and the same cheap-model distractors as `/quiz`, reshaped to the player's pack schema. Ask the Tutor
  calls `/hint`. A wrong answer rates the card `Again` through `/api/cards/{kid}/review`, as the 2D game does.
- **The 2D Arena stays** as the fallback. Without WebGL, the player itself switches to a 2D stage.
  Reduced motion and a low-quality switch carry through.

Acceptance (11f):
- [ ] Signed out, `/play/player/index.html`, `/api/courses/{cid}/lawyer-pack` and `/api/courses/{cid}/docket` are refused (redirect / 401).
- [ ] The pack has exactly four distinct options A–D per question, an answer among them, level 1–3, a non-empty quote and a cite; only the selected course's cards are used.
- [ ] Arena → "Play in 3D" opens the player full-screen for the selected course; the course name and "Back to Arena" are always visible; Escape and browser Back return to Arena.
- [ ] The show: up to 15 rungs (as many as the cards fill), 50:50, Poll the Jury, Ask the Tutor (a hint, never the answer); a wrong answer makes that card due again.
- [ ] Courtroom → "Play in 3D" lists only the Case Docket games for the selected course; an empty list says so.
- [ ] Reduced motion is respected; the Low quality switch reloads the player in low quality.
- [ ] The Docker image ships `play/` without `.blend`/`_src` files.

## Acceptance
- [ ] Book: opens, tabs turn to a leaf, tilt is calm, still fine at 1190px and with reduced motion.
- [ ] Apply mode: names an article and a case from ticked files for each step; `[OUTSIDE FILES]` when it strays.
- [ ] Marking returns the four IRAC components and a score out of 100 that equals their sum.
- [ ] A missed question makes that card due again — checked by reading the card's `due` before and after.
- [ ] An oral answer with no card behind it creates one, then rates it.
- [ ] Millionaire: fifteen questions, three lifelines, wrong answer rates `Again`, win state at fifteen.
- [ ] Courtroom: a case detected from a real ticked file; every quoted holding traceable to that file.
- [ ] Every screen checked light and dark, 1440px and 1190px, keyboard reachable, 32px hit areas.

### 11g — Backend result caching for quiz and hint

`POST /api/courses/{cid}/quiz` and `POST /api/courses/{cid}/hint` both called `CHEAP_MODEL` on
every request. Neither prompt is long enough for Anthropic prompt caching to help, so the results
are stored instead (migration `010_quiz_hint_cache.sql`):

- `card_distractors` — one row per card, keyed on the card id, storing the three wrong options
  written for it and a hash of the card's back. `quiz()` only calls the model for cards whose stored
  set is missing, invalid, or stale (the back was edited since it was cached); the call is skipped
  entirely when every picked card already has a valid set. Options are still shuffled fresh on every
  request, cached or not, and a card never surfaces with fewer than four options.
- `hint_cache` — one row per `(course, normalised question, sorted options)`, reused for 30 days.
  The "no hint available" fallback is never written to the cache, so a transient model failure
  doesn't haunt that question for a month.

Both routes now 404 on an unknown course id, matching the existing `if not course: raise
HTTPException(404)` check already used by `/chat`, `/plan` and `/notes/draft` — the closest existing
"course routes check ownership" pattern in this codebase. Note for the record: true per-user course
ownership (one signed-in user 403'ing on another's course) does not exist anywhere in `run.py` yet —
`current_user` is explicitly "not a data filter yet (single tenant)" (see `auth.py`), and CLAUDE.md
defers multi-user to a later phase. Adding real cross-user enforcement to only these two endpoints
would be inconsistent with every other course route and would pull that later phase's work forward,
so this slice matches the existing pattern instead of inventing a new one.

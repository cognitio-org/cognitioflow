# CognitioFlow — cloud migration roadmap

Nine phases, one PR each, in order. Each phase leaves the app fully working. Each brief has a **Decisions** block at the top — Matej settles those before the phase starts; Claude Code never guesses them.

| # | Phase | Seam | Depends on |
|---|-------|------|------------|
| 1 | SQLite → Postgres (docker local, Neon cloud) | `db()` | — |
| 2 | Filesystem → object storage | `storage.py` | 1 |
| 3 | Jobs table + hosted transcription (no local worker) | `transcribe.py`, `jobs` | 1, 2 |
| 4 | Google sign-in + Secret Manager | auth middleware | 1 |
| 5 | Dockerfile + Cloud Run + auto-deploy | infra | 1–4 |
| 6 | Course scaffolding (add courses in-app) | `courses` | 1 |
| 7 | Cutover, backups, retire the laptop build | ops | all |
| 8 | Voice: Gemini dictation option for the tutor, Gemini batch option for lectures | tutor mic, `transcribe/` | 3, 5 |
| 9 | LLM provider seam: Anthropic direct or OpenRouter, usage/cost readout | `llm.py`, `llm_usage` | 1 (5 for the cloud secret) |
| 10 | Course-first retrieval and adaptive recall | `retrieval.py`, `schedule.py` | 1 |
| 11 | Arena: oral tutor, application mode, two games | `oral.py`, `tts.py` | 8, 10 |
| 12 | Voice agent: `/speech` grading, EdgeTTS + Kokoro voices, one voice across the app, own-question panel | `tts.py`, oral routes | 11 |
| 13 | Syllabus in, weeks and topics out | `courses.brief`, `course_brief.py` | 1, 6 |
| 14 | Notes you can listen to | `tts.py`, `storage.py`, `jobs` | 2, 3, 12 |
| 15 | Keep the streak honest, and keep it alive | `reviews`, stats | 1, 10 |
| 16 | The case law, in order | `retrieval.py`, note renderer | 1, 10 |
| 17 | Practise the essay, not just the recall | `oral.py`, tutor method | 1, 11 |

Phases 4 and 6 don't depend on 2–3 and run in parallel branches — separate git worktrees, each with its own local database (a separate database in `cf-db`, `DATABASE_URL` exported in that worktree).

**Merge when ready** (decided 2026-09-12): a phase merges as soon as its acceptance checklist passes, rebased onto `main`. Phase 5 still waits for 1–4 because it genuinely depends on them.

**Migration numbers** are reserved per phase brief (`002` storage, `003` jobs, `004` auth if needed, `005` course brief, `007` llm usage, `011` syllabus, `012` audio, `013` streak freeze, `014` timeline, `015` essay practice), so `main` may have gaps. `migrate.py` applies every file not yet recorded in `schema_migrations`, in filename order, so a gap or a late-arriving lower number is applied, never skipped. Because an existing database can then apply a lower number after a higher one, a migration must not depend on any migration with a higher number.

## Phases 13–17 — where they came from

These five are lifted from `cognitio-org/ALLMS`, the older app, which has a much wider
feature surface and is no longer being built on. It is a source of ideas, not a
dependency: each brief names the ALLMS module worth reading and then says what does not
come across. None of its code, its Firestore access or its service layout belongs here.

Two of the five were narrowed after checking what this app already has, rather than what
ALLMS has. Streaks are not new — `run.py:1789` already computes one and `#h-streak`
already shows it — so phase 15 is about the streak surviving a missed day, not about
building one. ALLMS's badge service is deliberately left behind: it is a leaderboard
feature, and a leaderboard of one is decoration.

They are independent of one another and can run in parallel worktrees. They are not
independent in the file system: every one of them touches `run.py` and
`static/index.html`, so whichever lands second rebases. Keep each diff additive and in
its own region of those files.

## Working rules for every phase

- Read `CLAUDE.md` first. Its golden rules and "must not do" list apply to every phase.
- `static/index.html` changes only where the brief says so, and only via the safe-restyle rules.
- Every phase ends with its acceptance checklist run and pasted into the PR.
- **Every phase is demoable.** Matej must be able to see the progress running, not just read tests. Before Phase 5 is live: the phase branch runs locally against docker Postgres (`make dev`; parallel worktrees each on their own port and database) with seeded demo data where needed, and the PR has a "How to see it" section (exact commands, URL, what to click) plus light/dark screenshots of anything visible. Once Phase 5 is live: the same, plus the change running on the Cloud Run URL after merge.
- Anything marked **[Matej]** is done by him, not the agent.

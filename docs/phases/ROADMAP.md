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

Phases 4 and 6 don't depend on 2–3 and run in parallel branches — separate git worktrees, each with its own local database (a separate database in `cf-db`, `DATABASE_URL` exported in that worktree).

**Merge when ready** (decided 2026-09-12): a phase merges as soon as its acceptance checklist passes, rebased onto `main`. Phase 5 still waits for 1–4 because it genuinely depends on them.

**Migration numbers** are reserved per phase brief (`002` storage, `003` jobs, `004` auth if needed, `005` course brief, `007` llm usage), so `main` may have gaps. `migrate.py` applies every file not yet recorded in `schema_migrations`, in filename order, so a gap or a late-arriving lower number is applied, never skipped. Because an existing database can then apply a lower number after a higher one, a migration must not depend on any migration with a higher number.

## Working rules for every phase

- Read `CLAUDE.md` first. Its golden rules and "must not do" list apply to every phase.
- `static/index.html` changes only where the brief says so, and only via the safe-restyle rules.
- Every phase ends with its acceptance checklist run and pasted into the PR.
- **Every phase is demoable.** Matej must be able to see the progress running, not just read tests. Before Phase 5 is live: the phase branch runs locally against docker Postgres (`make dev`; parallel worktrees each on their own port and database) with seeded demo data where needed, and the PR has a "How to see it" section (exact commands, URL, what to click) plus light/dark screenshots of anything visible. Once Phase 5 is live: the same, plus the change running on the Cloud Run URL after merge.
- Anything marked **[Matej]** is done by him, not the agent.

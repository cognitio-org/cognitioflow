# CognitioFlow — cloud migration roadmap

Seven phases, one PR each, in order. Each phase leaves the app fully working. Each brief has a **Decisions** block at the top — Matej settles those before the phase starts; Claude Code never guesses them.

| # | Phase | Seam | Depends on |
|---|-------|------|------------|
| 1 | SQLite → Postgres (docker local, Neon cloud) | `db()` | — |
| 2 | Filesystem → object storage | `storage.py` | 1 |
| 3 | Jobs table + hosted transcription (no local worker) | `transcribe.py`, `jobs` | 1, 2 |
| 4 | Google sign-in + Secret Manager | auth middleware | 1 |
| 5 | Dockerfile + Cloud Run + auto-deploy | infra | 1–4 |
| 6 | Course scaffolding (add courses in-app) | `courses` | 1 |
| 7 | Cutover, backups, retire the laptop build | ops | all |

Phases 4 and 6 don't depend on 2–3 and can run in parallel branches if convenient, but merge in numeric order to keep the diff history readable.

## Working rules for every phase

- Read `CLAUDE.md` first. Its golden rules and "must not do" list apply to every phase.
- `static/index.html` changes only where the brief says so, and only via the safe-restyle rules.
- Every phase ends with its acceptance checklist run and pasted into the PR.
- Anything marked **[Matej]** is done by him, not the agent.

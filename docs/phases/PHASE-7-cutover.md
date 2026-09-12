# Phase 7 — Cutover, backups, retire the laptop build

Branch: `phase-7-cutover` (scripts and docs only). Depends on everything.

## Decisions
- **Cutover date/time [Matej, open]** — pick a ~2-hour slot with no lectures once Phase 5 is live.
- **Mac worker:** dropped (2026-09-12). Hosted STT only; Files-screen upload is the only ingest.
- **Neon plan:** Free (2026-09-12).
- **Backup bucket:** `cognitioflow-backups`, Coldline, `europe-west4` (2026-09-12).

## Objective
Move the real data once, cleanly, verify it, switch to the cloud URL, and make sure nothing in `data/` on iCloud is load-bearing any more. Set up backups that need no laptop.

## Runbook **[Matej runs; agent writes the scripts and checks them]**
1. Stop `run.py` on the Mac. Copy `data/` to `data-final-YYYYMMDD/` (belt and braces).
2. `python migrate_sqlite.py --sqlite ~/Desktop/cognitioflow/data/cognitioflow.db --dry-run` against Neon **prod** → paste counts. Then without `--dry-run`. Then `--verify` (re-counts, spot-checks 20 random ids across notes/cards/recordings).
3. `python migrate_storage.py --data ~/Desktop/cognitioflow/data --dry-run` → counts → run → `--verify` (HEAD each object).
4. In the cloud app: Files screen shows every file under the right week with text; Notes open with recordings that play and seek; Recall due count matches the last laptop count you noted; Planner agenda intact; Progress case index intact.
5. Reconcile one note end-to-end and transcribe one short recording in the cloud to prove the model and STT paths.
6. Bookmark the Cloud Run URL; install as PWA (Chrome → Install app). Remove `Start CognitioFlow.command` from the Dock.
7. Leave the Desktop folder in place for two weeks, untouched. Then archive `data-final-*` to iCloud cold storage and delete the working copy.

## Backups (agent delivers)
- Neon: use the Free plan's point-in-time restore window (much shorter than the 7 days this brief originally assumed — confirm the current limit in the Neon console and state it in the README); document `neonctl branches create --parent main@<timestamp>` as the restore path.
- Bucket: object versioning on; a Cloud Scheduler job **weekly** (decided 2026-09-12 — the Free plan's short restore window makes this the real safety net) copying `neon pg_dump` (via a Cloud Run job) + bucket snapshot to a second, cold bucket (`cognitioflow-backups`). `infra/backup.sh` + restore instructions tested once end-to-end on a Neon branch.
- `scripts/export_all.py`: dumps every course as a folder of Markdown notes + a cards CSV + audio, so there is always a plain-files exit from the app.

## Acceptance
- [ ] All counts equal across SQLite → Neon and `data/` → bucket; `--verify` green for both.
- [ ] A day of normal use on the cloud URL with the Mac closed: drill, note edit, recall session, planner — no errors in Cloud Run logs.
- [ ] `export_all.py` output opens as readable Markdown; the restore drill (Phase 7 backups) rebuilds a working app from a backup on a Neon branch.
- [ ] `README.md` no longer describes the laptop build as the primary way to run the app; `COGNITIOFLOW_GUIDE.md` §3 and §6 updated to the cloud architecture.

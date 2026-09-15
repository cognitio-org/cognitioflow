# CognitioFlow

**Start here:** unzip onto your Desktop, then double-click **Start CognitioFlow.command** inside the folder.
First run installs everything and asks for your API key. After that, one double-click opens the app in its own
window — hold the green button and choose "Tile Window to Right of Screen" to sit it beside Claude.

Unzipping over an existing install is safe: your `.env` and `data/` folder are not in the zip and stay as they are.


Runs on your Mac. Files, notes, cards and conversations live in `./data/`. The only thing that leaves the machine is each tutor message (plus the ticked files' text) sent to the Claude API.

## Cloud (Cloud Run)
The cloud build runs on Cloud Run in project `vigilant-axis-483119-r8`, region `europe-west4`, service `cognitioflow`.
Data lives in Neon Postgres, files in the `cognitioflow-user-content` bucket, secrets in Secret Manager.

**URL:** `https://cognitioflow-<hash>-ez.a.run.app` (placeholder until the first deploy; get it with
`gcloud run services describe cognitioflow --region europe-west4 --format='value(status.url)'`).

### Deploy
- Merging to `main` deploys. `.github/workflows/deploy.yml` runs the tests against a throwaway Neon branch of
  production, builds the image, pushes it to Artifact Registry
  (`europe-west4-docker.pkg.dev/vigilant-axis-483119-r8/cognitioflow/cognitioflow:<commit>`) and runs `gcloud run deploy`.
- Manual: GitHub → Actions → **test and deploy** → **Run workflow** on `main` (or `gh workflow run deploy.yml --ref main`).
- Every pull request runs the same tests; only `main` deploys.

### PR worthiness check
Every pull request gets one short comment after its tests: **Approve for deployment** or **Hold**, a one-line reason and a
security percentage. Rules always run on the diff (leaked credentials and committed `.env`/`data/` block; sign-in, workflow,
infrastructure, schema and dependency changes and risky lines such as public access or `shell=True` lower the score). With an
`ANTHROPIC_API_KEY` repo secret, Claude reviews the diff too and the lower score counts. Approve needs passing tests and ≥ 75%.
It runs from `main`, so a PR can't change its own check.

**Auto-approve:** when the verdict is Approve, the GitHub Actions bot approves the PR (once per commit); a later Hold
withdraws that approval. It never merges — merging deploys, and stays with you. A PR that changes the checker or its
workflows is always held for a person. `.github/workflows/pr-sweep.yml` re-checks open PRs every 30 minutes, skipping
drafts, PRs whose tests are still running and commits it has already judged. Needs the repo setting *Allow GitHub Actions
to create and approve pull requests*. Locally: `python3 scripts/pr_worthiness.py --pr <n>` or `--all` (prints only).

### Roll back
```
gcloud run revisions list --service cognitioflow --region europe-west4
gcloud run services update-traffic cognitioflow --to-revisions=REVISION=100 --region europe-west4
```
Replace `REVISION` with a name from the list (e.g. `cognitioflow-00012-abc`). The next merge to `main` sends traffic
to the new revision again.

### Logs
- Console: Cloud Run → `cognitioflow` → **Logs** (or Logs Explorer, resource "Cloud Run Revision").
- Terminal: `gcloud run services logs read cognitioflow --region europe-west4 --limit 100`
  (`gcloud beta run services logs tail cognitioflow --region europe-west4` to follow).
- Deploy runs: GitHub → Actions.

### Run the container locally
```
docker build -t cognitioflow .
docker run --rm -p 8080:8080 --env-file data/docker.env cognitioflow   # → http://localhost:8080
```
`data/docker.env` (gitignored) needs at least `DATABASE_URL=postgresql://cf:cf@host.docker.internal:5432/cognitioflow`,
`AUTH=off`, `ALLOWED_EMAILS=…`, `STORAGE=local`, `STORAGE_LOCAL_ROOT=/tmp/cf-data`. The container checks the
environment (`ENV=production` refuses to start with `AUTH=off` or a missing secret), applies migrations, then serves.

### One-time setup [Matej]
1. `bash infra/setup.sh --dry-run` to see what it will do, then `bash infra/setup.sh`. It is idempotent and keeps
   what already exists (bucket, `cognitioflow-run` and its roles). It enables the APIs, creates the Artifact Registry
   repo, the five secrets (values from env vars or hidden prompts; `--rotate` adds new versions), Workload Identity
   Federation for `cognitio-org/cognitioflow` (main branch only) and the `cognitioflow-deploy` service account.
2. Add the GitHub repo variables and secret it prints: `GCP_WIF_PROVIDER`, `GCP_DEPLOY_SA`, `NEON_PROJECT_ID`
   (variables) and `NEON_API_KEY` (secret). Optional variables: `NEON_DATABASE` (default `cognitioflow`), `NEON_ROLE`.
3. Merge to `main` (or run the workflow), then add `<URL>/auth/callback` to the OAuth client's authorised redirect URIs.

### Backups and restore
Three layers, from newest to broadest:

| Layer | Covers | How far back | Restore |
|---|---|---|---|
| Neon point-in-time restore | the database | **6 hours** (Free plan history window) | Neon console → Branches → create a branch from a point in time |
| Object versioning on `cognitioflow-user-content` | uploads and recordings deleted or replaced in the app | 30 days | `gcloud storage ls --all-versions gs://cognitioflow-user-content/<key>`, then copy the old generation back |
| Weekly backup (`scripts/backup.py`) | database dump + a copy of every stored file | 365 days | `scripts/restore.py`, below |

The weekly backup runs as the Cloud Run job `cognitioflow-backup` every Sunday at 03:00 Europe/Amsterdam, under its own
service account `cognitioflow-backup@…` (it can add to the backup bucket but not delete from it). Each run writes
`gs://cognitioflow-backups/<UTC stamp>/` with `db.dump`, `objects/…` and, last, `manifest.json` (row counts, dump
sha256, object count and bytes). A folder without a manifest is an incomplete run and is ignored.

```
bash infra/backup.sh                     # dry run: shows the job, schedule, permissions and bucket rules it would set
gcloud run jobs execute cognitioflow-backup --region europe-west4 --wait     # take a backup now
python3 scripts/backup.py --list         # completed backups (needs your gcloud application-default login)
```

**Restore** into a fresh Neon branch or any empty Postgres 18 database. `restore.py` never uses `DATABASE_URL` as its
target, checks the dump's sha256 first, refuses a database that already holds rows unless `--replace`, and compares every
table's row count with the manifest afterwards. `pg_restore` 18 runs locally if installed, otherwise from the
`postgres:18` image through Docker.

```
python3 scripts/restore.py --list
python3 scripts/restore.py --latest --database-url "$TARGET_URL" --objects-to ~/cf-restore/files   # or gs://<bucket>
```

To put a restore into service: add the restored branch's connection string as a new `DATABASE_URL` secret version,
copy the objects back with `--objects-to gs://cognitioflow-user-content --replace` if files were lost, and redeploy.
For a plain-files copy you can open without the app, use `scripts/export_all.py`.

## First run
```
cd cognitioflow
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then paste your key into .env
python run.py               # → http://localhost:8000
```
Next time: `source .venv/bin/activate && python run.py`

## Daily use
1. Files: drop slides (.pptx), transcripts (.txt/.vtt), readings (.pdf), photographed notes (.jpg/.png). Tick what the tutor should read; untick old weeks to keep calls cheap and focused.
2. Tutor: "Drill me" is the default. "Explain" for a structured answer. "Build notes" to reconcile ticked files into master notes with provenance tags.
3. Notes: type during lectures; "Send to tutor" snapshots the note into Files so the tutor can reconcile it against the slides.
4. Recall: generate cards from a file, review with Again/Hard/Good/Easy (SM-2 scheduling).

## Voice (Chrome or Safari, no API cost)
On the Tutor screen: **Talk** dictates your answer using the Mac's own speech recognition and sends it when you stop speaking; **Read aloud** has the reply spoken back. Both use the browser's built-in speech engine, so they cost nothing and work offline. Note this is turn-taking dictation, not the continuous voice conversation on claude.ai.

## Find anything: ⌘K
⌘K (or the Search button) opens a palette: type a screen name to jump, or two letters or more to search this course's notes, files, chats and cards with a snippet. Arrows and Enter.

## Note history
Edits are snapshotted (at most every three minutes, only when the text changed). **History** in Read view lists them; Enter previews one in place, **Restore this version** swaps it in — the text you had is itself kept as a version.

## Audio anchors in the editor
Lines typed while recording carry an anchor. In Read view it is a ▶ chip; in Edit it shows as ⏵1·10:58 (recording 1, ten minutes fifty-eight). Leave it in place; delete it only if you want that line unlinked.

## Notes look like notes
Notes open in a **Read** view: rendered Markdown, serif, provenance tags shown as small chips ([WG] bold, [ADDED] / ?? dashed = verify), tables and diagrams rendered. **Edit** switches to the plain text. **Print / PDF** prints the reading view alone, monochrome A4, with the text in the left two-thirds and a ruled annotation column down the right of every page — for the working group, where laptops aren't allowed. In the print dialog choose Save as PDF or a printer; nothing else on screen prints.

## Offline: record, self-test, cards
- **● Record** (in the editor bar) records the lecture on the Mac — audio never leaves the machine. While recording, every line you finish gets an invisible marker; in Read view it shows as a ▶ chip that plays the audio from 20 seconds before you typed that line. Type `t` + space for a visible clock time. Recordings sit above the note with a player each.
- **Auto-transcribe** (ticked by default, in the editor bar): when you press Stop, transcription starts on its own; the editor bar shows the elapsed time, and when it finishes a bar appears in Read view with one button — Reconcile with lecture. The Whisper model is loaded at app start so the first transcription isn't slow (set `CF_WHISPER_PRELOAD=0` to skip).
- **Clean garble** — after transcription (automatically, or by the button in Read view) Haiku repairs mis-heard case names, article numbers and terms. It may only correct towards a glossary harvested from your ticked files plus the course's known cases, must keep every line, timestamp and anchor, and appends (?) where it isn't sure. The raw transcript is kept in History. Set `CF_AUTO_CLEAN=0` to keep transcripts raw.
- **Transcribe** next to a recording runs Whisper on the Mac (faster-whisper, `small` model by default; set `CF_WHISPER=medium` in .env for better accuracy at 2–3× the time). The first run downloads the model (~500 MB) and needs internet once; after that it is fully offline. Output is appended to the note as a timestamped "Live capture — transcript" section, each line carrying a ▶ chip — then press **Reconcile with lecture**.
- **Cover rules / Cover cases** in Read view black out the rule after each bold lead, or every italic case name (and the Case/Rule column of tables). Click a bar to reveal. A self-test straight off the notes, no model.
- **Cards from case map** turns each row of a table with a Case column into a recall card — front is the case, back is the other columns. Deterministic; re-running skips rows already made.

## Draft notes from files
Notes → choose **Master** (everything ticked in Files) or **Week** + a number (only that week's ticked files), tick **diagrams** for a decision-tree flowchart of the main test, then **Draft from files**. Output: scope, core rules with provenance tags, case map, traps, gaps. Cheap model.

**Split** shows the set page beside what you type. The editor continues bullets and numbered lists on Enter (an empty item ends the list), Tab / Shift-Tab indent, ⌘B bold, ⌘K italic case name, and ⌘1–⌘4 drop [LEC] / [!] / [P] / ?? at the start of the line (after the bullet). Buttons above the editor do the same.

**Reconcile with lecture** (after the lecture): splits the note into the draft and the Live capture, and rewrites the draft so the capture wins — [!] corrections override, [P] pinpoints are inserted, ?? gaps are filled from the ticked files where they can be. Saves a new "(reconciled)" note and keeps the original; ends with a Reconciliation log and a Still-to-verify list. Strong model.

**+ Lecture capture** appends a dated "Live capture" section to the open note and drops you into Edit at the end — for typing during the lecture, then reconcile after with "Send to tutor".

## Auto-plan
Planner → **Auto-plan 7 days** reads the course calendar files, what is indexed by week and what is due for recall, and fills the next week: pre-read before each lecture, reconcile after, short recall slots. **Re-plan** discards unfinished sessions from today and starts again.

## Visuals in the tutor
Replies render as Markdown. When the tutor draws a flowchart or case map it sends a Mermaid block, which the app renders inline (libraries are bundled, no internet needed). Ask for one directly: "draw the Art 34 test as a flowchart" or "table Dassonville vs Cassis vs Keck".

## Model routing
Automatic by task: note-building and card generation run on the cheap model, drilling and explaining on the strong one. A cheap task escalates automatically if the request looks analytical (compare, contrast, IRAC, why, critique, argue). Override per message with the dropdown next to the mode buttons.

Defaults, overridable in `.env`:
```
CF_MODEL=claude-sonnet-4-6        # drilling, explaining
CF_CHEAP_MODEL=claude-haiku-4-5   # notes, cards
CF_STRONG_MODEL=claude-sonnet-4-6 # reconcile with lecture only; set claude-fable-5-1 or claude-opus-5 for the hardest step (≈3–4× the cost of Sonnet per call)
```
The per-message dropdown in the Tutor lists all five models for one-off escalation.

## Watched folder — one drop, two homes
Each course has a folder under `data/watch/<Course name>/`. Drop a file there in Finder and hit **Import new files** on the Files screen; already-imported files are skipped. There is no way to read the files inside a claude.ai Project, so keep the same file in both places: the watched folder for this app, and an upload into the Project for chat.

## Bring your claude.ai history in
claude.ai → Settings → Privacy → Export data (zip arrives by email). Then:
```
python import_claude_export.py ~/Downloads/data-XXXX.zip "European Law" --match "EU law,Dassonville,Article 34,Cassis,Keck,direct effect,Schütze" --project "European"
```
Matching chats land in `data/watch/European Law/claude-chats/` as Markdown, project documents (if the export carries them) in `claude-project-docs/`. Press **Import new files**. Safe to re-run — existing files are skipped.

## Keep data in iCloud
Move `data/` into iCloud Drive and leave a link behind; the app doesn't notice, and everything syncs.
```
mv ~/Desktop/cognitioflow/data ~/Library/Mobile\ Documents/com~apple~CloudDocs/CognitioFlow-data && ln -s ~/Library/Mobile\ Documents/com~apple~CloudDocs/CognitioFlow-data ~/Desktop/cognitioflow/data
```

## Notes
- The course tutor prompt (per course) is in the `courses` table; European Law ships with the standing traps pre-loaded. Edit via PUT /api/courses/{id} or a SQLite browser.
- Context budget ≈ 180k characters of file text per message (≈45k tokens). Over that, later files are truncated — untick what you don't need.
- Images: up to 6 ticked images are sent with each message. Keep photographed notes ticked only while reconciling them.
- Back up `data/` — it's everything.

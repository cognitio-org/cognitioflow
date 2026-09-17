#!/usr/bin/env bash
# Phase 7 cutover: move the laptop build's data into Neon and the bucket, checking every step.
#
#   bash scripts/cutover.sh --from ~/Desktop/cognitioflow              # dry run (default): read-only checks and counts
#   bash scripts/cutover.sh --from ~/Desktop/cognitioflow --execute    # do it, pausing for confirmation before every write
#
# Rehearsal only (tests, local docker):
#   bash scripts/cutover.sh --from DIR --workdir DIR --execute --local --yes --allow-running
#
# Cloud mode reads DATABASE_URL from Secret Manager (never printed) and uploads to gs://cognitioflow-user-content
# with your ADC. The laptop folder is only read: the SQLite file is copied with `sqlite3 .backup`, data/ with cp,
# and every later step works on those copies.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
PROJECT=vigilant-axis-483119-r8
BUCKET=cognitioflow-user-content
NEON_PROJECT=long-shadow-92858463
APP_URL=https://cognitioflow-sarfwmfd3q-ez.a.run.app
STAMP=$(date +%Y%m%d-%H%M)
FROM="" WORK="$HOME/cf-cutover-$STAMP" EXECUTE=0 LOCAL=0 YES=0 ALLOW_RUNNING=0

while (($#)); do
  case "$1" in
    --from) FROM="$2"; shift ;;
    --workdir) WORK="$2"; shift ;;
    --execute) EXECUTE=1 ;;
    --local) LOCAL=1 ;;
    --yes) YES=1 ;;
    --allow-running) ALLOW_RUNNING=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done
[[ -n "$FROM" ]] || { echo "--from <laptop build folder> is required" >&2; exit 2; }
FROM=${FROM/#\~/$HOME}
SRC_DB="$FROM/data/cognitioflow.db"
SRC_DATA="$FROM/data"

step() { printf '\n== %s\n' "$*"; }
ok() { printf '  ✓ %s\n' "$*"; }
die() { printf '  ✗ %s\n' "$*" >&2; exit 1; }
confirm() {
  (( YES )) && return 0
  local answer
  read -r -p "  → $* [y/N] " answer
  [[ "$answer" == y || "$answer" == Y ]] || die "stopped by you — nothing after this point was done"
}

cd "$ROOT"
step "Preflight ($( (( EXECUTE )) && echo EXECUTE || echo 'DRY RUN — nothing is written' ))"
for tool in python3 sqlite3; do command -v "$tool" >/dev/null || die "$tool is not installed"; done
[[ -f "$SRC_DB" ]] || die "no SQLite database at $SRC_DB"
[[ -d "$SRC_DATA" ]] || die "no data folder at $SRC_DATA"
ok "laptop build: $FROM"
if lsof -iTCP:8000 -sTCP:LISTEN -P >/dev/null 2>&1 && (( ! ALLOW_RUNNING )); then
  if (( EXECUTE )); then die "the laptop app is still running on :8000 — stop it first so nothing changes after the snapshot"; fi
  echo "  ! the laptop app is still running on :8000 (fine for a dry run; stop it before --execute)"
fi

if (( LOCAL )); then
  [[ -n "${DATABASE_URL:-}" ]] || die "--local needs DATABASE_URL in the environment"
  export STORAGE=${STORAGE:-local}
  ok "local rehearsal: DATABASE_URL and STORAGE=$STORAGE from the environment"
else
  command -v gcloud >/dev/null || die "gcloud is not installed"
  DATABASE_URL=$(gcloud secrets versions access latest --secret DATABASE_URL --project "$PROJECT" 2>/dev/null) \
    || die "could not read DATABASE_URL from Secret Manager"
  export DATABASE_URL STORAGE=gcs GCS_BUCKET="$BUCKET" GCP_PROJECT="$PROJECT"
  unset STORAGE_EMULATOR_HOST STORAGE_LOCAL_ROOT
  ok "target: Neon production (DATABASE_URL from Secret Manager, not shown) and gs://$BUCKET"
fi
export MATEJ_EMAIL=${MATEJ_EMAIL:-matej@mgms.eu}

python3 - <<'PY' || die "the target database isn't ready (unreachable, or the app hasn't created its tables yet)"
import os, psycopg
with psycopg.connect(os.environ["DATABASE_URL"], connect_timeout=30) as c:
    applied = {r[0] for r in c.execute("SELECT version FROM schema_migrations")}
    missing = {"001_initial", "002_storage_keys", "003_jobs", "006_card_week"} - applied
    if missing:
        raise SystemExit(f"  migrations missing on the target: {sorted(missing)}")
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("courses", "notes", "cards", "files", "recordings")}
    print("  ✓ target schema is current; rows already there:", ", ".join(f"{k} {v}" for k, v in counts.items()))
PY

check_files() {  # every file/recording the SQLite database points at must exist in the data folder
  python3 - "$1" "$2" <<'PY'
import sqlite3, sys
from pathlib import PurePath
sys.path.insert(0, ".")
import storage
db_path, data_dir = sys.argv[1], sys.argv[2]
local = storage.LocalStorage(data_dir)
db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
total = missing = 0
for table, folder in (("files", "uploads"), ("recordings", "audio")):
    for (path,) in db.execute(f"SELECT path FROM {table} WHERE COALESCE(path, '') <> ''"):
        total += 1
        key = f"{folder}/{PurePath(path).name}"
        if not local.exists(key):
            missing += 1
            print(f"  ✗ {table}: {key} is referenced but not in the data folder")
print(f"  {'✓' if not missing else '✗'} {total} stored file(s) referenced by the database, {missing} missing")
sys.exit(1 if missing else 0)
PY
}

if (( ! EXECUTE )); then
  step "1. Database — counts only"
  python3 migrate_sqlite.py --sqlite "$SRC_DB" --dry-run
  step "2. Files and audio — does every referenced file exist?"
  check_files "$SRC_DB" "$SRC_DATA" || die "fix or accept the missing files before --execute"
  step "Dry run complete — nothing was written"
  echo "  When ready (laptop app stopped): bash scripts/cutover.sh --from \"$FROM\" --execute"
  exit 0
fi

step "1. Snapshot the laptop data into $WORK"
confirm "copy the SQLite database and data/uploads, data/audio into $WORK?"
mkdir -p "$WORK/data"
sqlite3 "$SRC_DB" ".backup '$WORK/cognitioflow.db'"
for sub in uploads audio; do
  if [[ -d "$SRC_DATA/$sub" ]]; then cp -R "$SRC_DATA/$sub" "$WORK/data/"; fi
done
SNAP_DB="$WORK/cognitioflow.db"
SNAP_DATA="$WORK/data"
ok "snapshot taken; every step below works on the copy"
check_files "$SNAP_DB" "$SNAP_DATA" || confirm "some files are missing (listed above) — continue anyway?"

step "2. Restore point on Neon"
if (( LOCAL )); then
  ok "skipped in a local rehearsal"
elif [[ -n "${NEON_API_KEY:-}" ]]; then
  confirm "create Neon branch pre-cutover-$STAMP from production as a restore point?"
  curl -fsS -X POST "https://console.neon.tech/api/v2/projects/$NEON_PROJECT/branches" \
    -H "Authorization: Bearer $NEON_API_KEY" -H "Content-Type: application/json" \
    -d "{\"branch\": {\"name\": \"pre-cutover-$STAMP\"}}" >/dev/null || die "could not create the Neon branch"
  ok "Neon branch pre-cutover-$STAMP created"
else
  echo "  Create a branch of 'production' named pre-cutover-$STAMP in the Neon console (Branches → New branch)."
  confirm "done?"
fi

step "3. Database"
python3 migrate_sqlite.py --sqlite "$SNAP_DB" --dry-run
confirm "copy these rows into the target database?"
python3 migrate_sqlite.py --sqlite "$SNAP_DB"
python3 migrate_sqlite.py --sqlite "$SNAP_DB" --verify || die "verify failed — restore from the pre-cutover branch before trying again"

step "4. Files and audio"
python3 migrate_storage.py --data "$SNAP_DATA" --dry-run || die "file counts don't reconcile (see above)"
confirm "upload the files and recordings to storage and rewrite their keys?"
python3 migrate_storage.py --data "$SNAP_DATA"
python3 migrate_storage.py --verify || die "storage verify failed"

step "Cutover complete"
echo "  Check in the app ($( (( LOCAL )) && echo 'your local app' || echo "$APP_URL" )):"
echo "   - Files: every file under the right week, with its text"
echo "   - Notes: recordings play and seek"
echo "   - Recall: due count matches the laptop; Planner and Progress intact"
echo "   - Reconcile one note and transcribe one short recording"
echo "  Keep $FROM untouched for two weeks; the snapshot is in $WORK."

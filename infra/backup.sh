#!/usr/bin/env bash
# Phase 7 backups: the weekly Cloud Run job that copies the database and every stored file into gs://cognitioflow-backups.
#
#   bash infra/backup.sh                     # dry run (default): read-only checks, prints every change, makes none
#   bash infra/backup.sh --apply             # make the changes
#   bash infra/backup.sh --apply --run-now   # ...then take one backup now and wait for it
#
# Order: run --apply (service account, permissions, buckets); merge to main (the deploy builds the backup image and
# creates the Cloud Run job); run --apply again (the invoker binding and the weekly schedule need the job to exist).
# Idempotent: existing resources and bindings are detected and kept. Existing bucket lifecycle rules are never replaced.
set -euo pipefail

PROJECT=vigilant-axis-483119-r8
REGION=europe-west4
JOB=cognitioflow-backup
SOURCE_BUCKET=cognitioflow-user-content
BACKUP_BUCKET=cognitioflow-backups
BACKUP_SA_NAME=cognitioflow-backup
BACKUP_SA="${BACKUP_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="cognitioflow-deploy@${PROJECT}.iam.gserviceaccount.com"
SCHEDULER_JOB=cognitioflow-backup-weekly
SCHEDULE="0 3 * * 0"          # Sundays 03:00
TIME_ZONE=Europe/Amsterdam
BACKUP_RETENTION_DAYS=365      # Coldline bills a 90-day minimum per object; a year of weekly backups is ~5 GB today
NONCURRENT_DAYS=30             # a deleted or replaced upload stays recoverable in the live bucket this long
APIS=(run.googleapis.com cloudscheduler.googleapis.com storage.googleapis.com secretmanager.googleapis.com iam.googleapis.com)

APPLY=0
RUN_NOW=0
for arg in "$@"; do
  case "$arg" in
    --apply) APPLY=1 ;;
    --run-now) RUN_NOW=1 ;;
    -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\n== %s\n' "$*"; }
keep() { printf '  exists, keep: %s\n' "$*"; }
run() {
  if (( APPLY )); then printf '  + %s\n' "$(printf '%q ' "$@")"; "$@"
  else printf '  [dry-run] %s\n' "$(printf '%q ' "$@")"; fi
}
exists() { "$@" >/dev/null 2>&1; }

policy_has() {
  python3 -c '
import json, sys
role, member = sys.argv[1], sys.argv[2]
policy = json.loads(sys.stdin.read() or "{}")
sys.exit(0 if any(b.get("role") == role and member in b.get("members", []) for b in policy.get("bindings", [])) else 1)
' "$2" "$3" <<<"$1"
}

# grant <bucket|sa|secret|job> <target> <role> <member>
grant() {
  local kind=$1 target=$2 role=$3 member=$4 policy
  local -a get add
  case "$kind" in
    bucket) get=(gcloud storage buckets get-iam-policy "gs://$target" --project "$PROJECT")
            add=(gcloud storage buckets add-iam-policy-binding "gs://$target" --project "$PROJECT") ;;
    sa)     get=(gcloud iam service-accounts get-iam-policy "$target" --project "$PROJECT")
            add=(gcloud iam service-accounts add-iam-policy-binding "$target" --project "$PROJECT") ;;
    secret) get=(gcloud secrets get-iam-policy "$target" --project "$PROJECT")
            add=(gcloud secrets add-iam-policy-binding "$target" --project "$PROJECT") ;;
    job)    get=(gcloud run jobs get-iam-policy "$target" --region "$REGION" --project "$PROJECT")
            add=(gcloud run jobs add-iam-policy-binding "$target" --region "$REGION" --project "$PROJECT") ;;
    *) echo "grant: unknown kind $kind" >&2; exit 2 ;;
  esac
  if policy=$("${get[@]}" --format=json 2>/dev/null) && policy_has "$policy" "$role" "$member"; then
    keep "$role for $member on $kind $target"
  else
    run "${add[@]}" --role "$role" --member "$member" --format none
  fi
}

# lifecycle <bucket> <json> — set a lifecycle config only when the bucket has none (never replace someone's rules)
lifecycle() {
  local bucket=$1 json=$2 current file
  current=$(gcloud storage buckets describe "gs://$bucket" --project "$PROJECT" --format='json(lifecycle_config)' 2>/dev/null || echo '{}')
  if python3 -c 'import json,sys; sys.exit(0 if (json.load(sys.stdin) or {}).get("lifecycle_config") else 1)' <<<"$current"; then
    keep "lifecycle rules on gs://$bucket (left as they are): $(tr -d '\n ' <<<"$current")"
  else
    file=$(mktemp); printf '%s\n' "$json" > "$file"
    printf '  lifecycle for gs://%s: %s\n' "$bucket" "$json"
    run gcloud storage buckets update "gs://$bucket" --project "$PROJECT" --lifecycle-file "$file"
    rm -f "$file"
  fi
}

(( APPLY )) || echo "DRY RUN — read-only checks; nothing below is changed. Re-run with --apply to make these changes."
command -v gcloud >/dev/null || { echo "gcloud is not installed" >&2; exit 1; }
gcloud auth print-access-token >/dev/null 2>&1 || { echo "gcloud is not signed in (or the login expired): run gcloud auth login" >&2; exit 1; }
echo "project $PROJECT, region $REGION, as $(gcloud auth list --filter=status:ACTIVE --format='value(account)' | head -n1)"

say "APIs"
ENABLED=$(gcloud services list --enabled --project "$PROJECT" --format='value(config.name)')
MISSING=()
for api in "${APIS[@]}"; do if grep -qx "$api" <<<"$ENABLED"; then keep "$api"; else MISSING+=("$api"); fi; done
(( ${#MISSING[@]} )) && run gcloud services enable "${MISSING[@]}" --project "$PROJECT"

say "Backup bucket gs://$BACKUP_BUCKET"
if exists gcloud storage buckets describe "gs://$BACKUP_BUCKET" --project "$PROJECT"; then
  keep "gs://$BACKUP_BUCKET ($(gcloud storage buckets describe "gs://$BACKUP_BUCKET" --project "$PROJECT" --format='value(default_storage_class,location)'))"
else
  run gcloud storage buckets create "gs://$BACKUP_BUCKET" --project "$PROJECT" --location "$REGION" \
    --default-storage-class COLDLINE --uniform-bucket-level-access --public-access-prevention
fi
lifecycle "$BACKUP_BUCKET" "{\"rule\":[{\"action\":{\"type\":\"Delete\"},\"condition\":{\"age\":$BACKUP_RETENTION_DAYS}}]}"

say "Live bucket gs://$SOURCE_BUCKET: object versioning"
if [[ "$(gcloud storage buckets describe "gs://$SOURCE_BUCKET" --project "$PROJECT" --format='value(versioning_enabled)')" == "True" ]]; then
  keep "versioning on gs://$SOURCE_BUCKET"
else
  run gcloud storage buckets update "gs://$SOURCE_BUCKET" --project "$PROJECT" --versioning
fi
lifecycle "$SOURCE_BUCKET" "{\"rule\":[{\"action\":{\"type\":\"Delete\"},\"condition\":{\"daysSinceNoncurrentTime\":$NONCURRENT_DAYS}}]}"

say "Backup service account $BACKUP_SA"
if exists gcloud iam service-accounts describe "$BACKUP_SA" --project "$PROJECT"; then keep "$BACKUP_SA"
else run gcloud iam service-accounts create "$BACKUP_SA_NAME" --project "$PROJECT" --display-name "CognitioFlow weekly backup"; fi
# Write-once into the backups (objectCreator cannot delete or overwrite), read to verify what it wrote, read the live bucket.
grant bucket "$BACKUP_BUCKET" roles/storage.objectCreator "serviceAccount:$BACKUP_SA"
grant bucket "$BACKUP_BUCKET" roles/storage.objectViewer  "serviceAccount:$BACKUP_SA"
grant bucket "$SOURCE_BUCKET" roles/storage.objectViewer  "serviceAccount:$BACKUP_SA"
grant secret DATABASE_URL roles/secretmanager.secretAccessor "serviceAccount:$BACKUP_SA"
# The GitHub deploy creates/updates the job with this identity.
grant sa "$BACKUP_SA" roles/iam.serviceAccountUser "serviceAccount:$DEPLOY_SA"

say "Cloud Run job $JOB and weekly schedule"
if exists gcloud run jobs describe "$JOB" --region "$REGION" --project "$PROJECT"; then
  keep "job $JOB (image $(gcloud run jobs describe "$JOB" --region "$REGION" --project "$PROJECT" --format='value(spec.template.spec.template.spec.containers[0].image)'))"
  grant job "$JOB" roles/run.invoker "serviceAccount:$BACKUP_SA"
  URI="https://run.googleapis.com/v2/projects/$PROJECT/locations/$REGION/jobs/$JOB:run"
  if exists gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT"; then
    keep "schedule $SCHEDULER_JOB: $(gcloud scheduler jobs describe "$SCHEDULER_JOB" --location "$REGION" --project "$PROJECT" --format='value(schedule,timeZone,state)')"
  else
    run gcloud scheduler jobs create http "$SCHEDULER_JOB" --project "$PROJECT" --location "$REGION" \
      --schedule "$SCHEDULE" --time-zone "$TIME_ZONE" --uri "$URI" --http-method POST \
      --oauth-service-account-email "$BACKUP_SA" --oauth-token-scope https://www.googleapis.com/auth/cloud-platform \
      --attempt-deadline 180s --description "Weekly CognitioFlow backup (infra/backup.sh)"
  fi
  if (( RUN_NOW )); then
    say "Backup now"
    run gcloud run jobs execute "$JOB" --region "$REGION" --project "$PROJECT" --wait
    (( APPLY )) && gcloud storage ls "gs://$BACKUP_BUCKET/" | tail -n 3
  fi
else
  echo "  not deployed yet: merge to main (the deploy creates $JOB), then run this script again for the schedule."
fi
echo
echo "Done$( (( APPLY )) || echo ' (dry run)')."

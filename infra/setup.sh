#!/usr/bin/env bash
# One-time, idempotent GCP setup for CognitioFlow on Cloud Run (Phase 5).
#
#   bash infra/setup.sh --dry-run    # read-only checks; prints every mutating command, runs none
#   bash infra/setup.sh              # apply (secrets from env vars, else prompted with read -s)
#   bash infra/setup.sh --rotate     # also add new versions to secrets that already have one
#
# Secrets: ANTHROPIC_API_KEY, DATABASE_URL, SESSION_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET.
# If set in the environment they are piped to gcloud on stdin and never echoed; otherwise prompted.
# An empty SESSION_SECRET answer generates one. Existing resources are detected and kept.
set -euo pipefail

PROJECT=vigilant-axis-483119-r8
REGION=europe-west4
SERVICE=cognitioflow
AR_REPO=cognitioflow
BUCKET=cognitioflow-user-content
RUN_SA_NAME=cognitioflow-run
DEPLOY_SA_NAME=cognitioflow-deploy
RUN_SA="${RUN_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
DEPLOY_SA="${DEPLOY_SA_NAME}@${PROJECT}.iam.gserviceaccount.com"
OWNER_EMAIL=matej@mgms.eu
GITHUB_REPO=cognitio-org/cognitioflow
GITHUB_REPO_ID=1367526874          # gh api repos/cognitio-org/cognitioflow -q .id (survives renames/transfers)
DEPLOY_REF=refs/heads/main
POOL=github
PROVIDER=github
SECRETS=(ANTHROPIC_API_KEY DATABASE_URL SESSION_SECRET GOOGLE_CLIENT_ID GOOGLE_CLIENT_SECRET)
APIS=(run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com speech.googleapis.com
      iamcredentials.googleapis.com iam.googleapis.com sts.googleapis.com cloudresourcemanager.googleapis.com
      storage.googleapis.com aiplatform.googleapis.com)

DRY_RUN=0
ROTATE=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --rotate) ROTATE=1 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

say()  { printf '\n== %s\n' "$*"; }
keep() { printf '  exists, keep: %s\n' "$*"; }
# Run a mutating command, or only print it (shell-quoted, real values) under --dry-run.
run() {
  if (( DRY_RUN )); then printf '  [dry-run] %s\n' "$(printf '%q ' "$@")"
  else printf '  + %s\n' "$(printf '%q ' "$@")"; "$@"; fi
}
exists() { "$@" >/dev/null 2>&1; }

# policy_has <policy-json> <role> <member>
policy_has() {
  python3 -c '
import json, sys
role, member = sys.argv[1], sys.argv[2]
policy = json.loads(sys.stdin.read() or "{}")
sys.exit(0 if any(b.get("role") == role and member in b.get("members", []) for b in policy.get("bindings", [])) else 1)
' "$2" "$3" <<<"$1"
}

# grant <project|bucket|sa|secret|repo> <target> <role> <member> — add the binding unless it is already there.
grant() {
  local kind=$1 target=$2 role=$3 member=$4 policy
  local -a get add
  case "$kind" in
    project) get=(gcloud projects get-iam-policy "$PROJECT")
             add=(gcloud projects add-iam-policy-binding "$PROJECT" --condition=None) ;;
    bucket)  get=(gcloud storage buckets get-iam-policy "gs://$target" --project "$PROJECT")
             add=(gcloud storage buckets add-iam-policy-binding "gs://$target" --project "$PROJECT") ;;
    sa)      get=(gcloud iam service-accounts get-iam-policy "$target" --project "$PROJECT")
             add=(gcloud iam service-accounts add-iam-policy-binding "$target" --project "$PROJECT") ;;
    secret)  get=(gcloud secrets get-iam-policy "$target" --project "$PROJECT")
             add=(gcloud secrets add-iam-policy-binding "$target" --project "$PROJECT") ;;
    repo)    get=(gcloud artifacts repositories get-iam-policy "$target" --location "$REGION" --project "$PROJECT")
             add=(gcloud artifacts repositories add-iam-policy-binding "$target" --location "$REGION" --project "$PROJECT") ;;
    *) echo "grant: unknown kind $kind" >&2; exit 2 ;;
  esac
  if policy=$("${get[@]}" --format=json 2>/dev/null) && policy_has "$policy" "$role" "$member"; then
    keep "$role for $member on $kind $target"
  else
    run "${add[@]}" --role "$role" --member "$member" --format none
  fi
}

(( DRY_RUN )) && echo "DRY RUN — read-only checks only; nothing below is changed."
command -v gcloud >/dev/null || { echo "gcloud is not installed" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required (IAM policy checks)" >&2; exit 1; }
ACCOUNT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | head -n1)
[[ -n "$ACCOUNT" ]] || { echo "No active gcloud account: run gcloud auth login" >&2; exit 1; }
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
echo "project $PROJECT ($PROJECT_NUMBER), region $REGION, as $ACCOUNT"

WIF_POOL_ID="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
WIF_PROVIDER_ID="${WIF_POOL_ID}/providers/${PROVIDER}"
WIF_CONDITION="assertion.repository_id=='${GITHUB_REPO_ID}' && assertion.repository=='${GITHUB_REPO}' && assertion.ref=='${DEPLOY_REF}'"

say "APIs"
ENABLED=$(gcloud services list --enabled --project "$PROJECT" --format='value(config.name)')
MISSING=()
for api in "${APIS[@]}"; do
  if grep -qx "$api" <<<"$ENABLED"; then keep "$api"; else MISSING+=("$api"); fi
done
if (( ${#MISSING[@]} )); then run gcloud services enable "${MISSING[@]}" --project "$PROJECT"; fi

say "Bucket gs://$BUCKET"
if exists gcloud storage buckets describe "gs://$BUCKET" --project "$PROJECT"; then keep "gs://$BUCKET"
else run gcloud storage buckets create "gs://$BUCKET" --project "$PROJECT" --location "$REGION" \
       --uniform-bucket-level-access --public-access-prevention; fi

say "Artifact Registry repo $AR_REPO"
if exists gcloud artifacts repositories describe "$AR_REPO" --location "$REGION" --project "$PROJECT"; then keep "$AR_REPO"
else run gcloud artifacts repositories create "$AR_REPO" --repository-format docker --location "$REGION" \
       --project "$PROJECT" --description "CognitioFlow Cloud Run images"; fi

say "Runtime service account $RUN_SA"
if exists gcloud iam service-accounts describe "$RUN_SA" --project "$PROJECT"; then keep "$RUN_SA"
else run gcloud iam service-accounts create "$RUN_SA_NAME" --project "$PROJECT" --display-name "CognitioFlow Cloud Run"; fi
grant bucket  "$BUCKET"  roles/storage.objectAdmin              "serviceAccount:$RUN_SA"
grant project "$PROJECT" roles/speech.client                    "serviceAccount:$RUN_SA"
grant project  "$PROJECT"  roles/aiplatform.user                "serviceAccount:$RUN_SA"   # Phase 8: Gemini dictation via Vertex AI
grant sa      "$RUN_SA"  roles/iam.serviceAccountTokenCreator   "serviceAccount:$RUN_SA"   # signed URLs
grant sa      "$RUN_SA"  roles/iam.serviceAccountTokenCreator   "user:$OWNER_EMAIL"        # local impersonation

say "Secrets (Secret Manager)"
for name in "${SECRETS[@]}"; do
  if exists gcloud secrets describe "$name" --project "$PROJECT"; then keep "secret $name"
  else run gcloud secrets create "$name" --project "$PROJECT" --replication-policy automatic; fi
  grant secret "$name" roles/secretmanager.secretAccessor "serviceAccount:$RUN_SA"

  has_version=""
  if exists gcloud secrets describe "$name" --project "$PROJECT"; then
    has_version=$(gcloud secrets versions list "$name" --project "$PROJECT" --filter='state=ENABLED' --limit 1 --format='value(name)' 2>/dev/null || true)
  fi
  if [[ -n "$has_version" ]] && (( ! ROTATE )); then keep "$name has an enabled version (pass --rotate to add a new one)"; continue; fi

  source_desc="prompt (read -s)"
  [[ -n "${!name:-}" ]] && source_desc="environment variable \$$name"
  if (( DRY_RUN )); then
    printf '  [dry-run] printf %%s "$%s" | gcloud secrets versions add %s --project %s --data-file=-   # value: ******** from %s\n' \
      "$name" "$name" "$PROJECT" "$source_desc"
    continue
  fi
  value="${!name:-}"
  if [[ -z "$value" ]]; then
    read -rsp "  $name (input hidden${name/#SESSION_SECRET/, empty = generate}): " value; echo
    if [[ -z "$value" && "$name" == SESSION_SECRET ]]; then
      value=$(python3 -c 'import secrets; print(secrets.token_urlsafe(48), end="")')
    fi
  fi
  [[ -n "$value" ]] || { echo "  $name is empty; aborting" >&2; exit 1; }
  printf '  + printf %%s "$%s" | gcloud secrets versions add %s --project %s --data-file=-   # value: ********\n' "$name" "$name" "$PROJECT"
  printf %s "$value" | gcloud secrets versions add "$name" --project "$PROJECT" --data-file=- --format none
  unset value
done

say "Workload Identity Federation (GitHub Actions -> GCP, no JSON keys)"
if exists gcloud iam workload-identity-pools describe "$POOL" --location global --project "$PROJECT"; then keep "pool $POOL"
else run gcloud iam workload-identity-pools create "$POOL" --location global --project "$PROJECT" --display-name "GitHub Actions"; fi
if exists gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" --location global --project "$PROJECT"; then
  current=$(gcloud iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool "$POOL" \
              --location global --project "$PROJECT" --format='value(attributeCondition)')
  if [[ "$current" == "$WIF_CONDITION" ]]; then keep "provider $PROVIDER (condition matches)"
  else run gcloud iam workload-identity-pools providers update-oidc "$PROVIDER" --workload-identity-pool "$POOL" \
         --location global --project "$PROJECT" --attribute-condition "$WIF_CONDITION"; fi
else
  run gcloud iam workload-identity-pools providers create-oidc "$PROVIDER" --workload-identity-pool "$POOL" \
    --location global --project "$PROJECT" --display-name "GitHub $GITHUB_REPO" \
    --issuer-uri https://token.actions.githubusercontent.com \
    --attribute-mapping 'google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.repository_id=assertion.repository_id,attribute.ref=assertion.ref' \
    --attribute-condition "$WIF_CONDITION"
fi

say "Deployer service account $DEPLOY_SA"
if exists gcloud iam service-accounts describe "$DEPLOY_SA" --project "$PROJECT"; then keep "$DEPLOY_SA"
else run gcloud iam service-accounts create "$DEPLOY_SA_NAME" --project "$PROJECT" --display-name "CognitioFlow GitHub deployer"; fi
# run.admin (not run.developer): the deploy sets --allow-unauthenticated, which needs run.services.setIamPolicy.
grant project "$PROJECT"   roles/run.admin                  "serviceAccount:$DEPLOY_SA"
grant repo    "$AR_REPO"   roles/artifactregistry.writer    "serviceAccount:$DEPLOY_SA"
grant sa      "$RUN_SA"    roles/iam.serviceAccountUser     "serviceAccount:$DEPLOY_SA"   # deploy as cognitioflow-run
grant sa      "$DEPLOY_SA" roles/iam.workloadIdentityUser \
  "principalSet://iam.googleapis.com/${WIF_POOL_ID}/attribute.repository/${GITHUB_REPO}"

say "GitHub repo settings to add (run these; values for secrets are read from your environment)"
cat <<GH
  gh variable set GCP_WIF_PROVIDER --repo $GITHUB_REPO --body '$WIF_PROVIDER_ID'
  gh variable set GCP_DEPLOY_SA    --repo $GITHUB_REPO --body '$DEPLOY_SA'
  gh variable set NEON_PROJECT_ID  --repo $GITHUB_REPO --body "\$NEON_PROJECT_ID"
  printf %s "\$NEON_API_KEY" | gh secret set NEON_API_KEY --repo $GITHUB_REPO   # value: ********
GH

say "After the first deploy [Matej]"
cat <<NEXT
  URL:   gcloud run services describe $SERVICE --region $REGION --project $PROJECT --format='value(status.url)'
  OAuth: add <URL>/auth/callback to the OAuth client's authorised redirect URIs
         (GCP console -> APIs & Services -> Credentials -> the web client).
NEXT
(( DRY_RUN )) && printf '\nDRY RUN complete — nothing was changed.\n'

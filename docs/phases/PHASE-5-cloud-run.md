# Phase 5 — Dockerfile, Cloud Run, auto-deploy

Branch: `phase-5-cloud-run`. Depends on Phases 1–4.

## Decisions — settled (2026-09-12)
- **Region:** `europe-west4` (Netherlands) — closest to Groningen and to Neon's EU region.
- **Service name / URL:** `cognitioflow` on Cloud Run; custom domain optional later.
- **Deploy trigger:** on merge to `main`, with a manual `workflow_dispatch` fallback.
- **Scaling:** min 0 / max 2 instances, 1 GiB, 1 CPU. Cold starts accepted; no always-warm instance.

## Objective
The app runs on Cloud Run in `vigilant-axis-483119-r8`, scale-to-zero, reading secrets from Secret Manager, talking to Neon and the bucket. Merging to `main` deploys. The Mac is no longer required for anything.

## Deliverables
1. `Dockerfile`: `python:3.12-slim`, non-root user, `pip install -r requirements.txt` (which no longer contains faster-whisper), copy `run.py static/ prompts/ migrations/ storage.py transcribe/`, `CMD uvicorn run:app --host 0.0.0.0 --port 8080`. Image < 300 MB. `.dockerignore` excludes `data/`, `.env*`, `.venv/`, tests, docs.
2. Startup runs migrations (`python -m migrate && uvicorn …`) — idempotent, so multiple instances are safe.
3. `infra/setup.sh` — one-time, idempotent `gcloud` script **[Matej runs it]**: enable APIs (run, artifactregistry, secretmanager, speech, iamcredentials), create Artifact Registry repo, service account `cognitioflow-run@…` with `secretmanager.secretAccessor`, `storage.objectAdmin` on `cognitioflow-user-content` only (the Phase 7 backup job gets its own service account), `speech.client`, and `iam.serviceAccountTokenCreator` on itself (for signed URLs), create the five secrets (values entered interactively, never in the script). The bucket `cognitioflow-user-content` and service account `cognitioflow-run` (with its bucket role and token-creator bindings) already exist — created during Phase 2 on 2026-09-12 — so the script must detect and keep them.
4. `.github/workflows/deploy.yml`: on push to `main` — build with Cloud Build or `docker build` + push to Artifact Registry, `gcloud run deploy cognitioflow --image … --region europe-west4 --min-instances 0 --max-instances 2 --memory 1Gi --cpu 1 --concurrency 20 --set-secrets ANTHROPIC_API_KEY=…:latest,DATABASE_URL=…,SESSION_SECRET=…,GOOGLE_CLIENT_ID=…,GOOGLE_CLIENT_SECRET=… --set-env-vars ENV=production,STORAGE=gcs,GCS_BUCKET=…,STT=hosted,STT_PROVIDER=google,STT_REGION=europe-west4,ALLOWED_EMAILS=…`. Auth to GCP via Workload Identity Federation (no JSON key in GitHub secrets). Also a `test` job that runs `make test` against a Neon branch created for the PR and deleted after.
5. Add the Cloud Run URL to the OAuth client's redirect URIs **[Matej]**.
6. `README.md` "Cloud" section: URL, how to deploy, how to roll back (`gcloud run services update-traffic --to-revisions`), where logs are.

## Acceptance
- [ ] `docker build` locally + `docker run -p 8080:8080 --env-file .env.local` serves the app against docker Postgres.
- [ ] First deploy from GitHub Actions succeeds; the Cloud Run URL loads, sign-in works, all seven screens work against Neon + bucket, tutor call succeeds, cost readout shows.
- [ ] Cold start under 4 s (measure with `curl -w`); a warm request under 300 ms for `/api/courses`.
- [ ] A hosted transcription completes end to end from a recording made in the browser.
- [ ] Revoking the service account's bucket role makes uploads fail with a clear 500 — i.e. the app has no other credentials.
- [ ] Rolling back to the previous revision via the documented command works.

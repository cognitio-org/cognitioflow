# Phase 2 — Filesystem → object storage

Branch: `phase-2-storage`. Depends on Phase 1 merged.

## Decisions — settled
- **Provider: Google Cloud Storage** in `vigilant-axis-483119-r8`, bucket `cognitioflow-user-content`, region `europe-west4` (same as Cloud Run and Speech-to-Text). Uniform bucket-level access, no public objects; signed URLs only.
- Credentials: Application Default Credentials (the Cloud Run service account in cloud; `gcloud auth application-default login` locally). No JSON key files in the repo or `.env.local`. Signed URLs from an SA without a private key use the IAM `signBlob` API — grant the SA `roles/iam.serviceAccountTokenCreator` on itself.

## Objective
Every byte of user content — uploaded course files, lecture audio, printed/exported PDFs — goes through one `storage.py` seam with `local` and `gcs` backends. `run.py` stops building filesystem paths. The `path` columns become object keys.

## What exists today (verified)
Filesystem touchpoints in `run.py`:
- L151 upload write → `UPLOADS/{fid}_{name}`; L174 delete `unlink`; L188 `FileResponse` raw download; L199 reads PNG/JPEG bytes to send as base64 images to the tutor.
- L525 audio write → `AUDIO/{rid}.webm`; L539 `FileResponse` audio serve; L544 delete `unlink`.
- L831–870 watched-folder scan copies `WATCH/<course>/*` into `UPLOADS`.
- `extract()` (L78) runs at upload time and stores text in `files.text`; the tutor reads **text from the DB**, not from disk. So storage only ever holds raw bytes and serves them for download/playback/images.

## `storage.py` contract
```python
put(key: str, data: bytes | BinaryIO, content_type: str) -> None
get(key: str) -> bytes
stream(key: str) -> Iterator[bytes]          # for audio playback
url(key: str, expires_s: int = 3600) -> str  # signed URL (gcs) or /api/… route (local)
delete(key: str) -> None
exists(key: str) -> bool
```
Backend chosen by `STORAGE=local|gcs`. `local` writes under `STORAGE_LOCAL_ROOT` (default `./data`) with the same key layout, so dev and the fake-gcs profile behave identically.

Key layout: `courses/{cid}/files/{fid}/{original_name}` and `notes/{nid}/audio/{rid}.webm`. Keys are stored in the existing `path` column (rename to `key` via `migrations/002_storage_keys.sql`; keep the column type TEXT).

## Code changes
1. Upload (L147): `extract()` runs on the uploaded bytes via a temp file (pypdf/python-pptx need a path) → text into DB → `storage.put(key, bytes)`. Temp file deleted.
2. Raw download (L184): redirect to `storage.url(key)` for gcs; `StreamingResponse(storage.stream(key))` for local. Keep the route path unchanged — the UI links to it.
3. Tutor images (L199): `storage.get(key)` instead of `p.read_bytes()`. Respect `MAX_IMAGES`.
4. Audio finish (L523) / serve (L535) / delete (L541): same pattern. Serve must support HTTP range requests for `<audio>` seeking — use a redirect to a signed URL on gcs; for local, add range handling.
5. Delete file (L170): `storage.delete(key)` then DB row.
6. **Remove the watched folder** (L831–870, `WATCH`, `/api/courses/{cid}/watch`, `/scan`, the `watch_root` field in `/api/config`). In `index.html`, remove the "Drop files in Finder" hint and the Scan button by deleting their elements — keep every other `id`/`data-` attribute. The Files-screen upload becomes the only ingest; folder-watching is not coming back (local worker dropped 2026-09-12).
7. `migrate_storage.py`: walks `data/uploads` and `data/audio` from the old build, uploads each to the bucket under the new key layout, updates `files.key` / `recordings.key`. Idempotent, `--dry-run`, count check, non-zero exit on mismatch. Not run against prod until Phase 7.

## Acceptance
- [ ] `STORAGE=local`: upload PDF/PPTX/DOCX/PNG, download raw, tutor sees images, record + play back audio with seeking, delete both. No filesystem access outside `storage.py` (`grep -n "UPLOADS\|AUDIO\|WATCH\|read_bytes\|write_bytes\|FileResponse" run.py` returns only the `index.html` route).
- [ ] `docker compose --profile gcs up -d` + `STORAGE=gcs STORAGE_EMULATOR_HOST=…`: same suite passes.
- [ ] Against the real bucket with ADC (`gcloud auth application-default login`): same suite passes; signed URLs open in an incognito window and expire.
- [ ] `migrate_storage.py --dry-run` on the old `data/` reports counts matching `SELECT COUNT(*) FROM files` / `recordings`.
- [ ] Watch-folder code and UI gone; `index.html` diff touches only those elements.

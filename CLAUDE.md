# CLAUDE.md — CognitioFlow

Private legal study app for Matej (LLB, University of Groningen). Read this file fully before touching anything. `COGNITIOFLOW_GUIDE.md` is the human-facing reference; this file is the agent contract.

## What it is

FastAPI + Postgres backend (`run.py`) serving a single-file UI (`static/index.html`). Claude API powers the tutor, card writing and note reconciliation. Two courses ship (European Law, Property Law); more are added through the `courses` table, never through code.

## Where it is going (the migration)

The app is moving from a laptop-only build (SQLite in `data/`, local Whisper, watched Finder folder) to:

- **Cloud Run** (GCP project `vigilant-axis-483119-r8`) — the app, always on, scale-to-zero.
- **Neon Postgres** — all structured data. Local dev uses docker Postgres; tests/PRs use Neon branches.
- **Cloud Storage bucket** — uploaded files, lecture audio, printed PDFs. Never the filesystem.
- **Hosted STT** (Google Speech-to-Text v2) for lecture transcription. No local worker — the Mac is not part of the cloud build (decided 2026-09-12).
- **Google sign-in** restricted to allow-listed emails. Multi-user later; `user_id` on `courses` now.

Work proceeds in numbered phases. The current phase brief lives in `docs/phases/`. Do not pull work from later phases into the current one.

## Three seams — every backend change goes through one

1. `db()` / `rows()` — the only way to touch the database. Placeholders are `%s`. No SQLite-isms.
2. `storage.py` — `put(key, bytes|stream) / get(key) / url(key) / delete(key)`. Backends: `local` (dev), `gcs`. `run.py` never imports `google.cloud.storage` and never builds a filesystem path to user content.
3. `transcribe.py` — `transcribe(audio_key, language) -> Job`. Backend: `hosted` (`STT_PROVIDER=google`). Job state lives in the `jobs` table, never in process memory.

Environment selects the backend. There is no other configuration surface.

## Golden rules (from the guide — these are hard constraints)

- **Never touch `run.py` for a look change.** All styling is CSS tokens in `static/index.html` (`:root{}` block and its dark-mode counterpart). Change tokens, not scattered hex values.
- **Keep every `id` and `data-` attribute** in `index.html`. JS finds elements by `id` (`#fc`, `#agenda`, `#weekdir`, `#ratings`…) and `data-` hooks (`data-nav`, `data-mode`, `data-r`, `data-wk`…). Restyle, wrap, move — never rename or delete a hook.
- **Preserve JS-written class names.** Grep the `<script>` for a class before restyling it (`wk`, `sess done`, `prov`, `prio`, `callout`, `noteview`).
- **Don't break the note renderer**: `render()` → `chipify()` → `priomark()`. Style `.prov`, `.prio`, `.noteview`, `.callout`; don't edit the functions for a visual change.
- **No CSS framework, no build step, no bundler.** Two vendored libs only (`marked`, `mermaid`). No `!important` wars.
- **Visual changes are checked in light + dark, at ~1440px and ~1190px** (breakpoint at 1300px collapses the sidebar and hides the book). Screenshots before finalising.
- **Quality floor stays**: visible keyboard focus, `prefers-reduced-motion` respected, tap targets ≥ 32px, dark-mode contrast.
- **Design language**: one bold object (the Blackstone book), one accent used for meaning, no idle motion, serif for content / sans for chrome, sentence case. The seven Blackstone tab colours map to legal function — never repurpose them.

## Model and cost rules

- `CF_MODEL` (Sonnet) for drilling, explaining, reconcile-by-default. `CF_CHEAP_MODEL` (Haiku) for cards, notes, quiz distractors, garble cleaning. `CF_STRONG_MODEL` for reconcile only.
- **Fable is ~10× a Sonnet call. Auto-routing must never select it.** It is opt-in per call only.
- Tutor rules + selected files are sent as cached blocks; the per-message mode block sits last so switching modes doesn't invalidate the file cache. Preserve this ordering.
- Reconcile: `max_tokens=8000` and a forced "Bottom line" section. Don't raise the cap; the Continue button handles truncation.

## Secrets and data

- `.env` and `data/` are never committed (`.gitignore` enforces). Never print secrets in logs or tests.
- In cloud, secrets come from Secret Manager as env vars. Code reads `os.environ` only.
- User content (notes, cards, audio) is never fabricated in tests against Neon branches — branch from prod, don't seed fake notes into it.

## Dev workflow

```
docker compose up -d           # Postgres (and fake-gcs with --profile gcs)
cp .env.local.example .env.local && edit
make dev                       # uvicorn run:app --reload on :8000, reads .env.local
make test                      # pytest against docker Postgres
make db-branch NAME=pr-123     # Neon branch of prod for an isolated test DB
```

- Work on a branch; open a PR; the Claude PR-review bridge runs. Never work in `~/Desktop/cognitioflow` (that folder holds live `data/` and `.env`).
- One phase per PR. Keep PRs reviewable; if a phase needs splitting, split by seam (db / storage / transcribe), not by file.
- Before claiming a phase done, run the phase's acceptance checklist verbatim and paste the results in the PR description.

## Course-domain facts the tutor relies on (don't "fix" these)

- Authority hierarchy: annotated WG notes > lecture > slides > Schütze. Anything outside ticked files is labelled `[OUTSIDE FILES]`.
- Exam method (Villanueva): applicability → restriction/scope → justification + proportionality; IRAC.
- Provenance tags in notes: `[LECTURE] [WG] [SLIDES] [READER] [SCHUTZE] [ADDED]`.

## Things an agent must not do

- Add Electron, a bundler, Tailwind, React, or any front-end framework.
- Move job or session state into process memory, `localStorage` (beyond small view prefs), or module globals.
- Build filesystem paths to user content anywhere outside `storage.py`.
- Make Fable, Opus, or any model above `CF_MODEL` reachable by auto-routing.
- Change the schema without a numbered migration in `migrations/`.
- "Improve" tutor prompts, course facts, or note house style without an explicit instruction.

# CognitioFlow — Games pipeline

Static, framework-free law-study games. Each game is a course-agnostic template that
loads its content from `content/*.json` and renders in the browser (no bundler, no build step).

## Games
- `objection/` — first-person courtroom reaction game (spot flawed EU-law submissions).
  3D stage = a real Gaussian splat of the EU Grand Chamber, streamed from GCS
  (https://storage.googleapis.com/cf-splats-vigilant-axis-483119-r8/courtroom_full.splat).

## Run locally
    ./serve.sh            # serves this dir on http://127.0.0.1:8123
    open http://127.0.0.1:8123/objection/

## Why not a claude.ai artifact
Artifacts cap embeds at 16MB and block external fetches, so the full-res splat and real
first-person (pointer-lock) controls only work as a served static page like this.

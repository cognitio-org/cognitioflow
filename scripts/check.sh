#!/bin/bash
# Gate 1: one command, run before every push and by the Stop hook.
#
# Why this exists: on 2026-09-19 three CI failures in a row were test hygiene, not code — a module
# missing from the Dockerfile COPY line, a test asserting the wrong behaviour, and a test file
# deleting ANTHROPIC_API_KEY for the rest of the suite. Every one would have been caught here in
# under a minute. CI was being used as the place mistakes surface first.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 2
fail=0

if command -v ruff >/dev/null 2>&1; then
  echo "── ruff"
  ruff check . || fail=1
else
  echo "── ruff: not installed (brew install ruff) — skipping, not failing"
fi

echo "── pytest"
python3 -m pytest tests/ -q || fail=1

[ "$fail" -eq 0 ] && echo "✅ check: green" || echo "⛔ check: red"
exit "$fail"

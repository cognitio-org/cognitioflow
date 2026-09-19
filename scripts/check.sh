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

# The repo has carried four .test.mjs files since the extensions were written and nothing has
# ever run them. On 2026-09-19 one of them was found with two tests failing on a leaked timer,
# which is the kind of thing a test file is supposed to tell you about on the day. 44 tests.
#
# `node --test extension/` reports "pass 0, fail 1" - the directory form does not find these -
# so the files are named explicitly. A glob that matches nothing would make this silently pass,
# so it counts them first and fails if it finds none.
if command -v node >/dev/null 2>&1; then
  echo "── node --test"
  shopt -s nullglob
  jsfiles=(extension/*/test/*.test.mjs)
  shopt -u nullglob
  if [ "${#jsfiles[@]}" -eq 0 ]; then
    echo "no .test.mjs files matched — the glob is wrong, not the tests"; fail=1
  else
    node --test "${jsfiles[@]}" || fail=1
  fi
else
  echo "── node: not installed — skipping, not failing"
fi

echo "── pytest"
python3 -m pytest tests/ -q || fail=1

[ "$fail" -eq 0 ] && echo "✅ check: green" || echo "⛔ check: red"
exit "$fail"

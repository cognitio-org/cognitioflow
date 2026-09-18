#!/usr/bin/env bash
# Run pytest the way CI runs it, instead of against your own development setup.
#
# run.py does load_dotenv(".env.local", override=True). "override" means it beats
# the environment the caller exported, which causes two traps that have each cost
# real time:
#
#   1. conftest.py TRUNCATEs every table on each test. It does that against
#      .env.local's DATABASE_URL, not the one you exported — so a plain `pytest`
#      wipes the database you have been working in, silently.
#   2. .env.local sets ENV=development, which overrides the ENV=production that
#      tests/test_auth.py::test_production_with_auth_off_refuses_to_boot passes to
#      its subprocess. The test then fails for a reason that has nothing to do
#      with the code, and reads like a regression.
#
# This rewrites those two lines for the duration of the run and restores the file
# on any exit, Ctrl-C included. Everything else in .env.local is left as it is,
# because the auth tests need the OAuth settings that live there.
#
# Set $PYTHON if your interpreter is not on PATH as `python`; a .venv in the
# checkout is picked up automatically. Runs are serialised with a lock, so do not
# expect two of these to overlap, and stop `make dev` first if it is running.
#
#   bash scripts/runtests.sh                         # everything
#   bash scripts/runtests.sh tests/test_ui_routes.py -q
set -euo pipefail

cd "$(dirname "$0")/.."   # the checkout this script lives in — worktree-safe

TEST_DB="${CF_TEST_DB:-cognitioflow_test}"
TEST_URL="${CF_TEST_DATABASE_URL:-postgresql://cf:cf@127.0.0.1:5432/${TEST_DB}}"

# pytest truncates every table in whatever database it is handed. Refuse anything
# that is not visibly the throwaway one.
case "$TEST_URL" in
  */"$TEST_DB") ;;
  *) echo "refusing: \$CF_TEST_DATABASE_URL does not end in /${TEST_DB}" >&2; exit 1 ;;
esac

PY="${PYTHON:-}"
if [ -z "$PY" ]; then
  if [ -x .venv/bin/python ]; then PY=.venv/bin/python; else PY=python; fi
fi
if ! "$PY" -c 'import pytest' 2>/dev/null; then
  echo "refusing: $PY has no pytest. Set \$PYTHON to the interpreter with the" >&2
  echo "   project's requirements installed, or create .venv here." >&2; exit 1
fi

# One run at a time. This rewrites .env.local, which every process in this
# checkout reads — a second concurrent run, or a `make dev` started mid-run,
# would see the test database. Two agents working the same checkout hit exactly
# this today. flock serialises; if you are waiting, something else is testing.
if command -v flock >/dev/null 2>&1; then
  exec 9>".git/runtests.lock"
  flock -w 900 9 || { echo "another test run has held the lock for 15 minutes" >&2; exit 1; }
fi

# Neutralise the two lines that hurt, and leave the rest of .env.local alone:
# the auth tests legitimately need the Google/OAuth settings in it, so parking
# the whole file trades one broken suite for another.
if [ -f .env.local ]; then
  PARKED="$(mktemp .env.local.parked.XXXXXX)"
  cp .env.local "$PARKED"
  # Restore on any exit path, Ctrl-C included. Leaving .env.local pointed at the
  # test database is how the next `make dev` silently starts on an empty app.
  trap 'mv -f "$PARKED" .env.local' EXIT INT TERM
  sed -e "s|^DATABASE_URL=.*|DATABASE_URL=${TEST_URL}|" \
      -e "s|^ENV=.*|# ENV removed by scripts/runtests.sh: it overrides what the tests pass|" \
      "$PARKED" > .env.local
fi

DATABASE_URL="$TEST_URL" \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-sk-ant-test-key}" \
AUTH="${AUTH:-off}" \
ALLOWED_EMAILS="${ALLOWED_EMAILS:-matej@mgms.eu}" \
STORAGE="${STORAGE:-local}" \
CF_WHISPER_PRELOAD=0 \
  "$PY" -m pytest "$@"

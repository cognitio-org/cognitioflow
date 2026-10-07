#!/bin/bash
# Install Lector as the fourth daemon in the eu.mgms.cognitio family.
#
# The other three (dispatch, release-check, todo) live unversioned in ~/.cognitio, which the
# handoff calls the single biggest risk in the whole fleet. Lector is deliberately the other
# way round: the code stays in the repo under version control, and only its state — the feed,
# the digest and the seen-list — lives in ~/.cognitio/lector.
set -uo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"
state="$HOME/.cognitio/lector"
plist="$HOME/Library/LaunchAgents/eu.mgms.cognitio.lector.plist"

mkdir -p "$state" "$HOME/Library/LaunchAgents"

sed -e "s|REPO_PATH|$repo|g" -e "s|HOME_PATH|$HOME|g" \
    "$repo/research/eu.mgms.cognitio.lector.plist" > "$plist"

launchctl unload "$plist" 2>/dev/null
launchctl load "$plist" || { echo "launchctl load failed"; exit 1; }

echo "installed  eu.mgms.cognitio.lector  (daily 07:45)"
echo "state      $state"
echo
echo "Verify the endpoints before trusting a single result — they were written in a container"
echo "whose network policy blocked every one of these hosts, so none is confirmed:"
echo "    python3 $repo/research/lector.py --check"
echo
echo "Then take one harvest and look at it:"
echo "    python3 $repo/research/lector.py --once"

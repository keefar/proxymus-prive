#!/usr/bin/env bash
# Inspect zeroc00I/DontFeedTheAI upstream for changes since our pinned commit.
# Does NOT bump the submodule pin — just reports.
#
# What it watches for:
#   1. New commits on upstream main
#   2. Changes to src/regex_detector.py (where we vendor patterns from)
#   3. Changes to RegexMatch dataclass shape (affects our adapter)
#   4. Appearance of a LICENSE file (we filed upstream issue #3 asking for one)
#   5. Status of our outstanding PRs (queried via gh if available)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SUB="$ROOT/vendor/dontfeedtheai"

if [[ ! -e "$SUB/.git" ]]; then
  echo "vendor/dontfeedtheai not initialised; run: git submodule update --init" >&2
  exit 1
fi

cd "$SUB"

PIN="$(cd "$ROOT" && git ls-tree HEAD vendor/dontfeedtheai | awk '{print $3}')"
git fetch --quiet origin main
UPSTREAM="$(git rev-parse origin/main)"

echo "pinned:   $PIN"
echo "upstream: $UPSTREAM"

if [[ "$PIN" == "$UPSTREAM" ]]; then
  echo "status:   up to date"
else
  echo "status:   $(git rev-list --count "$PIN..$UPSTREAM") commits behind"
  echo
  echo "── new commits ─────────────────────────────────────────"
  git log --oneline "$PIN..$UPSTREAM"
  echo
  echo "── files changed ───────────────────────────────────────"
  git diff --stat "$PIN..$UPSTREAM"
  echo
  if git diff --quiet "$PIN..$UPSTREAM" -- src/regex_detector.py; then
    echo "regex_detector.py: unchanged"
  else
    echo "regex_detector.py: CHANGED — review before bumping pin"
    if git diff "$PIN..$UPSTREAM" -- src/regex_detector.py | grep -q "class RegexMatch"; then
      echo "  ⚠️  RegexMatch dataclass touched — adapter may need update"
    fi
  fi
  if ! git ls-tree "$PIN" -- LICENSE >/dev/null 2>&1 && git ls-tree "$UPSTREAM" -- LICENSE >/dev/null 2>&1; then
    echo "LICENSE: added upstream — close apf-9y2's license blocker"
  fi
fi

echo
if command -v gh >/dev/null 2>&1; then
  echo "── our PRs to zeroc00I/DontFeedTheAI ───────────────────"
  gh pr list --repo zeroc00I/DontFeedTheAI --author "@me" --state all 2>/dev/null || \
    echo "  (gh not authenticated or no PRs yet)"
  echo
  echo "── issue #3 (LICENSE request) ──────────────────────────"
  gh issue view 3 --repo zeroc00I/DontFeedTheAI --json state,title --jq '"\(.state): \(.title)"' 2>/dev/null || \
    echo "  (issue not found or gh unavailable)"
fi

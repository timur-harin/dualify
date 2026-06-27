#!/usr/bin/env bash
# Rewrite commit messages to remove Cursor agent attribution.
set -euo pipefail

MSG_FILTER='/usr/bin/sed "/^Co-authored-by: Cursor <cursoragent@cursor.com>$/d; /^Made-with: Cursor$/d"'

rewrite_repo() {
  local repo="$1"
  local branch="${2:-main}"
  echo "==> Rewriting $repo ($branch)"
  git -C "$repo" filter-branch -f --msg-filter "$MSG_FILTER" "$branch"
}

verify_repo() {
  local repo="$1"
  if git -C "$repo" log --format=%B | /usr/bin/grep -qiE 'co-authored-by: cursor|made-with: cursor'; then
    echo "error: Cursor attribution still present in $repo" >&2
    exit 1
  fi
  echo "    ok: $repo"
}

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

rewrite_repo "$ROOT/conferences/arxiv" main
rewrite_repo "$ROOT/conferences/icse-2027" main

ICSE_SHA="$(git -C "$ROOT/conferences/icse-2027" rev-parse main)"
ARXIV_SHA="$(git -C "$ROOT/conferences/arxiv" rev-parse main)"
git -C "$ROOT/conferences/icse-2027" checkout main
git -C "$ROOT/conferences/arxiv" checkout main

git -C "$ROOT" add -f conferences/icse-2027 conferences/arxiv
if ! git -C "$ROOT" diff --cached --quiet; then
  git -C "$ROOT" commit --amend --no-edit
fi

rewrite_repo "$ROOT" main

echo "==> Verifying no Cursor attribution remains"
verify_repo "$ROOT/conferences/arxiv"
verify_repo "$ROOT/conferences/icse-2027"
verify_repo "$ROOT"

echo "==> New submodule SHAs"
echo "    icse-2027: $ICSE_SHA"
echo "    arxiv:     $ARXIV_SHA"

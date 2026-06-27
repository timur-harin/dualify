#!/usr/bin/env bash
# Enable repo git hooks (strips Cursor co-author trailers from commits).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

install_hooks() {
  local repo="$1"
  local label="$2"
  mkdir -p "$repo/.githooks"
  cp "$ROOT/.githooks/prepare-commit-msg" "$repo/.githooks/prepare-commit-msg"
  chmod +x "$repo/.githooks/prepare-commit-msg"
  git -C "$repo" config core.hooksPath .githooks
  echo "==> Git hooks enabled for $label"
  echo "    core.hooksPath=.githooks"
}

install_hooks "$ROOT" "$(basename "$ROOT")"

for path in conferences/icse-2027 conferences/arxiv; do
  if [[ -d "$ROOT/$path/.git" || -f "$ROOT/$path/.git" ]]; then
    install_hooks "$ROOT/$path" "$path"
  fi
done

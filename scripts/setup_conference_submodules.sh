#!/usr/bin/env bash
# Wire conferences/icse-2027 and conferences/arxiv as private GitHub submodules.
#
# Prerequisites:
#   gh auth login
#   Run from the dualify repository root.
#
# Creates (if needed):
#   https://github.com/timur-harin/dualify-icse-2027  (private)
#   https://github.com/timur-harin/dualify-arxiv        (private)

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

GITHUB_USER="${GITHUB_USER:-timur-harin}"
ICSE_REPO="${ICSE_REPO:-dualify-icse-2027}"
ARXIV_REPO="${ARXIV_REPO:-dualify-arxiv}"
ICSE_URL="https://github.com/${GITHUB_USER}/${ICSE_REPO}.git"
ARXIV_URL="https://github.com/${GITHUB_USER}/${ARXIV_REPO}.git"
ICSE_PATH="conferences/icse-2027"
ARXIV_PATH="conferences/arxiv"

if ! command -v gh >/dev/null 2>&1; then
  echo "error: GitHub CLI (gh) is not installed." >&2
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "error: gh is not authenticated. Run: gh auth login" >&2
  exit 1
fi

init_local_repo() {
  local path="$1"
  local message="$2"
  if [[ ! -d "$path" ]]; then
    echo "error: missing $path" >&2
    exit 1
  fi
  if [[ ! -e "$path/.git" ]]; then
    git -C "$path" init -b main
  fi
  if ! git -C "$path" rev-parse HEAD >/dev/null 2>&1; then
    git -C "$path" add -A
    git -C "$path" commit -m "$message"
  fi
}

ensure_remote_repo() {
  local path="$1"
  local name="$2"
  local full="${GITHUB_USER}/${name}"
  local url="https://github.com/${full}.git"

  if gh repo view "$full" >/dev/null 2>&1; then
    echo "==> Remote exists: $full"
    git -C "$path" remote remove origin 2>/dev/null || true
    git -C "$path" remote add origin "$url"
    git -C "$path" push -u origin main
  else
    echo "==> Creating private repo $full from $path"
    gh repo create "$full" --private --source="$path" --remote=origin --push
  fi
}

register_submodule() {
  local url="$1"
  local path="$2"
  if [[ -f .gitmodules ]] && git config -f .gitmodules --get-regexp "submodule\\..*\\.path" | grep -q " ${path}$"; then
    echo "==> Submodule already registered: $path"
    return
  fi
  if [[ -e "$path/.git" ]]; then
    local backup
    backup="$(mktemp -d)"
    cp -a "$path/." "$backup/"
    rm -rf "$path"
    git submodule add --force "$url" "$path"
    if command -v rsync >/dev/null 2>&1; then
      rsync -a --exclude='.git' "$backup/" "$path/"
    else
      (cd "$backup" && find . -not -path './.git*' -print0 | cpio -p0dm "$ROOT/$path" 2>/dev/null) || {
        shopt -s dotglob
        for item in "$backup"/*; do
          base="$(basename "$item")"
          [[ "$base" == .git ]] && continue
          cp -a "$item" "$path/"
        done
        shopt -u dotglob
      }
    fi
    rm -rf "$backup"
    git -C "$path" add -A
    if ! git -C "$path" diff --cached --quiet; then
      git -C "$path" commit -m "Sync local conference source"
      git -C "$path" push origin main
    fi
    git add -f "$path" .gitmodules
  else
    git submodule add --force "$url" "$path"
  fi
}

echo "==> Initializing local conference repositories"
init_local_repo "$ICSE_PATH" "Initial ICSE 2027 Dualify paper source"
init_local_repo "$ARXIV_PATH" "Initial arXiv Dualify paper source"

echo "==> Creating/pushing private GitHub repositories"
ensure_remote_repo "$ICSE_PATH" "$ICSE_REPO"
ensure_remote_repo "$ARXIV_PATH" "$ARXIV_REPO"

echo "==> Removing any directly tracked conference files from dualify (keep submodules only)"
git rm -r --cached "$ICSE_PATH" 2>/dev/null || true
git rm -r --cached "$ARXIV_PATH" 2>/dev/null || true

echo "==> Registering submodules"
register_submodule "$ICSE_URL" "$ICSE_PATH"
register_submodule "$ARXIV_URL" "$ARXIV_PATH"

echo "==> Done."
echo "    Review: git status"
echo "    Commit in dualify:"
echo "      git add -f conferences/icse-2027 conferences/arxiv .gitmodules .gitignore scripts/setup_conference_submodules.sh"
echo "      git commit -m 'Track conference papers as private submodules'"
echo "    Clone elsewhere: git clone --recurse-submodules https://github.com/${GITHUB_USER}/dualify"

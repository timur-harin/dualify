#!/usr/bin/env bash
# Fetch latest upstream dataset sources (not vendored in git).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCES="${ROOT}/benchmark/dataset/sources"

CROSSHAIR_URL="https://github.com/pschanely/CrossHair.git"
CORPUS_URL="https://github.com/mristin/python-by-contract-corpus.git"

clone_or_update() {
  local name="$1"
  local url="$2"
  local dest="${SOURCES}/${name}"

  if [[ -d "${dest}/.git" ]]; then
    echo "Updating ${name}..."
    git -C "${dest}" fetch --depth 1 origin
    git -C "${dest}" checkout -f origin/HEAD
  else
    echo "Cloning ${name}..."
    rm -rf "${dest}"
    git clone --depth 1 "${url}" "${dest}"
  fi
}

mkdir -p "${SOURCES}"
clone_or_update "CrossHair" "${CROSSHAIR_URL}"
clone_or_update "python-by-contract-corpus" "${CORPUS_URL}"

echo "Dataset sources ready under ${SOURCES}"

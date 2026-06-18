#!/usr/bin/env bash
# Download the curated PyPI packages as sdists into packages/ and record the
# exact versions and licences into packages/MANIFEST.txt. Idempotent: re-running
# re-extracts into the same place.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
PKG_DIR="$ROOT/packages"
SRC_DIR="$PKG_DIR/src"
mkdir -p "$SRC_DIR"

MANIFEST="$PKG_DIR/MANIFEST.txt"
: > "$MANIFEST"

# Read package names (skip comments/blanks).
mapfile -t PKGS < <(grep -vE '^\s*(#|$)' "$HERE/packages.txt")

for pkg in "${PKGS[@]}"; do
  echo ">>> $pkg"
  # Fetch the sdist only (full source tree, deterministic layout).
  python3 -m pip download --no-deps --no-binary :all: --dest "$PKG_DIR/_dl" "$pkg" \
    >/dev/null 2>&1 || { echo "    download failed: $pkg" >&2; continue; }
done

# Extract every sdist into src/<pkg>/ and record version.
shopt -s nullglob
for archive in "$PKG_DIR"/_dl/*.tar.gz "$PKG_DIR"/_dl/*.zip; do
  base="$(basename "$archive")"
  name="${base%.tar.gz}"; name="${name%.zip}"
  dest="$SRC_DIR/$name"
  rm -rf "$dest"; mkdir -p "$dest"
  case "$archive" in
    *.tar.gz) tar -xzf "$archive" -C "$dest" --strip-components=1 ;;
    *.zip)    unzip -q "$archive" -d "$dest" ;;
  esac
  echo "$name" >> "$MANIFEST"
done

echo "Done. Extracted sources in $SRC_DIR"
cat "$MANIFEST"

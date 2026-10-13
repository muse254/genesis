#!/usr/bin/env bash
#
# Assemble the Python runtime the release build bundles as a resource: a
# relocatable CPython (python-build-standalone via uv), our dependencies, and
# our pure-Python source, so the app runs on a machine with no Python.
#
# Only the macOS branch has been run; Linux and Windows are untested.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESOURCES="$ROOT/desktop/src-tauri/resources"
RUNTIME="$RESOURCES/python-runtime"
APP_SRC="$RESOURCES/app-src"
PY_VERSION="3.12.9"

# uv's download key is cpython-<version>-<os>-<arch>-<libc>; it no longer
# accepts Rust target triples (`uv python list --only-downloads` shows keys).
case "$(uname -s)" in
  Darwin) TRIPLE="macos-aarch64-none" ;;
  Linux)  TRIPLE="linux-x86_64-gnu" ;;
  MINGW*|MSYS*|CYGWIN*) TRIPLE="windows-x86_64-none" ;;
  *) echo "unrecognised platform: $(uname -s)" >&2; exit 1 ;;
esac
PY_BUILD="cpython-$PY_VERSION-$TRIPLE"

# Windows lays out a standalone Python differently: `python.exe` and
# `Lib\site-packages` at the root, not `bin/python3.12` and
# `lib/python3.12/site-packages`.
if [[ "$TRIPLE" == *windows* ]]; then
  PYTHON_BIN="$RUNTIME/python.exe"
else
  PYTHON_BIN="$RUNTIME/bin/python3.12"
fi

echo "== fetching $PY_BUILD (python-build-standalone, via uv)"
uv python install "$PY_BUILD" >/dev/null
SOURCE="$(uv python dir)/$PY_BUILD"
[ -d "$SOURCE" ] || { echo "expected $SOURCE to exist after uv python install" >&2; exit 1; }

echo "== copying it to $RUNTIME (a private copy -- pip-installing into it must not touch uv's own)"
mkdir -p "$RESOURCES"
rm -rf "$RUNTIME"
cp -R "$SOURCE" "$RUNTIME"
# PEP 668's marker would refuse the pip install below. Absent on Windows.
find "$RUNTIME" -maxdepth 3 -name "EXTERNALLY-MANAGED" -delete

echo "== installing this project's dependencies into it"
uv pip install --python "$PYTHON_BIN" -r "$ROOT/requirements.txt"

echo "== checking it hashes images exactly as the verify page does"
# App and web page must agree on pixel hashes. The JPEG hash depends on
# Pillow's per-platform libjpeg-turbo, so check it against the browser fixtures.
(cd "$ROOT" && "$PYTHON_BIN" -m ingest.dump_hash_fixtures --check)

echo "== copying our own pure-Python source"
# git-tracked .py only, never validate_ modules: the packages hold local
# fixtures (RAW frames, references) that must never leave this machine
# (docs/security.md).
rm -rf "$APP_SRC"
mkdir -p "$APP_SRC"
for pkg in console fingerprint ingest scoring; do
  while IFS= read -r file; do
    mkdir -p "$APP_SRC/$(dirname "$file")"
    cp "$ROOT/$file" "$APP_SRC/$file"
  done < <(git -C "$ROOT" ls-files "$pkg" | grep '\.py$' | grep -v '/validate_')
done
cp "$ROOT/desktop/sidecar/embedded_runner.py" "$APP_SRC/embedded_runner.py"

du -sh "$RUNTIME" "$APP_SRC"
echo "== done. cargo tauri build now bundles $RESOURCES as a resource."

#!/usr/bin/env bash
#
# Assemble the Python runtime a release build bundles and embeds -- a
# relocatable CPython (python-build-standalone, via `uv python install`)
# plus this project's third-party dependencies installed into it, plus our
# own pure-Python source. `cargo tauri build` copies the whole thing into
# the app as a resource (tauri.conf.json's bundle.resources); the embedded
# interpreter (desktop/src-tauri/src/lib.rs) points PYTHONHOME and sys.path
# at it, so a machine with no Python at all can still run the app.
#
#   desktop/scripts/bundle-python.sh
#
# Proven on macOS (measured: 2s cold start, a real CR3 decoded through the
# bundled runtime, 17 Sept). The Linux and Windows branches below follow the
# same pattern -- python-build-standalone ships all three -- but neither has
# been run; say so rather than claim otherwise if you hit something here.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RESOURCES="$ROOT/desktop/src-tauri/resources"
RUNTIME="$RESOURCES/python-runtime"
APP_SRC="$RESOURCES/app-src"
PY_VERSION="3.12.9"

case "$(uname -s)" in
  Darwin) TRIPLE="aarch64-apple-darwin" ;;
  Linux)  TRIPLE="x86_64-unknown-linux-gnu" ;;
  MINGW*|MSYS*|CYGWIN*) TRIPLE="x86_64-pc-windows-msvc" ;;
  *) echo "unrecognised platform: $(uname -s)" >&2; exit 1 ;;
esac
PY_BUILD="cpython-$PY_VERSION-$TRIPLE-none"

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
# This copy is ours now, not the one uv manages; PEP 668's marker would
# otherwise refuse the pip install below. Not present on the Windows layout.
find "$RUNTIME" -maxdepth 3 -name "EXTERNALLY-MANAGED" -delete

echo "== installing this project's dependencies into it"
uv pip install --python "$PYTHON_BIN" -r "$ROOT/requirements.txt"

echo "== copying our own pure-Python source"
# git-tracked .py files only, and never a test/validate_ module -- the
# packages otherwise hold local fixtures (RAW frames, references) that must
# never leave this machine, this project's whole security posture rests on
# that (docs/security.md), and have no business in a shipped binary anyway.
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

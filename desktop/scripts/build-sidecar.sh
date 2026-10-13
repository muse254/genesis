#!/usr/bin/env bash
#
# Superseded by bundle-python.sh (the imaging core is embedded via PyO3 now);
# kept unreferenced, see desktop/PACKAGING.md.
#
# Freezes the console backend into binaries/genesis-console-<host triple>,
# the name Tauri looks for. Run on each platform you build for.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TRIPLE="$(rustc -vV | awk '/^host:/ {print $2}')"
EXT=""
case "$TRIPLE" in *windows*) EXT=".exe" ;; esac
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

cd "$ROOT"
python -m PyInstaller --noconfirm --onefile \
  --name "genesis-console-$TRIPLE" \
  --distpath desktop/src-tauri/binaries \
  --workpath "$WORK/work" --specpath "$WORK" \
  --paths "$ROOT" \
  --collect-submodules uvicorn \
  --collect-submodules console \
  --collect-submodules fingerprint \
  --collect-submodules ingest \
  --collect-submodules scoring \
  --collect-submodules eth_hash \
  --collect-all rawpy \
  --collect-all pywt \
  desktop/sidecar/genesis_console.py

ls -lh "desktop/src-tauri/binaries/genesis-console-$TRIPLE$EXT"

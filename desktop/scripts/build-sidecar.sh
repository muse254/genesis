#!/usr/bin/env bash
#
# SUPERSEDED (18 Sept) by desktop/scripts/bundle-python.sh: the imaging core
# is embedded in the Rust process now (PyO3), not a sidecar this script
# freezes. Kept, unreferenced, for the reason desktop/sidecar/genesis_console.py
# gives -- see desktop/PACKAGING.md.
#
# Freeze the console backend into the sidecar the Tauri app bundles.
#
#   desktop/scripts/build-sidecar.sh
#
# Tauri looks for `binaries/genesis-console-<target triple>`, so the name
# carries the host triple. Run it on each platform you build for; CI does
# this per runner (.github/workflows/desktop.yml).
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

#!/usr/bin/env bash
#
# Point the release binary at the libpython bundled inside the app.
#
# PyO3 links against the build machine's libpython by its absolute path
# (on CI, /Users/runner/.local/share/uv/...), so a shipped app aborts in
# dyld on every Mac but the one that built it. Runs as Tauri's
# beforeBundleCommand: after the binary is linked, before it is bundled.
set -euo pipefail

[ "$(uname -s)" = Darwin ] || exit 0

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BUNDLED="@executable_path/../Resources/python-runtime/lib/libpython3.12.dylib"

shopt -s nullglob
found=0
for bin in "$ROOT"/target/release/genesis "$ROOT"/target/*/release/genesis; do
  found=1
  old="$(otool -L "$bin" | awk '/libpython3\.12\.dylib/ {print $1}')"
  [ -n "$old" ] || { echo "$bin does not link libpython3.12" >&2; exit 1; }
  [ "$old" = "$BUNDLED" ] && continue
  install_name_tool -change "$old" "$BUNDLED" "$bin" 2>/dev/null
  codesign --force --sign - "$bin"  # the edit voids the linker's ad-hoc signature
  otool -L "$bin" | grep -qF "$BUNDLED" || { echo "failed to repoint $bin" >&2; exit 1; }
  echo "== $bin now loads $BUNDLED"
done
[ "$found" = 1 ] || { echo "no release binary under $ROOT/target" >&2; exit 1; }

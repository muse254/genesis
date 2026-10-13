#!/usr/bin/env bash
# Build libjpeg-turbo + decode.c to WASM. Needs emcc (see core/README.md).
# LIBJPEG_TURBO_VERSION must equal Pillow's bundled libjpeg-turbo
# (`features.version('libjpeg_turbo')`): the pixel hash is exact.
# core/test/hashes.test.ts fails if they drift. SIMD off (unavailable in WASM)
# decodes to the same bytes on this version.
set -euo pipefail

LIBJPEG_TURBO_VERSION=3.1.4.1
LIBJPEG_TURBO_SHA256=ecae8008e2cc9ade2f2c1bb9d5e6d4fb73e7c433866a056bd82980741571a022

here="$(cd "$(dirname "$0")" && pwd)"
work="$here/.build"
src="$work/libjpeg-turbo-$LIBJPEG_TURBO_VERSION"
out="$here/../src/jpeg"

command -v emcc >/dev/null || { echo "emcc not found: install Emscripten (core/README.md)" >&2; exit 1; }
mkdir -p "$work" "$out"

if [ ! -d "$src" ]; then
  tarball="$work/libjpeg-turbo-$LIBJPEG_TURBO_VERSION.tar.gz"
  curl -sSfL -o "$tarball" \
    "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/$LIBJPEG_TURBO_VERSION/libjpeg-turbo-$LIBJPEG_TURBO_VERSION.tar.gz"
  # sha256sum on Linux and Git Bash (Windows), shasum on macOS; exactly one decides.
  if command -v sha256sum >/dev/null; then sumcheck="sha256sum -c -"; else sumcheck="shasum -a 256 -c -"; fi
  echo "$LIBJPEG_TURBO_SHA256  $tarball" | $sumcheck >/dev/null
  tar xzf "$tarball" -C "$work"
fi

if [ ! -f "$work/lib/libjpeg.a" ]; then
  emcmake cmake -S "$src" -B "$work/lib" -DCMAKE_BUILD_TYPE=Release \
    -DWITH_SIMD=0 -DENABLE_SHARED=0 -DWITH_TURBOJPEG=0 -DWITH_TOOLS=0 -DWITH_TESTS=0 >/dev/null
  cmake --build "$work/lib" --target jpeg-static -j >/dev/null
fi

emcc -O3 "$here/decode.c" "$work/lib/libjpeg.a" -I"$src/src" -I"$work/lib" \
  -o "$out/libjpeg.mjs" \
  -sMODULARIZE -sEXPORT_ES6 -sENVIRONMENT=web,worker,node \
  -sALLOW_MEMORY_GROWTH -sMAXIMUM_MEMORY=4GB \
  -sEXPORTED_FUNCTIONS=_decode,_release,_result_pixels,_result_w,_result_h,_error_message,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=HEAPU8,UTF8ToString

cp "$here/libjpeg.d.mts" "$out/libjpeg.d.mts"
printf '*\n' > "$out/.gitignore"
echo "built $out/libjpeg.mjs (libjpeg-turbo $LIBJPEG_TURBO_VERSION)"

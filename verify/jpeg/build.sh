#!/usr/bin/env bash
# Build libjpeg-turbo + decode.c to WASM for the verify page. Needs emcc
# (Emscripten) on PATH; see verify/README.md.
#
# LIBJPEG_TURBO_VERSION must equal the libjpeg-turbo bundled in the Pillow
# the Python side runs -- `python -c "from PIL import features;
# print(features.version('libjpeg_turbo'))"`, also recorded in
# rust/genesis-prnu/tests/fixtures/hashing/manifest.json. Different
# versions can decode to different pixels, and the pixel hash is exact.
# ingest/validate_hash_fixtures.py and verify/test/hashes.test.ts fail
# loudly if they drift apart.
#
# SIMD is off because WASM can't use libjpeg-turbo's hand-written SIMD.
# That changes nothing in the output: on this version the C paths decode
# to the same bytes as the SIMD ones (checked on real photos both ways).
set -euo pipefail

LIBJPEG_TURBO_VERSION=3.1.4.1
LIBJPEG_TURBO_SHA256=ecae8008e2cc9ade2f2c1bb9d5e6d4fb73e7c433866a056bd82980741571a022

here="$(cd "$(dirname "$0")" && pwd)"
work="$here/.build"
src="$work/libjpeg-turbo-$LIBJPEG_TURBO_VERSION"
out="$here/../src/jpeg"

command -v emcc >/dev/null || { echo "emcc not found: install Emscripten (verify/README.md)" >&2; exit 1; }
mkdir -p "$work" "$out"

if [ ! -d "$src" ]; then
  tarball="$work/libjpeg-turbo-$LIBJPEG_TURBO_VERSION.tar.gz"
  curl -sSfL -o "$tarball" \
    "https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/$LIBJPEG_TURBO_VERSION/libjpeg-turbo-$LIBJPEG_TURBO_VERSION.tar.gz"
  echo "$LIBJPEG_TURBO_SHA256  $tarball" | shasum -a 256 -c - >/dev/null
  tar xzf "$tarball" -C "$work"
fi

if [ ! -f "$work/lib/libjpeg.a" ]; then
  emcmake cmake -S "$src" -B "$work/lib" -DCMAKE_BUILD_TYPE=Release \
    -DWITH_SIMD=0 -DENABLE_SHARED=0 -DWITH_TURBOJPEG=0 -DWITH_TOOLS=0 -DWITH_TESTS=0 >/dev/null
  cmake --build "$work/lib" --target jpeg-static -j >/dev/null
fi

emcc -O3 "$here/decode.c" "$work/lib/libjpeg.a" -I"$src/src" -I"$work/lib" \
  -o "$out/libjpeg.mjs" \
  -sMODULARIZE -sEXPORT_ES6 -sENVIRONMENT=web,node \
  -sALLOW_MEMORY_GROWTH -sMAXIMUM_MEMORY=4GB \
  -sEXPORTED_FUNCTIONS=_decode,_release,_result_pixels,_result_w,_result_h,_error_message,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=HEAPU8,UTF8ToString

cp "$here/libjpeg.d.mts" "$out/libjpeg.d.mts"
printf '*\n' > "$out/.gitignore"
echo "built $out/libjpeg.mjs (libjpeg-turbo $LIBJPEG_TURBO_VERSION)"

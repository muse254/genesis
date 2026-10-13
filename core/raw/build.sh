#!/usr/bin/env bash
# Build LibRaw + decode.cpp to WASM. Needs emcc (see core/README.md).
# LIBRAW_VERSION must equal rawpy's bundled LibRaw (`rawpy.libraw_version`);
# parity.mjs checks against rawpy on real frames.
# LibRaw is dual-licensed LGPL 2.1 / CDDL 1.0; fetched from libraw.org at the pinned version.
set -euo pipefail

LIBRAW_VERSION=0.22.1
LIBRAW_SHA256=a789dc4e2409e2901d93793a4e0b80c7b49d0d97cf6ad71c850eb7616acfd786

here="$(cd "$(dirname "$0")" && pwd)"
work="$here/.build"
src="$work/LibRaw-$LIBRAW_VERSION"
out="$here/../src/raw"

command -v emcc >/dev/null || { echo "emcc not found: install Emscripten (core/README.md)" >&2; exit 1; }
mkdir -p "$work" "$out"

if [ ! -d "$src" ]; then
  tarball="$work/LibRaw-$LIBRAW_VERSION.tar.gz"
  curl -sSfL -o "$tarball" "https://www.libraw.org/data/LibRaw-$LIBRAW_VERSION.tar.gz"
  # sha256sum on Linux and Git Bash (Windows), shasum on macOS; exactly one decides.
  if command -v sha256sum >/dev/null; then sumcheck="sha256sum -c -"; else sumcheck="shasum -a 256 -c -"; fi
  echo "$LIBRAW_SHA256  $tarball" | $sumcheck >/dev/null
  tar xzf "$tarball" -C "$work"
fi

# WASM exceptions: LibRaw throws internally on corrupt input; without them a
# bad file aborts the module. 8 MB stack (see below): the 64 KB default
# overflows in LibRaw's identify and CR3 decoder.
flags=(-O3 -w -fwasm-exceptions -DLIBRAW_NOTHREADS -DNO_LCMS -DNO_JASPER -DLIBRAW_NODLL -I"$src")

lib="$work/libraw.a"
if [ ! -f "$lib" ]; then
  # The objects LibRaw's own Makefile.dist builds into the library.
  objects=$(sed -n '/^LIB_OBJECTS=/,/^$/p' "$src/Makefile.dist" | grep -o 'object/[a-z0-9_]*\.o' | sed 's|object/||; s|\.o$||')
  mkdir -p "$work/obj"
  for name in $objects; do
    file=$(find "$src/src" -name "$name.cpp" | head -1)
    [ -n "$file" ] || { echo "no source for $name" >&2; exit 1; }
    em++ "${flags[@]}" -c "$file" -o "$work/obj/$name.o" &
    while [ "$(jobs -r | wc -l)" -ge 8 ]; do sleep 0.1; done
  done
  wait
  emar rcs "$lib" "$work"/obj/*.o
fi

em++ "${flags[@]}" "$here/decode.cpp" "$lib" -I"$here" -I"$src/libraw" \
  -o "$out/libraw.mjs" \
  -sMODULARIZE -sEXPORT_ES6 -sENVIRONMENT=web,worker,node \
  -sALLOW_MEMORY_GROWTH -sMAXIMUM_MEMORY=4GB \
  -sSTACK_SIZE=8MB \
  -sEXPORTED_FUNCTIONS=_raw_open,_raw_close,_raw_error,_raw_visible,_raw_width,_raw_height,_raw_pattern_size,_raw_pattern_at,_raw_color_visible,_raw_black,_raw_white,_raw_make,_raw_model,_raw_body_serial,_raw_libraw_version,_malloc,_free \
  -sEXPORTED_RUNTIME_METHODS=HEAPU8,HEAPU16,UTF8ToString

cp "$here/libraw.d.mts" "$out/libraw.d.mts"
printf '*\n' > "$out/.gitignore"
echo "built $out/libraw.mjs (LibRaw $LIBRAW_VERSION)"

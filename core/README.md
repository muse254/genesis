# Genesis — core

Verification, once, for both the web page (`verify/`) and the desktop app
(`console-ui/`). See `docs/shared-verify-plan.md` for why there is one.

```ts
import { verify, workerEngine, createChainReader } from "@genesis/core";

const result = await verify(file, {
  engine: workerEngine(),              // decode, hash, PRNU: in a Web Worker
  chain: createChainReader({ rpcUrl, chain: "base-sepolia", registry }),
  subgraphUrl,                         // the perceptual index
  bodies,                              // enrolled K files (desktop only)
  rawDecoder,                          // LibRaw via the desktop's Python (desktop only)
  onStep: (label, fraction) => {},
});
```

The web page passes no `bodies`, so no PRNU runs and only the hashes leave
the browser. The desktop passes the K files it enrolled, which never leave
that machine (`docs/security.md`, "Where K lives").

## Pieces

| file | does | port of |
|---|---|---|
| `src/verify.ts` | the verdict, stages, diagnosis | `console/app.py` `_verify`, `_diagnose`; `consistency.stages` |
| `src/analyse.ts` | decode, hash, score each body, signals (runs in the worker) | `scoring/app.py` `_score_against`; `console/app.py` `_signals` |
| `src/chain.ts` | registry reads, The Graph | `console/chain.py`, `console/subgraph.py` |
| `src/hashes.ts` | decoding to Pillow's exact pixels; the two hashes | `ingest/hashing.py` |
| `src/exif.ts` | Make/Software, for the diagnosis | Pillow `getexif()` |
| `src/engine.ts`, `src/worker.ts` | where the pixel work runs | — |

The numerics are Rust (`rust/genesis-prnu`), compiled to WASM.

## Two WASM modules

`npm run wasm` builds both. Neither output is committed.

- **`src/wasm/`**: `rust/genesis-prnu-wasm`, built with `wasm-pack`.
- **`src/jpeg/`**: libjpeg-turbo, built with Emscripten by `jpeg/build.sh`.
  You need `emcc` on your PATH
  (https://emscripten.org/docs/getting_started/downloads.html).

- **`src/raw/`** (built on its own, `npm run wasm:raw`): LibRaw 0.22.1 for
  enrolling a camera in the browser, the first piece of that work. Not
  imported by anything yet, so not part of `npm run wasm`. See below.

### Why JPEG gets its own decoder

The pixel hash is an exact SHA-256 over decoded pixels, so the browser has
to decode a JPEG to the very bytes Python does. Python decodes with the
libjpeg-turbo bundled in Pillow. The Rust `image` crate does not produce the
same bytes: on a real camera JPEG, 15% of bytes differed. Every JPEG would
then come back "no record". PRNU scoring reads the same decoded pixels, so
the hash and the score always see one image.

`jpeg/build.sh` pins libjpeg-turbo to the version in the Pillow that
`requirements.txt` pins (12.3.0, libjpeg-turbo 3.1.4.1). **To upgrade
Pillow:** check `features.version("libjpeg_turbo")`, and if it changed,
bump `build.sh`, regenerate the fixtures, and rerun the tests.

### RAW in the browser: LibRaw

`raw/build.sh` compiles LibRaw at the version `rawpy` bundles (0.22.1,
`requirements.txt` pins `rawpy`), and `raw/decode.cpp` returns exactly what
enrolment reads through `rawpy`: the visible mosaic, `raw_pattern`,
`raw_colors_visible`, `black_level_per_channel` (by `rawpy`'s own helper,
vendored as `raw/data_helper.h`) and `white_level`, plus the body serial for
refusing frames from two cameras.

`node raw/parity.mjs <raw files>` compares every one of those against
`rawpy` (and the serial against `exiftool`) on real files, exactly. On 29
September: all 41 enrolment frames of the R10, a second R10 body, and a
lossy DNG (refused, as `load_raw_planes` refuses it) -- 43 of 43. A CR3
decodes in ~300 ms in Chrome.

Built without lossy-DNG JPEG, zlib (deflate DNG) or threads: enrolment reads
Bayer mosaics, and a CR3 needs none of them. LibRaw is LGPL 2.1 / CDDL 1.0,
fetched from libraw.org at the pinned version and rebuilt by the script.

## Tests

```
npm test                                         # everything below, through the real WASM
npm run parity -- ~/photos/a.jpg ~/photos/b.png  # real photos' hashes against live Python
```

- `test/hashes.test.ts`: every hash fixture, JPEG included (the only place
  JPEG parity runs), and the refusals (RAW, CMYK, 16-bit, truncated).
- `test/analyse.test.ts`: scoring against a synthetic K on every path
  (aligned, portrait, resized, mirrored, bordered, RAW), the signals, the
  progress weighting, and `stages`/`diagnose` against Python's output.
- `test/verdict.test.ts`: the verdict rules, with the chain and The Graph
  faked, including that only a chain read grants `registered` and that a
  failed chain read withholds the verdict.

Fixtures come from `python -m ingest.dump_hash_fixtures` and
`python -m fingerprint.dump_search_fixtures`; the Rust port is checked
against the same files by `cargo test -p genesis-prnu`.

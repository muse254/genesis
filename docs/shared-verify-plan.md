# One verify implementation for the web page and the desktop app

Decided 29 September 2026. The verify page (`verify/`) and the desktop app
(`console-ui/` on top of `console/app.py`) each had their own verification:
TypeScript + WASM on the page, Python in the app. Two implementations of the
same verdict can disagree about the same photograph, and the fix both times
this project hit that (registration vs verification, `/verify` vs
`/verify/stream`) was to collapse onto one function. This collapses the two
frontends onto one as well.

## The shape

```
             verify/ (Pages)           console-ui/ (desktop webview, demo browser)
                    \                   /
                     core/  (TypeScript, one package)
                     - hashes: libjpeg-turbo WASM + genesis-prnu WASM
                     - PRNU: score_against, the scale search, signals (genesis-prnu WASM)
                     - chain + subgraph reads (viem), the verdict, stages, diagnosis
                     - runs the WASM in a Web Worker, reports progress
                     |
      inputs it cannot get itself, from console/app.py over loopback:
      - the enrolled K files        (GET /bodies, GET /bodies/{id}/fingerprint)
      - a RAW file, decoded          (POST /raw/decode: developed RGB8 + CFA planes)
```

The web page passes no K files, so no PRNU candidates, which is today's
public behaviour. The desktop passes the K files it has enrolled. Both get
the same verdict code.

**What stays Python, and why.** RAW decoding (`rawpy`, which wraps LibRaw and
has no WASM build) and enrolment (which needs RAW). Python becomes a local
adapter for those two jobs and a file server for K. It no longer computes a
verdict. The Python scoring code stays as the *reference* the Rust is
parity-tested against (`fingerprint/`, the `validate_*` suites, the gate and
attack measurements). It is not in the verify runtime path any more.

**Why WASM in the desktop and not native Rust.** It's the same code as the
page, and measured on 29 September it is no slower. Aligned scoring of a
24 MP JPEG against the R10's K took Python 3.5 s, native Rust 6.9 s and WASM
7.7 s. The Rust port is single-threaded and slower than numpy either way;
making it faster is separate work, and it would speed up both frontends.

## Hard invariants

- **K never leaves the machine it was enrolled on** (`docs/security.md`,
  "Where K lives"). The desktop webview is on that machine, and loopback is
  not the network. `/bodies/{id}/fingerprint` binds to 127.0.0.1 like the
  rest of the console and is restricted to the console's allowed origins.
  The page on GitHub Pages never receives a K.
- **Only a chain read grants `registered`.** Signals are advisory
  (`fingerprint/consistency.py`, `stages`). The port keeps the three-stage
  report and its one-directional rule.
- **A chain read failure withholds the verdict**, never downgrades it
  (`console/app.py` `_verify`'s docstring). The shared core must throw, not
  fall back to `fingerprint-only`.
- **Parity with Python is the acceptance bar** for every numeric port,
  measured against dumped fixtures, as in `docs/wasm-scoring-plan.md`.

## Phases

Each phase ends green, with its parity checks, and lands as its own commit.

**Status, 29 September:** A–E done, on branch `shared-verify-core`. On the
R10's K and real photos, the Rust port matches Python on every decision and
to four decimals of PCE (as shot, web JPEG, portrait, framed, and a CR3
through the RAW path), and the desktop app verifies end to end on `core/`.
F is open, and so is **E2** below, which this work surfaced.

### A. Rust: everything `_score_against` does, from pixels

In `rust/genesis-prnu`, working from RGB8 (decoded by libjpeg-turbo for
JPEG, so the planes match Pillow's exactly) rather than from file bytes:

- `load_delivered_planes` from an RGB buffer.
- `sensor_field`, `green_channel`, `strip_uniform_border` (Pillow `L`
  greyscale, population std per line).
- `area_resize`: Pillow's BOX filter on float32 (`F` mode), double
  accumulation, float32 between passes (`Resample.c` `_32bpc`).
- `crop_and_scale_search`: eight orientations at nominal scale, then 13
  scales around it, with a progress callback.
- `score_against`: aligned, then the portrait retry (Pillow `rotate(270|90,
  expand=True)` is an exact transpose), then border strip and search.
  Accepts CFA planes from a RAW decode in place of RGB for the aligned path.
- Signals: `effective_strength`, `resampling_peak`, `high_frequency_content`
  (scipy `laplace`, `reflect` boundary).

Parity fixtures come from a new dump script against the real Python. The
end-to-end check is `score_against` on real photos against the real K,
compared with `scoring.app._score_against`.

### B. WASM bindings

`scoreAgainst(rgb, w, h, k, progress)`, `rawScoreAgainst(planes, rgb, k)`,
`signals(...)`, plus the existing `imageHashes`/`decodeRgb`. Each returns a
plain JS object.

### C. `core/`: one TS package

Moves `verify/src/hashes.ts` in, and adds the worker, chain/subgraph reads,
and `verify(file, { bodies, chain, subgraph, onStep })` returning the
console's richer `VerifyResult` (stages, consistency, diagnosis, body,
registration). The EXIF read for the diagnosis moves here. Both apps import
it through a Vite alias, since there's no npm workspace.

### D. Web page onto `core/`

`verify/src/main.ts` keeps only rendering. `VITE_SCORING_URL` goes:
`core/` does the PRNU itself wherever it has K, and the page has none.

### E. Desktop onto `core/`

- `console/app.py`: add `GET /bodies`, `GET /bodies/{id}/fingerprint`,
  `POST /raw/decode`, and add the RPC and subgraph URLs to `/state`. Delete
  `/verify`, `/verify/stream`, `_verify`, `_signals` and `_diagnose`.
- `console-ui`: the verify screen calls `core.verify` with the enrolled
  bodies; RAW goes through `/raw/decode` first.
- `console/validate_console.py`: the verify cases move to `core/`'s tests.

### E2. Registration onto `core/` too

Verification is on `core/`; **registration still scores and hashes in
Python** (`console/registry.py`, `_score_against`, `ingest/hashing.py`). So
the app now runs two implementations of the same scorer: the Rust port when
verifying, the Python original when registering. They are parity-tested
(`search_parity.rs`, and exact on real photos), but that is a guarantee
kept by tests rather than by there being one function -- which is the thing
`console/validate_console.py` says cost a 500 on every portrait photo the
last time the two paths diverged.

Closing it: the webview computes the hashes and PCE with `core/` (the
`analyse` step verification already runs) and sends them with the file;
`/register-image` checks the file's pixel hash matches before signing, and
still reads the metadata HMAC and body commitment in Python. Its own
decision because it moves a value that goes on chain.

### F. Retire the duplicates

`scoring/app.py`'s `/lookup` and `/score` exist to serve the two paths this
replaces. Whether the service survives at all is a separate call; its public
mode returns nothing the page can't now compute.

## Out of scope

Enrolment and RAW decoding in Rust (a pure-Rust RAW decoder such as `rawler`
is the future path), and multi-threaded scoring.

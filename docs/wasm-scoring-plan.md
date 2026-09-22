# Rust scoring core, compiled to WASM: plan and handoff

Decided 23 September 2026, after proving feasibility in-session (see chat
log / commit history around this date): `fingerprint/prnu.py`'s scoring
path — everything except enrolment — runs with no dependency that WASM
can't satisfy. Verified concretely, not guessed: the real, unmodified
`fingerprint/prnu.py` was loaded into Pyodide (real WASM CPython) via
Node and `noise_residual`/`score`/`pce` were called directly and returned
correct numbers.

This document reframes that finding: **write the scoring core in Rust**
instead of shipping Python-in-WASM (Pyodide). Rationale below, then a
phased task breakdown, then a ready-to-paste prompt for the session that
starts the work.

## Why Rust instead of Pyodide

Pyodide proved the algorithm has no RAW-decode dependency for scoring, but
using it in production means shipping ~65MB of gzipped numpy/scipy/
pywavelets/pillow wheels to every visitor's browser, one time, just to run
a few hundred lines of numeric code. A Rust port compiled with `wasm-pack`
would be single-digit megabytes, loads fast, and — this is the actual
"huge win" — it is the **same binary** that could replace the PyO3-embedded
Python interpreter in the desktop app's scoring path
(`desktop/src-tauri/src/lib.rs`, `desktop/PACKAGING.md`). That embedding
currently bundles a full relocatable CPython + numpy/scipy/pywavelets
(measured 217MB unpacked) just to run `console.app`'s `/score` endpoint
and friends. If the scoring core is Rust:

- the browser gets a small, fast WASM module instead of a Pyodide runtime
- the desktop app can call the same Rust code natively (no interpreter,
  no bundled runtime, no `PYTHONHOME`/`os.environ` embedding quirks
  documented in `desktop/PACKAGING.md`)
- one implementation instead of two to keep numerically in sync

**What does not move to Rust in this phase: enrolment.**
`estimate_fingerprint` and RAW decoding (`load_raw_planes`, `cfa_pattern`)
depend on `rawpy` (LibRaw bindings) to read CR3/RAW files, and there is no
realistic WASM build of LibRaw. Enrolment stays Python/desktop-only for
now. A future phase could investigate pure-Rust RAW decoders (`rawler`,
`rawloader`) to close that gap too, but that is explicitly out of scope
here — do not let it creep in.

## Hard invariants — read before writing any code

- **K never leaves the machine it was enrolled on**, browser or desktop
  (`docs/security.md`, "Where K lives"). The WASM module scores against a
  K the user already has locally (file upload, IndexedDB) — it must never
  transmit K anywhere, and the plan must not introduce a code path that
  could.
- **`commitment()`'s byte format is already load-bearing on chain**
  (`fingerprint/prnu.py`, `commitment()`, `COMMITMENT_VERSION =
  b"genesis-prnu-k-v1"`). Bodies are already registered on Base Sepolia
  against commitments Python computed. This phase does not touch
  commitment computation or enrolment at all, so this should be a
  non-issue — but if any subtask starts to imply recomputing or
  re-deriving K, stop and check `docs/colosseum-checklist.md` first.
- **Numeric parity with the Python reference is the acceptance bar**, not
  "looks right." `docs/gates.md` and `docs/adversarial.md` have real
  measured thresholds (`PCE_THRESHOLD = 100.0`, the R10 numbers in
  `docs/adversarial.md`) that a subtly-wrong port could silently pass or
  fail differently against. Every phase below ends in a parity check
  against Python, not just "it compiles and returns a number."

## The algorithm, precisely (what has to be reproduced)

All in `fingerprint/prnu.py`. Constants: `WAVELET = "db8"`,
`WAVELET_LEVELS = 4`, `WIENER_WINDOWS = (3, 5, 7, 9)`, `SIGMA = 2.0/255.0`,
`SATURATION_LEVEL = 0.99`, `PCE_THRESHOLD = 100.0`.

1. **`noise_residual`** (Mihcak wavelet Wiener denoiser, [F09] Appendix A):
   `db8` 2-D wavelet decomposition (`pywt.wavedec2`, `mode="symmetric"`,
   up to 4 levels, clamped by `pywt.dwt_max_level` for small images), per
   detail-band local-variance estimate as the *minimum* over four window
   sizes of a uniform (box) filter on the squared coefficients minus
   sigma², floored at zero (`_variance_estimate`), Wiener shrinkage
   `c * sigma² / (var + sigma²)` on every detail coefficient, approximation
   band zeroed, reconstruct (`pywt.waverec2`). Read PyWavelets' actual
   `"symmetric"` boundary-extension source before implementing this by
   hand in Rust — get the exact half-sample vs whole-sample convention
   wrong and every downstream number is subtly off in a way that won't
   throw, just silently drift.
2. **`cross_correlation`**: zero-mean both fields (float64), FFT-based
   circular cross-correlation: `ifft2(fft2(a) * conj(fft2(b))).real`.
3. **`_pce_of`**: peak of `|cc|`, exclude an `(2*half+1)²` neighbourhood
   around it (circular wraparound included, `squared_size=11`), energy is
   the mean of the squared remainder, PCE is `sign(peak) * peak² / energy`.
4. **`score`**: per shared CFA plane, `noise_residual` on the candidate
   plane, `expected = plane * k`, optionally zero both wherever
   `plane >= SATURATION_LEVEL`, cross-correlate, RMS-normalise each
   plane's correlation surface before summing across planes (so no plane
   dominates on scale alone), final PCE of the sum.
5. **`load_delivered_planes`**: decode an ordinary image (JPEG/PNG/TIFF —
   not RAW), convert to RGB float32 in [0,1], sample each 2×2 CFA phase
   from its corresponding RGB channel using the stored `cfa_pattern`
   (`{0: red, 1/3: green, 2: blue}` by default) — this is why scoring
   needs no RAW decode: the CFA pattern was already determined once, at
   enrolment, and is saved in the fingerprint file's metadata.
6. **K file format**: `save_fingerprint`/`load_fingerprint` write/read a
   `.npz` (numpy zip) with one `plane_<c>` float32 array per CFA colour, a
   JSON `meta` field (including `cfa_pattern`), and a raw commitment byte
   array. The Rust side needs to *read* this format (not write it —
   enrolment stays Python). `ndarray-npy` reads `.npy`; check whether it
   also handles the `.npz` zip container or whether a small zip-unwrap
   step is needed first.

## Proposed repo layout

Promote to a Cargo workspace so the core crate can be shared:

```
Cargo.toml                      # new: [workspace] members = ["rust/genesis-prnu", "rust/genesis-prnu-wasm", "desktop/src-tauri"]
rust/
  genesis-prnu/                 # pure algorithm crate: no I/O beyond reading bytes handed to it
    src/lib.rs                  #   noise_residual, cross_correlation, pce, score
    src/wavelet.rs              #   db8 2-D DWT/IDWT, symmetric boundary
    src/kfile.rs                #   read the .npz K format
    tests/parity.rs             #   compares against fixtures/ (see Phase 0)
    tests/fixtures/             #   golden input/output pairs dumped from Python
  genesis-prnu-wasm/             # wasm-bindgen wrapper: score(image_bytes, k_bytes) -> JsValue
    src/lib.rs
desktop/src-tauri/              # existing Tauri crate; becomes a workspace member (Phase 5)
```

Do not restructure `desktop/src-tauri` until Phase 5 — keep it building
and green throughout.

## Subtasks

Each phase should be its own PR-sized unit of work with its own parity
check before moving on. Do not start Phase *n+1* numerics until Phase *n*
parity passes — a wrong wavelet transform makes every later number
meaningless to debug.

### Phase 0 — Golden fixtures and parity harness

- Write a small Python script (`fingerprint/dump_parity_fixtures.py` or
  similar, throwaway/dev-only, does not need to ship) that runs
  `noise_residual`, `cross_correlation`, `pce`, and `score` on a handful of
  fixed inputs (a deterministic synthetic plane like
  `fingerprint/validate_synthetic.py` already builds, plus at least one
  real image from `fingerprint/verify-test-files/` if one is small enough
  to commit, or a synthetic stand-in if not — check `.gitignore` and the
  `raw-corpus-location` memory before adding any real photo to git) and
  dumps inputs + outputs as fixtures (`.npy` or JSON) under
  `rust/genesis-prnu/tests/fixtures/`.
- Acceptance: fixtures committed, a short README in that directory
  explaining what each one is and how it was generated (so it can be
  regenerated if the Python reference ever legitimately changes).

### Phase 1 — Wavelet transform (the highest-risk piece)

- Implement `db8`, 4-level, symmetric-boundary 2-D DWT and inverse in
  `rust/genesis-prnu/src/wavelet.rs`. Use exact Daubechies-8 filter
  coefficients (cite the source — PyWavelets' own source is the ground
  truth for the exact convention in use, not a generic Daubechies-8
  reference, since normalization/sign conventions vary between sources).
- Parity check: decompose-then-reconstruct a fixture plane with all
  coefficients kept unmodified and confirm it round-trips to the original
  (sanity check independent of Python), then confirm the coefficients
  themselves match `pywt.wavedec2`'s output on the same fixture within a
  tight tolerance (relative error, not exact float equality — but tight:
  this is the piece everything else depends on).

### Phase 2 — Wiener shrinkage and `noise_residual`

- Port `_variance_estimate` (box filter via `uniform_filter`, `mode="constant"`
  — check what `scipy.ndimage.uniform_filter`'s `"constant"` boundary mode
  actually does at the edges before assuming a naive box filter matches)
  and the shrinkage step.
- Parity check: `noise_residual` output on Phase 0's fixtures matches
  Python within tolerance.

### Phase 3 — Correlation, PCE, and `score`

- Port `cross_correlation` (use `rustfft`), `_pce_of`, and `score`
  (including saturation masking and per-plane RMS normalisation).
- Parity check: PCE values on fixtures match Python closely enough that
  they land on the same side of `PCE_THRESHOLD` and don't shift
  `docs/gates.md`'s pass/fail calls.

### Phase 4 — Image decode and K-file reading

- `load_delivered_planes` equivalent using the `image` crate (JPEG/PNG/
  TIFF decode, no RAW).
- `.npz` K-file reader (`ndarray-npy` or a small manual zip+npy reader) —
  read-only, matching `save_fingerprint`'s layout in `fingerprint/prnu.py`.
- Parity check: full `score()` end-to-end on a real delivered image against
  a real (or fixture) K, matching the Python service's answer for the same
  inputs.

### Phase 5 — WASM bindings and browser integration

- `rust/genesis-prnu-wasm`: `wasm-bindgen` wrapper exposing something like
  `score(image_bytes: &[u8], k_bytes: &[u8]) -> ScoreResult { score: f64,
  pce: f64 }`. Build with `wasm-pack build --target web`.
- Measure the built `.wasm` size and load time; this is the number that
  justifies the whole rewrite over Pyodide — report it.
- A minimal browser integration: K stored in IndexedDB (never uploaded
  anywhere), an uploaded photo scored entirely client-side. Where this
  lives (a new page, or folded into `verify/` or `dashboard/`) is an open
  design question for that session, not decided here.

### Phase 6 (stretch, separate decision before starting) — desktop reuse

- Add `desktop/src-tauri` to the Cargo workspace and call
  `genesis-prnu` directly from Rust instead of through PyO3 for the
  scoring/verify path, shrinking or eliminating the bundled Python runtime
  for that half of the app (`desktop/PACKAGING.md`). Enrolment's Python/
  rawpy dependency is unaffected and the app still needs *some* Python
  runtime bundled until/unless enrolment also moves — evaluate whether a
  partial win (smaller bundle, same architecture) is worth doing before
  enrolment moves, or whether to wait.

## What "done" looks like for the first session

Phases 0–2 completed and passing parity, committed. Not more — the
wavelet transform is the riskiest, least forgiving part of this port, and
getting it right with a real fixture-based harness matters more than
speed through the later phases.

---

## Prompt for the next session

```
Genesis (certify-the-camera) is porting its PRNU photo-scoring algorithm
from Python to Rust, to eventually compile to WASM for in-browser scoring
and to replace the PyO3-embedded Python interpreter in the Tauri desktop
app. Full context, rationale, the precise algorithm spec, repo layout, and
the full phase breakdown are in docs/wasm-scoring-plan.md -- read that
file first, in full, before writing any code.

Do Phases 0-2 from that plan in this session:

- Phase 0: a throwaway Python script that dumps golden input/output
  fixtures from the real fingerprint/prnu.py (noise_residual,
  cross_correlation, pce, score) into rust/genesis-prnu/tests/fixtures/,
  with a short README explaining each fixture and how to regenerate it.
- Phase 1: a new Cargo workspace (root Cargo.toml, rust/genesis-prnu
  member) implementing db8, 4-level, symmetric-boundary 2-D DWT/IDWT
  (rust/genesis-prnu/src/wavelet.rs), with a parity test against the
  fixtures and against PyWavelets' actual wavedec2 output -- not a generic
  Daubechies-8 reference, PyWavelets' own convention specifically.
- Phase 2: port _variance_estimate and the Wiener shrinkage step to
  produce noise_residual, parity-tested against the fixtures within a
  tight numeric tolerance.

Hard constraints, from the plan doc -- do not relax these:
- Do not touch enrolment, RAW decoding, or commitment() -- those stay
  Python-only in this phase, on purpose (rawpy has no WASM path; K
  commitments are already live on chain on Base Sepolia).
- Every phase ends in a parity check against the Python reference, not
  "it compiles." A subtly wrong wavelet transform will not throw an
  error -- it will just quietly produce wrong scores later, so the parity
  harness is not optional scaffolding, it's the actual deliverable.
- Do not restructure desktop/src-tauri in this session. It stays exactly
  as it is; workspace integration is Phase 6, later, and is its own
  decision.

Stop and report back after Phase 2 passes parity, rather than continuing
into Phase 3+ -- the wavelet transform is the highest-risk piece and
should be checked before building more on top of it.
```

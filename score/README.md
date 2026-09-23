# Genesis — score

Local, offline PCE scoring against your own enrolled fingerprint (K),
entirely client-side. A fourth Vite app sibling to `site/`, `verify/` and
`dashboard/`, deployed at `/score/`.

See `docs/wasm-scoring-plan.md` (Phase 5) and `docs/security.md`
("Where K lives") for the invariant this page exists to preserve: K never
leaves the machine it's on. This page makes no network request involving
either the K file or the photo -- both are read from local `File` objects
and handed straight into a WASM module compiled from
`rust/genesis-prnu-wasm` (which itself wraps `rust/genesis-prnu`, the same
scoring core the Python reference and the desktop app use).

## Building the WASM module

The actual scoring code is Rust, compiled with `wasm-pack`, not part of
this package's own TypeScript. `npm run dev`/`npm run build` won't work
until `score/src/wasm/` exists with the `wasm-pack --target web` output
(`genesis_prnu_wasm.js`, `genesis_prnu_wasm_bg.wasm`, `.d.ts` files).

This is wired up automatically: `predev` and `prebuild` npm lifecycle
scripts run `npm run wasm` before `vite`/`vite build`, which runs

```
wasm-pack build ../rust/genesis-prnu-wasm --target web --release --out-dir ../../score/src/wasm
```

Note the `../../` in `--out-dir`: `wasm-pack`'s `--out-dir` is resolved
relative to the **crate path** you gave it (`../rust/genesis-prnu-wasm`,
itself relative to this package), not to the directory you ran the command
from -- so getting the output back into `score/src/wasm` needs one more
`../..` than you'd expect. If you ever see the output land inside
`rust/genesis-prnu-wasm/src/wasm` instead, that's this gotcha.

`score/src/wasm/` is never committed -- `wasm-pack` writes its own
`.gitignore` (`*`) into that directory, so a fresh checkout always needs
`npm run wasm` (or a plain `npm run build`/`npm run dev`, which run it for
you) before anything in `src/main.ts` will resolve.

Requires a Rust toolchain with the `wasm32-unknown-unknown` target and
`wasm-pack` on `PATH` (`cargo install wasm-pack`, or `which wasm-pack` to
check). `.github/workflows/pages.yml` installs both before building this
package in CI.

## What's on the page

- A file input for the enrolled `K` `.npz` file (labelled as never
  uploaded anywhere) -- read into an in-memory `Uint8Array` for this tab's
  session only (see the comment at the top of `src/main.ts` for why this
  is in-memory rather than IndexedDB, and what to change if that needs to
  become persistent later).
- A file input for the photo to score.
- A "Score" button that calls into the WASM module's `score(imageBytes,
  kBytes)` and displays the resulting PCE against
  `fingerprint/prnu.py`'s `PCE_THRESHOLD = 100.0` (via the module's
  `pceThreshold()` export, so the number is never duplicated by hand on
  the JS side).

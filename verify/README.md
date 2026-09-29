# Genesis — verify

Drop a photo, get its record off the chain. Deployed at `/verify/` on
GitHub Pages (`.github/workflows/pages.yml`).

The page computes the photo's two hashes itself, in WASM, and reads Base
and The Graph directly. The photo is never uploaded. `src/main.ts` has the
verdict logic, `src/hashes.ts` the hashing.

## Two WASM modules

`npm run dev` and `npm run build` build both first (`predev`/`prebuild`
run `npm run wasm`). Neither output is committed.

- **`src/wasm/`**: `rust/genesis-prnu-wasm`, built with `wasm-pack`. It
  computes the pixel hash and perceptual hash from RGB pixels and decodes
  PNG and TIFF. The same crate powers `score/`; see `score/README.md` for
  the `--out-dir` gotcha.
- **`src/jpeg/`**: libjpeg-turbo, built with Emscripten by
  `jpeg/build.sh`. You need `emcc` on your PATH
  (https://emscripten.org/docs/getting_started/downloads.html). CI uses
  `mymindstorm/setup-emsdk`.

### Why JPEG gets its own decoder

The pixel hash (`ingest/hashing.py`) is an exact SHA-256 over decoded
pixels, so the browser has to decode a JPEG to the very bytes Python does.
Python decodes with the libjpeg-turbo bundled in Pillow. The Rust `image`
crate does not produce the same bytes: on a real camera JPEG, 15% of
bytes differed. Every JPEG would then come back "no record".

`jpeg/build.sh` pins libjpeg-turbo to the version bundled in the Pillow
the Python side runs. `requirements.txt` pins Pillow (12.3.0, which bundles
libjpeg-turbo 3.1.4.1) for the same reason. **To upgrade Pillow:** check
`features.version("libjpeg_turbo")`, and if it changed, bump `build.sh`,
regenerate the fixtures, and rerun everything below. Registrations made
before and after the change may disagree about the same JPEG, which is why
this is a deliberate step and not a floating dependency.

## Tests

```
.venv/bin/python -m pytest ingest/validate_hash_fixtures.py  # fixtures still match Python
cargo test -p genesis-prnu                                  # Rust: PNG parity, unit tests
npm test                                                    # verify: every fixture, JPEG included, plus verdict logic
npm run parity -- ~/photos/a.jpg ~/photos/b.png             # real photos against live Python
```

Regenerate the fixtures with `.venv/bin/python -m ingest.dump_hash_fixtures`
whenever `hashing.py` or the pins change; the pytest above fails until you do.

- `test/hashes.test.ts` runs the real WASM modules against the fixtures.
  It is the only place JPEG parity is tested, because cargo test can't
  link libjpeg-turbo. It also covers the refusals: RAW, CMYK, 16-bit and
  truncated files error out rather than produce a hash nothing matches.
- `test/verify.test.ts` covers the verdict logic, with the chain and The
  Graph stubbed. It includes the property this page exists for: without
  `VITE_SCORING_URL`, no request carries the photo.

CI runs the Rust and verify tests on every PR (`ci.yml`, the `wasm` job),
and runs `npm test` again in `pages.yml` before deploying.

## Scoring service (optional)

With `VITE_SCORING_URL` set (see `.env.example`), the page also posts the
photo to that service's `/lookup` for PRNU candidates. That is the only
way to reach the `fingerprint-only` verdict, because it means searching
every enrolled K, and K files never go to a browser. The Pages build
leaves it unset.

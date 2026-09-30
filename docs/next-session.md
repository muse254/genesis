# Next session: where things stand, and what is open

Written 30 September 2026, for whoever picks this up next. Colosseum's
deadline is **Sunday 12 October** (`COLOSSEUM.md`); the checklist is
`docs/colosseum-checklist.md`. The direction chosen on 30 September is the
open core plus a paid **Genesis Cloud** (`docs/cloud-plan.md`).

## State of the repo

- `main` has everything: the WASM verify page (PR #1), one verification
  implementation for the web page and the desktop app (PR #2,
  `docs/shared-verify-plan.md`), and LibRaw in WASM for browser enrolment
  (`core/raw/`). CI and the Pages deploy are green.
- The live verify page, https://muse254.github.io/genesis/verify/, hashes in
  the browser and makes no localhost call. `/score/` is live too.
- Local branch `browser-enrol` equals `main`; use it or branch fresh.
- Untracked `.agents/` and `skills-lock.json` are not project files; leave
  them out of commits.

## Tools a fresh machine needs

The WASM builds need **Emscripten** (`emcc`) and **wasm-pack** on PATH, plus
the `wasm32-unknown-unknown` Rust target. Last session's Emscripten lived in
a temporary scratch directory and is gone: install it properly
(https://emscripten.org/docs/getting_started/downloads.html, or
`brew install emscripten`). Browser checks were done with `puppeteer-core`
driving the installed Chrome; that harness was scratch too.

The real RAW frames used for measurements are deliberately not in the repo,
and their location is deliberately not written in any committed file.

## Open, in priority order

### Critical path to the submission (`COLOSSEUM.md`: never cut)

1. **Deployer / mainnet key** — *Osoro*. Choose and back up; it owns the R10
   body forever. Fund with ~0.005 ETH on Base.
2. **Deploy the registry to Base mainnet**, `REGISTRY_TEST_MODE` unset,
   verified on Basescan; pin the address in README and `.env.example`.
   *Needs the key from 1.* An agent can prepare and dry-run it.
3. **Subgraph on Base mainnet, published** (the Studio development URL is
   capped at 3,000 queries/day). Deploy key is in `.env`.
4. **Register the R10 on mainnet** with a camera commitment, then **20+
   photographs**, each resolvable from the public verify page. *Osoro.*
5. **README for a stranger**: verify an image in 60 seconds without
   `BUILD.md`; `docs/adversarial.md` linked prominently.
6. **LICENSE** — *Osoro decides*; open-source status is scored. Must be
   compatible with shipping LibRaw (LGPL 2.1 / CDDL 1.0) in WASM.
7. **Week 3 (1–7 Oct): ten enrolled cameras that are not the founder's**,
   one note per onboarding, the first osoroprints customer. The column
   judges weigh most.

### Genesis Cloud (`docs/cloud-plan.md`)

8. **Decisions C1–C5** in the plan — *Osoro*. C1 (who can decrypt K) and C2
   (Stripe entity/country) block building.
9. **Colosseum slice C1–C2**, only if mainnet is live and week 3 is on track
   by ~5 October: Cloud Run skeleton, Google + wallet sign-in, Stripe test
   mode, encrypted K backup in the browser.

### Follow-ups from the 29–30 September work

10. **Run the desktop release build** (`desktop.yml`, workflow_dispatch). It
    has never run with the shared verification in the packaged app
    (WKWebView). It creates a draft release — ask before triggering.
11. **Score page: "No fingerprint file? Get the desktop app"** link to the
    landing page's download. ~15 minutes.
12. **Browser enrolment, steps 2–3** (step 1, LibRaw in WASM, is done:
    `core/raw/`, 43/43 files exact against `rawpy`):
    - Rust: `split_cfa`, the estimator, `postprocess` (`_zero_mean`,
      `_wiener_dft`), `commitment()` and an `.npz` writer that
      `load_fingerprint` reads (the `meta` field is a numpy unicode scalar).
      Parity-test each against Python fixtures; the commitment exactly.
    - An enrol page: 40+ RAWs, serial check (LibRaw's body serial replaces
      `exiftool`), saturation warning, progress, download of the K. A CSP
      with no outbound connections, so K can leave only as a download.
    - Enrol from the real 41 frames in the browser and compare with the
      Python K: held-out frames must score within 2%.
    - A `POST /bodies/import` on the console so the desktop app can take a
      browser-made K (the cloud plan needs the same endpoint).
13. **Registration onto `core/` (phase E2, `docs/shared-verify-plan.md`)**:
    registration still scores and hashes in Python while verification runs
    the Rust port. Parity-tested, but two implementations.
14. **Faster Rust scoring**: 1.2–1.8x slower than numpy, single-threaded;
    an aligned 24 MP score takes ~7 s in the desktop app. Helps both
    frontends.
15. **Retire the scoring service (phase F)**: its public mode no longer
    serves the verify page.

### Smaller, from the checklist

16. MCP server against live Base data; an agent can check an image it holds
    (core's `hashImage` makes this easy); install instructions.
17. Hot-pixel and defect map (`adversarial.md` tier 1, item 2) — first to
    cut.
18. Week 4: demo video, pitch, prior-work disclosure
    (`git log --since=2026-09-14`), submission form.

## Things learned that are easy to lose

- The coverage floor in `ci.yml` only fails the job because the step now
  runs with `shell: bash` (pipefail). Before that it was silently green.
- JPEG pixel hashes are defined by the libjpeg-turbo in the pinned Pillow;
  `core/jpeg/build.sh`, `requirements.txt` and the fixtures move together.
- LibRaw's WASM build needs WASM exceptions and an 8 MB stack; without
  either, real CR3s crash it.
- `.npz` is gitignored on purpose (a real K is a forgery kit); synthetic
  test fixtures get explicit exceptions in `.gitignore`.

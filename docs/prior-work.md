# Prior-work disclosure

For the Colosseum judges. Genesis existed before this hackathon. It was
built for ETHOnline (4–16 September 2026). This file marks the boundary
between that earlier work and the work done during the Crypto World's Fair
window, so only the in-window work is judged.

## The boundary

- **Prior work ends at commit `1e2f392`** (13 September 2026), tagged
  `ethonline-submission` and also kept as the branch `ethonline`. Neither
  has moved since. The window opened on 14 September.
- **The in-window work is every commit after the tag:** 61 commits,
  14 September to 12 October 2026, all by Osoro Bironga. Two are merge
  commits of the founder's own pull requests, and 59 are not. Reproduce the
  list with:

  ```sh
  git log --reverse --no-merges --format='%ad %h %s' --date=short ethonline-submission..main
  ```

- Across the window: 291 files changed, with 24,403 lines added and 5,341
  removed (`git diff --shortstat ethonline-submission main`).

## What existed before the window

As of `ethonline-submission`:

- **Fingerprinting (Python):** PRNU extraction and PCE scoring (`fingerprint/`,
  `scoring/`), and record construction (`ingest/`).
- **The registry contract on Ethereum Sepolia,**
  `0xd1bbDB8A6BfD25563d2e6444fA41E4C5230Ed3C9`, with a subgraph.
- **A verify page** that called a scoring service on localhost.
- **A presenter console** (`console/`, `console-ui/`) and an MCP server sketch.
- **Chainlink CRE** (`cre/`) and **ENS identity** (`identity/`). Both were
  removed in the window (17 September) and stay at the tag.
- **The adversarial work** (`docs/adversarial.md`): the measured attacks on
  the fingerprint and the numbers that were corrected.

## What was built in the window

- **Base, and then Base mainnet.** The camera commitment moved from ENS into
  the registry. Rehearsed on Base Sepolia (17 September). Registry 1.0.0
  deployed to Base mainnet on 12 October at
  `0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB`. It adds transfers,
  attestations and challenges, a registration date set by the chain, and a
  guard that refuses test mode on mainnet. The registry sets the date because
  dates are the claim.
- **On mainnet, 12 October:** the founder's Canon R10 is registered with its
  camera commitment, and 20 photographs are registered. All 20 resolve from
  their files, and again after being resized, re-encoded and stripped.
- **One verification core for web and desktop.** The PRNU scorer was ported
  to Rust and compiled to WASM. `core/` is a single TypeScript verify package
  that both the verify page and the desktop app run, so the two cannot
  disagree. The verify page now hashes photos in the browser instead of
  calling a server.
- **LibRaw in WASM** for decoding RAW files in the browser, matching rawpy
  field for field.
- **A desktop app:** a Tauri shell with the Python imaging core embedded via
  PyO3, plus CI-built installers.
- **Public pages:** a landing page, a dashboard that looks up any address's
  bodies and images, and a status page.
- **The MCP server:** an agent can check an image file it holds, using the
  same core as the verify page.
- **CI for every component,** with the Registry at 100% test coverage.
- **Plans:** the go-to-market, Genesis Cloud (open core, paid cloud), the
  platform plan, the desktop plan (Google sign-in, Stripe, no visible crypto),
  and the MIT LICENSE.

## In-window commits

The output of the command above as of 12 October 2026, with merges left out.

```
2026-09-17 92930ec COLOSSEUM.md: the 25-day plan for Crypto World's Fair
2026-09-17 ff7b5f2 COLOSSEUM.md: D1 Base mainnet, D2 drop ENS and move the body commitment on chain, D3 3h/day
2026-09-17 3c058ad Registry: the body commitment takes the ENS node's slot; Base Sepolia may run test mode
2026-09-17 64108d3 Console and ingest: GENESIS_CHAIN picks the chain; register a body with a camera commitment, not an ENS label
2026-09-17 0125261 Subgraph, MCP, verify page, local e2e: bodyCommitment in place of ensNode
2026-09-17 3967341 security.md and .env.example: the camera commitment lives in the body record; Base settings
2026-09-17 f9eeb0d docs/colosseum-checklist.md: what is done, what is left, and how scoring works without CRE
2026-09-17 0c32420 No server holds K: public scoring mode, identity from the chain, and the posture that defends it
2026-09-17 1e36770 Remove Chainlink CRE and ENS code from the Colosseum build
2026-09-17 cd48046 Checklist: the Base Sepolia rehearsal passed
2026-09-17 ff4bf6b Desktop app: Tauri shell around the console, with the Python backend as a sidecar
2026-09-17 ed0b47d CI for every component; Registry at 100% coverage; AI-USE.md removed
2026-09-17 a775e4d Checklist: CI is green
2026-09-17 5f38ce6 Ignore coverage output
2026-09-17 3b8c51c README: rewritten for Colosseum around the intro, how it works, and the maths
2026-09-17 25654cb docs/go-to-market.md: buyers, pricing hypotheses, distribution and honest demand validation
2026-09-18 67b8f7c console-ui: sidebar app replaces the eight-screen presenter console
2026-09-18 d490c2f Desktop app: fix the real 'Load failed' bug (a startup race), plus two defensive CORS/plist fixes found chasing it
2026-09-18 18675a2 Checklist: the sidebar rebuild and the startup-race fix
2026-09-18 8f797c7 Desktop: embed the Python imaging core (PyO3) instead of a sidecar process
2026-09-18 9c29e8c Checklist: the sidecar is gone, embedded Python instead
2026-09-20 8912776 README: pin the ETHOnline reference to its commit SHA, not just the tag
2026-09-20 30cf415 ci.yml: satisfy tauri-build's resource-path check with empty placeholders
2026-09-22 aae70bb Landing page on GitHub Pages, download links pulled from the release API
2026-09-22 e265575 Dashboard: look up any address's bodies and images, no login
2026-09-22 bec7c95 Redeploy the subgraph (v0.0.5) and fix chrome consistency across the three pages
2026-09-22 0cba3f9 verify/dashboard: light mode only, matching the landing page
2026-09-22 42b75eb Fix wrong-chain subgraph, repoint everything at Base Sepolia, add a status page
2026-09-23 e43839c Same nav on every page: Source was missing from verify/ and dashboard/
2026-09-23 9817014 Plan: Rust port of the scoring core, WASM-first, with a phased handoff
2026-09-23 8f4d394 Rust PRNU port, Phases 0-2: fixtures, db8 wavelet transform, noise_residual
2026-09-23 72e6b01 Rust PRNU port, Phases 3-5: score(), WASM module, and a local-scoring page
2026-09-23 4777310 Update literature to reflect the scoring core's Rust port
2026-09-23 31a66dc Desktop app: native Rust scoring for delivered-image probes (Phase 6, partial)
2026-09-29 5b7b461 Verify page: hash photos in the browser, no more localhost scoring call
2026-09-29 d85bf1c genesis-prnu: clear clippy findings the desktop job now sees
2026-09-29 ea2279e desktop: move the score_delivered_image tests to the end of lib.rs
2026-09-29 56ac6be Desktop: check the bundled Python hashes photos exactly as the verify page
2026-09-29 f9abc0b CI: make the coverage floor actually fail, and leave fixture generators out
2026-09-29 f2477cd Rust core: the whole verify-time scoring path, from pixels (phase A)
2026-09-29 826f47d WASM: score against an enrolled body, RAW included, plus signals (phase B)
2026-09-29 a6251fd core/: one TypeScript verification package for web and desktop (phase C)
2026-09-29 f36766d Verify page on core/ (phase D)
2026-09-29 71135e5 Desktop app verifies on core/ (phase E)
2026-09-29 73e8032 Update the literature for one shared verify implementation
2026-09-29 fd80e90 BUILD.md: redraw the architecture diagram for the shared verify path
2026-09-29 4b2cffc LibRaw in WASM, matching rawpy exactly, for enrolment in the browser
2026-09-30 7eaa0c0 Plan Genesis Cloud (open core, paid cloud) and hand off what is open
2026-10-12 839cb8f Registry 1.0.0 for mainnet: transfers, attestations, a chain-set date
2026-10-12 8996ead Verify page: say when a near-identical image was registered earlier
2026-10-12 e7d4cc2 MCP: verify_image_file, hashing with core's WASM
2026-10-12 185ad94 MIT LICENSE, a README a stranger can use, launch and platform plans
2026-10-12 a761f8b Pin the Base mainnet registry: 0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB
2026-10-12 5bd05ac Subgraph and verify page on Base mainnet
2026-10-12 eba5403 Console signs with a Foundry keystore, keeping the key off argv
2026-10-12 1dd235d Console gas gate: 0.001 ETH, measured against Base mainnet
2026-10-12 9d13a2c Desktop parity: every launch-day step against the shipped app
2026-10-12 5c330ce Desktop parity without the crypto: Google sign-in, Stripe, hidden signing
2026-10-12 ab3d0a5 R10 and 20 photographs on Base mainnet; MCP reads Base by default
```

Commits made on 12 October after this file was written are part of the
window too. The command above always lists the complete set.

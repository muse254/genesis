# Genesis — verify

Drop a photo, get its record off the chain. Deployed at `/verify/` on
GitHub Pages (`.github/workflows/pages.yml`).

This app is configuration and rendering. The verification is `core/`
(`@genesis/core`), the same code the desktop app runs, so the two cannot
disagree about a photo (`docs/shared-verify-plan.md`). See `core/README.md`
for how it works, its two WASM modules and its tests.

The photo never leaves the browser. It is decoded and hashed in a Web
Worker, and only the hashes go out: to the chain RPC (`VITE_RPC_URL`) and to
The Graph (`VITE_SUBGRAPH_URL`). This page holds no fingerprints, so it
never reaches `fingerprint-only`; the desktop app, holding its owner's K,
does.

## Build

`npm run dev` / `npm run build` build core's WASM first (`predev` /
`prebuild`), which needs `wasm-pack` and Emscripten's `emcc` on your PATH,
and core's own dependencies installed (`npm ci` in `core/`).

Configuration is in `.env.example`. There is no localhost default for
anything: with no `VITE_REGISTRY_ADDRESS`/`VITE_RPC_URL` the page still
hashes, and says "no record".

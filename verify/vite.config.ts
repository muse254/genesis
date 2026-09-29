import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Relative base: this app is deployed under a subpath on GitHub Pages
// (site/ is the root, this build lands at /verify/ inside it -- see
// .github/workflows/pages.yml). Relative asset URLs work at any depth
// without hardcoding the repo name here.
//
// Verification itself lives in core/ (docs/shared-verify-plan.md), shared
// with the desktop app. There is no npm workspace, so it is reached by
// alias, and the dev server is allowed to serve it from outside this app.
export default defineConfig({
  base: "./",
  resolve: {
    alias: { "@genesis/core": fileURLToPath(new URL("../core/src/index.ts", import.meta.url)) },
  },
  server: { fs: { allow: [".."] } },
  // The worker imports WASM glue that uses import.meta.url.
  worker: { format: "es" },
});

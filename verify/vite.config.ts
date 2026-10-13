import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// Relative base: deployed under /verify/ on GitHub Pages (.github/workflows/pages.yml).
// No npm workspace, so core/ is reached by alias and fs.allow.
export default defineConfig({
  base: "./",
  resolve: {
    alias: { "@genesis/core": fileURLToPath(new URL("../core/src/index.ts", import.meta.url)) },
  },
  server: { fs: { allow: [".."] } },
  // The worker imports WASM glue that uses import.meta.url.
  worker: { format: "es" },
});

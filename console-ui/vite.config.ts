import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Vite's default `localhost` can resolve to ::1 only, refusing 127.0.0.1.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    // core/ lives outside this app; see the alias below.
    fs: { allow: [".."] },
  },
  // core/ is shared with the web page; no npm workspace, so it's an alias.
  resolve: {
    alias: { "@genesis/core": fileURLToPath(new URL("../core/src/index.ts", import.meta.url)) },
  },
  // core's worker imports WASM glue that uses import.meta.url.
  worker: { format: "es" },
});

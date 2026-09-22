import { defineConfig } from "vite";

// Relative base, same reason as verify/vite.config.ts: this deploys nested
// under /dashboard/ on GitHub Pages (.github/workflows/pages.yml).
export default defineConfig({
  base: "./",
});

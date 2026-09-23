import { defineConfig } from "vite";

// Relative base, same reason as verify/vite.config.ts and
// dashboard/vite.config.ts: this deploys nested under /score/ on GitHub
// Pages (.github/workflows/pages.yml).
export default defineConfig({
  base: "./",
});

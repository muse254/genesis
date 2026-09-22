import { defineConfig } from "vite";

// Relative base: this app is deployed under a subpath on GitHub Pages
// (site/ is the root, this build lands at /verify/ inside it -- see
// .github/workflows/pages.yml). Relative asset URLs work at any depth
// without hardcoding the repo name here.
export default defineConfig({
  base: "./",
});

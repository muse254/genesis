import { defineConfig } from "vite";

export default defineConfig({
  server: {
    // Bind the v4 loopback explicitly. Vite's default binds `localhost`, which
    // on this machine resolves to ::1 only -- so http://127.0.0.1:5173 refuses
    // the connection while http://localhost:5173 works. Both addresses appear
    // in the console API's CORS allowlist and in the handoff's chrome, and a
    // presenter typing the wrong one loses a minute on camera to a blank page.
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
  },
});

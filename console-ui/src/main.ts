/**
 * The console shell: chrome, screen switching, presenter shortcuts.
 *
 * The stage fills the viewport. The handoff draws 1280x720 because that is
 * the recording resolution, not because the console should be that size --
 * locked to it, anything that is not 16:9 letterboxes and the page's height
 * goes unused. Size the window to 16:9 when recording and it is the board
 * again, exactly.
 */

import "./tokens.css";
import "./console.css";
import { api } from "./api";
import { SCREENS } from "./screens";

/**
 * Served from `public/`, not hotlinked.
 *
 * The handoff lists the marks as public raw.githubusercontent URLs, and that
 * is fine for a design board. In the console it is a network dependency on
 * the one thing that must not fail: raw.githubusercontent returned 503 while
 * this was being wired, which would have put a broken-image icon in the
 * header of a recording. Chrome does not get to depend on the internet.
 *
 * 1540x416 native, so 20px tall is 74px wide. Both are set to stop the header
 * reflowing as the image decodes.
 */
const MARK = "/genesis-lockup-horizontal-ink.png";
const MARK_W = 74;
const MARK_H = 20;

const app = document.getElementById("app")!;
app.innerHTML = `
  <div id="stage">
    <header class="chrome">
      <img src="${MARK}" width="${MARK_W}" height="${MARK_H}" alt="Genesis" />
      <span class="divider"></span>
      <nav class="steps"></nav>
      <span class="meta"></span>
    </header>
    <main class="screen"></main>
    <footer class="chrome">
      <span class="dot" data-dot="scorer"><i></i>SCORER</span>
      <span class="dot" data-dot="rpc"><i></i>RPC</span>
      <span class="dot" data-dot="ens"><i></i>ENS</span>
      <span class="standing">FINGERPRINT STAYS ON THIS MACHINE — ONLY HASHES LEAVE IT</span>
    </footer>
  </div>`;

const nav = app.querySelector("nav.steps")!;
const screen = app.querySelector("main.screen") as HTMLElement;
let current = SCREENS[0].id;

function show(id: string) {
  const entry = SCREENS.find((s) => s.id === id) ?? SCREENS[0];
  current = entry.id;
  nav.querySelectorAll("button").forEach((button) =>
    button.setAttribute("aria-current", String(button.dataset.id === current)),
  );
  entry.render(screen);
}

nav.innerHTML = SCREENS.map(
  (s) => `<button data-id="${s.id}">${s.label}</button>`,
).join("");
nav.addEventListener("click", (event) => {
  const id = (event.target as HTMLElement).closest("button")?.dataset.id;
  if (id) show(id);
});

/**
 * Footer dots. Green means the dependency answered, red means it did not --
 * and a red dot is the only place a failure is allowed to be silent, because
 * nothing on screen is withdrawn when one goes down.
 */
async function heartbeat() {
  const set = (name: string, up: boolean) =>
    app.querySelector(`[data-dot="${name}"]`)!.classList.toggle("down", !up);
  try {
    const state = await api.state();
    const has = (needle: string) =>
      state.checks.find((c) => c.check.includes(needle))?.go ?? false;
    set("scorer", state.bodies.length > 0);
    set("rpc", has("chain id") && has("block"));
    set("ens", has("ens"));
    app.querySelector(".meta")!.textContent =
      `LOCALHOST:5173 · SEPOLIA · ${new Date().toISOString().slice(11, 19)} UTC`;
  } catch {
    set("scorer", false);
    set("rpc", false);
    set("ens", false);
    app.querySelector(".meta")!.textContent = "LOCALHOST:5173 · CONSOLE UNREACHABLE";
  }
}

// Presenter shortcuts. P re-runs pre-flight; number keys jump to a screen,
// because reaching for a mouse mid-take is a cut.
addEventListener("keydown", (event) => {
  if ((event.target as HTMLElement)?.tagName === "INPUT") return;
  if (event.key.toLowerCase() === "p") show("preflight");
  // C re-renders the current screen, which is how it clears: a presenter runs
  // each screen several times in a take, and a stale result beside a fresh
  // photograph is how a demo shows the wrong number to an audience.
  if (event.key.toLowerCase() === "c") show(current);
  const index = Number(event.key);
  if (!Number.isNaN(index) && SCREENS[index]) show(SCREENS[index].id);
});

// No stage scaling: #stage fills the viewport and the layout flexes.

show(current);
heartbeat();
setInterval(heartbeat, 10_000);

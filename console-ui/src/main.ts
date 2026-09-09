/**
 * The console shell: chrome, screen switching, presenter shortcuts.
 *
 * Drawn at 1280x720 -- the recording resolution -- and scaled to fit the
 * window, so every measurement in the handoff stays literal instead of
 * becoming approximate on a different display.
 */

import "./tokens.css";
import "./console.css";
import { api } from "./api";
import { SCREENS } from "./screens";

const MARK = "https://raw.githubusercontent.com/muse254/genesis/main/logos/genesis-lockup-horizontal-ink.png";

const app = document.getElementById("app")!;
app.innerHTML = `
  <div id="stage">
    <header class="chrome">
      <img src="${MARK}" alt="Genesis" />
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
  const index = Number(event.key);
  if (!Number.isNaN(index) && SCREENS[index]) show(SCREENS[index].id);
});

// Scale the fixed stage into whatever window the presenter has.
function fit() {
  const stage = app.querySelector("#stage") as HTMLElement;
  const scale = Math.min(innerWidth / 1282, innerHeight / 722, 1);
  stage.style.transform = `scale(${scale})`;
  app.style.height = `${722 * scale}px`;
}
addEventListener("resize", fit);

show(current);
fit();
heartbeat();
setInterval(heartbeat, 10_000);

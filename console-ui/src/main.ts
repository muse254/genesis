/**
 * Unreferenced: the old presenter console shell, superseded by `app.ts`.
 */

import "./tokens.css";
import "./console.css";
import { api } from "./api";
import { SCREENS } from "./screens";

/** Served locally so the chrome never depends on the network. Size set to avoid reflow. */
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
      <span class="dot" data-dot="index"><i></i>INDEX</span>
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

/** Footer dots: green if the dependency answered, red if not. */
async function heartbeat() {
  const set = (name: string, up: boolean) =>
    app.querySelector(`[data-dot="${name}"]`)!.classList.toggle("down", !up);
  try {
    const state = await api.state();
    const has = (needle: string) =>
      state.checks.find((c) => c.check.includes(needle))?.go ?? false;
    set("scorer", state.bodies.length > 0);
    set("rpc", has("chain id") && has("block"));
    set("index", has("perceptual index"));
    // Read the chain id rather than asserting it.
    const chainId = state.chain?.chainId;
    const network = !chainId
      ? "NO CHAIN"
      : state.chain.onExpectedChain && state.chain.chainName
        ? state.chain.chainName.toUpperCase()
        : `CHAIN ${chainId}`;
    app.querySelector(".meta")!.textContent =
      `LOCALHOST:5173 · ${network} · ${new Date().toISOString().slice(11, 19)} UTC`;
  } catch {
    set("scorer", false);
    set("rpc", false);
    set("index", false);
    app.querySelector(".meta")!.textContent = "LOCALHOST:5173 · CONSOLE UNREACHABLE";
  }
}

// Presenter shortcuts: P pre-flight, C clear, digits jump to a screen.
addEventListener("keydown", (event) => {
  if ((event.target as HTMLElement)?.tagName === "INPUT") return;
  if (event.key.toLowerCase() === "p") show("preflight");
  if (event.key.toLowerCase() === "c") show(current);
  const index = Number(event.key);
  if (!Number.isNaN(index) && SCREENS[index]) show(SCREENS[index].id);
});

show(current);
heartbeat();
setInterval(heartbeat, 10_000);

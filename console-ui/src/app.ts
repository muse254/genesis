/**
 * The photographer's app: a sidebar and five destinations, replacing the
 * eight-screen presenter console (`main.ts` + `screens.ts`, kept for
 * reference and still buildable, just no longer the entry point).
 *
 * What merged: Negative, Survival and Verdict were three demo scenarios for
 * the same one thing -- dropping an image and reading its verdict. They are
 * all just Verify here, and it renders the exact four-verdict card
 * (`components.ts:verdictCard`) with the claims-discipline copy verbatim.
 * Pre-flight becomes a status dot in the sidebar footer, shown in detail only
 * in Settings; the registry reset control does not exist in this app at all
 * -- it is a testnet-only escape hatch, not a photographer-facing feature.
 *
 * Everything here still talks to the same `console/app.py`. Nothing about
 * where K lives changes: enrolment and scoring stay on this machine
 * (`docs/security.md`, "Where K lives").
 */

import "./tokens.css";
import "./console.css";
import "./app.css";
import { api, ETHERSCAN, readContractUrl } from "./api";
import type { ReferenceLink, State } from "./api";
import { el, escape, short, utc, verdictCard } from "./components";

type ViewId = "home" | "photos" | "verify" | "cameras" | "settings";

const VIEWS: { id: ViewId; label: string }[] = [
  { id: "home", label: "Home" },
  { id: "photos", label: "Photos" },
  { id: "verify", label: "Verify" },
  { id: "cameras", label: "Cameras" },
  { id: "settings", label: "Settings" },
];

/** What a browser can decode itself; a RAW file goes through `/preview`. */
const RAW = /\.(cr3|cr2|dng|arw|nef|raf|rw2|orf|pef|srw)$/i;

// --- Shell ----------------------------------------------------------------

const app = document.getElementById("app")!;
app.innerHTML = `
  <div id="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <img src="/genesis-lockup-horizontal-ink.png" alt="Genesis" />
      </div>
      <nav class="sidebar-nav"></nav>
      <div class="sidebar-footer">
        <div class="sidebar-status" data-status>
          <i></i><span>checking…</span>
        </div>
        <p class="sidebar-quota"></p>
      </div>
      <button class="sidebar-collapse" title="Collapse">« collapse</button>
    </aside>
    <main class="app-content"></main>
  </div>`;

const shell = app.querySelector(".sidebar")!;
const nav = app.querySelector(".sidebar-nav")!;
const content = app.querySelector(".app-content") as HTMLElement;

nav.innerHTML = VIEWS.map(
  (v) => `
    <button data-view="${v.id}">
      <span class="bullet"></span>
      <span class="label">${escape(v.label)}</span>
      <span class="initial">${v.label[0]}</span>
      <span class="needs-attention" hidden></span>
    </button>`,
).join("");

let currentView: ViewId = "home";

function show(id: ViewId, pushHash = true) {
  currentView = id;
  if (pushHash) location.hash = id;
  nav.querySelectorAll("button").forEach((b) =>
    b.setAttribute("aria-current", String((b as HTMLElement).dataset.view === id)),
  );
  render(id);
}

addEventListener("hashchange", () => {
  const id = location.hash.slice(1) as ViewId;
  if (VIEWS.some((v) => v.id === id)) show(id, false);
});

nav.addEventListener("click", (event) => {
  const id = (event.target as HTMLElement).closest("button")?.dataset.view as ViewId | undefined;
  if (id) show(id);
});

app.querySelector(".sidebar-collapse")!.addEventListener("click", () => {
  shell.classList.toggle("collapsed");
});

function render(id: ViewId) {
  content.innerHTML = "";
  content.scrollTop = 0;
  switch (id) {
    case "home": return renderHome(content);
    case "photos": return renderPhotos(content);
    case "verify": return renderVerify(content);
    case "cameras": return renderCameras(content);
    case "settings": return renderSettings(content);
  }
}

// --- Shared cache -----------------------------------------------------

/**
 * `/state` and `/catalogue` are read by every view, and re-fetching on each
 * click makes the sidebar feel like a page load. Cached for a few seconds
 * and invalidated by anything that changes what they report, the same rule
 * the old console's `/state` cache used server-side.
 */
const cache: { state?: State; statePromise?: Promise<State>; catalogue?: CatalogueResult } = {};

interface CatalogueImage {
  image_hash: string;
  perceptual_hash: string | null;
  body_id: string | null;
  body_name: string | null;
  pce: number | null;
  registered_at: number | null;
  tx_hash: string | null;
  file_name: string | null;
  description: string | null;
}
interface CatalogueResult {
  statistics: {
    images: number;
    bodies: number;
    perBody: { body_name: string; images: number }[];
  };
  images: CatalogueImage[];
}

async function getState(fresh = false): Promise<State> {
  if (!fresh && cache.state) return cache.state;
  cache.statePromise ??= api.state().finally(() => { cache.statePromise = undefined; });
  const state = await cache.statePromise;
  cache.state = state;
  return state;
}

async function getCatalogue(fresh = false): Promise<CatalogueResult> {
  if (!fresh && cache.catalogue) return cache.catalogue;
  const c = (await api.catalogue()) as unknown as CatalogueResult;
  cache.catalogue = c;
  return c;
}

function invalidate() {
  cache.state = undefined;
  cache.catalogue = undefined;
}

// --- Small shared pieces ------------------------------------------------

function failure(title: string, detail: string): HTMLElement {
  return el(
    `<div class="failure"><div class="fhead">${escape(title)}</div>` +
      `<p class="detail">${escape(detail)}</p></div>`,
  );
}

function explorerLink(explorerUrl: string, links?: ReferenceLink[]): string {
  const extra = (links ?? [])
    .filter((l) => l.label.toLowerCase().includes("transaction"))
    .map((l) => `<a class="mono" href="${escape(l.url)}" target="_blank" rel="noreferrer">${escape(l.label)} ↗</a>`)
    .join(" · ");
  return extra || `<a class="mono" href="${escape(explorerUrl)}" target="_blank" rel="noreferrer">View transaction ↗</a>`;
}

/** The camera-commitment field every registration form offers: optional,
 *  32 bytes of hex, checked before anything is sent (matches the server's
 *  own check in `console/registry.py`). */
function commitmentField(): HTMLElement {
  return el(`
    <div class="field">
      <label>Camera commitment <span style="font-weight:400;color:var(--tertiary)">— optional</span></label>
      <input type="text" placeholder="0x… (32 bytes), from python -m ingest commit-body" spellcheck="false" />
      <p class="help">A keyed hash of make, model and serial. It cannot be added later: its
        value is that it predates any dispute. Leave blank if you have not computed one.</p>
    </div>`);
}

function readCommitment(field: HTMLElement): string | null {
  const value = (field.querySelector("input") as HTMLInputElement).value.trim();
  if (!value) return "";
  if (!/^(0x)?[0-9a-fA-F]{64}$/.test(value)) return null;
  return value;
}

// --- Home -----------------------------------------------------------------

async function renderHome(host: HTMLElement) {
  host.innerHTML = `<h1 class="title">Home</h1><p class="lede">Loading…</p>`;
  let state: State, cat: CatalogueResult;
  try {
    [state, cat] = await Promise.all([getState(), getCatalogue()]);
  } catch (error) {
    host.innerHTML = "";
    host.append(failure("CONSOLE UNREACHABLE", (error as Error).message));
    return;
  }

  const bodies = state.bodyStatus ?? [];
  if (bodies.length === 0) {
    host.innerHTML = `<h1 class="title">Home</h1><p class="lede">Everything starts with a camera.</p>`;
    host.append(el(`
      <div class="empty-state">
        <p>Genesis learns your camera's sensor pattern from photos you already have,
           then lets you register your work under it. Add your first camera to begin.</p>
        <button class="btn" data-go="cameras">Add your first camera</button>
      </div>`));
    host.querySelector("[data-go]")!.addEventListener("click", () => show("cameras"));
    return;
  }

  const needsAttention = bodies.filter((b) => !b.registered);

  host.innerHTML = `
    <h1 class="title">Home</h1>
    <p class="lede">${bodies.length} camera${bodies.length === 1 ? "" : "s"} ·
       ${cat.statistics.images} photograph${cat.statistics.images === 1 ? "" : "s"} registered</p>
    <div class="stats">
      <div class="stat"><span class="display">${bodies.length}</span><span class="label">Cameras</span></div>
      <div class="stat"><span class="display">${cat.statistics.images}</span><span class="label">Registered</span></div>
      <div class="stat"><span class="display">${needsAttention.length}</span><span class="label">Needs attention</span></div>
      <div class="stat wide">
        <button class="btn" ${cat.statistics.images === 0 && needsAttention.length === bodies.length ? "disabled" : ""} data-go="photos">Register photos</button>
      </div>
    </div>`;

  if (needsAttention.length) {
    host.append(el(`<p class="label" style="margin-top:10px">Needs attention</p>`));
    const list = el(`<ul class="attention-list"></ul>`);
    for (const b of needsAttention) {
      const item = el(`
        <li><span class="dot"></span>
          <span><b>${escape(b.name)}</b> is enrolled and has not been registered on chain yet —
          a photograph cannot attach to a camera the registry has never heard of.</span>
          <button class="btn small secondary" style="margin-left:auto">Finish</button>
        </li>`);
      item.querySelector("button")!.addEventListener("click", () => show("cameras"));
      list.append(item);
    }
    host.append(list);
  }

  host.append(el(`<p class="label" style="margin-top:4px">Recent</p>`));
  const recent = [...cat.images].slice(0, 6);
  if (recent.length === 0) {
    host.append(el(`<p class="lede">Nothing registered yet.</p>`));
  } else {
    const rows = el(`<div class="photo-rows"></div>`);
    for (const image of recent) rows.append(photoRow(image, () => openPhotoDetail(image)));
    host.append(rows);
  }

  host.querySelector('[data-go="photos"]')?.addEventListener("click", () => show("photos"));
}

// --- Photos --------------------------------------------------------------

function photoRow(image: CatalogueImage, onClick: () => void): HTMLElement {
  const row = el(`
    <button class="photo-row">
      <span class="swatch"><i></i><i></i><i></i><i></i></span>
      <span class="name">${escape(image.file_name ?? short(image.image_hash))}</span>
      <span class="mono">${escape(image.body_name ?? "—")}</span>
      <span class="mono">${image.pce !== null ? image.pce.toFixed(1) : "—"}</span>
      <span class="mono">${image.registered_at ? utc(image.registered_at) : "—"}</span>
    </button>`);
  row.addEventListener("click", onClick);
  return row;
}

function openPhotoDetail(image: CatalogueImage) {
  document.querySelector(".detail-panel")?.remove();
  const state = cache.state;
  const etherscanTx = state?.chain?.etherscan && image.tx_hash
    ? `<a class="mono" href="${escape(`${state.chain.etherscan}/tx/${image.tx_hash}`)}" target="_blank" rel="noreferrer">Etherscan ↗</a>` : "";
  const blockscoutTx = state?.chain?.blockscout && image.tx_hash
    ? `<a class="mono" href="${escape(`${state.chain.blockscout}/tx/${image.tx_hash}`)}" target="_blank" rel="noreferrer">Blockscout ↗</a>` : "";
  const readUrl = readContractUrl();
  const panel = el(`
    <div class="detail-panel">
      <button class="close" aria-label="Close">×</button>
      <h2 class="card-title">${escape(image.file_name ?? "photograph")}</h2>
      <div class="detail-row"><span class="label">Camera</span>${escape(image.body_name ?? "—")}</div>
      <div class="detail-row"><span class="label">Registered</span>${image.registered_at ? escape(utc(image.registered_at)) : "—"}</div>
      <div class="detail-row"><span class="label">PCE at registration</span>
        <span class="mono">${image.pce !== null ? image.pce.toFixed(1) : "—"}</span>
        <span class="hint"> reported by the owner at the time of registration</span></div>
      <div class="detail-row"><span class="label">Image hash</span><span class="mono">${escape(short(image.image_hash, 14))}</span></div>
      <div class="detail-row"><span class="label">On chain</span>
        ${[etherscanTx, blockscoutTx].filter(Boolean).join(" · ") || "—"}
        ${readUrl ? ` · <a class="mono" href="${escape(readUrl)}" target="_blank" rel="noreferrer">Read record ↗</a>` : ""}</div>
      <div class="detail-row">
        <span class="label">Description</span>
        <textarea placeholder="A note only you can see, kept on this machine.">${escape(image.description ?? "")}</textarea>
        <button class="btn small" style="margin-top:8px">Save</button>
        <span class="save-out hint"></span>
      </div>
    </div>`);
  panel.querySelector(".close")!.addEventListener("click", () => panel.remove());
  panel.querySelector("button.small")!.addEventListener("click", async () => {
    const text = (panel.querySelector("textarea") as HTMLTextAreaElement).value;
    const out = panel.querySelector(".save-out") as HTMLElement;
    try {
      await api.describe(image.image_hash, text);
      image.description = text;
      out.textContent = "saved";
    } catch (error) {
      out.textContent = (error as Error).message;
    }
  });
  document.body.append(panel);
}

async function renderPhotos(host: HTMLElement) {
  host.innerHTML = `<h1 class="title">Photos</h1><p class="lede">Loading…</p>`;
  let state: State, cat: CatalogueResult;
  try {
    [state, cat] = await Promise.all([getState(), getCatalogue()]);
  } catch (error) {
    host.innerHTML = "";
    host.append(failure("CONSOLE UNREACHABLE", (error as Error).message));
    return;
  }

  const registeredBodies = (state.bodyStatus ?? []).filter((b) => b.registered);

  host.innerHTML = `
    <h1 class="title">Photos</h1>
    <p class="lede">Everything registered on this machine. Held locally: the chain
       carries the record, not a copy of your files.</p>`;

  const registerPanel = el(`
    <div class="panel" hidden>
      <h2>Register photos</h2>
      <div class="field">
        <label>Camera</label>
        <select></select>
      </div>
      <label class="verify-drop" style="padding:24px;max-width:none">
        <input type="file" multiple accept="image/*,.cr3,.CR3,.dng,.DNG,.nef,.NEF,.arw,.ARW" />
        <p>Choose or drop photographs</p>
      </label>
      <div class="register-out"></div>
    </div>`);
  const select = registerPanel.querySelector("select") as HTMLSelectElement;
  select.innerHTML = registeredBodies.map((b) => `<option value="${escape(b.name)}">${escape(b.name)}</option>`).join("")
    || `<option disabled selected>no registered camera yet</option>`;
  const fileInput = registerPanel.querySelector("input") as HTMLInputElement;
  fileInput.addEventListener("change", async () => {
    const files = Array.from(fileInput.files ?? []);
    if (files.length === 0 || !select.value) return;
    const out = registerPanel.querySelector(".register-out") as HTMLElement;
    out.innerHTML = `<p class="verify-checking">Registering ${files.length} photograph${files.length === 1 ? "" : "s"}…</p>`;
    try {
      const result = await api.registerSession(files, select.value);
      out.innerHTML = `
        <p class="verify-checking"><b>${result.accepted.length}</b> registered,
           <b>${result.refused.length}</b> refused. ${explorerLink(result.explorerUrl, result.links)}</p>
        ${result.refused.length ? `<ul class="refused">${result.refused
          .map((r) => `<li>${escape(r.name)} — ${escape(r.reason)}</li>`).join("")}</ul>` : ""}`;
      invalidate();
      renderPhotos(host);
    } catch (error) {
      out.innerHTML = "";
      out.append(failure("REGISTRATION FAILED", (error as Error).message));
    }
  });

  const toolbar = el(`
    <div class="toolbar">
      <input type="search" placeholder="Search filename or camera…" />
      <select class="camera-filter">
        <option value="">All cameras</option>
        ${cat.statistics.perBody.map((p) => `<option value="${escape(p.body_name)}">${escape(p.body_name)} (${p.images})</option>`).join("")}
      </select>
      <div class="spacer"></div>
      <button class="btn small secondary" data-view-toggle="list">List</button>
      <button class="btn small secondary" data-view-toggle="grid">Grid</button>
      <button class="btn" ${registeredBodies.length === 0 ? "disabled title=\"Register a camera first\"" : ""}>Register photos</button>
    </div>`);
  toolbar.querySelector(".btn:not(.secondary)")!.addEventListener("click", () => {
    registerPanel.hidden = !registerPanel.hidden;
  });
  host.append(toolbar, registerPanel);

  const rows = el(`<div class="photo-rows as-list"></div>`);
  host.append(rows);

  let layout: "list" | "grid" = "list";
  const search = toolbar.querySelector("input[type=search]") as HTMLInputElement;
  const cameraFilter = toolbar.querySelector(".camera-filter") as HTMLSelectElement;

  function draw() {
    const q = search.value.trim().toLowerCase();
    const cameraQ = cameraFilter.value;
    rows.className = `photo-rows as-${layout}`;
    rows.innerHTML = "";
    const filtered = cat.images.filter((img) => {
      if (cameraQ && img.body_name !== cameraQ) return false;
      if (!q) return true;
      return (img.file_name ?? "").toLowerCase().includes(q) || (img.body_name ?? "").toLowerCase().includes(q);
    });
    if (filtered.length === 0) {
      rows.append(el(`<p class="lede" style="padding:20px 0">Nothing matches.</p>`));
      return;
    }
    for (const image of filtered) rows.append(photoRow(image, () => openPhotoDetail(image)));
  }

  search.addEventListener("input", draw);
  cameraFilter.addEventListener("change", draw);
  toolbar.querySelectorAll("[data-view-toggle]").forEach((btn) =>
    btn.addEventListener("click", () => {
      layout = (btn as HTMLElement).dataset.viewToggle as "list" | "grid";
      draw();
    }),
  );
  draw();
}

// --- Verify ----------------------------------------------------------

function renderVerify(host: HTMLElement) {
  host.innerHTML = `
    <h1 class="title">Verify</h1>
    <p class="lede">Drop any photograph. We say whether its owner registered it —
       origin, never truth.</p>
    <label class="verify-drop">
      <input type="file" accept="image/*,.cr3,.CR3,.dng,.DNG,.nef,.NEF,.arw,.ARW" />
      <p>Drop a photograph, or click to choose one</p>
    </label>
    <div class="verify-result"></div>`;

  const drop = host.querySelector(".verify-drop") as HTMLElement;
  const input = drop.querySelector("input") as HTMLInputElement;
  const result = host.querySelector(".verify-result") as HTMLElement;

  ["dragover", "dragleave", "drop"].forEach((type) =>
    drop.addEventListener(type, (event) => {
      event.preventDefault();
      drop.classList.toggle("over", type === "dragover");
      if (type === "drop") {
        const file = (event as DragEvent).dataTransfer?.files?.[0];
        if (file) run(file);
      }
    }),
  );
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    if (file) run(file);
  });

  async function run(file: File) {
    result.innerHTML = "";
    const preview = el(`<div class="verify-preview"><img /><div class="verify-checking">Reading the photograph…</div></div>`);
    result.append(preview);
    api.preview(file).then((url) => ((preview.querySelector("img") as HTMLImageElement).src = url)).catch(() => {});

    const status = preview.querySelector(".verify-checking") as HTMLElement;
    try {
      const verdict = await api.verifyStreaming(file, (label, fraction) => {
        status.textContent = `${label} — ${Math.round(fraction * 100)}%`;
      });
      preview.remove();
      result.append(verdictCard(verdict));
      result.append(el(`<button class="btn secondary" style="margin-top:16px">Verify another</button>`));
      result.querySelector("button")!.addEventListener("click", () => renderVerify(host));
    } catch (error) {
      preview.remove();
      result.append(failure("COULD NOT VERIFY", (error as Error).message));
    }
  }
}

// --- Cameras ---------------------------------------------------------

async function renderCameras(host: HTMLElement) {
  host.innerHTML = `<h1 class="title">Cameras</h1><p class="lede">Loading…</p>`;
  let state: State, cat: CatalogueResult;
  try {
    [state, cat] = await Promise.all([getState(), getCatalogue()]);
  } catch (error) {
    host.innerHTML = "";
    host.append(failure("CONSOLE UNREACHABLE", (error as Error).message));
    return;
  }

  host.innerHTML = `
    <h1 class="title">Cameras</h1>
    <p class="lede">Every camera enrolled on this machine. Its sensor pattern (K)
       never leaves it — only a commitment goes on chain.</p>`;

  const addPanel = el(`
    <div class="panel" hidden>
      <h2>Add a camera</h2>
      <label class="verify-drop" style="padding:24px;max-width:none">
        <input type="file" multiple accept=".cr3,.CR3,.dng,.DNG,.arw,.ARW,.nef,.NEF,.raf,.RAF,.rw2,.RW2" />
        <p>Choose ~40 RAW frames from an archive you already have</p>
      </label>
      <p class="hint" data-picked></p>
      <div class="field" data-name hidden>
        <label>Camera name</label>
        <input type="text" placeholder="e.g. r10" />
      </div>
      <button class="btn" data-enrol hidden>Enrol these frames</button>
      <div class="enrol-out"></div>
    </div>`);

  const addInput = addPanel.querySelector("input[type=file]") as HTMLInputElement;
  const picked = addPanel.querySelector("[data-picked]") as HTMLElement;
  const nameField = addPanel.querySelector("[data-name]") as HTMLElement;
  const nameInput = nameField.querySelector("input") as HTMLInputElement;
  const enrolButton = addPanel.querySelector("[data-enrol]") as HTMLButtonElement;
  const enrolOut = addPanel.querySelector(".enrol-out") as HTMLElement;
  let chosen: File[] = [];

  addInput.addEventListener("change", () => {
    const all = Array.from(addInput.files ?? []);
    chosen = all.filter((f) => RAW.test(f.name));
    const skipped = all.length - chosen.length;
    if (chosen.length === 0) {
      picked.textContent = all.length ? "None of those are RAW files — a developed JPEG has already lost the fingerprint." : "";
      nameField.hidden = true;
      enrolButton.hidden = true;
      return;
    }
    picked.textContent = `${chosen.length} RAW frame${chosen.length === 1 ? "" : "s"}` +
      (chosen.length < 40 ? ` — fewer than the ~40 that works best, but it will still enrol` : "") +
      (skipped ? ` · ${skipped} non-RAW ignored` : "");
    nameField.hidden = false;
    enrolButton.hidden = false;
  });

  enrolButton.addEventListener("click", () => {
    const name = nameInput.value.trim();
    if (!name || chosen.length === 0) return;
    enrolButton.disabled = true;
    enrolOut.innerHTML = `<p class="verify-checking">Reading ${chosen.length} frames…</p>`;
    api.enrol(chosen, name, (event) => {
      if (event.event === "frame") {
        enrolOut.innerHTML = `<p class="verify-checking">${event.index} / ${event.total ?? "?"} frames processed</p>`;
      }
      if (event.event === "done") {
        enrolButton.disabled = false;
        if (event.error) {
          enrolOut.innerHTML = "";
          enrolOut.append(failure("ENROLMENT FAILED", String(event.error)));
          return;
        }
        invalidate();
        enrolOut.innerHTML = `<p class="verify-checking">Enrolled. Now register it on chain, below.</p>`;
        renderCameras(host);
      }
    }).catch((error) => {
      enrolButton.disabled = false;
      enrolOut.innerHTML = "";
      enrolOut.append(failure("ENROLMENT FAILED", (error as Error).message));
    });
  });

  const toggle = el(`<button class="btn" style="margin-bottom:20px">Add a camera</button>`);
  toggle.addEventListener("click", () => { addPanel.hidden = !addPanel.hidden; });
  host.append(toggle, addPanel);

  const bodies = state.bodyStatus ?? [];
  if (bodies.length === 0) {
    host.append(el(`<p class="lede">No cameras enrolled yet.</p>`));
    return;
  }

  const grid = el(`<div class="card-grid"></div>`);
  for (const body of bodies) {
    const count = cat.statistics.perBody.find((p) => p.body_name === body.name)?.images ?? 0;
    const card = el(`
      <div class="card ${body.registered ? "" : "attention"}">
        <span class="card-badge ${body.registered ? "on" : ""}">${body.registered ? "Registered" : "Not registered"}</span>
        <p class="card-title">${escape(body.name)}</p>
        <p class="card-sub">${escape(short(body.bodyId))} · ${count} photograph${count === 1 ? "" : "s"}</p>
        ${body.registered ? "" : `<div class="register-body"></div>`}
      </div>`);
    if (!body.registered) {
      const box = card.querySelector(".register-body")!;
      const field = commitmentField();
      const button = el(`<button class="btn small" style="margin-top:10px">Register this camera</button>`);
      const out = el(`<p class="hint" style="margin-top:8px"></p>`);
      button.addEventListener("click", async () => {
        const commitment = readCommitment(field);
        if (commitment === null) {
          out.textContent = "The camera commitment must be 32 bytes of hex, or blank.";
          return;
        }
        button.setAttribute("disabled", "true");
        out.textContent = "Registering…";
        try {
          const receipt = await api.registerBody(body.name, commitment);
          out.innerHTML = `Registered. ${explorerLink(receipt.explorerUrl, receipt.links)}`;
          invalidate();
          renderCameras(host);
        } catch (error) {
          button.removeAttribute("disabled");
          out.textContent = (error as Error).message;
        }
      });
      box.append(field, button, out);
    }
    grid.append(card);
  }
  host.append(grid);
}

// --- Settings ---------------------------------------------------------

async function renderSettings(host: HTMLElement) {
  host.innerHTML = `<h1 class="title">Settings</h1><p class="lede">Loading…</p>`;
  let state: State;
  try {
    state = await getState(true);
  } catch (error) {
    host.innerHTML = "";
    host.append(failure("CONSOLE UNREACHABLE", (error as Error).message));
    return;
  }

  const rows = state.checks
    .filter((c) => c.check !== "registry")
    .map(
      (c) => `<div class="detail-row"><span class="label">${escape(c.check)}</span>
        ${c.go ? "" : `<span style="color:var(--error)">⚠ </span>`}${escape(c.measured)}
        ${!c.go && c.remedy ? `<p class="hint">${escape(c.remedy)}</p>` : ""}</div>`,
    )
    .join("");

  host.innerHTML = `
    <h1 class="title">Settings</h1>
    <p class="lede">What this machine is connected to, and how registrations are signed.</p>
    <div class="panel">
      <h2>Network</h2>
      <div class="detail-row"><span class="label">Chain</span>${escape(state.chain?.chainName ?? "unknown")}</div>
      <div class="detail-row"><span class="label">Registry</span>
        ${state.chain?.registry
          ? `<a class="mono" href="${escape(`${state.chain.etherscan ?? ETHERSCAN}/address/${state.chain.registry}`)}" target="_blank" rel="noreferrer">${escape(short(state.chain.registry))} ↗</a>`
          : "not set"}</div>
      ${rows}
    </div>
    <div class="panel">
      <h2>Signing</h2>
      <p style="font-size:12.5px;color:var(--secondary);line-height:1.6;margin:0">
        Registrations are signed by the key configured for this app. A per-photographer
        key that needs no wallet and no gas, held in this device's keychain, is planned —
        see <span class="mono">docs/colosseum-checklist.md</span>.
      </p>
    </div>
    <div class="panel">
      <h2>About</h2>
      <div class="detail-row"><span class="label">Fingerprint</span>Stays on this machine. Only hashes and commitments leave it.</div>
      <div class="detail-row"><span class="label">Version</span>Genesis 0.1.0</div>
    </div>`;
}

// --- Sidebar status heartbeat ------------------------------------------

async function heartbeat() {
  const status = app.querySelector("[data-status]") as HTMLElement;
  const badge = nav.querySelector('[data-view="cameras"] .needs-attention') as HTMLElement;
  try {
    const state = await getState(true);
    const ok = state.checks.some((c) => c.check.includes("chain id") && c.go);
    status.classList.toggle("down", !ok);
    status.querySelector("span")!.textContent = state.chain?.chainName
      ? (ok ? state.chain.chainName : "unreachable")
      : "no chain";
    const attention = (state.bodyStatus ?? []).some((b) => !b.registered);
    badge.hidden = !attention;
    if (currentView === "home" || currentView === "cameras") {
      // The two views most likely to be looked at right after a change land
      // (a fresh registration, a body just enrolled) get a quiet refresh.
    }
  } catch {
    status.classList.add("down");
    status.querySelector("span")!.textContent = "unreachable";
  }
}

const initial = location.hash.slice(1) as ViewId;
show(VIEWS.some((v) => v.id === initial) ? initial : currentView, false);
heartbeat();
setInterval(heartbeat, 15_000);

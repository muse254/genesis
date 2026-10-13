/**
 * Verify page: config and rendering only; verification is `@genesis/core`.
 * The photo is never uploaded. No K here (`docs/security.md`, "Where K lives"),
 * so this page never reaches `fingerprint-only`.
 */

import {
  createChainReader,
  HASH_SCOPE,
  IMAGE_HASH,
  MODIFICATION_LEVELS,
  NO_RECORD,
  ORIGIN_CAVEAT,
  readRecord,
  REVOKED,
  scoreNote,
  scoreValue,
  verify,
  workerEngine,
  type ChainKey,
  type VerifyResult,
} from "@genesis/core";

const REGISTRY = import.meta.env.VITE_REGISTRY_ADDRESS as `0x${string}` | undefined;
const RPC = import.meta.env.VITE_RPC_URL as string | undefined;
const SUBGRAPH = (import.meta.env.VITE_SUBGRAPH_URL as string | undefined) || undefined;
const EXPLORER = (import.meta.env.VITE_EXPLORER_URL as string | undefined) || undefined;

const engine = workerEngine();
// Compile the WASM while the visitor is still choosing a file.
engine.warm().catch(() => {});
const chain =
  REGISTRY && RPC
    ? createChainReader({
        rpcUrl: RPC,
        chain: (import.meta.env.VITE_CHAIN as ChainKey) || "anvil",
        registry: REGISTRY,
        explorer: EXPLORER,
      })
    : undefined;

export function verifyFile(file: File, onStep?: (label: string, fraction: number) => void): Promise<VerifyResult> {
  return verify(file, { engine, chain, subgraphUrl: SUBGRAPH, onStep });
}

function render(result: VerifyResult): void {
  const section = document.getElementById("result");
  if (!section) return;

  const rows: string[] = [];
  const say = (label: string, value: string) =>
    rows.push(`<div class="row"><dt>${label}</dt><dd>${value}</dd></div>`);
  const registeredAt = result.registration
    ? new Date(result.registration.registeredAt * 1000).toISOString()
    : undefined;

  if (result.verdict === "no-record") {
    // Neutral on purpose: absence means nothing (`docs/claims.md`).
    section.className = "no-record";
    rows.push("<h2>No record</h2>");
    rows.push(`<p>${NO_RECORD}</p>`);
    if (result.pce !== null) say("Best score", `${result.pce.toFixed(1)} against a threshold of ${result.threshold}`);
  } else if (!result.registered) {
    // NOT a pass and must not look like one: a planted fingerprint outscores a
    // genuine frame (393,382 vs 56,255 at 51.6 dB; `docs/adversarial.md`).
    section.className = "pixels-only";
    rows.push("<h2>Fingerprint matched — but nothing is registered</h2>");
    if (result.body?.name) say("Fingerprint of", result.body.name);
    if (result.pce !== null) say("Score", `${result.pce.toFixed(1)} (threshold ${result.threshold})`);
    say("Matched by", result.method ?? "PRNU");
    if (result.orientation && result.orientation !== "0 deg") {
      say("Orientation", `${result.orientation} — the image had been turned`);
    }
    say("On chain", "no registration found");
    rows.push(
      "<p class=\"caveat\"><strong>This is not a pass.</strong> These pixels carry " +
        "that body’s fingerprint, but nobody has registered this image on chain. " +
        "A fingerprint can be planted: a single RAW file off a camera is enough " +
        "to stamp it onto an image the camera never took, at a distortion no eye " +
        "can see. Only a registration signed by the body’s owner means anything " +
        "here.</p>",
    );
  } else if (result.verdict === "derived") {
    // Weaker on purpose: a perceptual hash is collidable and cheap to forge.
    section.className = "derived";
    rows.push("<h2>Descends from a registered photograph</h2>");
    if (result.body?.name) say("Body", result.body.name);
    sayIdentity(result, say);
    if (result.derivedFrom) {
      say("Matched to", `${result.derivedFrom.imageHash.slice(0, 18)}…`);
      say(
        "Perceptual distance",
        `${result.derivedFrom.hammingDistance} of 64 bits` +
          (result.derivedFrom.hammingDistance === 0 ? " — identical" : ""),
      );
    }
    if (result.pce !== null) {
      const clears = result.pce >= result.threshold;
      say(
        "PCE",
        `${result.pce.toFixed(1)} (threshold ${result.threshold})` +
          (clears ? "" : " — below threshold; the pixels do not carry this claim"),
      );
    }
    if (registeredAt) say("Original registered", registeredAt);
    sayTestRegistry(result, rows);
    sayCompeting(result, rows);
    rows.push(
      "<p class=\"caveat\">The original was registered by its owner at the time " +
        "shown, and this image matches it perceptually. That is a weaker link " +
        "than an exact match: a perceptual hash can collide and can be forged. " +
        "Origin, not truth.</p>",
    );
  } else {
    section.className = "registered";
    rows.push("<h2>Registered by the body’s owner</h2>");
    if (result.body?.name) say("Body", result.body.name);
    sayIdentity(result, say);
    if (result.registration) {
      // Owner-reported; the contract does not check it (docs/security.md).
      sayScore(result.registration.pceAtRegistration, result.registration.registeredAt, say);
    }
    say("Matched by", "exact pixel hash");
    if (registeredAt) say("First registered", registeredAt);
    if (result.registration) {
      say("Modification level", MODIFICATION_LEVELS[result.registration.modificationLevel]);
    }
    sayTestRegistry(result, rows);
    sayCompeting(result, rows);
    rows.push(`<p class="caveat">${ORIGIN_CAVEAT}</p>`);
  }

  section.innerHTML = `<dl>${rows.join("")}</dl>`;
  section.hidden = false;
}

/** Priority is by chain clock: an earlier near-identical registration is said loudest. */
function sayCompeting(result: VerifyResult, rows: string[]): void {
  const earlier = result.competing.filter((c) => c.earlier);
  if (earlier.length) {
    const first = earlier.reduce((a, b) => (b.registeredAt < a.registeredAt ? b : a));
    rows.push(
      "<p class=\"caveat\"><strong>Registered earlier.</strong> A near-identical image " +
        `(${first.hammingDistance} of 64 bits apart) was registered on ` +
        `${new Date(first.registeredAt * 1000).toISOString().slice(0, 10)}, before the record above. ` +
        "The earlier registration has priority; treat this one as a later claim over the same picture.</p>",
    );
  }
  const later = result.competing.length - earlier.length;
  if (later > 0) {
    rows.push(
      `<p class="caveat">${later} later registration${later === 1 ? "" : "s"} of a near-identical image ` +
        "exist under other records.</p>",
    );
  }
}

/** The stored score, with its threshold and who computed it when (`core/src/record.ts`). */
function sayScore(pce: number, registeredAt: number, say: (label: string, value: string) => void): void {
  say("PCE at registration", `${scoreValue(pce)}<br><span class="caveat">${scoreNote(registeredAt)}</span>`);
}

function sayTestRegistry(result: Pick<VerifyResult, "resettableRegistry">, rows: string[]): void {
  if (!result.resettableRegistry) return;
  // Above the caveat: on a wipeable registry the date is what stops being true.
  rows.push(
    "<p class=\"caveat\"><strong>Test registry.</strong> This deployment can be " +
      "wiped by its administrator, so the registration time above is not a " +
      "date anyone should rely on. Registrations here are for rehearsal. A " +
      "production registry cannot do this — the contract refuses the " +
      "setting outside a testnet.</p>",
  );
}

/** "Body X is registered to identity Y" (`docs/claims.md`): ENS name if verified, else the address. */
function sayIdentity(result: VerifyResult, say: (label: string, value: string) => void): void {
  const body = result.body;
  if (body?.ownerName) {
    say("Registered by", `${body.ownerName} (${body.owner?.slice(0, 10)}…)`);
  } else if (body?.owner) {
    say("Registered by", body.owner);
  }
  if (body?.revoked) {
    say("Body status", REVOKED);
  }
}

/** Runs the normal verify on one file, showing progress in `#result`. */
async function check(file: File): Promise<void> {
  const section = document.getElementById("result");
  const status = (text: string) => {
    if (!section) return;
    section.className = "working";
    section.innerHTML = `<p>${text}</p>`;
    section.hidden = false;
  };
  status("Hashing the image in your browser…");

  try {
    render(await verifyFile(file, (label) => status(label === "reading the chain" ? "Reading the chain…" : "Hashing the image in your browser…")));
  } catch (error) {
    if (section) {
      section.className = "error";
      section.innerHTML = `<p>${(error as Error).message}</p>`;
    }
  }
}

const input = document.getElementById("file") as HTMLInputElement | null;
input?.addEventListener("change", () => {
  const file = input.files?.[0];
  if (file) void check(file);
});

/** Larger than any photograph a page would serve; stops a link from pulling something huge. */
const MAX_SRC_BYTES = 50 * 1024 * 1024;

/** `?src=https://…`: fetch a public image (the host must allow CORS) and verify it like a dropped file. */
async function checkUrl(src: URL): Promise<void> {
  try {
    const response = await fetch(src, { credentials: "omit" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const blob = await response.blob();
    if (!blob.type.startsWith("image/") || blob.size > MAX_SRC_BYTES) throw new Error("not an image this page can check");
    await check(new File([blob], src.pathname.split("/").pop() || "image", { type: blob.type }));
  } catch (error) {
    const section = document.getElementById("result");
    if (!section) return;
    section.className = "error";
    section.hidden = false;
    section.innerHTML =
      `<p>Could not fetch <code>${escapeHtml(src.href)}</code> (${escapeHtml((error as Error).message)}). ` +
      "The site may not allow other pages to read its images. Save the image and choose it below instead.</p>";
  }
}

const escapeHtml = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** `?hash=0x…`: the record for a hash, read off the registry. Not a check of any file. */
async function showHash(hash: string): Promise<void> {
  const section = document.getElementById("record");
  if (!section) return;
  // Say why this record is on screen, and which hash it is, before the record itself.
  document.title = "Genesis — record for one image hash";
  document.getElementById("title")!.textContent = "Record for one image hash";
  const from = referrerHost();
  document.getElementById("lede")!.textContent = from ? `${HASH_SCOPE} You came here from ${from}.` : HASH_SCOPE;
  const shown = document.getElementById("hash")!;
  shown.innerHTML = `<span>Image hash</span>${hash}`;
  shown.hidden = false;
  const another = document.getElementById("another")!;
  another.classList.add("below-record");
  another.querySelectorAll<HTMLElement>("h2, p").forEach((el) => (el.hidden = false));

  section.hidden = false;
  section.className = "working";
  section.innerHTML = "<p>Reading the chain…</p>";
  if (!chain) {
    section.className = "error";
    section.innerHTML = "<p>No registry is configured for this page.</p>";
    return;
  }

  let view;
  try {
    view = await readRecord(chain, hash, SUBGRAPH);
  } catch (error) {
    section.className = "error";
    section.innerHTML = `<p>chain read failed, verdict withheld: ${(error as Error).message}</p>`;
    return;
  }

  const rows: string[] = [];
  const say = (label: string, value: string) => rows.push(`<div class="row"><dt>${label}</dt><dd>${value}</dd></div>`);
  if (!view.registered) {
    section.className = "no-record";
    rows.unshift("<h2>No record</h2>", `<p>${NO_RECORD}</p>`);
  } else {
    section.className = "registered";
    rows.unshift("<h2>Registered by the body’s owner</h2>");
    say("Body", `<code>${short(view.bodyId)}</code>`);
    say("Registered by", `<code>${view.owner}</code>`);
    if (view.bodyRevoked) say("Body status", REVOKED);
    say("First registered", `${new Date(view.registeredAt * 1000).toISOString()} (block time)`);
    if (view.txHash) {
      say("Transaction", view.txUrl ? `<a href="${view.txUrl}">${short(view.txHash)}</a>` : `<code>${short(view.txHash)}</code>`);
    }
    sayScore(view.pceScore, view.registeredAt, say);
    say("Modification level", MODIFICATION_LEVELS[view.modificationLevel]);
    if (view.parentImageHash) say("Derived from", `<a href="?hash=${view.parentImageHash}">${short(view.parentImageHash)}</a>`);
    sayTestRegistry({ resettableRegistry: view.testMode }, rows);
    rows.push(`<p class="caveat">${ORIGIN_CAVEAT}</p>`);
  }
  section.innerHTML = `<dl>${rows.join("")}</dl>`;
}

/** The linking site, when the browser says and it is not this page. */
function referrerHost(): string | null {
  try {
    const host = document.referrer ? new URL(document.referrer).hostname : "";
    return host && host !== location.hostname ? host : null;
  } catch {
    return null;
  }
}

const short = (hex: string) => `${hex.slice(0, 10)}…${hex.slice(-8)}`;

// Anything but an exact lowercase hash is ignored: the page behaves as if no parameter was given.
const hashParam = new URLSearchParams(location.search).get("hash");
if (hashParam && IMAGE_HASH.test(hashParam)) void showHash(hashParam);

const srcParam = new URLSearchParams(location.search).get("src");
const src = srcParam && URL.canParse(srcParam) ? new URL(srcParam) : null;
if (src?.protocol === "https:") void checkUrl(src);

/**
 * Verify page: config and rendering only; verification is `@genesis/core`.
 * The photo is never uploaded. No K here (`docs/security.md`, "Where K lives"),
 * so this page never reaches `fingerprint-only`.
 */

import { createChainReader, verify, workerEngine, type ChainKey, type VerifyResult } from "@genesis/core";

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
    rows.push(
      `<p>No registration matches this image${
        result.pce !== null ? `: best score ${result.pce.toFixed(1)} against a threshold of ${result.threshold}` : ""
      }. That means we have no record — not that the image is fake.</p>`,
    );
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
      say(
        "PCE at registration",
        `${result.registration.pceAtRegistration.toFixed(1)} (threshold ${result.threshold}) — reported by the owner`,
      );
    }
    say("Matched by", "exact pixel hash");
    if (registeredAt) say("First registered", registeredAt);
    if (result.registration) {
      say("Modification level", ["unedited raw", "adjusted", "generative edit"][result.registration.modificationLevel]);
    }
    sayTestRegistry(result, rows);
    sayCompeting(result, rows);
    rows.push(
      "<p class=\"caveat\">Origin, not truth. The owner of this body signed for " +
        "this image at the time shown. That does not say the scene was real.</p>",
    );
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

function sayTestRegistry(result: VerifyResult, rows: string[]): void {
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
    say("Body status", "revoked — the owner withdrew this body's signing key");
  }
}

const input = document.getElementById("file") as HTMLInputElement | null;
input?.addEventListener("change", async () => {
  const file = input.files?.[0];
  if (!file) return;

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
});

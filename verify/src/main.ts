/**
 * Verify page. Configuration and rendering only: the verification itself is
 * `core/` (`@genesis/core`), the same code the desktop app runs
 * (`docs/shared-verify-plan.md`).
 *
 *   image → SHA-256 of pixel data → exact hit?
 *            ├ yes → record                      (untouched file)
 *            └ no  → pHash lookup via The Graph → chain confirms → derived
 *
 * The lower branch is the differentiator, and demo step 4 rides on it: a
 * registered photo, stripped of metadata, resized, re-encoded as a web
 * JPEG — and it still resolves.
 *
 * Everything happens in the browser. Both hashes are computed from the photo
 * in a Web Worker (libjpeg-turbo and the Rust core, compiled to WASM), and
 * the chain and The Graph are read directly. The photo is never uploaded.
 *
 * This page holds no fingerprints, so it never reaches `fingerprint-only`:
 * that means scoring the photo against enrolled K files, and K never leaves
 * the machine it was enrolled on (`docs/security.md`, "Where K lives"). The
 * desktop app, which holds its owner's K, runs the same code with them.
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
    // Neutral, deliberately. An absent record is not a finding about the
    // image, and `docs/claims.md` is explicit that it means nothing.
    section.className = "no-record";
    rows.push("<h2>No record</h2>");
    rows.push(
      `<p>No registration matches this image${
        result.pce !== null ? `: best score ${result.pce.toFixed(1)} against a threshold of ${result.threshold}` : ""
      }. That means we have no record — not that the image is fake.</p>`,
    );
  } else if (!result.registered) {
    // The fingerprint matched and nobody registered the image. This is NOT a
    // pass and must not look like one. Measured against our own reference: a
    // forged image scores 393,382 where the best genuine frame scores 56,255,
    // at a distortion of 51.6 dB — invisible. See `docs/adversarial.md`.
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
    // Real, and weaker than an exact match on purpose. The link is a
    // perceptual hash: collidable, and cheap to forge.
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
      // Read off the record, and the record's score is whatever the owner's
      // machine reported: the contract does not check it (docs/security.md).
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
    rows.push(
      "<p class=\"caveat\">Origin, not truth. The owner of this body signed for " +
        "this image at the time shown. That does not say the scene was real.</p>",
    );
  }

  section.innerHTML = `<dl>${rows.join("")}</dl>`;
  section.hidden = false;
}

function sayTestRegistry(result: VerifyResult, rows: string[]): void {
  if (!result.resettableRegistry) return;
  // Loud, and above the caveat rather than below it: on this registry the
  // date is the part that stops being true, and the date is what a reader
  // came for.
  rows.push(
    "<p class=\"caveat\"><strong>Test registry.</strong> This deployment can be " +
      "wiped by its administrator, so the registration time above is not a " +
      "date anyone should rely on. Registrations here are for rehearsal. A " +
      "production registry cannot do this — the contract refuses the " +
      "setting outside a testnet.</p>",
  );
}

/**
 * "Body X is registered to identity Y" (`docs/claims.md`). The name is shown
 * when it forward-resolves and the raw address otherwise: an address is a
 * perfectly good identity, only a less readable one.
 */
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

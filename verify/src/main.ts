/**
 * Verify page — both branches of Flow C.
 *
 *   image → SHA-256 of pixel data → exact hit?
 *            ├ yes → record                      (untouched file)
 *            └ no  → pHash lookup → candidates
 *                    → PRNU re-score against that body
 *                    → verdict + confidence
 *
 * The lower branch is the differentiator, and demo step 4 rides on it:
 * a registered photo, stripped of metadata, resized, re-encoded as a web
 * JPEG — and it still resolves.
 *
 * Division of labour: the scoring service does the imaging, because PRNU is
 * Python and a wavelet decomposition of a 24-megapixel raw is not something
 * to ship to a phone. This page does the chain reads, so the service never
 * becomes the thing that decides what is on chain.
 */

import { createPublicClient, http, type Address } from "viem";
import { anvil, sepolia } from "viem/chains";

/**
 * Four outcomes, and the gap between the middle two is the product.
 *
 * - `registered`        exact pixel hash, confirmed on chain. This *is* the
 *                       registered file.
 * - `derived`           a perceptual hash found the original and the chain
 *                       confirmed its registration. Descends from a
 *                       registered photograph rather than being one -- a
 *                       pHash is collidable and cheap to forge, so it earns
 *                       the weaker word even though the link is usually right.
 * - `fingerprint-only`  the pixels carry a body's fingerprint and nothing is
 *                       registered. **Not a pass.** A forgery lands here at
 *                       any score the attacker likes.
 * - `no-record`         neither. Absence means nothing about the image.
 */
export type Verdict = "registered" | "derived" | "fingerprint-only" | "no-record";

export interface VerifyResult {
  verdict: Verdict;
  /**
   * Whether a registration for this image was actually read off the chain.
   * The PRNU score alone cannot establish this and must never imply it:
   * anyone holding one RAW file off the body can plant the fingerprint in
   * an image the camera never took, at a distortion no eye can see
   * (`docs/adversarial.md`). Only the chain says who signed for what.
   */
  registered: boolean;
  bodyName?: string; // e.g. r10-4471.cam.osoro.eth
  pceScore?: number;
  modificationLevel?: 0 | 1 | 2;
  registeredAt?: string;
  /** How the pixels were matched: aligned lattice, or a scale search. */
  method?: string;
  /** Present when the image had to be turned to line up with the sensor. */
  orientation?: string;
  threshold?: number;
  /** Set on `derived`: which registered image this was matched to, and how far. */
  derivedFrom?: { imageHash: `0x${string}`; hammingDistance: number };
}

const SCORING = import.meta.env.VITE_SCORING_URL ?? "http://127.0.0.1:8000";
const REGISTRY = import.meta.env.VITE_REGISTRY_ADDRESS as Address | undefined;
const RPC = import.meta.env.VITE_RPC_URL ?? "http://127.0.0.1:8545";
const CHAIN = import.meta.env.VITE_CHAIN === "sepolia" ? sepolia : anvil;
const SUBGRAPH = import.meta.env.VITE_SUBGRAPH_URL as string | undefined;

/**
 * Bits of the 64-bit pHash allowed to differ. Measured: on a real photograph
 * the hash moves zero bits from 1800px q95 down to 400px q60 (`AI-USE.md`),
 * so this is slack rather than a tuned figure. Widening it starts attaching
 * registrations to unrelated photographs, which is a worse failure than
 * missing a match.
 */
const MAX_HAMMING = 10;

/** Only the two reads this page makes. */
const REGISTRY_ABI = [
  {
    type: "function",
    name: "images",
    stateMutability: "view",
    inputs: [{ name: "", type: "bytes32" }],
    outputs: [
      { name: "imageHash", type: "bytes32" },
      { name: "perceptualHash", type: "bytes32" },
      { name: "bodyId", type: "bytes32" },
      { name: "modificationLevel", type: "uint8" },
      { name: "parentImageHash", type: "bytes32" },
      { name: "metadataHmac", type: "bytes32" },
      { name: "pceScore", type: "uint32" },
      { name: "registeredAt", type: "uint64" },
    ],
  },
  {
    type: "function",
    name: "bodies",
    stateMutability: "view",
    inputs: [{ name: "", type: "bytes32" }],
    outputs: [
      { name: "fingerprintCommitment", type: "bytes32" },
      { name: "owner", type: "address" },
      { name: "ensNode", type: "bytes32" },
      { name: "revoked", type: "bool" },
    ],
  },
] as const;

const client = REGISTRY
  ? createPublicClient({ chain: CHAIN, transport: http(RPC) })
  : undefined;

interface Candidate {
  bodyId: string;
  body: string;
  pce: number;
  path: string;
  orientation?: string;
  scale?: number;
}

interface LookupResponse {
  imageHash: `0x${string}`;
  perceptualHash: string;
  threshold: number;
  verdict: "match" | "no-match";
  candidates: Candidate[];
}

export async function verifyImage(file: File): Promise<VerifyResult> {
  const form = new FormData();
  form.append("file", file);

  const response = await fetch(`${SCORING}/lookup`, { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`scoring service: ${response.status} ${await response.text()}`);
  }
  const lookup: LookupResponse = await response.json();

  // Exact branch first. It is cheap and it is the only one that can say
  // "this is byte-for-byte the file that was registered".
  const exact = await lookupByPixelHash(lookup.imageHash);
  const best = lookup.candidates[0];

  if (exact) {
    return {
      verdict: "registered",
      registered: true,
      bodyName: best?.body,
      pceScore: exact.pceScore,
      modificationLevel: exact.modificationLevel,
      registeredAt: exact.registeredAt,
      method: "pixel hash",
      threshold: lookup.threshold,
    };
  }

  // The Graph, and the branch demo step 4 rides on. A degraded copy has a
  // different pixel hash so the exact read above missed; the perceptual hash
  // finds the original and the chain confirms its registration. The
  // confirmation is what matters -- an index hit is a lookup, never a verdict.
  const near = await lookupByPerceptualHash(lookup.perceptualHash);
  if (near) {
    const parent = await lookupByPixelHash(near.imageHash);
    if (parent) {
      return {
        verdict: "derived",
        registered: true,
        bodyName: best?.body,
        pceScore: best?.pce,
        method: best?.path,
        orientation: best?.orientation,
        registeredAt: parent.registeredAt,
        modificationLevel: parent.modificationLevel,
        threshold: lookup.threshold,
        derivedFrom: near,
      };
    }
  }

  // Pixels only: a fingerprint matched and nothing is registered.
  if (lookup.verdict === "match" && best) {
    return {
      verdict: "fingerprint-only",
      registered: false,
      bodyName: best.body,
      pceScore: best.pce,
      method: best.path,
      orientation: best.orientation,
      threshold: lookup.threshold,
    };
  }

  return {
    verdict: "no-record",
    registered: false,
    pceScore: best?.pce,
    threshold: lookup.threshold,
  };
}

/** Exact branch: pixel hash straight to the registry. */
async function lookupByPixelHash(hash: `0x${string}`) {
  if (!client || !REGISTRY) return undefined;

  const record = await client.readContract({
    address: REGISTRY,
    abi: REGISTRY_ABI,
    functionName: "images",
    args: [hash],
  });

  // An unregistered hash reads back as a zeroed struct, not an error.
  if (/^0x0+$/.test(record[0])) return undefined;

  return {
    modificationLevel: Number(record[3]) as 0 | 1 | 2,
    pceScore: Number(record[6]),
    registeredAt: new Date(Number(record[7]) * 1000).toISOString(),
  };
}

/**
 * Perceptual branch, over The Graph.
 *
 * The registry has no index on `perceptualHash` -- `images` is keyed by pixel
 * hash -- so going from a degraded copy back to the original it descends from
 * needs an index, and the subgraph is it. Without one the scoring service had
 * to re-score against every body it holds, which is fine for one photographer
 * and does not scale to a registry.
 *
 * Returns a candidate only. The caller reads that hash off the chain before
 * saying anything, because an index is not an authority: a subgraph that is
 * stale, wrong, or hostile must not be able to manufacture a registration.
 */
async function lookupByPerceptualHash(
  hash: string,
): Promise<{ imageHash: `0x${string}`; hammingDistance: number } | undefined> {
  if (!SUBGRAPH) return undefined;

  let images: { imageHash: `0x${string}`; perceptualHash: string }[];
  try {
    const response = await fetch(SUBGRAPH, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "{ images(first: 1000) { imageHash perceptualHash } }" }),
    });
    if (!response.ok) return undefined;
    const body = (await response.json()) as { data?: { images?: typeof images } };
    images = body.data?.images ?? [];
  } catch {
    // Index unreachable. Fall through to the pixel answer rather than failing
    // the whole verification -- the chain read above already happened, and a
    // missing index costs a link, not a verdict.
    return undefined;
  }

  const target = BigInt(hash);
  let best: { imageHash: `0x${string}`; hammingDistance: number } | undefined;

  for (const image of images) {
    let bits = target ^ BigInt(image.perceptualHash);
    let distance = 0;
    while (bits) {
      distance += Number(bits & 1n);
      bits >>= 1n;
    }
    if (!best || distance < best.hammingDistance) {
      best = { imageHash: image.imageHash, hammingDistance: distance };
    }
  }

  return best && best.hammingDistance <= MAX_HAMMING ? best : undefined;
}

function render(result: VerifyResult): void {
  const section = document.getElementById("result");
  if (!section) return;

  const rows: string[] = [];
  const say = (label: string, value: string) =>
    rows.push(`<div class="row"><dt>${label}</dt><dd>${value}</dd></div>`);

  if (result.verdict === "no-record") {
    // Neutral, deliberately. An absent record is not a finding about the
    // image, and `docs/claims.md` is explicit that it means nothing.
    section.className = "no-record";
    rows.push("<h2>No record</h2>");
    rows.push(
      `<p>This does not resolve to any body we hold${
        result.pceScore !== undefined
          ? `: best score ${result.pceScore.toFixed(1)} against a threshold of ${result.threshold}`
          : ""
      }. That means we have no record — not that the image is fake.</p>`,
    );
  } else if (!result.registered) {
    // The fingerprint matched and nobody registered the image. This is NOT a
    // pass and must not look like one. Measured against our own reference: a
    // forged image scores 393,382 where the best genuine frame scores 56,255,
    // at a distortion of 51.6 dB — invisible. See `docs/adversarial.md`.
    section.className = "pixels-only";
    rows.push("<h2>Fingerprint matched — but nothing is registered</h2>");
    if (result.bodyName) say("Fingerprint of", result.bodyName);
    if (result.pceScore !== undefined) {
      say("Score", `${result.pceScore.toFixed(1)} (threshold ${result.threshold})`);
    }
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
    // perceptual hash: collidable, and cheap to forge. The PCE is shown even
    // when it is below threshold, because that is the honest state of a copy
    // that has been through a platform -- the pHash and the chain carry this
    // one, not the pixels.
    section.className = "derived";
    rows.push("<h2>Descends from a registered photograph</h2>");
    if (result.bodyName) say("Body", result.bodyName);
    if (result.derivedFrom) {
      say("Matched to", `${result.derivedFrom.imageHash.slice(0, 18)}…`);
      say(
        "Perceptual distance",
        `${result.derivedFrom.hammingDistance} of 64 bits` +
          (result.derivedFrom.hammingDistance === 0 ? " — identical" : ""),
      );
    }
    if (result.pceScore !== undefined) {
      const clears = result.threshold !== undefined && result.pceScore >= result.threshold;
      say(
        "PCE",
        `${result.pceScore.toFixed(1)} (threshold ${result.threshold})` +
          (clears ? "" : " — below threshold; the pixels do not carry this claim"),
      );
    }
    if (result.registeredAt) say("Original registered", result.registeredAt);
    rows.push(
      "<p class=\"caveat\">The original was registered by its owner at the time " +
        "shown, and this image matches it perceptually. That is a weaker link " +
        "than an exact match: a perceptual hash can collide and can be forged. " +
        "Origin, not truth.</p>",
    );
  } else {
    section.className = "registered";
    rows.push("<h2>Registered by the body’s owner</h2>");
    if (result.bodyName) say("Body", result.bodyName);
    if (result.pceScore !== undefined) {
      say("PCE", `${result.pceScore.toFixed(1)} (threshold ${result.threshold})`);
    }
    say("Matched by", result.verdict === "registered" ? "exact pixel hash" : result.method ?? "PRNU");
    if (result.orientation && result.orientation !== "0 deg") {
      say("Orientation", `${result.orientation} — the image had been turned`);
    }
    if (result.registeredAt) say("First registered", result.registeredAt);
    if (result.modificationLevel !== undefined) {
      say("Modification level", ["unedited raw", "adjusted", "generative edit"][result.modificationLevel]);
    }
    rows.push(
      "<p class=\"caveat\">Origin, not truth. The owner of this body signed for " +
        "this image at the time shown. That does not say the scene was real.</p>",
    );
  }

  section.innerHTML = `<dl>${rows.join("")}</dl>`;
  section.hidden = false;
}

const input = document.getElementById("file") as HTMLInputElement | null;
input?.addEventListener("change", async () => {
  const file = input.files?.[0];
  if (!file) return;

  const section = document.getElementById("result");
  if (section) {
    section.className = "working";
    section.innerHTML = "<p>Extracting the noise residual…</p>";
    section.hidden = false;
  }

  try {
    render(await verifyImage(file));
  } catch (error) {
    if (section) {
      section.className = "error";
      section.innerHTML = `<p>${(error as Error).message}</p>`;
    }
  }
});

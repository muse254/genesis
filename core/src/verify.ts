/**
 * Verification: the one implementation the web page and the desktop app
 * share (`docs/shared-verify-plan.md`). The port of `console/app.py::_verify`,
 * `_diagnose` and `fingerprint/consistency.py::stages`, merged with what the
 * web page's own `verifyImage` did.
 *
 *   photo -> pixels -> SHA-256 of pixels -> exact hit on chain?
 *                   \                       ├ yes -> registered
 *                    \                      └ no  -> pHash via The Graph -> chain confirms -> derived
 *                     PRNU against each enrolled body  -> fingerprint-only, never a pass
 *
 * Four outcomes, and the gap between the middle two is the product:
 *
 * - `registered`        exact pixel hash, confirmed on chain.
 * - `derived`           a perceptual hash found the original and the chain
 *                       confirmed it. Weaker on purpose: a pHash is
 *                       collidable and cheap to forge.
 * - `fingerprint-only`  the pixels carry a body's fingerprint and nothing is
 *                       registered. **Not a pass** -- a fingerprint can be
 *                       planted (`docs/adversarial.md`).
 * - `no-record`         neither. Absence means nothing about the image.
 *
 * Only a chain read grants `registered` or `derived`. PRNU and the signals
 * may add doubt and never add confidence. A chain read that fails withholds
 * the verdict (throws); it never downgrades one.
 *
 * The web page passes no bodies, so there is no PRNU and nothing leaves the
 * browser but the hashes. The desktop passes the K files it enrolled.
 */

import { cropKey, type Analysis, type Candidate, type OnStep, type RawInput, type Signals } from "./analyse";
import { nearest, type ChainReader } from "./chain";
import type { Engine } from "./engine";
import { readExif } from "./exif";
import { isRaw } from "./hashes";

export type Verdict = "registered" | "derived" | "fingerprint-only" | "no-record";

export interface Signal {
  signal: string;
  value: number | null;
  auc: number | null;
}

export interface Stage {
  stage: number;
  name: string;
  asks: string;
  result: string | Signal[] | null;
  decides: string;
}

export interface VerifyResult {
  verdict: Verdict;
  /** A registration was read off the chain. Nothing else may set this. */
  registered: boolean;
  /** Best PCE across enrolled bodies; null with none enrolled. */
  pce: number | null;
  threshold: number;
  /** `"aligned"` or `"scale search"`; null with no bodies. */
  method: string | null;
  orientation: string | null;
  scale: number | null;
  borderStripped: string | null;
  imageHash: `0x${string}`;
  perceptualHash: `0x${string}`;
  body: {
    bodyId: string;
    /** The enrolled body's name, when the fingerprint matched one held locally. */
    name?: string;
    owner?: `0x${string}` | null;
    /** A reverse ENS name that forward-resolves to `owner`. */
    ownerName?: string | null;
    commitment?: `0x${string}` | null;
    revoked?: boolean | null;
    bodyCommitment?: `0x${string}` | null;
  } | null;
  registration: {
    /** Unix seconds. */
    registeredAt: number;
    modificationLevel: number;
    pceAtRegistration: number;
    explorerUrl?: string;
  } | null;
  derivedFrom: { imageHash: `0x${string}`; hammingDistance: number; matchedBy: "perceptual hash" } | null;
  consistency: Signals | null;
  stages: Stage[];
  /** On `no-record`: why there was nothing to find, when it can be measured. */
  diagnosis: string | null;
  /** The registry admits it can be wiped (`Registry.resetAll`): its dates are for rehearsal. */
  resettableRegistry: boolean;
}

/** A body the engine has loaded, with the crop a RAW decode must use for it. */
export interface LoadedBody {
  id: string;
  name: string;
  crop: number | null;
}

/** Decodes a RAW file (desktop only: LibRaw, in Python) for the given crops. */
export type RawDecoder = (file: File, crops: (number | null)[]) => Promise<RawInput>;

export interface VerifyOptions {
  engine: Engine;
  /** Absent when no registry is configured: nothing can be `registered`. */
  chain?: ChainReader;
  subgraphUrl?: string;
  /** Enrolled bodies, already loaded into `engine`. Empty on the web page. */
  bodies?: LoadedBody[];
  rawDecoder?: RawDecoder;
  onStep?: OnStep;
  fetch?: typeof fetch;
}

export async function verify(file: File, options: VerifyOptions): Promise<VerifyResult> {
  const { engine, chain, bodies = [], onStep } = options;
  const bytes = new Uint8Array(await file.arrayBuffer());

  let raw: RawInput | undefined;
  if (isRaw(file.name)) {
    if (!options.rawDecoder) {
      throw new Error("RAW files can't be checked in the browser. Export a JPEG, or verify the RAW in the desktop app.");
    }
    onStep?.("developing the RAW", 0.03);
    raw = await options.rawDecoder(file, [...new Set(bodies.map((b) => b.crop))]);
  }

  const analysis: Analysis = await engine.analyse({ bytes, name: file.name, bodies: bodies.map((b) => b.id), raw }, onStep);
  const best: Candidate | undefined = analysis.candidates[0];
  const matched = best !== undefined && best.pce >= analysis.threshold;

  onStep?.("reading the chain", 0.97);
  const withheld = (error: unknown) =>
    new Error(`chain read failed, verdict withheld: ${error instanceof Error ? error.message : error}`);

  let registration = null as Awaited<ReturnType<ChainReader["image"]>>;
  let derivedFrom: VerifyResult["derivedFrom"] = null;
  if (chain) {
    try {
      registration = await chain.image(analysis.imageHash);
    } catch (error) {
      throw withheld(error);
    }
    // The perceptual branch: a degraded copy has a different pixel hash, so
    // the exact read missed. The index proposes; the chain confirms.
    if (!registration && options.subgraphUrl) {
      const near = await nearest(options.subgraphUrl, analysis.perceptualHash, options.fetch);
      if (near) {
        let parent;
        try {
          parent = await chain.image(near.imageHash);
        } catch (error) {
          throw withheld(error);
        }
        if (parent) {
          registration = parent;
          derivedFrom = { imageHash: near.imageHash, hammingDistance: near.hammingDistance, matchedBy: "perceptual hash" };
        }
      }
    }
  }

  const verdict: Verdict = registration
    ? derivedFrom
      ? "derived"
      : "registered"
    : matched
      ? "fingerprint-only"
      : "no-record";

  const result: VerifyResult = {
    verdict,
    registered: registration !== null,
    pce: best?.pce ?? null,
    threshold: analysis.threshold,
    method: best?.path ?? null,
    orientation: best?.orientation ?? null,
    scale: best?.scale ?? null,
    borderStripped: best?.borderStripped ?? null,
    imageHash: analysis.imageHash,
    perceptualHash: analysis.perceptualHash,
    body: null,
    registration: null,
    derivedFrom,
    consistency: analysis.signals,
    stages: best
      ? stages({
          matched,
          registered: registration !== null,
          signals: analysis.signals ?? {},
          path: best.path === "aligned" ? "raw" : "delivered",
        })
      : [],
    diagnosis: null,
    resettableRegistry: registration && chain ? await chain.testMode() : false,
  };

  if (registration && chain) {
    // Identity comes from the record on chain, never from the scorer.
    let onChain;
    try {
      onChain = await chain.body(registration.bodyId);
    } catch (error) {
      throw withheld(error);
    }
    const local = bodies.find((b) => sameId(b.id, registration.bodyId));
    result.body = {
      bodyId: registration.bodyId,
      ...(local ? { name: local.name } : {}),
      owner: onChain?.owner ?? null,
      ownerName: onChain ? await chain.ensName(onChain.owner) : null,
      commitment: onChain?.fingerprintCommitment ?? null,
      revoked: onChain?.revoked ?? null,
      bodyCommitment: onChain?.bodyCommitment ?? null,
    };
    result.registration = {
      registeredAt: registration.registeredAt,
      modificationLevel: registration.modificationLevel,
      pceAtRegistration: registration.pceScore,
      explorerUrl: chain.explorerUrl,
    };
  } else if (matched) {
    // Named, because the page has to say *which* body's fingerprint it is --
    // and say in the same breath that nobody registered it.
    result.body = { bodyId: best.bodyId, name: best.name };
  } else if (best) {
    result.diagnosis = diagnose(bytes, file.name, analysis.signals);
  }
  return result;
}

/** Body ids come bare from the desktop's enrolment and 0x-prefixed from the chain. */
function sameId(a: string, b: string): boolean {
  return a.replace(/^0x/, "").toLowerCase() === b.replace(/^0x/, "").toLowerCase();
}

/**
 * What each advisory signal was measured to be worth
 * (`consistency.MEASURED_AUC`), so a signal never travels without its own
 * error bar. Every range overlaps; none is a test.
 */
export const MEASURED_AUC: Record<string, { raw: number | null; delivered: number | null }> = {
  bodyConsistency: { raw: 0.9, delivered: 0.725 },
  effectiveStrength: { raw: 0.8, delivered: 0.767 },
  resamplingPeak: { raw: null, delivered: 0.517 },
};

/**
 * `consistency.stages`: the pipeline as an ordered, reportable list. Stages
 * 1 and 2 can add doubt and can never grant a claim; only stage 3, a chain
 * read, produces `registered`.
 */
export function stages({
  matched,
  registered,
  signals,
  path = "delivered",
}: {
  matched: boolean;
  registered: boolean;
  signals: Partial<Signals>;
  path?: "raw" | "delivered";
}): Stage[] {
  const advisory: Signal[] = (["bodyConsistency", "effectiveStrength", "resamplingPeak"] as const)
    .filter((name) => signals[name] != null)
    .map((name) => ({ signal: name, value: signals[name] as number, auc: MEASURED_AUC[name]?.[path] ?? null }));

  return [
    {
      stage: 1,
      name: "pixel match",
      asks: "do these pixels carry this body's fingerprint?",
      result: matched ? "match" : "no match",
      decides: "whether to look further. A match alone claims nothing.",
    },
    {
      stage: 2,
      name: "consistency",
      asks: "does anything about this image contradict a genuine capture?",
      result: advisory.length ? advisory : null,
      decides:
        "nothing. Advisory only -- every signal here overlaps between " +
        "genuine frames and forgeries, best AUC 0.900 on RAW and 0.725 " +
        "on delivered. It may add doubt; it may never add confidence.",
    },
    {
      stage: 3,
      name: "registration",
      asks: "did this body's owner register this image on chain?",
      result: registered ? "registered" : "no registration",
      decides: "the verdict. This is the only stage that grants a claim.",
    },
  ];
}

/**
 * Software tags a desktop development leaves behind (`console/app.py`
 * `DESKTOP_SOFTWARE`). A camera Make and none of these looks like a JPEG
 * straight out of the camera, which `docs/gates.md` measured as carrying no
 * readable fingerprint.
 */
const DESKTOP_SOFTWARE = [
  "adobe", "photoshop", "lightroom", "acd", "capture one", "darktable",
  "rawtherapee", "affinity", "dxo", "luminar", "gimp", "pixelmator",
  "apple", "preview",
];

/**
 * `console/app.py::_diagnose`: why there was nothing to find, when it can be
 * said from measurement. Stops a photographer distrusting a camera that is
 * fine. Never guesses at a cause it cannot see.
 */
export function diagnose(bytes: Uint8Array, fileName: string, signals: Signals | null): string | null {
  if (signals?.tooSoftToMeasure) {
    return (
      `This image has almost no high-frequency detail (median tile ${signals.detail}, against roughly ` +
      `1,000-4,000 for files that verify). A sensor fingerprint lives in high frequencies, so there is ` +
      `nothing here to measure — which is not the same as the camera not matching.`
    );
  }
  if (isRaw(fileName)) return null;

  const exif = readExif(bytes);
  if (exif?.make && !DESKTOP_SOFTWARE.some((tag) => exif.software.toLowerCase().includes(tag))) {
    return (
      "This looks like a JPEG written by the camera itself. Measured on this body, in-camera JPEGs " +
      "carry no readable fingerprint — the camera's noise reduction removes it, because to the camera " +
      "a sensor fingerprint is noise (docs/gates.md). Try the RAW, or a development of it."
    );
  }
  return null;
}

export { cropKey };

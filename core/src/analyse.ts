/**
 * The pixel half of verification: decode, hash, score against every
 * enrolled body, and the advisory signals for the best one. Runs inside the
 * Web Worker (`worker.ts`) so a seven-second score never freezes the page,
 * and in-process in tests.
 *
 * The port of what `console/app.py::_verify` did before its chain reads,
 * with `scoring/app.py::_score_against` per body. The chain and the verdict
 * are `verify.ts`'s job, on the main thread.
 */

import { Body, pceThreshold, scoreAgainst, scoreAgainstRaw, signals } from "./wasm/genesis_prnu_wasm.js";
import { decode, ensurePrnu, hashesOf, type Decoded, type Hashes, type Loaders } from "./hashes";

/** What `_score_against` returns, per body. */
export interface ScoreResult {
  pce: number;
  path: "aligned" | "scale search";
  orientation: string;
  scale: number | null;
  borderStripped: string | null;
  turned: string | null;
  attempts: number[];
}

export interface Candidate extends ScoreResult {
  bodyId: string;
  name: string;
}

/** `console/app.py::_signals`. Advisory: none of these may raise a verdict. */
export interface Signals {
  calibrated: false;
  bodyConsistency: null;
  pooledTriangle: null;
  effectiveStrength: number | null;
  resamplingPeak: number | null;
  detail: number | null;
  tooSoftToMeasure: boolean | null;
}

/** A RAW file decoded by the desktop's Python (LibRaw), for bodies to score against. */
export interface RawInput {
  /** The developed image: what the pixel hash covers and the scale search reads. */
  rgb: Uint8Array;
  width: number;
  height: number;
  /** CFA planes as a `plane_<c>` `.npz`, keyed by the body crop they were cut to (`"none"` for none). */
  planes: Record<string, Uint8Array>;
}

export interface AnalyseRequest {
  bytes: Uint8Array;
  name: string;
  /** Ids of bodies already loaded with `loadBody`. Empty on the web page. */
  bodies: string[];
  raw?: RawInput;
}

export interface Analysis extends Hashes {
  threshold: number;
  /** Best first. */
  candidates: Candidate[];
  /** For the best candidate; null when there are no bodies. */
  signals: Signals | null;
}

export type OnStep = (label: string, fraction: number) => void;

/** `meta["crop"]` as the key `RawInput.planes` uses. */
export function cropKey(crop: number | undefined | null): string {
  return crop == null ? "none" : String(crop);
}

const loaded = new Map<string, { name: string; body: Body }>();

/** Parse a body's K once; later analyses refer to it by id. */
export async function loadBody(id: string, name: string, k: Uint8Array, loaders: Loaders = {}): Promise<{ crop: number | null }> {
  await ensurePrnu(loaders);
  loaded.get(id)?.body.free();
  const body = new Body(k);
  loaded.set(id, { name, body });
  return { crop: body.crop ?? null };
}

/**
 * `console/app.py`'s progress weighting, so the desktop's bar moves as it
 * did: the scale search is most of the wall clock, and equal shares would sit
 * at 40% for a minute and then jump.
 */
export function fractionOf(label: string): number {
  if (label.includes("residual")) return 0.15;
  if (label.includes("sensor space") || label.includes("lattice")) return 0.8;
  const counted = /— (\d+) of (\d+)/.exec(label);
  if (label.includes("searching") && counted) {
    return Math.round((0.2 + 0.65 * (Number(counted[1]) / Math.max(Number(counted[2]), 1))) * 1000) / 1000;
  }
  return 0.06;
}

export async function analyse(request: AnalyseRequest, onStep: OnStep = () => {}, loaders: Loaders = {}): Promise<Analysis> {
  await ensurePrnu(loaders);
  const image: Decoded = request.raw
    ? { rgb: request.raw.rgb, width: request.raw.width, height: request.raw.height }
    : await decode(request.bytes, request.name, loaders);
  const hashes = hashesOf(image);
  const step = (label: string) => onStep(label, fractionOf(label));

  const candidates: Candidate[] = [];
  for (const id of request.bodies) {
    const entry = loaded.get(id);
    if (!entry) throw new Error(`body ${id} was not loaded`);
    const result: ScoreResult = request.raw
      ? scoreAgainstRaw(planesFor(request.raw, entry.body), image.rgb, image.width, image.height, entry.body, step)
      : scoreAgainst(image.rgb, image.width, image.height, entry.body, step);
    candidates.push({ bodyId: id, name: entry.name, ...result });
  }
  // Stable, so equal scores keep enrolment order, as Python's sort did.
  candidates.sort((a, b) => b.pce - a.pce);

  const best = candidates[0];
  return {
    ...hashes,
    threshold: pceThreshold(),
    candidates,
    signals: best ? signalsFor(image, loaded.get(best.bodyId)!.body, best, request.raw) : null,
  };
}

function planesFor(raw: RawInput, body: Body): Uint8Array {
  const planes = raw.planes[cropKey(body.crop)];
  if (!planes) throw new Error(`no RAW planes decoded for crop ${cropKey(body.crop)}`);
  return planes;
}

function signalsFor(image: Decoded, body: Body, best: Candidate, raw?: RawInput): Signals {
  const s = signals(
    image.rgb,
    image.width,
    image.height,
    body,
    best.path === "aligned",
    raw ? planesFor(raw, body) : undefined,
  ) as { effectiveStrength: number | null; resamplingPeak: number | null; detail: number | null };
  return {
    calibrated: false,
    bodyConsistency: null,
    pooledTriangle: null,
    effectiveStrength: s.effectiveStrength,
    resamplingPeak: s.resamplingPeak,
    // Not advisory in the same sense: it says whether there was anything to
    // measure. A soft frame carries no fingerprint however genuine it is.
    detail: s.detail === null ? null : Math.round(s.detail * 10) / 10,
    tooSoftToMeasure: s.detail === null ? null : s.detail < DETAIL_FLOOR,
  };
}

/** `consistency.DETAIL_FLOOR`. */
export const DETAIL_FLOOR = 200;

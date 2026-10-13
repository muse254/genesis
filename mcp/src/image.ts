/**
 * Check a local photo using core/'s `hashImage` and `nearest`, bundled into
 * dist/core, so digests match the verify page. Only hashes leave the machine.
 */

import { readFile } from "node:fs/promises";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

import { SubgraphClient, describeImage, type ImageRecord } from "./queries.js";

export interface Hashes {
  imageHash: `0x${string}`;
  perceptualHash: `0x${string}`;
}

interface Core {
  hashImage(bytes: Uint8Array, fileName: string, loaders?: { prnuWasm?: Uint8Array }): Promise<Hashes>;
  isRaw(fileName: string): boolean;
  nearest(
    subgraphUrl: string,
    perceptualHash: string,
    fetchImpl?: typeof fetch,
  ): Promise<{ imageHash: `0x${string}`; hammingDistance: number } | null>;
  MAX_HAMMING: number;
}

const coreDir = join(dirname(fileURLToPath(import.meta.url)), "core");
let core: Promise<Core> | undefined;
let prnuWasm: Promise<Buffer> | undefined;

async function loadCore(): Promise<Core> {
  try {
    // Variables, so tsc doesn't resolve modules that exist only after bundling.
    const hashes = pathToFileURL(join(coreDir, "hashes.js")).href;
    const chain = pathToFileURL(join(coreDir, "chain.js")).href;
    const [h, c] = await Promise.all([import(hashes), import(chain)]);
    return { hashImage: h.hashImage, isRaw: h.isRaw, nearest: c.nearest, MAX_HAMMING: c.MAX_HAMMING };
  } catch (error) {
    core = undefined;
    throw new Error(
      "This server was built without core's WASM, so it cannot hash a file. " +
        "Build it with `cd core && npm ci && npm run wasm`, then `cd mcp && npm run build` " +
        "(mcp/README.md). Meanwhile verify_image takes a pixel hash computed elsewhere, " +
        `e.g. on the public verify page. (${(error as Error).message})`,
    );
  }
}

/** Whether dist/core was bundled, for tests that need the real WASM. */
export async function coreAvailable(): Promise<boolean> {
  try {
    await (core ??= loadCore());
    return true;
  } catch {
    return false;
  }
}

/** Pixel SHA-256 and perceptual hash of image bytes, by core/'s `hashImage`. */
export async function hashBytes(bytes: Uint8Array, fileName: string): Promise<Hashes> {
  const lib = await (core ??= loadCore());
  if (lib.isRaw(fileName)) {
    throw new Error(
      `${basename(fileName)} is a RAW file. Registrations hash the developed image, and developing ` +
        "a RAW the way enrolment does is the desktop app's job. Export a JPEG, PNG or TIFF and check that.",
    );
  }
  // Node's fetch cannot read a file: URL, so hand the Rust WASM its bytes.
  prnuWasm ??= readFile(join(coreDir, "wasm", "genesis_prnu_wasm_bg.wasm"));
  return lib.hashImage(bytes, fileName, { prnuWasm: await prnuWasm });
}

export function expandPath(path: string): string {
  if (path === "~" || path.startsWith("~/")) return join(homedir(), path.slice(1));
  return resolve(path);
}

export async function hashFile(path: string): Promise<Hashes> {
  const full = expandPath(path);
  let bytes: Buffer;
  try {
    bytes = await readFile(full);
  } catch (error) {
    throw new Error(`Could not read ${full}: ${(error as NodeJS.ErrnoException).code ?? error}`);
  }
  return hashBytes(new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength), full);
}

export interface FileCheck {
  file: string;
  hashes: Hashes;
  /** The registration for these exact pixels, if any. */
  exact: ImageRecord | null;
  /** Otherwise the nearest registration by perceptual hash, within core's MAX_HAMMING. */
  near: { record: ImageRecord; hammingDistance: number; maxHamming: number } | null;
}

/** Hash a local file and look it up: exact pixels first, then the perceptual index. */
export async function checkImageFile(
  path: string,
  client: SubgraphClient,
  fetchImpl: typeof fetch = fetch,
): Promise<FileCheck> {
  const hashes = await hashFile(path);
  const file = basename(path);
  const exact = await client.imageByHash(hashes.imageHash);
  if (exact) return { file, hashes, exact, near: null };

  const lib = await (core ??= loadCore());
  const candidate = await lib.nearest(client.url, hashes.perceptualHash, fetchImpl);
  const record = candidate ? await client.imageByHash(candidate.imageHash) : null;
  return {
    file,
    hashes,
    exact: null,
    near: record && candidate ? { record, hammingDistance: candidate.hammingDistance, maxHamming: lib.MAX_HAMMING } : null,
  };
}

/** What the agent is told about a file. The record wording is describeImage's. */
export function describeFileCheck({ file, hashes, exact, near }: FileCheck): string {
  const head = [
    `Hashed ${file} locally (core/'s hashImage, as the verify page does). The file did not leave this machine.`,
    `  Pixel SHA-256     ${hashes.imageHash}`,
    `  Perceptual hash   ${hashes.perceptualHash}`,
    "",
  ];

  if (exact) return [...head, describeImage(exact, hashes.imageHash)].join("\n");

  if (near) {
    return [
      ...head,
      `No registration for these exact pixels. The nearest registered image by`,
      `perceptual hash is ${near.record.id}, ${near.hammingDistance} of 64 bits apart`,
      `(the verify page accepts up to ${near.maxHamming}).`,
      "",
      "That is a lead, not a match. A perceptual hash says two images look alike;",
      "it survives re-encoding and resizing, and it also survives edits. This file",
      "may be a re-encoded or edited copy of the registered one, or an unrelated",
      "image that happens to hash close. Only the registered original's pixels",
      "carry the record below.",
      "",
      describeImage(near.record, near.record.id),
    ].join("\n");
  }

  return [...head, describeImage(null, hashes.imageHash)].join("\n");
}

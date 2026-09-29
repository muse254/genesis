/**
 * Decoding a photo to canonical RGB8, and the image record's two hashes.
 *
 * The same digests `ingest/hashing.py` computes: `imageHash` (SHA-256 over
 * canonical RGB8 pixels) and `perceptualHash` (64-bit DCT pHash).
 *
 * Decoding is split by format, because the pixel hash is exact and the
 * decoder decides the pixels:
 *
 * - JPEG goes through libjpeg-turbo compiled to WASM (`core/jpeg/`), the
 *   same version Pillow bundles, so it decodes to the same bytes. The Rust
 *   `image` crate does not (15% of bytes off on a real photo).
 * - PNG and TIFF go through the Rust crate (`rust/genesis-prnu-wasm`).
 *   Lossless, so any correct decoder agrees.
 * - RAW is refused here: developing one is LibRaw's job, and LibRaw has no
 *   WASM build. The desktop decodes RAW in Python and passes the result in
 *   (see `verify.ts`); the web page cannot.
 *
 * Both modules load lazily on first use and are cached. The pixels decoded
 * here are also what PRNU scoring reads (`analyse.ts`), so the hash and the
 * score always see the same image.
 */

import initPrnu, { decodeRgb, imageHashes } from "./wasm/genesis_prnu_wasm.js";
import createLibJpeg, { type LibJpeg } from "./jpeg/libjpeg.mjs";

export interface Hashes {
  imageHash: `0x${string}`;
  perceptualHash: `0x${string}`;
}

export interface Decoded {
  rgb: Uint8Array;
  width: number;
  height: number;
}

/** `hashing_raw_suffixes()` in `ingest/record.py`. */
export const RAW_SUFFIXES = [".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"];

export function isRaw(fileName: string): boolean {
  const lower = fileName.toLowerCase();
  return RAW_SUFFIXES.some((suffix) => lower.endsWith(suffix));
}

let prnu: Promise<unknown> | undefined;
let jpeg: Promise<LibJpeg> | undefined;

/**
 * Optional override for where the Rust `.wasm` binary comes from. The pages
 * never pass it (the module finds its binary next to its JS); tests and
 * Node scripts do, because Node's `fetch` cannot read files.
 */
export interface Loaders {
  prnuWasm?: BufferSource;
}

/** Load the Rust WASM module once. Everything else in core that calls into it awaits this first. */
export function ensurePrnu(loaders: Loaders = {}): Promise<unknown> {
  prnu ??= initPrnu(loaders.prnuWasm ? { module_or_path: loaders.prnuWasm } : undefined);
  return prnu;
}

/** Load and compile both WASM modules now, so the first photo does not wait for them. */
export async function warm(loaders: Loaders = {}): Promise<void> {
  jpeg ??= createLibJpeg();
  await Promise.all([ensurePrnu(loaders), jpeg]);
  // Run the hot paths once. Browsers first run WASM in a quick-to-compile,
  // slow-to-run tier and optimise only code that turns out to be hot, and
  // the heap starts small; a first 24 MP photo paid for both (measured:
  // 4.6 s to hash cold, under 0.5 s warm).
  const width = 1500;
  const height = 1000;
  hashesOf({ rgb: new Uint8Array(width * height * 3), width, height });
}

/** Decode a JPEG, PNG or TIFF to canonical RGB8. Throws on RAW and on anything unreadable. */
export async function decode(bytes: Uint8Array, fileName: string, loaders: Loaders = {}): Promise<Decoded> {
  if (isRaw(fileName)) {
    throw new Error(
      "RAW files can't be checked in the browser. Export a JPEG, or verify the RAW in the desktop app.",
    );
  }
  await ensurePrnu(loaders);
  return isJpeg(bytes) ? decodeJpeg(bytes) : decodeLossless(bytes);
}

/** Both hashes of pixels already decoded. */
export function hashesOf({ rgb, width, height }: Decoded): Hashes {
  const hashes = imageHashes(rgb, width, height);
  try {
    return {
      imageHash: hashes.imageHash as `0x${string}`,
      perceptualHash: hashes.perceptualHash as `0x${string}`,
    };
  } finally {
    hashes.free();
  }
}

/** Decode and hash in one step. */
export async function hashImage(bytes: Uint8Array, fileName: string, loaders: Loaders = {}): Promise<Hashes> {
  return hashesOf(await decode(bytes, fileName, loaders));
}

function isJpeg(bytes: Uint8Array): boolean {
  return bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
}

async function decodeJpeg(bytes: Uint8Array): Promise<Decoded> {
  jpeg ??= createLibJpeg();
  const lib = await jpeg;

  const input = lib._malloc(bytes.length);
  try {
    lib.HEAPU8.set(bytes, input);
    if (lib._decode(input, bytes.length) !== 0) {
      throw new Error(`Could not read this JPEG: ${lib.UTF8ToString(lib._error_message())}`);
    }
    const width = lib._result_w();
    const height = lib._result_h();
    const at = lib._result_pixels();
    // Copy out: HEAPU8 is a view that memory growth can invalidate.
    const rgb = lib.HEAPU8.slice(at, at + width * height * 3);
    return { rgb, width, height };
  } finally {
    lib._free(input);
    lib._release();
  }
}

function decodeLossless(bytes: Uint8Array): Decoded {
  let decoded;
  try {
    decoded = decodeRgb(bytes);
  } catch (error) {
    throw new Error(`Could not read this image (JPEG, PNG and TIFF are supported): ${error}`);
  }
  try {
    return { rgb: decoded.rgb, width: decoded.width, height: decoded.height };
  } finally {
    decoded.free();
  }
}

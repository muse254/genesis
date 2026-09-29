/**
 * The image record's two hashes, computed in the browser.
 *
 * The same digests `ingest/hashing.py` computes: `imageHash` (SHA-256 over
 * canonical RGB8 pixels) and `perceptualHash` (64-bit DCT pHash). The photo
 * never leaves the page to get them -- this used to be a POST to a scoring
 * service's `/lookup`, which on GitHub Pages meant a request to localhost.
 *
 * Decoding is split by format, because the pixel hash is exact and the
 * decoder decides the pixels:
 *
 * - JPEG goes through libjpeg-turbo compiled to WASM (`verify/jpeg/`), the
 *   same version Pillow bundles, so it decodes to the same bytes. The Rust
 *   `image` crate does not (15% of bytes off on a real photo).
 * - PNG and TIFF go through the Rust crate (`rust/genesis-prnu-wasm`).
 *   Lossless, so any correct decoder agrees.
 * - RAW is refused: developing one is LibRaw's job, and LibRaw has no WASM
 *   build.
 *
 * Both modules load lazily on first use and are cached.
 */

import initPrnu, { decodeRgb, imageHashes } from "./wasm/genesis_prnu_wasm.js";
import createLibJpeg, { type LibJpeg } from "./jpeg/libjpeg.mjs";

export interface Hashes {
  imageHash: `0x${string}`;
  perceptualHash: `0x${string}`;
}

/** `hashing_raw_suffixes()` in `ingest/record.py`. */
const RAW_SUFFIXES = [".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"];

let prnu: Promise<unknown> | undefined;
let jpeg: Promise<LibJpeg> | undefined;

/**
 * Optional overrides for where the two `.wasm` binaries come from. The page
 * never passes these (both modules find their binary next to their JS);
 * the Node parity check does, because Node's `fetch` cannot read files.
 */
export interface Loaders {
  prnuWasm?: BufferSource;
}

export async function hashImage(bytes: Uint8Array, fileName: string, loaders: Loaders = {}): Promise<Hashes> {
  const lower = fileName.toLowerCase();
  if (RAW_SUFFIXES.some((suffix) => lower.endsWith(suffix))) {
    throw new Error(
      "RAW files can't be checked in the browser. Export a JPEG, or verify the RAW in the desktop app.",
    );
  }

  prnu ??= initPrnu(loaders.prnuWasm ? { module_or_path: loaders.prnuWasm } : undefined);
  await prnu;

  const { rgb, width, height } = isJpeg(bytes) ? await decodeJpeg(bytes) : decodeLossless(bytes);
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

function isJpeg(bytes: Uint8Array): boolean {
  return bytes.length > 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
}

async function decodeJpeg(bytes: Uint8Array) {
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

function decodeLossless(bytes: Uint8Array) {
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

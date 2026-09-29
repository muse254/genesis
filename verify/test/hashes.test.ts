/**
 * src/hashes.ts against ingest/hashing.py, through the real WASM modules.
 *
 * The fixtures and their expected hashes come from
 * `python -m ingest.dump_hash_fixtures`. This is the only place the JPEG
 * cases run: cargo test cannot, because the Rust crate does not link
 * libjpeg-turbo. Needs `npm run wasm` first (CI does it via `npm run build`).
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

import { hashImage } from "../src/hashes";

const fixtures = join(__dirname, "..", "..", "rust", "genesis-prnu", "tests", "fixtures", "hashing");
const manifest: {
  libjpeg_turbo: string;
  cases: { file: string; kind: string; expect: "match" | "refused"; why?: string; imageHash?: string; perceptualHash?: string }[];
} = JSON.parse(readFileSync(join(fixtures, "manifest.json"), "utf8"));

const loaders = { prnuWasm: readFileSync(join(__dirname, "..", "src", "wasm", "genesis_prnu_wasm_bg.wasm")) };
const fixture = (file: string) => new Uint8Array(readFileSync(join(fixtures, file)));
const hash = (bytes: Uint8Array, name: string) => hashImage(bytes, name, loaders);

describe("parity with ingest/hashing.py", () => {
  it("was generated with the libjpeg-turbo build.sh pins", () => {
    const pinned = readFileSync(join(__dirname, "..", "jpeg", "build.sh"), "utf8").match(/LIBJPEG_TURBO_VERSION=(\S+)/)![1];
    expect(manifest.libjpeg_turbo).toBe(pinned);
  });

  it.each(manifest.cases.filter((c) => c.expect === "match").map((c) => [c.file, c] as const))(
    "%s",
    async (file, c) => {
      expect(await hash(fixture(file), file)).toEqual({ imageHash: c.imageHash, perceptualHash: c.perceptualHash });
    },
  );

  it.each(manifest.cases.filter((c) => c.expect === "refused").map((c) => [c.file, c.why] as const))(
    "refuses %s (%s) instead of hashing it",
    async (file) => {
      await expect(hash(fixture(file), file)).rejects.toThrow(/Could not read/);
    },
  );
});

describe("hashImage", () => {
  it("ignores an EXIF segment, since it hashes pixels and not bytes", async () => {
    const jpeg = fixture("jpeg_420.jpg");
    const exif = new Uint8Array([0xff, 0xe1, 0x00, 0x10, ...new TextEncoder().encode("Exif\0\0not-pixels")]);
    const withExif = new Uint8Array([...jpeg.slice(0, 2), ...exif, ...jpeg.slice(2)]);

    expect(withExif.length).toBeGreaterThan(jpeg.length);
    expect(await hash(withExif, "a.jpg")).toEqual(await hash(jpeg, "a.jpg"));
  });

  it("chooses the decoder by content, not by the file name", async () => {
    const c = manifest.cases.find((x) => x.file === "jpeg_444.jpg")!;
    expect((await hash(fixture("jpeg_444.jpg"), "renamed.png")).imageHash).toBe(c.imageHash);
  });

  it.each(["frame.CR3", "frame.nef", "frame.DNG", "frame.arw"])("refuses RAW (%s) with a way forward", async (name) => {
    await expect(hash(new Uint8Array([1, 2, 3]), name)).rejects.toThrow(/desktop app/);
  });

  it("refuses bytes that are no image at all", async () => {
    await expect(hash(new TextEncoder().encode("not an image"), "a.txt")).rejects.toThrow(/Could not read this image/);
  });

  it("names the problem for a truncated JPEG", async () => {
    await expect(hash(fixture("jpeg_truncated.jpg"), "t.jpg")).rejects.toThrow(/truncated/);
  });

  it("still decodes after a failure", async () => {
    await expect(hash(fixture("jpeg_cmyk.jpg"), "c.jpg")).rejects.toThrow(/CMYK/);
    const c = manifest.cases.find((x) => x.file === "jpeg_420.jpg")!;
    expect((await hash(fixture("jpeg_420.jpg"), "ok.jpg")).imageHash).toBe(c.imageHash);
  });
});

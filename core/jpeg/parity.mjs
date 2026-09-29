// Real-photo parity: the browser hashes (core/src/hashes.ts) against
// ingest/hashing.py, on photos too large or too private to commit.
//
//   npm run parity -- ~/photos/a.jpg ~/photos/b.png
//
// Each photo is hashed by Python (PYTHON, default .venv/bin/python) and by
// the WASM modules, and the two must agree exactly. The committed synthetic
// fixtures are covered by `npm test` (test/hashes.test.ts); this is the
// check on real camera output, worth running after bumping libjpeg-turbo or
// Pillow. Needs `npm run wasm` first.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const { hashImage } = await import(join(here, "..", "src", "hashes.ts"));
const loaders = { prnuWasm: readFileSync(join(here, "..", "src", "wasm", "genesis_prnu_wasm_bg.wasm")) };
const python = process.env.PYTHON ?? join(root, ".venv", "bin", "python");

const photos = process.argv.slice(2).map((p) => resolve(process.env.INIT_CWD ?? process.cwd(), p));
if (photos.length === 0) {
  console.error("usage: npm run parity -- <photo> [photo ...]");
  process.exit(2);
}

let failures = 0;
for (const photo of photos) {
  const [imageHash, perceptualHash] = execFileSync(
    python,
    ["-c", "import sys; from ingest import hashing as h; p=sys.argv[1]; print('0x'+h.pixel_sha256(p).hex(), f'0x{h.perceptual_hash(p):016x}')", photo],
    { cwd: root, encoding: "utf8" },
  ).trim().split(" ");
  const got = await hashImage(readFileSync(photo), photo, loaders);
  const ok = got.imageHash === imageHash && got.perceptualHash === perceptualHash;
  if (!ok) failures++;
  console.log(`${ok ? "ok  " : "FAIL"} ${basename(photo)}`);
  if (!ok) console.log(`     wasm   ${got.imageHash} ${got.perceptualHash}\n     python ${imageHash} ${perceptualHash}`);
}

if (failures) {
  console.log(`${failures} of ${photos.length} differ`);
  process.exit(1);
}
console.log("all match");

// Parity of the WASM LibRaw build (core/raw/) with `rawpy`, on real RAW files.
//
//   node core/raw/parity.mjs <raw> [raw ...]
//
// For each file, every field enrolment reads (fingerprint/prnu.py
// load_raw_planes and cfa_pattern) is compared exactly: the visible mosaic
// (by SHA-256), its size, raw_pattern, raw_colors_visible (every pixel),
// black_level_per_channel and white_level. The body serial is compared with
// exiftool's, which the desktop's enrolment check uses today. Python comes
// from PYTHON (default .venv/bin/python). Needs `./core/raw/build.sh` first.
//
// Pass real camera files. They are not committed, and neither is where they
// live: one RAW off a body is enough to forge its fingerprint.
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const python = process.env.PYTHON ?? join(root, ".venv", "bin", "python");
const createLibRaw = (await import(join(here, "..", "src", "raw", "libraw.mjs"))).default;
const lib = await createLibRaw();

const REFERENCE = `
import hashlib, json, subprocess, sys
import numpy as np, rawpy
path = sys.argv[1]
out = {}
try:
    with rawpy.imread(path) as raw:
        out["flat"] = raw.raw_type == rawpy.RawType.Flat
        if out["flat"]:
            v = np.ascontiguousarray(raw.raw_image_visible, dtype="<u2")
            out["size"] = [v.shape[1], v.shape[0]]
            out["mosaic"] = hashlib.sha256(v.tobytes()).hexdigest()
            out["pattern"] = raw.raw_pattern.tolist()
            out["colors"] = hashlib.sha256(np.ascontiguousarray(raw.raw_colors_visible, dtype=np.uint8).tobytes()).hexdigest()
            out["black"] = [int(b) for b in raw.black_level_per_channel]
            out["white"] = int(raw.white_level)
except rawpy.LibRawError as e:
    out["error"] = str(e)
try:
    out["serial"] = subprocess.run(["exiftool", "-s3", "-SerialNumber", path], capture_output=True, text=True).stdout.strip()
except FileNotFoundError:
    out["serial"] = None
print(json.dumps(out))
`;

function wasm(path) {
  const bytes = readFileSync(path);
  const input = lib._malloc(bytes.length);
  lib.HEAPU8.set(bytes, input);
  const status = lib._raw_open(input, bytes.length);
  lib._free(input);
  const text = (ptr) => lib.UTF8ToString(ptr);
  try {
    if (status !== 0) return { flat: status === 2 ? false : undefined, error: text(lib._raw_error()) };
    const [w, h] = [lib._raw_width(), lib._raw_height()];
    const at = lib._raw_visible() / 2;
    const mosaic = createHash("sha256").update(Buffer.from(lib.HEAPU16.buffer, at * 2, w * h * 2)).digest("hex");
    const n = lib._raw_pattern_size();
    const pattern = Array.from({ length: n }, (_, y) => Array.from({ length: n }, (_, x) => lib._raw_pattern_at(y, x)));
    // Every pixel's colour, built from the same rule, hashed as rawpy's array is.
    const colors = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) colors[y * w + x] = lib._raw_color_visible(y, x);
    return {
      flat: true,
      size: [w, h],
      mosaic,
      pattern,
      colors: createHash("sha256").update(colors).digest("hex"),
      black: [0, 1, 2, 3].map((c) => lib._raw_black(c)),
      white: lib._raw_white(),
      serial: text(lib._raw_body_serial()),
      camera: `${text(lib._raw_make())} ${text(lib._raw_model())}`,
    };
  } finally {
    lib._raw_close();
  }
}

console.log(`LibRaw ${lib.UTF8ToString(lib._raw_libraw_version())} (WASM) against rawpy\n`);
let failures = 0;
for (const path of process.argv.slice(2)) {
  const want = JSON.parse(execFileSync(python, ["-c", REFERENCE, path], { cwd: root, encoding: "utf8" }));
  const t = Date.now();
  const got = wasm(path);
  const ms = Date.now() - t;

  const checks = want.flat
    ? ["flat", "size", "mosaic", "pattern", "colors", "black", "white"].map((k) => [k, JSON.stringify(got[k]) === JSON.stringify(want[k])])
    : // Not a mosaic: rawpy opens it and load_raw_planes refuses it; this
      // build may refuse it earlier (no lossy-DNG JPEG support). Either way
      // it must not come back as a mosaic.
      [["refused, as load_raw_planes refuses it", got.flat !== true]];
  if (want.flat && want.serial) checks.push(["serial", got.serial === want.serial]);
  const ok = checks.every(([, pass]) => pass);
  if (!ok) failures++;

  console.log(`${ok ? "ok  " : "FAIL"} ${basename(path)}  ${got.camera ?? ""}  ${ms} ms`);
  for (const [k, pass] of checks) if (!pass) console.log(`     ${k}: wasm ${JSON.stringify(got[k])}  rawpy ${JSON.stringify(want[k])}`);
  if (ok && !want.flat) console.log(`     ${got.error ?? "refused"}`);
  if (ok && want.flat) console.log(`     ${got.size.join("x")}  pattern ${JSON.stringify(got.pattern)}  black ${got.black}  white ${got.white}  serial ${got.serial || "(none)"}`);
}
if (failures) {
  console.log(`\n${failures} differ`);
  process.exit(1);
}
console.log("\nall match");

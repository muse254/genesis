// Copy core/'s hashing into dist/core, so verify_image_file hashes a photo
// with exactly the code the verify page runs. Nothing is reimplemented here.
//
//   core/src/hashes.ts            -> dist/core/hashes.js   (types stripped)
//   core/src/chain.ts             -> dist/core/chain.js    (for `nearest`)
//   core/src/wasm/*  (wasm-pack)  -> dist/core/wasm/
//   core/src/jpeg/*  (Emscripten) -> dist/core/jpeg/
//
// The two WASM modules are not committed; `npm run wasm` in core/ builds
// them (Rust + wasm-pack + emcc, see core/README.md). Without them this
// prints how to get them and exits 0, so the three hash-lookup tools still
// build and run; verify_image_file then says what is missing. Set
// GENESIS_REQUIRE_CORE=1 to make a missing build an error instead.
//
// Types are stripped, not checked: core/'s own CI job type-checks it.
import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";

const mcp = join(dirname(fileURLToPath(import.meta.url)), "..");
const core = join(mcp, "..", "core", "src");
const out = join(mcp, "dist", "core");

const assets = [
  "wasm/genesis_prnu_wasm.js",
  "wasm/genesis_prnu_wasm_bg.wasm",
  "jpeg/libjpeg.mjs",
  "jpeg/libjpeg.wasm",
];
const sources = ["hashes.ts", "chain.ts"];

const missing = [...assets, ...sources].filter((file) => !existsSync(join(core, file)));
rmSync(out, { recursive: true, force: true });

if (missing.length) {
  const message = [
    `core's WASM is not built (missing: ${missing.map((f) => `core/src/${f}`).join(", ")}).`,
    "verify_image_file needs it; verify_image, lookup_body and image_lineage do not.",
    "To build it: cd ../core && npm ci && npm run wasm   (Rust, wasm-pack and emcc; core/README.md)",
    "then rerun npm run build here.",
  ].join("\n  ");
  if (process.env.GENESIS_REQUIRE_CORE === "1") {
    console.error(`error: ${message}`);
    process.exit(1);
  }
  console.warn(`note: ${message}`);
  process.exit(0);
}

for (const file of sources) {
  const { outputText } = ts.transpileModule(readFileSync(join(core, file), "utf8"), {
    compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 },
    fileName: file,
  });
  mkdirSync(out, { recursive: true });
  writeFileSync(join(out, file.replace(/\.ts$/, ".js")), outputText);
}
for (const file of assets) {
  mkdirSync(dirname(join(out, file)), { recursive: true });
  copyFileSync(join(core, file), join(out, file));
}
console.log(`core hashing bundled into dist/core (${sources.length} modules, ${assets.length} assets)`);

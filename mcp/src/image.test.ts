/**
 * verify_image_file: the hashes an agent gets for a file it holds must be
 * the verify page's, byte for byte, or every lookup misses.
 *
 * The parity cases are core/'s own (test/hashes.test.ts), from
 * `python -m ingest.dump_hash_fixtures`, run through the copy of core
 * bundled into dist/core. They need core's WASM built (mcp/README.md) and
 * are skipped, with a reason, when it is not.
 */

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { subgraphUrl } from "./config.js";
import { checkImageFile, coreAvailable, describeFileCheck, expandPath, hashBytes, hashFile } from "./image.js";
import { SubgraphClient, type ImageRecord } from "./queries.js";

const fixtures = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "rust", "genesis-prnu", "tests", "fixtures", "hashing");
const manifest: {
  cases: { file: string; expect: "match" | "refused"; imageHash?: string; perceptualHash?: string }[];
} = JSON.parse(readFileSync(join(fixtures, "manifest.json"), "utf8"));

const skip = (await coreAvailable())
  ? false
  : "core's WASM is not bundled (cd core && npm run wasm, then npm run build here)";

const matches = manifest.cases.filter((c) => c.expect === "match");

test("hashes every fixture exactly as ingest/hashing.py and the verify page do", { skip }, async () => {
  assert.ok(matches.some((c) => c.file.endsWith(".jpg")), "the JPEG path must be covered");
  for (const c of matches) {
    assert.deepEqual(await hashFile(join(fixtures, c.file)), {
      imageHash: c.imageHash,
      perceptualHash: c.perceptualHash,
    }, c.file);
  }
});

test("refuses what the verify page refuses, rather than hashing it", { skip }, async () => {
  for (const c of manifest.cases.filter((x) => x.expect === "refused")) {
    await assert.rejects(() => hashFile(join(fixtures, c.file)), /Could not read/, c.file);
  }
});

test("refuses a RAW file with a way forward", { skip }, async () => {
  await assert.rejects(() => hashBytes(new Uint8Array([1, 2, 3]), "frame.CR3"), /RAW file.*Export a JPEG/s);
});

test("a missing file names the path", { skip }, async () => {
  await assert.rejects(() => hashFile("/nonexistent/genesis/photo.jpg"), /Could not read .*photo\.jpg: ENOENT/);
});

// A subgraph that knows one image, answering both the exact lookup and
// core's `nearest` (which lists every registered perceptual hash).
function subgraph(registered: ImageRecord) {
  const sent: string[] = [];
  const fetchImpl = (async (_url: string, init: { body: string }) => {
    const { query, variables } = JSON.parse(init.body);
    sent.push(query);
    const data = query.includes("images(first: 1000)")
      ? { images: [{ imageHash: registered.imageHash, perceptualHash: registered.perceptualHash }] }
      : { image: variables?.id === registered.id ? registered : null };
    return new Response(JSON.stringify({ data }), { status: 200, headers: { "content-type": "application/json" } });
  }) as unknown as typeof fetch;
  return { client: new SubgraphClient("http://stub", fetchImpl), fetchImpl, sent };
}

function record(c: (typeof matches)[number], perceptualHash = c.perceptualHash!): ImageRecord {
  return {
    id: c.imageHash!,
    imageHash: c.imageHash!,
    perceptualHash,
    modificationLevel: 0,
    pceScore: "1895",
    registeredAt: "1757000000",
    body: {
      id: "0xb5ed056e",
      owner: "0xf39fd6e5",
      bodyCommitment: "0x00",
      fingerprintCommitment: "0xbb3e3a38",
      revoked: false,
      registeredAt: "1757000000",
    },
    parent: null,
    derivatives: [],
  };
}

const jpeg = () => matches.find((c) => c.file === "jpeg_420.jpg")!;

test("a file whose pixels are registered gets the registration, keyed by its pixel hash", { skip }, async () => {
  const { client, fetchImpl, sent } = subgraph(record(jpeg()));
  const answer = describeFileCheck(await checkImageFile(join(fixtures, "jpeg_420.jpg"), client, fetchImpl));

  assert.match(answer, new RegExp(jpeg().imageHash!));
  assert.match(answer, /Registered by the owner of body 0xb5ed056e/);
  assert.match(answer, /did not leave this machine/);
  assert.ok(!/\bverified\b/i.test(answer));
  assert.equal(sent.length, 1, "an exact hit needs no perceptual query");
});

test("a near perceptual hash is reported as a lead, not a match", { skip }, async () => {
  // A registered image of other pixels whose pHash is two bits off this one's,
  // stored as the subgraph stores it: bytes32, zero-padded.
  const other = matches.find((c) => c.file !== "jpeg_420.jpg")!;
  const near = (BigInt(jpeg().perceptualHash!) ^ 0b101n).toString(16).padStart(64, "0");
  const { client, fetchImpl } = subgraph(record(other, `0x${near}`));
  const answer = describeFileCheck(await checkImageFile(join(fixtures, "jpeg_420.jpg"), client, fetchImpl));

  assert.match(answer, /No registration for these exact pixels/);
  assert.match(answer, new RegExp(`${other.imageHash}, 2 of 64 bits apart`));
  assert.match(answer, /a lead, not a match/);
  assert.match(answer, /unrelated\s+image/);
});

test("nothing near reads as nothing registered, not as fake", { skip }, async () => {
  const other = matches.find((c) => c.file !== "jpeg_420.jpg")!;
  const far = (~BigInt(jpeg().perceptualHash!) & ((1n << 64n) - 1n)).toString(16);
  const { client, fetchImpl } = subgraph(record(other, `0x${far}`));
  const answer = describeFileCheck(await checkImageFile(join(fixtures, "jpeg_420.jpg"), client, fetchImpl));

  assert.match(answer, /No record for/);
  assert.match(answer, /does not\s+mean the image is fabricated/s);
});

test("~ expands to the home directory", () => {
  assert.ok(!expandPath("~/a.jpg").startsWith("~"));
  assert.ok(expandPath("~/a.jpg").endsWith("/a.jpg"));
});

test("GENESIS_SUBGRAPH_URL wins; otherwise GENESIS_CHAIN picks, defaulting to Base mainnet", () => {
  assert.equal(subgraphUrl({ GENESIS_SUBGRAPH_URL: "http://x", GENESIS_CHAIN: "base" }), "http://x");
  assert.match(subgraphUrl({}), /v1\.0\.0-base$/);
  assert.match(subgraphUrl({ GENESIS_CHAIN: "base-sepolia" }), /base-sepolia/);
  assert.match(subgraphUrl({ GENESIS_CHAIN: "sepolia" }), /v0\.0\.5/);
  assert.throws(() => subgraphUrl({ GENESIS_CHAIN: "mainnet" }), /not one of/);
});

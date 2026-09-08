/**
 * Tests for what the agent is actually told.
 *
 * The queries are stubbed; what matters here is the wording. An agent that
 * reads "verified" will say "verified", and this system verifies nothing —
 * it says which sensor the light fell on.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SubgraphClient,
  describeBody,
  describeImage,
  describeLineage,
  type ImageRecord,
} from "./queries.js";

const BODY = {
  id: "0xb5ed056e",
  owner: "0xf39fd6e5",
  ensNode: "0xaaaa",
  fingerprintCommitment: "0xbb3e3a38",
  revoked: false,
  registeredAt: "1757000000",
};

const IMAGE: ImageRecord = {
  id: "0x2224a686",
  imageHash: "0x2224a686",
  perceptualHash: "0xe829e9b0556d25cb",
  modificationLevel: 0,
  pceScore: "1895",
  registeredAt: "1757000000",
  body: BODY,
  parent: null,
  derivatives: [],
};

function stub(payload: unknown) {
  return new SubgraphClient("http://stub", (async () =>
    new Response(JSON.stringify({ data: payload }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch);
}

test("a missing record says nothing was registered, not that the image is fake", async () => {
  const client = stub({ image: null });
  const answer = describeImage(await client.imageByHash("0xdead"), "0xdead");

  assert.match(answer, /No record/);
  assert.match(answer, /does not\s+mean the image is fabricated/s);
  for (const word of ["fake", "authentic", "AI-generated"]) {
    assert.ok(!new RegExp(`\\b${word}\\b`, "i").test(answer.replace(/fabricated/g, "")),
      `a no-match answer should not use "${word}"`);
  }
});

test("a match reports a registration, not where the light fell", async () => {
  const client = stub({ image: IMAGE });
  const answer = describeImage(await client.imageByHash(IMAGE.id), IMAGE.id);

  // `registerImage` checks only that the body's owner sent the transaction,
  // and a fingerprint can be planted from one RAW file off the body. So the
  // agent must say who registered it, never that the sensor saw the scene.
  assert.match(answer, /Registered by the owner of body/);
  assert.ok(!/exposed on/i.test(answer), "must not claim where the light fell");
  assert.ok(
    !/light fell/i.test(answer) || /does not say the light fell/i.test(answer),
    "may only mention the light to deny the claim",
  );

  assert.match(answer, /1895/);
  assert.match(answer, /fingerprint alone proves nothing/i);
  assert.match(answer, /does\s+not say the image\s+is authentic, AI-free/s);
  assert.ok(!/\bverified\b/i.test(answer), "must never say verified");
});

test("a revoked body still reports the record it made while it was valid", async () => {
  const client = stub({ image: { ...IMAGE, body: { ...BODY, revoked: true } } });
  const answer = describeImage(await client.imageByHash(IMAGE.id), IMAGE.id);

  assert.match(answer, /REVOKED/);
  assert.match(answer, /does not\s+unwrite past ones/s);
});

test("the body description never hands out the fingerprint", async () => {
  const answer = describeBody(BODY, BODY.id);

  assert.match(answer, /commitment is a hash/);
  assert.match(answer, /never published/);
  assert.ok(!/\bPRNU field\b/i.test(answer));
});

test("lineage says unregistered edits are a gap, not an absence of edits", () => {
  const answer = describeLineage(
    { ...IMAGE, derivatives: [{ id: "0xchild", modificationLevel: 1 }] },
    IMAGE.id,
  );

  assert.match(answer, /0xchild/);
  assert.match(answer, /gap in the record/);
});

test("subgraph errors surface rather than reading as an empty result", async () => {
  const failing = new SubgraphClient("http://stub", (async () =>
    new Response(JSON.stringify({ errors: [{ message: "bad query" }] }), {
      status: 200,
      headers: { "content-type": "application/json" },
    })) as unknown as typeof fetch);

  await assert.rejects(() => failing.imageByHash("0x00"), /bad query/);
});

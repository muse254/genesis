/**
 * Tests for the name arithmetic.
 *
 * This is the file where a silent bug is most expensive. A record written
 * against the wrong node still succeeds on chain, costs gas, and resolves to
 * nothing -- and the failure only shows up when a verifier looks the name up,
 * which on this project means on camera. So the node, the label rules and the
 * registry walk are pinned to literal expected values rather than recomputed
 * by the same code that produces them.
 */

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BODY_ROLES,
  ROLE,
  assertBodyLabel,
  labelOf,
  nodeFor,
  parentOf,
  subregistryPath,
} from "./ens.js";

test("the resolver node is the v1 namehash of the full name", () => {
  assert.equal(
    nodeFor("r10-4471.cam.osoro.eth"),
    "0x3533036ced2f2bc810b8f48af0e57a86d334a9612e265789b272c9292dfa8c7c",
  );
});

test("a name is normalised before it is hashed", () => {
  assert.equal(nodeFor("R10-4471.Cam.Osoro.ETH"), nodeFor("r10-4471.cam.osoro.eth"));
});

test("the registry walk runs outermost first, from ETHRegistry down", () => {
  assert.deepEqual(subregistryPath("cam.osoro.eth"), ["osoro", "cam"]);
  assert.deepEqual(subregistryPath("osoro.eth"), ["osoro"]);
});

test("only .eth names are reachable from ETHRegistry", () => {
  assert.throws(() => subregistryPath("cam.osoro.xyz"), /only \.eth names/);
  assert.throws(() => subregistryPath("eth"), /root, not a name/);
});

test("label and parent split the way the registry expects", () => {
  assert.equal(labelOf("r10-4471.cam.osoro.eth"), "r10-4471");
  assert.equal(parentOf("r10-4471.cam.osoro.eth"), "cam.osoro.eth");
  assert.throws(() => parentOf("eth"), /no parent/);
});

test("body labels are the shape the demo derives from model and serial", () => {
  assertBodyLabel("r10-4471");
  assertBodyLabel("5d3-00219");
  assert.throws(() => assertBodyLabel("R10-4471"), /not a usable body label/);
  assert.throws(() => assertBodyLabel("-r10"), /not a usable body label/);
  assert.throws(() => assertBodyLabel("r"), /not a usable body label/);
  assert.throws(() => assertBodyLabel("r10 4471"), /not a usable body label/);
});

test("a body owner can retire the name but not grow children under it", () => {
  assert.equal(BODY_ROLES & ROLE.setResolver, ROLE.setResolver);
  assert.equal(BODY_ROLES & ROLE.unregister, ROLE.unregister);
  assert.equal(BODY_ROLES & ROLE.renew, ROLE.renew);
  assert.equal(BODY_ROLES & ROLE.setSubregistry, 0n);
  assert.equal(BODY_ROLES & ROLE.registrar, 0n);
});

test("each granted role carries its admin half, so one key can also revoke", () => {
  for (const role of [ROLE.setResolver, ROLE.unregister, ROLE.renew]) {
    assert.equal(BODY_ROLES & (role << 128n), role << 128n);
  }
});

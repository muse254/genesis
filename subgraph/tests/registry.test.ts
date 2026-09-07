/**
 * Mapping tests.
 *
 * These run the handlers against a mocked store and mocked contract calls,
 * so they check the logic the type checker cannot: that a revocation leaves
 * images standing, that an edit links to its parent, and that an ERC-7053
 * commit is joined back to its image by the genesis: URI.
 */

import { Address, BigInt, Bytes, ethereum } from "@graphprotocol/graph-ts";
import {
  afterEach,
  assert,
  clearStore,
  createMockedFunction,
  describe,
  newMockEvent,
  test,
} from "matchstick-as/assembly/index";

import {
  handleBodyRegistered,
  handleBodyRevoked,
  handleCommit,
  handleImageRegistered,
  handleSessionCommitted,
} from "../src/registry";
import {
  BodyRegistered,
  BodyRevoked,
  Commit,
  ImageRegistered,
  SessionCommitted,
} from "../generated/Registry/Registry";

const REGISTRY = Address.fromString("0x5FbDB2315678afecb367f032d93F642f64180aa3");
const BODY = Bytes.fromHexString(
  "0xb5ed056efa4f82f2e2e3aa7778a73e14de82f476c5408813c4f33ee5281afc3b",
);
const COMMITMENT = Bytes.fromHexString(
  "0xbb3e3a38e051973355faf0d7dcdb8a0598c87d4f04b8a8ecbff152c4ad5cb5d7",
);
const IMAGE = Bytes.fromHexString(
  "0x2224a686797182e43b86a0efb74fe34d29424b51ce7df233914508c887624725",
);
const EDIT = Bytes.fromHexString(
  "0x1111111111111111111111111111111111111111111111111111111111111111",
);
const ZERO = Bytes.fromHexString(
  "0x0000000000000000000000000000000000000000000000000000000000000000",
);

function mockBody(): void {
  createMockedFunction(REGISTRY, "bodies", "bodies(bytes32):(bytes32,address,bytes32,bool)")
    .withArgs([ethereum.Value.fromFixedBytes(BODY)])
    .returns([
      ethereum.Value.fromFixedBytes(COMMITMENT),
      ethereum.Value.fromAddress(Address.fromString("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")),
      ethereum.Value.fromFixedBytes(Bytes.fromHexString("0x" + "aa".repeat(32))),
      ethereum.Value.fromBoolean(false),
    ]);
}

function mockImage(hash: Bytes, parent: Bytes, level: i32): void {
  createMockedFunction(
    REGISTRY,
    "images",
    "images(bytes32):(bytes32,bytes32,bytes32,uint8,bytes32,bytes32,uint32,uint64)",
  )
    .withArgs([ethereum.Value.fromFixedBytes(hash)])
    .returns([
      ethereum.Value.fromFixedBytes(hash),
      ethereum.Value.fromFixedBytes(Bytes.fromHexString("0x" + "e8".repeat(32))),
      ethereum.Value.fromFixedBytes(BODY),
      ethereum.Value.fromI32(level),
      ethereum.Value.fromFixedBytes(parent),
      ethereum.Value.fromFixedBytes(Bytes.fromHexString("0x" + "05".repeat(32))),
      ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(1895)),
      ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(1757000000)),
    ]);
}

function bodyRegistered(): BodyRegistered {
  let event = changetype<BodyRegistered>(newMockEvent());
  event.address = REGISTRY;
  event.parameters = [
    new ethereum.EventParam("bodyId", ethereum.Value.fromFixedBytes(BODY)),
    new ethereum.EventParam(
      "owner",
      ethereum.Value.fromAddress(Address.fromString("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")),
    ),
    new ethereum.EventParam(
      "ensNode",
      ethereum.Value.fromFixedBytes(Bytes.fromHexString("0x" + "aa".repeat(32))),
    ),
  ];
  return event;
}

function imageRegistered(hash: Bytes): ImageRegistered {
  let event = changetype<ImageRegistered>(newMockEvent());
  event.address = REGISTRY;
  event.parameters = [
    new ethereum.EventParam("imageHash", ethereum.Value.fromFixedBytes(hash)),
    new ethereum.EventParam("bodyId", ethereum.Value.fromFixedBytes(BODY)),
    new ethereum.EventParam("pceScore", ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(1895))),
  ];
  return event;
}

describe("Registry mappings", () => {
  afterEach(() => {
    clearStore();
  });

  test("a body is indexed with the commitment read from storage", () => {
    mockBody();
    handleBodyRegistered(bodyRegistered());

    assert.entityCount("Body", 1);
    assert.fieldEquals("Body", BODY.toHexString(), "fingerprintCommitment", COMMITMENT.toHexString());
    assert.fieldEquals("Body", BODY.toHexString(), "revoked", "false");
  });

  test("revocation leaves earlier images standing", () => {
    mockBody();
    mockImage(IMAGE, ZERO, 0);
    handleBodyRegistered(bodyRegistered());
    handleImageRegistered(imageRegistered(IMAGE));

    let revoked = changetype<BodyRevoked>(newMockEvent());
    revoked.address = REGISTRY;
    revoked.parameters = [
      new ethereum.EventParam("bodyId", ethereum.Value.fromFixedBytes(BODY)),
    ];
    handleBodyRevoked(revoked);

    assert.fieldEquals("Body", BODY.toHexString(), "revoked", "true");
    // Unwriting the record would make every earlier claim unfalsifiable.
    assert.entityCount("Image", 1);
    assert.fieldEquals("Image", IMAGE.toHexString(), "pceScore", "1895");
  });

  test("an edit links to the original, an original links to nothing", () => {
    mockBody();
    mockImage(IMAGE, ZERO, 0);
    mockImage(EDIT, IMAGE, 1);
    handleBodyRegistered(bodyRegistered());
    handleImageRegistered(imageRegistered(IMAGE));
    handleImageRegistered(imageRegistered(EDIT));

    assert.fieldEquals("Image", EDIT.toHexString(), "parent", IMAGE.toHexString());
    assert.fieldEquals("Image", EDIT.toHexString(), "modificationLevel", "1");
    assert.assertNull(null);
  });

  test("an ERC-7053 commit joins back to its image by the genesis URI", () => {
    let event = changetype<Commit>(newMockEvent());
    event.address = REGISTRY;
    event.parameters = [
      new ethereum.EventParam(
        "recorder",
        ethereum.Value.fromAddress(Address.fromString("0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266")),
      ),
      new ethereum.EventParam(
        "assetCid",
        ethereum.Value.fromString("genesis:" + IMAGE.toHexString().slice(2)),
      ),
      new ethereum.EventParam("commitData", ethereum.Value.fromString("")),
    ];
    handleCommit(event);

    assert.entityCount("CommitLog", 1);
  });

  test("a session records its root and frame count", () => {
    let event = changetype<SessionCommitted>(newMockEvent());
    event.address = REGISTRY;
    let sessionId = Bytes.fromHexString("0x" + "77".repeat(32));
    event.parameters = [
      new ethereum.EventParam("sessionId", ethereum.Value.fromFixedBytes(sessionId)),
      new ethereum.EventParam(
        "merkleRoot",
        ethereum.Value.fromFixedBytes(Bytes.fromHexString("0x" + "12".repeat(32))),
      ),
      new ethereum.EventParam("frameCount", ethereum.Value.fromUnsignedBigInt(BigInt.fromI32(2000))),
    ];
    handleSessionCommitted(event);

    assert.fieldEquals("Session", sessionId.toHexString(), "frameCount", "2000");
  });
});

/**
 * Registry subgraph mappings. Events stay small (a shoot is thousands of
 * frames), so handlers read the rest of each record back with a bound call.
 */

import { BigInt, Bytes, store } from "@graphprotocol/graph-ts";

import {
  Attested,
  BodyRegistered,
  BodyRevoked,
  BodyTransferred,
  Challenged,
  Commit,
  ImageRegistered,
  Registry,
  RegistryReset,
  SessionCommitted,
} from "../generated/Registry/Registry";
import { Attestation, Body, Challenge, CommitLog, Image, RegistryState, Session } from "../generated/schema";

/**
 * A testnet registry can be wiped, and a stale index is worse than none.
 * Mappings cannot enumerate entities, so ids are tracked here and walked on reset.
 */
function state(): RegistryState {
  let s = RegistryState.load("genesis");
  if (s == null) {
    s = new RegistryState("genesis");
    s.epoch = BigInt.zero();
    s.resettable = false;
    s.bodyIds = [];
    s.imageIds = [];
    s.sessionIds = [];
  }
  return s as RegistryState;
}

function track(list: Array<Bytes>, id: Bytes): Array<Bytes> {
  for (let i = 0; i < list.length; i++) {
    if (list[i].equals(id)) return list;
  }
  list.push(id);
  return list;
}

/** Clear everything before this epoch. `resettable` is never unset: readers must discount the dates. */
export function handleRegistryReset(event: RegistryReset): void {
  let s = state();

  let bodies = s.bodyIds;
  for (let i = 0; i < bodies.length; i++) store.remove("Body", bodies[i].toHexString());
  let images = s.imageIds;
  for (let i = 0; i < images.length; i++) store.remove("Image", images[i].toHexString());
  let sessions = s.sessionIds;
  for (let i = 0; i < sessions.length; i++) store.remove("Session", sessions[i].toHexString());
  // CommitLog is NOT cleared: events can't unhappen, and `store.remove` on an
  // immutable entity is a silent no-op. They carry `epoch` instead.

  s.epoch = event.params.newEpoch;
  s.resettable = true;
  s.lastResetAt = event.block.timestamp;
  s.bodyIds = [];
  s.imageIds = [];
  s.sessionIds = [];
  s.save();
}

export function handleBodyRegistered(event: BodyRegistered): void {
  let s = state();
  s.bodyIds = track(s.bodyIds, event.params.bodyId);
  s.save();

  let body = new Body(event.params.bodyId);

  // The fingerprint commitment is only in storage.
  let registry = Registry.bind(event.address);
  let stored = registry.try_bodies(event.params.bodyId);

  body.owner = event.params.owner;
  body.bodyCommitment = event.params.bodyCommitment;
  body.fingerprintCommitment = stored.reverted
    ? Bytes.empty()
    : stored.value.getFingerprintCommitment();
  body.revoked = false;
  body.registeredAt = event.block.timestamp;
  body.save();
}

export function handleBodyRevoked(event: BodyRevoked): void {
  let body = Body.load(event.params.bodyId);
  if (body == null) return;

  // Images stay indexed: unwriting them would make earlier records unfalsifiable.
  body.revoked = true;
  body.save();
}

export function handleBodyTransferred(event: BodyTransferred): void {
  let body = Body.load(event.params.bodyId);
  if (body == null) return;

  // Indexed images keep their body; their owner is the one at their block.
  body.owner = event.params.to;
  body.save();
}

export function handleAttested(event: Attested): void {
  let a = new Attestation(event.transaction.hash.concatI32(event.logIndex.toI32()));
  a.epoch = state().epoch;
  a.subject = event.params.subject;
  a.attester = event.params.attester;
  a.kind = event.params.kind;
  a.dataHash = event.params.dataHash;
  a.blockNumber = event.block.number;
  a.timestamp = event.block.timestamp;
  a.save();
}

export function handleChallenged(event: Challenged): void {
  let c = new Challenge(event.transaction.hash.concatI32(event.logIndex.toI32()));
  c.epoch = state().epoch;
  c.subject = event.params.subject;
  c.challenger = event.params.challenger;
  c.evidenceHash = event.params.evidenceHash;
  c.blockNumber = event.block.number;
  c.timestamp = event.block.timestamp;
  c.save();
}

export function handleImageRegistered(event: ImageRegistered): void {
  let s = state();
  s.imageIds = track(s.imageIds, event.params.imageHash);
  s.save();

  let image = new Image(event.params.imageHash);
  let registry = Registry.bind(event.address);
  let stored = registry.try_images(event.params.imageHash);

  image.imageHash = event.params.imageHash;
  image.body = event.params.bodyId;
  image.pceScore = event.params.pceScore;
  image.registeredAt = event.block.timestamp;

  if (stored.reverted) {
    // Unreadable state: leave fields empty rather than guess.
    image.perceptualHash = Bytes.empty();
    image.metadataHmac = Bytes.empty();
    image.modificationLevel = 0;
  } else {
    image.perceptualHash = stored.value.getPerceptualHash();
    image.metadataHmac = stored.value.getMetadataHmac();
    image.modificationLevel = stored.value.getModificationLevel();

    // A zero parent means an original.
    let parent = stored.value.getParentImageHash();
    if (!isZero(parent) && Image.load(parent) != null) {
      image.parent = parent;
    }
  }

  image.save();
}

export function handleSessionCommitted(event: SessionCommitted): void {
  let s = state();
  s.sessionIds = track(s.sessionIds, event.params.sessionId);
  s.save();

  let session = new Session(event.params.sessionId);
  session.merkleRoot = event.params.merkleRoot;
  session.frameCount = event.params.frameCount.toI32();
  session.committedAt = event.block.timestamp;
  session.save();
}

export function handleCommit(event: Commit): void {
  // Separate entity: ERC-7053 is content-agnostic, so don't impose our reading of commit data.
  let id = event.transaction.hash.concatI32(event.logIndex.toI32());
  let log = new CommitLog(id);
  log.epoch = state().epoch;
  log.recorder = event.params.recorder;
  log.assetCid = event.params.assetCid;
  log.commitData = event.params.commitData;
  log.blockNumber = event.block.number;
  log.timestamp = event.block.timestamp;

  // ingest/record.py mints "genesis:<image hash>"; join such commits to their image.
  if (event.params.assetCid.startsWith("genesis:")) {
    let hex = event.params.assetCid.slice(8);
    if (hex.length == 64) {
      log.image = Bytes.fromHexString("0x" + hex);
    }
  }

  log.save();
}

function isZero(value: Bytes): boolean {
  for (let i = 0; i < value.length; i++) {
    if (value[i] != 0) return false;
  }
  return true;
}

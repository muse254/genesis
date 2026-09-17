/**
 * AssemblyScript mappings for the Registry subgraph.
 *
 * Two Graph tracks come out of this one body of work: the subgraph itself,
 * and the MCP server in ../mcp that puts it in front of an agent.
 *
 * The events carry only what is cheap to log — an image event has the hash,
 * the body and the score. The rest of the record lives in contract storage,
 * so the handlers read it back with a bound call. That costs an eth_call per
 * registration at index time and keeps the events small, which is the right
 * trade when a shoot is two thousand frames.
 */

import { BigInt, Bytes, store } from "@graphprotocol/graph-ts";

import {
  BodyRegistered,
  BodyRevoked,
  Commit,
  ImageRegistered,
  Registry,
  RegistryReset,
  SessionCommitted,
} from "../generated/Registry/Registry";
import { Body, CommitLog, Image, RegistryState, Session } from "../generated/schema";

/**
 * The registry can be wiped on a testnet, and an index that outlived the
 * chain is worse than no index: it would answer for records that no longer
 * exist, and `lookup_body` would hand an agent a body the chain has never
 * heard of.
 *
 * Graph mappings cannot enumerate entities, so ids are tracked as they are
 * written and walked on reset. The lists grow with the registry, which is
 * fine for one that exists to be reset.
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

/**
 * Clear everything written before this epoch.
 *
 * `resettable` is set to true and never unset: a registry that has admitted
 * once that it can be wiped should not look pristine afterwards, and a reader
 * deciding what a registration date is worth needs to know.
 */
export function handleRegistryReset(event: RegistryReset): void {
  let s = state();

  let bodies = s.bodyIds;
  for (let i = 0; i < bodies.length; i++) store.remove("Body", bodies[i].toHexString());
  let images = s.imageIds;
  for (let i = 0; i < images.length; i++) store.remove("Image", images[i].toHexString());
  let sessions = s.sessionIds;
  for (let i = 0; i < sessions.length; i++) store.remove("Session", sessions[i].toHexString());
  // CommitLog is deliberately NOT cleared. It records events, a reset cannot
  // unhappen an event, and the entity is immutable so `store.remove` would be
  // a silent no-op anyway. They carry `epoch` instead.

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

  // The event has the owner and the camera commitment; the fingerprint
  // commitment is storage.
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

  // Revocation stops future claims. The images stay indexed, because
  // unwriting them would make every earlier record unfalsifiable.
  body.revoked = true;
  body.save();
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
    // Indexing a chain whose state we cannot read would silently produce
    // records that claim less than the contract does, so say so instead.
    image.perceptualHash = Bytes.empty();
    image.metadataHmac = Bytes.empty();
    image.modificationLevel = 0;
  } else {
    image.perceptualHash = stored.value.getPerceptualHash();
    image.metadataHmac = stored.value.getMetadataHmac();
    image.modificationLevel = stored.value.getModificationLevel();

    // A zero parent means an original. Anything else is an edit, and the
    // link is what turns a list of records into an edit graph.
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
  // ERC-7053 is deliberately content-agnostic: it indexes assertions and
  // declines to say whether they are true. Kept as its own entity so an
  // indexer following only the standard sees the same log we do, without
  // inheriting our opinion about what the commit data means.
  let id = event.transaction.hash.concatI32(event.logIndex.toI32());
  let log = new CommitLog(id);
  log.epoch = state().epoch;
  log.recorder = event.params.recorder;
  log.assetCid = event.params.assetCid;
  log.commitData = event.params.commitData;
  log.blockNumber = event.block.number;
  log.timestamp = event.block.timestamp;

  // The local URI ingest/record.py mints is "genesis:<image hash>", so a
  // commit that came from registerImage can be joined back to its image.
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

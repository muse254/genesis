/**
 * The record a hash resolves to, and the wording every surface uses for it
 * (`docs/claims.md`): a score is strength of evidence, with who computed it,
 * when, and the threshold beside it. Never a verdict.
 */
import { describe, expect, it, vi } from "vitest";

import type { BodyRecord, ChainReader, ImageRecord } from "../src/chain";
import * as wording from "../src/record";
import { HASH_SCOPE, NO_RECORD, ORIGIN_CAVEAT, PCE_THRESHOLD, readRecord, scoreNote, scoreValue } from "../src/record";

const REGISTRY = "0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB" as const;
const HASH = `0x${"6e".repeat(32)}` as const;
const BODY = `0x${"65".repeat(32)}` as const;
const OWNER = "0xc0b60Ce1d7EfAc453Cd0D5BC1783b9B28972625A" as const;
const TX = `0x${"aa".repeat(32)}` as const;
const REGISTERED_AT = 1_791_890_447;

const IMAGE: ImageRecord = {
  imageHash: HASH,
  perceptualHash: "0x000000000000000000000000000000000000000000000000909b017ca32f5d9b",
  bodyId: BODY,
  modificationLevel: 0,
  parentImageHash: `0x${"0".repeat(64)}`,
  pceScore: 123821,
  registeredAt: REGISTERED_AT,
};

function chain(images: Record<string, ImageRecord>, body: Partial<BodyRecord> = {}): ChainReader {
  return {
    registry: REGISTRY,
    chainId: 8453,
    explorer: "https://basescan.org",
    image: async (hash) => images[hash] ?? null,
    body: async () => ({ fingerprintCommitment: `0x${"22".repeat(32)}`, owner: OWNER, bodyCommitment: `0x${"0".repeat(64)}`, revoked: false, ...body }),
    registrationTx: vi.fn(async () => ({ txHash: TX, from: OWNER, to: REGISTRY })),
    testMode: async () => false,
    ensName: async () => null,
  };
}

/** A CommitLog id is the tx hash followed by the log index. */
const graph = (txHash: string | null) =>
  vi.fn(async () => new Response(JSON.stringify({ data: { commitLogs: txHash ? [{ id: `${txHash}fe010000` }] : [] } }))) as unknown as typeof fetch;

/** Every string the module exports, plus the generated ones: the whole vocabulary. */
const allWording = () => [
  ...Object.values(wording).filter((v): v is string => typeof v === "string"),
  scoreNote(REGISTERED_AT),
  scoreValue(123821),
];

describe("wording", () => {
  it("never claims more than claims.md allows", () => {
    for (const text of allWording()) {
      for (const banned of [/authentic/i, /\bverified\b/i, /AI-free/i, /proves? origin/i, /probability(?<!not a probability)/i]) {
        expect(text, `"${text}" uses ${banned}`).not.toMatch(banned);
      }
      // "verdict" only to deny it.
      expect(text.replace(/not a verdict/g, "")).not.toMatch(/verdict/i);
    }
  });

  it("calls the score strength of evidence, says who computed it and when, and is not a probability", () => {
    const note = scoreNote(REGISTERED_AT);
    expect(note).toMatch(/^Strength of evidence, not a verdict/);
    expect(note).toMatch(/not a probability/);
    expect(note).toMatch(/owner computed this score on their own machine/);
    expect(note).toContain("2026-10-13");
    expect(note).toMatch(/does not recompute it/);
    expect(note).toMatch(/not proof of origin/);
  });

  it("shows the threshold beside the score", () => {
    expect(PCE_THRESHOLD).toBe(100);
    expect(scoreValue(123821)).toBe("123821 against a threshold of 100");
  });

  it("says an unknown hash means no record, not a finding", () => {
    expect(NO_RECORD).toMatch(/^No registration matches/);
    expect(NO_RECORD).toMatch(/not that the image is fake/);
    expect(HASH_SCOPE).toMatch(/does not check a file you hold/);
    expect(ORIGIN_CAVEAT).toMatch(/Origin, not truth/);
  });
});

describe("readRecord", () => {
  it("refuses a malformed hash before reading anything", async () => {
    const reader = chain({ [HASH]: IMAGE });
    for (const bad of ["", "0x1234", HASH.toUpperCase(), `${HASH}00`, `${HASH.slice(0, -1)}g`, ` ${HASH}`]) {
      await expect(readRecord(reader, bad)).rejects.toThrow(/malformed/);
    }
  });

  it("answers no record for an unknown hash", async () => {
    const view = await readRecord(chain({}), HASH);
    expect(view).toMatchObject({ registered: false, imageHash: HASH, note: NO_RECORD, testMode: false, chainId: 8453 });
  });

  it("returns the chain's record with the score note, and the tx the index located and the chain confirmed", async () => {
    const reader = chain({ [HASH]: IMAGE });
    const fetch = graph(TX);
    const view = await readRecord(reader, HASH, "https://graph.example", fetch);
    expect(view).toMatchObject({
      registered: true,
      owner: OWNER,
      bodyId: BODY,
      bodyRevoked: false,
      pceScore: 123821,
      threshold: 100,
      registeredAt: REGISTERED_AT,
      parentImageHash: null,
      txHash: TX,
      txUrl: `https://basescan.org/tx/${TX}`,
      verifyUrl: `https://muse254.github.io/genesis/verify/?hash=${HASH}`,
      registry: REGISTRY,
      source: wording.SOURCE,
    });
    expect(reader.registrationTx).toHaveBeenCalledWith(HASH, TX);
    expect(view.registered && view.pceScoreNote).toBe(scoreNote(REGISTERED_AT));
  });

  it("keeps the record when the index is down; only the tx hash is lost", async () => {
    const down = vi.fn(async () => { throw new TypeError("network down"); }) as unknown as typeof fetch;
    const view = await readRecord(chain({ [HASH]: IMAGE }, { revoked: true }), HASH, "https://graph.example", down);
    expect(view).toMatchObject({ registered: true, txHash: null, txUrl: null, owner: OWNER, bodyRevoked: true });
  });

  it("keeps the record when the receipt read fails", async () => {
    const reader = chain({ [HASH]: IMAGE });
    reader.registrationTx = async () => { throw new Error("request limit reached"); };
    const view = await readRecord(reader, HASH, "https://graph.example", graph(TX));
    expect(view).toMatchObject({ registered: true, txHash: null, owner: OWNER });
  });

  it("links the verify page only for the registry that page reads", async () => {
    const unknown = await readRecord(chain({}), HASH);
    expect(unknown.verifyUrl).toBe(`https://muse254.github.io/genesis/verify/?hash=${HASH}`);
    const testnet = { ...chain({}), chainId: 84532, registry: "0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2" as const };
    expect((await readRecord(testnet, HASH)).verifyUrl).toBeNull();
  });

  it("does not trust the index: no log on chain means no tx hash", async () => {
    const reader = chain({ [HASH]: IMAGE });
    reader.registrationTx = async () => null;
    const view = await readRecord(reader, HASH, "https://graph.example", graph(TX));
    expect(view.registered && view.txHash).toBeNull();
  });
});

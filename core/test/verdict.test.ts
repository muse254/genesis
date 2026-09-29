/**
 * The verdict rules in src/verify.ts, with the pixel work, the chain and The
 * Graph faked. Hashing and scoring have their own tests against Python
 * (hashes.test.ts, analyse.test.ts); these check that each verdict is
 * reached only on the evidence it claims -- above all, that nothing but a
 * chain read grants `registered`, and that a failed chain read withholds
 * the verdict instead of downgrading it.
 */
import { describe, expect, it, vi } from "vitest";

import type { Analysis, Candidate } from "../src/analyse";
import type { BodyRecord, ChainReader, ImageRecord } from "../src/chain";
import type { Engine } from "../src/engine";
import { verify, type VerifyOptions } from "../src/verify";

const IMAGE = `0x${"ab".repeat(32)}` as const;
const PARENT = `0x${"cd".repeat(32)}` as const;
const BODY = `0x${"11".repeat(32)}` as const;
const OWNER = "0x00000000000000000000000000000000000000a1" as const;
const PHASH = "0x00000000000000ff" as const;
const SUBGRAPH = "https://graph.example/genesis";

const photo = (name = "photo.jpg") => new File([new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3])], name);

function candidate(pce: number, extra: Partial<Candidate> = {}): Candidate {
  return {
    bodyId: BODY.slice(2),
    name: "canon-r10",
    pce,
    path: "aligned",
    orientation: "0 deg",
    scale: null,
    borderStripped: null,
    turned: null,
    attempts: [],
    ...extra,
  };
}

function engine(candidates: Candidate[] = [], signals: Analysis["signals"] = null): Engine & { calls: unknown[] } {
  const calls: unknown[] = [];
  return {
    calls,
    loadBody: async () => ({ crop: null }),
    analyse: async (request) => {
      calls.push(request);
      return { imageHash: IMAGE, perceptualHash: PHASH, threshold: 100, candidates, signals };
    },
  };
}

function record(hash: `0x${string}`, level = 0): ImageRecord {
  return { imageHash: hash, perceptualHash: PHASH, bodyId: BODY, modificationLevel: level as 0, pceScore: 812, registeredAt: 1_750_000_000 };
}

function chain(images: Record<string, ImageRecord> = {}, opts: { failOn?: string; testMode?: boolean } = {}): ChainReader {
  const body: BodyRecord = { fingerprintCommitment: `0x${"22".repeat(32)}`, owner: OWNER, bodyCommitment: `0x${"0".repeat(64)}`, revoked: false };
  return {
    registry: "0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2",
    explorerUrl: "https://sepolia.basescan.org/address/0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2",
    image: async (hash) => {
      if (opts.failOn === hash) throw new Error("rpc down");
      return images[hash] ?? null;
    },
    body: async () => body,
    testMode: async () => opts.testMode ?? false,
    ensName: async () => null,
  };
}

/** A fetch for The Graph that serves `images` and records every request. */
function graph(images: { imageHash: string; perceptualHash: string }[] | "down") {
  const sent: string[] = [];
  const fetch = vi.fn(async (url: string | URL | Request) => {
    sent.push(String(url));
    if (images === "down") throw new TypeError("network down");
    return new Response(JSON.stringify({ data: { images } }));
  }) as unknown as typeof globalThis.fetch;
  return { fetch, sent };
}

const flip = (hash: string, bits: number) => `0x${(BigInt(hash) ^ ((1n << BigInt(bits)) - 1n)).toString(16).padStart(16, "0")}`;
const bodies = [{ id: BODY.slice(2), name: "canon-r10", crop: null }];

async function run(file: File, options: Partial<VerifyOptions>) {
  return verify(file, { engine: engine(), ...options });
}

describe("the web page: no enrolled bodies", () => {
  it("is `registered` on an exact pixel-hash hit, with the owner read off the chain", async () => {
    const result = await run(photo(), { chain: chain({ [IMAGE]: record(IMAGE, 1) }) });
    expect(result).toMatchObject({
      verdict: "registered",
      registered: true,
      body: { bodyId: BODY, owner: OWNER, revoked: false },
      registration: { registeredAt: 1_750_000_000, modificationLevel: 1, pceAtRegistration: 812 },
      derivedFrom: null,
      pce: null,
      stages: [],
      resettableRegistry: false,
    });
  });

  it("flags a resettable test registry", async () => {
    const result = await run(photo(), { chain: chain({ [IMAGE]: record(IMAGE) }, { testMode: true }) });
    expect(result.resettableRegistry).toBe(true);
  });

  it("is `derived` when The Graph finds a near pHash and the chain confirms the parent", async () => {
    const { fetch } = graph([{ imageHash: PARENT, perceptualHash: flip(PHASH, 3) }]);
    const result = await run(photo(), { chain: chain({ [PARENT]: record(PARENT) }), subgraphUrl: SUBGRAPH, fetch });
    expect(result).toMatchObject({
      verdict: "derived",
      registered: true,
      derivedFrom: { imageHash: PARENT, hammingDistance: 3, matchedBy: "perceptual hash" },
    });
  });

  it("picks the nearest of several perceptual candidates", async () => {
    const NEARER = `0x${"ee".repeat(32)}` as const;
    const { fetch } = graph([
      { imageHash: PARENT, perceptualHash: flip(PHASH, 6) },
      { imageHash: NEARER, perceptualHash: flip(PHASH, 2) },
    ]);
    const result = await run(photo(), {
      chain: chain({ [PARENT]: record(PARENT), [NEARER]: record(NEARER) }),
      subgraphUrl: SUBGRAPH,
      fetch,
    });
    expect(result.derivedFrom).toMatchObject({ imageHash: NEARER, hammingDistance: 2 });
  });

  it("ignores a perceptual match beyond 10 bits", async () => {
    const { fetch } = graph([{ imageHash: PARENT, perceptualHash: flip(PHASH, 11) }]);
    const result = await run(photo(), { chain: chain({ [PARENT]: record(PARENT) }), subgraphUrl: SUBGRAPH, fetch });
    expect(result.verdict).toBe("no-record");
  });

  it("does not trust the index: a pHash hit the chain has no record of is `no-record`", async () => {
    const { fetch } = graph([{ imageHash: PARENT, perceptualHash: PHASH }]);
    const result = await run(photo(), { chain: chain(), subgraphUrl: SUBGRAPH, fetch });
    expect(result.verdict).toBe("no-record");
  });

  it("survives The Graph being down", async () => {
    const { fetch } = graph("down");
    const result = await run(photo(), { chain: chain(), subgraphUrl: SUBGRAPH, fetch });
    expect(result.verdict).toBe("no-record");
  });

  it("is `no-record` with nothing configured", async () => {
    const result = await run(photo(), {});
    expect(result).toMatchObject({ verdict: "no-record", registered: false, threshold: 100, diagnosis: null });
  });

  it("withholds the verdict when the chain cannot answer, rather than downgrading it", async () => {
    await expect(run(photo(), { chain: chain({}, { failOn: IMAGE }) })).rejects.toThrow(/chain read failed, verdict withheld: rpc down/);
  });

  it("withholds it too when the perceptual parent cannot be read", async () => {
    const { fetch } = graph([{ imageHash: PARENT, perceptualHash: PHASH }]);
    await expect(
      run(photo(), { chain: chain({}, { failOn: PARENT }), subgraphUrl: SUBGRAPH, fetch }),
    ).rejects.toThrow(/verdict withheld/);
  });

  it("refuses RAW without a decoder, and says where it can be checked", async () => {
    await expect(run(photo("frame.CR3"), {})).rejects.toThrow(/desktop app/);
  });

  it("asks the engine to score against no bodies, and sends the photo nowhere", async () => {
    const e = engine();
    const { fetch, sent } = graph([]);
    await verify(photo(), { engine: e, chain: chain(), subgraphUrl: SUBGRAPH, fetch });
    expect(e.calls).toEqual([expect.objectContaining({ bodies: [] })]);
    expect(sent).toEqual([SUBGRAPH]); // the pHash query, and nothing else
  });
});

describe("the desktop: enrolled bodies", () => {
  it("is `fingerprint-only` on a PRNU match with nothing on chain -- never a pass", async () => {
    const result = await run(photo(), { engine: engine([candidate(4210)]), chain: chain(), bodies });
    expect(result).toMatchObject({
      verdict: "fingerprint-only",
      registered: false,
      pce: 4210,
      method: "aligned",
      body: { bodyId: BODY.slice(2), name: "canon-r10" },
      registration: null,
    });
    expect(result.stages.map((s) => s.result)).toEqual(["match", null, "no registration"]);
  });

  it("never lets a PRNU match raise a verdict without the chain", async () => {
    const result = await run(photo(), { engine: engine([candidate(99_999)]), bodies });
    expect(result.verdict).toBe("fingerprint-only");
    expect(result.registered).toBe(false);
  });

  it("names the local body when the registered image is one of ours", async () => {
    const result = await run(photo(), { engine: engine([candidate(812)]), chain: chain({ [IMAGE]: record(IMAGE) }), bodies });
    expect(result).toMatchObject({ verdict: "registered", body: { bodyId: BODY, name: "canon-r10", owner: OWNER } });
    expect(result.stages[2].result).toBe("registered");
  });

  it("reports the scale-search details of the best body", async () => {
    const best = candidate(3115, { path: "scale search", orientation: "mirrored, 0 deg", scale: 1.02, borderStripped: "1920x1280 to 1800x1200" });
    const result = await run(photo(), { engine: engine([best, candidate(12)]), chain: chain(), bodies });
    expect(result).toMatchObject({ method: "scale search", orientation: "mirrored, 0 deg", scale: 1.02, borderStripped: "1920x1280 to 1800x1200" });
    expect(result.stages[1].result).toBeNull();
  });

  it("diagnoses a no-record from the signals, as the desktop did", async () => {
    const signals = { calibrated: false, bodyConsistency: null, pooledTriangle: null, effectiveStrength: null, resamplingPeak: 3, detail: 7.7, tooSoftToMeasure: true } as const;
    const result = await run(photo(), { engine: engine([candidate(44.9)], signals), chain: chain(), bodies });
    expect(result.verdict).toBe("no-record");
    expect(result.diagnosis).toMatch(/median tile 7.7/);
    expect(result.consistency).toEqual(signals);
  });

  it("decodes a RAW through the desktop's decoder, once, for every crop the bodies need", async () => {
    const rawDecoder = vi.fn(async () => ({ rgb: new Uint8Array(3), width: 1, height: 1, planes: {} }));
    const e = engine([candidate(812)]);
    await verify(photo("frame.CR3"), {
      engine: e,
      bodies: [...bodies, { id: "b2", name: "other", crop: 512 }, { id: "b3", name: "third", crop: null }],
      rawDecoder,
    });
    expect(rawDecoder).toHaveBeenCalledOnce();
    expect(rawDecoder.mock.calls[0][1]).toEqual([null, 512]);
    expect(e.calls[0]).toMatchObject({ raw: { width: 1, height: 1 } });
  });

  it("reports progress through to the chain read", async () => {
    const steps: [string, number][] = [];
    await run(photo(), { engine: engine([candidate(812)]), chain: chain(), bodies, onStep: (l, f) => steps.push([l, f]) });
    expect(steps.at(-1)).toEqual(["reading the chain", 0.97]);
  });
});

// @vitest-environment happy-dom
/**
 * The verdict logic in src/main.ts, with hashing, the chain and The Graph
 * stubbed out. Hashing has its own tests (hashes.test.ts). These check that
 * each verdict is reached only on the evidence it claims, and that the photo
 * leaves the browser only when a scoring service has been configured.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const IMAGE = `0x${"ab".repeat(32)}` as const;
const PARENT = `0x${"cd".repeat(32)}` as const;
const BODY = `0x${"11".repeat(32)}` as const;
const OWNER = "0x00000000000000000000000000000000000000a1";
const PHASH = "0x00000000000000ff";
const ZERO = `0x${"0".repeat(64)}`;

vi.mock("../src/hashes", () => ({
  hashImage: vi.fn(async () => ({ imageHash: IMAGE, perceptualHash: PHASH })),
}));

/** The chain: `images` keyed by pixel hash, plus one body. */
let images: Record<string, readonly unknown[]> = {};
let testMode = false;

vi.mock("viem", async (actual) => ({
  ...(await actual<typeof import("viem")>()),
  createPublicClient: () => ({
    readContract: async ({ functionName, args }: { functionName: string; args?: string[] }) => {
      if (functionName === "images") {
        return images[args![0]] ?? [ZERO, ZERO, ZERO, 0, ZERO, ZERO, 0, 0n];
      }
      if (functionName === "bodies") return [ZERO, OWNER, ZERO, false];
      if (functionName === "testMode") return testMode;
      throw new Error(`unexpected read ${functionName}`);
    },
    getEnsName: async () => null,
    getEnsAddress: async () => null,
  }),
}));

function registered(hash: string, pce = 812, level = 0) {
  images[hash] = [hash, PHASH, BODY, level, ZERO, ZERO, pce, 1_750_000_000n];
}

/** Stub fetch for The Graph and a scoring service; record what was sent. */
let sent: { url: string; body: unknown }[] = [];
let subgraphImages: { imageHash: string; perceptualHash: string }[] = [];
let lookupResponse: unknown;

function flip(hash: string, bits: number): string {
  return `0x${(BigInt(hash) ^ ((1n << BigInt(bits)) - 1n)).toString(16).padStart(16, "0")}`;
}

async function load(env: Record<string, string>) {
  vi.resetModules();
  for (const [key, value] of Object.entries(env)) vi.stubEnv(key, value);
  return import("../src/main");
}

const photo = () => new File([new Uint8Array([0xff, 0xd8, 0xff, 1, 2, 3])], "photo.jpg");
const CHAIN = { VITE_REGISTRY_ADDRESS: "0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2", VITE_CHAIN: "base-sepolia" };
const GRAPH = { VITE_SUBGRAPH_URL: "https://graph.example/genesis" };

beforeEach(() => {
  images = {};
  testMode = false;
  sent = [];
  subgraphImages = [];
  lookupResponse = undefined;
  // Blank everything a developer's verify/.env might set, so each test
  // sees only the configuration it passes to load().
  for (const key of ["VITE_SCORING_URL", "VITE_RPC_URL", "VITE_REGISTRY_ADDRESS", "VITE_CHAIN", "VITE_SUBGRAPH_URL"]) {
    vi.stubEnv(key, "");
  }
  vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
    sent.push({ url: String(url), body: init?.body });
    if (String(url).startsWith(GRAPH.VITE_SUBGRAPH_URL)) {
      return new Response(JSON.stringify({ data: { images: subgraphImages } }));
    }
    if (String(url).endsWith("/lookup")) return new Response(JSON.stringify(lookupResponse));
    return new Response("not found", { status: 404 });
  });
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

describe("without a scoring service (GitHub Pages)", () => {
  it("never sends the photo anywhere", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    subgraphImages = [{ imageHash: PARENT, perceptualHash: PHASH }];
    registered(PARENT);

    await verifyImage(photo());

    expect(sent.length).toBeGreaterThan(0);
    for (const { url, body } of sent) {
      expect(body).not.toBeInstanceOf(FormData);
      expect(url).not.toMatch(/127\.0\.0\.1|localhost/);
    }
  });

  it("is `registered` on an exact pixel-hash hit, with the owner read off the chain", async () => {
    const { verifyImage } = await load(CHAIN);
    registered(IMAGE, 812, 1);

    const result = await verifyImage(photo());

    expect(result).toMatchObject({
      verdict: "registered",
      registered: true,
      owner: OWNER,
      pceScore: 812,
      modificationLevel: 1,
      method: "pixel hash",
      resettableRegistry: false,
    });
  });

  it("flags a resettable test registry", async () => {
    const { verifyImage } = await load(CHAIN);
    registered(IMAGE);
    testMode = true;

    expect((await verifyImage(photo())).resettableRegistry).toBe(true);
  });

  it("is `derived` when The Graph finds a near pHash and the chain confirms the parent", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    subgraphImages = [{ imageHash: PARENT, perceptualHash: flip(PHASH, 3) }];
    registered(PARENT);

    const result = await verifyImage(photo());

    expect(result).toMatchObject({
      verdict: "derived",
      registered: true,
      derivedFrom: { imageHash: PARENT, hammingDistance: 3 },
    });
  });

  it("picks the nearest of several perceptual candidates", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    const NEARER = `0x${"ee".repeat(32)}`;
    subgraphImages = [
      { imageHash: PARENT, perceptualHash: flip(PHASH, 6) },
      { imageHash: NEARER, perceptualHash: flip(PHASH, 2) },
    ];
    registered(PARENT);
    registered(NEARER);

    expect((await verifyImage(photo())).derivedFrom).toEqual({ imageHash: NEARER, hammingDistance: 2 });
  });

  it("ignores a perceptual match beyond 10 bits", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    subgraphImages = [{ imageHash: PARENT, perceptualHash: flip(PHASH, 11) }];
    registered(PARENT);

    expect((await verifyImage(photo())).verdict).toBe("no-record");
  });

  it("does not trust the index: a pHash hit the chain has no record of is `no-record`", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    subgraphImages = [{ imageHash: PARENT, perceptualHash: PHASH }];

    expect((await verifyImage(photo())).verdict).toBe("no-record");
  });

  it("is `no-record` when nothing is configured, making no requests at all", async () => {
    const { verifyImage } = await load({});

    expect(await verifyImage(photo())).toMatchObject({ verdict: "no-record", registered: false, threshold: 100 });
    expect(sent).toEqual([]);
  });

  it("survives The Graph being down", async () => {
    const { verifyImage } = await load({ ...CHAIN, ...GRAPH });
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("network down");
    });

    expect((await verifyImage(photo())).verdict).toBe("no-record");
  });
});

describe("with a scoring service (local demo)", () => {
  const SCORING = { VITE_SCORING_URL: "http://127.0.0.1:8000" };

  it("posts the photo to /lookup, and nowhere else", async () => {
    const { verifyImage } = await load({ ...SCORING, ...CHAIN, ...GRAPH });
    lookupResponse = { imageHash: IMAGE, perceptualHash: PHASH, threshold: 100, verdict: "no-match", candidates: [] };

    await verifyImage(photo());

    const uploads = sent.filter(({ body }) => body instanceof FormData);
    expect(uploads.map(({ url }) => url)).toEqual(["http://127.0.0.1:8000/lookup"]);
  });

  it("is `fingerprint-only` on a PRNU match with nothing on chain -- never a pass", async () => {
    const { verifyImage } = await load({ ...SCORING, ...CHAIN });
    lookupResponse = {
      imageHash: IMAGE,
      perceptualHash: PHASH,
      threshold: 100,
      verdict: "match",
      candidates: [{ bodyId: BODY, body: "r10", pce: 4210, path: "aligned", orientation: "0 deg" }],
    };

    expect(await verifyImage(photo())).toMatchObject({
      verdict: "fingerprint-only",
      registered: false,
      bodyName: "r10",
      pceScore: 4210,
    });
  });

  it("uses the locally computed hashes for the chain, not the service's", async () => {
    const { verifyImage } = await load({ ...SCORING, ...CHAIN });
    registered(IMAGE);
    lookupResponse = { imageHash: PARENT, perceptualHash: "0x0", threshold: 100, verdict: "no-match", candidates: [] };

    expect((await verifyImage(photo())).verdict).toBe("registered");
  });

  it("reports a failing service instead of a verdict", async () => {
    const { verifyImage } = await load(SCORING);
    vi.stubGlobal("fetch", async () => new Response("boom", { status: 502 }));

    await expect(verifyImage(photo())).rejects.toThrow(/scoring service: 502/);
  });
});

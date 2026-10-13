/**
 * Registry reads and the perceptual index: ports of `console/chain.py` and
 * `console/subgraph.py`. The desktop passes its loopback proxy URL so an RPC
 * API key stays out of the webview.
 */

import { createPublicClient, http, type Address, type Chain } from "viem";
import { anvil, base, baseSepolia, sepolia } from "viem/chains";

/** Same keys as `GENESIS_CHAIN` in `console/chain.py`. */
export const CHAINS = { base, "base-sepolia": baseSepolia, sepolia, anvil } as const satisfies Record<string, Chain>;
export type ChainKey = keyof typeof CHAINS;

export interface ImageRecord {
  imageHash: `0x${string}`;
  perceptualHash: `0x${string}`;
  bodyId: `0x${string}`;
  modificationLevel: 0 | 1 | 2;
  pceScore: number;
  /** Unix seconds. */
  registeredAt: number;
}

export interface BodyRecord {
  fingerprintCommitment: `0x${string}`;
  owner: `0x${string}`;
  /** Keyed camera commitment; all zeros when none was committed. */
  bodyCommitment: `0x${string}`;
  revoked: boolean;
}

export interface ChainReader {
  registry: Address;
  /** `{explorer}/address/{registry}`, for linking a registration. */
  explorerUrl?: string;
  /** `images(bytes32)`; null for a hash nobody registered. Throws if the RPC cannot answer. */
  image(hash: `0x${string}`): Promise<ImageRecord | null>;
  /** `bodies(bytes32)`; null for a body nobody registered. */
  body(bodyId: `0x${string}`): Promise<BodyRecord | null>;
  /** `testMode()`: whether the registry can be wiped. False for a registry predating the flag. */
  testMode(): Promise<boolean>;
  /** A reverse ENS name that forward-resolves to `owner`, or null. Never throws. */
  ensName(owner: `0x${string}`): Promise<string | null>;
}

const REGISTRY_ABI = [
  {
    type: "function",
    name: "images",
    stateMutability: "view",
    inputs: [{ name: "", type: "bytes32" }],
    outputs: [
      { name: "imageHash", type: "bytes32" },
      { name: "perceptualHash", type: "bytes32" },
      { name: "bodyId", type: "bytes32" },
      { name: "modificationLevel", type: "uint8" },
      { name: "parentImageHash", type: "bytes32" },
      { name: "metadataHmac", type: "bytes32" },
      { name: "pceScore", type: "uint32" },
      { name: "registeredAt", type: "uint64" },
    ],
  },
  {
    type: "function",
    name: "bodies",
    stateMutability: "view",
    inputs: [{ name: "", type: "bytes32" }],
    outputs: [
      { name: "fingerprintCommitment", type: "bytes32" },
      { name: "owner", type: "address" },
      { name: "bodyCommitment", type: "bytes32" },
      { name: "revoked", type: "bool" },
    ],
  },
  { type: "function", name: "testMode", stateMutability: "view", inputs: [], outputs: [{ name: "", type: "bool" }] },
] as const;

const isZero = (word: string) => /^0x0*$/.test(word);

export interface ChainConfig {
  rpcUrl: string;
  chain: ChainKey;
  registry: Address;
  /** Block explorer base URL, e.g. https://sepolia.basescan.org */
  explorer?: string;
}

export function createChainReader(config: ChainConfig): ChainReader {
  const client = createPublicClient({ chain: CHAINS[config.chain] ?? anvil, transport: http(config.rpcUrl) });
  const address = config.registry;
  let testMode: Promise<boolean> | undefined;

  return {
    registry: address,
    explorerUrl: config.explorer ? `${config.explorer}/address/${address}` : undefined,

    async image(hash) {
      const r = await client.readContract({ address, abi: REGISTRY_ABI, functionName: "images", args: [hash] });
      // Unregistered reads back zeroed, not as an error. This check is the
      // only thing that may produce `registered`.
      if (isZero(r[0])) return null;
      return {
        imageHash: r[0],
        perceptualHash: r[1],
        bodyId: r[2],
        modificationLevel: Number(r[3]) as 0 | 1 | 2,
        pceScore: Number(r[6]),
        registeredAt: Number(r[7]),
      };
    },

    async body(bodyId) {
      const r = await client.readContract({ address, abi: REGISTRY_ABI, functionName: "bodies", args: [bodyId] });
      if (isZero(r[0])) return null;
      return { fingerprintCommitment: r[0], owner: r[1], bodyCommitment: r[2], revoked: r[3] };
    },

    testMode() {
      // Immutable in the contract, so asked once.
      testMode ??= client
        .readContract({ address, abi: REGISTRY_ABI, functionName: "testMode" })
        .catch(() => false); // a registry predating the flag cannot be reset
      return testMode;
    },

    async ensName(owner) {
      // A reverse record is self-asserted: count it only if it forward-resolves
      // to the same address. Throws on chains without ENS (Base).
      try {
        const name = await client.getEnsName({ address: owner });
        if (!name) return null;
        const forward = await client.getEnsAddress({ name });
        return forward && forward.toLowerCase() === owner.toLowerCase() ? name : null;
      } catch {
        return null;
      }
    },
  };
}

/**
 * Bits of the 64-bit pHash allowed to differ (`console/subgraph.py`). Slack,
 * not tuned: real photos move 0 bits from 1800px q95 to 400px q60 (`docs/gates.md`
 * Gate B). Wider attaches registrations to unrelated photos.
 */
export const MAX_HAMMING = 10;

export interface NearMatch {
  imageHash: `0x${string}`;
  hammingDistance: number;
}

/**
 * Indexed images within `MAX_HAMMING`, nearest first. Candidates only: each must
 * be confirmed on chain. Empty when the index fails: that costs a link, never a verdict.
 */
export async function nearAll(
  subgraphUrl: string,
  perceptualHash: string,
  fetchImpl: typeof fetch = fetch,
): Promise<NearMatch[]> {
  let images: { imageHash: `0x${string}`; perceptualHash: string }[];
  try {
    const response = await fetchImpl(subgraphUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query: "{ images(first: 1000) { imageHash perceptualHash } }" }),
    });
    if (!response.ok) return [];
    const payload = (await response.json()) as { data?: { images?: typeof images }; errors?: unknown };
    if (payload.errors) return [];
    images = payload.data?.images ?? [];
  } catch {
    return [];
  }

  const target = BigInt(perceptualHash);
  const matches: NearMatch[] = [];
  for (const image of images) {
    let bits = target ^ BigInt(image.perceptualHash);
    let distance = 0;
    for (; bits; bits >>= 1n) distance += Number(bits & 1n);
    if (distance <= MAX_HAMMING) matches.push({ imageHash: image.imageHash, hammingDistance: distance });
  }
  return matches.sort((a, b) => a.hammingDistance - b.hammingDistance);
}

export async function nearest(
  subgraphUrl: string,
  perceptualHash: string,
  fetchImpl: typeof fetch = fetch,
): Promise<NearMatch | null> {
  return (await nearAll(subgraphUrl, perceptualHash, fetchImpl))[0] ?? null;
}

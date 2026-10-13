/**
 * The record for one image hash, read off the registry, and every sentence any
 * surface says about it. Shared by the verify page's `?hash=` mode and the read
 * API (`api/`), so the two cannot word the score differently (`docs/claims.md`).
 *
 * Neither holds K, so neither recomputes the score: `pceScore` is what the owner
 * computed at registration and the contract does not check (`docs/security.md`).
 */

import type { ChainReader } from "./chain";

/** `prnu.py`'s `PCE_THRESHOLD`, `pce_threshold()` in the WASM. No WASM here: the API is a Worker. */
export const PCE_THRESHOLD = 100;

/** The only form of hash accepted from a URL; anything else is refused unread. */
export const IMAGE_HASH = /^0x[0-9a-f]{64}$/;

export const MODIFICATION_LEVELS = ["unedited raw", "adjusted", "generative edit"] as const;

const ZERO = `0x${"0".repeat(64)}` as const;

/** The public verify page reads only this registry, so it is the only one `verifyUrl` may point at. */
export const MAINNET_REGISTRY = "0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB";
export const VERIFY_PAGE = "https://muse254.github.io/genesis/verify/";

/** Where a partner links "Check this copy": the verify page at this hash, or null off the mainnet registry. */
export function verifyUrl(chain: Pick<ChainReader, "registry" | "chainId">, hash: string): string | null {
  return chain.chainId === 8453 && chain.registry.toLowerCase() === MAINNET_REGISTRY.toLowerCase()
    ? `${VERIFY_PAGE}?hash=${hash}`
    : null;
}

export type ImageRecordView =
  | {
      registered: false;
      imageHash: `0x${string}`;
      registry: `0x${string}`;
      chainId: number;
      testMode: boolean;
      verifyUrl: string | null;
      source: string;
      note: string;
    }
  | {
      registered: true;
      imageHash: `0x${string}`;
      perceptualHash: `0x${string}`;
      bodyId: `0x${string}`;
      bodyRevoked: boolean;
      /** The address that registered it: `msg.sender`, which the contract required to own the body. */
      owner: `0x${string}`;
      /** Unix seconds, from the block. */
      registeredAt: number;
      pceScore: number;
      threshold: number;
      pceScoreNote: string;
      modificationLevel: 0 | 1 | 2;
      /** Null for an original. */
      parentImageHash: `0x${string}` | null;
      registry: `0x${string}`;
      chainId: number;
      testMode: boolean;
      /** Null when the index could not find it; the record above still came from the contract. */
      txHash: `0x${string}` | null;
      /** The registration on the block explorer; null without `txHash`. */
      txUrl: string | null;
      verifyUrl: string | null;
      source: string;
    };

export const SOURCE = "confirmed on chain: Registry.images(imageHash) read from the contract";

/** Same words as an unknown file on the verify page: absence means nothing. */
export const NO_RECORD = "No registration matches this image. That means we have no record — not that the image is fake.";

/** The verify page's `?hash=` mode checks a hash, not the visitor's file. */
export const HASH_SCOPE =
  "This shows the record for that hash. It does not check a file you hold: to check your own copy, choose it below.";

export const ORIGIN_CAVEAT =
  "Origin, not truth. The owner of this body signed for this image at the time shown. That does not say the scene was real.";

export const REVOKED = "revoked — the owner withdrew this body. Records made before that still stand.";

export const scoreValue = (pce: number, threshold = PCE_THRESHOLD) => `${pce} against a threshold of ${threshold}`;

/** Who computed the score and when, and what it is not. Every surface that shows `pceScore` shows this beside it. */
export function scoreNote(registeredAt: number): string {
  const day = new Date(registeredAt * 1000).toISOString().slice(0, 10);
  return (
    "Strength of evidence, not a verdict and not a probability. The owner computed this score on their own " +
    `machine, against their own camera's fingerprint, when they registered the photograph on ${day}. ` +
    "The contract does not check it, and Genesis does not recompute it: it holds no fingerprint. " +
    "A score is evidence of a link to the camera, not proof of origin."
  );
}

/**
 * The record for `hash`, confirmed against the contract. The subgraph only
 * locates the transaction; a failed index costs the tx hash, never the record.
 * Throws for a malformed hash and when the chain cannot answer.
 */
export async function readRecord(
  chain: ChainReader,
  hash: string,
  subgraphUrl?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ImageRecordView> {
  if (!IMAGE_HASH.test(hash)) throw new Error("malformed image hash: expected 0x and 64 lowercase hex digits");
  const imageHash = hash as `0x${string}`;
  const [record, testMode] = await Promise.all([chain.image(imageHash), chain.testMode()]);
  const common = {
    imageHash,
    registry: chain.registry,
    chainId: chain.chainId,
    testMode,
    verifyUrl: verifyUrl(chain, imageHash),
    source: SOURCE,
  };
  if (!record) return { registered: false, ...common, note: NO_RECORD };

  const [body, tx] = await Promise.all([
    chain.body(record.bodyId),
    findTx(chain, imageHash, subgraphUrl, fetchImpl),
  ]);
  // A direct call's sender is `msg.sender`, the owner at the time. Without the
  // tx, the current owner: the same unless the body was transferred since.
  const owner = tx && tx.to?.toLowerCase() === chain.registry.toLowerCase() ? tx.from : body?.owner;
  if (!owner) throw new Error(`chain has image ${imageHash} but no body ${record.bodyId}`);

  return {
    registered: true,
    perceptualHash: record.perceptualHash,
    bodyId: record.bodyId,
    bodyRevoked: body?.revoked ?? false,
    owner,
    registeredAt: record.registeredAt,
    pceScore: record.pceScore,
    threshold: PCE_THRESHOLD,
    pceScoreNote: scoreNote(record.registeredAt),
    modificationLevel: record.modificationLevel,
    parentImageHash: record.parentImageHash === ZERO ? null : record.parentImageHash,
    ...common,
    txHash: tx?.txHash ?? null,
    txUrl: tx && chain.explorer ? `${chain.explorer}/tx/${tx.txHash}` : null,
  };
}

/**
 * The index names the tx (a `CommitLog` id is the tx hash and log index); its
 * receipt on chain confirms it. Any failure here costs the tx hash, never the record.
 */
async function findTx(chain: ChainReader, hash: `0x${string}`, subgraphUrl: string | undefined, fetchImpl: typeof fetch) {
  if (!subgraphUrl) return null;
  try {
    const response = await fetchImpl(subgraphUrl, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        query: "query($id: String!) { commitLogs(where: { image: $id }, orderBy: blockNumber, first: 1) { id } }",
        variables: { id: hash },
      }),
    });
    const payload = (await response.json()) as { data?: { commitLogs?: { id: string }[] } };
    const id = payload.data?.commitLogs?.[0]?.id;
    return id ? await chain.registrationTx(hash, id.slice(0, 66) as `0x${string}`) : null;
  } catch (error) {
    console.warn(`tx lookup for ${hash} failed:`, error instanceof Error ? error.message.split("\n")[0] : error);
    return null;
  }
}

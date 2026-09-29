/**
 * Verification for the desktop app: `@genesis/core`, the same code the web
 * page runs (`docs/shared-verify-plan.md`), fed with what only this machine
 * has.
 *
 * - The enrolled K files, from the console (`GET /bodies/{id}/fingerprint`),
 *   loaded into core's worker once per session. They never leave this
 *   machine: the console is on loopback and answers only this app.
 * - RAW decoding, which is LibRaw's job and LibRaw has no WASM build
 *   (`POST /raw/develop`, `POST /raw/planes`).
 * - The chain and The Graph, read through the console's read-only proxies
 *   (`/rpc`, `/subgraph`) so a key in either URL stays out of this webview.
 *
 * The verdict is core's. Nothing here decides anything.
 */

import {
  createChainReader,
  cropKey,
  verify,
  workerEngine,
  type ChainKey,
  type LoadedBody,
  type RawInput,
  type VerifyResult as CoreVerifyResult,
} from "@genesis/core";

import { api, BASE } from "./api";

/** The desktop always has enrolled bodies, so it always has a score. */
export type VerifyResult = CoreVerifyResult & { pce: number };

const engine = workerEngine();
// Compile the WASM while the operator is still choosing a file.
engine.warm().catch(() => {});

/** Bodies already in the worker, by id. */
const loaded = new Map<string, Promise<LoadedBody>>();

async function enrolledBodies(): Promise<LoadedBody[]> {
  const response = await fetch(`${BASE}/bodies`);
  if (!response.ok) throw new Error(`bodies: ${response.status}`);
  const bodies = (await response.json()) as { id: string; name: string; crop: number | null }[];

  return Promise.all(
    bodies.map((body) => {
      if (!loaded.has(body.id)) {
        const loading = (async () => {
          const k = await fetch(`${BASE}/bodies/${body.id}/fingerprint`);
          if (!k.ok) throw new Error(`fingerprint ${body.name}: ${k.status}`);
          const { crop } = await engine.loadBody(body.id, body.name, new Uint8Array(await k.arrayBuffer()));
          return { id: body.id, name: body.name, crop };
        })();
        // A failed load is retried on the next verification, not cached.
        loading.catch(() => loaded.delete(body.id));
        loaded.set(body.id, loading);
      }
      return loaded.get(body.id)!;
    }),
  );
}

async function decodeRaw(file: File, crops: (number | null)[]): Promise<RawInput> {
  const post = (route: string, fields: Record<string, string> = {}) => {
    const form = new FormData();
    form.append("file", file);
    for (const [key, value] of Object.entries(fields)) form.append(key, value);
    return fetch(`${BASE}${route}`, { method: "POST", body: form }).then(async (response) => {
      if (!response.ok) throw new Error(`${route}: ${response.status} ${await response.text()}`);
      return response;
    });
  };

  const developed = await post("/raw/develop");
  const planes: Record<string, Uint8Array> = {};
  for (const crop of crops) {
    const response = await post("/raw/planes", { crop: cropKey(crop) });
    planes[cropKey(crop)] = new Uint8Array(await response.arrayBuffer());
  }
  return {
    rgb: new Uint8Array(await developed.arrayBuffer()),
    width: Number(developed.headers.get("X-Width")),
    height: Number(developed.headers.get("X-Height")),
    planes,
  };
}

/** Verify a photo, reporting progress as `(label, fraction)`. */
export async function verifyStreaming(
  file: File,
  onStep: (label: string, fraction: number) => void,
): Promise<VerifyResult> {
  const [state, bodies] = await Promise.all([api.state(), enrolledBodies()]);
  if (bodies.length === 0) throw new Error("no enrolled fingerprints");

  const config = state.verify;
  const chain = config?.registry
    ? createChainReader({
        rpcUrl: `${BASE}/rpc`,
        chain: config.chain as ChainKey,
        registry: config.registry as `0x${string}`,
        explorer: config.explorer,
      })
    : undefined;

  const result = await verify(file, {
    engine,
    chain,
    subgraphUrl: config?.subgraph ? `${BASE}/subgraph` : undefined,
    bodies,
    rawDecoder: decodeRaw,
    onStep,
  });
  return result as VerifyResult;
}

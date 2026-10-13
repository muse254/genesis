/**
 * `GET /v1/images/{imageHash}`: the registry's record for one image hash, as
 * JSON, for a partner's server. Reads the contract through `core/`, the same
 * code and wording as the verify page's `?hash=` mode. Holds no K, so it never
 * recomputes a score (`docs/security.md`).
 */

import { createChainReader, type ChainKey } from "../../core/src/chain";
import { IMAGE_HASH, readRecord } from "../../core/src/record";

const ROUTE = /^\/v1\/images\/([^/]+)$/;

/** Bump whenever the response gains or changes a field: cached answers are kept a year. */
const SHAPE = 2;

const CORS = {
  "access-control-allow-origin": "*",
  "access-control-allow-methods": "GET, OPTIONS",
  "access-control-max-age": "86400",
};

function json(body: unknown, status: number, cache: string): Response {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", "cache-control": cache, ...CORS },
  });
}

export default {
  async fetch(request, env, ctx): Promise<Response> {
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: CORS });
    if (request.method !== "GET") return json({ error: "method not allowed" }, 405, "no-store");

    const url = new URL(request.url);
    const match = ROUTE.exec(url.pathname);
    if (!match) return json({ error: "not found", routes: ["GET /v1/images/{imageHash}"] }, 404, "public, max-age=3600");
    const hash = match[1];
    if (!IMAGE_HASH.test(hash)) {
      return json({ error: "malformed image hash: expected 0x and 64 lowercase hex digits" }, 400, "public, max-age=86400");
    }

    const cache = caches.default;
    const key = new Request(`${url.origin}${url.pathname}?shape=${SHAPE}`);
    const hit = await cache.match(key);
    if (hit) return hit;

    const { success } = await env.LIMITER.limit({ key: request.headers.get("cf-connecting-ip") ?? "unknown" });
    if (!success) {
      return new Response(JSON.stringify({ error: "rate limited: 60 requests a minute per client" }), {
        status: 429,
        headers: { "content-type": "application/json", "retry-after": "60", ...CORS },
      });
    }

    const chain = createChainReader({
      rpcUrl: env.RPC_URL.split(","),
      chain: env.CHAIN as ChainKey,
      registry: env.REGISTRY_ADDRESS as `0x${string}`,
    });
    let view;
    try {
      view = await readRecord(chain, hash, env.SUBGRAPH_URL);
    } catch (error) {
      // Withheld, never downgraded to "no record".
      return json({ error: `chain read failed, record withheld: ${(error as Error).message.split("\n")[0]}` }, 502, "no-store");
    }

    // A mainnet record never changes. A missing one may appear later; a test registry can be wiped.
    // The tx hash comes from the index, so an answer without one is not final either.
    const final = view.registered && !view.testMode && view.txHash !== null;
    const response = json(view, 200, final ? "public, max-age=31536000, immutable" : "public, max-age=60");
    ctx.waitUntil(cache.put(key, response.clone()));
    return response;
  },
} satisfies ExportedHandler<Env>;

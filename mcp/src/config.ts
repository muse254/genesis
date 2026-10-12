/**
 * Which subgraph the server reads.
 *
 * `GENESIS_SUBGRAPH_URL` wins when set. Otherwise `GENESIS_CHAIN` (the same
 * keys as the console and verify page: base | base-sepolia | sepolia |
 * anvil) picks the published deployment for that chain, defaulting to
 * base-sepolia, the registry this project currently points at.
 */

export const CHAIN_SUBGRAPHS: Record<string, string | null> = {
  // The Colosseum rehearsal registry (verify/.env.example).
  "base-sepolia": "https://api.studio.thegraph.com/query/1758974/genesis/v0.1.0-base-sepolia",
  // Production. Not deployed yet: set GENESIS_SUBGRAPH_URL once it is.
  base: null,
  // The ETHOnline deployment, still readable.
  sepolia: "https://api.studio.thegraph.com/query/1758974/genesis/v0.0.5",
  // contracts/script/local-e2e.sh with a local graph-node.
  anvil: "http://127.0.0.1:8000/subgraphs/name/genesis",
};

export const DEFAULT_CHAIN = "base-sepolia";

export function subgraphUrl(env: Record<string, string | undefined> = process.env): string {
  if (env.GENESIS_SUBGRAPH_URL) return env.GENESIS_SUBGRAPH_URL;

  const chain = env.GENESIS_CHAIN || DEFAULT_CHAIN;
  if (!(chain in CHAIN_SUBGRAPHS)) {
    throw new Error(
      `GENESIS_CHAIN=${chain} is not one of ${Object.keys(CHAIN_SUBGRAPHS).join(", ")}.`,
    );
  }
  const url = CHAIN_SUBGRAPHS[chain];
  if (!url) {
    throw new Error(
      `No subgraph is published for GENESIS_CHAIN=${chain} yet. Set GENESIS_SUBGRAPH_URL to one.`,
    );
  }
  return url;
}

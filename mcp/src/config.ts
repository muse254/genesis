/** `GENESIS_SUBGRAPH_URL` wins; otherwise `GENESIS_CHAIN` picks a published deployment (default base). */

export const CHAIN_SUBGRAPHS: Record<string, string | null> = {
  // Production registry (README, "Deployments").
  base: "https://api.studio.thegraph.com/query/1758974/genesis/v1.0.0-base",
  // A test registry whose records can be wiped.
  "base-sepolia": "https://api.studio.thegraph.com/query/1758974/genesis/v0.1.0-base-sepolia",
  // Older registry, still readable.
  sepolia: "https://api.studio.thegraph.com/query/1758974/genesis/v0.0.5",
  // contracts/script/local-e2e.sh with a local graph-node.
  anvil: "http://127.0.0.1:8000/subgraphs/name/genesis",
};

export const DEFAULT_CHAIN = "base";

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

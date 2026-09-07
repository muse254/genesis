/**
 * Subgraph MCP server — the second Graph track.
 *
 * Nearly free once the subgraph exists, and it makes the product
 * conversational: an agent can ask whether an image is registered and get a
 * verdict back, rather than a human loading a web page.
 *
 * Read-only by construction. There is no tool here that registers anything:
 * registration needs the fingerprint, which never leaves the photographer's
 * machine, so an agent could not do it even if it wanted to.
 *
 *   GENESIS_SUBGRAPH_URL=https://... node dist/server.js
 */

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import {
  SubgraphClient,
  describeBody,
  describeImage,
  describeLineage,
} from "./queries.js";

export const tools = [
  {
    name: "verify_image",
    description:
      "Given an image hash or URL, return its provenance record: which camera body exposed it, at what confidence, and when it was registered. Reports origin only — never authenticity.",
  },
  {
    name: "lookup_body",
    description:
      "Resolve an ENS body name (e.g. r10-4471.cam.osoro.eth) to its registry record, including revocation status.",
  },
  {
    name: "image_lineage",
    description:
      "Walk parentImageHash to return the edit graph for an image: its original and every registered derivative.",
  },
];

const SUBGRAPH_URL =
  process.env.GENESIS_SUBGRAPH_URL ?? "http://127.0.0.1:8000/subgraphs/name/genesis";

export function createServer(client = new SubgraphClient(SUBGRAPH_URL)): McpServer {
  const server = new McpServer({ name: "genesis", version: "0.1.0" });

  const text = (body: string) => ({ content: [{ type: "text" as const, text: body }] });

  server.tool(
    "verify_image",
    tools[0].description,
    {
      hash: z
        .string()
        .describe("Pixel SHA-256 of the image, 0x-prefixed. Use the scoring service to compute it."),
    },
    async ({ hash }) => text(describeImage(await client.imageByHash(hash), hash)),
  );

  server.tool(
    "lookup_body",
    tools[1].description,
    {
      body: z
        .string()
        .describe("A body id, or the namehash of an ENS name such as r10-4471.cam.osoro.eth"),
    },
    async ({ body }) =>
      text(describeBody((await client.bodyById(body)) ?? (await client.bodyByEnsNode(body)), body)),
  );

  server.tool(
    "image_lineage",
    tools[2].description,
    { hash: z.string().describe("Pixel SHA-256 of the image, 0x-prefixed.") },
    async ({ hash }) => text(describeLineage(await client.imageByHash(hash), hash)),
  );

  return server;
}

export async function verifyImage(hash: string, client = new SubgraphClient(SUBGRAPH_URL)) {
  return describeImage(await client.imageByHash(hash), hash);
}

export async function lookupBody(query: string, client = new SubgraphClient(SUBGRAPH_URL)) {
  const record = (await client.bodyById(query)) ?? (await client.bodyByEnsNode(query));
  return describeBody(record, query);
}

export async function imageLineage(hash: string, client = new SubgraphClient(SUBGRAPH_URL)) {
  return describeLineage(await client.imageByHash(hash), hash);
}

// Only start a transport when this file *is* the program. A looser check
// (matching on basename, say) makes the server boot inside the test runner,
// where it hangs waiting on a stdio transport that nothing is speaking to.
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const server = createServer();
  await server.connect(new StdioServerTransport());
}

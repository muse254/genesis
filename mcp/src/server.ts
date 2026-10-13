/**
 * Subgraph MCP server. Read-only by construction: registering needs K, which
 * never leaves the photographer's machine. Setup: mcp/README.md.
 */

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { subgraphUrl } from "./config.js";
import { checkImageFile, describeFileCheck } from "./image.js";
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
      "Look up a camera body's registry record, including revocation status, by body id or by its camera commitment.",
  },
  {
    name: "image_lineage",
    description:
      "Walk parentImageHash to return the edit graph for an image: its original and every registered derivative.",
  },
  {
    name: "verify_image_file",
    description:
      "Given the path of an image file on this machine (JPEG, PNG or TIFF), hash it locally exactly as the public verify page does and return its provenance record, or the nearest registered image by perceptual hash. The file never leaves the machine. Reports origin only — never authenticity.",
  },
];

// Lazy, so importing this module (tests) never throws over configuration.
let defaultClient: SubgraphClient | undefined;
const client = () => (defaultClient ??= new SubgraphClient(subgraphUrl()));

export function createServer(client = new SubgraphClient(subgraphUrl())): McpServer {
  const server = new McpServer({ name: "genesis", version: "0.1.0" });

  const text = (body: string) => ({ content: [{ type: "text" as const, text: body }] });

  server.tool(
    "verify_image",
    tools[0].description,
    {
      hash: z
        .string()
        .describe("Pixel SHA-256 of the image, 0x-prefixed. The verify page computes it in the browser (core/'s hashImage)."),
    },
    async ({ hash }) => text(describeImage(await client.imageByHash(hash), hash)),
  );

  server.tool(
    "lookup_body",
    tools[1].description,
    {
      body: z
        .string()
        .describe("A body id, or a camera commitment (python -m ingest commit-body), 0x-prefixed"),
    },
    async ({ body }) =>
      text(describeBody((await client.bodyById(body)) ?? (await client.bodyByCommitment(body)), body)),
  );

  server.tool(
    "image_lineage",
    tools[2].description,
    { hash: z.string().describe("Pixel SHA-256 of the image, 0x-prefixed.") },
    async ({ hash }) => text(describeLineage(await client.imageByHash(hash), hash)),
  );

  server.tool(
    "verify_image_file",
    tools[3].description,
    {
      path: z
        .string()
        .describe("Absolute path (or ~/...) of a JPEG, PNG or TIFF on this machine. RAW files are refused: export one first."),
    },
    async ({ path }) => text(describeFileCheck(await checkImageFile(path, client))),
  );

  return server;
}

export async function verifyImage(hash: string, subgraph = client()) {
  return describeImage(await subgraph.imageByHash(hash), hash);
}

export async function lookupBody(query: string, subgraph = client()) {
  const record = (await subgraph.bodyById(query)) ?? (await subgraph.bodyByCommitment(query));
  return describeBody(record, query);
}

export async function imageLineage(hash: string, subgraph = client()) {
  return describeLineage(await subgraph.imageByHash(hash), hash);
}

export async function verifyImageFile(path: string, subgraph = client()) {
  return describeFileCheck(await checkImageFile(path, subgraph));
}

// Exact path check: a looser one boots the server inside the test runner, which then hangs on stdio.
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  const server = createServer();
  await server.connect(new StdioServerTransport());
}

/**
 * Subgraph MCP server — the second Graph track.
 *
 * Nearly free once the subgraph exists, and it makes the product
 * conversational: an agent can ask whether an image is registered and get a
 * verdict back, rather than a human loading a web page.
 */

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

export async function verifyImage(): Promise<never> {
  throw new Error("not implemented");
}

export async function lookupBody(): Promise<never> {
  throw new Error("not implemented");
}

export async function imageLineage(): Promise<never> {
  throw new Error("not implemented");
}

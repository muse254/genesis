/** Subgraph queries and everything an agent is told: origin, never authenticity (`docs/claims.md`). */

export interface BodyRecord {
  id: string;
  owner: string;
  /** Keyed commitment to make, model and serial; zero when none was committed. */
  bodyCommitment: string;
  fingerprintCommitment: string;
  revoked: boolean;
  registeredAt: string;
}

export interface ImageRecord {
  id: string;
  imageHash: string;
  perceptualHash: string;
  modificationLevel: number;
  pceScore: string;
  registeredAt: string;
  body: BodyRecord;
  parent: { id: string } | null;
  derivatives: { id: string; modificationLevel: number }[];
}

const IMAGE_FIELDS = `
  id
  imageHash
  perceptualHash
  modificationLevel
  pceScore
  registeredAt
  body { id owner bodyCommitment fingerprintCommitment revoked registeredAt }
  parent { id }
  derivatives { id modificationLevel }
`;

export class SubgraphClient {
  constructor(
    readonly url: string,
    private readonly fetchImpl: typeof fetch = fetch,
  ) {}

  async query<T>(query: string, variables: Record<string, unknown>): Promise<T> {
    const response = await this.fetchImpl(this.url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ query, variables }),
    });

    if (!response.ok) {
      throw new Error(`subgraph ${response.status}: ${await response.text()}`);
    }

    const body = (await response.json()) as { data?: T; errors?: { message: string }[] };
    if (body.errors?.length) {
      throw new Error(`subgraph: ${body.errors.map((e) => e.message).join("; ")}`);
    }
    if (!body.data) throw new Error("subgraph returned no data");
    return body.data;
  }

  async imageByHash(hash: string): Promise<ImageRecord | null> {
    const data = await this.query<{ image: ImageRecord | null }>(
      `query Image($id: ID!) { image(id: $id) { ${IMAGE_FIELDS} } }`,
      { id: hash.toLowerCase() },
    );
    return data.image;
  }

  /** Exact pHash equality only; Hamming search is core/'s `nearest`, client-side. */
  async imagesByPerceptualHash(hash: string, limit = 10): Promise<ImageRecord[]> {
    const data = await this.query<{ images: ImageRecord[] }>(
      `query ByPHash($hash: Bytes!, $limit: Int!) {
         images(where: { perceptualHash: $hash }, first: $limit) { ${IMAGE_FIELDS} }
       }`,
      { hash: hash.toLowerCase(), limit },
    );
    return data.images;
  }

  /** The body a revealed camera commitment belongs to: where a dispute starts. */
  async bodyByCommitment(commitment: string): Promise<BodyRecord | null> {
    const data = await this.query<{ bodies: BodyRecord[] }>(
      `query ByCommitment($commitment: Bytes!) {
         bodies(where: { bodyCommitment: $commitment }, first: 1) {
           id owner bodyCommitment fingerprintCommitment revoked registeredAt
         }
       }`,
      { commitment: commitment.toLowerCase() },
    );
    return data.bodies[0] ?? null;
  }

  async bodyById(id: string): Promise<BodyRecord | null> {
    const data = await this.query<{ body: BodyRecord | null }>(
      `query Body($id: ID!) {
         body(id: $id) { id owner bodyCommitment fingerprintCommitment revoked registeredAt }
       }`,
      { id: id.toLowerCase() },
    );
    return data.body;
  }
}

const LEVELS = ["unedited", "adjusted (exposure, white balance, crop)", "generative edit"];

/** Every sentence is load-bearing: an agent repeats what it reads, so never say "verified". */
export function describeImage(record: ImageRecord | null, hash: string): string {
  if (!record) {
    return [
      `No record for ${hash}.`,
      "",
      "This means nothing has been registered under that hash. It does not",
      "mean the image is fabricated, and it does not mean it was not taken",
      "on a camera. Most photographs in the world are unregistered.",
    ].join("\n");
  }

  const lines = [
    // Not "exposed on body X": `registerImage` checks only the sender, and a
    // fingerprint can be planted (docs/adversarial.md, docs/claims.md).
    `Registered by the owner of body ${record.body.id}`,
    `  Owner                ${record.body.owner}`,
    `  PCE score            ${record.pceScore}`,
    `  Modification level   ${LEVELS[record.modificationLevel] ?? record.modificationLevel}`,
    `  First registered     ${new Date(Number(record.registeredAt) * 1000).toISOString()}`,
  ];

  if (record.body.revoked) {
    lines.push(
      "",
      "  This body has been REVOKED — sold, stolen, or retired. The record",
      "  above still stands: revocation stops future claims and does not",
      "  unwrite past ones.",
    );
  }

  if (record.parent) {
    lines.push("", `  Derived from ${record.parent.id}`);
  }
  if (record.derivatives.length) {
    lines.push(`  ${record.derivatives.length} registered derivative(s)`);
  }

  lines.push(
    "",
    "Two things are certified here and nothing else. That this registration",
    "exists on chain, signed by the body's owner, at the time shown. And that",
    "these pixels carry that body's fingerprint at the PCE above.",
    "",
    "The fingerprint alone proves nothing: anyone holding one RAW file off a",
    "body can plant it in an image the camera never took, invisibly. So this",
    "does not say the light fell on that sensor, and it does not say the image",
    "is authentic, AI-free, or that the scene was real.",
  );

  return lines.join("\n");
}

export function describeBody(record: BodyRecord | null, query: string): string {
  if (!record) return `No body registered under ${query}.`;

  return [
    `Body ${record.id}`,
    `  Camera commitment      ${record.bodyCommitment}`,
    `  Owner                  ${record.owner}`,
    `  Fingerprint commitment ${record.fingerprintCommitment}`,
    `  Status                 ${record.revoked ? "REVOKED" : "active"}`,
    `  Registered             ${new Date(Number(record.registeredAt) * 1000).toISOString()}`,
    "",
    "The commitment is a hash of the sensor fingerprint. The fingerprint",
    "itself is never published: anyone holding it could forge images that",
    "this registry would then attribute to this camera.",
  ].join("\n");
}

export function describeLineage(record: ImageRecord | null, hash: string): string {
  if (!record) return `No record for ${hash}, so no lineage.`;

  const lines = [`Lineage for ${record.id}`];
  lines.push(
    record.parent
      ? `  Derived from   ${record.parent.id}`
      : "  Original       no registered parent",
  );

  if (record.derivatives.length === 0) {
    lines.push("  Derivatives    none registered");
  } else {
    lines.push("  Derivatives:");
    for (const child of record.derivatives) {
      lines.push(`    ${child.id}  (${LEVELS[child.modificationLevel] ?? child.modificationLevel})`);
    }
  }

  lines.push(
    "",
    "Only registered edits appear here. An edit nobody registered is invisible",
    "to this graph, which is a gap in the record rather than evidence that no",
    "edit happened.",
  );
  return lines.join("\n");
}

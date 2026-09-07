/**
 * Verify page — both branches of Flow C.
 *
 *   image → SHA-256 of pixel data → exact hit?
 *            ├ yes → record                      (untouched file)
 *            └ no  → pHash lookup → candidates
 *                    → PRNU re-score against that body
 *                    → verdict + confidence
 *
 * The lower branch is the differentiator, and demo step 4 rides on it:
 * a registered photo, stripped of metadata, resized, re-encoded as a web
 * JPEG — and it still resolves.
 */

export type Verdict = "exact" | "perceptual" | "no-match";

export interface VerifyResult {
  verdict: Verdict;
  bodyName?: string; // e.g. r10-4471.cam.osoro.eth
  pceScore?: number;
  modificationLevel?: 0 | 1 | 2;
  registeredAt?: string;
}

export async function verifyImage(_file: File): Promise<VerifyResult> {
  throw new Error("not implemented");
}

/** Exact branch: pixel hash straight to the subgraph. */
async function lookupByPixelHash(_hash: string) {
  throw new Error("not implemented");
}

/** Perceptual branch: pHash candidates, then re-score against each body. */
async function lookupByPerceptualHash(_hash: string) {
  throw new Error("not implemented");
}

function render(_result: VerifyResult): void {
  throw new Error("not implemented");
}

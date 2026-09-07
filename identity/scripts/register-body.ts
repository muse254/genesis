/**
 * Register a camera body as an ENSv2 subname and write its resolver records.
 *
 *   r10-4471.cam.osoro.eth
 *     ├ fingerprintCommitment
 *     ├ signing key
 *     └ revocation status
 *
 * Nothing here may be hardcoded on the demo path -- ENS's prize criteria
 * require live registration and live resolution.
 */

import { createWalletClient, http } from "viem";
import { sepolia } from "viem/chains";

export interface BodySubname {
  label: string; // "r10-4471"
  parent: string; // "cam.osoro.eth"
  fingerprintCommitment: `0x${string}`;
  signingKey: `0x${string}`;
}

export async function registerBody(_body: BodySubname): Promise<`0x${string}`> {
  throw new Error("not implemented");
}

export async function setBodyRecords(_body: BodySubname): Promise<void> {
  throw new Error("not implemented");
}

export async function resolveBody(_name: string): Promise<BodySubname | null> {
  throw new Error("not implemented");
}

export async function revokeBody(_name: string): Promise<void> {
  throw new Error("not implemented");
}

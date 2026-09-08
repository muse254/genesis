/**
 * ENSv2 on Sepolia: the pinned addresses, the ABI fragments we call, and the
 * pure name arithmetic.
 *
 * ENSv2 is not v1 with new addresses. There is no flat `registry.owner(node)`
 * table: every name owns a *subregistry*, and a child lives in its parent's
 * subregistry. So `r10-4471.cam.osoro.eth` is a name registered in the
 * subregistry of `cam.osoro.eth`, which is a name in the subregistry of
 * `osoro.eth`, which is a name in `ETHRegistry`. Walking that chain is what
 * `subregistryPath` describes and what the caller has to do before it can
 * register anything.
 *
 * Resolver records still key off the v1 `namehash`, which is why both
 * coordinate systems appear here: namehash to address a record, and the
 * registry walk to address the name.
 *
 * The ABI fragments are copied from the verified sources at the addresses
 * below, read from Blockscout on 8 September 2026. They are fragments on
 * purpose -- the full ABIs run to eighty entries and the surface we actually
 * touch is this small. `identity/addresses.md` is the note on why these
 * addresses move and must be re-checked on the day.
 */

import type { Address } from "viem";
import { namehash, normalize } from "viem/ens";

/**
 * An address from the environment, falling back to the pinned value.
 *
 * `??` is not enough. `.env` carries these keys declared but blank, and an
 * empty string is a perfectly good `string` -- it sails through the nullish
 * check and becomes an empty `to` address, which the RPC rejects as "Invalid
 * params" from four frames away from the actual mistake. Treat blank as unset.
 */
function envAddress(name: string, pinned: string): Address {
  const value = process.env[name]?.trim();
  return (value ? value : pinned) as Address;
}

/**
 * Sepolia ENSv2, pinned. Overridable by environment because the beta
 * redeploys: `addresses.md` is explicit that a table written a week earlier
 * is not to be trusted, and hardcoding is how the demo breaks silently.
 */
export const ENS = {
  ethRegistry: envAddress("ENS_ETH_REGISTRY", "0xbdc85dd5b15d7ecb354cd7cb6f2c50b4f2c4f0e2"),
  resolver: envAddress("ENS_PERMISSIONED_RESOLVER", "0x9eae5c2730a7dd16bdd1dee6421a1b91e3b0365e"),
  ethRegistrar: envAddress("ENS_ETH_REGISTRAR", "0xa88553f454b77203b0d036a05c894d555eaaa2cc"),
  universalResolver: envAddress(
    "ENS_UNIVERSAL_RESOLVER_V2",
    "0x4a1817d13e9cf196f471725176355c1234b63c70",
  ),
} as const;

/**
 * `RegistryRolesLib` roles, as nybble-packed bitmaps. Each role is one nybble;
 * its admin counterpart sits 128 bits higher and implies the regular role.
 */
export const ROLE = {
  registrar: 1n << 0n,
  unregister: 1n << 12n,
  renew: 1n << 16n,
  setSubregistry: 1n << 20n,
  setResolver: 1n << 24n,
} as const;

const asAdmin = (role: bigint) => role << 128n;

/**
 * What a body subname's owner gets: point the name at a resolver, keep it
 * alive, and take it down. Not `setSubregistry` -- a camera body is a leaf
 * and has no children to delegate. The admin halves stay with the owner so
 * the key that runs the demo can also revoke without a second signer.
 */
export const BODY_ROLES =
  ROLE.setResolver |
  ROLE.renew |
  ROLE.unregister |
  asAdmin(ROLE.setResolver) |
  asAdmin(ROLE.renew) |
  asAdmin(ROLE.unregister);

/**
 * Resolver text keys. Namespaced so they cannot collide with ENS's own.
 *
 * `body` is the keyed commitment to the physical camera -- make, model,
 * serial, owner, under HMAC (`ingest/hashing.py:body_commitment`). It lives
 * here rather than on chain because `Registry.registerBody` takes only a
 * bodyId, a fingerprint commitment and an ENS node, and adding a field would
 * mean redeploying and abandoning the live registration. The resolver is also
 * the honest place for it: this is identity, which is what the name is for.
 *
 * Never the serial itself. Ten digits is about 2^33 and a published hash of
 * it is not a commitment -- see the docstring on `body_commitment`.
 */
export const TEXT_KEY = {
  commitment: "genesis.fingerprint",
  signer: "genesis.signer",
  status: "genesis.status",
  body: "genesis.body",
} as const;

export const STATUS_ACTIVE = "active";
export const STATUS_REVOKED = "revoked";

export const permissionedRegistryAbi = [
  {
    type: "function",
    name: "register",
    stateMutability: "nonpayable",
    inputs: [
      { name: "label", type: "string" },
      { name: "owner", type: "address" },
      { name: "registry", type: "address" },
      { name: "resolver", type: "address" },
      { name: "roleBitmap", type: "uint256" },
      { name: "expiry", type: "uint64" },
    ],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "unregister",
    stateMutability: "nonpayable",
    inputs: [{ name: "anyId", type: "uint256" }],
    outputs: [],
  },
  {
    type: "function",
    name: "getSubregistry",
    stateMutability: "view",
    inputs: [{ name: "label", type: "string" }],
    outputs: [{ name: "", type: "address" }],
  },
  {
    type: "function",
    name: "getParent",
    stateMutability: "view",
    inputs: [],
    outputs: [
      { name: "", type: "address" },
      { name: "", type: "string" },
    ],
  },
  {
    type: "function",
    name: "findOwner",
    stateMutability: "view",
    inputs: [{ name: "label", type: "string" }],
    outputs: [{ name: "", type: "address" }],
  },
  {
    type: "function",
    name: "findExpiry",
    stateMutability: "view",
    inputs: [{ name: "label", type: "string" }],
    outputs: [{ name: "", type: "uint64" }],
  },
  {
    type: "function",
    name: "findTokenId",
    stateMutability: "view",
    inputs: [{ name: "label", type: "string" }],
    outputs: [{ name: "", type: "uint256" }],
  },
  {
    type: "function",
    name: "hasRootRoles",
    stateMutability: "view",
    inputs: [
      { name: "roleBitmap", type: "uint256" },
      { name: "account", type: "address" },
    ],
    outputs: [{ name: "", type: "bool" }],
  },
] as const;

export const permissionedResolverAbi = [
  {
    type: "function",
    name: "setText",
    stateMutability: "nonpayable",
    inputs: [
      { name: "node", type: "bytes32" },
      { name: "key", type: "string" },
      { name: "value", type: "string" },
    ],
    outputs: [],
  },
  {
    type: "function",
    name: "text",
    stateMutability: "view",
    inputs: [
      { name: "node", type: "bytes32" },
      { name: "key", type: "string" },
    ],
    outputs: [{ name: "", type: "string" }],
  },
  {
    type: "function",
    name: "multicall",
    stateMutability: "nonpayable",
    inputs: [{ name: "calls", type: "bytes[]" }],
    outputs: [{ name: "", type: "bytes[]" }],
  },
] as const;

export const universalResolverAbi = [
  {
    type: "function",
    name: "resolve",
    stateMutability: "view",
    inputs: [
      { name: "name", type: "bytes" },
      { name: "data", type: "bytes" },
    ],
    outputs: [
      { name: "", type: "bytes" },
      { name: "", type: "address" },
    ],
  },
] as const;

/**
 * Normalise a name the way ENS does before hashing it. Skipping this is how
 * a name that looks right on screen resolves to a different node than the one
 * that was registered.
 */
export function normalizeName(name: string): string {
  return normalize(name);
}

/** The resolver node for a name -- still the v1 namehash under ENSv2. */
export function nodeFor(name: string): `0x${string}` {
  return namehash(normalizeName(name));
}

export function labelOf(name: string): string {
  return normalizeName(name).split(".")[0]!;
}

export function parentOf(name: string): string {
  const labels = normalizeName(name).split(".");
  if (labels.length < 2) throw new Error(`\`${name}\` has no parent`);
  return labels.slice(1).join(".");
}

/**
 * The labels to walk down from `ETHRegistry` to reach the registry that holds
 * `name`'s children -- outermost first.
 *
 *   subregistryPath("cam.osoro.eth") -> ["osoro", "cam"]
 *
 * which reads as: ask `ETHRegistry` for `osoro`'s subregistry, then ask that
 * for `cam`'s. What comes back is where `r10-4471` gets registered.
 */
export function subregistryPath(name: string): string[] {
  const labels = normalizeName(name).split(".");
  const tld = labels.pop();
  if (tld !== "eth") {
    throw new Error(`only .eth names live in ETHRegistry, got \`${name}\``);
  }
  if (labels.length === 0) throw new Error("`eth` is the root, not a name");
  return labels.reverse();
}

/**
 * A camera body label. Kept deliberately narrow: the demo derives it from the
 * model and the serial (`r10-4471`), and a label that normalises to something
 * other than what was typed is a label that will not resolve to the node the
 * record was written against.
 */
export function assertBodyLabel(label: string): void {
  if (!/^[a-z0-9][a-z0-9-]{1,62}$/.test(label)) {
    throw new Error(
      `\`${label}\` is not a usable body label -- lowercase letters, digits ` +
        `and hyphens, 2 to 63 characters, not starting with a hyphen`,
    );
  }
  if (normalize(label) !== label) {
    throw new Error(`\`${label}\` is not ENS-normalised`);
  }
}

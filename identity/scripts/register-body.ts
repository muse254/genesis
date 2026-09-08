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
 *
 * The parent is registered by hand at <https://app.ens.dev/> from the deployer
 * address, close to the recording: Sepolia ENSv2 resets names on redeployment,
 * so an early registration is a liability rather than progress. See
 * `identity/addresses.md`. This module assumes `cam.osoro.eth` exists and the
 * deployer can register into it; when that is not true it says so rather than
 * reverting with a bare `execution reverted`, because finding that out on
 * camera is the failure mode worth engineering against.
 *
 *   npm run build && node dist/register-body.js register r10-4471 0xcommit 0xsigner
 *   node dist/register-body.js resolve r10-4471.cam.osoro.eth
 *   node dist/register-body.js revoke  r10-4471.cam.osoro.eth
 *
 * Add `--dry-run` to any write: it does every read and simulates the call
 * without sending it. That is the check to run on the morning of the demo,
 * when the question is whether the name survived the last redeployment.
 */

import {
  createPublicClient,
  createWalletClient,
  decodeFunctionResult,
  encodeFunctionData,
  http,
  zeroAddress,
  type Address,
  type PublicClient,
  type WalletClient,
} from "viem";
import { privateKeyToAccount } from "viem/accounts";
import { sepolia } from "viem/chains";
import { packetToBytes } from "viem/ens";
import { toHex } from "viem";

import {
  BODY_ROLES,
  ENS,
  ROLE,
  STATUS_ACTIVE,
  STATUS_REVOKED,
  TEXT_KEY,
  assertBodyLabel,
  labelOf,
  nodeFor,
  parentOf,
  permissionedRegistryAbi,
  permissionedResolverAbi,
  subregistryPath,
  universalResolverAbi,
} from "./ens.js";

export interface BodySubname {
  label: string; // "r10-4471"
  parent: string; // "cam.osoro.eth"
  fingerprintCommitment: `0x${string}`;
  signingKey: `0x${string}`;
}

export interface Options {
  /** Do every read and simulate the write, but do not send it. */
  dryRun?: boolean;
}

const RPC = process.env.SEPOLIA_RPC_URL ?? "https://ethereum-sepolia-rpc.publicnode.com";

let cachedPublic: PublicClient | undefined;

export function publicClient(): PublicClient {
  cachedPublic ??= createPublicClient({ chain: sepolia, transport: http(RPC) });
  return cachedPublic;
}

/**
 * The signing key. Built lazily: the read paths and the tests must not need a
 * private key in the environment, and a module that throws on import is a
 * module that cannot be tested offline.
 */
export function wallet(): { client: WalletClient; account: Address } {
  const key = process.env.DEPLOYER_PRIVATE_KEY;
  if (!key) {
    throw new Error(
      "DEPLOYER_PRIVATE_KEY is not set. The demo registers the body subname " +
        "from the address that owns the parent -- see identity/addresses.md.",
    );
  }
  const account = privateKeyToAccount(key as `0x${string}`);
  return {
    client: createWalletClient({ account, chain: sepolia, transport: http(RPC) }),
    account: account.address,
  };
}

/**
 * Walk from `ETHRegistry` to the registry that holds `parent`'s children.
 *
 * Each step is a real call, and each can come back zero -- which is what a
 * name that was never registered, or that a redeployment took with it, looks
 * like from here. The error names the label that broke the chain, because
 * "osoro" missing and "cam" missing are different problems with different
 * fixes.
 */
export async function subregistryFor(parent: string): Promise<Address> {
  const client = publicClient();
  let registry: Address = ENS.ethRegistry;
  const walked: string[] = [];

  for (const label of subregistryPath(parent)) {
    const next = (await client.readContract({
      address: registry,
      abi: permissionedRegistryAbi,
      functionName: "getSubregistry",
      args: [label],
    })) as Address;

    if (next === zeroAddress) {
      const name = [label, ...walked].join(".") + ".eth";
      const owner = (await client.readContract({
        address: registry,
        abi: permissionedRegistryAbi,
        functionName: "findOwner",
        args: [label],
      })) as Address;

      // Two different problems that look identical from a zero address, and
      // they have different fixes. Owning a name does not give it a
      // subregistry: `raffy.eth` and `hello.eth` are both owned on Sepolia and
      // both return zero here. The subregistry gets provisioned when the first
      // subname is created through app.ens.dev, so an owned-but-empty parent
      // means the UI step was skipped, not that the name is missing.
      throw new Error(
        owner === zeroAddress
          ? `${name} is not registered. Register it at https://app.ens.dev/ ` +
            `from the deployer address -- ENSv2 Sepolia resets names on ` +
            `redeployment, so this is expected if it has been a while.`
          : `${name} is registered to ${owner} but has no subregistry, so ` +
            `nothing can be registered under it. Create one subname under ` +
            `${name} at https://app.ens.dev/ -- that is what provisions the ` +
            `subregistry this walk needs.`,
      );
    }
    walked.unshift(label);
    registry = next;
  }
  return registry;
}

/**
 * Register the body subname.
 *
 * Expiry is inherited from the parent rather than picked: a child cannot
 * outlive its parent, and asking the registry what the parent's expiry
 * actually is beats assuming a year and reverting.
 */
export async function registerBody(
  body: BodySubname,
  options: Options = {},
): Promise<`0x${string}`> {
  assertBodyLabel(body.label);

  const client = publicClient();
  const { client: signer, account } = wallet();
  const registry = await subregistryFor(body.parent);

  const owner = (await client.readContract({
    address: registry,
    abi: permissionedRegistryAbi,
    functionName: "findOwner",
    args: [body.label],
  })) as Address;

  if (owner !== zeroAddress) {
    throw new Error(
      `${body.label}.${body.parent} is already registered to ${owner}. ` +
        `Revoke it or pick another label -- re-registering would silently ` +
        `rebind a name a verifier may already have resolved.`,
    );
  }

  const canRegister = (await client.readContract({
    address: registry,
    abi: permissionedRegistryAbi,
    functionName: "hasRootRoles",
    args: [ROLE.registrar, account],
  })) as boolean;

  if (!canRegister) {
    throw new Error(
      `${account} does not hold ROLE_REGISTRAR on the subregistry for ` +
        `${body.parent} (${registry}). The parent has to be owned by the key ` +
        `that signs the demo -- a transfer step mid-demo is a step that can ` +
        `fail on camera.`,
    );
  }

  const [parentRegistry, parentLabel] = (await client.readContract({
    address: registry,
    abi: permissionedRegistryAbi,
    functionName: "getParent",
    args: [],
  })) as [Address, string];

  const expiry = (await client.readContract({
    address: parentRegistry,
    abi: permissionedRegistryAbi,
    functionName: "findExpiry",
    args: [parentLabel],
  })) as bigint;

  const { request } = await client.simulateContract({
    address: registry,
    abi: permissionedRegistryAbi,
    functionName: "register",
    args: [body.label, account, zeroAddress, ENS.resolver, BODY_ROLES, expiry],
    account,
  });

  if (options.dryRun) return "0x";
  return signer.writeContract(request);
}

/**
 * Write the three records the verifier reads.
 *
 * One multicall, so the name is never briefly resolvable with a commitment
 * but no signer -- a verifier that catches that window would read a body it
 * cannot check signatures for.
 */
export async function setBodyRecords(
  body: BodySubname,
  options: Options = {},
): Promise<void> {
  assertBodyLabel(body.label);

  const node = nodeFor(`${body.label}.${body.parent}`);
  const client = publicClient();
  const { client: signer, account } = wallet();

  const calls = [
    [TEXT_KEY.commitment, body.fingerprintCommitment],
    [TEXT_KEY.signer, body.signingKey],
    [TEXT_KEY.status, STATUS_ACTIVE],
  ].map(([key, value]) =>
    encodeFunctionData({
      abi: permissionedResolverAbi,
      functionName: "setText",
      args: [node, key!, value!],
    }),
  );

  const { request } = await client.simulateContract({
    address: ENS.resolver,
    abi: permissionedResolverAbi,
    functionName: "multicall",
    args: [calls],
    account,
  });

  if (options.dryRun) return;
  await signer.writeContract(request);
}

/**
 * Resolve a body name back to its records, through `UniversalResolverV2`.
 *
 * Deliberately the universal resolver rather than a direct read of the
 * resolver we happen to have written to: that is the path a third party takes,
 * and if it does not work for them the registration is decorative. `null`
 * means nothing resolved -- no name, no resolver, or no commitment record --
 * which the verify page reads as "no record", never as "fake".
 */
export async function resolveBody(name: string): Promise<BodySubname | null> {
  const client = publicClient();
  const node = nodeFor(name);
  const dnsName = toHex(packetToBytes(name));

  const readText = async (key: string): Promise<string | null> => {
    try {
      const [encoded] = (await client.readContract({
        address: ENS.universalResolver,
        abi: universalResolverAbi,
        functionName: "resolve",
        args: [
          dnsName,
          encodeFunctionData({
            abi: permissionedResolverAbi,
            functionName: "text",
            args: [node, key],
          }),
        ],
      })) as [`0x${string}`, Address];

      if (encoded === "0x") return null;
      return decodeFunctionResult({
        abi: permissionedResolverAbi,
        functionName: "text",
        data: encoded,
      }) as string;
    } catch {
      // No resolver, or no name at all. Both are "nothing registered".
      return null;
    }
  };

  const [commitment, signer, status] = await Promise.all([
    readText(TEXT_KEY.commitment),
    readText(TEXT_KEY.signer),
    readText(TEXT_KEY.status),
  ]);

  if (!commitment) return null;
  if (status === STATUS_REVOKED) return null;

  return {
    label: labelOf(name),
    parent: parentOf(name),
    fingerprintCommitment: commitment as `0x${string}`,
    signingKey: (signer ?? "0x") as `0x${string}`,
  };
}

/**
 * Mark a body revoked.
 *
 * The name stays registered and stays resolvable. Unregistering would be
 * tidier and is wrong: a verifier holding a photograph signed by this body
 * needs to learn that the key was withdrawn, and a name that resolves to
 * nothing is indistinguishable from a name that never existed. Revocation is
 * an answer, not an absence.
 */
export async function revokeBody(name: string, options: Options = {}): Promise<void> {
  const node = nodeFor(name);
  const client = publicClient();
  const { client: signer, account } = wallet();

  const { request } = await client.simulateContract({
    address: ENS.resolver,
    abi: permissionedResolverAbi,
    functionName: "setText",
    args: [node, TEXT_KEY.status, STATUS_REVOKED],
    account,
  });

  if (options.dryRun) return;
  await signer.writeContract(request);
}

async function main(argv: string[]): Promise<void> {
  const dryRun = argv.includes("--dry-run");
  const args = argv.filter((a) => a !== "--dry-run");
  const [command, ...rest] = args;
  const parent = process.env.ENS_PARENT_NAME ?? "cam.osoro.eth";

  switch (command) {
    case "register": {
      const [label, commitment, signingKey] = rest;
      if (!label || !commitment || !signingKey) {
        throw new Error("usage: register <label> <commitment> <signingKey>");
      }
      const body: BodySubname = {
        label,
        parent,
        fingerprintCommitment: commitment as `0x${string}`,
        signingKey: signingKey as `0x${string}`,
      };
      const hash = await registerBody(body, { dryRun });
      await setBodyRecords(body, { dryRun });
      console.log(
        dryRun
          ? `would register ${label}.${parent} and write its records`
          : `registered ${label}.${parent} in ${hash}`,
      );
      break;
    }
    case "resolve": {
      const [name] = rest;
      if (!name) throw new Error("usage: resolve <name>");
      const body = await resolveBody(name);
      console.log(body ? JSON.stringify(body, null, 2) : "nothing registered");
      break;
    }
    case "revoke": {
      const [name] = rest;
      if (!name) throw new Error("usage: revoke <name>");
      await revokeBody(name, { dryRun });
      console.log(dryRun ? `would revoke ${name}` : `revoked ${name}`);
      break;
    }
    default:
      throw new Error("usage: register-body <register|resolve|revoke> [--dry-run]");
  }
}

if (process.argv[1] && import.meta.url.endsWith(process.argv[1].split("/").pop()!)) {
  main(process.argv.slice(2)).catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exit(1);
  });
}

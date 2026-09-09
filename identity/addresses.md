# ENSv2 on Sepolia — working notes and pinned addresses

ENSv2 is live on **Sepolia only** — public beta, the last phase before
mainnet. That is why the whole project sits on Sepolia: the prize requires
ENSv2 features to be central rather than cosmetic, and they do not exist on
mainnet yet. A mainnet ENS name does not carry over.

**The app is <https://app.ens.dev/>**, not `sepolia.app.ens.domains`. The
beta moved; the old host still answers, which is exactly how you end up
registering in the wrong place.

## The registration is not durable

The app warns, verbatim: *"ENS v2 is in active development. Registered names
on Sepolia and state data may be reset periodically due to routine contract
deployments. The most recent deployment was on July 30, 2026."*

So the name is not an asset and not a milestone to tick early. A redeployment
between registering and demoing takes the name with it, and the demo depends
on resolving it live.

Consequences, and they cut against `BUILD.md`'s day-4 instinct:

- **Register late, not early.** Close to the demo recording, not now.
- **Re-check the day of.** Resolve the name before recording; if it is gone,
  register again — minutes, not hours, and free.
- **Never hardcode a resolved value** as insurance against the reset. ENS's
  own rule forbids it, and it would hide exactly the failure you need to see.
- The pinned addresses below can still move. Pin them, and re-verify on the
  day rather than trusting a table written a week earlier.

## Registration order

Register the parent from the **deployer address**, not a personal wallet.
The demo has to create a body subname live — ENS's rule is no hardcoded
values — so the key that signs the demo must already own the parent.
A transfer step mid-demo is a step that can fail on camera.

1. Fund `DEPLOYER_PRIVATE_KEY`'s address from the Sepolia faucet.
2. Register `osoro.eth` at <https://app.ens.dev/> from that address.
   Taken on mainnet, free on Sepolia as of 8 September 2026.
3. Create `cam.osoro.eth` as a subname of it.
4. Leave `r10-4471.cam.osoro.eth` for the demo to create live.

Step 3 is not optional tidiness, and this is the part that is easy to get
wrong. In ENSv2 a name does not own a flat entry in a global registry: every
name points at its own **subregistry**, and children live in that. Owning a
name does not create one. Checked against live Sepolia on 8 September 2026:
`raffy.eth` and `hello.eth` both have real owners and both return the zero
address for their subregistry.

So `osoro.eth` registered and paid for is still a parent nothing can be
registered under. Creating the first subname through app.ens.dev is what
provisions the subregistry, and only after that can the script create body
names. `identity/scripts/register-body.ts` tells the two cases apart —
unregistered, versus owned but empty — because they look identical from a
zero address and have different fixes.

## Rehearsing it without registering anything

Every write in `register-body.ts` takes `--dry-run`: it does each read and
simulates the call, and sends nothing.

```bash
cd identity && npm install && npm run build
node dist/register-body.js register r10-4471 <commitment> <signer> --dry-run
node dist/register-body.js resolve r10-4471.cam.osoro.eth
```

That is the check to run on the morning of the recording. It answers the only
question that matters that day — did the name survive the last redeployment —
without spending anything and without a transaction to undo. Today it returns
`osoro.eth is not registered`, which is the correct answer and will stay
correct until step 2 is done.

`ENS_PARENT_NAME=cam.osoro.eth` in `.env` already assumes this, as do
`BUILD.md`, the README diagram and the MCP tool descriptions. Registering
anything else means changing all four.

## What we deployed, and why we had to

Done 9 September 2026. `app.ens.dev` registers a name and, as of the beta,
**offers no way to create a subname** — there is no such section in the UI.
Registering `osoro.eth` therefore left it in exactly the state `raffy.eth` is
in: owned, with `getSubregistry` returning zero and nothing registerable
underneath.

In ENSv2 a name's children live in a `PermissionedRegistry` that the name
points at, so the fix is to deploy one and attach it. The sources are public
and verified, so this is ENS's own contract rather than an imitation:

| Contract | Address | Holds |
| --- | --- | --- |
| Registry for `osoro.eth`'s children | `0xbA42b356627ecEC560269d06792C70E3c6A24d4B` | `cam` |
| Registry for `cam.osoro.eth`'s children | `0xB264327897C7d18bFa10C79C6Abdd9208BD3a118` | body subnames |

Built from the 32 verified sources behind `ETHRegistry` on Blockscout,
compiled with **solc 0.8.24** rather than the 0.8.27 ENS used — every pragma
in the tree allows it and this repo already runs 0.8.24. The bytecode is
therefore not byte-identical to theirs, which is fine for a fresh deployment
and would not be fine for a verification.

Three things that were not obvious and each cost a transaction:

- **The constructor's root bitmap grants `ROLE_REGISTRAR_ADMIN`, not
  `ROLE_REGISTRAR`.** Being able to grant a role is not holding it, so the
  first `register` reverted with `EACUnauthorizedAccountRoles(0, 1, …)`. The
  deployer had to `grantRootRoles(1, self)` on each registry.
- **`setParent` is not implied by being pointed at.** A registry deployed
  fresh returns `(0x0, "")` from `getParent()`, and
  `register-body.ts` reads the child's expiry through it. Both registries had
  to be told their parent explicitly.
- **Expiry is inherited, not chosen.** `cam` was registered at `osoro`'s own
  expiry, 1820499912 (September 2027). A child cannot outlive its parent.

## Pinned addresses

From <https://docs.ens.domains/learn/deployments/>, read 8 September 2026.
The docs note the Sepolia apps and Universal Resolver are linked against the
**ENSv2** deployment, which makes the v1 contracts below obsolete there —
worth knowing, because a lookup against the legacy registry answers happily
and tells you nothing about ENSv2 state.

Verify each against the docs before the deploy, then freeze. The contracts
are not final and a mid-window upgrade is how the demo breaks.

| Contract | Sepolia address | Pinned |
| --- | --- | --- |
| ETHRegistrar | `0xa88553f454b77203b0d036a05c894d555eaaa2cc` | |
| ETHRegistry | `0xbdc85dd5b15d7ecb354cd7cb6f2c50b4f2c4f0e2` | |
| UniversalResolverV2 | `0x4a1817d13e9cf196f471725176355c1234b63c70` | |
| PermissionedResolverImpl | `0x9eae5c2730a7dd16bdd1dee6421a1b91e3b0365e` | |
| PublicResolverV2 | `0xe7b9a25607e02da8145e4eb1836ca539e53f11f7` | |

Legacy ENSv1 on Sepolia, kept only so nobody wires them by mistake:
registry `0x00000000000C2E074eC69A0dFb2997BA6C7d2e1e`,
BaseRegistrar `0x57f1887a8bf19b14fc0df6fd9b2acc9af147ea85`,
ETHRegistrarController `0xfb3cE5D01e0f33f41DbB39035dB9745962F1f968`.

## What registration costs, and in what

Nothing real, but **not in ETH** — that was wrong here until 9 September 2026
and it matters, because it sends you to the wrong faucet.

Read off the contracts rather than the app: `ETHRegistrar.getRegisterPrice`
reverts for `address(0)` with `PaymentTokenNotSupported`. The rent oracle at
`0x8914b66260EB8C4fff795650c3AE8Cd335958987` accepts
`0x1c7D4B196Cb0C7B01d743Fbc6116a902379C7238`, which is Circle's Sepolia
**USDC** (a `FiatTokenProxy`, 6 decimals — real testnet USDC, not a mintable
mock).

| | |
| --- | --- |
| `osoro`, one year | **8,000,021 units = $8.000021 USDC** |
| Deployer's USDC balance | **0** |
| Sepolia ETH | still needed, for gas only |

So the deployer needs about 8.01 test USDC from <https://faucet.circle.com>
before the transaction will go through, in addition to the gas it already
has. Nothing costs real money; it is simply a different token from a
different faucet than this file used to claim.

## Registering from the command line

The whole flow is reachable with `cast` once the USDC is there —
`makeCommitment`, `commit`, wait `MIN_COMMITMENT_AGE` (60s, and under
`MAX_COMMITMENT_AGE` 86,400s), then `register`. `MIN_REGISTER_DURATION` is
2,419,200s, twenty-eight days.

One thing the CLI does not solve. `register` takes a `subregistry` address,
and passing zero gives the name no subregistry — the state `raffy.eth` and
`hello.eth` are in, where nothing can be registered underneath. Provisioning
one means having a `PermissionedRegistry` instance to point at, which
app.ens.dev creates for you when you add the first subname. That is the
reason to use the app rather than a preference for it.

What it does mean: the deployer address needs faucet ETH before the app will
let the transaction through. As of 8 September 2026 it has 0.0484 Sepolia ETH,
which is enough — `0x91C968D9aBCF4324db9210DCBC4C732b912aFfBe`, the same
address that owns the registered body on chain. Connect *that* account to
<https://app.ens.dev/>, not a personal wallet: the demo signs the subname
registration live, so the key on camera has to own the parent already.

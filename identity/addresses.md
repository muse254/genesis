# ENSv2 on Sepolia — working notes and pinned addresses

ENSv2 is live on **Sepolia only** — public beta, the last phase before
mainnet. That is why the whole project sits on Sepolia: the prize requires
ENSv2 features to be central rather than cosmetic, and they do not exist on
mainnet yet. A mainnet ENS name does not carry over.

**The app is <https://app.ens.dev/>**, not `sepolia.app.ens.domains`. The
beta moved; the old host still answers, which is exactly how you end up
registering in the wrong place.

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

`ENS_PARENT_NAME=cam.osoro.eth` in `.env` already assumes this, as do
`BUILD.md`, the README diagram and the MCP tool descriptions. Registering
anything else means changing all four.

## Pinned addresses — fill in, then freeze

The contracts are not final. Pin these once and do not chase changes; a
mid-window upgrade is how the demo breaks.

| Contract | Sepolia address | Pinned |
| --- | --- | --- |
| Permissioned Registry | `0x…` | |
| Permissioned Resolver | `0x…` | |
| ETH Registrar | `0x…` | |
| Universal Resolver V2 | `0x…` | |

Source of truth: <https://docs.ens.domains/learn/deployments/> and the
`ensdomains/ens-contracts` repository. Treat any ENS material more than a few
months old as suspect.

# Deploying the registry to Base mainnet

Next-session item 2: the registry on Base mainnet (chain id 8453),
`REGISTRY_TEST_MODE` unset, source verified on Basescan. It happens **once**.
The mainnet registry is permanent. Its registration dates are the claim, so it
is never redeployed to fix a mistake. Everything below is ready except the
deployer key (item 1).

## What guards test mode

- `Registry`'s constructor refuses `enableTestMode = true` on any chain not on
  its explicit testnet list (Sepolia, Base Sepolia, Holesky, anvil, ganache).
  Tested in `contracts/test/Registry.t.sol`
  (`test_test_mode_is_refused_off_a_testnet`).
- `contracts/script/Deploy.s.sol` refuses `REGISTRY_TEST_MODE=true` on chain
  1 and chain 8453 before it broadcasts anything, with the error
  `Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy`. Tested through
  `run()` in `contracts/test/Deploy.t.sol`.
- `REGISTRY_TEST_MODE` defaults to false when unset. The script logs
  `testMode false` after deploying. Check that line before you pin anything.

## Versioning and upgrades

The registry is not upgradeable, on purpose. A proxy whose owner can swap
the code could rewrite registration dates, which are the claim. An upgrade
is a new deployment:

- `VERSION()` returns this contract's semver, `"1.0.0"` for the first
  mainnet registry. A new registry bumps it.
- `RECORD_VERSION()` returns `genesis-record-v1`, the domain tag in body ids.
  It must equal `ingest/record.py`. A new registry keeps it unless the id
  derivation changes, so the same camera gets the same body id on every
  registry.
- The old registry stays live and readable for good. Records are not
  migrated. A verifier reads every registry it trusts and gives priority to
  the earliest registration across all of them.

## Prerequisites

1. **Deployer key** (item 1). A fresh key used only for this. On a production
   registry the deployer has no powers: `admin` is zero and there is no owner.
   So the deployer does not need to be the key that later registers the R10
   body (see open questions). Import it into an encrypted Foundry keystore so
   it is never in `.env` or shell history:
   ```sh
   cast wallet import genesis-deployer --interactive
   cast wallet address --account genesis-deployer   # -> DEPLOYER_ADDRESS
   ```
   A hardware wallet also works: use `--ledger` in place of `--account`.
2. **Funding.** Send about 0.005 ETH on Base to that address. That is several
   hundred times the cost of the deploy (see the numbers below). The rest
   pays for registering the body and the photographs.
3. **`ETHERSCAN_API_KEY`**, an Etherscan V2 key from etherscan.io/myapikey.
   One V2 key covers Basescan. It is already a key in the root `.env`.
4. **`BASE_RPC_URL`.** `contracts/foundry.toml` resolves `--rpc-url base` from
   it. `https://mainnet.base.org` works, and a dedicated endpoint is less
   likely to be rate-limited. The root `.env` does not set it yet.
5. `forge test` passes in `contracts/`.

Foundry reads `.env` from `contracts/` and not from the repo root, so export
the root `.env` into the shell first:

```sh
cd contracts
set -a; source ../.env; set +a
unset REGISTRY_TEST_MODE
export DEPLOYER_ADDRESS=0x...   # the address from step 1
```

## Rehearse (no broadcast)

This is the same command without `--broadcast`. It simulates against live
Base and prints the gas estimate:

```sh
forge script script/Deploy.s.sol:Deploy \
  --rpc-url base --account genesis-deployer --sender "$DEPLOYER_ADDRESS"
```

Expect `chain id 8453` and `testMode false` in the logs, and
`SIMULATION COMPLETE`.

## Deploy (the one command)

```sh
forge script script/Deploy.s.sol:Deploy \
  --rpc-url base --account genesis-deployer --sender "$DEPLOYER_ADDRESS" \
  --broadcast --verify --verifier etherscan --chain base -vvv
```

- Pass `--verifier etherscan` explicitly. Forge's default verifier is
  Sourcify. The `[etherscan] base = { key = "${ETHERSCAN_API_KEY}", chain = 8453 }`
  entry in `foundry.toml` supplies the key.
- The receipt is written to `contracts/broadcast/Deploy.s.sol/8453/run-latest.json`,
  which is gitignored. Take the address and the block number from it:
  ```sh
  jq -r '.receipts[0].contractAddress, (.receipts[0].blockNumber|tostring)' \
    broadcast/Deploy.s.sol/8453/run-latest.json
  ```
  `cast to-dec` converts the block number if it prints as hex.

## Verification, if `--verify` did not finish

Basescan sometimes has not indexed the contract by the time forge asks. Retry
on its own. This never re-sends the deploy:

```sh
forge verify-contract <ADDRESS> src/Registry.sol:Registry \
  --chain base --verifier etherscan \
  --constructor-args $(cast abi-encode "constructor(bool)" false) --watch
```

Then confirm on chain that it is a production registry:

```sh
cast call <ADDRESS> "testMode()(bool)" --rpc-url base   # false
cast call <ADDRESS> "admin()(address)"  --rpc-url base   # 0x000...000
```

## After the deploy: pin the address

Freeze the address and the start block in the following places. The Base
Sepolia test registry `0x0C0F3Ec87339F985c509c01dEE8474BB8f5b0EB2` currently
appears in each of the files marked (\*). Keep it where the doc calls it the
test registry.

| File | What to change |
| --- | --- |
| `README.md` (\*) | Add a Base mainnet row beside the Base Sepolia test registry (around line 92) with a Basescan link |
| `.env.example` | `REGISTRY_ADDRESS`, `REGISTRY_START_BLOCK`, and `GENESIS_CHAIN=base` |
| `.env` (local, not committed) | The same three values |
| `subgraph/subgraph.yaml` (\*) | `network: base`, `address`, `startBlock` = the deploy block (item 3). There is no `networks.json`. The manifest holds the network directly |
| `verify/.env.example` (\*) | `VITE_REGISTRY_ADDRESS`, and the chain if it is set there |
| `.github/workflows/pages.yml` (\*) | `VITE_REGISTRY_ADDRESS` for the published verify page |
| `site/health.js` (\*) | `REGISTRY` constant |
| `core/test/verdict.test.ts` (\*) | Test fixture. Change it only if the test is meant to follow the live registry |
| `docs/colosseum-checklist.md` (\*) | Tick the mainnet item and add the address |

`console/chain.py` already knows Base (8453, basescan.org) and reads
`REGISTRY_ADDRESS` from the environment, so it needs no edit.

## Dry-run numbers (30 September 2026)

The dry run was a simulation against a local anvil fork of Base mainnet at
block 51,988,660, using the public anvil account as sender, with no
`--broadcast`:

| | |
| --- | --- |
| Result | `SIMULATION COMPLETE`, `chain id 8453`, `testMode false` |
| Gas limit forge sets (estimate x 1.3) | 1,743,025 |
| Runtime bytecode | ~5.9 KB (the limit is 24 KB) |
| Base gas price at the time | 0.00602 gwei |
| L2 execution cost at that gas limit | 0.0000105 ETH |
| L1 data fee (`GasPriceOracle.getL1Fee` on the initcode) | ~0.00000008 ETH |
| **Total** | **~0.0000106 ETH** |
| Gas price at which 0.005 ETH stops covering the deploy | ~2.9 gwei (about 480 times today's price) |

With `REGISTRY_TEST_MODE=true`, the same simulation fails with
`Deploy: unset REGISTRY_TEST_MODE for a mainnet deploy`.

**0.005 ETH is ample.** The deploy uses about 0.2% of it, and the rest is
there for the body and image registrations in item 4.

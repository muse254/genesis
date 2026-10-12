# Desktop parity: the mainnet launch, step by step

12 October 2026. On launch day the founder registered the R10 on Base
mainnet by hand, working in a terminal with Foundry, a `.env` file and the
localhost console. A photographer with only the desktop app has to be able
to do every one of those steps. This file lists each step, how it was done
on the day, and what the shipped app does today.

The desktop app is the console in a Tauri window (`desktop/README.md`). It
can do whatever the console can do, but it gets no `.env` and has no
Foundry, so every gap below comes from one of those two facts.

| # | Step | Done on 12 Oct with | Shipped desktop app today | Gap |
| --- | --- | --- | --- | --- |
| 1 | Chain config: chain, registry, RPC, subgraph | `.env`: `GENESIS_CHAIN=base`, `REGISTRY_ADDRESS`, `GENESIS_SUBGRAPH_URL` | Nothing sets them. `console/chain.py` defaults to `sepolia` with no registry | **Blocking.** Bake Base mainnet defaults into the app, with `.env` overrides for development only |
| 2 | Create the signing key and back it up | `cast wallet new` and `cast wallet import` (an encrypted keystore), with a paper backup | No wallet screen | **Blocking.** Generate or import a key in the app, keep it as an encrypted keystore in the app data directory, and show the key once for a paper backup |
| 3 | Fund it with Base ETH | A Binance withdrawal on the Base network to the printed address | The pre-flight gas check reads `DEPLOYER_ADDRESS` from the environment, which is unset here | Show the address with a copy button and a QR code, and read the balance live. Say **Base network** in words, since the wrong network is the classic loss |
| 4 | Sign transactions | `cast send --account … --password-file …` (`console/registry.py`) | `cast` is not bundled, so every registration fails with "cast not found" | **Blocking.** Sign in-process with `eth-account` (keystore decrypt and EIP-1559 signing), and unlock with a password prompt held in memory for the session. That also removes the password file |
| 5 | Camera commitment | `python -m ingest commit-body`, which prompts for the serial and creates `~/.genesis/body-commitment.key` | The register-body screen asks for a hex value from the CLI | Add an in-app form. LibRaw already reads the serial from a RAW file (`core/raw/decode.cpp`), so it can be pre-filled for the photographer to confirm. Keep the key in app data and prompt for a backup |
| 6 | Register the body | `POST /register-body` | Works once 1, 2 and 4 are fixed | None |
| 7 | Score, then register photographs | `POST /register-image`, refused below PCE 100 | Works once 1, 2 and 4 are fixed | Add a batch view: pick a folder, show each photo's PCE, approve, then register |
| 8 | Metadata settings | `METADATA_HMAC_KEY` and `GENESIS_OWNER` in `.env` | Unset, so `metadataHmac` is zero and the owner is blank | Add a settings screen. Generate the HMAC key on first run |
| 9 | Check it worked | `cast call`, Basescan and a subgraph query | The register screens link to Basescan, Blockscout and The Graph | None |

## Order to build

1. **Steps 1 and 4.** Without both, the shipped app cannot register anything.
2. **Steps 2 and 3,** the wallet screen. Step 4 needs a key to sign with.
3. **Step 5,** so a photographer never needs a terminal.
4. **Steps 7 and 8.**

The console keeps the `cast` path and `.env` for development and CI.
`DEPLOYER_ACCOUNT` and `DEPLOYER_PASSWORD_FILE` (commit `eba5403`) are the
development path, not the product.

## What must not change

- The key never leaves the machine and is never sent to any Genesis
  service. `docs/security.md` covers where K lives, and the signing key
  follows the same rule.
- The body commitment is entered once. It has no setter, and the app must
  say so before the transaction is sent.
- Registration refuses a photograph below the PCE threshold before it
  reaches the chain, as it does today.

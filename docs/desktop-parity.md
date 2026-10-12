# Desktop parity: the mainnet launch, without the crypto

12 October 2026. On launch day the founder registered the R10 on Base
mainnet by hand, using Foundry, a `.env` and the localhost console. The
desktop app has to produce the same records for a photographer who knows
nothing about blockchains.

**The product rule:** a photographer signs in with Google, pays through
Stripe (or optionally with crypto), and registers photographs. The app
never mentions keys, wallets, gas, networks or transactions. In the app's
words, a registration is a *record*, and its Basescan page is a *proof
link*.

## Each launch step, and what the app does instead

| # | Done by hand on 12 Oct | In the app | Who does the work |
| --- | --- | --- | --- |
| 1 | `.env`: chain, registry, RPC, subgraph | Nothing to set. Base mainnet and registry 1.0.0 are built in | The app's build config |
| 2 | `cast wallet new` and a paper backup | **Sign in with Google.** An account and its signer are created silently. Recovery is the Google account | Embedded-wallet provider (decision D1) |
| 3 | Buy ETH, withdraw on the Base network | Nothing. Registration fees are paid through Stripe, and Genesis pays the gas | Genesis Cloud: Stripe entitlements plus a paymaster |
| 4 | `cast send` with a keystore | Invisible. The app asks the signer, and a sponsored transaction is sent | Smart account (ERC-4337) and the paymaster |
| 5 | `python -m ingest commit-body`, typing the serial | "Add your camera": make, model and serial are read from one RAW file for the photographer to confirm. The commitment key is kept with the account | Desktop app (LibRaw already reads the serial) |
| 6 | `POST /register-body` | Part of "Add your camera" | Desktop app |
| 7 | `POST /register-image`, refused below PCE 100 | "Register photos": pick a folder, see which ones match the camera, confirm | Desktop app; the threshold is unchanged |
| 8 | `METADATA_HMAC_KEY` and `GENESIS_OWNER` | The owner name comes from the Google profile. The HMAC key is generated per account | Desktop app and Genesis Cloud |
| 9 | `cast call` and Basescan | Each photo shows "Registered 12 Oct 2026" and a proof link | Desktop app |

## Why per-user smart accounts, not one Genesis relayer

The deployed registry (1.0.0) checks `msg.sender == body.owner`.

- **A per-user smart account works with it unchanged.** Each photographer's
  account is the body's owner, and a paymaster covers the gas. The on-chain
  claim stays "this body's owner registered this image".
- **One Genesis relayer key would own every body.** Every record would then
  say "Genesis registered this". That weakens claim 1 in `docs/claims.md`.
  Supporting it properly needs ERC-2771, which the cloud plan's C6 assumed
  and which 1.0.0 does not have, so it would mean deploying registry 2.0.

**Custody has to be stated honestly.** With an embedded wallet, the key is
held by the provider's infrastructure and unlocked by the Google sign-in.
`docs/security.md` and `docs/claims.md` must say who can sign for a body,
because the record's meaning depends on it.

## Open decisions

| # | Decision | Notes |
| --- | --- | --- |
| D1 | Embedded-wallet provider | Candidates are Privy (owned by Stripe), Coinbase CDP Embedded Wallets (built for Base, with its own paymaster), or our own KMS signer per user (no third party, but Genesis holds custody). Check each one's support for a desktop webview before choosing |
| D2 | Google sign-in from Tauri | Google refuses OAuth inside embedded webviews. Sign-in has to open the system browser and return to the app through a deep link (`genesis://`) |
| D3 | The founder's R10 | It is owned by the `cast` key `0xc0b6…625A`. When the founder's own account exists, use `transferBody` to move the R10 to that account's smart account. Records already written keep their history |
| D4 | Free quota | "20 free per body" is the founder's plan and is not yet in `docs/cloud-plan.md`. Gas sponsorship enforces it: the paymaster sponsors 20, and Stripe pays for the rest |

## Order to build

1. Built-in chain config (step 1). Small, and needed by everything else.
2. Google sign-in, via the system browser and a deep link (D2).
3. Embedded signer, smart account and paymaster (D1). After this, the app
   can register.
4. "Add your camera" (steps 5 and 6), then "Register photos" (step 7).
5. Stripe entitlements gating sponsorship (D4), then optional crypto payment.

## What stays for development only

`cast`, `.env`, `DEPLOYER_ACCOUNT` and `DEPLOYER_PASSWORD_FILE`
(commit `eba5403`) remain the founder's and CI's path. They never ship in
the app.

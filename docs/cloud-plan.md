# Genesis Cloud: the paid tier, and the plan to build it

Written 30 September 2026. Status: **plan, nothing built.** Nothing here may
be claimed as working until it is (`docs/claims.md`).

## The model

**Open core.** Everything that runs on the photographer's own machine is
open source and free: enrolment, registration, the verify page, the score
page, the desktop app. A photographer who wants nothing from us never needs
an account.

**Genesis Cloud is what we charge for.** The things a photographer cannot do
alone, or would rather not:

- **Keep K safe off the machine.** Today K lives on one disk, cannot be
  recreated identically (`save_fingerprint` does not record which frames went
  into it), and losing it means enrolling the camera again. Cloud backup and
  sync across devices, stored encrypted so that Genesis cannot read it.
- **An archive of RAWs and photographs**, encrypted the same way. A RAW off
  the body is a forgery kit (`docs/adversarial.md`), so it is treated like K.
- **Registration without gas.** The relayer already planned for the desktop
  app (`docs/colosseum-checklist.md`, desktop section) pays the fee; the tier
  sets the quota.
- **Dispute packs and certificate pages**: the record, the reveal of the
  camera commitment, a report an adjudicator can follow, a public page per
  registered photograph (osoroprints certificates link to it).

This is the photographer row of `docs/go-to-market.md` made concrete:
registration stays free within a quota, and what a photographer pays for is
safety of their reference and a dispute when one comes. Businesses
(competitions, libraries, agencies) stay the API and per-event rows there.

**The same account works in the desktop app.** Since 29 September the web
page and the desktop app share one verification package, `core/`
(`docs/shared-verify-plan.md`); the cloud client goes there too, so every
cloud feature exists in both.

### Tiers (hypotheses, to be priced from week 3's interviews)

| | Free (open source) | Pro | Studio |
| --- | --- | --- | --- |
| Enrol, verify, score, desktop app | ✓ | ✓ | ✓ |
| Registrations | own gas | quota, gas paid | larger quota, gas paid |
| Encrypted K backup + sync | — | 1 body | several bodies |
| Encrypted archive (RAW + photos) | — | ✓ (GB cap) | ✓ (larger cap) |
| Certificate pages | — | ✓ | ✓, custom domain |
| Dispute packs | pay per dispute | included quota | included quota |

Prices are deliberately absent. `docs/go-to-market.md` makes week 3's notes
("what they would pay for") the evidence; set prices from those.

## The one invariant: Genesis never holds a readable K

`docs/security.md` ("Where K lives") and the pitch rest on K never leaving
the photographer's machine: a published fingerprint is a forgery kit. The
cloud keeps that true only if **encryption happens on the device, with a
key Genesis never has**. Then the bucket holds ciphertext, a breach of it
yields nothing usable, and a subpoena to Genesis yields nothing either.

If instead the server encrypts (Cloud KMS, or a key Cloud Run can use), K
is readable by Genesis, and the security document, the claims file and the
pitch all have to say so. That is **decision C1** below; this plan assumes
client-side encryption, and recommends it.

It is affordable now because of what shipped on 29 September: all scoring
runs client-side in WASM (`core/`), so the cloud never needs K in the clear
to do anything. It stores and returns bytes.

## Architecture

```
 browser (verify/, account/)  ─┐                      ┌─ Cloud Run: genesis-cloud (TypeScript)
 desktop app (console-ui/)    ─┤  core/src/cloud/     │   auth: Google (OIDC) · wallet (SIWE)
                               ├─ sign in, encrypt,  ─┤   billing: Stripe Checkout + webhooks
                               │  upload / download   │   storage broker: signed URLs, quotas
                               │  (WebCrypto)         │   relayer: pays registerImage gas (later)
                               │                      └──────┬──────────────┬─────────────
                               │                             │              │
                               └──── signed URL PUT/GET ───► GCS bucket     Firestore
                                     ciphertext only         (ciphertext)   users, entitlements,
                                                                            object index, wrapped keys
```

- **Cloud Run** runs one TypeScript service (shares types with `core/`). It
  never receives plaintext K or RAWs: clients upload ciphertext straight to
  GCS through V4 signed URLs it issues, after checking the user's tier and
  quota.
- **GCS** holds ciphertext under per-user prefixes. Uniform bucket-level
  access, no public objects except certificate-page images the user chose to
  publish (a separate public bucket).
- **Firestore** holds accounts, entitlements (from Stripe webhooks), an index
  of objects, and each object's wrapped data key. Nothing secret.
- **Secret Manager** holds the Stripe keys and, later, the relayer key.
- **Deploy** from GitHub Actions with Workload Identity Federation; no
  long-lived service-account key in the repo.

### Sign-in

- **Google**: Google Identity (OIDC). Cloud Run verifies the ID token and
  issues its own session.
- **Wallet**: Sign-In with Ethereum (EIP-4361) against the user's address;
  the same address the registry knows as the body's owner, which makes
  "this account owns this body" checkable on chain.

Signing in proves who someone is. It does **not** give us an encryption key,
and must not: the key has to come from something only the user holds.

### Encryption (client-side, WebCrypto)

- **Envelope**: each object gets a random AES-256-GCM data key. The data key
  is wrapped with the user's **master key** and stored beside the object.
- **The master key** comes from one of:
  - **Wallet users**: HKDF over a signature of a fixed message. Deterministic
    for ordinary accounts (RFC 6979); not guaranteed for smart-contract or
    passkey wallets, which fall back to the recovery phrase.
  - **Google users**: a **passkey with the WebAuthn PRF extension**, which
    yields a stable secret per credential (Chrome, Safari, Android). Where
    PRF is unavailable (some desktop webviews), the recovery phrase.
  - **Always, at setup**: a recovery phrase shown once. Losing every key and
    the phrase loses the data, and the setup screen says so plainly. That is
    the cost of Genesis being unable to read it.
- **What the server still sees**: object sizes, counts, timestamps, and which
  body an object belongs to. Say so in `docs/security.md` when built.

### Payments

- **Stripe** Checkout for subscriptions, the Customer Portal for changes and
  cancellation, webhooks into Firestore entitlements.
- **Wallet payments** (USDC on Base) later: simplest is a quote with an
  invoice id and a transfer the server confirms on chain; a small payment
  contract only if that proves fragile.
- **Check first (decision C2):** Stripe's availability for the entity that
  will own the account. Stripe does not onboard businesses in every country;
  if the founder's jurisdiction is unsupported, the options are a US entity
  (e.g. Stripe Atlas) or a regional processor. Verify before building
  checkout.

## How the desktop app gets it

- The cloud client lives in `core/src/cloud/`, so `console-ui` imports the
  same code the web does.
- Sign-in from the app opens the system browser and returns to the app on a
  loopback redirect (the app already runs a loopback server) or a deep link.
- Encryption runs in the webview with WebCrypto, same code. If WKWebView
  lacks passkey PRF, desktop users use a wallet or the recovery phrase.
- K backup is then: after enrolment, encrypt the `.npz` and upload; on a new
  machine, sign in, download, decrypt, and hand it to the console's
  references directory (a small `POST /bodies/import` endpoint on the
  loopback console, the same one browser enrolment needs).

## Phases

**Colosseum slice, by 12 October: a demo of the model, not a launch.**
`COLOSSEUM.md` is binding: the mainnet deploy and week 3's ten strangers come
first, and nothing here may displace them. So only this, at ~2–3 focused
days, and only after mainnet is live:

1. **C0. Decisions** (below). An hour.
2. **C1. Skeleton.** Cloud Run service, Google sign-in and SIWE, Firestore
   users, a pricing page, Stripe Checkout **in test mode** with a webhook
   that sets the entitlement.
3. **C2. Encrypted K backup** in the browser: passkey-PRF or wallet key,
   recovery phrase, encrypt the K `.npz`, upload via signed URL, restore on
   another browser. Shown in the demo; described in the pitch as the paid
   tier, built to test-mode.

**After Colosseum:**

4. **C3. Desktop sign-in and K sync** (loopback redirect, `/bodies/import`).
5. **C4. Encrypted archive** of RAWs and photographs, with quotas per tier.
6. **C5. Certificate pages** and the osoroprints integration on them.
7. **C6. Relayer as a paid feature**: ERC-2771 forwarder in the registry
   (already on the desktop list, before the mainnet deploy if it is to be in
   this deployment), gas paid per tier quota.
8. **C7. Dispute packs**, **wallet payments**, then the business API.

## Decisions needed

| | Decision | Recommendation |
| --- | --- | --- |
| C1 | Who can decrypt K: client-side keys, or server-held (KMS)? | **Client-side.** Server-held keys make Genesis a holder of forgery kits, which the security document and the pitch currently rule out. |
| C2 | Which entity owns the Stripe account, in which country? | Check Stripe's supported countries first; decide before C1 work on checkout. |
| C3 | Tiers and prices | Structure above; prices from week 3's notes, not before. |
| C4 | Licence for the open core, and whether `cloud/` is in the public repo | Decide with the LICENSE item already on the checklist. LibRaw's WASM build is LGPL 2.1 / CDDL 1.0, so the licence must be compatible with shipping it. A public server is fine: the value is the hosted, trusted service, not secret code. |
| C5 | Is the Colosseum slice worth building at all, versus pitching the model on paper? | Build C1–C2 only if mainnet is live and week 3 is on track by ~5 October; otherwise pitch it from this document and a pricing page. |

## Risks

- **Key loss is data loss.** The recovery phrase is the only mitigation, and
  users lose phrases. Make restore testable from day one.
- **Passkey PRF support** is uneven across browsers and webviews; the wallet
  and phrase paths must be first-class, not fallbacks nobody tests.
- **Scope.** This is a product, not a feature. Twelve days out, the thing
  that wins Colosseum is still strangers' cameras on mainnet.
- **Claims.** Until built, the pitch says "planned paid tier", and
  `docs/claims.md` governs every sentence about it.

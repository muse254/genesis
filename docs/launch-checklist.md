# Launch checklist and later roadmap

6 October 2026. Companion to `docs/platform-plan.md` and `docs/mainnet-deploy.md`
(the runbook for the deploy command itself).

## Status (6 October 2026, nothing committed yet)

Done in the working tree, with tests passing (forge 47, subgraph 11, core 63):

- [x] `registerImage` sets `registeredAt` from `block.timestamp`; a caller's
      value is ignored (was a backdating bug). Two tests.
- [x] `transferBody(bodyId, newOwner)`, history kept. Four tests.
- [x] `attest(subject, kind, dataHash)` and `challenge(subject, evidenceHash)`,
      event-only. Five tests.
- [x] Subgraph: ABI, `Attestation` and `Challenge` entities, transfer handler,
      two tests. `subgraph.local.yaml` is a stale manifest (no reset handler
      either) and was left alone.
- [x] F1: `core/src/verify.ts` reads up to 10 near-duplicates off the chain,
      gives a perceptual match to the earliest registration, and reports
      `competing` registrations (flagged `earlier`) even after an exact hit.
      Three tests. The verify page shows "Registered earlier".
- [x] F7: public copy already says "origin, not truth" and bars "authentic",
      "AI-free" and "verified real"; no change needed.
- [ ] Not done: F2 wording on the desktop console-ui, ABI copies in `mcp/` and
      `console/`, a rehearsal on Base Sepolia of the new functions, and the
      docs (`security.md`, `claims.md`) describing transfer, attest and challenge.

## A. Before you press deploy (the registry is permanent)

The deploy is cheap (about 0.00001 ETH) and cannot be undone. Registration
dates are the claim, so the only real risk is deploying a contract you later
want to change. Decide these first.

- [x] **Contract settled (see Status).** Things that would need a
      new contract, not a patch: on-chain K-against-K dedupe, witness or bond
      logic, earliest-registration priority enforced on chain, KYC or
      uniqueness tokens. The plan puts these off-chain first (F1, F3), so
      v1 can stand. If you choose to redesign the contract, do not deploy today.
- [ ] **Accept that a v2 later means a second registry.** Old dates stay valid
      on v1. The verifier and subgraph must then read both. Cheap to support if
      the verify code takes a list of registries now.
- [ ] **Commit the deploy code first.** `Deploy.s.sol`, `Deploy.t.sol` and
      `docs/mainnet-deploy.md` are uncommitted. Source verification on Basescan
      should match a commit you can point to. (Branch question open: the
      `colosseum` rule runs to 12 Oct.)
- [ ] `forge test` passes in `contracts/`, including `Deploy.t.sol`.
- [ ] Run the rehearsal (no `--broadcast`) against live Base. Expect
      `chain id 8453`, `testMode false`, `SIMULATION COMPLETE`.

## B. Deploy (you do this; it needs your key and funds)

- [ ] Fresh deployer key in an encrypted Foundry keystore (or Ledger). Never in
      `.env` or shell history.
- [ ] About 0.005 ETH on Base sent to it.
- [ ] `ETHERSCAN_API_KEY` and `BASE_RPC_URL` exported (Foundry reads `.env`
      from `contracts/`, not the repo root).
- [ ] Run the single broadcast command from the runbook with
      `--verifier etherscan`.
- [ ] Record the address and block number from
      `broadcast/Deploy.s.sol/8453/run-latest.json`.
- [ ] On chain: `testMode()` returns false and `admin()` is the zero address.
- [ ] Source shows as verified on Basescan (retry `forge verify-contract` if not).

## C. Pin the address (same day)

Files listed in `docs/mainnet-deploy.md`: `README.md`, `.env.example`,
`.env`, `subgraph/subgraph.yaml` (`network: base`, address, `startBlock`),
`verify/.env.example`, `.github/workflows/pages.yml`, `site/health.js`,
`docs/colosseum-checklist.md`. Keep the Sepolia address where it is called the
test registry.

- [ ] Deploy the subgraph against Base mainnet and confirm it indexes from the
      start block.
- [ ] Redeploy the verify page with the mainnet address.
- [ ] Register one real image from a camera you own, then verify it on the
      public page: expect `registered`.
- [ ] Verify a second, unregistered image: expect `no-record`.

## D. Honest launch (week 1, before telling anyone)

- [ ] **F1:** `core/src/verify.ts` compares `registeredAt` across near-duplicates
      so a later copy cannot outrank the first.
- [ ] **F2:** verify page stops saying "this camera body" on a hit.
- [ ] **F7:** site, README and `docs/claims.md` say "registered capture", never
      "proven not AI".
- [ ] **F5:** no key on a command line for anything hosted (`console/registry.py`).
- [ ] Terms of service and privacy notice published (images stay on the device;
      only hashes leave).
- [ ] Status page and error monitoring on.

## E. Platform build (weeks 2 to 10)

Per `docs/platform-plan.md`: org accounts and console, intake API and SDK,
hosted signer, K-against-K dedupe at enrolment (F3), scalable near-duplicate
index (F4), result URLs, audit log, SSO, DPA, SOC 2 Type I.

## F. Later roadmap: trained AI models in the pipeline

Do this after there are paying or piloting users. Rules that hold throughout:
a model score may open a challenge or add doubt, and never grants
`registered`. Every score ships with its measured error bar, as the
consistency signals already do (`MEASURED_AUC` in `core/src/verify.ts`).

| Stage | What | Before it ships |
| --- | --- | --- |
| M1 | Evaluation set: real RAW and delivered files from your own cameras, plus images from current generators (closed and open models), re-compressed and resized | A held-out set that is never used for training, refreshed each quarter |
| M2 | Third-party classifier as an advisory signal (Hive, Reality Defender or similar via API) | Measured accuracy on your set after JPEG, resize and screenshot, not the vendor's headline number |
| M3 | Watermark and provenance readers: C2PA manifest, SynthID-style detectors where a public detector exists | Treat a positive as strong, an absence as nothing |
| M4 | Own model for sensor-level cues (noise statistics, demosaicing traces, resampling) that complement PRNU | Beats a baseline on M1; reports AUC and calibration |
| M5 | Retest stored files when detectors improve (as anti-doping retests samples) | Keep original bytes or hashes plus the model version used |
| M6 | Human review queue for the contested middle | Written criteria; reviewers see the score and its error bar |

Claims discipline: FTC v. Workado (August 2025) bars unsubstantiated accuracy
claims. Publish the measured error rates before quoting any.

## G. Open items

1. Whether to deploy today or first settle the contract design (section A).
2. Which branch to commit on.
3. Hosted custodial signing vs. contributor wallets (recommend custodial).

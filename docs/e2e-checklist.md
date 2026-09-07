# End-to-end testing checklist

What has to exist, in order, before the three flows in `BUILD.md` §4 can be
run start to finish. Ticked items were verified on 7 September 2026.

## Works today

- [x] `demo` passes on the synthetic sensor — `python3 fingerprint/fingerprint.py demo`
- [x] `pytest fingerprint ingest` — 26 tests
- [x] Flow A on real CR3: 16 frames enrolled, `.npz` written, commitment printed
- [x] Flow C upper branch, offline: 13/13 held-out frames MATCH via the CLI,
      PCE 1,895 to 56,255, exit 0
- [x] Delivered JPEG at native resolution: `game.jpg` matches at 1,147.8
- [x] Linear DNGs are refused with a clear message rather than crashing

```bash
python3 fingerprint/fingerprint.py enroll --out data/references/r10.npz <16 frames>
python3 fingerprint/fingerprint.py test --fingerprint data/references/r10.npz <held-out frames>
```

## Blocking, in the order they block

**1. A second camera body.** Everything about false positives is unmeasured
without one. The current null is K rotated 180°, which is a bound, not
evidence. A second R10 is worth more than any other single input to this
project — same model means shared model-level artefacts, which is the case
that can actually break the claim.

- [ ] Enrol body B from its own frames
- [ ] Score body A's frames against K_B and vice versa
- [ ] Set `PCE_THRESHOLD` from the measured separation, not from 50

**2. A frame that should not match.** Demo step 3 needs one.

- [x] Cross-model: Canon 5D Mark III DNG scores 26.6 against the R10
      fingerprint, inside the null band
- [ ] Same model, different body — the one that actually sets the threshold

**3. Gate B — `prnu.crop_and_scale_search`.** Not written; `test --crop-scale`
exits 2. `fingerprint/stress.py` is also empty — both `ladder` and
`to_web_jpeg` are stubs, so there is no way to generate the stimulus yet
either.

- [ ] `to_web_jpeg`: export an enrolled frame at ~1800px, JPEG q80
- [ ] Search over scale, record best PCE and the scale it occurred at
- [ ] Fill in the Gate B table in `docs/gates.md`
- [ ] Decide: retroactive claim live, or archive-claim tool only

**4. Record construction — `ingest/`.** Done, 17 tests.

- [x] `hashing.py` — pixel SHA-256 (metadata-independent), DCT pHash, HMAC
- [x] `record.py` — `ImageRecord`, secp256k1 signing, ERC-7053 commit shape
- [x] `merkle.py` — sorted keccak256 pairs, odd node promoted (OpenZeppelin
      rules, so the Solidity verifier agrees)
- [x] A record built from IMG_0230 against the real fingerprint: PCE 1,895,
      signature recovers, session proof verifies

**5. Contracts — `contracts/src/Registry.sol`.** Every function reverts
`not implemented`.

- [ ] `registerBody`, `registerImage`, `commitSession`, `verifyInclusion`, `commit`
- [ ] `forge test` green
- [ ] Local anvil run: enrol → register → look up, offline end to end

**6. Testnet and ENS.**

- [ ] Deploy `Registry` to Sepolia, record the address
- [ ] Register `r10-4471.cam.osoro.eth` live, no hardcoded values
- [ ] Pin the four ENSv2 addresses in `identity/addresses.md` and freeze

**7. Subgraph.**

- [ ] Index `BodyRegistered` / `ImageRegistered` / `SessionCommitted`
- [ ] Resolve a perceptual hash to a body record

**8. Scoring service and verify page.** `scoring/app.py` has both endpoints
stubbed.

- [ ] `uvicorn scoring.app:app` — upload an image, get a PCE and a lookup
- [ ] Verify page: upload, score, resolve, verdict

## The full run, once the above exists

- [ ] Enrol body A from an archive folder
- [ ] Register one photograph → `commit()` on Sepolia, ENS name resolves
- [ ] Score a different camera's photograph → no match
- [ ] Strip metadata, resize, re-encode the registered photograph → still
      resolves through the pHash-plus-PRNU branch
- [ ] Verify page shows body, identity and registration time
- [ ] Whole path repeated on a clean machine, following `README.md` from the top

## Verified state, 7 September 2026

| Module | Implemented | Stubs |
| --- | --- | --- |
| `fingerprint/prnu.py` | 20 | 1 — `crop_and_scale_search` |
| `fingerprint/fingerprint.py` | 9 | 0 |
| `fingerprint/stress.py` | 0 | 2 |
| `ingest/` | 13 | 0 |
| `scoring/app.py` | 1 | 2 |
| `contracts/src/Registry.sol` | 0 | 6 functions revert |

## Standing constraints

- Never publish K. Only the commitment leaves the machine.
- Do not crop to save time: `--crop 2048` costs roughly 6x PCE and can push a
  frame under the threshold.
- Re-run `pytest fingerprint` after touching anything in `fingerprint/`. The
  commitment test is the one that matters — a changed serialisation
  invalidates every prior on-chain registration.

# Chainlink CRE — confidential scoring

`scoring/app.py` is the trust hole by design: it holds the reference and you
take its word for a PCE. This is the fix, and this document is what it cost.

Every number here was run on 10 September 2026 against CRE CLI v1.32.0. The
limits come from `cre workflow limits export`, not from the docs — the
service-quotas page 404s, which is why BUILD.md §11 said to spike them early.

## What it buys, and what it does not

**Buys:** the algorithm is public, the reference is private, the score is
signed. A third party gets a verdict without anyone holding K, and the scorer
cannot lie about the number.

**Does not buy: anything against forgery.** An enclave would score the forged
DNG in `docs/adversarial.md` at 868 and sign it faithfully. The signature
attests that the computation was performed correctly on the pixels it was
given; it says nothing about where those pixels came from. Confidential
compute protects the reference from the verifier. The attack happens before
the pixels arrive. `docs/security.md` is the long version and nothing here
softens it.

## Four things the original plan had wrong

BUILD.md §11 sketched: extract the residual client-side, send a 512² crop,
correlate against the secret reference, fall back to Confidential HTTP if a
~1 MB reference will not ride as a Vault secret. Measured, four of those are
wrong.

**1. The reference is 89 MB, not ~1 MB.** `data/references/r10.npz` is
89,197,405 bytes — four CFA planes of 2000×3000 float32. `WASMSecretsSizeLimit`
is `1mb`. Off by a factor of 89.

**2. Confidential HTTP is not the fallback.** It is capped at `RequestSizeLimit`
125kb and `ResponseSizeLimit` 500kb. It does not carry an 89 MB reference
either, so the documented escape hatch was never one.

**3. 512² does not fit.** Four planes at 512² int8 is 1,048,576 bytes before
base64. 256² is 262,144 bytes, ~350 kB encoded, and fits with room.

**4. The residual alone is not enough.** `prnu.score` correlates the residual
against `plane * k` — the multiplicative model — and masks saturated
photosites, which needs the plane too. So two arrays cross, not one.

Also ruled out, though it would fit: embedding K in the workflow binary.
`WASMBinarySizeLimit` is 100mb, but the CRE beta is explicit that **the binary
is not confidential**. That would publish K.

## What the crop costs

Four CFA planes, K int8, probe int8, against `PCE_THRESHOLD` 100. Genuine
frames from the enrolled R10; the negative is a different R10 body
(`raw.pixls.us`, serial 022031004996 against our 473034005088).

| CFA plane | K as a secret | payload | IMG_0217 | IMG_0216 | IMG_0236 | IMG_0230 | different R10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2000×3000 (full) | 96 MB | — | 49,309.6 | 37,623.4 | 24,186.0 | 1,895.4 | 39.1 |
| 1024² | 4 MB | 8 MB | 8,485.2 | 6,463.1 | 3,197.8 | 124.7 | −36.5 |
| 512² | 1 MB | 2 MB | 1,647.0 | 1,416.2 | 832.1 | 25.7 | 27.5 |
| **256²** — what ships | **256 kB** | **512 kB** | **390.1** | **315.7** | **164.1** | **−25.5** | **−22.4** |

**Three of four genuine frames clear the threshold at 256². The fourth does
not.** IMG_0230 goes from 1,895.4 on the full frame to −25.5, while a
different camera body sits at −22.4 — at the crop size that fits an enclave,
the weakest frame in the corpus is indistinguishable from a different camera.
Only 1024² recovers it, at 124.7 against a threshold of 100, and 4 MB of K
does not fit any secret path available.

That is the price of confidential scoring on this reference, and it is not
hidden: the confidential endpoint is a second opinion, not a replacement for
`/score`.

The caveat on the genuine column: `save_fingerprint` does not record which
frames were enrolled (`docs/adversarial.md` already flags this), so these four
cannot be proven held-out. The negative is certainly not enrolled.

### int8 is free

Quantising to one byte per photosite, both K and the probe:

| | K float32 | K int8 | K and probe int8 |
| --- | --- | --- | --- |
| IMG_0217 @ 512² | 1,647.5 | 1,646.7 | 1,647.0 |
| IMG_0217 @ 256² | 391.6 | 390.6 | 390.1 |

Under half a percent. It buys a factor of four on the secret and on the wire,
which is the difference between fitting a Vault secret and not.

### Area beats planes

At an equal 256 kB of K, four planes at 256² score 390.1 where one plane at
512² scores 284.9. Each CFA plane is an independent measurement of the same
body, so summing their correlation surfaces adds the peaks coherently and the
noise incoherently — the argument in `prnu.score`'s docstring, measured.

## The two backends

```
GENESIS_CONFIDENTIAL_BACKEND=cre     a real confidential workflow
GENESIS_CONFIDENTIAL_BACKEND=local   the same arithmetic, in this process
```

`local` exists because deployment waits on private-beta enrolment with unknown
turnaround. It keeps the demo standing if the CRE path fails on the day.

**They agree on the number.** Measured through the shipped module on the real
corpus — every probe, both backends, to the tenth, with identical payload
digests:

| Probe | local | cre (simulated) | digest |
| --- | --- | --- | --- |
| IMG_0217 | 390.1 | 390.1 | `f930f00437e1a199…` |
| IMG_0216 | 315.7 | 315.7 | `d6b8ef3cd8433191…` |
| IMG_0236 | 164.1 | 164.1 | `5893aafe0361a2e0…` |
| IMG_0230 | −25.5 | −25.5 | `d1c09569d6cf568c…` |
| different R10 | −22.4 | −22.4 | `7cffc05bd64444de…` |

The TypeScript kernel is a radix-2 Cooley-Tukey and numpy is pocketfft, so
they cannot be bit-identical. They agree to the thousandth the attestation
actually carries, which is what the tests assert.

**They do not agree on what the number is worth**, and the code refuses to
blur that. Three states, and only the third removes the scorer as a trusted
party:

| State | `attested` | What the signature is worth |
| --- | --- | --- |
| `local` | `false` | Self-signed on the machine holding K. Closes nothing |
| `cre`, simulated | `false` | The CLI itself says the simulator is not a real TEE. The report is built, not DON-signed |
| `cre`, deployed | `true` | K released by the Vault DON into an attested enclave, consensus signs the score |

**Only the third is the guarantee, and it is not reachable today.** A demo
that showed the first and described the third would be the same drift
`docs/security.md` warns about, one level up. `cre/validate_cre.py` fails if
`local` ever reports `attested`.

## Practical limits worth knowing

- **`ARG_MAX`, not a CRE limit.** The CLI passes secret values to the compiler
  as process arguments, and macOS `ARG_MAX` is 1,048,576. Measured: three
  400 kB secrets fail to simulate with `argument list too long`; three 200 kB
  ones do not. K is split one secret per CFA plane for this reason, and it is
  a local constraint rather than a protocol one.
- **No trigger payload cap observed.** 16 MB passed through an HTTP trigger in
  simulation with production limits enabled, and there is no `HTTPTrigger` size
  limit in the exported limits at all. Whether production enforces one is
  **unknown** and not testable without deployment.
- **A run takes about 16 seconds**, nearly all of it compiling TypeScript to
  WASM. The correlation itself is milliseconds.

## Running it

```bash
cd cre/workflow && bun install --cwd ./genesis      # once

GENESIS_CONFIDENTIAL_BACKEND=local uvicorn scoring.app:app --port 8000
curl -F file=@frame.CR3 localhost:8000/score/confidential

.venv/bin/python -m pytest cre/                      # 9 tests, no camera needed
GENESIS_TEST_CRE=1 .venv/bin/python -m pytest cre/   # adds the CRE round trip
```

RAW only. The confidential path correlates on the photosite lattice, and a
developed JPEG has none left; the scale and orientation search that rescues
those needs the whole 89 MB reference. `/score` stays the path for delivered
images, and this endpoint refuses rather than quietly scoring worse.

## Account state, 10 September 2026

| | |
| --- | --- |
| CLI | v1.32.0 |
| Account | fanosoro@gmail.com, org `org_by3cdanb8BDALH8p` |
| `cre account list-key` | No linked owners. `link-key` broadcasts a transaction and needs gas the deployer does not have. Only read on deploy |
| `cre account access` | Deployment access not enabled. Needs a TTY, so it has to be run by hand |
| Simulation | Works with no linked owner and no deploy access |

Deployment would buy two things and they are worth naming: a real attestation,
and — if a larger secret budget came with it — the 1024² crop that recovers
IMG_0230. Neither is assumed anywhere in the demo.

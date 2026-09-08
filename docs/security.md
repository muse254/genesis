# Security posture

What this system defends, what it does not, and what is still open. Every
claim here is measured; `docs/adversarial.md` holds the numbers.

## Threat model

The attacker is assumed to hold:

- **The photographer's delivered files**, including RAWs. A working
  photographer has sent RAWs to clients for years and cannot recall them.
- **Possibly K itself**, from a service compromise or a mishandled reference.
- **The published algorithm**, which is this repository.

The attacker is assumed **not** to hold the owner's wallet key.

That last line is the whole security model. Everything below follows from it.

## The boundary

**`registerImage`'s `require(body.owner == msg.sender)`.** It is the only
mechanism in the system that no attack got past, and every claim the product
makes has to sit downstream of it.

Second, and only for images already registered: **first-registration time**. A
forgery fabricated later cannot claim to predate a registration that is
already on chain. This is why registering early is the security model and not
hygiene.

## What is not a control

Each of these looks like one and is not. All measured.

| Mechanism | Why it is not a control |
| --- | --- |
| A PCE score | Forgeable at 50–90 dB PSNR by anyone with one RAW off the body |
| `fingerprintCommitment` on chain | A hash of K. Once K leaks it authenticates the forgery kit |
| `PCE_THRESHOLD` | The attacker picks the score; a synthetic carrier reached 291,608 |
| The degradation ladder | A forgery survives further down it than a real photograph |
| `commitSession` | Permissionless, and takes any root |
| Keeping K secret | The attacker does not need K. One RAW file suffices |
| Degrading the verifier's copy of K | Measured: kills genuine verification before it stops a forgery |
| Salting K by a secret transform | Measured: a forgery outscores the weakest genuine frame 14x |
| `exiftool -SerialNumber` | Correct for vetting mislabelled files, useless against a forged one |

The last row matters because that check appears in our own procedure in
`docs/gates.md`. It protects against mistakes, not adversaries.

## The property that cannot be fixed

**K cannot be rotated.** A leaked password is changed; a leaked sensor
fingerprint needs a new camera body. And the trait is broadcast in every
photograph the body has ever produced, so it is not a secret in the first
place — it is an identifier. This is the biometrics conclusion (`[ISO24745]`,
and the prior-art section of `docs/adversarial.md`) and no preprocessing
escapes it: any transform the verifier applies must also be applied to the
probe, and the forgery's planted term transforms identically.

The forgery is not an approximation of the signal the detector looks for. It
**is** that signal, scaled. No linear operator separates a vector from its own
scalar multiple.

## Detection: what is built, what is not

Detection raises an attacker's cost. It is not a boundary and nothing here
gates a verdict.

Measured 8 September 2026 on ten genuine images per path against forgeries
that clear PCE, references held out. **Every range overlaps. None is a test.**

| Check | RAW AUC | Delivered AUC | Reading |
| --- | --- | --- | --- |
| `body_consistency` | **0.900** | 0.725 | Strongest we have, and weakest on the path that matters |
| `effective_strength` | 0.800 | 0.767 | A weak signal both ways |
| `resampling_peak` | — | **0.517** | Chance. Scene content drives it, not resampling |

Earlier readings of these were far more flattering and came from two to eight
genuine images. Ten per path was enough to collapse them: the genuine
`effective_strength` band on the delivered path is 0.0011-0.6674, not the
0.0109-0.0218 that two files suggested, and forgeries land inside it without
aiming. Any figure quoted from a sample that small is a description of the
sample.

| Check | Status | Result |
| --- | --- | --- |
| Triangle test `[G11]` | Tried | Negative result on a corpus that was never suitable — 41 frames, few scenes |
| Effective strength `alpha_hat` | Tried | Separates every forgery here from every genuine frame — then falls to a six-line alpha sweep. A window, not a boundary |
| Triangle test implementation | **Validated** | Recovers on a synthetic corpus with independent scenes: lambda +1.338, Pearson +0.729, against -0.163 / -0.379 on ours. The code is right; the corpus was wrong |
| Pooled statistic `[B18]` | Implemented, `pooled_triangle` | **Not reproduced.** Flat at every stolen/public ratio from 0.33 to 0.83, 5/8 runs — chance. Cannot separate implementation, synthetic model, or unmet conditions |
| **Two fingerprints in one image** | **Not tested** | A forgery on a real carrier holds the carrier's PRNU *and* ours. A genuine frame holds one |
| Noise-floor physics | Not tested | Shot-noise scaling and read noise at the claimed ISO should not match a foreign carrier |
| Demosaic / CFA consistency | Not tested | A forgery carries the carrier's interpolation signature |
| Hot-pixel / defect map | Not built | Premise unchecked: in-camera correction may not survive to a delivered JPEG |

Nothing built so far catches the delivered-JPEG forgery, and the delivered
path is the one the product exists to serve. That is the honest state.

**There is no forgery detection success rate, and none should be quoted.**
With overlapping ranges no operating point gives useful detection at a
tolerable false-positive cost, and a false positive here means calling a
photographer's real photograph a fake. `fingerprint.consistency.stages`
encodes the consequence: stages 1 and 2 may add doubt and can never grant a
claim, and only the chain read produces `registered`. There is a test that
fails if that ordering is broken.

## Chainlink CRE, and what confidential compute does not do

Not built — `docs/e2e-checklist.md` §10. Recorded here because it is easy to
mistake for a defence against what this document describes, and it is not one.

Confidential compute removes the **scorer** as a trusted party: published
algorithm, private reference, signed score, so a third party gets a verdict
without anyone holding K and the service cannot lie about the number. That is
real, and it is the honest answer to keeping a reference off other people's
machines.

It does nothing about forgery. An enclave would score the forged DNG above at
868 and sign it faithfully. The signature attests that the computation was
performed correctly on the pixels it was given; it says nothing about where
those pixels came from. Confidential compute protects the reference from the
verifier. The attack happens before the pixels arrive.

## Disclosure

Fingerprints, references and the raw corpus are not published, and the reason
is measured rather than cautionary: **one RAW file off a body is enough** to
estimate K well enough to plant it invisibly. The frames are the kit, not just
the `.npz`. `docs/claims.md` carries the full reasoning.

Consequences we accept:

- Reproducibility suffers. We publish the method, the code, every number and
  the conditions it was taken under, and not the corpus.
- No forged image is committed either. Everything in `docs/adversarial.md`
  regenerates from a seed or from files already on the machine.

What may be published, by our own measurement: derivatives at 1800px quality
80, which `docs/gates.md` scores at 37, 35 and -33 against a threshold of 100.
The fingerprint is gone at that setting. Quality 95 at the same size scores
408 and is not safe.

## What the product may say

> This image carries body X's sensor fingerprint **and** body X's owner
> registered it at time T.

Never the first half alone. A match on an unregistered image says the pixels
carry the fingerprint; it does not say the light did.

## Standing rules

- Never publish K, a reference, or a RAW frame from an enrolled body.
- Register a body as soon as it is enrolled — `registerBody` is a race, and
  `bodyId` derives from `SHA-256(K)`, so a leaked K lets someone else win it.
- Register photographs at capture, not on demand. Priority is the defence.
- No hosted endpoint may accept a K and an image and return a stamped image.
  That is a forgery service regardless of intent.
- Treat any new defence as evidence until it has a measured false-positive
  rate on a corpus with many bodies and many scenes.

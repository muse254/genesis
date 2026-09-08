# The fingerprint-copy attack

**The sentence in `docs/claims.md` does not survive.** A leaked K forges a
match at PCE 116 with a distortion of 73 dB PSNR — invisible on any display,
against a threshold set at 100 and a genuine delivered JPEG that scores 1,148.
And the leak is not the interesting part: **one RAW file off the camera is
enough**, at 57 dB, which is still invisible. Everything below is measured
against the real `data/references/r10.npz` and the real Canon R10 corpus, with
`fingerprint/prnu.py` unmodified and `PCE_THRESHOLD` left at 100.

The attack is [G10]/[G11]'s fingerprint copy: the sensor model in [F09]
eq. (3) is generative and nothing in it is one-way, so anyone holding K can
evaluate it forwards. Plant `alpha * J * K` into an image J from a different
camera and the estimator recognises it, because the estimator asks exactly one
question — is there a term proportional to `J*K` in this residual — and the
attacker has just put one there.

Code: `fingerprint/attacks.py`. Tests: `fingerprint/validate_attacks.py`,
synthetic so they run without a fingerprint on disk.

**Independently re-measured 8 September 2026**, and three numbers did not
reproduce. Attacks 3 and 4 carry `### Correction` subsections with what was
measured instead; in both cases the attack is **cheaper** than first written,
and attack 4 does not work at all unless one step is left out. Attack 4's
estimate-from-stolen-frames path is not exposed in the CLI, so the corrected
figures were produced by calling `prnu` directly — the scripts are not
committed, but every number below is a `prnu.score` or a `fingerprint.py test`
against `data/references/r10.npz`. The headline is unchanged and understated.

## What falls, and what does not

The scoping question first, because it is the only part of this document that
changes what to build.

| Claim | Falls to K alone? | Also needs a key? | Code path |
| --- | --- | --- | --- |
| `fingerprint test` says MATCH | **yes** | no | `prnu.score`, `fingerprint.py:cmd_test` |
| `/score` and `/lookup` return `"match"` | **yes** | no | `scoring/app.py:_score_against` |
| The verify page says "Exposed on a known body" | **yes** | no | `verify/src/main.ts:verifyImage`, perceptual branch |
| `registerImage` accepts the forgery | no | **yes** — the body owner's wallet | `Registry.sol:registerImage` |
| The subgraph shows an `Image` entity | no | **yes** | `subgraph/src/registry.ts:handleImageRegistered` |
| An ERC-7053 `Commit` log entry exists | **yes** | no | `Registry.sol:commit` is permissionless |
| A session Merkle root exists | **yes** | no | `Registry.sol:commitSession` is permissionless |
| The attacker *owns* the body on chain | **yes, if nobody registered it first** | no | `Registry.sol:registerBody` |

Three things in that table deserve their own paragraph.

**The verify page is the hole.** `verifyImage` tries the exact branch first,
reads `images[imageHash]` on chain, and gets a zeroed struct for a forgery
nobody registered. It then falls through to `if (lookup.verdict === "match")`
and returns `verdict: "perceptual"` with the body name and the PCE — and
`render` prints **"Exposed on a known body"**, the body, "PCE 116.5 (threshold
100)", and "Matched by: aligned". No chain read happens on that path.
`lookupByPerceptualHash` throws `needs the subgraph` and is never called. So
the strongest sentence the product says is produced entirely by the scoring
service, for an image with no record, no signature and no owner. The caveat
line underneath — *"Origin, not truth. This says which sensor the light fell
on"* — is exactly the sentence the forgery falsifies, so it makes the page
worse rather than better.

**On chain, the owner check stops it — and it is not a signature check.**
`registerImage` requires
`body.owner == msg.sender`. The attacker cannot attribute a forged image to
somebody else's registered body, and the subgraph only mints an `Image` entity
from `ImageRegistered`. That check is doing real work and it is the only thing
in the system that does.

**But `registerBody` is a race, and K alone wins it.** `bodyId` derives from
`fingerprintCommitment`, which is `SHA-256` over K — so anyone holding K can
compute the id and call `registerBody` first. The contract only requires the
slot to be empty. The legitimate photographer is then permanently locked out:
`registerBody` reverts on "body already registered", and `revokeBody` requires
being the owner. For the R10 this is closed because the body is already
registered; for every future body it is open from the moment K leaks until the
owner registers.

The record signature in `ingest/record.py` is never checked by anything. It is
constructed and verified only in `ingest/validate_records.py`. On chain,
custody is `msg.sender`, not `recover_signer`. That is a coherent design — but
it means "the signing key" in the scoping question is really "the wallet that
called `registerBody`", and the ECDSA record signature is not currently part
of any verdict.

## Attack 1 — planting K in a photograph from another camera

Carrier: `Canon - EOS R10 - 3_2.CR3`, the second R10 body from `raw.pixls.us`,
serial `022031004996`. It is the strongest possible carrier for this attack
and the fairest test of it: same sensor geometry, same CFA, same model-level
artefacts, and `docs/gates.md` has it as the negative that set the threshold.

`J' = J * (1 + alpha * K)` per CFA plane, then rounded back onto the 14-bit raw
lattice. Multiplicative rather than additive, per [G11] eq. (8): `prnu.score`
correlates the residual against `J*K`, so an additive plant throws away most
of the peak for the same distortion.

| alpha | PCE, CFA planes | PSNR |
| --- | --- | --- |
| 0 (carrier alone) | 39.1 | — |
| **0.046** | **103.4** | **89.9 dB** |
| 0.25 | 6,721.9 | 75.5 dB |
| 0.50 | 27,949.7 | 69.5 dB |
| 1.00 | 106,895.7 | 63.5 dB |

And on the delivered path, which is what the scoring service is actually
pointed at — developed to 6000x4000, K planted on the pixel lattice with
`attacks.mosaic_field`, saved as JPEG q95, then read back through
`prnu.load_delivered_planes`:

| alpha | PCE, delivered JPEG | PSNR | SSIM |
| --- | --- | --- | --- |
| 0 (carrier alone) | 32.0 | — | — |
| **0.207** | **116.5** | **73.5 dB** | **0.99997** |
| 0.50 | 14,890.4 | 61.1 dB | 0.99954 |
| 1.00 | 89,947.1 | 54.8 dB | 0.99809 |

For scale: "visually lossless" is conventionally taken at about 40 dB. The
minimum-strength forgery is thirty decibels quieter than that. At the strength
an attacker would actually use — enough margin to survive a re-encode —
the damage is still 61 dB and SSIM 0.9995.

**The minimum alpha is set by quantisation, not by the threshold.** Below
alpha 0.03 on the CFA path the plant is smaller than half a raw DN and rounds
away completely; the PCE does not move at all until it clears that. This
carrier averages 0.05 of full scale, and the floor scales inversely with
carrier brightness, so a bright forgery is cheaper than a dark one. Any figure
quoted from an unquantised experiment is roughly five times too optimistic for
the attacker.

## Where the forgery dies, and where a real photograph dies

`stress.ladder` on the forgery at alpha 0.6, injected at native resolution and
then put through the same resize-and-encode ladder as a real frame. The
genuine columns are from `docs/gates.md`, same fingerprint, same code.

| Rung | **Forgery** | IMG_0217 | IMG_0216 | IMG_0230 |
| --- | --- | --- | --- | --- |
| 6000px q95 | 784 | 6,149 | 4,849 | 282 |
| 6000px q80 | 447 | 3,517 | 2,924 | 112 |
| 4000px q80 | 507 | 900 | 629 | -36 |
| 3000px q80 | 373 | 198 | 187 | -35 |
| 2400px q80 | 215 | 53 | -40 | 33 |
| 1800px q95 | 368 | 408 | 316 | 37 |
| **1800px q80** | **132** | **37** | **35** | **-33** |
| 1200px q80 | 32 | -35 | -38 | 33 |

**The forgery outlives every real photograph.** At 1800px q80 — the rung Gate B
calls the failure case, the rung that forced the sentence "provided the JPEG is
encoded at quality 95" — the forgery still clears the threshold at 132 while
the best genuine frame is at 37, in the null. It is also far flatter across the
ladder: 784 to 132 over six rungs, against 6,149 to 37 for IMG_0217.

That is a detector, and it is free. A real fingerprint is buried in one
exposure's worth of shot noise and degrades roughly with the pixels removed; a
planted one is a clean 16-frame average with the noise already divided out, so
it degrades far more slowly. **An image that scores in the low hundreds at
1800px q80 is more likely forged than genuine.** It is also a detector that
only works while the attacker does not know about it — alpha is a free
parameter and tuning it down to imitate the genuine decay curve costs nothing.

## Attack 2 — a carrier that was never a photograph

The complete form. `attacks.synthetic_carrier` generates a 6000x4000 test
pattern — gradients, discs, a sine grid, a little grain — from a seed. No
light, no lens, no sensor. Injected, saved as JPEG q95, scored through the
same delivered path.

| Carrier | PCE | PSNR | SSIM |
| --- | --- | --- | --- |
| Synthetic pattern, untouched | 28.2 | — | — |
| + K at alpha 0.2 | **37,175** | 57.9 dB | 0.99860 |
| + K at alpha 0.3 | 82,191 | 56.2 dB | 0.99790 |
| + K at alpha 0.6 | 291,608 | 53.0 dB | 0.99570 |

**A synthetic carrier is easier to forge than a photograph, by more than two
orders of magnitude.** At alpha 0.2 it reaches 37,175 where the photographic carrier at
alpha 0.207 reached 116. The reason is the estimator working as designed: it
is a matched filter for `J*K`, and a smooth synthetic image contributes almost
no competing sensor noise or scene texture to the residual, so nearly all the
residual energy is the plant. The cleaner the carrier, the purer the match.

That is the sentence "this image was exposed on body X" failing in the most
complete way available: nothing was exposed, and the system returns 291,608
against 18,929 for the strongest genuine held-out frame in `docs/gates.md`.
The forgery is not merely accepted; it is the best specimen the body has.

## Attack 3 — a different camera model, through the Gate B search

`Adobe DNG Converter - Canon EOS 5D Mark III` developed to 5760x3840 — a
different sensor, a different geometry, scoring 38.4 untouched through
`crop_and_scale_search`. K has to be cropped to fit, which is the realistic
case for any carrier that is not the same model.

| Carrier | PCE via scale search | PSNR |
| --- | --- | --- |
| 5D Mark III, untouched | 38.4 | — |
| + cropped K at alpha 0.6 | -34.7 | 59.6 dB |
| + cropped K at alpha 1.5 | **2,895** | 51.6 dB |

Alpha 0.6 fails and 1.5 succeeds, which is a bigger jump than the CFA path
needed. Two reasons, and they are both about the search rather than the plant:
the cropped K is misaligned against the developed raster, and the eight-way
orientation search picks a wrong orientation when the true peak is weak — at
alpha 0.6 it reported `90 deg`, at 1.5 it reported `0 deg`. The attack works
on a different model; it just costs about eight decibels more.

### Correction: cropping K is the attacker's mistake

Re-measured 8 September 2026. The table above makes the attack look harder
than it is, because it crops K to the carrier. An attacker would instead
resize the carrier to the target sensor's native resolution and plant the
whole of K, which lands on the aligned lattice and skips the search
altogether. Same carrier, developed and resized 5760x3840 -> 6000x4000 with
Lanczos, planted with `inject_delivered`, saved at JPEG q95 and scored
through `fingerprint.py test`:

| Carrier | PCE, aligned path | PSNR |
| --- | --- | --- |
| 5D Mark III resized, untouched | -30.9 | — |
| + K at alpha 0.5 | **11,934** | 61.7 dB |
| + K at alpha 1.0 | 149,987 | 54.9 dB |
| + K at alpha 1.5 | **393,382** | 51.6 dB |
| + K at alpha 3.0 | 1,256,056 | 45.8 dB |

At the same alpha 1.5 and the same 51.6 dB, that is 393,382 against the 2,895
above — 135x — and seven times the 56,255 of the strongest genuine frame in
`docs/gates.md`. A different camera model is not a harder carrier. It was the
resampling choice that was hard, and the attacker picks it.

One threshold effect worth recording, since it is the only thing that
resisted: on the 8-bit delivered path an alpha below about 0.3 rounds away
entirely. At alpha 0.15 the forgery scored -30.9, unchanged from untouched, at
86.6 dB — the plant was smaller than a quantisation step. The 14-bit CFA path
has no such floor, which is why alpha 0.06 suffices there.

## Attack 4 — the leak is not necessary

This is the finding that matters most, and it was not in the threat model as
posed.

An attacker does not need `r10.npz`. The ML estimator is public, in this repo,
and it runs on whatever frames the attacker has. Minimum alpha that clears
PCE 100 against the **shipped** fingerprint, by what the attacker holds
(green plane 3, CFA path, same carrier):

| The attacker holds | alpha | PCE | PSNR |
| --- | --- | --- | --- |
| The leaked K (16 frames, post-processed) | 0.062 | 100.3 | 87.2 dB |
| **1 RAW file from the body** | **0.250** | **101.2** | **57.4 dB** |
| 2 RAW files | 0.246 | 102.0 | 61.3 dB |
| 4 RAW files | 0.258 | 100.0 | 61.5 dB |
| 8 RAW files | 0.289 | 101.6 | 62.1 dB |
| 16 RAW files | 0.438 | 101.5 | 64.2 dB |
| 1 delivered JPEG at native resolution | — | never clears 100 (best 73.0) | — |
| 2 delivered JPEGs at native resolution | 7.250 | 100.6 | 41.5 dB |

**One raw file is a forgery kit.** The leak buys the attacker thirty decibels
of quiet — 87 dB against 57 dB — and nothing else. Both are invisible.

### Correction: do not postprocess the stolen estimate

Re-measured 8 September 2026, and this is the step the table above leaves out.
`prnu.postprocess` — zero-mean rows and columns, then the DFT Wiener — is a
*defender-side* step. It exists so that two bodies of one model stop
correlating through shared artefacts. Nothing obliges an attacker to run it,
and running it destroys the attack:

| Attacker's estimate from 1 RAW | alpha | PCE vs shipped K |
| --- | --- | --- |
| postprocessed | 0.25 | 39.3 — the null |
| postprocessed | 2.00 | 42.2 — still the null |
| **not postprocessed** | **0.10** | **280.5** |
| not postprocessed | 0.25 | 2,049 |
| not postprocessed | 0.60 | 6,255 |

Carrier throughout is the second R10 body, scoring 39.1 untouched. The
postprocessed estimate never leaves the null however hard it is planted; the
raw estimate clears the threshold at alpha 0.10, at 58.4 dB. Whoever
reproduces this should expect the attack to appear to fail until that call is
removed.

Corrected minimum alphas, then: **0.10 from one RAW file**, not 0.250, at
58.4 dB rather than 57.4. The attack is cheaper than the table above states.

And the alpha column in that table rises with more stolen frames, which is
backwards. More frames strictly help the attacker, as they must — the estimate
converges on K. Measured on plane 3 against the shipped fingerprint:

| Frames stolen | corr with true K | best PCE reached |
| --- | --- | --- |
| 1 | +0.035 | 6,255 |
| 4 | +0.252 | 50,539 |
| 16 | +0.528 | 77,830 |

Controls, because a result this strong needs them:

| Control | PCE |
| --- | --- |
| Carrier alone, plane 3 | -37.3 |
| Single-frame estimate from **the other R10 body**, alpha 0.6 | 29.1 |
| Single-frame estimate from our body, **shuffled**, alpha 0.6 | -32.5 |
| Single-frame estimate from our body, alpha 0.6 | **399.4** |

So the transfer is identity, not a model-level artefact: running the identical
procedure on the wrong body of the same model lands in the null.

The delivered-JPEG row is the one that is thin. **n = 2.** `game.jpg` and
`a-piece-of-quiet.jpg` are the only native-resolution delivered files in the
corpus, and two is not a sample. [G11] and [Q19] both build usable fingerprints
from 20 to 4,648 web JPEGs, so the honest reading of that row is "two is not
enough here", not "web JPEGs are safe". [Q19] measured 1.4 million scraped
social-media images at mean JPEG quality 83.5 and found the attack fails below
about q85, which is the one piece of good news in this section and it is
somebody else's measurement, not ours.

**Consequence for the disclosure rule.** `.gitignore` already says a published
enrolment set is a forgery kit, and it is right. What the numbers add is that
the threshold is *one file*, not a set, and that it applies to every RAW the
photographer has ever delivered to a client.

## How much of K is enough

Degrading the leaked K, injecting at alpha 0.6 on the delivered path:

| The leak was | PCE | PSNR | Verdict |
| --- | --- | --- | --- |
| All of K | 25,605 | 59.3 dB | MATCH |
| Downsampled 2x2 | 1,333 | 63.0 dB | MATCH |
| Downsampled 4x4 | 31.8 | 69.3 dB | no match |
| Downsampled 8x8 | 32.1 | 75.5 dB | no match |
| Centre 50% only | 882 | 66.4 dB | MATCH |
| Centre 25% only | 31.5 | 74.3 dB | no match |
| Quantised to 4 bits | 27,426 | 59.0 dB | MATCH |
| Quantised to 2 bits | 82,001 | 52.7 dB | MATCH |
| **Quantised to 1 bit — the sign map only** | **104,590** | 47.2 dB | **MATCH** |

**One bit per photosite is enough.** Keeping only `sign(K)` — throwing away
every magnitude — still forges, and on the CFA path directly comparable at
equal amplitude it reaches 4,886 against the full K's 8,886. One bit per
photosite instead of thirty-two, for a factor of two.

The PSNR column is in the table because a coarsely quantised K is a *louder* K
at the same alpha, so the PCE column alone would overstate the coarse rows.
Read across: the one-bit row buys its 104,590 with twelve decibels more
distortion than the full-K row, and 47 dB is still invisible.

Resolution is the one axis where degradation actually protects. Halving K
survives; quartering it does not, and a quarter of K's pixels is also where the
centre-crop row fails. That is the same fact twice — PCE grows with the number
of correlated samples, which `docs/gates.md` already records from the
defender's side when cropping enrolment to 2048 cost roughly 6x.

**What this means for handling.** "Do not publish K" is not the rule. The rule
is that anything from which a half-resolution or one-bit copy of K can be
recovered is K: a thumbnail of the fingerprint, a lossily compressed archive of
it, a debug visualisation. And per attack 4, a single RAW file is in that set.

## The defences

### The triangle test

The principal published defence, [G11] section III. K is a linear function of
the enrolment frames' residuals, so every enrolment frame's *own noise
realisation* is inside K; a forgery built by planting K carries a copy of it,
and a genuine new exposure of the same body does not. The verifier holds those
frames, so the verifier can look for it.

Implemented in `attacks.py`: `TriangleFrame`, `predicted_correlation`
([G11] eqs. 10–11), `calibrate_triangle` (eq. 13) and `triangle_d` (eq. 15).

**The published statistic does not calibrate on this corpus, and I could not
make it.** Eq. (10) predicts `corr(W_I, W_J)` from the other two sides of the
triangle; the affine fit `c = lambda*c_hat + eta` is supposed to come out with
`lambda > 1`. On 820 innocent pairs of the 41 R10 frames it comes out at
**lambda = -0.163, Pearson -0.379** — no relationship at all. Observed
correlations run to 0.21 where the prediction never exceeds 0.027.

The reason is the corpus. These are 41 frames from a handful of scenes in one
shoot, not independent natural images, so `corr(W_I, W_J)` between two genuine
frames is dominated by shared *scene* content that the mutual-content factor of
eq. (11) does not model. [G11] used 358 unrelated images from a camera Eve
never touched. That condition is not available here and would not be available
to most photographers either.

**The underlying signal is real, though, and visible in the raw correlation.**
Controlled experiment: Eve estimates K from frames 1–8, Alice holds frames 9–16
and 17–41. Eve's forgery scores PCE 616 against Alice's independent fingerprint
at alpha 0.1. Correlating the forgery's residual against each candidate frame:

| Candidate frames | n | mean c | min | max |
| --- | --- | --- | --- | --- |
| **Used by Eve** | 8 | **+0.012876** | +0.002947 | +0.021831 |
| Alice's own enrolment | 8 | +0.001114 | +0.000733 | +0.001703 |
| Neither | 25 | +0.002214 | +0.000438 | +0.005433 |

Six to twelve times elevated on exactly the frames the attacker used. But the
ranges **overlap** — the weakest used frame (0.0029) sits below the strongest
unused one (0.0054) — so per-frame this is not a decision, and the pooled form
of [G11] eq. (17) would be needed. With eight used frames out of forty-one,
`N/N_c = 0.2`, which is below the `N/N_c > 0.5` the paper says the pooled test
needs.

Run against the shipped `r10.npz`, the same correlation produces a ranking with
no clean break — the values decay smoothly from +0.0063 to -0.0003 across all
41 frames — but the top thirteen ranks are all frames numbered 0191 to 0217,
and no frame numbered above 0219 reaches them. That is consistent with the
enrolment set being the earlier frames, which is also what a clipping cut
applied in filename order would produce. The enrolment set is not recorded in
the `.npz`, so I could not check it. Suggestive, not evidence.

**`save_fingerprint` should record which frames were enrolled.** It writes
`frames: 16` and nothing else. Without the list, the verifier cannot run the
test that the frames were kept for, and this section had to be a controlled
re-enrolment instead of a measurement on the real fingerprint.

**And in this threat model the test is inapplicable at its root.** [G11]
requires the verifier's fingerprint to be independent of the attacker's. When K
itself leaks, they are the same object, and there is nothing for the prediction
to be a prediction *of*.

### Collinearity — the defence that half worked

The one that did separate, and it is not the triangle test. Project `J*K` out
of the suspect's residual and out of each candidate frame's residual, then
correlate what is left. `attacks.strip_fingerprint` and `attacks.collinearity`.

A genuine frame carries the body's whole response — readout structure, dark
current, lens signature, and the unfiltered part of the PRNU that
`prnu.postprocess` deliberately removes with its zero-mean and DFT Wiener
stages. The published K is only a filtered slice of that. A forgery carries
`alpha * J * K` and nothing else, so once `J*K` comes out it is empty.

Against the shipped `r10.npz`, 39 candidate frames, green plane:

| Suspect | mean rho | max rho |
| --- | --- | --- |
| Forgery from leaked K, alpha 0.6 (PCE 8,886) | +0.000239 | +0.000994 |
| Carrier alone, different R10 body (PCE -37) | +0.000153 | +0.000876 |
| Genuine IMG_0230, the weakest own frame | **+0.017097** | +0.044084 |
| Genuine IMG_0217, the strongest | **+0.080026** | +0.209481 |

Seventy to three hundred times apart, and the forgery is statistically
indistinguishable from a frame that came out of a *different camera* — which is
the correct verdict, stated the right way round: this residual shares nothing
with body A beyond the number that was published about body A.

**And it is defeated by exactly the attacker who does not need the leak.** The
same detector, against forgeries built from the attacker's own ML estimate —
un-post-processed, so it carries all the structure `prnu.postprocess` strips
out and the projection therefore cannot remove:

| Suspect | PCE | mean rho | max rho |
| --- | --- | --- | --- |
| Forgery from the leaked K, minimum strength | 101.8 | +0.000158 | +0.000890 |
| Forgery from the leaked K, alpha 0.6 | 8,886 | +0.000239 | +0.000994 |
| **Forgery from 1 RAW file, alpha 0.25** | **695** | **+0.005052** | **+0.080655** |
| **Forgery from 8 RAW files, alpha 0.30** | **23,883** | **+0.009569** | **+0.053663** |
| Carrier alone, different R10 body | -37 | +0.000153 | +0.000876 |
| Genuine IMG_0230, weakest own frame | 1,212 | +0.017097 | +0.044084 |
| Genuine IMG_0217, strongest | 18,929 | +0.080026 | +0.209481 |

The eight-file forgery sits at 0.0096 against 0.0171 for the weakest genuine
frame — the same order of magnitude, not two apart — and the one-file forgery's
maximum, 0.081, is above the weakest genuine frame's maximum of 0.044. The
detector separates a **leaked-K** forgery cleanly and does not separate a
**self-estimated** one.

Which means it catches only the attacker who took the harder route. Attack 4
shows the self-estimated forgery is cheaper to mount and, per this table,
harder to detect. Deploy the check — it is one wavelet decomposition per
enrolment frame and it raises the bar — but do not let it into a claim.

### What does not help

**The commitment on chain.** `fingerprintCommitment` is `SHA-256` over K. Once
K leaks, the commitment proves that the leaked K is the enrolled K — it
authenticates the forgery kit. It was never a defence against this and the
design does not claim it is; it is worth writing down because a hash on a
blockchain reads like a security control and here it is a binding, nothing
more.

**Raising `PCE_THRESHOLD`.** The forgery reached 291,608 on a synthetic
carrier. There is no threshold that admits genuine photographs and excludes
this, because the attacker chooses the score.

**The degradation ladder.** It is a floor, not a ceiling: the forgery survives
further down it than any real photograph.

**Session Merkle roots.** `commitSession` is permissionless and takes any root.
It proves a set of hashes was fixed at a time, which is useful against later
substitution and useless against a forgery committed alongside the genuine
frames.

**What does help**, in order of how much:

1. **`registerImage`'s owner check.** It is the only mechanism in the system
   the attack does not get past. Everything the product can safely say has to
   be downstream of it.
2. **First-registration time.** A genuine photograph registered at capture
   beats a forgery registered later. This is real, it is on chain, and it is
   the reason to register early rather than on demand — but it only works for
   images the photographer actually registered, so it defends an archive and
   not the world.
3. **Collinearity**, as a re-scoring step for anything the scoring service
   calls a match. Cheap, and it catches a leaked-K forgery outright — but it
   does not catch an attacker who estimated K from the body's own files, which
   is the cheaper attack. A bar, not a wall.
4. **Registering the body early.** It closes the `registerBody` race.

## What has to change

**`docs/claims.md`, "We certify".** The first bullet is false as written and
the fourth is unaffected. Proposed:

> - this image contains the sensor fingerprint of body X, **and body X's
>   owner signed for it**
> - body X is registered to identity Y
> - it was first registered at time T
> - these derivatives descend from that original

with, in the same file:

> ## What the fingerprint alone proves
>
> Nothing, on its own. Anyone holding K — or **one RAW file off the body** —
> can plant the fingerprint in an image that was never exposed on it, at a
> distortion of 57 to 90 dB PSNR, which is invisible. Measured against our own
> reference: `docs/adversarial.md`.
>
> A PCE score is evidence only in combination with an on-chain registration by
> the body's owner, and only for images registered before the dispute. **A
> match on an unregistered image says the pixels carry the fingerprint. It does
> not say the light did.**

**`verify/src/main.ts` — done, `acf3f87`.** The perceptual branch no longer
says "Exposed on a known body". There are three outcomes now: *registered by
the body's owner* when a chain read succeeded, *fingerprint matched, nothing
registered* in amber with copy saying outright that it is not a pass, and *no
record* on a neutral rule rather than an amber one — an absent record is not a
finding about the image. The "origin, not truth" caveat moved to the
registered verdict only, since on the perceptual branch it was the exact
sentence a forgery falsifies.

**`README.md:36` and `BUILD.md:491`** carry the same sentence and need the same
edit.

## Reproducing this

```bash
python3 fingerprint/attacks.py alpha --fingerprint data/references/r10.npz \
    --carrier "fingerprint/raw-test-files/Canon - EOS R10 - 3_2.CR3"
python3 fingerprint/attacks.py ladder --fingerprint data/references/r10.npz \
    --carrier "fingerprint/raw-test-files/Canon - EOS R10 - 3_2.CR3" --alpha 0.6
python3 fingerprint/attacks.py synthetic --fingerprint data/references/r10.npz \
    --alpha 0.3 --seed 7 --out /tmp/never-a-photograph.jpg
python3 fingerprint/attacks.py partial --fingerprint data/references/r10.npz \
    --carrier "fingerprint/raw-test-files/Canon - EOS R10 - 3_2.CR3"
python3 fingerprint/attacks.py triangle --fingerprint data/references/r10.npz \
    --suspect "forgery=/tmp/never-a-photograph.jpg" \
    --suspect "genuine=fingerprint/raw-test-files/IMG_0217.CR3" \
    --candidates fingerprint/raw-test-files/
```

No forged image is committed to this repo, for the same reason no fingerprint
is. Every one above is regenerated from a seed or from a file already on the
machine.

## Sample sizes, stated plainly

Everything here is **one body, one leaked fingerprint, one same-model negative,
one different-model negative**. `docs/gates.md` is careful to say that one
other body is not a false-positive rate; the same discipline applies in the
other direction. What these numbers establish is that the attack works and
roughly what it costs. They do not establish a detection rate for any defence,
and the triangle-test section is a negative result on a corpus that was never
suitable for it rather than a finding about the test.

Specifically thin:

- **n = 2** for the delivered-JPEG attacker in attack 4.
- **n = 1** carrier for the whole of attacks 1 and 3.
- The enrolment set of `r10.npz` is **not recorded**, so the triangle test
  against the shipped fingerprint could not be scored against ground truth.
- The collinearity separation is measured on **two** genuine frames against
  **four** forgeries, each scored against 39 candidate frames. Two genuine
  frames is not a null distribution; it should be run over all 41 before
  anyone relies on the numbers.

Not attempted, and each would make the attack stronger rather than weaker:

- **[L17]'s block-wise dispersal.** Estimate K separately per 32x32 block from
  a different random subset of the stolen frames, which cuts what any single
  frame shares with the forgery. It drops [G11]'s individual triangle test
  below 4% detection at N >= 100. Nothing here needed it, because the test did
  not work in the first place.
- **[L17]'s target-PSNR alpha.** Choose alpha per block to hit a fixed image
  quality rather than a fixed strength. It removes the one thing an attacker
  here genuinely does not know — how much is enough — and this document's
  bisection is a cruder version of the same idea.
- **A generative carrier.** `synthetic_carrier` is a test pattern, deliberately,
  so it regenerates from a seed. A diffusion output would make the same point
  with a picture somebody would believe, and given the synthetic result it
  would score higher rather than lower.

## References

- **[F09]** J. Fridrich, "Digital Image Forensics Using Sensor Noise", IEEE
  Signal Processing Magazine 26(2), 2009. Sensor model eq. (3), ML estimator
  eq. (6), CRLB eq. (7), PCE eq. (14).
- **[G10]** M. Goljan, J. Fridrich, M. Chen, "Sensor Noise Camera
  Identification: Countering Counter-Forensics", Proc. SPIE 7541, Media
  Forensics and Security XII, 2010.
- **[G11]** M. Goljan, J. Fridrich, M. Chen, "Defending Against
  Fingerprint-Copy Attack in Sensor-Based Camera Identification", IEEE TIFS
  6(1), 2011, 227–236. The journal version of [G10]; forgery eq. (8), triangle
  test eqs. (10)–(17), the appendix derivation.
- **[L17]** C. Li, Y. Luo, Q. Rao, J. Huang, "Anti-Forensics of Camera
  Identification and the Triangle Test by Improved Fingerprint-Copy Attack",
  arXiv:1707.07795. Target-PSNR alpha selection, block-wise dispersal.
- **[B18]** M. Barni, E. Santoyo García, B. Tondi, "An Improved Statistic for
  the Pooled Triangle Test against PRNU-Copy Attack", arXiv:1805.02899.
- **[Q19]** E. Quiring, M. Kirchner, K. Rieck, "On the Security and
  Applicability of Fragile Camera Fingerprints", ESORICS 2019,
  arXiv:1907.04025. JPEG-quality cliff at q85; the 1.4M-image social-media
  quality survey.

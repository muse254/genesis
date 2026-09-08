# Camera sensors, or what makes K possible

Every photograph carries a birthmark left by the individual sensor it passed
through. This is where it comes from, why it survives delivery, and how
`fingerprint/prnu.py` recovers it.

Claims below are tagged with their source: bracketed keys are papers, listed
at the end; repo paths are measurements made here.

## The birthmark

Photosites do not convert light at identical rates. Doping concentration
varies across the wafer, etched photosite areas differ, and microlenses are
imperfectly placed, so photosite *(i, j)* has a fixed multiplicative gain
typically within a percent of unity [LFG06] [F09]. This is photo-response
non-uniformity, PRNU.

Three properties make it an identity:

| Property | Why | Source |
| --- | --- | --- |
| Permanent | Comes from die structure, so it does not drift with temperature, age or firmware as dark current does | [LFG06] |
| Effectively random | Nothing in manufacturing correlates two sensors, including adjacent dies from one wafer | [LFG06] [CFGL08] |
| Present in every exposure | Light must land on the photosites to be measured, so the gain applies to every frame the sensor takes | [F09] |

The third is what the system rests on. The fingerprint is not metadata, which
can be stripped, and not a firmware signature, which needs the manufacturer.
It is a property of the measurement.

## The sensor model

An exposure is `I = I0 + I0*K + Theta` [F09 eq. 3], with `I0` the noise-free
scene, `K` the fingerprint and `Theta` shot, read and quantisation noise. `K`
multiplies the scene rather than adding to it.

Two consequences:

- Bright pixels carry more fingerprint than dark ones — where `I0` is near
  zero, `I0*K` is too. [F09] concludes the best enrolment frames are "those
  with high luminance (but not saturated) and small sigma^2".
- Saturated pixels carry none. A clipped photosite is clamped, not modulated
  [F09]. `SATURATION_LEVEL = 0.99` marks them; `SATURATION_WARN = 0.01`
  complains past one percent of a frame.

## Recovery

**Residual.** Denoise and subtract, `W = I - denoise(I)` [LFG06]. The filter
is the wavelet Wiener of [F09 App. A] over the Mihcak local-variance
estimator [M99]: `db8`, `WAVELET_LEVELS = 4`, variance taken as the *minimum*
over `WIENER_WINDOWS = (3, 5, 7, 9)`.

The minimum biases the filter toward calling a coefficient noise rather than
signal. That costs scene leakage and keeps fingerprint a cautious filter
would discard — leaked scene is suppressed later, filtered-away fingerprint
is gone. `SIGMA = 2.0/255.0` overestimates sensor noise for the same reason,
following [F09 App. A].

**Estimator.** `K = sum(W*I) / sum(I^2)` [F09 eq. 6], the maximum-likelihood
form under the multiplicative model, weighting each frame by its brightness.
Introduced in [CFGL08]. The model is linear, so the estimator is
minimum-variance unbiased with variance falling as 1/frames [F09 eq. 7] —
which is where the 40-frame enrolment requirement comes from.

## Why RAW CFA planes

`load_raw_planes` refuses anything that is not a CFA mosaic. Demosaicing
interpolates each output pixel from its neighbours, which blurs the
per-photosite gains that are the fingerprint and imprints the manufacturer's
interpolation pattern — shared by every body of the model — on top [CFGL08].
Splitting first gives one real image per photosite type.

This choice is also why phone output is unusable here; see
[docs/phones.md](phones.md).

## Identity versus family resemblance

A raw K still contains artefacts shared across every body of a model: CFA
interpolation, JPEG blocking, row and column readout structure. Left in, two
bodies of the same model correlate through shared inheritance [CFGL08].

`postprocess` removes them in two passes, following [CFGL08] and [DDE]:
`_zero_mean` subtracts per-column then per-row means, since readout patterns
are constant along a row or column; `_wiener_dft` attenuates strong periodic
frequency structure, on the reasoning that a spatially coherent frequency is
a design artefact rather than this die's manufacturing noise.

Measured here (`docs/e2e-checklist.md`):

| Probe | PCE |
| --- | --- |
| Genuine frames, enrolled body | 1,895 – 56,255 |
| Delivered JPEG, native resolution | 1,147.8 |
| Different Canon R10, same model | 39.1 |
| Canon 5D Mark III, different model | 26.6 |

## Comparison

Matching uses Peak-to-Correlation-Energy [F09 eq. 14], introduced for this
purpose in [GF08]: the peak of the circular cross-correlation surface against
the energy of the rest, excluding an 11x11 neighbourhood. PCE rather than raw
correlation because it is shift-invariant and its null is stable enough for
one threshold across bodies [GF08]. The sign is kept — a strong negative peak
is not a match.

Peaking over every shift raises the null: uncorrelated inputs concentrate near
`2*ln(N)`, about 22 on a 256x256 plane and 31 on a full-size one, not near 1.
The orientation search raises it further, the null becoming the largest of
eight tries. Observed nulls on R10 planes: 24 to 43 (`docs/gates.md`).

`PCE_THRESHOLD = 100.0` is roughly twice the worst null seen and well under
the weakest true match. It rests on **one** other body; a false-positive rate
needs dozens. Current public benchmark for context: PRNU-Bench, 73.65% top-1,
AUC 0.967, EER 0.097 across 126 sensors [PB25] — closed-set identification,
not verification against one known body.

## What weakens it

The fingerprint lives in high spatial frequencies, which is what processing
attacks.

| Operation | Effect | Source |
| --- | --- | --- |
| Saturation | Clipped pixels carry no fingerprint | [F09] |
| Dim exposure | `I0*K` shrinks with `I0` | [F09 eq. 3] |
| Heavy JPEG | Quantises the high-frequency detail away; 1800px q95 scores 408, q80 scores 37 | `docs/gates.md` |
| Resize / crop | Breaks pixel-to-photosite alignment; needs a scale and orientation search | [GF08] |
| Multi-frame fusion | Averages the fingerprint down, smears it across neighbours | [docs/phones.md](phones.md) |
| Aggressive denoise | Removes the residual band directly | [LFG06] |

A delivered JPEG at native resolution still scores 1,147.8, so ordinary
delivery does not destroy it.

## K never leaves the machine

Anyone holding K can claim to be that body, so only `commitment(K)` is
published — SHA-256 over a pinned serialisation tagged `genesis-prnu-k-v1`,
stored as `BodyRecord.fingerprintCommitment`. Changing dtype, byte order or
shape changes the hash and invalidates every prior registration, so it is
pinned and regression-tested.

The commitment proves K was not altered after registration. It gives no
protection if K leaks; the hash of a leaked secret is still leaked. See
`docs/adversarial.md`.

## What it does not prove

It places a photograph on a sensor, and nothing more. A camera pointed at a
high-quality screen produces a genuine exposure, PRNU intact, of a scene that
never existed. No sensor-level method reaches that, including in-camera
cryptographic signing. Origin, not truth — [docs/claims.md](claims.md).

## References

- **[LFG06]** J. Lukáš, J. Fridrich, M. Goljan, "Digital Camera Identification
  from Sensor Pattern Noise", *IEEE TIFS* 1(2), 205–214, June 2006.
  <https://ieeexplore.ieee.org/document/1634362>
- **[CFGL08]** M. Chen, J. Fridrich, M. Goljan, J. Lukáš, "Determining Image
  Origin and Integrity Using Sensor Noise", *IEEE TIFS* 3(1), 74–90, March
  2008. <https://ws2.binghamton.edu/fridrich/Research/DoubleColumnFinal.pdf>
- **[GF08]** M. Goljan, J. Fridrich, "Camera Identification from Cropped and
  Scaled Images", *Proc. SPIE* 6819, 68190E, 2008.
  <https://doi.org/10.1117/12.766732>
- **[F09]** J. Fridrich, "Digital Image Forensics Using Sensor Noise", *IEEE
  Signal Processing Magazine* 26(2), 26–37, March 2009. Sensor model eq. (3),
  ML estimator eq. (6), CRLB eq. (7), PCE eq. (14), denoiser App. A.
  <http://ws2.binghamton.edu/fridrich/Research/full_paper_02.pdf>
- **[M99]** M. K. Mihcak, I. Kozintsev, K. Ramchandran, "Spatially Adaptive
  Statistical Modeling of Wavelet Image Coefficients and its Application to
  Denoising", *IEEE ICASSP* 1999.
- **[PB25]** PRNU-Bench, arXiv:2509.17581. <https://arxiv.org/abs/2509.17581>
- **[DDE]** Binghamton DDE Lab reference implementation.
  <https://dde.binghamton.edu/download/camera_fingerprint/>

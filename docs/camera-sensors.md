# Camera sensors, or what makes K possible

Why every photograph carries a birthmark from the individual sensor it passed
through, and how `fingerprint/prnu.py` recovers it.

Bracketed keys are papers, listed at the end. Repo paths are measurements made
here.

## The birthmark

Photosites do not convert light at identical rates: doping varies across the
wafer, etched areas differ, microlenses sit imperfectly. So photosite *(i, j)*
has a fixed multiplicative gain, typically within a percent of unity
[LFG06] [F09]. That is photo-response non-uniformity, PRNU.

| Property | Why | Source |
| --- | --- | --- |
| Permanent | Comes from die structure, so it does not drift with temperature, age or firmware as dark current does | [LFG06] |
| Effectively random | Nothing in manufacturing correlates two sensors, including adjacent dies from one wafer | [LFG06] [CFGL08] |
| In every exposure | Light must hit the photosites to be measured, so the gain applies to every frame | [F09] |

The third is the one the system rests on: not metadata, which strips, and not
a firmware signature, which needs the manufacturer. A property of the
measurement.

## The sensor model

`I = I0 + I0*K + Theta` [F09 eq. 3] — scene, fingerprint, noise. `K`
multiplies the scene rather than adding to it, which sets everything
downstream: bright pixels carry more fingerprint than dark ones, and saturated
pixels carry none, being clamped rather than modulated [F09].

## Recovery

**Residual.** `W = I - denoise(I)` [LFG06], using the wavelet Wiener filter of
[F09 App. A] over the Mihcak estimator [M99]: `db8`, 4 levels, variance the
*minimum* over windows `(3, 5, 7, 9)`. The minimum biases toward calling a
coefficient noise — leaked scene can be suppressed later, filtered-away
fingerprint cannot be recovered. `SIGMA = 2.0/255.0` overestimates noise for
the same reason [F09 App. A].

**Estimator.** `K = sum(W*I) / sum(I^2)` [F09 eq. 6] [CFGL08], the ML form,
weighting each frame by its brightness. Minimum-variance unbiased with
variance falling as 1/frames [F09 eq. 7].

## Enrolment: how many frames, and which

**Count.** Variance falls as 1/frames [F09 eq. 7], so error falls as
1/sqrt(N): 10 to 40 halves it, 40 to 160 halves it again. The curve flattens
past ~40; [CFGL08] and [DDE] work from ~50.

Yield is the binding constraint in practice. Of 41 frames shot for Gate A, 26
passed the clipping cut and 16 were enrolled, 10 held back to test against
(`docs/gates.md`). You shoot 40–50 to have enough left after culling and
holdout.

**Which.** [F09] wants "high luminance (but not saturated) and small sigma^2
(which means smooth content)" — two effects from [F09 eq. 7]: variance falls
with luminance, since `K` multiplies the scene, and rises with texture, since
the denoiser leaks scene edges into the residual.

| Provide | Why | Source |
| --- | --- | --- |
| Bright, nothing clipping | `I0*K` scales with `I0`; clipped photosites carry nothing | [F09] |
| Smooth subject — a defocused wall is ideal | Scene edges survive denoising | [F09] [LFG06] |
| Full resolution, never cropped | PCE grows with sample count; `--crop 2048` costs ~6x and put one frame under threshold | `docs/gates.md` |
| Long Exposure NR off | Dark-frame subtraction written into the raw itself | `docs/gates.md` |

**What did not matter.** Gate A violated four of its five conditions and
passed at 32x over the null: all 41 frames C-RAW, ISO 100–3200, 15 clipping,
ordinary handheld photographs rather than flats (`docs/gates.md`). So an
existing archive is likely to work, which matters more for the product than
the ideal procedure does. The cost is that the ideal procedure has never been
run — flats at base ISO should do better, but that is inference, not
measurement.

**Green planes carry the result**, 4–5x over red: twice the photosites in
RGGB. `prnu.score()` sums all four surfaces, which add coherently since a true
match peaks at the same shift in each (`docs/gates.md`).

## Why RAW CFA planes

`load_raw_planes` refuses anything that is not a CFA mosaic. Demosaicing
interpolates each pixel from its neighbours, blurring the per-photosite gains
that *are* the fingerprint, and imprints the manufacturer's interpolation
pattern — shared across every body of the model — on top [CFGL08]. This is
also why phone output is unusable here: [docs/phones.md](phones.md).

## Identity versus family resemblance

Raw K still holds artefacts shared by every body of a model — CFA
interpolation, JPEG blocking, row and column readout. Left in, two bodies of
one model correlate through shared inheritance [CFGL08]. `postprocess`
zero-means columns then rows, then attenuates coherent frequency structure
[CFGL08] [DDE].

Measured (`docs/gates.md`):

| Probe | PCE |
| --- | --- |
| Genuine frames, enrolled body | 1,895 – 56,255 |
| Delivered JPEG, native resolution | 1,147.8 |
| Different Canon R10, same model | 39.1 |
| Canon 5D Mark III, different model | 26.6 |

## Comparison

PCE [F09 eq. 14] [GF08]: correlation peak against the energy of the rest of
the surface, excluding an 11x11 neighbourhood. Shift-invariant, and its null
is stable enough for one threshold across bodies [GF08]. Sign is kept — a
strong negative peak is not a match.

Peaking over every shift raises the null to about `2*ln(N)`, roughly 22 on a
256x256 plane, not 1; the orientation search raises it further, the null being
the largest of eight tries. Observed: 24–43 (`docs/gates.md`).

`PCE_THRESHOLD = 100.0` is about twice the worst null and well under the
weakest true match. It rests on **one** other body; a false-positive rate
needs dozens. External context: PRNU-Bench, 73.65% top-1, EER 0.097 across 126
sensors [PB25] — closed-set identification, not verification against one known
body.

## What weakens it

| Operation | Effect | Source |
| --- | --- | --- |
| Saturation | Clipped pixels carry no fingerprint | [F09] |
| Heavy JPEG | 1800px q95 scores 408; q80 scores 37 | `docs/gates.md` |
| Resize / crop | Breaks pixel-to-photosite alignment | [GF08] |
| Multi-frame fusion | Averages it down, smears it across neighbours | [docs/phones.md](phones.md) |
| Aggressive denoise | Removes the residual band directly | [LFG06] |

A delivered JPEG at native resolution still scores 1,147.8, so ordinary
delivery does not destroy it (`docs/gates.md`).

## K never leaves the machine

Anyone holding K can claim to be that body, so only `commitment(K)` is
published — SHA-256 over a serialisation tagged `genesis-prnu-k-v1`. Changing
dtype, byte order or shape invalidates every prior registration, so it is
pinned and regression-tested. It proves K was not altered after registration
and gives no protection if K leaks; see `docs/adversarial.md`.

## What it does not prove

It places a photograph on a sensor, nothing more. A camera pointed at a screen
produces a genuine exposure, PRNU intact, of a scene that never existed — no
sensor-level method reaches that, in-camera signing included. Origin, not
truth: [docs/claims.md](claims.md).

## References

- **[LFG06]** Lukáš, Fridrich, Goljan, "Digital Camera Identification from
  Sensor Pattern Noise", *IEEE TIFS* 1(2), 205–214, 2006.
  <https://ieeexplore.ieee.org/document/1634362>
- **[CFGL08]** Chen, Fridrich, Goljan, Lukáš, "Determining Image Origin and
  Integrity Using Sensor Noise", *IEEE TIFS* 3(1), 74–90, 2008.
  <https://ws2.binghamton.edu/fridrich/Research/DoubleColumnFinal.pdf>
- **[GF08]** Goljan, Fridrich, "Camera Identification from Cropped and Scaled
  Images", *Proc. SPIE* 6819, 68190E, 2008. <https://doi.org/10.1117/12.766732>
- **[F09]** Fridrich, "Digital Image Forensics Using Sensor Noise", *IEEE SPM*
  26(2), 26–37, 2009. Model eq. (3), estimator eq. (6), CRLB eq. (7), PCE
  eq. (14), denoiser App. A.
  <http://ws2.binghamton.edu/fridrich/Research/full_paper_02.pdf>
- **[M99]** Mihcak, Kozintsev, Ramchandran, "Spatially Adaptive Statistical
  Modeling of Wavelet Image Coefficients and its Application to Denoising",
  *IEEE ICASSP* 1999.
- **[PB25]** PRNU-Bench, arXiv:2509.17581. <https://arxiv.org/abs/2509.17581>
- **[DDE]** Binghamton DDE Lab reference implementation.
  <https://dde.binghamton.edu/download/camera_fingerprint/>

# Camera sensors, or what makes K possible

Every photograph carries a birthmark left by the specific piece of silicon it
passed through. Not the model, not the batch — the individual sensor. This
document is why that is true, why it survives being made into a JPEG, and how
`fingerprint/prnu.py` gets it back out.

The short version: a sensor's photosites do not all convert light at exactly
the same rate, the differences are permanent and effectively random, and they
multiply the scene rather than adding to it. That multiplicative pattern is
the fingerprint, and this project calls it K.

## Where the birthmark comes from

A sensor is cut from a silicon wafer. Doping concentration varies microscopic-
ally across the wafer, photosite areas differ by fractions of a percent after
etching, and the microlens over each well is not placed perfectly. The result
is that photosite *(i, j)* converts arriving photons into electrons slightly
more or slightly less efficiently than its neighbour — a fixed multiplicative
gain, typically within about a percent of unity.

This is **photo-response non-uniformity**, PRNU. Three properties make it
useful, and all three have to hold:

- **It is permanent.** It comes from the physical structure of the die, so it
  does not drift with temperature, age or firmware the way dark current does.
  A fingerprint enrolled today matches a frame shot years earlier.
- **It is effectively random.** Nothing in the manufacturing process makes
  two sensors share a pattern, including two dies cut adjacently from the same
  wafer. It is not a serial number that could be reissued; it is closer to a
  crystallisation pattern.
- **It is in every exposure.** Light has to land on the photosites to be
  measured, so the gain applies to every photograph the sensor has ever taken
  or will take. There is no capture mode that turns it off.

That last point is what makes the system possible at all. The fingerprint is
not metadata attached to a file, which can be stripped, and not a signature
added by firmware, which requires the manufacturer's cooperation. It is a
property of the measurement itself.

## The sensor model

[F09] eq. (3) writes an exposure as

```
I = I0 + I0*K + Theta
```

`I0` is the noise-free scene, `K` is the fingerprint, and `Theta` collects
everything else — shot noise, read noise, quantisation. The term that matters
is `I0*K`: the fingerprint is **multiplied** by the scene, not added to it.

Two consequences run through the whole design.

The first is that bright pixels carry more fingerprint than dark ones. Where
`I0` is near zero the product `I0*K` is near zero too, and the fingerprint is
simply not present to be measured. This is why enrolment wants bright,
smooth, unsaturated frames, and why `estimate_fingerprint` uses the maximum-
likelihood form rather than averaging residuals — a residual from a bright
frame is stronger evidence and gets weighted accordingly.

The second is that a saturated pixel carries none at all. A clipped photosite
is clamped to full scale rather than modulated by its gain, so it contributes
only noise. `SATURATION_LEVEL = 0.99` marks those pixels and
`SATURATION_WARN = 0.01` complains when more than one percent of an enrolment
frame is clipped.

## Getting it out of a photograph

The fingerprint is perhaps a percent of the signal, buried under a scene that
is a hundred times stronger. Recovery is two steps: suppress the scene, then
accumulate across frames.

**Step one, the residual.** Denoise the frame and subtract: `W = I - denoise(I)`.
What remains is noise plus fingerprint, with most of the scene removed. The
denoiser is the wavelet Wiener filter of [F09] Appendix A, using the Mihcak
local-variance estimator [M99] — `db8` at `WAVELET_LEVELS = 4`, with the
variance taken as the *minimum* over `WIENER_WINDOWS = (3, 5, 7, 9)`.

Taking the minimum is a deliberate bias. It makes the filter more willing to
call a coefficient noise than signal, which costs some scene leakage into the
residual and buys fingerprint that a more cautious filter would have thrown
away. The asymmetry is on purpose: leaked scene content can be suppressed
later, but fingerprint filtered away is gone for good. `SIGMA = 2.0/255.0`
overestimates the sensor noise for the same reason.

**Step two, the estimator.** One residual is mostly noise. The ML estimator,
[F09] eq. (6), is

```
K = sum(W * I) / sum(I^2)
```

weighting each frame by its own brightness, exactly as the multiplicative
model demands. The model is linear, so by the CRLB of eq. (7) this is
minimum-variance unbiased with variance falling as 1/frames. That is the
arithmetic behind the 40-frame enrolment requirement — not a rule of thumb,
a variance target.

## Why RAW, and why CFA planes

This pipeline splits the Bayer mosaic into its colour planes and never
demosaics. `load_raw_planes` refuses anything that is not a CFA mosaic for
that reason.

Demosaicing interpolates each output pixel from its neighbours. That mixes
adjacent photosites together, which blurs the per-photosite gains that *are*
the fingerprint, and it imprints the manufacturer's interpolation algorithm —
a pattern shared by every body of that model — on top. Splitting first means
each plane is a real image of one photosite type on a regular sublattice,
rather than an interpolation of four.

This is the choice that makes the R10 result strong and the choice that makes
phone output unusable; `docs/phones.md` is that argument.

## Separating identity from family resemblance

A raw K is not yet an identity. It contains, alongside this body's PRNU,
several patterns shared by every body of the model: CFA interpolation
artefacts, JPEG blocking, and row and column readout structure. Left in, two
different bodies of the same model would correlate through their shared
inheritance, and the system would confuse a family resemblance for a person.

`postprocess` removes them in two passes. `_zero_mean` subtracts per-column
then per-row means, since readout patterns are constant along a row or a
column and carry no individual identity. `_wiener_dft` then attenuates strong
periodic structure in the frequency domain, on the reasoning that anything
surviving as a spatially coherent frequency is almost certainly a design
artefact rather than this die's manufacturing noise.

The measured evidence that this works is the one negative that mattered: a
*different* Canon R10 — same model, same firmware, same CFA layout — scores
39.1 against this body's K, inside the null band. A Canon 5D Mark III scores
26.6. Genuine frames from the enrolled body score 1,895 to 56,255.

## Comparing a photograph to a fingerprint

Matching uses **Peak-to-Correlation-Energy**, [F09] eq. (14): take the
circular cross-correlation surface of the test residual against K, then
compare the peak against the energy in the rest of the surface, excluding an
11x11 neighbourhood around the peak.

PCE rather than plain correlation because it is shift-invariant — a crop no
longer has to be aligned by hand — and because its null distribution is stable
enough to set one threshold across bodies. The sign is kept rather than taking
an absolute value: a strong *negative* peak is not a match, and hiding that
would turn an obvious failure into a silent one.

The price of peaking over every shift is that **the null is not zero**. For
uncorrelated inputs PCE concentrates near `2*ln(N)` — about 22 on a 256x256
plane, about 31 on a full-size one — and searching all eight orientations
raises it further, since the null becomes the largest of eight tries. Observed
nulls on R10 planes run 24 to 43.

`PCE_THRESHOLD = 100.0` sits at roughly twice the worst null seen and well
under the weakest true match. It was 50 until a real second body existed,
which left only 1.1x of headroom over a null of 44. It still rests on **one**
other body: a defensible false-positive rate needs dozens, and until those
exist this is a floor with a margin, not a calibrated operating point.

## What weakens the birthmark

The fingerprint lives in high spatial frequencies, which is exactly what image
processing attacks:

| Operation | Effect |
| --- | --- |
| Saturation | Clipped pixels carry no fingerprint at all |
| Dim exposure | `I0*K` shrinks with `I0`; little to recover |
| Heavy JPEG | Quantises away the high-frequency detail; 1800px at q95 scores 408, the same size at q80 scores 37 |
| Resize / crop | Breaks pixel-to-photosite alignment; needs the scale and orientation search |
| Multi-frame fusion | Averages the fingerprint down and smears it across neighbours |
| Aggressive denoise | Removes the residual band directly |

A delivered JPEG at native resolution still scores 1,147.8, so ordinary
delivery does not destroy it. Sustained reprocessing does.

## K never leaves the machine

K identifies the body, and anyone holding it can claim to be that body. So it
stays local: only `commitment(K)` — a SHA-256 over a pinned canonical
serialisation, tagged `genesis-prnu-k-v1` — is published on chain as
`BodyRecord.fingerprintCommitment`.

The serialisation is a one-way door. Changing dtype, byte order or shape
changes the hash and silently invalidates every registration made under the
old one, which is why it is pinned and covered by a regression test.

What the commitment buys is the ability to prove later that K was not changed
after the fact. What it does not buy is any protection if K leaks — the hash
of a leaked secret is still a leaked secret. `docs/adversarial.md` is where
that scenario gets tested.

## What the birthmark does not prove

It places a photograph on a sensor. That is all it does.

A camera pointed at a high-quality screen produces a genuine exposure, with
this body's PRNU faithfully imprinted, of a scene that never existed. The
birthmark is intact and the photograph is a lie. No sensor-level method
reaches that problem, including in-camera cryptographic signing.

Origin, not truth. `docs/claims.md` holds the line on how that is worded.

## References

- **[F09]** J. Fridrich, "Digital Image Forensics Using Sensor Noise", IEEE
  Signal Processing Magazine 26(2), March 2009, 26-37. Sensor model eq. (3),
  ML estimator eq. (6), CRLB eq. (7), PCE eq. (14), denoiser in Appendix A.
- **[M99]** Mihcak, Kozintsev, Ramchandran, "Spatially Adaptive Statistical
  Modeling of Wavelet Image Coefficients and its Application to Denoising",
  IEEE ICASSP 1999.
- **[DDE]** Binghamton DDE Lab reference implementation,
  <https://dde.binghamton.edu/download/camera_fingerprint/>

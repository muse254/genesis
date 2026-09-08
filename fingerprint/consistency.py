"""Tier 1 consistency checks: evidence beside a PCE score, never a verdict.

`docs/adversarial.md` establishes that a PCE score alone means nothing --
anyone with one RAW file off the body can plant the fingerprint invisibly.
The owner's on-chain registration is the security boundary and nothing here
changes that. What these checks buy is *cost*: a forgery has to satisfy them
too, and satisfying them is more work than multiplying by ``1 + alpha * K``.

Two checks, both measured, both partial, and the limits are in the
docstrings rather than in a footnote. Neither gates a verdict. A caller that
turns either of these into a pass/fail has misread the module.
"""

from __future__ import annotations

import numpy as np

from fingerprint import prnu

#: Which CFA plane the checks run on. Green carries the result on this body --
#: plane 3 scored highest on all ten held-out frames in `docs/gates.md`,
#: typically 4-5x over red, because RGGB has twice the green photosites.
DEFAULT_PLANE = 3


def strip_fingerprint(planes, k, plane: int = DEFAULT_PLANE):
    """A frame's residual with the fingerprint it should carry projected out.

    Both a genuine frame and a forgery contain a term proportional to
    ``J*K``. That term is exactly what `prnu.score` measures, so it says
    nothing about which is which and has to come out before anything else is
    compared. Least squares, because the coefficient differs: a genuine
    exposure has whatever strength the silicon has, a forgery has whatever
    alpha the attacker chose.

    What remains is everything else the body puts into a frame that the
    published K does not hold -- readout structure, dark current, the lens,
    and the part of the PRNU `prnu.postprocess` deliberately removed.
    """
    image = np.asarray(planes[plane], dtype=np.float64)
    field = np.asarray(k[plane], dtype=np.float64)
    if image.shape != field.shape:
        raise ValueError(f"one lattice required: frame {image.shape}, K {field.shape}")

    residual = prnu.noise_residual(planes[plane]).astype(np.float64).ravel()
    expected = (image * field).ravel()

    energy = float(expected @ expected)
    if energy > 0:
        residual = residual - (float(residual @ expected) / energy) * expected
    return residual - residual.mean()


def _collinearity(a, b) -> float:
    denominator = np.sqrt(float(a @ a) * float(b @ b))
    return 0.0 if denominator <= 0 else float((a @ b) / denominator)


def reference_vectors(frames, k, plane: int = DEFAULT_PLANE):
    """Stripped residuals of known-good frames, to compare probes against.

    Built once at enrolment from frames the body definitely produced. These
    are not K and do not identify the body on their own, but they are derived
    from the enrolment set, so they are as private as it is.
    """
    return [strip_fingerprint(f if isinstance(f, dict) else prnu.load_raw_planes(f), k, plane)
            for f in frames]


def body_consistency(planes, k, references, plane: int = DEFAULT_PLANE) -> float:
    """Mean correlation between a probe's stripped residual and known-good ones.

    The question: beyond the published K, does this frame carry the rest of
    what this body puts into an image? A genuine frame does. A forgery given
    only ``alpha * J * K`` does not.

    **Measured, and it is partial.** Five R10 reference frames, 8 September
    2026::

        genuine IMG_0217            +0.055
        genuine game.jpg            +0.015
        genuine IMG_0230 (weakest)  +0.012
        forgery, 5D3 carrier        +0.0077
        forgery, synthetic carrier  +0.00052
        a different R10 body        +0.00040

    It separates the synthetic forgery decisively -- 23x below the weakest
    genuine frame. It does **not** separate the delivered-JPEG forgery: 0.0077
    against 0.012 is 1.6x, and on the per-reference maximum that forgery
    (+0.029) beats two genuine probes outright. The delivered path carries far
    less of the residual structure this keys on than a RAW does, and the
    delivered path is the one the product exists to serve.

    So: useful as evidence, useless as a gate, and n is three genuine probes
    against two forgeries. Report it; do not threshold it.
    """
    if not references:
        return 0.0
    v = strip_fingerprint(planes, k, plane)
    return float(np.mean([_collinearity(v, r) for r in references]))


def resampling_peak(image, side: int = 1024) -> float:
    """Periodicity in the second difference, as left by interpolation.

    An upsampled image is a linear combination of neighbours on a periodic
    lattice, which puts periodic structure in the second difference that a
    native capture has no reason to carry. Our attack-3 forgery was upsampled
    5760x3840 -> 6000x4000 to reach the aligned lattice, so it should show it.

    **Measured, and it is weak.** Peak-to-median of the windowed spectrum::

        genuine game.jpg          16.0
        genuine a-piece-of-quiet  25.8
        forgery, 5D3 upsampled    32.1
        forgery, same at alpha 1.5 33.2
        forgery, synthetic         7.4

    The upsampled forgeries do sit above both genuine files, but 25.8 against
    32.1 is not a threshold on n = 2, and the synthetic forgery scores
    *lowest* of everything because it was generated at native resolution and
    never resampled at all. This check only ever sees attackers who resized,
    and an attacker who generates at the sensor's native size is invisible to
    it. Kept because it costs nothing and it is one more thing to get right.
    """
    g = np.asarray(image, dtype=np.float64)
    if g.ndim == 3:
        g = g.mean(axis=2)
    h, w = g.shape
    side = min(side, h, w)
    g = g[(h - side) // 2 : (h - side) // 2 + side, (w - side) // 2 : (w - side) // 2 + side]

    magnitude = np.abs(np.diff(g, n=2, axis=1)).mean(axis=0)
    magnitude = magnitude - magnitude.mean()
    spectrum = np.abs(np.fft.rfft(magnitude * np.hanning(magnitude.size)))
    spectrum[:4] = 0.0  # DC and the lowest bins carry scene, not lattice
    median = float(np.median(spectrum))
    return 0.0 if median <= 0 else float(spectrum.max() / median)

def effective_strength(planes, k, plane: int = DEFAULT_PLANE) -> float:
    """How strongly the fingerprint is present, as a least-squares coefficient.

    ``alpha_hat = <W, J*K> / ||J*K||^2``. A genuine exposure carries whatever
    strength the silicon has; a forgery carries whatever alpha the attacker
    chose. So a forgery tuned only to clear the threshold sits outside the
    range genuine frames occupy.

    **The range is per processing path and the two differ by a hundredfold**,
    measured 8 September 2026::

        RAW / CFA        genuine 0.97 - 3.64 (n=8)   forgeries 0.029 - 0.469
        delivered JPEG   genuine 0.0109 - 0.0218 (n=2)  forgeries 0.065 - 0.653

    Forgeries fall *below* on RAW, because an attacker plants the least that
    clears the threshold, and *above* on delivered, because 8-bit
    quantisation swallows anything under about alpha 0.3, so clearing PCE at
    all costs more energy than a real attenuated fingerprint carries.

    **Evadable, and cheaply.** At alpha 0.35 a delivered forgery scores 1,515
    and returns 0.0166 -- inside the genuine band. Finding that took a
    six-value sweep. This narrows an attacker's usable alpha from a floor to a
    window; it does not close it. And the delivered band above rests on two
    images, which is not a band. Report it, calibrate it per path, and do not
    decide on it.
    """
    image = np.asarray(planes[plane], dtype=np.float64)
    field = np.asarray(k[plane], dtype=np.float64)
    if image.shape != field.shape:
        raise ValueError(f"one lattice required: frame {image.shape}, K {field.shape}")

    residual = prnu.noise_residual(planes[plane]).astype(np.float64).ravel()
    expected = (image * field).ravel()
    energy = float(expected @ expected)
    return 0.0 if energy <= 0 else float(residual @ expected) / energy


def pooled_triangle(d_values) -> float:
    """[B18]'s sign-aware pooled statistic over per-candidate triangle scores.

    ``V = sum(sign(d_i) * d_i^2) / sqrt(3 * n)``.

    [G11] decides per candidate frame, and that does not work: measured on a
    synthetic corpus where the ground truth is known, a forgery's per-frame d
    against the frames it was built from has mean +1.08 and maximum +2.04,
    while a genuine held-out frame reaches +2.18. The means separate; the
    maxima cross. Pooling is the answer [B18] gives, and the sign is the
    improvement -- a forgery should show *excess* correlation with the stolen
    set, so positive deviations are evidence and negative ones are not.

    ``mu`` and ``sigma`` are the suspect's **own** mean and spread across
    candidates -- they carry a ``J`` subscript in [B18] eq. (12) and are not
    the calibration's. That makes ``V`` scale-free and centred: it asks
    whether this suspect's ``d`` distribution is skewed positive, which is
    what a subset of stolen frames does to it. Normalising against the
    calibration instead gives values in the hundreds and ranks a forgery above
    a genuine frame in 3 runs out of 8 -- worse than chance, measured.

    Only meaningful when the calibration it came from is sound. Check the
    Pearson coefficient from :func:`fingerprint.attacks.calibrate_triangle`
    first -- on this repo's own corpus it is negative, and every ``d`` built on
    it is noise (`docs/adversarial.md`).
    """
    d = np.asarray(list(d_values), dtype=np.float64)
    if d.size < 2:
        return 0.0
    spread = float(d.std())
    if spread <= 0:
        return 0.0
    centred = (d - d.mean()) / spread
    return float(np.sum(np.sign(centred) * centred**2) / np.sqrt(3.0 * d.size))

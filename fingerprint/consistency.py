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

    Re-measured on ten genuine frames per path, references held out from the
    genuine set, against forgeries that clear PCE::

        RAW        genuine -0.0018 - 0.0116   forged 0.0004 - 0.0006   AUC 0.900
        delivered  genuine -0.0007 - 0.0086   forged 0.0002 - 0.0077   AUC 0.725

    The strongest signal here and still overlapping on both paths: a genuine
    RAW frame reaches -0.0018, below every forgery. On the delivered path --
    the one the product exists to serve -- it falls to 0.725, which is barely
    a signal at all.

    Report it, do not threshold it, and do not call it detection.
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

    **Measured on ten genuine images per path, it is chance.** AUC **0.517**,
    genuine 15.5-96.8 against forged 15.3-33.1 (8 September 2026). An earlier
    reading of two genuine files put them at 16.0 and 25.8 against forgeries
    at 32-33 and looked promising; ten genuine files reach 96.8, which
    swallows the forgeries whole.

    Scene content drives this far harder than resampling does. Retained only
    because it is nearly free, and because a *specific* claim -- this file says
    it is a native capture and its spectrum says it was upsampled -- may still
    be worth making about one suspect image. As a population discriminator it
    is worth nothing and nothing should read it as one.
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

    **Measured properly it barely separates.** An earlier reading quoted a
    genuine RAW band of 0.97-3.64 from eight frames and a delivered band of
    0.0109-0.0218 from *two*. Both were artefacts of the sample. Ten genuine
    frames per path, against forgeries that clear PCE, 8 September 2026::

        RAW        genuine 0.0326 - 3.6250   forged 0.0293 - 1.0883   AUC 0.800
        delivered  genuine 0.0011 - 0.6674   forged 0.0086 - 0.6530   AUC 0.767

    The ranges **overlap on both paths**. One real frame sits at 0.033, inside
    the forgery range, so there is no threshold that separates them -- and the
    alpha 0.35 evasion found earlier was almost beside the point, since most
    forgeries land in the genuine band without aiming for it.

    AUC 0.8 is a weak signal, not a test. Report it; never decide on it.
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


#: What each advisory signal was measured to be worth, so a caller reporting
#: one is obliged to report how weak it is. Separability of forgeries that
#: clear PCE from genuine frames, ten of each per path, 8 September 2026.
#: Every one of these ranges overlaps; none is a test.
MEASURED_AUC = {
    "bodyConsistency": {"raw": 0.900, "delivered": 0.725},
    "effectiveStrength": {"raw": 0.800, "delivered": 0.767},
    "resamplingPeak": {"raw": None, "delivered": 0.517},
}


def stages(*, matched: bool, registered: bool, signals: dict, path: str = "delivered") -> list:
    """The verification pipeline, as an ordered, reportable list.

    Staggered on purpose. One number that folds pixels and chain together
    would let a weak signal quietly raise a verdict, and today's measurements
    say every signal here is weak: the best is AUC 0.900 on RAW and it falls
    to 0.725 on the delivered path, with overlapping ranges throughout.

    So the rule this encodes is one-directional. **Stages 1 and 2 can add
    doubt and can never grant a claim.** Only stage 3, a chain read, produces
    `registered`. A caller that lets a signal upgrade a verdict has
    reintroduced exactly the hole `verify/src/main.ts` had before `acf3f87`.

    Returns one entry per stage: what it asked, what it found, and -- for the
    advisory stage -- what it is measured to be worth, so the number never
    travels without its own error bar.
    """
    advisory = [
        {
            "signal": name,
            "value": signals.get(name),
            "auc": MEASURED_AUC.get(name, {}).get(path),
        }
        for name in ("bodyConsistency", "effectiveStrength", "resamplingPeak")
        if signals.get(name) is not None
    ]

    return [
        {
            "stage": 1,
            "name": "pixel match",
            "asks": "do these pixels carry this body's fingerprint?",
            "result": "match" if matched else "no match",
            "decides": "whether to look further. A match alone claims nothing.",
        },
        {
            "stage": 2,
            "name": "consistency",
            "asks": "does anything about this image contradict a genuine capture?",
            "result": advisory or None,
            "decides": (
                "nothing. Advisory only -- every signal here overlaps between "
                "genuine frames and forgeries, best AUC 0.900 on RAW and 0.725 "
                "on delivered. It may add doubt; it may never add confidence."
            ),
        },
        {
            "stage": 3,
            "name": "registration",
            "asks": "did this body's owner register this image on chain?",
            "result": "registered" if registered else "no registration",
            "decides": "the verdict. This is the only stage that grants a claim.",
        },
    ]


#: Samples per class needed before a likelihood ratio is worth quoting. Not a
#: derived figure -- a floor. Today's corpus has ten per class per path, and
#: ten is how the bands in this module came to be overstated by three hundred
#: times before they were re-measured. `docs/gates.md` applies the same rule to
#: the false-positive rate: "one body is not a false-positive rate".
LR_MIN_SAMPLES = 50


def likelihood_ratio(value: float, genuine: list, forged: list) -> dict:
    """How much more likely this reading is under 'genuine' than under 'forged'.

    Forensic feature-comparison disciplines moved from match/no-match to
    likelihood ratios precisely because the distributions overlap, which is
    our situation on every signal here. A ratio is honest where a verdict is
    not: it says how far the evidence moves you, rather than pretending it
    settles anything.

    PCAST's 2016 report on feature-comparison methods is the standard this
    aims at -- error rates established by designed studies, and empirical
    validation as the thing nothing can substitute for. We do not meet it.
    Ten samples per class is what produced the overstated bands corrected
    above, so this **refuses to quote a ratio** below `LR_MIN_SAMPLES` and
    returns what it would need instead.

    The estimate, when there is enough data, is deliberately crude: the
    fraction of each class at least as extreme as the observed value, Laplace
    smoothed. A kernel density estimate would look more precise and would not
    be more true at these sample sizes.

    Returns
    -------
    dict
        ``sufficient`` says whether the number may be used at all. When it is
        ``False`` there is no ``ratio`` key -- a caller cannot accidentally
        read one.
    """
    genuine, forged = list(genuine), list(forged)
    have = min(len(genuine), len(forged))
    if have < LR_MIN_SAMPLES:
        return {
            "sufficient": False,
            "have": have,
            "need": LR_MIN_SAMPLES,
            "why": (
                "too few samples per class to quote a likelihood ratio. The "
                "bands in this module were overstated by up to 300x at this "
                "sample size before they were re-measured."
            ),
        }

    lower = min(len(genuine), len(forged))  # symmetric two-tailed extremity
    g = (sum(1 for x in genuine if abs(x) >= abs(value)) + 1) / (len(genuine) + 2)
    f = (sum(1 for x in forged if abs(x) >= abs(value)) + 1) / (len(forged) + 2)
    return {
        "sufficient": True,
        "ratio": g / f,
        "samples": {"genuine": len(genuine), "forged": len(forged)},
        "reading": "ratios near 1 mean the evidence distinguishes nothing",
        "floor": lower,
    }


#: Below this, a frame has too little high-frequency detail for PRNU to be
#: measured in it. Not a tuned threshold -- an order-of-magnitude marker.
#: Files that verify sit at 1,000-4,000 (`game.jpg` median 2,161); a
#: motion-blurred frame from the *same enrolled body* measured 7.7 median with
#: no tile above 92.5, and scored 44.9, inside the null band.
DETAIL_FLOOR = 200.0


def high_frequency_content(image) -> float:
    """Median Laplacian variance over a grid of tiles.

    PRNU lives in high spatial frequencies, so an image that has none carries
    no measurable fingerprint however genuine it is. That is a different fact
    from "this is not your camera", and a verifier that cannot tell them apart
    will tell a photographer their own photograph is unrecognised.

    Measured on a real failure: `gloria-dreamy.JPG`, EXIF serial matching the
    enrolled body exactly, 1/60s at 300mm on a superzoom -- globally soft.
    Median tile 7.7 against 2,161 for a frame that verifies, sharpest tile
    92.5 against that same 2,161, and **not one tile of thirty-six** above
    500. It scored 44.9.

    Tiled and taken as a median rather than measured once over the frame,
    because shallow depth of field is not blur: a portrait with a sharp face
    and soft background should pass, and a single centre crop would call it
    soft. Only a frame that is soft *everywhere* has nothing to correlate.
    """
    import numpy as np
    from scipy import ndimage

    grid, size = 6, 600
    grey = np.asarray(image.convert("L") if hasattr(image, "convert") else image, dtype=np.float64)
    if grey.ndim == 3:
        grey = grey.mean(axis=2)

    height, width = grey.shape
    size = min(size, height, width)
    values = []
    for i in range(grid):
        for j in range(grid):
            y = int((height - size) * i / max(grid - 1, 1))
            x = int((width - size) * j / max(grid - 1, 1))
            values.append(ndimage.laplace(grey[y : y + size, x : x + size]).var())
    return float(np.median(values))

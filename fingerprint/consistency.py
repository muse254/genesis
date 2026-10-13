"""Tier 1 consistency checks: evidence beside a PCE score, never a verdict.

A PCE score alone can be forged (`docs/adversarial.md`); on-chain
registration is the security boundary. These checks only raise a forger's
cost. None of them may gate a verdict.
"""

from __future__ import annotations

import numpy as np

from fingerprint import prnu

#: CFA plane the checks run on: green plane 3 scored highest on all ten held-out
#: frames (`docs/gates.md`), typically 4-5x over red.
DEFAULT_PLANE = 3


def strip_fingerprint(planes, k, plane: int = DEFAULT_PLANE):
    """A frame's residual with the ``J*K`` term projected out by least squares.

    What remains (readout structure, dark current, lens, unfiltered PRNU) is
    what a genuine frame has and a forgery lacks.
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
    """Stripped residuals of known-good frames. As private as the enrolment set."""
    return [strip_fingerprint(f if isinstance(f, dict) else prnu.load_raw_planes(f), k, plane)
            for f in frames]


def body_consistency(planes, k, references, plane: int = DEFAULT_PLANE) -> float:
    """Mean correlation between a probe's stripped residual and known-good ones.

    Ten genuine frames per path vs forgeries that clear PCE::

        RAW        genuine -0.0018 - 0.0116   forged 0.0004 - 0.0006   AUC 0.900
        delivered  genuine -0.0007 - 0.0086   forged 0.0002 - 0.0077   AUC 0.725

    Ranges overlap. Report it, do not threshold it, do not call it detection.
    """
    if not references:
        return 0.0
    v = strip_fingerprint(planes, k, plane)
    return float(np.mean([_collinearity(v, r) for r in references]))


def resampling_peak(image, side: int = 1024) -> float:
    """Periodicity in the second difference, as left by interpolation.

    **Measured, it is chance**: AUC 0.517, genuine 15.5-96.8 vs forged
    15.3-33.1; scene content dominates. Kept only because it is nearly free.
    Never read it as a discriminator.
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

    ``alpha_hat = <W, J*K> / ||J*K||^2``. Ten genuine frames per path vs
    forgeries that clear PCE::

        RAW        genuine 0.0326 - 3.6250   forged 0.0293 - 1.0883   AUC 0.800
        delivered  genuine 0.0011 - 0.6674   forged 0.0086 - 0.6530   AUC 0.767

    Ranges overlap on both paths. Report it; never decide on it.
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

    Pooled because per-frame maxima cross between forged and genuine. Centred
    on the suspect's **own** mean and spread ([B18] eq. (12)), not the
    calibration's, which measured worse than chance. Meaningless unless the
    :func:`fingerprint.attacks.calibrate_triangle` Pearson is sound; on this
    repo's corpus it is negative (`docs/adversarial.md`).
    """
    d = np.asarray(list(d_values), dtype=np.float64)
    if d.size < 2:
        return 0.0
    spread = float(d.std())
    if spread <= 0:
        return 0.0
    centred = (d - d.mean()) / spread
    return float(np.sum(np.sign(centred) * centred**2) / np.sqrt(3.0 * d.size))


#: Measured AUC of each advisory signal (ten genuine vs ten forged per path),
#: reported alongside it. Every range overlaps; none is a test.
MEASURED_AUC = {
    "bodyConsistency": {"raw": 0.900, "delivered": 0.725},
    "effectiveStrength": {"raw": 0.800, "delivered": 0.767},
    "resamplingPeak": {"raw": None, "delivered": 0.517},
}


def stages(*, matched: bool, registered: bool, signals: dict, path: str = "delivered") -> list:
    """The verification pipeline, as an ordered, reportable list.

    **Stages 1 and 2 can add doubt and can never grant a claim.** Only stage
    3, a chain read, produces `registered`. Never let a signal upgrade a verdict.
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


#: Samples per class before a likelihood ratio may be quoted. A floor, not
#: derived: at ten per class the bands here were once overstated up to 300x.
LR_MIN_SAMPLES = 50


def likelihood_ratio(value: float, genuine: list, forged: list) -> dict:
    """How much more likely this reading is under 'genuine' than under 'forged'.

    **Refuses to quote a ratio** below `LR_MIN_SAMPLES`. Deliberately crude:
    Laplace-smoothed fraction of each class at least as extreme as ``value``.

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


#: Below this a frame has too little detail for PRNU. Order-of-magnitude marker:
#: verifying files sit at 1,000-4,000; a blurred frame from the enrolled body
#: measured 7.7 and scored PCE 44.9, inside the null.
DETAIL_FLOOR = 200.0


def high_frequency_content(image) -> float:
    """Median Laplacian variance over a grid of tiles.

    Tells "too soft to measure" apart from "not your camera". Tiled median so
    shallow depth of field passes; only soft-everywhere frames fail.
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

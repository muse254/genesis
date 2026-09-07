"""Synthetic-sensor validation harness -- the regression suite, not a demo.

Simulates a sensor with a known ground-truth PRNU, runs the full extraction
pipeline, and asserts the recovered fingerprint correlates with truth and
that same-body PCE separates from other-body PCE by orders of magnitude.

These are SYNTHETIC UPPER BOUNDS. The simulation has a perfectly stable
fingerprint, no lens vignetting, no dark current and no demosaic. Real
figures will be far lower, and the moment real ones exist they replace
these everywhere -- here, in the README, and in the pitch (BUILD.md sec.15).
"""

from __future__ import annotations

import numpy as np

from fingerprint import prnu

# --- simulation parameters -------------------------------------------------

#: Multiplicative PRNU strength. Real sensors sit around 1-3%.
PRNU_STRENGTH = 0.02
#: Read/shot noise standard deviation, in the same [0, 1] scale as a plane.
NOISE_SIGMA = 0.01
#: Frames per enrolment. Gate A asks for 40-50 on a real body; the synthetic
#: sensor is stationary, so fewer suffice to prove the estimator works.
FRAMES = 24
SHAPE = (256, 256)

# --- acceptance floors -----------------------------------------------------
# Deliberately well below what the simulation actually achieves. These are a
# regression alarm, not a score to report. Anything measured on real frames
# replaces them (BUILD.md sec.9).

MIN_TRUTH_CORRELATION = 0.35
MIN_MATCH_PCE = prnu.PCE_THRESHOLD
#: Not near zero: PCE peaks over all shifts, so the null sits near 2*ln(N),
#: about 22 for these 256x256 planes. See :func:`prnu.pce`.
MAX_MISMATCH_PCE = 40.0
MIN_SEPARATION = 10.0


def simulate_sensor(shape=SHAPE, seed: int = 0):
    """Generate a ground-truth multiplicative PRNU field for a fake body."""
    rng = np.random.default_rng(seed)
    k = rng.normal(0.0, PRNU_STRENGTH, size=shape).astype(np.float32)
    return k - k.mean()


def simulate_exposure(sensor_prnu, scene=None, seed: int = 0):
    """Render one exposure through a simulated sensor: I = I0 * (1 + K) + noise."""
    rng = np.random.default_rng(seed)
    shape = sensor_prnu.shape

    if scene is None:
        # A defocused flat: mid-grey with a gentle gradient, which is what a
        # Gate A enrolment frame is meant to look like.
        y = np.linspace(0.45, 0.55, shape[0], dtype=np.float32)[:, None]
        x = np.linspace(0.98, 1.02, shape[1], dtype=np.float32)[None, :]
        scene = y * x

    noise = rng.normal(0.0, NOISE_SIGMA, size=shape).astype(np.float32)
    return np.clip(scene * (1.0 + sensor_prnu) + noise, 0.0, 1.0).astype(np.float32)


def enrol(sensor_prnu, frames: int = FRAMES, seed: int = 0):
    """Run Flow A end to end against a simulated body."""
    exposures = [simulate_exposure(sensor_prnu, seed=seed + n) for n in range(frames)]
    return prnu.postprocess(prnu.estimate_fingerprint(exposures))


def correlation(a, b) -> float:
    """Normalised correlation coefficient between two fields."""
    a = np.asarray(a, dtype=np.float64).ravel()
    b = np.asarray(b, dtype=np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    denom = np.linalg.norm(a) * np.linalg.norm(b)
    return float(a @ b / denom) if denom else 0.0


def score(image, k) -> float:
    """PCE of one image against a fingerprint.

    The reference is ``image * K``, not K alone: PRNU is multiplicative, so
    the fingerprint only appears in a test frame scaled by that frame's own
    intensity.
    """
    return prnu.pce(prnu.noise_residual(image), np.asarray(image, dtype=np.float32) * k)


def test_fingerprint_recovery():
    """Recovered K correlates with ground truth above the accepted floor."""
    truth = simulate_sensor(seed=1)
    k = enrol(truth, seed=100)

    got = correlation(k, truth)
    assert got >= MIN_TRUTH_CORRELATION, f"K correlates {got:.3f} with truth"


def test_body_separation():
    """Same-body PCE exceeds other-body PCE by at least an order of magnitude."""
    body_a = simulate_sensor(seed=1)
    body_b = simulate_sensor(seed=2)
    k_a = enrol(body_a, seed=100)

    # Held-out frames: none of these was used to build K.
    match = score(simulate_exposure(body_a, seed=900), k_a)
    others = [score(simulate_exposure(body_b, seed=900 + n), k_a) for n in range(1, 6)]
    worst = max(abs(x) for x in others)

    assert match >= MIN_MATCH_PCE, f"same-body PCE {match:.1f}"
    assert worst <= MAX_MISMATCH_PCE, f"other-body PCE reached {worst:.1f}"
    assert match / max(worst, 1.0) >= MIN_SEPARATION, (
        f"separation {match:.1f} vs {worst:.1f} is under {MIN_SEPARATION}x"
    )


def test_commitment_is_pinned():
    """K's serialisation cannot drift without invalidating prior registrations.

    A body registered today must still hash the same way tomorrow, so this
    fixes the commitment of a known array rather than trusting the code to
    stay put (BUILD.md sec.5).
    """
    k = np.arange(12, dtype=np.float32).reshape(3, 4) / 100.0

    expected = "efccc13a457ce758eb92e80486df987eddca917d05d53512eddaf94f2ad96446"
    assert prnu.commitment(k).hex() == expected
    assert prnu.commitment({0: k}) == prnu.commitment(k)


def test_cfa_split_is_per_photosite():
    """Each CFA plane is one photosite type, black-corrected on its own level.

    Exercises the split without a RAW file: RGGB mosaic, a different constant
    per colour, a different black level per channel. If the sublattice
    indexing or the per-channel subtraction is wrong, the planes come back
    mixed and every fingerprint built on them is quietly wrong.
    """
    values = {0: 1000.0, 1: 2000.0, 2: 3000.0, 3: 4000.0}
    colors = np.tile(np.array([[0, 1], [3, 2]]), (4, 4))
    image = np.vectorize(values.get)(colors).astype(np.float32)
    black = [100.0, 200.0, 300.0, 400.0]
    white = 4400.0

    planes = prnu.split_cfa(image, colors, black, white)

    assert sorted(planes) == [0, 1, 2, 3]
    for c, plane in planes.items():
        assert plane.shape == (4, 4)
        expected = (values[c] - black[c]) / (white - black[c])
        assert np.allclose(plane, expected), f"plane {c} is not one photosite type"

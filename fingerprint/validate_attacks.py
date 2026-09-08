"""Adversarial validation harness -- the forgeries, kept from rotting.

`validate_synthetic.py` asserts that the estimator recognises the right
body. This file asserts the other half of the same fact: that anyone holding
K can manufacture something it recognises. Both are properties of the same
estimator and the repo should fail loudly if either stops being true --
if the forgery ever stops working, either the estimator changed or these
tests did, and both are worth a red light.

Synthetic throughout, for the same reason `data/references/` and
`fingerprint/raw-test-files/` are gitignored: a test that needed a real
fingerprint could not run anywhere but the owner's laptop, and one that
shipped one would be publishing the forgery kit. The measured numbers
against the real R10 are in `docs/adversarial.md`.
"""

from __future__ import annotations

import numpy as np

from fingerprint import attacks, prnu
from fingerprint import validate_synthetic as sim

#: Injection strength used where a test only needs "a forgery that works".
#: Comfortably above the minimum on the synthetic sensor, comfortably below
#: anything visible.
ALPHA = 1.5
#: The 2x2 CFA layout of the R10, and of most Bayer bodies. Hard-coded here
#: rather than read from an enrolment, because these tests never open one.
PATTERN = [[0, 1], [3, 2]]


def _leaked_fingerprint(seed: int = 1, frames: int = sim.FRAMES):
    """Enrol a synthetic body, then hand K to the attacker."""
    body = sim.simulate_sensor(seed=seed)
    return body, sim.enrol(body, frames=frames, seed=100)


def test_a_leaked_fingerprint_manufactures_a_match():
    """The headline. A frame from body B, plus K from body A, scores as A."""
    _, k = _leaked_fingerprint(seed=1)
    other = sim.simulate_sensor(seed=2)
    carrier = sim.simulate_exposure(other, seed=900)

    honest = prnu.score({0: carrier}, {0: k})
    assert honest < prnu.PCE_THRESHOLD, f"carrier already matches at {honest}"

    forged = attacks.inject_planes({0: carrier}, {0: k}, ALPHA, levels=None)
    forgery = prnu.score(forged, {0: k})
    assert forgery >= prnu.PCE_THRESHOLD, f"forgery only reached PCE {forgery}"
    assert forgery > 10 * abs(honest)


def test_the_forgery_scores_higher_than_a_real_photograph():
    """The asymmetry that makes the forgery detectable, asserted as a fact.

    K is an average over many frames with the noise already divided out; a
    genuine single exposure carries the same K buried in one frame's worth of
    shot noise. So at the strength a real sensor imprints, the forgery wins.
    Measured on the R10 this runs to two orders of magnitude
    (`docs/adversarial.md`); here it only has to be true.
    """
    body, k = _leaked_fingerprint(seed=1)
    genuine = prnu.score({0: sim.simulate_exposure(body, seed=900)}, {0: k})

    other = sim.simulate_exposure(sim.simulate_sensor(seed=2), seed=900)
    at_natural_strength = attacks.inject_planes(
        {0: other}, {0: k}, sim.PRNU_STRENGTH / float(np.std(k)), levels=None
    )
    forgery = prnu.score(at_natural_strength, {0: k})
    assert forgery > genuine


def test_quantisation_puts_a_floor_under_the_attack():
    """Below half a quantisation step the plant rounds away entirely.

    The floor that decides the minimum alpha in `docs/adversarial.md` is this
    one, not the threshold: on a dim carrier it is what stops the attacker
    going arbitrarily quiet, and it rises as the carrier darkens.
    """
    _, k = _leaked_fingerprint(seed=1)
    carrier = 0.05 * np.ones((256, 256), dtype=np.float32)

    coarse = attacks.inject_planes({0: carrier}, {0: k}, 0.01, levels=255)
    assert np.array_equal(coarse[0], np.round(carrier * 255) / 255)

    fine = attacks.inject_planes({0: carrier}, {0: k}, 0.01, levels=None)
    assert not np.allclose(fine[0], carrier)


def test_minimum_alpha_brackets_the_threshold():
    _, k = _leaked_fingerprint(seed=1)
    carrier = sim.simulate_exposure(sim.simulate_sensor(seed=2), seed=900)

    def evaluate(a):
        return prnu.score(attacks.inject_planes({0: carrier}, {0: k}, a, levels=None), {0: k})

    alpha, value = attacks.minimum_alpha(evaluate, high=8.0)
    assert np.isfinite(alpha)
    assert value >= prnu.PCE_THRESHOLD
    assert evaluate(alpha * 0.5) < prnu.PCE_THRESHOLD


def test_a_carrier_that_was_never_a_photograph_still_matches():
    """The complete form of the claim's failure: no exposure took place."""
    _, k = _leaked_fingerprint(seed=1)
    planes = {c: k for c in (0, 1, 2, 3)}

    carrier = attacks.synthetic_carrier(shape=(512, 512), seed=7)
    assert carrier.shape == (512, 512, 3)

    forged = attacks.inject_delivered(carrier, planes, PATTERN, ALPHA)
    assert forged.dtype == np.uint8

    # Split the forged raster back onto the photosite lattice exactly as
    # prnu.load_delivered_planes would, and score it.
    pattern = np.asarray(PATTERN)
    channels = {0: 0, 1: 1, 2: 2, 3: 1}
    recovered = {}
    for c in np.unique(pattern):
        i, j = np.argwhere(pattern == c)[0]
        recovered[int(c)] = np.ascontiguousarray(
            forged[i::2, j::2, channels[int(c)]].astype(np.float32) / 255.0
        )
    assert prnu.score(recovered, planes) >= prnu.PCE_THRESHOLD


def test_mosaic_field_puts_every_plane_back_where_it_came_from():
    """The inverse of the delivered split, asserted plane by plane."""
    k = {c: np.full((16, 24), float(c + 1), dtype=np.float32) for c in range(4)}
    field = attacks.mosaic_field(k, PATTERN, (32, 48))

    pattern = np.asarray(PATTERN)
    for c in range(4):
        i, j = np.argwhere(pattern == c)[0]
        assert np.array_equal(field[i::2, j::2], k[c])


def test_the_forgery_costs_almost_nothing_to_look_at():
    _, k = _leaked_fingerprint(seed=1)
    planes = {c: k for c in (0, 1, 2, 3)}
    carrier = attacks.synthetic_carrier(shape=(512, 512), seed=7)
    forged = attacks.inject_delivered(carrier, planes, PATTERN, ALPHA)

    reference = np.clip(np.round(carrier), 0, 255).astype(np.uint8)
    assert attacks.psnr(forged, reference) > 40.0
    assert attacks.ssim(forged, reference) > 0.99


def test_psnr_and_ssim_are_exact_on_an_unchanged_image():
    image = attacks.synthetic_carrier(shape=(128, 128), seed=3)
    assert attacks.psnr(image, image) == float("inf")
    assert abs(attacks.ssim(image, image) - 1.0) < 1e-9


def test_a_downsampled_leak_is_still_a_leak():
    """How much of K the attacker actually needs.

    A K that leaked through something that halved its resolution still
    forges. That matters for the disclosure rule: "do not publish K" is not
    the same instruction as "do not publish anything derived from K".
    """
    _, k = _leaked_fingerprint(seed=1)
    carrier = sim.simulate_exposure(sim.simulate_sensor(seed=2), seed=900)

    weakened = attacks.degrade({0: k}, downsample=2)
    assert weakened[0].shape == k.shape

    forged = attacks.inject_planes({0: carrier}, weakened, 4 * ALPHA, levels=None)
    assert prnu.score(forged, {0: k}) >= prnu.PCE_THRESHOLD


def test_degrade_weakens_without_reshaping():
    _, k = _leaked_fingerprint(seed=1)
    for kwargs in ({"downsample": 4}, {"crop": 0.5}, {"bits": 2}):
        weakened = attacks.degrade({0: k}, **kwargs)[0]
        assert weakened.shape == k.shape
        assert not np.array_equal(weakened, k)


def test_a_forgery_shares_nothing_with_the_body_beyond_the_published_k():
    """The defence, in the one form that survived measurement.

    A forgery carries exactly ``alpha * J * K`` and nothing else of the body,
    so projecting that direction out of its residual empties it. A genuine
    frame carries the body's real response, of which the published K is only
    a filtered part, so something is always left over -- and that leftover is
    shared with every other genuine frame from the same body.

    `docs/adversarial.md` measures the separation on the real R10: 0.0002 for
    a forgery against 0.017 to 0.080 for genuine frames.
    """
    body, k = _leaked_fingerprint(seed=1)
    kd = {0: k}

    genuine_a = {0: sim.simulate_exposure(body, seed=900)}
    genuine_b = {0: sim.simulate_exposure(body, seed=901)}
    carrier = sim.simulate_exposure(sim.simulate_sensor(seed=2), seed=902)
    forged = attacks.inject_planes({0: carrier}, kd, ALPHA, levels=None)

    reference = attacks.strip_fingerprint(genuine_b, kd, plane=0)
    genuine_rho = attacks.collinearity(
        attacks.strip_fingerprint(genuine_a, kd, plane=0), reference
    )
    forgery_rho = attacks.collinearity(attacks.strip_fingerprint(forged, kd, plane=0), reference)

    assert genuine_rho > 10 * abs(forgery_rho)


def test_a_one_bit_leak_is_still_a_leak():
    """Only the sign of K, and the forgery still clears the threshold.

    Measured on the real R10: a sign-only K scores 4,886 where the full K
    scores 8,886 (`docs/adversarial.md`). It matters because "K leaked" and
    "one bit per photosite of K leaked" are the same disclosure, and any
    handling rule that treats a lossy or coarse copy as harmless is wrong.
    """
    _, k = _leaked_fingerprint(seed=1)
    carrier = sim.simulate_exposure(sim.simulate_sensor(seed=2), seed=900)

    one_bit = attacks.degrade({0: k}, bits=1)[0]
    assert set(np.unique(one_bit)).__len__() == 2, "a one-bit K should take two values"

    forged = attacks.inject_planes({0: carrier}, {0: one_bit}, ALPHA, levels=None)
    assert prnu.score(forged, {0: k}) >= prnu.PCE_THRESHOLD


def test_the_triangle_prediction_reports_its_own_calibration():
    """`calibrate_triangle` must hand back the Pearson coefficient.

    On this repo's own corpus the [G11] prediction does not track the
    observation at all (Pearson -0.38), and a caller that could not see that
    would read meaningless d values as evidence. The number is part of the
    return type so it cannot be skipped.
    """
    body, k = _leaked_fingerprint(seed=1)
    kd = {0: k}
    planes = [sim.simulate_exposure(body, seed=800 + n) for n in range(5)]
    frames = attacks.triangle_frames(planes, kd, plane=0)

    innocent = [
        (frames[i], frames[j])
        for i in range(len(frames))
        for j in range(i + 1, len(frames))
    ]
    calibration = attacks.calibrate_triangle(innocent)
    slope, intercept, spread, pearson = calibration
    assert spread > 0
    assert -1.0 <= pearson <= 1.0
    assert np.isfinite(attacks.triangle_d(frames[0], frames[1], calibration))
    assert np.isfinite(slope) and np.isfinite(intercept)

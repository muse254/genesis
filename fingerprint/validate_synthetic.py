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
from PIL import Image

from fingerprint import prnu

# --- simulation parameters -------------------------------------------------

#: Multiplicative PRNU strength -- the K of the sensor model
#: ``I = I0 + I0*K + Theta`` (Fridrich 2009, eq. 3; see fingerprint/prnu.py
#: for the full citation). Published RMS figures are lower than this: CMOS
#: parts are commonly specified under 1%, and a measured large-format
#: scientific CMOS came in at 1.1% raw. 2% is therefore a deliberately
#: generous simulation, not a claim about any real body -- what it tests is
#: that the estimator recovers whatever K it is handed. The number that
#: matters for this project is measured, not simulated (docs/gates.md).
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


def _four_plane_body(seed: int):
    """A simulated body as four independent CFA planes."""
    return {c: simulate_sensor(seed=seed + c) for c in range(4)}


def _four_plane_exposure(body, seed: int):
    return {c: simulate_exposure(k, seed=seed + c) for c, k in body.items()}


def test_score_beats_the_best_single_plane():
    """Summing correlation surfaces across CFA planes adds signal coherently.

    A true match peaks at the same shift in every plane while the noise does
    not, so the combined statistic must exceed the best plane taken alone.
    """
    body = _four_plane_body(seed=10)
    frames = [_four_plane_exposure(body, seed=200 + 10 * n) for n in range(FRAMES)]
    k = prnu.postprocess(prnu.estimate_fingerprint(frames))

    held_out = _four_plane_exposure(body, seed=9000)
    combined = prnu.score(held_out, k)
    best_single = max(
        prnu.pce(prnu.noise_residual(held_out[c]), held_out[c] * k[c]) for c in k
    )

    assert combined > best_single, f"combined {combined:.0f} vs best plane {best_single:.0f}"
    assert combined >= MIN_MATCH_PCE


def test_saturation_mask_recovers_clipped_frames():
    """Clipped pixels carry no fingerprint; excluding them lifts the score.

    They are clamped rather than modulated, so they contribute nothing to the
    correlation peak while still inflating the energy it is measured against.
    """
    body = _four_plane_body(seed=10)
    frames = [_four_plane_exposure(body, seed=200 + 10 * n) for n in range(FRAMES)]
    k = prnu.postprocess(prnu.estimate_fingerprint(frames))

    clipped = _four_plane_exposure(body, seed=9000)
    for plane in clipped.values():  # blow out a fifth of the frame
        plane[: plane.shape[0] // 5, :] = 1.0

    masked = prnu.score(clipped, k, mask_saturated=True)
    unmasked = prnu.score(clipped, k, mask_saturated=False)
    assert masked > unmasked, f"masked {masked:.0f} vs unmasked {unmasked:.0f}"


def test_delivered_image_maps_back_to_the_photosite_lattice():
    """A delivered RGB frame is sampled onto the same lattice as the raw.

    Builds a mosaic from four known plane values, renders it as the RGB image
    a demosaic would produce, and checks each plane comes back off the right
    photosites and the right channel.
    """
    import tempfile

    from PIL import Image

    pattern = [[0, 1], [3, 2]]  # RGGB, as LibRaw reports for the R10
    values = {0: 0.8, 1: 0.6, 2: 0.4, 3: 0.2}

    rgb = np.zeros((8, 8, 3), dtype=np.float32)
    for c, (i, j) in {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}.items():
        rgb[i::2, j::2, {0: 0, 1: 1, 2: 2, 3: 1}[c]] = values[c]

    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        Image.fromarray((rgb * 255).astype(np.uint8)).save(f.name)
        planes = prnu.load_delivered_planes(f.name, pattern)

    assert sorted(planes) == [0, 1, 2, 3]
    for c, plane in planes.items():
        assert plane.shape == (4, 4)
        assert np.allclose(plane, values[c], atol=1 / 255), f"plane {c} sampled wrong"


def test_scale_search_finds_a_resized_match():
    """A downscaled frame still matches, once the reference is area-averaged.

    Resizing averages neighbouring pixels, so the fingerprint left behind is
    the area average of K. The search has to model that; sampling K instead
    lands at the null, which is the failure this test guards against.
    """
    from PIL import Image

    from fingerprint import stress

    body = _four_plane_body(seed=10)
    frames = [_four_plane_exposure(body, seed=200 + 10 * n) for n in range(FRAMES)]
    k = prnu.postprocess(prnu.estimate_fingerprint(frames))
    field = prnu.sensor_field(k)

    held_out = _four_plane_exposure(body, seed=9000)
    probe = prnu.sensor_field(held_out)

    half = (probe.shape[1] // 2, probe.shape[0] // 2)
    shrunk = np.asarray(
        Image.fromarray(probe, mode="F").resize(half, Image.LANCZOS), dtype=np.float32
    )
    residual = prnu.noise_residual(shrunk)

    match = prnu.crop_and_scale_search(residual, field)
    assert match.pce >= MIN_MATCH_PCE, f"resized frame scored {match.pce:.1f}"
    assert 0.9 <= match.scale <= 1.1, f"peak at an implausible scale {match.scale:.3f}"

    # A quarter-turned copy must still be found, and reported as turned.
    turned = prnu.crop_and_scale_search(np.rot90(residual, 1), field)
    assert turned.pce >= MIN_MATCH_PCE, f"portrait copy scored {turned.pce:.1f}"
    assert turned.rotation == 3 and not turned.mirrored, f"reported {turned.orientation}"

    # So must a mirrored one -- an editor or a careless upload can flip a
    # photograph, and a flip is not a rotation.
    flipped = prnu.crop_and_scale_search(np.fliplr(residual), field)
    assert flipped.pce >= MIN_MATCH_PCE, f"mirrored copy scored {flipped.pce:.1f}"
    assert flipped.mirrored, f"reported {flipped.orientation}"

    # The null here has to be a different body, not a rotated copy of this
    # one: once the search tries all eight orientations it simply undoes the
    # rotation and matches. A rotated K stops being a negative control the
    # moment orientation is part of the search.
    other = _four_plane_body(seed=50)
    other_frames = [_four_plane_exposure(other, seed=700 + 10 * n) for n in range(FRAMES)]
    other_field = prnu.sensor_field(prnu.postprocess(prnu.estimate_fingerprint(other_frames)))

    null = prnu.crop_and_scale_search(residual, other_field)
    assert abs(null.pce) <= MAX_MISMATCH_PCE, f"another body scored {null.pce:.1f}"


def test_web_jpeg_export_round_trips():
    """`to_web_jpeg` returns the pixels a downloader would actually get."""
    from fingerprint import stress

    rng = np.random.default_rng(0)
    source = Image.fromarray(rng.integers(0, 255, (400, 600, 3), dtype=np.uint8))

    out = stress.to_web_jpeg(source, longest_edge=300, quality=80)
    assert max(out.size) == 300
    assert stress.green_channel(out).shape == (200, 300)

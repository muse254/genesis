"""Synthetic-sensor regression suite: known ground-truth PRNU through the full pipeline.

SYNTHETIC UPPER BOUNDS: no vignetting, dark current or demosaic. Real figures
are far lower and are in docs/gates.md.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from fingerprint import prnu

# --- simulation parameters -------------------------------------------------

#: Multiplicative PRNU strength K in ``I = I0 + I0*K + Theta`` ([F09] eq. 3).
#: Real CMOS is usually under 1%; 2% is deliberately generous.
PRNU_STRENGTH = 0.02
#: Read/shot noise standard deviation, in the same [0, 1] scale as a plane.
NOISE_SIGMA = 0.01
#: Frames per enrolment. Real bodies need 40-50; a stationary synthetic sensor needs fewer.
FRAMES = 24
SHAPE = (256, 256)

# --- acceptance floors -----------------------------------------------------
# Well below what the simulation achieves: a regression alarm, not a score to report.

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
        # A defocused flat, like a real enrolment frame.
        y = np.linspace(0.45, 0.55, shape[0], dtype=np.float32)[:, None]
        x = np.linspace(0.98, 1.02, shape[1], dtype=np.float32)[None, :]
        scene = y * x

    noise = rng.normal(0.0, NOISE_SIGMA, size=shape).astype(np.float32)
    return np.clip(scene * (1.0 + sensor_prnu) + noise, 0.0, 1.0).astype(np.float32)


def enrol(sensor_prnu, frames: int = FRAMES, seed: int = 0):
    """Enrol a simulated body end to end."""
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
    """PCE of one image against ``image * K`` (PRNU is multiplicative)."""
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
    """K's serialisation cannot drift without invalidating prior registrations."""
    k = np.arange(12, dtype=np.float32).reshape(3, 4) / 100.0

    expected = "efccc13a457ce758eb92e80486df987eddca917d05d53512eddaf94f2ad96446"
    assert prnu.commitment(k).hex() == expected
    assert prnu.commitment({0: k}) == prnu.commitment(k)


def test_cfa_split_is_per_photosite():
    """Each CFA plane is one photosite type, black-corrected on its own level."""
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
    """Summing correlation surfaces across CFA planes beats the best single plane."""
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
    """Clipped pixels carry no fingerprint; excluding them lifts the score."""
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
    """A delivered RGB frame is sampled onto the same photosites and channels as the raw."""
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
    """A downscaled frame still matches, once the reference is area-averaged."""
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

    # So must a mirrored one: a flip is not a rotation.
    flipped = prnu.crop_and_scale_search(np.fliplr(residual), field)
    assert flipped.pce >= MIN_MATCH_PCE, f"mirrored copy scored {flipped.pce:.1f}"
    assert flipped.mirrored, f"reported {flipped.orientation}"

    # The null must be a different body: the search undoes any rotated copy.
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


def test_a_uniform_border_is_stripped_back_to_the_photograph():
    """A 200px margin took a real file from PCE 90,846 to 37.9; cropping restored it."""
    import numpy as np
    from PIL import Image

    from fingerprint import stress

    rng = np.random.default_rng(0)
    photo = rng.integers(20, 200, (400, 600, 3), dtype=np.uint8)
    canvas = np.full((440, 640, 3), 255, dtype=np.uint8)
    canvas[20:420, 20:620] = photo

    stripped = stress.strip_uniform_border(Image.fromarray(canvas))
    assert stripped.size == (600, 400)


def test_a_photograph_without_a_border_is_left_alone():
    import numpy as np
    from PIL import Image

    from fingerprint import stress

    rng = np.random.default_rng(1)
    photo = Image.fromarray(rng.integers(20, 200, (400, 600, 3), dtype=np.uint8))
    assert stress.strip_uniform_border(photo).size == photo.size


def test_a_blown_sky_is_not_mistaken_for_a_border():
    """Flat on one side only is scene content, not a border."""
    import numpy as np
    from PIL import Image

    from fingerprint import stress

    rng = np.random.default_rng(2)
    frame = rng.integers(20, 200, (400, 600, 3), dtype=np.uint8)
    frame[:60, :] = 255                      # blown sky along the top only
    image = Image.fromarray(frame)
    assert stress.strip_uniform_border(image).size == image.size

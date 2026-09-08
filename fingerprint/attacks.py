"""The fingerprint-copy attack, against this repo's own estimator.

What happens to `this image was exposed on body X` when K leaks.

The sensor model in [F09] eq. (3) is ``I = I0 + I0*K + Theta``. It is a
*generative* model, and nothing in it is one-way: anyone holding K can
evaluate it forwards. Plant ``alpha * J * K`` into a foreign image J and the
estimator that was built to recognise the body will recognise it, because
the estimator asks one question -- is there a term proportional to ``J*K``
in this residual -- and the attacker has just put one there. This is the
fingerprint-copy attack of [G10].

The forgery is not an approximation of a photograph from body X. On the
statistic the system actually decides on it is a *better* specimen than a
real photograph, because a real frame carries K buried in one exposure's
worth of shot noise while the forgery carries a 16-frame average of it with
the noise already removed. That asymmetry is measurable, and it is the
starting point for the defence at the bottom of this file.

Two domains, because the system accepts two kinds of file:

* **CFA planes** -- what `fingerprint test` and the scoring service's
  `aligned` path read out of a RAW. Injection is per plane, then quantised
  back to the 14-bit lattice a raw file can actually hold.
* **Delivered RGB** -- what the scoring service is actually pointed at by
  the verify page. Every output pixel of a native-resolution delivered image
  sits over one photosite, which is how `prnu.load_delivered_planes` works
  and equally how :func:`mosaic_field` puts K back onto that lattice.

Nothing here modifies the estimator. Every number this module reports comes
out of `prnu.score` and `prnu.crop_and_scale_search` unchanged, against the
threshold as shipped.

Run it:

    F=data/references/r10.npz
    C=fingerprint/raw-test-files/x.CR3

    python3 fingerprint/attacks.py alpha     --fingerprint $F --carrier $C
    python3 fingerprint/attacks.py forge     --fingerprint $F --carrier $C --alpha 0.6 --out f.jpg
    python3 fingerprint/attacks.py synthetic --fingerprint $F --alpha 0.3 --out f.jpg
    python3 fingerprint/attacks.py ladder    --fingerprint $F --carrier $C --alpha 0.6
    python3 fingerprint/attacks.py partial   --fingerprint $F --carrier $C --alpha 0.6
    python3 fingerprint/attacks.py triangle  --fingerprint $F --suspect f.jpg \
        --candidates fingerprint/raw-test-files/

References
----------
[G10] M. Goljan, J. Fridrich, M. Chen, "Sensor Noise Camera Identification:
      Countering Counter-Forensics", SPIE Media Forensics and Security 2010,
      and the IEEE TIFS 2011 version. Section 2 is the copy attack; section 3
      is the triangle test that answers it.
[G11] M. Goljan, J. Fridrich, M. Chen, "Defending Against Fingerprint-Copy
      Attack in Sensor-Based Camera Identification", IEEE TIFS 6(1), 2011.
[F09] J. Fridrich, "Digital Image Forensics Using Sensor Noise", IEEE Signal
      Processing Magazine 26(2), 2009. Sensor model eq. (3), ML estimator
      eq. (6), PCE eq. (14). Cited throughout `fingerprint/prnu.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):  # invoked as a script, not as -m fingerprint.attacks
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fingerprint import prnu  # noqa: E402

# --- constants -------------------------------------------------------------

#: Quantisation levels between black and white in a 14-bit Canon raw
#: (white 16383, black 2047). The attack is bounded from below by this and
#: not by anything the defender chose: a perturbation of ``alpha * J * K``
#: smaller than half a DN rounds away entirely. On a dim carrier -- the
#: different-R10 frame here averages 0.05 of full scale -- that puts a hard
#: floor under alpha which has nothing to do with the threshold.
RAW_LEVELS = 16383 - 2047
#: Same argument one domain along: a delivered 8-bit JPEG quantises to 256
#: levels, so the floor is higher again and rises as the carrier darkens.
DELIVERED_LEVELS = 255
#: Bisection tolerance for :func:`minimum_alpha`, as a fraction of alpha.
#: 2% is finer than the measurement is stable to -- PCE moves with the JPEG
#: encoder's rounding -- so there is no point going tighter.
ALPHA_TOLERANCE = 0.02


# --- planting K ------------------------------------------------------------


def mosaic_field(k, pattern, shape):
    """Interleave per-plane fingerprints back onto the full pixel lattice.

    The inverse of the split `prnu.load_delivered_planes` does. That function
    reads pixel ``(i, j)`` of a native-resolution delivered image from the
    colour channel the photosite under it actually measured; this writes K
    back to the same place, so a multiply by ``1 + alpha * M`` lands exactly
    ``alpha * K[c]`` in every plane the scorer will later split back out.

    Parameters
    ----------
    k : dict[int, np.ndarray]
        Enrolled fingerprint, keyed by CFA colour index.
    pattern : array-like
        The 2x2 CFA layout recorded at enrolment.
    shape : tuple[int, int]
        Pixel dimensions of the carrier.

    Returns
    -------
    np.ndarray
        A ``shape`` float32 field.
    """
    pattern = np.asarray(pattern)
    height, width = shape[:2]
    field = np.zeros((height, width), dtype=np.float32)
    for c in np.unique(pattern):
        i, j = np.argwhere(pattern == c)[0]
        plane = k[int(c)]
        rows = len(range(i, height, 2))
        cols = len(range(j, width, 2))
        if plane.shape[0] < rows or plane.shape[1] < cols:
            raise ValueError(
                f"fingerprint plane {c} is {plane.shape}, too small for a "
                f"{height}x{width} carrier -- the forgery has to be built at the "
                "sensor's own resolution"
            )
        field[i::2, j::2] = plane[:rows, :cols]
    return field


def inject_planes(planes, k, alpha: float, levels: int | None = RAW_LEVELS):
    """Plant K into CFA planes: ``J' = J * (1 + alpha * K)``.

    [G10] section 2. Multiplicative rather than additive because that is the
    form of the sensor model the estimator inverts -- an additive plant would
    correlate with K but not with ``J*K``, and `prnu.score` correlates the
    residual against ``J*K``, so the additive version throws away most of the
    peak for the same distortion.

    ``levels`` rounds the result back onto a real quantisation lattice. This
    is not tidiness: without it the attack appears to work at alpha values
    that no file format could carry, and the reported minimum alpha comes out
    roughly five times too optimistic for the attacker.
    """
    out = {}
    for c, plane in planes.items():
        forged = plane * (1.0 + float(alpha) * k[c])
        if levels:
            forged = np.round(forged * levels) / levels
        out[c] = np.clip(forged, 0.0, 1.0).astype(np.float32)
    return out


def inject_delivered(rgb, k, pattern, alpha: float):
    """Plant K into a native-resolution delivered RGB raster.

    All three channels are scaled by the same field. Only one of them is read
    back at any given pixel -- `prnu.load_delivered_planes` takes the channel
    belonging to that photosite -- but scaling all three is what a plausible
    forgery looks like and costs nothing, whereas touching one channel per
    pixel leaves a chroma checkerboard that is trivially visible.

    Done in the delivered gamma-encoded domain, not linearised first. [F09]'s
    model is linear, so this is the wrong domain in principle; measured, it
    does not matter, and `docs/gates.md` records the same thing from the
    defender's side -- linearising a delivered JPEG through an inverse sRGB
    curve made its genuine score *worse*, 309 against 1,148.

    Parameters
    ----------
    rgb : np.ndarray
        Carrier as float in [0, 255], shape (h, w, 3).
    k, pattern
        As :func:`mosaic_field`.
    alpha : float

    Returns
    -------
    np.ndarray
        uint8 raster.
    """
    rgb = np.asarray(rgb, dtype=np.float32)
    field = mosaic_field(k, pattern, rgb.shape[:2])
    forged = rgb * (1.0 + float(alpha) * field[:, :, None])
    return np.clip(np.round(forged), 0, DELIVERED_LEVELS).astype(np.uint8)


def synthetic_carrier(shape=(4000, 6000), seed: int = 0):
    """An image that was never a photograph: gradients, discs, bars, noise.

    The point of the strongest form of the attack. A forgery built on a frame
    from another camera at least began as light falling on silicon somewhere;
    this began in a random number generator, so a match against it makes
    "exposed on body X" false in every sense the sentence has.

    Deliberately a plain test pattern rather than anything generative. The
    claim under test is about the fingerprint, not about how convincing the
    picture is, and a pattern that anyone can regenerate from a seed makes
    the result reproducible without shipping a file.
    """
    rng = np.random.default_rng(seed)
    height, width = shape
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]

    image = 0.35 + 0.30 * (y * 0.5 + x * 0.5)
    image = image + 0.10 * np.sin(2 * np.pi * x * 24) * np.sin(2 * np.pi * y * 16)
    for _ in range(12):
        cy, cx = rng.uniform(0.1, 0.9), rng.uniform(0.1, 0.9)
        r = rng.uniform(0.03, 0.12)
        disc = ((y - cy) ** 2 + (x - cx) ** 2) < r * r
        image = np.where(disc, image * rng.uniform(0.5, 1.4), image)
    # A little grain, so the carrier is not so smooth that the denoiser has
    # nothing to do and the residual becomes degenerate.
    image = image + rng.normal(0.0, 0.01, size=(height, width)).astype(np.float32)

    grey = np.clip(image, 0.0, 1.0) * 255.0
    tint = np.array([1.02, 1.00, 0.97], dtype=np.float32)
    return np.clip(grey[:, :, None] * tint, 0, 255).astype(np.float32)


# --- cost of the forgery ---------------------------------------------------


def psnr(a, b, peak: float = 255.0) -> float:
    """Peak signal-to-noise ratio, in dB, of a forgery against its carrier."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    mse = float(np.mean((a - b) ** 2))
    return float("inf") if mse <= 0 else float(10.0 * np.log10(peak * peak / mse))


def ssim(a, b, peak: float = 255.0, window: int = 7) -> float:
    """Mean structural similarity, Wang et al. 2004, in about fifteen lines.

    Written here rather than taking `scikit-image`, on the same reasoning as
    `ingest/hashing.perceptual_hash`: it is one formula, the repo has no
    other use for the dependency, and a vendored version cannot drift.

    A uniform window rather than the paper's Gaussian. On a 24-megapixel
    raster the difference is in the third decimal and this number is being
    used to answer "is the damage visible", not to rank codecs.
    """
    from scipy.ndimage import uniform_filter

    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.ndim == 3:
        return float(np.mean([ssim(a[..., c], b[..., c], peak, window) for c in range(a.shape[2])]))

    c1 = (0.01 * peak) ** 2
    c2 = (0.03 * peak) ** 2
    mu_a = uniform_filter(a, window)
    mu_b = uniform_filter(b, window)
    # E[x^2] - E[x]^2, with the unbiased correction the reference uses
    n = window * window
    cov_norm = n / (n - 1.0)
    var_a = cov_norm * (uniform_filter(a * a, window) - mu_a * mu_a)
    var_b = cov_norm * (uniform_filter(b * b, window) - mu_b * mu_b)
    cov = cov_norm * (uniform_filter(a * b, window) - mu_a * mu_b)

    numerator = (2 * mu_a * mu_b + c1) * (2 * cov + c2)
    denominator = (mu_a**2 + mu_b**2 + c1) * (var_a + var_b + c2)
    return float(np.mean(numerator / denominator))


def minimum_alpha(evaluate, low: float = 0.0, high: float = 4.0, target=None, tolerance=None):
    """Smallest alpha whose forgery clears the threshold, by bisection.

    ``evaluate(alpha) -> pce``. Assumes PCE rises monotonically in alpha,
    which it does above the quantisation floor and does not below it -- under
    the floor every alpha returns the carrier's own null score, so the
    bisection converges on the floor itself. That is the answer the attacker
    wants anyway.

    Returns
    -------
    tuple[float, float]
        (alpha, PCE at that alpha). ``(inf, best)`` if ``high`` never clears.
    """
    target = prnu.PCE_THRESHOLD if target is None else target
    tolerance = ALPHA_TOLERANCE if tolerance is None else tolerance

    best = evaluate(high)
    if best < target:
        return float("inf"), best

    while (high - low) > tolerance * high:
        mid = 0.5 * (low + high)
        value = evaluate(mid)
        if value >= target:
            high, best = mid, value
        else:
            low = mid
    return high, best


# --- the defence: triangle test --------------------------------------------


#: Block edge for the triangle test, in pixels of one CFA plane. [G11] sec.V
#: used 128x128 and reports the test performing "equally well for blocks as
#: small as 64x64 and as large as 256x256"; 125 divides a 2000x3000 R10 plane
#: exactly, into 384 blocks, and so wastes no border.
TRIANGLE_BLOCK = 125


def strip_fingerprint(planes, k, plane: int = 3):
    """A frame's residual with the fingerprint it should carry projected out.

    Both a genuine frame and a forgery contain a term proportional to
    ``J*K`` -- that term is exactly what `prnu.score` measures, so it carries
    no information about which is which and has to come out before anything
    else is compared. Least squares, because the coefficient differs between
    them: a genuine exposure has whatever PRNU strength the silicon has, a
    forgery has whatever alpha the attacker chose.

    What is left is everything else the body puts into a frame and the
    published K does not contain -- readout structure, dark current, lens
    signature, the unfiltered part of the PRNU that `prnu.postprocess`
    deliberately removed. A genuine frame has all of it. A forgery has none
    of it, because ``alpha * J * K`` is all it was ever given.

    Returns
    -------
    np.ndarray
        A zero-mean 1-D float64 vector, ready for :func:`collinearity`.
    """
    image = np.asarray(planes[plane], dtype=np.float64)
    field = np.asarray(k[plane], dtype=np.float64)
    if image.shape != field.shape:
        raise ValueError(
            f"one lattice required: frame {image.shape}, fingerprint {field.shape}"
        )

    residual = prnu.noise_residual(planes[plane]).astype(np.float64).ravel()
    expected = (image * field).ravel()

    energy = float(expected @ expected)
    if energy > 0:
        residual = residual - (float(residual @ expected) / energy) * expected
    return residual - residual.mean()


def collinearity(a, b) -> float:
    """Normalised correlation of two fingerprint-stripped residuals.

    NOT the triangle test, and the difference matters -- see
    `docs/adversarial.md`. [G11]'s test looks for an *excess* correlation
    between a forgery and the specific frames K was built from. This looks
    for a *deficit*: whatever a real frame of this body shares with other
    real frames of this body beyond the published K, a forgery does not have.

    Measured on the R10 this is the defence that worked, and by a wide
    margin. It is also the one an attacker escapes most cheaply, since the
    material it keys on is in any RAW file from the body.
    """
    denominator = np.sqrt(float(a @ a) * float(b @ b))
    return 0.0 if denominator <= 0 else float((a @ b) / denominator)


def _blocks(a, edge: int = TRIANGLE_BLOCK):
    """Cut a plane into non-overlapping square blocks, one row per block."""
    a = np.asarray(a, dtype=np.float64)
    h, w = (a.shape[0] // edge) * edge, (a.shape[1] // edge) * edge
    tiled = a[:h, :w].reshape(h // edge, edge, w // edge, edge)
    return tiled.transpose(0, 2, 1, 3).reshape(-1, edge * edge)


def _corr(a, b) -> float:
    a = a - a.mean()
    b = b - b.mean()
    denominator = np.sqrt(float(a @ a) * float(b @ b))
    return 0.0 if denominator <= 0 else float((a @ b) / denominator)


class TriangleFrame:
    """One image, reduced to what [G11] eqs (10)-(12) need of it.

    Precomputed because the triangle test is quadratic in the number of
    frames: every candidate is correlated with every other to calibrate the
    prediction, and none of the per-frame work depends on the pairing.

    ``verifier`` is the fingerprint the *verifier* holds. In [G11] that is
    Alice's own estimate from frames the attacker never had, which is the
    assumption this system cannot meet once K itself leaks -- the leaked K
    and the verifier's K are then the same object.
    """

    def __init__(self, plane, verifier_blocks, verifier_norms, verifier_flat, edge=TRIANGLE_BLOCK):
        image = np.asarray(plane, dtype=np.float64)
        residual = prnu.noise_residual(plane).astype(np.float64)

        self.image_blocks = _blocks(image, edge)
        self.residual = residual.ravel()
        #: corr(W, K_hat) -- one side of the triangle
        self.to_fingerprint = _corr(self.residual, verifier_flat)
        self.block_mean = self.image_blocks.mean(1)

        # [G11] eq (12): the per-block attenuation factor, with q = 1. Setting
        # q = 1 is sanctioned there -- a different fingerprint quality only
        # rescales lambda in the calibration below, so it cancels.
        residual_blocks = _blocks(residual, edge)
        expected = self.image_blocks * verifier_blocks
        centred_e = expected - expected.mean(1, keepdims=True)
        centred_w = residual_blocks - residual_blocks.mean(1, keepdims=True)
        block_corr = (centred_w * centred_e).sum(1) / np.sqrt(
            np.maximum((centred_w**2).sum(1) * (centred_e**2).sum(1), 1e-30)
        )
        rms = np.sqrt((self.image_blocks**2).mean(1))
        self.attenuation = (
            np.sqrt((residual_blocks**2).sum(1)) / np.maximum(rms * verifier_norms, 1e-30)
        ) * block_corr


def triangle_frames(planes, k, plane: int = 3, edge: int = TRIANGLE_BLOCK):
    """Build :class:`TriangleFrame` objects for a sequence of CFA planes."""
    field = np.asarray(k[plane], dtype=np.float64)
    blocks = _blocks(field, edge)
    norms = np.sqrt((blocks**2).sum(1))
    flat = field.ravel()
    return [TriangleFrame(p, blocks, norms, flat, edge) for p in planes]


def predicted_correlation(a: TriangleFrame, b: TriangleFrame) -> float:
    """[G11] eq. (10) with the mutual-content factor of eq. (11).

    What ``corr(W_a, W_b)`` should be if the only thing the two images share
    is the camera. The test is then whether the observed correlation exceeds
    it, which happens when one image was *built out of* the other through a
    stolen fingerprint estimate.
    """
    count = len(a.attenuation)
    mutual = (a.image_blocks * b.image_blocks).mean(1)
    numerator = float((a.attenuation * b.attenuation * mutual).sum())
    denominator = float((a.attenuation * a.block_mean).sum()) * float(
        (b.attenuation * b.block_mean).sum()
    )
    if denominator == 0:
        return 0.0
    return a.to_fingerprint * b.to_fingerprint * numerator * count / denominator


def observed_correlation(a: TriangleFrame, b: TriangleFrame) -> float:
    """The side of the triangle that is measured rather than predicted."""
    return _corr(a.residual, b.residual)


def calibrate_triangle(innocent):
    """Fit ``c = lambda * c_hat + eta`` on pairs known to be unrelated.

    [G11] eq. (13). The affine fit absorbs the non-periodic artefacts eq. (10)
    does not model, and the residual spread is what the decision threshold is
    set against.

    Returns ``(lambda, eta, sd, pearson)``. **Read the Pearson coefficient.**
    If the prediction does not track the observation on the verifier's own
    corpus, the test has no null to test against and every d below is
    meaningless -- which is what happened on this repo's frames
    (`docs/adversarial.md`).
    """
    predicted = []
    observed = []
    for a, b in innocent:
        predicted.append(predicted_correlation(a, b))
        observed.append(observed_correlation(a, b))
    predicted = np.asarray(predicted)
    observed = np.asarray(observed)

    slope, intercept = np.polyfit(predicted, observed, 1)
    spread = float((observed - (slope * predicted + intercept)).std())
    pearson = float(np.corrcoef(predicted, observed)[0, 1])
    return float(slope), float(intercept), spread, pearson


def triangle_d(suspect, candidate, calibration) -> float:
    """[G11] eq. (15) test statistic, in units of the calibrated spread."""
    slope, intercept, spread, _ = calibration
    if spread <= 0:
        return 0.0
    return (
        observed_correlation(suspect, candidate)
        - slope * predicted_correlation(suspect, candidate)
        - intercept
    ) / spread


# --- degrading K -----------------------------------------------------------


def degrade(k, *, downsample: int = 1, crop: float = 1.0, bits: int | None = None):
    """Weaken a leaked fingerprint, to ask how much of K an attacker needs.

    Three ways a leak can be partial, each answering a different question:
    ``downsample`` averages KxK blocks and expands them back (what survives
    if K leaked through a resized artefact), ``crop`` keeps a centred
    fraction and zeroes the rest (a partial file read), ``bits`` quantises
    the values (a low-precision or lossily-stored copy).

    Returns a fingerprint of the original shape, so it drops straight into
    :func:`inject_planes` and the scorer never knows the difference.
    """
    out = {}
    for c, plane in k.items():
        field = np.asarray(plane, dtype=np.float32).copy()

        if downsample > 1:
            h = field.shape[0] // downsample * downsample
            w = field.shape[1] // downsample * downsample
            block = field[:h, :w].reshape(
                h // downsample, downsample, w // downsample, downsample
            )
            coarse = block.mean(axis=(1, 3))
            field[:h, :w] = np.repeat(np.repeat(coarse, downsample, 0), downsample, 1)

        if crop < 1.0:
            keep = np.zeros_like(field, dtype=bool)
            ch = int(field.shape[0] * crop)
            cw = int(field.shape[1] * crop)
            top = (field.shape[0] - ch) // 2
            left = (field.shape[1] - cw) // 2
            keep[top : top + ch, left : left + cw] = True
            field = np.where(keep, field, 0.0).astype(np.float32)

        if bits is not None:
            # Mid-rise, not mid-tread: no quantisation level sits at zero, so
            # ``bits=1`` degrades to a pure sign map rather than collapsing the
            # whole field to zeros. That case is the interesting one -- a
            # one-bit K still forges (docs/adversarial.md) -- and a mid-tread
            # quantiser would have reported it as a failure.
            scale = float(np.abs(field).max())
            if scale > 0:
                levels = 2**bits
                step = 2 * scale / levels
                index = np.clip(np.floor(field / step), -levels // 2, levels // 2 - 1)
                field = ((index + 0.5) * step).astype(np.float32)

        out[c] = field
    return out


# --- CLI -------------------------------------------------------------------


def _carrier_rgb(path, size=None, seed: int = 0):
    """Load a carrier as a float RGB raster in [0, 255], developing a RAW."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    if path is None:
        return synthetic_carrier(size or (4000, 6000), seed=seed)

    suffix = Path(path).suffix.lower()
    if suffix in {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"}:
        from fingerprint import stress

        image = stress.develop(path)
    else:
        with Image.open(path) as opened:
            image = opened.convert("RGB")
    return np.asarray(image.convert("RGB"), dtype=np.float32)


def _workdir(args) -> Path:
    """Where the probe JPEGs go. Never the working directory by default -- a
    24-megapixel scratch file landing in the repo is how a forged image ends
    up committed."""
    import tempfile

    return Path(args.workdir or tempfile.gettempdir())


def _write_jpeg(array, path, quality: int):
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    Image.fromarray(np.asarray(array, dtype=np.uint8)).save(path, "JPEG", quality=quality)
    return path


def _delivered_score(path, k, meta) -> float:
    return prnu.score(prnu.load_delivered_planes(path, meta["cfa_pattern"]), k)


def cmd_alpha(args) -> int:
    """Find the smallest alpha that clears PCE 100, both domains."""
    k, meta = prnu.load_fingerprint(args.fingerprint)

    print(f"fingerprint {args.fingerprint} ({meta.get('frames', '?')} frames)")
    print(f"carrier     {args.carrier}\n")

    if not args.delivered_only:
        planes = prnu.load_raw_planes(args.carrier)
        baseline = prnu.score(planes, k)
        print(f"CFA-plane path, quantised to {RAW_LEVELS} raw levels")
        print(f"  carrier alone            PCE {baseline:10.1f}")

        def raw_eval(a):
            return prnu.score(inject_planes(planes, k, a), k)

        alpha, value = minimum_alpha(raw_eval)
        print(f"  minimum alpha {alpha:8.3f}   PCE {value:10.1f}")
        for a in (alpha, 0.25, 0.5, 1.0):
            forged = inject_planes(planes, k, a)
            mse = np.mean([np.mean((forged[c] - planes[c]) ** 2) for c in planes])
            print(
                f"  alpha {a:8.3f}          PCE {raw_eval(a):10.1f}   "
                f"PSNR {10 * np.log10(1.0 / mse):6.2f} dB"
            )
        print()

    rgb = _carrier_rgb(args.carrier)
    tmp = _workdir(args) / "_alpha_probe.jpg"
    print(f"delivered path, {rgb.shape[1]}x{rgb.shape[0]} JPEG q{args.quality}")
    carrier8 = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    _write_jpeg(carrier8, tmp, args.quality)
    print(f"  carrier alone            PCE {_delivered_score(tmp, k, meta):10.1f}")

    def delivered_eval(a):
        _write_jpeg(inject_delivered(rgb, k, meta["cfa_pattern"], a), tmp, args.quality)
        return _delivered_score(tmp, k, meta)

    alpha, value = minimum_alpha(delivered_eval)
    print(f"  minimum alpha {alpha:8.3f}   PCE {value:10.1f}")
    for a in (alpha, 0.5, 1.0):
        forged = inject_delivered(rgb, k, meta["cfa_pattern"], a)
        print(
            f"  alpha {a:8.3f}          PCE {delivered_eval(a):10.1f}   "
            f"PSNR {psnr(forged, carrier8):6.2f} dB   SSIM {ssim(forged, carrier8):.5f}"
        )
    tmp.unlink(missing_ok=True)
    return 0


def cmd_forge(args) -> int:
    """Write one forged JPEG and report what it scores and what it cost."""
    k, meta = prnu.load_fingerprint(args.fingerprint)
    if args.degrade_downsample > 1 or args.degrade_crop < 1.0 or args.degrade_bits:
        k = degrade(
            k,
            downsample=args.degrade_downsample,
            crop=args.degrade_crop,
            bits=args.degrade_bits,
        )
        print(
            f"using a degraded K: downsample {args.degrade_downsample}, "
            f"crop {args.degrade_crop}, bits {args.degrade_bits}"
        )

    rgb = _carrier_rgb(args.carrier, seed=args.seed)
    carrier8 = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    forged = inject_delivered(rgb, k, meta["cfa_pattern"], args.alpha)
    _write_jpeg(forged, args.out, args.quality)

    real_k, _ = prnu.load_fingerprint(args.fingerprint)
    print(f"carrier   {args.carrier or 'synthetic test pattern'}")
    print(f"alpha     {args.alpha}")
    print(f"written   {args.out}  (JPEG q{args.quality})")
    print(f"PCE       {_delivered_score(args.out, real_k, meta):.1f} "
          f"(threshold {prnu.PCE_THRESHOLD})")
    print(f"PSNR      {psnr(forged, carrier8):.2f} dB")
    print(f"SSIM      {ssim(forged, carrier8):.5f}")
    return 0


def cmd_ladder(args) -> int:
    """Run the Gate B degradation ladder on a forgery."""
    from PIL import Image

    from fingerprint import stress

    Image.MAX_IMAGE_PIXELS = None
    k, meta = prnu.load_fingerprint(args.fingerprint)
    rgb = _carrier_rgb(args.carrier, seed=args.seed)
    forged = Image.fromarray(inject_delivered(rgb, k, meta["cfa_pattern"], args.alpha))

    print(f"carrier {args.carrier or 'synthetic'}, alpha {args.alpha}, injected at native size\n")
    for label, value, scale, orientation in stress.ladder(forged, k):
        verdict = "MATCH   " if value >= prnu.PCE_THRESHOLD else "no match"
        print(f"  {label:>12}  {verdict}  PCE {value:9.1f}  scale {scale:.3f}  {orientation}")
    return 0


def cmd_partial(args) -> int:
    """How much of K does the attacker actually need?"""
    k, meta = prnu.load_fingerprint(args.fingerprint)
    rgb = _carrier_rgb(args.carrier, seed=args.seed)
    tmp = _workdir(args) / "_partial_probe.jpg"

    variants = [("full K", {})]
    variants += [(f"downsampled {n}x{n}", {"downsample": n}) for n in (2, 4, 8)]
    variants += [(f"centre {int(f * 100)}% only", {"crop": f}) for f in (0.5, 0.25)]
    variants += [(f"{b}-bit values", {"bits": b}) for b in (4, 2, 1)]

    carrier8 = np.clip(np.round(rgb), 0, 255).astype(np.uint8)
    print(f"carrier {args.carrier or 'synthetic'}, alpha {args.alpha}\n")
    # PSNR is in the table because degrading K changes its amplitude as well as
    # its structure -- a coarsely quantised K is a *louder* K, so its PCE is not
    # comparable with the full one at the same alpha unless the cost is shown.
    print(f"  {'leaked K':<22} {'PCE':>10} {'PSNR':>9}  verdict")
    for label, kwargs in variants:
        weakened = k if not kwargs else degrade(k, **kwargs)
        forged = inject_delivered(rgb, weakened, meta["cfa_pattern"], args.alpha)
        _write_jpeg(forged, tmp, args.quality)
        value = _delivered_score(tmp, k, meta)
        verdict = "MATCH" if value >= prnu.PCE_THRESHOLD else "no match"
        print(f"  {label:<22} {value:10.1f} {psnr(forged, carrier8):8.1f} dB  {verdict}")
    tmp.unlink(missing_ok=True)
    return 0


def cmd_triangle(args) -> int:
    """Both defences, side by side, on the same suspects and candidates.

    ``--suspect`` may be given more than once as ``label=path``. Give it at
    least one image known to be genuine as well as the one under suspicion:
    neither statistic here has an absolute threshold, only a separation, and
    a separation needs both sides.
    """
    k, meta = prnu.load_fingerprint(args.fingerprint)
    plane = args.plane

    def load(path):
        if Path(path).suffix.lower() in {".cr3", ".cr2", ".nef", ".arw", ".dng"}:
            return prnu.load_raw_planes(path, crop=meta.get("crop"))
        return prnu.load_delivered_planes(path, meta["cfa_pattern"])

    suspects = {}
    for item in args.suspect:
        label, _, path = item.rpartition("=")
        path = path or item
        suspects[label or Path(path).name] = load(path)

    paths = sorted(
        p for p in Path(args.candidates).iterdir() if p.suffix.lower() in {".cr3", ".cr2", ".nef"}
    )
    print(f"{len(suspects)} suspects, {len(paths)} candidates, plane {plane}", file=sys.stderr)

    candidates = []
    for n, path in enumerate(paths):
        print(f"  [{n + 1:>3}/{len(paths)}] {path.name}", file=sys.stderr)
        candidates.append((path.name, load(path)))

    # --- the collinearity detector -----------------------------------------
    print(f"\ncollinearity, plane {plane}: what a frame shares with other frames of")
    print("this body beyond the published K. A forgery has nothing.\n")
    stripped = {label: strip_fingerprint(p, k, plane) for label, p in suspects.items()}
    reference = [(name, strip_fingerprint(p, k, plane)) for name, p in candidates]

    print(f"  {'suspect':<26} {'mean rho':>11} {'max rho':>11}")
    for label, vector in stripped.items():
        values = np.array([collinearity(vector, r) for name, r in reference if name != label])
        print(f"  {label:<26} {values.mean():+11.6f} {values.max():+11.6f}")

    # --- the triangle test -------------------------------------------------
    print("\ntriangle test [G11] eqs (10)-(15): does the suspect correlate with the")
    print("frames K was estimated from, over and above what the camera explains?\n")
    frames = triangle_frames(
        [p[plane] for _, p in candidates] + [p[plane] for p in suspects.values()], k, plane
    )
    candidate_frames = frames[: len(candidates)]
    suspect_frames = dict(zip(suspects, frames[len(candidates) :]))

    innocent = [
        (candidate_frames[i], candidate_frames[j])
        for i in range(len(candidate_frames))
        for j in range(i + 1, len(candidate_frames))
    ]
    calibration = calibrate_triangle(innocent)
    slope, intercept, spread, pearson = calibration
    print(f"  calibration on {len(innocent)} innocent pairs: lambda {slope:+.3f} "
          f"eta {intercept:+.6f} spread {spread:.6f}")
    print(f"  Pearson(observed, predicted) {pearson:+.3f}")
    if pearson < 0.3:
        print("  the prediction does not track the observation: d below means nothing.")

    print(f"\n  {'suspect':<26} {'mean d':>9} {'max d':>9} {'mean c':>11} {'max c':>11}")
    for label, suspect in suspect_frames.items():
        rows = [(name, f) for (name, _), f in zip(candidates, candidate_frames) if name != label]
        d = np.array([triangle_d(suspect, f, calibration) for _, f in rows])
        c = np.array([observed_correlation(suspect, f) for _, f in rows])
        print(f"  {label:<26} {d.mean():+9.3f} {d.max():+9.3f} {c.mean():+11.6f} {c.max():+11.6f}")
        if args.detail:
            for (name, f), value in sorted(zip(rows, c), key=lambda r: -r[1]):
                print(f"      {name:<26} c {value:+.6f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="attacks", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def common(parser):
        parser.add_argument("--fingerprint", required=True)
        parser.add_argument("--carrier", default=None, help="omit for the synthetic carrier")
        parser.add_argument("--quality", type=int, default=95)
        parser.add_argument("--seed", type=int, default=0)
        parser.add_argument("--workdir", default=None, help="where probe JPEGs go (default: temp)")

    a = sub.add_parser("alpha", help="minimum injection strength that clears PCE 100")
    common(a)
    a.add_argument("--delivered-only", action="store_true")
    a.set_defaults(func=cmd_alpha)

    f = sub.add_parser("forge", help="write one forged JPEG")
    common(f)
    f.add_argument("--alpha", type=float, default=0.6)
    f.add_argument("--out", required=True)
    f.add_argument("--degrade-downsample", type=int, default=1)
    f.add_argument("--degrade-crop", type=float, default=1.0)
    f.add_argument("--degrade-bits", type=int, default=None)
    f.set_defaults(func=cmd_forge)

    lad = sub.add_parser("ladder", help="Gate B degradation ladder on a forgery")
    common(lad)
    lad.add_argument("--alpha", type=float, default=0.6)
    lad.set_defaults(func=cmd_ladder)

    part = sub.add_parser("partial", help="how much of K the attacker needs")
    common(part)
    part.add_argument("--alpha", type=float, default=0.6)
    part.set_defaults(func=cmd_partial)

    tri = sub.add_parser("triangle", help="the triangle-test defence")
    tri.add_argument("--fingerprint", required=True)
    tri.add_argument("--suspect", action="append", required=True, help="[label=]path, repeatable")
    tri.add_argument("--detail", action="store_true", help="print every candidate")
    tri.add_argument("--candidates", required=True, help="directory of enrolment-era RAW frames")
    tri.add_argument("--plane", type=int, default=3)
    tri.set_defaults(func=cmd_triangle)

    sy = sub.add_parser("synthetic", help="forge from a carrier that was never a photograph")
    common(sy)
    sy.add_argument("--alpha", type=float, default=0.6)
    sy.add_argument("--out", required=True)
    sy.set_defaults(func=lambda args: cmd_forge(_no_carrier(args)))

    return p


def _no_carrier(args):
    args.carrier = None
    args.degrade_downsample, args.degrade_crop, args.degrade_bits = 1, 1.0, None
    return args


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

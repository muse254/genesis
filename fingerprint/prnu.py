"""PRNU imaging core.

CFA-plane-native sensor fingerprint extraction and comparison.

Pipeline (BUILD.md sec.4, Flow A):
    RAW -> CFA plane split -> wavelet Wiener residual -> ML estimator -> K

Everything here operates on the *raw* Bayer planes, not a demosaiced RGB
image. That is the point of difference from polimi-ispl/prnu-python, which
assumes delivered RGB and must be adapted rather than imported.

Canonical behaviour reference: Binghamton DDE Lab MATLAB implementation.

References
----------
[F09] J. Fridrich, "Digital Image Forensics Using Sensor Noise", IEEE Signal
      Processing Magazine 26(2), March 2009, pp. 26-37.
      http://ws2.binghamton.edu/fridrich/Research/full_paper_02.pdf
      Sensor model eq. (3), ML fingerprint estimator eq. (6), CRLB eq. (7),
      PCE eq. (14), denoising filter in Appendix A.
[M99] M. K. Mihcak, I. Kozintsev, K. Ramchandran, "Spatially Adaptive
      Statistical Modeling of Wavelet Image Coefficients and its Application
      to Denoising", IEEE ICASSP 1999. The denoiser [F09] Appendix A uses.
[DDE] Binghamton DDE Lab reference implementation.
      https://dde.binghamton.edu/download/camera_fingerprint/
"""

from __future__ import annotations

import hashlib
import json
import warnings
from pathlib import Path

import numpy as np
import pywt
from scipy.ndimage import uniform_filter

# --- constants -------------------------------------------------------------

#: Wavelet basis for the denoiser. [F09] Appendix A Step 1 specifies the
#: 8-tap Daubechies QMF, which is ``db8`` in PyWavelets. The choice is not
#: free: the fingerprint lives in the high-frequency detail bands, and a
#: shorter filter leaks more scene edge into them, which is exactly the
#: content the estimator must not mistake for sensor noise.
WAVELET = "db8"
#: Decomposition depth, [F09] Appendix A Step 1. Four levels is what reaches
#: far enough down the frequency scale to catch the low-frequency part of the
#: residual while still separating it from scene structure. Fewer levels
#: leaves fingerprint energy in the approximation band, which this pipeline
#: discards; more levels starts folding scene content back in.
WAVELET_LEVELS = 4
#: Local-variance neighbourhoods for the Mihcak estimator, [F09] Appendix A
#: Step 2. The estimate is the *minimum* over these four sizes, and the
#: minimum is the point: a small window tracks detail, a large one is stable,
#: and taking the smallest variance biases the filter towards calling a
#: coefficient noise rather than signal. That bias is deliberate -- a
#: fingerprint wrongly classified as scene content is gone for good.
WIENER_WINDOWS = (3, 5, 7, 9)
#: Assumed sensor noise sigma for the Wiener shrinkage, in the [0, 1] scale
#: these planes use. [F09] Appendix A: "In all experiments, we used sigma0 = 2
#: (for dynamic range of images 0, ..., 255) to be conservative and to make
#: sure that the filter extracts a substantial part of the PRNU noise even for
#: cameras with a large noise component." Deliberately over-estimating the
#: noise costs some scene leakage and buys fingerprint that would otherwise be
#: filtered away. Raw CFA planes are linear where that figure was set on
#: gamma-encoded 8-bit, so this is a starting point to be re-measured per
#: body, not a constant of nature.
SIGMA = 2.0 / 255.0
#: PCE decision threshold. Provisional. It has to clear the null, and the null
#: is not zero: peaking over all shifts puts it near 2*ln(N), measured at 25
#: to 40 on full-resolution R10 planes (docs/gates.md). 50 sits above that and
#: below the weakest true match measured so far, 91. Replace it with a
#: measured value the moment a second body exists -- one body cannot tell you
#: where the false-positive rate lands.
PCE_THRESHOLD = 50.0
#: Fraction of full scale at which a photosite counts as saturated. A clipped
#: pixel is clamped rather than modulated, so it carries no PRNU at all and
#: contributes only noise to the denominator of the estimator.
SATURATION_LEVEL = 0.99
#: Warn when more than this fraction of an enrolment frame is saturated. Gate
#: A found bright unsaturated frames scoring an order of magnitude above dim
#: ones, which is what the CRLB in [F09] eq. (7) predicts.
SATURATION_WARN = 0.01
#: Byte-serialisation version for :func:`commitment`. Changing anything about
#: how K is serialised MUST change this string -- see the docstring there. A
#: body registered on chain under one serialisation can never be verified
#: under another, so this is a one-way door per registration.
COMMITMENT_VERSION = b"genesis-prnu-k-v1"


# --- raw ingest ------------------------------------------------------------


def load_raw_planes(path, crop: int | None = None):
    """Read a RAW file and return its CFA planes, black/white-level corrected.

    Uses rawpy (LibRaw bindings) -- the only realistic CR3 path. Reads
    ``raw_image_visible``, splits by ``raw_colors_visible``, subtracts
    ``black_level_per_channel`` and normalises by ``white_level``.

    Splitting happens before anything else and never demosaics: each CFA
    colour lands on its own regular sublattice, so a plane is a real image
    of one photosite type rather than an interpolation of four.

    Parameters
    ----------
    path : str | Path
        RAW file. CR3 requires LibRaw >= 0.21.
    crop : int, optional
        If given, take a centred ``crop`` x ``crop`` square of the CFA grid
        before splitting. Cheap mode for `pair` and for sanity checks.

    Returns
    -------
    dict[int, np.ndarray]
        CFA colour index -> 2-D float32 plane in [0, 1].
    """
    import rawpy  # imported lazily: the rest of this module needs no LibRaw

    with rawpy.imread(str(path)) as raw:
        image = raw.raw_image_visible.astype(np.float32)
        colors = raw.raw_colors_visible
        black = np.asarray(raw.black_level_per_channel, dtype=np.float32)
        white = float(raw.white_level)

    if crop is not None:
        image = _centre_crop(image, crop)
        colors = _centre_crop(colors, crop)

    return split_cfa(image, colors, black, white, source=path)


def split_cfa(image, colors, black, white: float, source="<array>"):
    """Split a Bayer mosaic into one normalised plane per CFA colour.

    Kept separate from :func:`load_raw_planes` so the sublattice indexing and
    the per-channel black-level subtraction -- the two places a silent error
    would poison every fingerprint downstream -- are testable without a RAW
    file and without LibRaw.
    """
    image = np.asarray(image, dtype=np.float32)
    colors = np.asarray(colors)
    black = np.asarray(black, dtype=np.float32)

    pattern = colors[:2, :2]
    tiled = np.tile(pattern, (colors.shape[0] // 2 + 1, colors.shape[1] // 2 + 1))
    if not np.array_equal(tiled[: colors.shape[0], : colors.shape[1]], colors):
        raise ValueError(
            f"{source}: CFA is not a 2x2 Bayer pattern. X-Trans and friends are "
            "out of scope (BUILD.md sec.13)."
        )

    planes: dict[int, np.ndarray] = {}
    for c in np.unique(colors):
        i, j = np.argwhere(pattern == c)[0]
        plane = image[i::2, j::2]
        level = float(black[c]) if c < len(black) else 0.0
        span = white - level
        if span <= 0:
            raise ValueError(f"{source}: white level {white} is not above black level {level}")
        planes[int(c)] = np.clip((plane - level) / span, 0.0, 1.0).astype(np.float32)

    return planes


def _centre_crop(a, size: int):
    h, w = a.shape[:2]
    size = min(size, h, w)
    # keep the crop on an even offset so the CFA phase is preserved
    top = ((h - size) // 2) & ~1
    left = ((w - size) // 2) & ~1
    return a[top : top + size, left : left + size]


# --- noise extraction ------------------------------------------------------


def _variance_estimate(coef, sigma2: float, windows=WIENER_WINDOWS):
    """Mihcak local signal variance: min over several window sizes.

    Taking the minimum is what keeps edges from being read as signal
    variance and swallowing the noise the fingerprint lives in.
    """
    squared = coef * coef
    est = None
    for w in windows:
        local = uniform_filter(squared, size=w, mode="constant")
        v = np.maximum(local - sigma2, 0.0)
        est = v if est is None else np.minimum(est, v)
    return est


def noise_residual(plane: "np.ndarray", sigma: float = SIGMA) -> "np.ndarray":
    """Extract the noise residual W from one CFA plane.

    The Mihcak wavelet-domain Wiener denoiser [M99], as specified in [F09]
    Appendix A: ``db8`` decomposition to
    ``WAVELET_LEVELS``, per-coefficient local variance estimated over
    ``WIENER_WINDOWS`` (minimum across scales), shrinkage, reconstruct,
    then W = plane - denoised.

    Implemented in the equivalent direct form -- keep the *noise* part of
    each detail coefficient, ``c * sigma^2 / (var + sigma^2)``, zero the
    approximation band, reconstruct -- which by linearity is exactly
    ``plane - denoised`` without materialising the denoised image.
    """
    plane = np.asarray(plane, dtype=np.float32)
    sigma2 = float(sigma) ** 2

    coeffs = pywt.wavedec2(plane, WAVELET, level=WAVELET_LEVELS, mode="symmetric")

    out = [np.zeros_like(coeffs[0])]  # the approximation carries the scene, not the noise
    for details in coeffs[1:]:
        kept = []
        for band in details:
            var = _variance_estimate(band, sigma2)
            kept.append((band * sigma2 / (var + sigma2)).astype(np.float32))
        out.append(tuple(kept))

    residual = pywt.waverec2(out, WAVELET, mode="symmetric")
    return residual[: plane.shape[0], : plane.shape[1]].astype(np.float32)


# --- the estimator ---------------------------------------------------------


def estimate_fingerprint(images, planes=None, *, crop: int | None = None, progress=None):
    """Maximum-likelihood fingerprint estimator K = sum(W*I) / sum(I^2).

    This is [F09] eq. (6), the ML estimate under the sensor model
    ``I = I0 + I0*K + Theta`` of eq. (3). The ML form rather than a plain
    average of residuals: PRNU is multiplicative, so a residual from a bright
    frame carries more evidence than one from a dark frame and the estimator
    weights it accordingly. The model is linear, so by the CRLB in eq. (7)
    the estimator is minimum-variance unbiased with variance ~ 1/frames.

    That same bound says which frames are worth enrolling: [F09] concludes
    "the best images for estimation of K are those with high luminance (but
    not saturated) and small sigma^2 (which means smooth content)". A dim or
    busy frame contributes far less than its place in the count suggests, and
    a saturated pixel contributes nothing at all.

    Needs 40+ enrolment frames to be stable (BUILD.md sec.9, Gate A):
    defocused flat field, CR3 not C-RAW, Long Exposure NR off, high-ISO NR
    off, base ISO, nothing clipping.

    Parameters
    ----------
    images : sequence
        RAW file paths, or 2-D arrays, or dicts of CFA plane -> array.
    planes : sequence[int], optional
        Restrict to these CFA colour indices. Ignored for 2-D array input.
    crop : int, optional
        Centre crop applied when reading RAW paths.
    progress : callable, optional
        Called as ``progress(index, total, path)`` before each frame.

    Returns
    -------
    np.ndarray | dict[int, np.ndarray]
        A single K for 2-D array input; K per CFA plane otherwise. Not
        post-processed -- run :func:`postprocess` before use.
    """
    images = list(images)
    if not images:
        raise ValueError("no enrolment frames given")

    numerator: dict[int, np.ndarray] = {}
    denominator: dict[int, np.ndarray] = {}
    flat = False

    for n, item in enumerate(images):
        if progress is not None:
            progress(n, len(images), item)

        frame = _as_planes(item, crop=crop)
        if isinstance(frame, np.ndarray):
            frame, flat = {0: frame}, True
        elif planes is not None:
            frame = {c: p for c, p in frame.items() if c in planes}

        saturated = max(float((p >= SATURATION_LEVEL).mean()) for p in frame.values())
        if saturated > SATURATION_WARN:
            warnings.warn(
                f"{item}: {saturated:.1%} of the frame is saturated and contributes "
                "nothing to K (see the CRLB discussion in [F09])",
                stacklevel=2,
            )

        for c, plane in frame.items():
            w = noise_residual(plane)
            if c not in numerator:
                numerator[c] = np.zeros_like(plane, dtype=np.float64)
                denominator[c] = np.zeros_like(plane, dtype=np.float64)
            elif numerator[c].shape != plane.shape:
                raise ValueError(
                    f"frame {n} plane {c} is {plane.shape}, expected "
                    f"{numerator[c].shape} -- enrolment frames must share a body "
                    "and an orientation"
                )
            numerator[c] += w * plane
            denominator[c] += plane.astype(np.float64) ** 2

    k = {
        c: (numerator[c] / np.maximum(denominator[c], np.finfo(np.float64).eps)).astype(np.float32)
        for c in numerator
    }
    return k[0] if flat else k


def _as_planes(item, crop: int | None = None):
    if isinstance(item, dict):
        return item
    if isinstance(item, (str, Path)):
        return load_raw_planes(item, crop=crop)
    a = np.asarray(item, dtype=np.float32)
    if a.ndim != 2:
        raise TypeError(f"expected a path, a dict of planes or a 2-D array, got shape {a.shape}")
    return _centre_crop(a, crop) if crop else a


def postprocess(k: "np.ndarray") -> "np.ndarray":
    """Zero-mean rows/columns then DFT Wiener filter.

    Suppresses the non-unique artefacts (CFA interpolation, JPEG blocking,
    row/column readout patterns) that would otherwise make two different
    bodies of the same model correlate.

    Accepts a single K or a dict of per-plane K and returns the same shape
    of thing.
    """
    if isinstance(k, dict):
        return {c: postprocess(v) for c, v in k.items()}

    k = np.asarray(k, dtype=np.float32)
    k = _zero_mean(k)
    return _wiener_dft(k)


def _zero_mean(k):
    """Remove per-column then per-row means: the readout patterns are shared
    across every body of a model and carry no identity."""
    k = k - k.mean(axis=0, keepdims=True)
    k = k - k.mean(axis=1, keepdims=True)
    return k.astype(np.float32)


def _wiener_dft(k):
    """Attenuate periodic structure in the frequency domain.

    Anything that survives as a strong, spatially coherent frequency is
    almost certainly a sensor-model artefact rather than this body's
    photo-response non-uniformity.
    """
    sigma2 = float(k.var())
    if sigma2 <= 0:
        return k

    f = np.fft.fft2(k)
    magnitude = np.abs(f) / np.sqrt(k.size)
    smoothed = _variance_estimate(magnitude, sigma2)
    smoothed = np.sqrt(smoothed)

    magnitude[magnitude == 0] = 1.0
    filtered = f * (smoothed / magnitude)
    return np.real(np.fft.ifft2(filtered)).astype(np.float32)


# --- comparison ------------------------------------------------------------


def pce(residual: "np.ndarray", reference: "np.ndarray", squared_size: int = 11) -> float:
    """Peak-to-Correlation-Energy between a test residual and a reference.

    [F09] eq. (14). PCE rather than raw normalised correlation: it is
    shift-invariant and
    its null distribution is stable enough to set one threshold across
    bodies. ``squared_size`` is the neighbourhood excluded around the peak
    when estimating the correlation energy.

    Returns a signed value: a strong *negative* peak is not a match, and
    silently taking the absolute value would hide that.

    The peak is taken over every shift, which buys alignment-independence at
    the cost of a raised null: for uncorrelated inputs PCE concentrates near
    ``2 * ln(N)`` -- about 22 on a 256x256 plane, about 31 on a full-frame
    one -- rather than near 1. Any threshold has to clear that, not zero.
    """
    a = _zero_mean_flat(residual)
    b = _zero_mean_flat(reference)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")

    cc = np.real(np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))))

    peak_index = np.unravel_index(np.argmax(np.abs(cc)), cc.shape)
    peak = cc[peak_index]

    half = squared_size // 2
    mask = np.ones(cc.shape, dtype=bool)
    for di in range(-half, half + 1):
        for dj in range(-half, half + 1):
            mask[(peak_index[0] + di) % cc.shape[0], (peak_index[1] + dj) % cc.shape[1]] = False

    energy = float((cc[mask] ** 2).mean())
    if energy <= 0:
        return 0.0
    return float(np.sign(peak) * peak * peak / energy)


def _zero_mean_flat(a):
    a = np.asarray(a, dtype=np.float64)
    return a - a.mean()


def crop_and_scale_search(residual, reference, scales=None, verbose: bool = False):
    """Search over scale (and offset) for a match -- the Gate B path.

    A web JPEG has been resized and re-encoded, so the test residual is no
    longer pixel-aligned with K. Resample the test residual over a range of
    scales (``scipy.ndimage.zoom``) and keep the best PCE.

    This function is what makes demo step 4 -- the money shot -- possible.
    If Gate B fails, this is the code that gets cut with it.

    Returns
    -------
    tuple[float, float]
        (best PCE, scale at which it occurred).
    """
    raise NotImplementedError


# --- persistence -----------------------------------------------------------


def save_fingerprint(path, k, meta: dict | None = None) -> None:
    """Persist K to an .npz alongside enrolment metadata.

    The reference is NEVER published. A published fingerprint is a
    published forgery kit (BUILD.md sec.5) -- only its commitment hash
    goes on chain.
    """
    planes = k if isinstance(k, dict) else {0: k}
    payload = {f"plane_{c}": np.asarray(v, dtype=np.float32) for c, v in planes.items()}
    payload["meta"] = np.array(json.dumps(meta or {}))
    payload["commitment"] = np.frombuffer(commitment(k), dtype=np.uint8)
    np.savez_compressed(path, **payload)


def load_fingerprint(path):
    """Load a fingerprint written by :func:`save_fingerprint`.

    Returns
    -------
    tuple[dict[int, np.ndarray], dict]
        planes keyed by CFA colour index, and the enrolment metadata.
    """
    with np.load(path, allow_pickle=False) as data:
        planes = {
            int(key.split("_", 1)[1]): data[key] for key in data.files if key.startswith("plane_")
        }
        meta = json.loads(str(data["meta"])) if "meta" in data.files else {}
    if not planes:
        raise ValueError(f"{path}: no fingerprint planes in file")
    return planes, meta


def commitment(k: "np.ndarray") -> bytes:
    """SHA-256 commitment over K's canonical byte serialisation.

    This is ``BodyRecord.fingerprintCommitment``. Serialisation must be
    pinned before the first on-chain registration -- a change to dtype,
    byte order or shape silently invalidates every prior commitment.

    Pinned, and covered by a regression test: version tag, then for each
    CFA plane in ascending index order, the index, the shape and the plane
    as little-endian float32 in C order.
    """
    planes = k if isinstance(k, dict) else {0: k}
    h = hashlib.sha256()
    h.update(COMMITMENT_VERSION)
    for c in sorted(planes):
        plane = np.ascontiguousarray(planes[c], dtype="<f4")
        h.update(c.to_bytes(4, "big"))
        h.update(len(plane.shape).to_bytes(4, "big"))
        for dim in plane.shape:
            h.update(int(dim).to_bytes(8, "big"))
        h.update(plane.tobytes(order="C"))
    return h.digest()

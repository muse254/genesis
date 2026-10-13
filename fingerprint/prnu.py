"""PRNU imaging core: CFA-plane-native sensor fingerprint extraction and comparison.

    RAW -> CFA plane split -> wavelet Wiener residual -> ML estimator -> K

Works on raw Bayer planes, never demosaiced RGB. The scoring subset is also
ported to Rust/WASM in `rust/genesis-prnu` and parity-tested against this file.

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
from typing import NamedTuple

import numpy as np
import pywt
from scipy.ndimage import uniform_filter

# --- constants -------------------------------------------------------------

#: [F09] Appendix A Step 1: 8-tap Daubechies QMF. A shorter filter leaks scene
#: edges into the detail bands the fingerprint lives in.
WAVELET = "db8"
#: [F09] Appendix A Step 1. Fewer levels leave fingerprint in the discarded
#: approximation band; more fold scene content back in.
WAVELET_LEVELS = 4
#: Mihcak local-variance windows, [F09] Appendix A Step 2. Taking the minimum
#: biases towards calling a coefficient noise: fingerprint lost to "scene" is gone.
WIENER_WINDOWS = (3, 5, 7, 9)
#: Wiener noise sigma on the [0, 1] scale: [F09]'s sigma0 = 2/255, a deliberate
#: over-estimate. Set on gamma-encoded 8-bit, not linear raw: re-measure per body.
SIGMA = 2.0 / 255.0
#: PCE decision threshold. The null is near 2*ln(N), higher through the
#: orientation search: R10 nulls 24-43, a different R10 body 39.1 / -44.0
#: (docs/gates.md). 100 is ~2x the worst null, well under the weakest true
#: match (629, delivered JPEG). Rests on ONE other body: a floor, not calibrated.
PCE_THRESHOLD = 100.0
#: Fraction of full scale counted as saturated: a clipped pixel carries no PRNU.
SATURATION_LEVEL = 0.99
#: Warn above this saturated fraction per enrolment frame ([F09] eq. (7) CRLB).
SATURATION_WARN = 0.01
#: Serialisation version for :func:`commitment`. Any change to how K is
#: serialised MUST change this; on-chain commitments cannot be re-verified otherwise.
COMMITMENT_VERSION = b"genesis-prnu-k-v1"


# --- raw ingest ------------------------------------------------------------


def load_raw_planes(path, crop: int | None = None):
    """Read a RAW file and return its CFA planes, black/white-level corrected.

    Uses rawpy (LibRaw), the only realistic CR3 path. Never demosaics.

    Parameters
    ----------
    path : str | Path
        RAW file. CR3 requires LibRaw >= 0.21.
    crop : int, optional
        Centred ``crop`` x ``crop`` square of the CFA grid, taken before splitting.

    Returns
    -------
    dict[int, np.ndarray]
        CFA colour index -> 2-D float32 plane in [0, 1].
    """
    import rawpy  # imported lazily: the rest of this module needs no LibRaw

    with rawpy.imread(str(path)) as raw:
        if raw.raw_type != rawpy.RawType.Flat:
            raise ValueError(
                f"{path}: {raw.raw_type.name} raw, not a CFA mosaic. Linear DNGs "
                "(Adobe's lossy-JPEG conversion among them) are already "
                "demosaiced, so there are no photosite planes to split. Use "
                "load_delivered_planes() if it is at native sensor resolution."
            )
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

    Separate so sublattice indexing and black-level subtraction are testable without LibRaw.
    """
    image = np.asarray(image, dtype=np.float32)
    colors = np.asarray(colors)
    black = np.asarray(black, dtype=np.float32)

    pattern = colors[:2, :2]
    tiled = np.tile(pattern, (colors.shape[0] // 2 + 1, colors.shape[1] // 2 + 1))
    if not np.array_equal(tiled[: colors.shape[0], : colors.shape[1]], colors):
        raise ValueError(
            f"{source}: CFA is not a 2x2 Bayer pattern. X-Trans and friends are "
            "out of scope."
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


def cfa_pattern(path) -> list:
    """The 2x2 CFA colour indices of a RAW file, as ``[[c, c], [c, c]]``."""
    import rawpy

    with rawpy.imread(str(path)) as raw:
        if raw.raw_pattern is None:
            raise ValueError(f"{path}: no CFA pattern (not a mosaic raw)")
        return raw.raw_pattern.tolist()


def load_delivered_planes(path, pattern, channels=None):
    """Sample a delivered RGB image back onto the CFA photosite lattice.

    Only valid at **native sensor resolution**; resized images need
    :func:`crop_and_scale_search`.

    Parameters
    ----------
    path : str | Path
        Any image PIL can open.
    pattern : list
        The 2x2 CFA layout from :func:`cfa_pattern`.
    channels : dict[int, int], optional
        CFA colour index -> RGB channel. Defaults to the RGBG convention
        LibRaw reports: 0 red, 1 and 3 green, 2 blue.

    Returns
    -------
    dict[int, np.ndarray]
        CFA colour index -> 2-D float32 plane in [0, 1].
    """
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    channels = channels or {0: 0, 1: 1, 2: 2, 3: 1}

    with Image.open(path) as im:
        rgb = np.asarray(im.convert("RGB"), dtype=np.float32) / 255.0

    pattern = np.asarray(pattern)
    planes = {}
    for c in np.unique(pattern):
        i, j = np.argwhere(pattern == c)[0]
        planes[int(c)] = np.ascontiguousarray(rgb[i::2, j::2, channels[int(c)]])
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
    """Mihcak local signal variance: min over several window sizes."""
    squared = coef * coef
    est = None
    for w in windows:
        local = uniform_filter(squared, size=w, mode="constant")
        v = np.maximum(local - sigma2, 0.0)
        est = v if est is None else np.minimum(est, v)
    return est


def noise_residual(plane: "np.ndarray", sigma: float = SIGMA) -> "np.ndarray":
    """Noise residual W = plane - denoised, Mihcak wavelet Wiener [M99], [F09] App. A.

    Direct form: keep ``c * sigma^2 / (var + sigma^2)`` of each detail
    coefficient and zero the approximation; by linearity this equals plane - denoised.
    """
    plane = np.asarray(plane, dtype=np.float32)
    sigma2 = float(sigma) ** 2

    # Small images (web thumbnails) can't carry four db8 levels without boundary effects.
    levels = min(WAVELET_LEVELS, pywt.dwt_max_level(min(plane.shape), WAVELET))
    coeffs = pywt.wavedec2(plane, WAVELET, level=max(levels, 1), mode="symmetric")

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
    """Maximum-likelihood fingerprint estimator K = sum(W*I) / sum(I^2), [F09] eq. (6).

    ML rather than a plain average because PRNU is multiplicative: bright frames
    carry more evidence. Best frames are bright, unsaturated and smooth. Needs
    40+ frames: defocused flat field, CR3 not C-RAW, NR off, base ISO.

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

    Removes model-wide artefacts (CFA, JPEG blocking, readout patterns) that
    would make two bodies of one model correlate. Accepts K or a dict of K.
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
    """Attenuate periodic structure: a strong coherent frequency is a model artefact, not PRNU."""
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
    """Signed Peak-to-Correlation-Energy, [F09] eq. (14).

    ``squared_size`` is the neighbourhood excluded around the peak. Signed
    because a strong negative peak is not a match. Peaking over every shift
    raises the null to ~2*ln(N): ~22 at 256x256, ~31 full-frame.
    """
    return _pce_of(cross_correlation(residual, reference), squared_size)


def cross_correlation(a, b):
    """Circular cross-correlation surface of two zero-meaned fields, via FFT."""
    a = _zero_mean_flat(a)
    b = _zero_mean_flat(b)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch: {a.shape} vs {b.shape}")
    return np.real(np.fft.ifft2(np.fft.fft2(a) * np.conj(np.fft.fft2(b))))


def _pce_of(cc, squared_size: int = 11) -> float:
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


def score(planes, reference, mask_saturated: bool = True) -> float:
    """One verdict for one image against one body's fingerprint.

    Sums the correlation surfaces of every CFA plane (peaks add coherently;
    ~2x the weakest R10 score vs best single plane) and masks saturated pixels
    from both sides (3-9x on frames with 10-18% clipping).

    Parameters
    ----------
    planes : dict[int, np.ndarray]
        The candidate image's CFA planes, as :func:`load_raw_planes` returns.
    reference : dict[int, np.ndarray]
        The enrolled fingerprint, keyed the same way.
    mask_saturated : bool
        Exclude pixels at or above :data:`SATURATION_LEVEL`.

    Returns
    -------
    float
        PCE of the summed correlation surface. Compare against
        :data:`PCE_THRESHOLD`.
    """
    shared = [c for c in sorted(reference) if c in planes]
    if not shared:
        raise ValueError("no CFA plane in common between image and fingerprint")

    total = None
    for c in shared:
        plane, k = planes[c], reference[c]
        if plane.shape != k.shape:
            raise ValueError(f"plane {c}: image is {plane.shape}, fingerprint is {k.shape}")

        residual = noise_residual(plane)
        expected = plane * k
        if mask_saturated:
            keep = (plane < SATURATION_LEVEL).astype(np.float32)
            residual = residual * keep
            expected = expected * keep

        cc = cross_correlation(residual, expected)
        rms = np.sqrt((cc**2).mean())
        if rms <= 0:
            continue
        # Normalise before summing so one plane cannot dominate on scale alone.
        total = cc / rms if total is None else total + cc / rms

    return _pce_of(total) if total is not None else 0.0


def sensor_field(planes, greens=(1, 3)):
    """Collapse per-plane fingerprints into one field to match a resized image.

    Averages the greens: half the photosites and most of the luminance a resize keeps.
    """
    available = [c for c in greens if c in planes]
    if not available:
        available = sorted(planes)
    return np.mean([planes[c] for c in available], axis=0).astype(np.float32)


def _area_resize(field, size):
    """Downscale by area averaging, as a resize does to K.

    Interpolating instead keeps detail the resized image lost: measured at the null vs 408.
    """
    from PIL import Image

    return np.asarray(
        Image.fromarray(np.asarray(field, dtype=np.float32), mode="F").resize(size, Image.BOX),
        dtype=np.float32,
    )


class ScaleMatch(NamedTuple):
    """Result of :func:`crop_and_scale_search`."""

    pce: float
    scale: float
    rotation: int  #: quarter turns anticlockwise applied to the candidate
    mirrored: bool  #: whether the candidate had to be flipped left-right

    @property
    def orientation(self) -> str:
        """How the candidate sits relative to the sensor, in words."""
        turn = f"{self.rotation * 90} deg"
        return f"mirrored, {turn}" if self.mirrored else turn


def crop_and_scale_search(residual, reference, scales=None, verbose=False,
                          exhaustive=False, progress=None):
    """Search a narrow scale band and all eight orientations for the best PCE.

    For resized web JPEGs. The reference is resampled, not the residual, so
    every correlation runs at the small size.

    Parameters
    ----------
    residual : np.ndarray
        Noise residual of the candidate image.
    reference : np.ndarray
        One fingerprint field, as :func:`sensor_field` returns.
    scales : sequence[float], optional
        Multipliers on the nominal scale. Defaults to +/-6% in 13 steps.
    verbose : bool
        Print each combination as it is tried.
    exhaustive : bool
        Try every orientation at every scale (104 correlations). Default
        settles orientation at nominal scale first (8 + 13).
    progress : callable, optional
        Called as ``progress(done, total, label)`` before each correlation.

    Eight orientations because PCE is neither rotation- nor reflection-invariant
    and this path is for images whose orientation metadata is gone.

    Returns
    -------
    ScaleMatch
        (best PCE, the multiplier, the quarter turns, whether mirrored).
    """
    residual = np.asarray(residual, dtype=np.float32)
    scales = np.linspace(0.94, 1.06, 13) if scales is None else np.asarray(scales)
    orientations = [(turns, flip) for flip in (False, True) for turns in (0, 1, 2, 3)]

    total = len(orientations) * len(scales) if exhaustive else len(orientations) + len(scales)
    done = 0

    def attempt(turns, flip, f):
        nonlocal done
        if progress is not None:
            side = "mirrored " if flip else ""
            progress(done, total, f"{side}rot {turns * 90} scale {f:.3f}")
        done += 1
        candidate = np.rot90(np.fliplr(residual) if flip else residual, turns)
        height, width = candidate.shape
        resized = _area_resize(reference, (int(round(width * f)), int(round(height * f))))
        h = min(resized.shape[0], height)
        w = min(resized.shape[1], width)
        value = pce(np.ascontiguousarray(candidate[:h, :w]), resized[:h, :w])
        if verbose:
            side = "mirrored " if flip else ""
            print(f"  {side}rot {turns * 90:>3} scale {f:.3f}: PCE {value:.1f}")
        return ScaleMatch(value, float(f), int(turns), bool(flip))

    if exhaustive:
        return max(
            (attempt(t, m, f) for t, m in orientations for f in scales),
            key=lambda r: abs(r.pce),
        )

    settled = max((attempt(t, m, 1.0) for t, m in orientations), key=lambda r: abs(r.pce))
    return max(
        (attempt(settled.rotation, settled.mirrored, f) for f in scales),
        key=lambda r: abs(r.pce),
    )


# --- persistence -----------------------------------------------------------


def save_fingerprint(path, k, meta: dict | None = None) -> None:
    """Persist K to an .npz alongside enrolment metadata.

    K is NEVER published: it is a forgery kit. Only its commitment goes on chain.
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
    """SHA-256 commitment over K's canonical bytes (``BodyRecord.fingerprintCommitment``).

    Pinned by a regression test: version tag, then per plane in index order the
    index, the shape and little-endian float32 C-order data. Changing any of it
    silently invalidates every on-chain commitment.
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

"""PRNU imaging core.

CFA-plane-native sensor fingerprint extraction and comparison.

Pipeline (BUILD.md sec.4, Flow A):
    RAW -> CFA plane split -> wavelet Wiener residual -> ML estimator -> K

Everything here operates on the *raw* Bayer planes, not a demosaiced RGB
image. That is the point of difference from polimi-ispl/prnu-python, which
assumes delivered RGB and must be adapted rather than imported.

Canonical behaviour reference: Binghamton DDE Lab MATLAB implementation.
"""

from __future__ import annotations

import numpy as np

# --- constants -------------------------------------------------------------

WAVELET = "db8"
WAVELET_LEVELS = 4
#: local-variance window sizes for the Mihcak Wiener filter
WIENER_WINDOWS = (3, 5, 7, 9)
#: PCE decision threshold; provisional, replace with a measured value once
#: Gate A has run against real CR3 frames (BUILD.md sec.9).
PCE_THRESHOLD = 50.0


def load_raw_planes(path):
    """Read a RAW file and return its CFA planes, black/white-level corrected.

    Uses rawpy (LibRaw bindings) -- the only realistic CR3 path. Reads
    ``raw_image_visible``, splits by ``raw_colors_visible``, subtracts
    ``black_level_per_channel`` and normalises by ``white_level``.

    Returns
    -------
    dict[int, np.ndarray]
        CFA colour index -> 2-D float32 plane.
    """
    raise NotImplementedError


def noise_residual(plane: "np.ndarray") -> "np.ndarray":
    """Extract the noise residual W from one CFA plane.

    Mihcak wavelet-domain Wiener denoiser: ``db8`` decomposition to
    ``WAVELET_LEVELS``, per-coefficient local variance estimated over
    ``WIENER_WINDOWS`` (minimum across scales), shrinkage, reconstruct,
    then W = plane - denoised.
    """
    raise NotImplementedError


def estimate_fingerprint(images, planes=None) -> "np.ndarray":
    """Maximum-likelihood fingerprint estimator K = sum(W*I) / sum(I^2).

    Needs 40+ enrolment frames to be stable (BUILD.md sec.9, Gate A):
    defocused flat field, CR3 not C-RAW, Long Exposure NR off, high-ISO NR
    off, base ISO, nothing clipping.
    """
    raise NotImplementedError


def postprocess(k: "np.ndarray") -> "np.ndarray":
    """Zero-mean rows/columns then DFT Wiener filter.

    Suppresses the non-unique artefacts (CFA interpolation, JPEG blocking,
    row/column readout patterns) that would otherwise make two different
    bodies of the same model correlate.
    """
    raise NotImplementedError


def pce(residual: "np.ndarray", reference: "np.ndarray", squared_size: int = 11) -> float:
    """Peak-to-Correlation-Energy between a test residual and a reference.

    PCE rather than raw normalised correlation: it is shift-invariant and
    its null distribution is stable enough to set one threshold across
    bodies. ``squared_size`` is the neighbourhood excluded around the peak
    when estimating the correlation energy.
    """
    raise NotImplementedError


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


def save_fingerprint(path, k, meta: dict | None = None) -> None:
    """Persist K to an .npz alongside enrolment metadata.

    The reference is NEVER published. A published fingerprint is a
    published forgery kit (BUILD.md sec.5) -- only its commitment hash
    goes on chain.
    """
    raise NotImplementedError


def load_fingerprint(path):
    """Load a fingerprint written by :func:`save_fingerprint`."""
    raise NotImplementedError


def commitment(k: "np.ndarray") -> bytes:
    """SHA-256 commitment over K's canonical byte serialisation.

    This is ``BodyRecord.fingerprintCommitment``. Serialisation must be
    pinned before the first on-chain registration -- a change to dtype,
    byte order or shape silently invalidates every prior commitment.
    """
    raise NotImplementedError

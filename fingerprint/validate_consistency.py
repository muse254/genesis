"""Tests for the Tier 1 consistency checks.

Synthetic throughout, so they run without a fingerprint or a corpus on disk.
What they pin is the *shape* of each check -- that a frame carrying a body's
structure scores above one that only carries the fingerprint, and that the
resampling statistic responds to resampling. The measured separations on real
frames are in the docstrings and in `docs/adversarial.md`; they are not
assertable here because the corpus is deliberately not in the repository.
"""

import numpy as np
import pytest

from fingerprint import consistency, prnu


def _body(rng, shape=(96, 96)):
    """A synthetic body: a fingerprint, plus other structure it always adds."""
    k = {3: rng.normal(0, 0.02, shape).astype(np.float32)}
    extra = rng.normal(0, 0.01, shape).astype(np.float32)  # readout, dark current
    return k, extra


def _genuine(rng, k, extra, shape=(96, 96)):
    scene = rng.uniform(0.3, 0.7, shape).astype(np.float32)
    return {3: (scene * (1 + k[3]) + extra + rng.normal(0, 0.001, shape)).astype(np.float32)}


def _forgery(rng, k, alpha=0.6, shape=(96, 96)):
    """Given alpha*J*K and nothing else -- no readout, no dark current."""
    scene = rng.uniform(0.3, 0.7, shape).astype(np.float32)
    return {3: (scene * (1 + alpha * k[3]) + rng.normal(0, 0.001, shape)).astype(np.float32)}


def test_strip_fingerprint_removes_the_shared_term():
    rng = np.random.default_rng(0)
    k, extra = _body(rng)
    frame = _genuine(rng, k, extra)
    stripped = consistency.strip_fingerprint(frame, k)
    raw = prnu.noise_residual(frame[3]).astype(np.float64).ravel()
    expected = (np.asarray(frame[3], dtype=np.float64) * k[3]).ravel()

    def corr(a, b):
        a, b = a - a.mean(), b - b.mean()
        return abs(float(a @ b) / np.sqrt(float(a @ a) * float(b @ b)))

    # The shared term is what carries no information about genuine-vs-forged,
    # so what matters is that stripping collapses it, not that it reaches zero.
    assert corr(stripped, expected) < 0.01 * corr(raw, expected)


def test_strip_fingerprint_needs_one_lattice():
    rng = np.random.default_rng(1)
    k, _ = _body(rng)  # K is 96x96
    frame = {3: rng.uniform(0.3, 0.7, (64, 64)).astype(np.float32)}
    with pytest.raises(ValueError, match="one lattice"):
        consistency.strip_fingerprint(frame, k)


def test_a_genuine_frame_is_more_consistent_than_a_forgery():
    rng = np.random.default_rng(2)
    k, extra = _body(rng)
    refs = consistency.reference_vectors([_genuine(rng, k, extra) for _ in range(5)], k)

    genuine = consistency.body_consistency(_genuine(rng, k, extra), k, refs)
    forged = consistency.body_consistency(_forgery(rng, k), k, refs)
    assert genuine > forged


def test_body_consistency_without_references_is_zero():
    rng = np.random.default_rng(3)
    k, extra = _body(rng)
    assert consistency.body_consistency(_genuine(rng, k, extra), k, []) == 0.0


def test_resampling_peak_rises_on_an_upsampled_image():
    from scipy.ndimage import zoom

    rng = np.random.default_rng(4)
    native = rng.uniform(0, 255, (512, 512))
    upsampled = zoom(native[:256, :256], 2, order=3)
    assert consistency.resampling_peak(upsampled) > consistency.resampling_peak(native)


def test_resampling_peak_accepts_colour_and_is_finite():
    rng = np.random.default_rng(5)
    rgb = rng.uniform(0, 255, (128, 128, 3))
    value = consistency.resampling_peak(rgb)
    assert np.isfinite(value) and value >= 0.0


def test_neither_check_is_a_verdict():
    """The module must not grow a threshold. If this fails, read the docstrings."""
    source = (consistency.__doc__ or "") + (consistency.body_consistency.__doc__ or "")
    assert "never a verdict" in source and "do not threshold" in source
    assert not hasattr(consistency, "THRESHOLD")

"""Synthetic-sensor validation harness -- the regression suite, not a demo.

Simulates a sensor with a known ground-truth PRNU, runs the full extraction
pipeline, and asserts the recovered fingerprint correlates with truth and
that same-body PCE separates from other-body PCE by orders of magnitude.

These are SYNTHETIC UPPER BOUNDS. The simulation has a perfectly stable
fingerprint, no lens vignetting, no dark current and no demosaic. Real
figures will be far lower, and the moment real ones exist they replace
these everywhere -- here, in the README, and in the pitch (BUILD.md sec.15).
"""


def simulate_sensor(shape, seed: int = 0):
    """Generate a ground-truth multiplicative PRNU field for a fake body."""
    raise NotImplementedError


def simulate_exposure(sensor_prnu, scene=None, seed: int = 0):
    """Render one exposure through a simulated sensor: I = I0 * (1 + K) + noise."""
    raise NotImplementedError


def test_fingerprint_recovery():
    """Recovered K correlates with ground truth above the accepted floor."""
    raise NotImplementedError


def test_body_separation():
    """Same-body PCE exceeds other-body PCE by at least an order of magnitude."""
    raise NotImplementedError

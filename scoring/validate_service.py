"""Scoring service tests.

The service is the trust hole in the design (see the module docstring), so
what is tested here is that it reports what the pixels say and nothing more:
no chain reads, no fingerprint leaving the machine, and a refusal that says
"no record" rather than "fake".
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fingerprint import prnu
from scoring import app as service


@pytest.fixture
def client(tmp_path, monkeypatch):
    """A service holding one synthetic body, so the tests need no camera."""
    from fingerprint import validate_synthetic as sim

    body = {c: sim.simulate_sensor(seed=10 + c) for c in range(4)}
    frames = [
        {c: sim.simulate_exposure(k, seed=200 + 10 * n) for c, k in body.items()}
        for n in range(sim.FRAMES)
    ]
    k = prnu.postprocess(prnu.estimate_fingerprint(frames))
    prnu.save_fingerprint(
        tmp_path / "synthetic.npz", k, {"frames": len(frames), "cfa_pattern": [[0, 1], [3, 2]]}
    )

    monkeypatch.setattr(service, "REFERENCES", tmp_path)
    service._bodies.cache_clear()
    yield TestClient(service.app), body
    service._bodies.cache_clear()


def _png(planes, path):
    """Write four CFA planes back out as the RGB image a camera would deliver."""
    height, width = planes[0].shape
    rgb = np.zeros((height * 2, width * 2, 3), dtype=np.float32)
    for c, (i, j) in {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}.items():
        rgb[i::2, j::2, {0: 0, 1: 1, 2: 2, 3: 1}[c]] = planes[c]
    Image.fromarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).save(path)
    return path


def test_health_reports_what_it_holds(client):
    api, _ = client
    assert api.get("/health").json() == {"status": "ok", "bodies": 1}


def test_lookup_matches_the_body_that_took_it(client, tmp_path):
    from fingerprint import validate_synthetic as sim

    api, body = client
    frame = {c: sim.simulate_exposure(k, seed=9000 + c) for c, k in body.items()}
    path = _png(frame, tmp_path / "held-out.png")

    with path.open("rb") as handle:
        result = api.post("/lookup", files={"file": ("held-out.png", handle, "image/png")}).json()

    assert result["verdict"] == "match"
    assert result["candidates"][0]["pce"] >= result["threshold"]
    # The hashes are for the caller to resolve on chain; the service does not.
    assert result["imageHash"].startswith("0x") and len(result["imageHash"]) == 66
    assert result["perceptualHash"].startswith("0x")


def test_lookup_refuses_another_body(client, tmp_path):
    """A different sensor is "no record", which is not the same as "fake"."""
    from fingerprint import validate_synthetic as sim

    api, _ = client
    other = {c: sim.simulate_sensor(seed=50 + c) for c in range(4)}
    frame = {c: sim.simulate_exposure(k, seed=9100 + c) for c, k in other.items()}
    path = _png(frame, tmp_path / "not-mine.png")

    with path.open("rb") as handle:
        result = api.post("/lookup", files={"file": ("not-mine.png", handle, "image/png")}).json()

    assert result["verdict"] == "no-match"
    assert abs(result["candidates"][0]["pce"]) < result["threshold"]


def test_nothing_about_the_fingerprint_leaves(client, tmp_path):
    """K stays on the machine. Only scores, hashes and a commitment go out.

    A response carrying the reference would hand every caller the means to
    forge images for that body.
    """
    from fingerprint import validate_synthetic as sim

    api, body = client
    frame = {c: sim.simulate_exposure(k, seed=9000 + c) for c, k in body.items()}
    path = _png(frame, tmp_path / "frame.png")

    with path.open("rb") as handle:
        raw = api.post("/lookup", files={"file": ("frame.png", handle, "image/png")}).text

    for leaked in ("plane", "planes", "reference", "npz"):
        assert leaked not in raw, f"the response mentions {leaked}"
    assert len(raw) < 4096, "a response this large is carrying more than a verdict"


def test_score_rejects_an_unknown_body(client, tmp_path):
    api, _ = client
    path = _png({c: np.full((16, 16), 0.5, np.float32) for c in range(4)}, tmp_path / "grey.png")
    with path.open("rb") as handle:
        response = api.post(
            "/score", params={"body": "0xdeadbeef"}, files={"file": ("grey.png", handle, "image/png")}
        )
    assert response.status_code == 404

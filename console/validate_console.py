"""Tests for the console API.

The chain is stubbed and no fingerprint is needed on disk. What these pin is
the one rule the whole system now rests on: `registered` is decided by a chain
read and by nothing else, and a missing chain does not degrade into a verdict
that looks like success.
"""

import pytest
from fastapi.testclient import TestClient

from console import app as console_app
from console import chain


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        console_app, "_bodies", lambda: {"b1": {"name": "r10", "planes": {}, "meta": {}}}
    )
    return TestClient(console_app.app)


def _scored(pce):
    return lambda body, path: {"pce": pce, "path": "aligned", "orientation": "0 deg"}


def _stub_pixels(monkeypatch, pce):
    monkeypatch.setattr(console_app, "_score_against", _scored(pce))
    monkeypatch.setattr(console_app.hashing, "pixel_sha256", lambda p: b"\x11" * 32)
    monkeypatch.setattr(console_app.hashing, "perceptual_hash", lambda p: 0x1234)
    monkeypatch.setattr(console_app, "_signals", lambda *a: {"calibrated": False})


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_a_high_score_without_a_record_is_not_registered(client, monkeypatch):
    """The forgery case. 82,190 and no record must not read as a pass."""
    _stub_pixels(monkeypatch, 82190.0)
    monkeypatch.setattr(chain, "image", lambda h: None)

    body = client.post("/verify", files={"file": ("x.jpg", b"x", "image/jpeg")}).json()
    assert body["verdict"] == "fingerprint-only"
    assert body["registration"] is None


def test_a_record_makes_it_registered(client, monkeypatch):
    _stub_pixels(monkeypatch, 1895.0)
    monkeypatch.setattr(
        chain, "image",
        lambda h: chain.ImageRecord("0x11", "0x22", "0xbb", 0, "0x0", "0x0", 1895, 1788857551),
    )
    monkeypatch.setattr(chain, "body", lambda b: chain.BodyRecord("0xcc", "0xowner", "0xee", False))

    body = client.post("/verify", files={"file": ("x.cr3", b"x", "image/x-raw")}).json()
    assert body["verdict"] == "registered"
    assert body["registration"]["registeredAt"] == 1788857551
    assert body["body"]["owner"] == "0xowner"


def test_a_low_score_is_no_record_not_an_accusation(client, monkeypatch):
    _stub_pixels(monkeypatch, 38.4)
    monkeypatch.setattr(chain, "image", lambda h: None)

    body = client.post("/verify", files={"file": ("x.dng", b"x", "image/x-raw")}).json()
    assert body["verdict"] == "no-record"
    assert body["body"] is None


def test_a_dead_rpc_withholds_the_verdict(client, monkeypatch):
    """It must not fall back to fingerprint-only: that is the flattering answer."""
    _stub_pixels(monkeypatch, 82190.0)

    def dead(_):
        raise chain.ChainError("connection refused")

    monkeypatch.setattr(chain, "image", dead)
    response = client.post("/verify", files={"file": ("x.jpg", b"x", "image/jpeg")})
    assert response.status_code == 502
    assert "verdict withheld" in response.json()["detail"]


def test_state_reports_a_broken_chain_rather_than_raising(client, monkeypatch):
    def dead():
        raise chain.ChainError("no route to host")

    monkeypatch.setattr(chain, "status", dead)
    body = client.get("/state").json()
    assert body["ready"] is False
    assert "no route to host" in body["chain"]["error"]

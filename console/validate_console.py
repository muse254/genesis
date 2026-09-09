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
    """A presenter needs to see WHICH part is down, not that something is."""
    def dead():
        raise chain.ChainError("no route to host")

    monkeypatch.setattr(chain, "status", dead)
    body = client.get("/state").json()
    assert body["ready"] is False
    row = next(c for c in body["checks"] if c["check"] == "chain id")
    assert row["go"] is False and "no route to host" in row["measured"]


def test_state_rows_carry_what_a_table_needs_and_no_logic(client, monkeypatch):
    """The frontend renders these; it must never have to evaluate them."""
    monkeypatch.setattr(chain, "status", lambda: {
        "chainId": 11155111, "onExpectedChain": True, "blockNumber": 1, "registry": "0xr",
    })
    monkeypatch.setattr(chain, "block_age_seconds", lambda: 5)
    body = client.get("/state").json()
    for row in body["checks"]:
        assert set(("check", "measured", "expected", "go")) <= set(row)
        assert isinstance(row["go"], bool)


def test_a_failing_check_carries_a_remedy(client, monkeypatch):
    """A gate that says no without saying what to do gets ignored on camera."""
    monkeypatch.setenv("ENS_PARENT_NAME", "cam.osoro.eth")
    monkeypatch.setattr(chain, "ens_parent_ready",
                        lambda n: (False, "`osoro` has no subregistry under eth"))
    monkeypatch.setattr(chain, "status", lambda: {
        "chainId": 11155111, "onExpectedChain": True, "blockNumber": 1, "registry": "0xr",
    })
    monkeypatch.setattr(chain, "block_age_seconds", lambda: 5)
    body = client.get("/state").json()
    ens = next(c for c in body["checks"] if c["check"] == "ens parent")
    assert ens["go"] is False and "app.ens.dev" in ens["remedy"]


def test_gas_threshold_is_ours_not_a_mockups(client, monkeypatch):
    """0.0484 ETH is plenty for four Sepolia transactions and must read GO."""
    from console import app as ca

    monkeypatch.setenv("DEPLOYER_ADDRESS", "0xdeadbeef")
    monkeypatch.setattr(chain, "balance", lambda a: 48_364_040_818_403_266)
    monkeypatch.setattr(chain, "status", lambda: {
        "chainId": 11155111, "onExpectedChain": True, "blockNumber": 1, "registry": "0xr",
    })
    monkeypatch.setattr(chain, "block_age_seconds", lambda: 5)
    gas = next(c for c in client.get("/state").json()["checks"] if c["check"] == "deployer gas")
    assert gas["go"] is True
    assert ca.MIN_BALANCE_WEI < 5 * 10**16


def test_register_body_refuses_a_slot_that_is_taken(client, monkeypatch):
    """registerBody is a race and it is won once. Say so rather than reverting."""
    monkeypatch.setattr(
        console_app, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )
    from console import registry as reg

    monkeypatch.setattr(reg, "_bodies", console_app._bodies)
    monkeypatch.setattr(chain, "body", lambda b: chain.BodyRecord("0xcc", "0xsomeone", "0x0", False))

    r = client.post("/register-body", data={"name": "r10", "ens_label": "r10-4471"})
    assert r.status_code == 409
    assert "0xsomeone" in r.json()["detail"]


def test_register_image_refuses_below_threshold(client, monkeypatch):
    """A frame the pixels do not support must not reach the chain."""
    from console import registry as reg

    monkeypatch.setattr(
        reg, "_bodies", lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}}
    )

    class Weak:
        pce_score = 41
    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Weak())

    sent = []
    monkeypatch.setattr(reg, "cast_send", lambda args: sent.append(args))

    r = client.post(
        "/register-image",
        files={"file": ("x.cr3", b"x", "image/x-raw")},
        data={"body": "r10"},
    )
    assert r.status_code == 422
    assert "below" in r.json()["detail"]
    assert sent == []  # nothing was signed


def test_signing_needs_a_key(client, monkeypatch):
    from console import registry as reg

    monkeypatch.delenv("DEPLOYER_PRIVATE_KEY", raising=False)
    with pytest.raises(Exception):
        reg._key()


def test_a_perceptual_match_is_derived_not_registered(client, monkeypatch):
    """A pHash is collidable and cheap to forge. It must not buy the strong word."""
    from console import subgraph as sg

    _stub_pixels(monkeypatch, 37.3)               # pixels BELOW threshold
    monkeypatch.setattr(sg, "nearest", lambda h: {"imageHash": "0xaa", "distance": 0})

    record = chain.ImageRecord("0xaa", "0x22", "0xbb", 0, "0x0", "0x0", 1895, 1788857551)
    monkeypatch.setattr(chain, "image", lambda h: None if h != "0xaa" else record)
    monkeypatch.setattr(chain, "body", lambda b: chain.BodyRecord("0xcc", "0xowner", "0xee", False))

    body = client.post("/verify", files={"file": ("x.jpg", b"x", "image/jpeg")}).json()
    assert body["verdict"] == "derived"
    assert body["derivedFrom"]["matchedBy"] == "perceptual hash"
    assert body["registration"] is not None      # the chain still confirmed it


def test_a_perceptual_hit_the_chain_cannot_confirm_grants_nothing(client, monkeypatch):
    """The index is not the authority. No record on chain, no claim."""
    from console import subgraph as sg

    _stub_pixels(monkeypatch, 5000.0)
    monkeypatch.setattr(sg, "nearest", lambda h: {"imageHash": "0xaa", "distance": 0})
    monkeypatch.setattr(chain, "image", lambda h: None)   # nothing on chain

    body = client.post("/verify", files={"file": ("x.jpg", b"x", "image/jpeg")}).json()
    assert body["verdict"] == "fingerprint-only"
    assert body["registration"] is None


def test_a_dead_subgraph_does_not_fabricate_a_link(client, monkeypatch):
    """Index down must degrade to the pixel answer, never invent a registration."""
    from console import subgraph as sg

    _stub_pixels(monkeypatch, 5000.0)

    def dead(_):
        raise sg.SubgraphError("unreachable")

    monkeypatch.setattr(sg, "nearest", dead)
    monkeypatch.setattr(chain, "image", lambda h: None)

    body = client.post("/verify", files={"file": ("x.jpg", b"x", "image/jpeg")}).json()
    assert body["verdict"] == "fingerprint-only"
    assert body["derivedFrom"] is None

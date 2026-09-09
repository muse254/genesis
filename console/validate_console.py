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


def test_the_hmac_key_becomes_bytes():
    """It arrives from the environment as str; hmac.new rejects that with a
    TypeError inside the request, which surfaced as a bare 500."""
    from console import registry as reg

    import os

    os.environ["METADATA_HMAC_KEY"] = "11d5ad"
    assert reg._hmac_key() == b"\x11\xd5\xad"          # hex, as .env holds it
    os.environ["METADATA_HMAC_KEY"] = "demo-key"
    assert reg._hmac_key() == b"demo-key"              # utf-8, as local-e2e.sh passes
    os.environ["METADATA_HMAC_KEY"] = ""
    assert reg._hmac_key() is None
    del os.environ["METADATA_HMAC_KEY"]


def test_every_hash_field_is_padded_to_a_word(monkeypatch):
    """The perceptual hash is eight bytes and the ABI wants bytes32.

    Unpadded, `cast` fails with a bare "parser error" naming no field, which
    reads on camera as the chain refusing a genuine photograph.
    """
    from console import registry as reg

    class Built:
        image_hash = b"\x01" * 32
        perceptual_hash = b"\x80\x87\x05\x3f\x15\xce\x5f\x73"   # 8 bytes
        body_id = b"\x02" * 32
        modification_level = 0
        parent_image_hash = b"\x00" * 32
        metadata_hmac = b"\x03" * 32
        pce_score = 49310
        registered_at = 1788943766

    monkeypatch.setattr(
        reg, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )
    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Built())
    monkeypatch.setattr(reg.prnu, "PCE_THRESHOLD", 100.0)

    sent: list = []
    monkeypatch.setattr(reg, "cast_send", lambda args: sent.append(args) or {"txHash": "0x"})

    from fastapi.testclient import TestClient
    from console import app as ca

    monkeypatch.setattr(ca, "_bodies", reg._bodies)
    TestClient(ca.app).post(
        "/register-image",
        files={"file": ("x.cr3", b"x", "image/x-raw")},
        data={"body": "r10"},
    )
    tuple_arg = sent[0][1]
    for word in tuple_arg.strip("()").split(",")[:3]:
        if word.startswith("0x"):
            assert len(word) == 66, f"{word} is not a full bytes32 word"


def test_browse_refuses_to_escape_its_root(client, monkeypatch, tmp_path):
    """A filesystem listing on a service that holds a signing key stays rooted."""
    from console import app as ca

    monkeypatch.setattr(ca, "BROWSE_ROOT", tmp_path.resolve())
    assert client.get("/browse", params={"path": "/etc"}).status_code == 403
    assert client.get("/browse", params={"path": str(tmp_path.parent)}).status_code == 403


def test_browse_counts_raw_frames_per_folder(client, monkeypatch, tmp_path):
    """The count is the point: Gate A wants 40-50, and a picker that does not
    say which folders qualify makes the operator guess."""
    from console import app as ca

    (tmp_path / "shoot").mkdir()
    for n in range(3):
        (tmp_path / "shoot" / f"IMG_{n}.CR3").write_bytes(b"x")
    (tmp_path / "shoot" / "notes.txt").write_bytes(b"x")
    (tmp_path / "empty").mkdir()
    (tmp_path / ".hidden").mkdir()

    monkeypatch.setattr(ca, "BROWSE_ROOT", tmp_path.resolve())
    body = client.get("/browse").json()
    counts = {e["name"]: e["frames"] for e in body["entries"]}
    assert counts == {"shoot": 3, "empty": 0}      # hidden folders are not listed
    assert body["parent"] is None                   # cannot go above the root


def test_a_session_refuses_weak_frames_without_failing_the_shoot(client, monkeypatch):
    """One bad frame in two thousand must not cost the whole import."""
    from console import registry as reg

    monkeypatch.setattr(
        reg, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )

    scores = iter([9000, 41, 8000])   # the middle frame is below threshold

    class Built:
        def __init__(self, pce):
            self.pce_score = pce
            self.image_hash = bytes([pce % 251]) * 32

    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Built(next(scores)))
    monkeypatch.setattr(reg.prnu, "PCE_THRESHOLD", 100.0)
    monkeypatch.setattr(reg, "cast_send", lambda args: {"txHash": "0xabc", "blockNumber": 1,
                                                        "explorerUrl": "http://x"})

    body = client.post(
        "/register-session",
        files=[("files", (f"IMG_{i}.CR3", b"x", "image/x-raw")) for i in range(3)],
        data={"body": "r10"},
    ).json()

    assert body["frameCount"] == 2
    assert len(body["refused"]) == 1 and body["refused"][0]["pce"] == 41
    assert len(body["accepted"][0]["proof"]) >= 1      # inclusion is provable


def test_a_session_with_nothing_acceptable_signs_nothing(client, monkeypatch):
    from console import registry as reg

    monkeypatch.setattr(
        reg, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )

    class Weak:
        pce_score = 12
        image_hash = b"\x01" * 32

    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Weak())
    monkeypatch.setattr(reg.prnu, "PCE_THRESHOLD", 100.0)
    sent: list = []
    monkeypatch.setattr(reg, "cast_send", lambda args: sent.append(args))

    response = client.post(
        "/register-session",
        files=[("files", ("a.CR3", b"x", "image/x-raw"))],
        data={"body": "r10"},
    )
    assert response.status_code == 422
    assert sent == []

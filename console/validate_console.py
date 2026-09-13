"""Tests for the console API.

The chain is stubbed and no fingerprint is needed on disk. What these pin is
the one rule the whole system now rests on: `registered` is decided by a chain
read and by nothing else, and a missing chain does not degrade into a verdict
that looks like success.
"""

import json

import pytest
from fastapi.testclient import TestClient

from console import app as console_app
from console import chain


@pytest.fixture(autouse=True)
def _isolated_catalogue(tmp_path, monkeypatch):
    """Point the catalogue at a temp file for every test in this module.

    Without this the suite writes into `data/catalogue.db` -- the operator's
    real archive -- because these tests drive the real endpoints through
    TestClient. It did: a fixture body `0x0202…` and two files named IMG_0.CR3
    showed up in a live archive and made the statistics say two bodies when
    one camera existed. A test that pollutes production data is worse than no
    test, so this is autouse rather than opt-in.
    """
    import importlib

    from console import catalogue as cat

    monkeypatch.setenv("GENESIS_CATALOGUE", str(tmp_path / "test-catalogue.db"))
    importlib.reload(cat)
    monkeypatch.setattr("console.registry.catalogue", cat)
    monkeypatch.setattr("console.app.catalogue", cat)
    yield
    importlib.reload(cat)


@pytest.fixture(autouse=True)
def _isolated_references(tmp_path, monkeypatch):
    """Point `GENESIS_REFERENCES` at a temp directory for every test here.

    The same lesson as `_isolated_catalogue`, learned the same way and one
    step worse. `/reset` deletes enrolled fingerprints, `clear_enrolments`
    defaults to true, and one test drove that endpoint without isolating the
    directory -- so running the suite deleted the operator's real `.npz`. A
    catalogue row can be re-registered; a reference cannot be recreated
    identically, because `save_fingerprint` does not record which frames went
    into it.

    Autouse, and covering every test rather than the reset ones, because the
    next endpoint to touch that directory should not have to remember.
    """
    # Dot-prefixed so it cannot show up in a `/browse` listing, which is
    # rooted at a temp directory in its own tests.
    # `/state` is cached for a few seconds and the cache is module-level, so
    # one test's gate would answer for the next one's. Dropped on both sides:
    # a stale gate is exactly the bug the cache could introduce, and a suite
    # that tolerated it here would not catch it in the product.
    from console.app import invalidate_state

    invalidate_state()

    references = tmp_path / ".genesis-references"
    references.mkdir()
    # The env var covers anything reading it at call time -- `/reset`'s
    # deletion, and `/enrol`'s output path.
    monkeypatch.setenv("GENESIS_REFERENCES", str(references))
    # And the module constant, which `scoring.app._bodies` resolved at import
    # and would otherwise still glob the operator's real directory.
    monkeypatch.setattr("scoring.app.REFERENCES", references)
    yield
    invalidate_state()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        console_app, "_bodies", lambda: {"b1": {"name": "r10", "planes": {}, "meta": {}}}
    )
    return TestClient(console_app.app)


def _scored(pce):
    # `progress` is optional: /verify passes None, /verify/stream passes a
    # callback. A stub that only accepts two arguments hides that difference.
    return lambda body, path, progress=None: {
        "pce": pce, "path": "aligned", "orientation": "0 deg",
    }


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

    monkeypatch.setattr(reg, "_score_against", lambda body, path, progress=None: {"pce": 41.0})
    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Weak())
    # The body is registered on chain; this test is about the threshold.
    monkeypatch.setattr(chain, "body", lambda body_id: object())

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
    monkeypatch.setattr(reg, "_score_against", lambda body, path, progress=None: {"pce": 49310.0})
    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Built())
    monkeypatch.setattr(reg.prnu, "PCE_THRESHOLD", 100.0)
    # Registered on chain; this test is about ABI padding.
    monkeypatch.setattr(chain, "body", lambda body_id: object())

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

    monkeypatch.setattr(reg, "_score_against", lambda body, path, progress=None: {"pce": 0.0})
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

    monkeypatch.setattr(reg, "_score_against", lambda body, path, progress=None: {"pce": 12.0})
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


def test_the_catalogue_never_leaves_the_machine(tmp_path, monkeypatch):
    """It holds file paths and free text. Both are local-only by construction:
    a path maps to a RAW and a RAW is a forgery kit; a caption is unbounded
    personal data that would be permanent if published."""
    import importlib

    monkeypatch.setenv("GENESIS_CATALOGUE", str(tmp_path / "c.db"))
    from console import catalogue as cat

    importlib.reload(cat)

    cat.record_image(image_hash="0xaa", body_name="r10", pce=1895.0, registered_at=10,
                     file_name="IMG_0230.CR3", file_path="/archive/IMG_0230.CR3",
                     description="")
    cat.record_image(image_hash="0xbb", body_name="r10", pce=49310.0, registered_at=20,
                     file_name="IMG_0217.CR3", file_path="/archive/IMG_0217.CR3",
                     description="")

    assert cat.describe("0xaa", "the weak frame") is True
    assert cat.describe("0xmissing", "nope") is False   # unknown hash is not created

    stats = cat.statistics()
    assert stats["images"] == 2
    assert stats["described"] == 1
    assert stats["weakest"] == 1895.0 and stats["strongest"] == 49310.0
    assert stats["perBody"] == [{"body_name": "r10", "images": 2}]

    newest = cat.listing()[0]
    assert newest["file_name"] == "IMG_0217.CR3"        # most recent first


def test_re_registering_the_same_pixels_keeps_the_newer_path(tmp_path, monkeypatch):
    """Registering the same photograph from a different folder should update
    where it is, not create a second row for one on-chain record."""
    import importlib

    monkeypatch.setenv("GENESIS_CATALOGUE", str(tmp_path / "c.db"))
    from console import catalogue as cat

    importlib.reload(cat)
    cat.record_image(image_hash="0xaa", file_path="/old/a.CR3", file_name="a.CR3",
                     registered_at=1, description="")
    cat.describe("0xaa", "kept")
    cat.record_image(image_hash="0xaa", file_path="/new/a.CR3", file_name="a.CR3",
                     registered_at=1, description="")

    rows = cat.listing()
    assert len(rows) == 1
    assert rows[0]["file_path"] == "/new/a.CR3"
    assert rows[0]["description"] == "kept"            # the caption survives


def test_registration_and_verification_use_one_scorer(monkeypatch):
    """They diverged once and it cost a 500 on every portrait photograph.

    build_record's own scoring is the aligned path only, and a fingerprint
    lives in sensor space -- always landscape -- so a portrait frame raised
    `image is (3000, 2000), fingerprint is (2000, 3000)`. /verify caught that
    and fell through to the orientation search; registration did not.
    """
    from console import registry as reg
    from scoring.app import _score_against

    assert reg._score_against is _score_against

    import inspect

    source = inspect.getsource(reg.register_image)
    assert "_score_against(holder, path)" in source, "registration must not score on its own"


def test_a_duplicate_registration_says_so_plainly(monkeypatch):
    """The contract has a word for it; a wall of revert hex is not that word."""
    import subprocess

    from fastapi import HTTPException

    from console import registry as reg

    class Done:
        returncode = 1
        stdout = ""
        stderr = "execution reverted: image already registered, data: 0x08c379a0..."

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    monkeypatch.setenv("DEPLOYER_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.setattr(reg.chain, "REGISTRY", "0xreg")

    try:
        reg.cast_send(["registerImage(...)", "(...)"])
        raise AssertionError("should have raised")
    except HTTPException as error:
        assert error.status_code == 409
        assert "already registered" in error.detail
        assert "0x08c379a0" not in error.detail        # no revert hex


def test_a_session_records_which_body_it_scored_against(client, monkeypatch):
    """Without this the archive counts a session's frames as belonging to no
    body, and the statistics undercount."""
    from console import catalogue as cat
    from console import registry as reg

    monkeypatch.setattr(
        reg, "_bodies",
        lambda: {"0xbeef": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )
    monkeypatch.setattr(reg, "_score_against", lambda body, path, progress=None: {"pce": 0.0})

    class Built:
        pce_score = 9000
        image_hash = b"\x07" * 32

    monkeypatch.setattr(reg.record, "build_record", lambda *a, **k: Built())
    monkeypatch.setattr(reg.prnu, "PCE_THRESHOLD", 100.0)
    monkeypatch.setattr(reg, "cast_send", lambda args: {"txHash": "0x1", "blockNumber": 2,
                                                       "explorerUrl": "http://x"})

    client.post(
        "/register-session",
        files=[("files", ("a.CR3", b"x", "image/x-raw"))],
        data={"body": "r10"},
    )
    row = cat.listing()[0]
    assert row["body_id"] == "0xbeef"
    assert cat.statistics()["bodies"] == 1


def test_progress_reaches_the_caller_and_the_verdict_is_unchanged(client, monkeypatch):
    """The streaming path must be the same work, not a second implementation."""
    seen: list = []

    def scoring(body, path, progress=None):
        if progress:
            progress("extracting the noise residual")
            progress("searching scale and orientation — 11 of 21 (rot 90 scale 1.000)")
        return {"pce": 38.4, "path": "scale search", "orientation": "90 deg"}

    monkeypatch.setattr(console_app, "_score_against", scoring)
    monkeypatch.setattr(console_app.hashing, "pixel_sha256", lambda p: b"\x11" * 32)
    monkeypatch.setattr(console_app.hashing, "perceptual_hash", lambda p: 0x1234)
    monkeypatch.setattr(console_app, "_signals", lambda *a: {"calibrated": False})
    monkeypatch.setattr(chain, "image", lambda h: None)

    job = client.post(
        "/verify/stream", files={"file": ("x.jpg", b"x", "image/jpeg")}
    ).json()["jobId"]

    with client.stream("GET", f"/verify/{job}/events") as stream:
        for line in stream.iter_lines():
            if not line.startswith("data: "):
                continue
            event = json.loads(line[6:])
            seen.append(event)
            if event.get("event") == "done":
                break

    steps = [e for e in seen if e.get("event") == "step"]
    assert steps, "no progress reached the caller"
    # The search dominates the wall clock, so its share of the bar dominates too.
    mid = next(e for e in steps if "11 of 21" in e["label"])
    assert 0.4 < mid["fraction"] < 0.8
    assert seen[-1]["result"]["verdict"] == "no-record"


def test_an_unknown_job_is_not_a_silent_stream(client):
    assert client.get("/verify/nosuchjob/events").status_code == 404


def test_a_soft_image_says_there_was_nothing_to_measure(tmp_path):
    """"No record" reads as "not your camera". For a soft frame that is the
    wrong thing for a photographer to conclude."""
    from console.app import _diagnose

    note = _diagnose(tmp_path / "x.jpg", {"tooSoftToMeasure": True, "detail": 7.7})
    assert "high-frequency detail" in note
    assert "not the same as the camera not matching" in note


def test_an_in_camera_jpeg_is_named_as_the_likely_reason(tmp_path):
    from PIL import Image

    from console.app import _diagnose

    path = tmp_path / "IMG_0007.JPG"
    image = Image.new("RGB", (32, 32))
    exif = image.getexif()
    exif[271] = "Canon"                    # Make, and no desktop Software tag
    image.save(path, exif=exif)

    note = _diagnose(path, {})
    assert note is not None and "camera itself" in note


def test_a_desktop_development_is_not_blamed_on_the_camera(tmp_path):
    from PIL import Image

    from console.app import _diagnose

    path = tmp_path / "game.jpg"
    image = Image.new("RGB", (32, 32))
    exif = image.getexif()
    exif[271] = "Canon"
    exif[305] = "ACD Systems Digital Imaging"
    image.save(path, exif=exif)

    assert _diagnose(path, {}) is None     # nothing measured, so nothing claimed


def test_a_raw_gets_no_guess(tmp_path):
    from console.app import _diagnose

    assert _diagnose(tmp_path / "IMG_0001.CR3", {}) is None


def test_ens_node_is_the_namehash_and_not_a_hash_of_the_name():
    """The one that would have caught the 8 September registration.

    `registerBody` takes an `ensNode` and nothing on chain checks it, so a
    wrong node succeeds, costs gas, and resolves to nothing -- the failure
    `identity/addresses.md` warned about, written into the live record by the
    console shelling out to `cast keccak` instead of `cast namehash`.

    Pinned against a value computed independently by viem in
    `identity/scripts/ens.test.ts`, so the two halves of the system cannot
    drift apart again without one of them going red.
    """
    from console.registry import ens_namehash

    name = "r10-4471.cam.osoro.eth"
    namehash = "0x3533036ced2f2bc810b8f48af0e57a86d334a9612e265789b272c9292dfa8c7c"
    keccak_of_string = "0x55c9d4fbcd22449029534f3350d732c1222dba3435f93f6bc72074efb28e6543"

    assert ens_namehash(name) == namehash
    assert ens_namehash(name) != keccak_of_string


def test_ens_node_is_recursive_over_labels():
    """A parent's node is not a prefix of its child's, which is the whole
    reason hashing the flat string cannot work."""
    from console.registry import ens_namehash

    assert ens_namehash("cam.osoro.eth") != ens_namehash("r10-4471.cam.osoro.eth")
    assert ens_namehash("eth") != ens_namehash("osoro.eth")


def test_enrolment_refuses_a_folder_holding_two_cameras(monkeypatch):
    """The archive folder that holds the enrolment frames also holds the
    negatives, and `/enrol` took every RAW in it.

    `docs/gates.md` makes the serial check the first thing done to any file,
    and this endpoint skipped it. Averaging two sensors produces a fingerprint
    belonging to neither -- silently, with a commitment that looks fine.
    """
    from pathlib import Path

    from console.app import _serials_disagree

    class Done:
        returncode = 0
        stdout = "473034005088\tIMG_0217.CR3\n022031004996\tother.CR3\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    mixed = _serials_disagree([Path("IMG_0217.CR3"), Path("other.CR3")])
    assert set(mixed) == {"473034005088", "022031004996"}


def test_one_camera_enrols_cleanly(monkeypatch):
    from pathlib import Path

    from console.app import _serials_disagree

    class Done:
        returncode = 0
        stdout = "473034005088\tIMG_0217.CR3\n473034005088\tIMG_0216.CR3\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    assert _serials_disagree([Path("a.CR3"), Path("b.CR3")]) == {}


def test_a_missing_serial_does_not_block_enrolment(monkeypatch):
    """A format with no serial tag is not evidence of a second body."""
    from pathlib import Path

    from console.app import _serials_disagree

    class Done:
        returncode = 0
        stdout = "-\ta.DNG\n473034005088\tb.CR3\n"

    monkeypatch.setattr("subprocess.run", lambda *a, **k: Done())
    assert _serials_disagree([Path("a.DNG"), Path("b.CR3")]) == {}


def test_reset_refuses_a_production_registry(client, monkeypatch):
    """The gate is the contract's answer, not a local flag.

    A console that trusted configuration could offer a wipe against a registry
    that has no wipe, and the failure would arrive as an unexplained revert
    mid-demo. Worse, it could hide the control on a registry that does.
    """
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: False)

    response = client.post("/reset", data={"confirm": "0x" + "11" * 20})
    assert response.status_code == 409
    assert "not a test registry" in response.json()["detail"]


def test_reset_requires_the_registry_address_as_confirmation(client, monkeypatch):
    """The mistake worth preventing is wiping the wrong registry."""
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: True)

    response = client.post("/reset", data={"confirm": "yes"})
    assert response.status_code == 422
    assert "0x" + "11" * 20 in response.json()["detail"]


def test_reset_sends_one_transaction_when_confirmed(client, monkeypatch):
    from console import registry as registry_module

    sent: list = []
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: True)
    monkeypatch.setattr(chain, "registry_epoch", lambda: 7)
    monkeypatch.setattr(
        registry_module,
        "cast_send",
        lambda args: sent.append(args) or {"txHash": "0xabc", "blockNumber": 1, "explorerUrl": "u"},
    )

    response = client.post("/reset", data={"confirm": "0x" + "11" * 20})
    assert response.status_code == 200
    assert sent == [["resetAll()"]]
    assert response.json()["epochAfter"] == 7


def test_reset_clears_enrolments_when_asked(client, monkeypatch, tmp_path):
    """A wipe that leaves the references behind is not a clean slate.

    `resetAll` clears the chain; the enrolled fingerprints are files on this
    machine and it never touched them, so the console went on reporting a body
    with nothing on chain behind it — and demo step 1 had nothing to do.
    """
    from console import registry as registry_module

    (tmp_path / "r10.npz").write_bytes(b"not a real reference")
    monkeypatch.setenv("GENESIS_REFERENCES", str(tmp_path))
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: True)
    monkeypatch.setattr(chain, "registry_epoch", lambda: 1)
    monkeypatch.setattr(
        registry_module, "cast_send",
        lambda args: {"txHash": "0xabc", "blockNumber": 1, "explorerUrl": "u"},
    )

    response = client.post(
        "/reset", data={"confirm": "0x" + "11" * 20, "clear_enrolments": "true"}
    )
    assert response.status_code == 200
    assert response.json()["enrolmentsCleared"] == ["r10"]
    assert list(tmp_path.glob("*.npz")) == []


def test_reset_leaves_enrolments_alone_when_not_asked(client, monkeypatch, tmp_path):
    """The chain wipe and the local wipe are separable, because one is
    reversible by re-registering and the other is not."""
    from console import registry as registry_module

    (tmp_path / "r10.npz").write_bytes(b"not a real reference")
    monkeypatch.setenv("GENESIS_REFERENCES", str(tmp_path))
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: True)
    monkeypatch.setattr(chain, "registry_epoch", lambda: 1)
    monkeypatch.setattr(
        registry_module, "cast_send",
        lambda args: {"txHash": "0xabc", "blockNumber": 1, "explorerUrl": "u"},
    )

    response = client.post(
        "/reset", data={"confirm": "0x" + "11" * 20, "clear_enrolments": "false"}
    )
    assert response.json()["enrolmentsCleared"] == []
    assert [p.name for p in tmp_path.glob("*.npz")] == ["r10.npz"]


def test_the_scorer_notices_a_reference_disappearing(tmp_path, monkeypatch):
    """The cross-process half of the same bug.

    The console and the scorer are separate processes. The cache used to say
    "restart to pick up a new enrolment", so clearing through one left the
    other scoring against a fingerprint that no longer existed on disk.
    """
    import numpy as np

    from fingerprint import prnu
    from fingerprint import validate_synthetic as sim
    from scoring import app as service

    body = {c: sim.simulate_sensor(seed=40 + c) for c in range(4)}
    frames = [{c: sim.simulate_exposure(k, seed=300 + 10 * n) for c, k in body.items()}
              for n in range(sim.FRAMES)]
    k = prnu.postprocess(prnu.estimate_fingerprint(frames))
    prnu.save_fingerprint(tmp_path / "one.npz", k, {"frames": len(frames),
                                                    "cfa_pattern": [[0, 1], [3, 2]]})

    monkeypatch.setattr(service, "REFERENCES", tmp_path)
    service._bodies.cache_clear()
    assert len(service._bodies()) == 1

    (tmp_path / "one.npz").unlink()
    # No cache_clear, no restart: the directory changed and that is enough.
    assert len(service._bodies()) == 0


def test_register_image_refuses_an_unregistered_body_before_scoring(client, monkeypatch):
    """Enrolled is not registered, and the difference costs a minute.

    `registerImage` reverts `unknown body` when the id has no record on chain.
    Reaching that revert means paying for the PRNU scale search first and then
    being handed hex. Both routes there are ordinary: a fresh enrolment, and a
    `resetAll` that cleared the chain out from under an existing one.
    """
    import io

    from console import registry as registry_module

    scored: list = []
    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "body", lambda body_id: None)
    monkeypatch.setattr(
        registry_module, "_score_against",
        lambda *a, **k: scored.append(a) or {"pce": 1.0, "path": "aligned"},
    )

    response = client.post(
        "/register-image",
        files={"file": ("frame.CR3", io.BytesIO(b"raw"), "application/octet-stream")},
        data={"body": "synthetic"},
    )
    assert response.status_code in (404, 409)
    if response.status_code == 409:
        assert "not registered" in response.json()["detail"]
    # The point of the guard: it refuses before paying for the search.
    assert scored == []


def test_no_user_facing_copy_claims_origin():
    """The claim `docs/adversarial.md` falsifies, guarded across both frontends.

    `registerImage` checks only that the body's owner sent the transaction, so
    a registration establishes who claimed an image and when -- **not where
    the light fell**. `mcp/` has had a test for this since the wording was
    corrected there; the frontends had none, and the console drifted back to
    "states where these pixels came from" without anything objecting.

    Source-level because the copy is the product here. A verdict card that
    overclaims is the failure this repository is most exposed to, and it costs
    nothing to pin.
    """
    import re
    from pathlib import Path

    forbidden = [
        r"where .{0,20}pixels came from",
        r"where the light fell(?!.{0,80}(not|never|does not))",
        r"exposed on",
        r"\bAI[- ]free\b",
        r"verified real",
        r"proves? (?:it is |the )?authentic",
    ]
    roots = [Path("console-ui/src"), Path("verify/src")]
    offences = []
    for root in roots:
        if not root.is_dir():
            continue
        for source in sorted(root.rglob("*.ts")):
            text = source.read_text()
            for pattern in forbidden:
                for match in re.finditer(pattern, text, re.IGNORECASE):
                    line = text[: match.start()].count("\n") + 1
                    context = text.splitlines()[line - 1].strip()
                    # A negation is the correct use: the copy is allowed to say
                    # what the system does *not* claim.
                    if re.search(r"\b(not|never|does not|nor)\b", context, re.I):
                        continue
                    offences.append(f"{source}:{line}: {context[:100]}")
    assert not offences, "user-facing copy claims origin:\n" + "\n".join(offences)


def test_reset_clears_the_archive(client, monkeypatch, tmp_path):
    """The archive describes the chain, so it cannot outlive a wipe.

    Every row is keyed by an image hash that, after `resetAll`, resolves to
    nothing. Left alone, screen 06 goes on presenting withdrawn registrations
    as registered work -- the same shape as the enrolled references, and the
    same reason it has to go.
    """
    from console import catalogue
    from console import registry as registry_module

    monkeypatch.setattr(catalogue, "CATALOGUE", tmp_path / "catalogue.db")
    catalogue.record_image(
        image_hash="0xdead", perceptual_hash="0x00", body_id="0xb", body_name="r10",
        pce=1895.0, registered_at=1, tx_hash="0xt", block_number=1, session_id=None,
        file_name="IMG_0217.CR3", file_path="", description="", noted_at=1,
    )
    assert len(catalogue.listing()) == 1

    monkeypatch.setattr(chain, "REGISTRY", "0x" + "11" * 20)
    monkeypatch.setattr(chain, "test_mode", lambda: True)
    monkeypatch.setattr(chain, "registry_epoch", lambda: 1)
    monkeypatch.setattr(
        registry_module, "cast_send",
        lambda args: {"txHash": "0xabc", "blockNumber": 1, "explorerUrl": "u"},
    )

    response = client.post(
        "/reset", data={"confirm": "0x" + "11" * 20, "clear_enrolments": "false"}
    )
    assert response.status_code == 200
    assert response.json()["archiveRowsCleared"] == 1
    assert catalogue.listing() == []


def test_enrol_accepts_uploaded_frames(client, monkeypatch, tmp_path):
    """The console path: frames chosen in the operating system's own dialog.

    A browser cannot hand a server a path, so the picker uploads. The service
    stages them, enrols, and removes the staging whether or not it worked.
    """
    import console.app as ca

    seen: dict = {}
    monkeypatch.setattr(ca, "_serials_disagree", lambda frames: {})
    monkeypatch.setenv("GENESIS_REFERENCES", str(tmp_path))

    def fake_start(work):
        class Job:
            id = "job1"

            def emit(self, **fields):
                seen.setdefault("emitted", []).append(fields)

            def finish(self, result):
                seen["result"] = result

        return Job()

    monkeypatch.setattr(ca.jobs, "start", fake_start)

    response = client.post(
        "/enrol",
        data={"name": "r10"},
        files=[
            ("files", ("IMG_0001.CR3", b"not really raw", "application/octet-stream")),
            ("files", ("IMG_0002.CR3", b"nor this", "application/octet-stream")),
        ],
    )
    assert response.status_code == 200
    assert response.json()["frames"] == 2


def test_enrol_refuses_a_selection_with_no_raw(client, monkeypatch, tmp_path):
    """A developed JPEG has been through the camera's own noise reduction,
    which is the thing that removes the fingerprint -- so this is refused with
    the reason rather than enrolled into something meaningless."""
    monkeypatch.setenv("GENESIS_REFERENCES", str(tmp_path))

    response = client.post(
        "/enrol",
        data={"name": "r10"},
        files=[("files", ("snap.jpg", b"jpeg", "image/jpeg"))],
    )
    assert response.status_code == 422
    assert "RAW" in response.json()["detail"]


def test_enrol_needs_either_files_or_a_folder(client):
    response = client.post("/enrol", data={"name": "r10"})
    assert response.status_code == 422


def test_the_suite_cannot_touch_the_operators_references():
    """A canary for the fixture above.

    This suite deleted a real enrolled fingerprint once. `_isolated_references`
    is what stops it; this is what notices if that fixture is removed, renamed
    or stops applying.
    """
    import os
    from pathlib import Path

    live = Path("data/references").resolve()
    used = Path(os.environ["GENESIS_REFERENCES"]).resolve()
    assert used != live, "GENESIS_REFERENCES points at the real references directory"
    assert not str(used).startswith(str(live)), f"{used} is inside {live}"

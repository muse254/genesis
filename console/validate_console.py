"""Console API tests, chain stubbed. Core rule: only a chain read decides `registered`."""

import json

import pytest
from fastapi.testclient import TestClient

from console import app as console_app
from console import chain


@pytest.fixture(autouse=True)
def _isolated_catalogue(tmp_path, monkeypatch):
    """Temp catalogue for every test; otherwise the suite writes into the real `data/catalogue.db`."""
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
    """Temp references dir for every test: `/reset` deletes real `.npz` files, which can't be recreated."""
    # The `/state` cache is module-level; clear it so tests don't share a gate.
    from console.app import invalidate_state

    invalidate_state()

    references = tmp_path / ".genesis-references"  # dot: hidden from `/browse`
    references.mkdir()
    monkeypatch.setenv("GENESIS_REFERENCES", str(references))
    # The module constant was resolved at import, so patch it too.
    monkeypatch.setattr("scoring.app.REFERENCES", references)
    yield
    invalidate_state()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(
        console_app, "_bodies", lambda: {"b1": {"name": "r10", "planes": {}, "meta": {}}}
    )
    return TestClient(console_app.app)


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


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
    monkeypatch.delenv("DEPLOYER_ADDRESS", raising=False)
    monkeypatch.setattr(chain, "status", lambda: {
        "chainId": 11155111, "onExpectedChain": True, "blockNumber": 1, "registry": "0xr",
    })
    monkeypatch.setattr(chain, "block_age_seconds", lambda: 5)
    body = client.get("/state").json()
    gas = next(c for c in body["checks"] if c["check"] == "deployer gas")
    assert gas["go"] is False and "DEPLOYER_ADDRESS" in gas["remedy"]


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

    r = client.post("/register-body", data={"name": "r10"})
    assert r.status_code == 409
    assert "0xsomeone" in r.json()["detail"]


def test_register_body_refuses_a_malformed_camera_commitment(client, monkeypatch):
    """Refused before gas: `cast` would pad short hex into an unreproducible commitment."""
    monkeypatch.setattr(
        console_app, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )
    from console import registry as reg

    monkeypatch.setattr(reg, "_bodies", console_app._bodies)
    monkeypatch.setattr(chain, "body", lambda b: None)
    sent = []
    monkeypatch.setattr(reg, "cast_send", lambda args: sent.append(args) or {})

    r = client.post("/register-body", data={"name": "r10", "body_commitment": "0xabc"})
    assert r.status_code == 422
    assert sent == []


def test_register_body_sends_the_camera_commitment_or_zero(client, monkeypatch):
    monkeypatch.setattr(
        console_app, "_bodies",
        lambda: {"b1": {"name": "r10", "commitment": "cc", "planes": {}, "meta": {}}},
    )
    from console import registry as reg

    monkeypatch.setattr(reg, "_bodies", console_app._bodies)
    monkeypatch.setattr(chain, "body", lambda b: None)
    sent = []
    monkeypatch.setattr(reg, "cast_send", lambda args: sent.append(args) or {"txHash": "0x1"})

    camera = "AB" * 32
    r = client.post("/register-body", data={"name": "r10", "body_commitment": "0x" + camera})
    assert r.status_code == 200
    assert sent[-1][-1] == "0x" + camera.lower()
    assert r.json()["bodyCommitment"] == "0x" + camera.lower()

    client.post("/register-body", data={"name": "r10"})
    assert sent[-1][-1] == "0x" + "0" * 64


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


def test_a_keystore_signs_without_the_key_on_argv(tmp_path, monkeypatch):
    from console import registry as reg

    password = tmp_path / "pass"
    password.write_text("pw")
    monkeypatch.setenv("DEPLOYER_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.setenv("DEPLOYER_ACCOUNT", "genesis-deployer")
    monkeypatch.setenv("DEPLOYER_PASSWORD_FILE", str(password))
    wallet, secret = reg._signer()
    assert wallet == ["--account", "genesis-deployer", "--password-file", str(password)]
    assert secret is None

    monkeypatch.setenv("DEPLOYER_PASSWORD_FILE", str(tmp_path / "missing"))
    with pytest.raises(Exception):
        reg._signer()

    monkeypatch.delenv("DEPLOYER_ACCOUNT")
    wallet, secret = reg._signer()
    assert wallet == ["--private-key", "0x" + "11" * 32] and secret == "0x" + "11" * 32


def test_a_builder_code_rides_on_every_transaction_and_its_absence_changes_nothing(monkeypatch):
    """Base attributes by the calldata's tail; with no code, `cast send` gets its old argv."""
    import subprocess

    from fastapi import HTTPException

    from console import registry as reg

    runs = []

    class Done:
        returncode = 0
        stdout = '{"status": "0x1", "transactionHash": "0xabc", "blockNumber": "0x2"}'
        stderr = ""

    def run(command, **kwargs):
        runs.append(command)
        done = Done()
        if command[1] == "calldata":
            done.stdout = "0x5e8b2a9e\n"
        return done

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("DEPLOYER_PRIVATE_KEY", "0x" + "11" * 32)
    monkeypatch.setattr(reg.chain, "REGISTRY", "0xreg")

    monkeypatch.setattr(reg, "BUILDER_CODE", "")
    reg.cast_send(["resetAll()"])
    assert runs == [["cast", "send", "0xreg", "resetAll()", *runs[0][4:]]]

    runs.clear()
    monkeypatch.setattr(reg, "BUILDER_CODE", "bc_a1b2c3d4")
    reg.cast_send(["resetAll()"])
    assert runs[0] == ["cast", "calldata", "resetAll()"]
    assert runs[1][3] == "0x5e8b2a9e" + "62635f6131623263336434" + "0b" + "00" + "8021" * 8

    monkeypatch.setattr(reg, "BUILDER_CODE", "bc_émoji")
    with pytest.raises(HTTPException) as refused:
        reg.cast_send(["resetAll()"])
    assert refused.value.status_code == 503


def test_the_builder_code_suffix_matches_the_erc_8021_test_vector():
    """eip.tools/eip/8021's own worked example, so the encoding is pinned to the spec."""
    from console import registry as reg

    assert reg._erc8021_suffix("baseapp") == "62617365617070" + "07" + "00" + "8021" * 8


def test_a_camera_comes_back_from_its_fingerprint_file(client, tmp_path, monkeypatch):
    import io
    import numpy as np
    from fingerprint import prnu
    from scoring.app import _bodies

    monkeypatch.setenv("GENESIS_REFERENCES", str(tmp_path / "refs"))
    monkeypatch.setattr("scoring.app.REFERENCES", tmp_path / "refs")
    monkeypatch.setattr(console_app, "_bodies", _bodies)  # the real one, not the fixture's stub
    _bodies.cache_clear()
    monkeypatch.setattr("console.chain.body", lambda body_id: None)

    src = tmp_path / "my-camera.npz"
    prnu.save_fingerprint(src, {0: np.ones((8, 8), np.float32)}, {"frames": 40})
    first = client.post("/bodies/import", files={"file": ("my-camera.npz", src.read_bytes())})
    assert first.status_code == 200, first.text
    assert first.json()["name"] == "my-camera" and first.json()["registered"] is False
    assert (tmp_path / "refs" / "my-camera.npz").exists()

    again = client.post("/bodies/import", files={"file": ("copy.npz", src.read_bytes())})
    assert again.status_code == 409

    junk = client.post("/bodies/import", files={"file": ("x.npz", io.BytesIO(b"not a fingerprint"))})
    assert junk.status_code == 422
    _bodies.cache_clear()


def test_the_hmac_key_becomes_bytes():
    """The env var is str; hmac.new needs bytes."""
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
    """The 8-byte pHash must be padded to bytes32, or `cast` fails with a bare "parser error"."""
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
    """Gate A wants 40-50 frames, so the picker shows counts."""
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
    """Paths and captions are local-only (see `console/catalogue.py`)."""
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
    """Same pixels from a new folder update the path, not add a row."""
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


def test_registration_scores_with_the_shared_scorer(monkeypatch):
    """Registration uses `_score_against`, which core/'s Rust port is parity-tested against.

    `build_record`'s own scoring is aligned-only and fails on portrait frames.
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
    """Else session frames count as belonging to no body."""
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


def test_enrolment_refuses_a_folder_holding_two_cameras(monkeypatch):
    """Averaging two sensors silently yields a K belonging to neither (`docs/gates.md`)."""
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
    """The gate is the contract's `testMode()`, not a local flag."""
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
    """A wipe that leaves the references behind is not a clean slate."""
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
    """Separable: the chain wipe is reversible by re-registering; deleting K is not."""
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
    """The scorer is a separate process; it must notice the directory change without a restart."""
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
    """Enrolled is not registered; refuse before a minute of scoring ends in a revert."""
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
    """A registration proves who claimed an image and when, **not where the light fell** (`docs/adversarial.md`)."""
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
                    # Negations are allowed: copy may say what is *not* claimed.
                    if re.search(r"\b(not|never|does not|nor)\b", context, re.I):
                        continue
                    offences.append(f"{source}:{line}: {context[:100]}")
    assert not offences, "user-facing copy claims origin:\n" + "\n".join(offences)


def test_reset_clears_the_archive(client, monkeypatch, tmp_path):
    """The archive describes the chain, so it cannot outlive a wipe."""
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
    """Frames uploaded from the OS file dialog are staged and enrolled."""
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
    """Developed JPEGs have had the fingerprint denoised away."""
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
    """Canary: fails if `_isolated_references` stops applying."""
    import os
    from pathlib import Path

    live = Path("data/references").resolve()
    used = Path(os.environ["GENESIS_REFERENCES"]).resolve()
    assert used != live, "GENESIS_REFERENCES points at the real references directory"
    assert not str(used).startswith(str(live)), f"{used} is inside {live}"


def test_the_desktop_app_s_webview_can_preflight_across_the_private_network(client):
    """WKWebView sends Private Network Access preflights to loopback and fails silently
    ("Load failed") if refused; Starlette refuses by default without `allow_private_network`.
    """
    response = client.options(
        "/state",
        headers={
            "Origin": "http://127.0.0.1:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-private-network"] == "true"


# --- what core/ needs from this machine ------------------------------------


@pytest.fixture
def enrolled(tmp_path, monkeypatch):
    """One enrolled body on disk, as `_bodies` would find it."""
    import scoring.app as scoring_app

    (scoring_app.REFERENCES / "r10.npz").write_bytes(b"K bytes")
    monkeypatch.setattr(
        console_app, "_bodies",
        lambda: {"ab" * 32: {"name": "r10", "planes": {}, "meta": {"crop": 512}}},
    )
    return TestClient(console_app.app)


def test_bodies_lists_what_core_needs_and_no_fingerprint(enrolled):
    assert enrolled.get("/bodies").json() == [{"id": "ab" * 32, "name": "r10", "crop": 512}]


def test_a_fingerprint_is_served_from_the_enrolled_directory(enrolled):
    response = enrolled.get(f"/bodies/0x{'ab' * 32}/fingerprint")
    assert response.status_code == 200
    assert response.content == b"K bytes"
    assert enrolled.get(f"/bodies/{'cd' * 32}/fingerprint").status_code == 404


def test_a_fingerprint_is_readable_only_from_the_apps_own_origins(enrolled):
    """CORS stops any other open web page from reading K off loopback."""
    path = f"/bodies/{'ab' * 32}/fingerprint"
    stranger = enrolled.get(path, headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in stranger.headers
    ours = enrolled.get(path, headers={"Origin": "http://127.0.0.1:5173"})
    assert ours.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"


def test_raw_develop_sends_the_pixels_python_hashes(client, monkeypatch):
    from PIL import Image

    monkeypatch.setattr(console_app.stress, "develop", lambda p: Image.new("RGB", (3, 2), (1, 2, 3)))
    response = client.post(
        "/raw/develop",
        files={"file": ("IMG_0001.CR3", b"raw", "image/x-raw")},
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    assert response.status_code == 200
    assert response.content == bytes([1, 2, 3] * 6)
    assert (response.headers["x-width"], response.headers["x-height"]) == ("3", "2")
    # A browser hides custom headers from cross-origin script unless exposed.
    exposed = response.headers["access-control-expose-headers"].lower()
    assert "x-width" in exposed and "x-height" in exposed


def test_raw_endpoints_refuse_what_core_decodes_itself(client):
    for route in ("/raw/develop", "/raw/planes"):
        response = client.post(route, files={"file": ("photo.jpg", b"x", "image/jpeg")})
        assert response.status_code == 400


def test_raw_planes_are_cut_to_the_bodys_crop(client, monkeypatch):
    import io

    import numpy as np

    seen = []

    def planes(path, crop=None):
        seen.append(crop)
        return {c: np.full((2, 2), c, dtype=np.float32) for c in range(4)}

    monkeypatch.setattr(console_app.prnu, "load_raw_planes", planes)
    for crop, want in (("512", 512), ("none", None)):
        response = client.post("/raw/planes", files={"file": ("a.CR3", b"raw")}, data={"crop": crop})
        assert response.status_code == 200
        with np.load(io.BytesIO(response.content)) as npz:
            assert sorted(npz.files) == ["plane_0", "plane_1", "plane_2", "plane_3"]
    assert seen == [512, None]


def test_the_rpc_proxy_is_read_only(client):
    for method in ("eth_sendRawTransaction", "eth_sendTransaction", "personal_sign"):
        response = client.post("/rpc", json={"jsonrpc": "2.0", "id": 1, "method": method, "params": []})
        assert response.status_code == 403, method
    # A batch is refused whole if any call in it writes.
    batch = [{"method": "eth_call"}, {"method": "eth_sendRawTransaction"}]
    assert client.post("/rpc", json=batch).status_code == 403


def test_the_rpc_proxy_forwards_reads_to_the_configured_node(client, monkeypatch):
    import httpx

    sent = []

    async def post(self, url, json=None, **_):
        sent.append((url, json))
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "0x14a34"})

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(chain, "RPC_URL", "https://node.example/v2/SECRET")
    call = {"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}

    assert client.post("/rpc", json=call).json()["result"] == "0x14a34"
    assert sent == [("https://node.example/v2/SECRET", call)]


def test_the_subgraph_proxy_needs_an_index(client, monkeypatch):
    from console import subgraph as sg

    monkeypatch.setattr(sg, "SUBGRAPH_URL", "")
    assert client.post("/subgraph", json={"query": "{ images { id } }"}).status_code == 503


def test_state_tells_core_how_to_read_the_chain_without_any_url(client, monkeypatch):
    """The RPC URL can carry a key; the webview gets /rpc and never the URL."""
    from console import subgraph as sg

    monkeypatch.setattr(chain, "status", lambda: {"chainId": 84532, "onExpectedChain": True, "registry": "0xreg", "blockNumber": 1})
    monkeypatch.setattr(chain, "block_age_seconds", lambda: 2)
    monkeypatch.setattr(chain, "RPC_URL", "https://node.example/v2/SECRET")
    monkeypatch.setattr(sg, "SUBGRAPH_URL", "https://gateway.example/api/SECRET/subgraphs/id/x")

    body = client.get("/state").json()
    assert body["verify"]["chain"] == chain.CHAIN_KEY
    assert body["verify"]["subgraph"] is True
    assert "SECRET" not in json.dumps(body["verify"])


def test_the_console_no_longer_computes_a_verdict(client):
    """Verification runs in core/, the code the web page runs too."""
    for route in ("/verify", "/verify/stream"):
        assert client.post(route, files={"file": ("x.jpg", b"x")}).status_code in (404, 405)



def test_catalogue_sync_follows_the_chain():
    """Chain rows arrive and win; captions stay; missing rows go unless newer than the index."""
    from console import catalogue as cat

    body = "0xb0"
    cat.record_image(image_hash="0xaa", body_id=body, body_name="r10", pce=1.0,
                     registered_at=1, block_number=90, file_name="kept.jpg", description="")
    cat.describe("0xaa", "my caption")
    cat.record_image(image_hash="0xdd", body_id=body, body_name="r10", pce=5.0,
                     registered_at=1, block_number=50, description="")    # testnet leftover
    cat.record_image(image_hash="0xee", body_id=body, body_name="r10", pce=5.0,
                     registered_at=1, block_number=120, description="")   # not indexed yet
    cat.record_image(image_hash="0xff", body_id="0xother", body_name="x", pce=5.0,
                     registered_at=1, block_number=50, description="")    # another camera

    chain_images = [
        {"imageHash": "0xAA", "perceptualHash": "0x01", "pceScore": "1148",
         "registeredAt": "1000", "body": {"id": body}},
        {"imageHash": "0xbb", "perceptualHash": "0x02", "pceScore": "900",
         "registeredAt": "2000", "body": {"id": body}},
    ]
    cat.sync({body: "r10"}, chain_images, indexed_block=100)

    rows = {r["image_hash"]: r for r in cat.listing()}
    assert set(rows) == {"0xaa", "0xbb", "0xee", "0xff"}
    assert rows["0xaa"]["pce"] == 1148.0 and rows["0xaa"]["registered_at"] == 1000
    assert rows["0xaa"]["description"] == "my caption" and rows["0xaa"]["file_name"] == "kept.jpg"
    assert rows["0xbb"]["body_name"] == "r10"

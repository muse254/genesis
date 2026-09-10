"""Confidential scoring tests.

Three things are worth testing here and the rest is arithmetic already covered
by `fingerprint/`:

1. **The payload never contains K.** The whole design rests on it, and a
   regression would be silent and unrecoverable — one leaked reference is a
   forgery kit (`docs/claims.md`).
2. **The two backends agree.** A flag that changed the answer would make the
   local path a different product rather than a stand-in for the CRE one.
3. **The local backend cannot pass itself off as attested.** That is the
   drift `docs/security.md` warns about, one level up.

The CRE backend needs the CLI and takes about half a minute, so it is marked
and skipped unless `GENESIS_TEST_CRE=1`. The rest runs on the synthetic
sensor and needs no camera.
"""

from __future__ import annotations

import base64
import json
import os
import shutil

import numpy as np
import pytest

from cre import backend, enclave, payload as payload_mod
from fingerprint import prnu


@pytest.fixture(scope="module")
def synthetic():
    """One synthetic body, a reference, and a probe exposed on it."""
    from fingerprint import validate_synthetic as sim

    body = {c: sim.simulate_sensor(seed=10 + c) for c in range(4)}
    frames = [
        {c: sim.simulate_exposure(k, seed=200 + 10 * n) for c, k in body.items()}
        for n in range(sim.FRAMES)
    ]
    reference = prnu.postprocess(prnu.estimate_fingerprint(frames))
    probe = {c: sim.simulate_exposure(k, seed=9999) for c, k in body.items()}
    foreign = {c: sim.simulate_sensor(seed=770 + c) for c in range(4)}
    stranger = {c: sim.simulate_exposure(k, seed=4242) for c, k in foreign.items()}
    size = min(payload_mod.PLANE_SIZE, min(a.shape[0] for a in reference.values()))
    return {"reference": reference, "probe": probe, "stranger": stranger, "size": size}


# --- what leaves the machine ----------------------------------------------


def test_payload_carries_no_fingerprint(synthetic):
    """The one that matters. K must not appear in the payload, in any plane.

    Checked by correlation rather than by byte equality: a payload that
    happened to carry a scaled or rounded K would pass an equality check and
    still be a forgery kit.
    """
    payload = payload_mod.build_payload(
        synthetic["probe"], "synthetic", size=synthetic["size"]
    )
    blob = json.dumps(payload).encode()

    for c, k in synthetic["reference"].items():
        cropped = prnu._centre_crop(k, synthetic["size"])
        assert base64.b64encode(payload_mod.quantise(cropped).data) not in blob

        for field in ("residual", "plane"):
            sent = payload_mod.Quantised.from_json(
                payload["planes"][str(c)][field]
            ).restore(synthetic["size"])
            # A residual correlates with K only through the image; a payload
            # that carried K itself would sit near 1.
            corr = abs(np.corrcoef(sent.ravel(), cropped.ravel())[0, 1])
            assert corr < 0.5, f"plane {c} {field} correlates with K at {corr:.3f}"


def test_payload_is_only_the_crop(synthetic):
    """Nothing outside the centre crop travels, whatever the frame's size."""
    payload = payload_mod.build_payload(
        synthetic["probe"], "synthetic", size=synthetic["size"]
    )
    for c in payload_mod.PLANES:
        for field in ("residual", "plane"):
            part = payload_mod.Quantised.from_json(payload["planes"][str(c)][field])
            assert len(part.data) == synthetic["size"] ** 2


def test_secret_fits_a_vault_secret(synthetic):
    """K has to fit `WASMSecretsSizeLimit`, per plane, base64 and all.

    1mb is the measured limit from `cre workflow limits export` on v1.32.0.
    If PLANE_SIZE is ever raised this test is the thing that objects.
    """
    secret = payload_mod.build_secret(synthetic["reference"], size=synthetic["size"])
    for plane, blob in secret.items():
        encoded = len(json.dumps(blob).encode())
        assert encoded < 1_000_000, f"plane {plane} secret is {encoded} bytes"


# --- the two backends agree ------------------------------------------------


def test_enclave_matches_the_shipped_scorer(synthetic):
    """The enclave arithmetic is `prnu.score` on the same cropped inputs.

    Not an identity: the shipped scorer extracts the residual from the plane
    it is given, and here it arrives quantised to int8. The measured cost of
    that is under half a percent (`docs/cre.md`), so the two are compared as
    ratios rather than for equality.
    """
    size = synthetic["size"]
    cropped_probe = {c: prnu._centre_crop(a, size) for c, a in synthetic["probe"].items()}
    cropped_ref = {c: prnu._centre_crop(a, size) for c, a in synthetic["reference"].items()}
    direct = prnu.score(cropped_probe, cropped_ref)

    payload = payload_mod.build_payload(synthetic["probe"], "synthetic", size=size)
    secret = payload_mod.build_secret(synthetic["reference"], size=size)
    through_enclave = enclave.correlate(payload, secret)

    assert through_enclave == pytest.approx(direct, rel=0.01)


def test_a_stranger_does_not_match(synthetic):
    """A different sensor lands in the null, through the same path."""
    result = backend.score(
        synthetic["stranger"], synthetic["reference"], "synthetic",
        backend="local", size=synthetic["size"],
    )
    assert not result.match
    assert result.pce < prnu.PCE_THRESHOLD


def test_the_digest_binds_the_score_to_the_probe(synthetic):
    """Two different probes must not produce the same attestation bytes."""
    mine = payload_mod.build_payload(synthetic["probe"], "synthetic", size=synthetic["size"])
    theirs = payload_mod.build_payload(
        synthetic["stranger"], "synthetic", size=synthetic["size"]
    )
    assert payload_mod.payload_digest(mine) != payload_mod.payload_digest(theirs)
    assert payload_mod.attestation_bytes(mine, 1.0) != payload_mod.attestation_bytes(theirs, 1.0)


# --- the flag, and what it may not claim -----------------------------------


def test_local_is_never_attested(synthetic, monkeypatch):
    """A self-signed score from the machine holding K closes nothing.

    If this ever returns True, a demo can show a rehearsal and call it the
    guarantee. That is the failure this file exists to prevent.
    """
    monkeypatch.setenv("GENESIS_ATTESTATION_KEY", "01" * 32)
    result = backend.score(
        synthetic["probe"], synthetic["reference"], "synthetic",
        backend="local", size=synthetic["size"],
    )
    assert result.attested is False
    assert result.signature is not None
    assert "closes nothing" in result.trust


def test_local_signature_recovers(synthetic, monkeypatch):
    """The verifier half is exercised: a signature nobody checks is a field."""
    monkeypatch.setenv("GENESIS_ATTESTATION_KEY", "01" * 32)
    payload = payload_mod.build_payload(
        synthetic["probe"], "synthetic", size=synthetic["size"]
    )
    result = backend.score(
        synthetic["probe"], synthetic["reference"], "synthetic",
        backend="local", size=synthetic["size"],
    )
    assert backend.verify_local(payload, result) == result.signer


def test_the_flag_selects(monkeypatch):
    monkeypatch.setenv("GENESIS_CONFIDENTIAL_BACKEND", "cre")
    assert backend.selected() == "cre"
    monkeypatch.delenv("GENESIS_CONFIDENTIAL_BACKEND")
    assert backend.selected() == "local"
    monkeypatch.setenv("GENESIS_CONFIDENTIAL_BACKEND", "enclave")
    with pytest.raises(ValueError, match="expected one of"):
        backend.selected()


# --- the CRE path, when the CLI is there -----------------------------------


@pytest.mark.skipif(
    os.environ.get("GENESIS_TEST_CRE") != "1",
    reason="needs the CRE CLI and ~30s; set GENESIS_TEST_CRE=1",
)
def test_cre_and_local_agree(synthetic):
    """The whole reason both backends exist: switching the flag must not
    change the number.

    A radix-2 Cooley-Tukey in the enclave and numpy's pocketfft accumulate
    differently, so this compares to the thousandth the attestation actually
    carries rather than pretending to bit-exactness.
    """
    if not backend.CRE_BIN.exists() or shutil.which("bun") is None:
        pytest.skip("CRE CLI or bun not installed")

    kwargs = dict(body_id="synthetic", size=synthetic["size"])
    local = backend.score(synthetic["probe"], synthetic["reference"], backend="local", **kwargs)
    remote = backend.score(synthetic["probe"], synthetic["reference"], backend="cre", **kwargs)

    assert payload_mod.pce_millis(remote.pce) == payload_mod.pce_millis(local.pce)
    assert remote.payload_digest == local.payload_digest
    assert remote.attested is False  # simulation is not an enclave either
    assert "not a real enclave" in remote.trust

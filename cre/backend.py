"""Two ways to get a score computed away from the caller, behind one flag.

    GENESIS_CONFIDENTIAL_BACKEND=cre     a real Chainlink confidential workflow
    GENESIS_CONFIDENTIAL_BACKEND=local   the same arithmetic, in this process

`local` exists because Confidential Workflows is private beta and deployment
waits on an approval with unknown turnaround (`docs/e2e-checklist.md` sec.10).
It keeps the demo standing if the CRE path fails on the day.

**The two are not the same guarantee, and this module will not let a caller
pretend otherwise.** Every result carries `attested` and a `trust` sentence,
and there are exactly three states:

    local              computed in this process, signed by a key on the same
                       machine that holds K. Closes nothing. It reproduces
                       the *shape* of an attestation, and the whole point of
                       an attestation is that it comes from somewhere else.
    cre, simulated     computed by the CRE simulator, which the CLI itself
                       warns "is not a real TEE". The report is built, not
                       DON-signed. Closer, still not the guarantee.
    cre, deployed      the real one: Vault DON releases K only into an
                       attested enclave, and consensus signs the score.
                       Needs enrolment. Not reachable yet.

Only the third removes the scorer as a trusted party. A demo that showed the
first and described the third would be the exact drift `docs/security.md`
warns about, one level up.

And none of the three helps against forgery. An enclave scores a planted
fingerprint faithfully and signs it; confidential compute protects the
reference from the verifier, and the attack happens before the pixels arrive.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from cre import enclave, payload as payload_mod
from fingerprint import prnu

#: Where the CRE project lives. The workflow is a sibling of this file so
#: that the TypeScript the enclave runs and the Python it must agree with
#: sit next to each other and get reviewed together.
WORKFLOW_ROOT = Path(__file__).parent / "workflow"

#: The CLI is installed per-user, not on PATH by default.
CRE_BIN = Path(os.environ.get("CRE_BIN", Path.home() / ".cre" / "bin" / "cre"))

BACKENDS = ("local", "cre")

TRUST = {
    "local": (
        "self-signed in the scoring process, on the same machine that holds K. "
        "Reproduces the shape of an attestation and closes nothing."
    ),
    "cre-simulated": (
        "computed by the CRE simulator, which is not a real enclave. The report "
        "is built but not DON-signed."
    ),
    "cre-deployed": (
        "computed in an attested enclave; K released by the Vault DON and never "
        "held by the scorer or a node operator."
    ),
}


@dataclass(frozen=True)
class ConfidentialScore:
    """One verdict, and an unambiguous statement of what produced it."""

    pce: float
    match: bool
    threshold: float
    backend: str
    #: True only for a score from a deployed confidential workflow. A caller
    #: that gates on anything else is gating on a rehearsal.
    attested: bool
    trust: str
    payload_digest: str
    signature: str | None = None
    signer: str | None = None

    def to_json(self) -> dict:
        return asdict(self)


def selected() -> str:
    """The configured backend, defaulting to the one that always works."""
    choice = os.environ.get("GENESIS_CONFIDENTIAL_BACKEND", "local").strip().lower()
    if choice not in BACKENDS:
        raise ValueError(
            f"GENESIS_CONFIDENTIAL_BACKEND={choice!r}; expected one of {', '.join(BACKENDS)}"
        )
    return choice


def score(planes: dict, reference: dict, body_id: str, backend: str | None = None,
          size: int = payload_mod.PLANE_SIZE) -> ConfidentialScore:
    """Score a probe against a reference, wherever the flag says to compute it.

    The client-side half is identical either way -- `build_payload` crops and
    extracts the residual here, before anything leaves -- so switching the
    flag changes where the correlation happens and nothing about what is sent.
    """
    backend = backend or selected()
    payload = payload_mod.build_payload(planes, body_id, size=size)
    secret = payload_mod.build_secret(reference, size=size)
    return _run_local(payload, secret) if backend == "local" else _run_cre(payload, secret)


def _finish(payload: dict, pce: float, backend: str, mode: str,
            signature: bytes | None, signer: str | None) -> ConfidentialScore:
    return ConfidentialScore(
        pce=pce,
        match=pce >= prnu.PCE_THRESHOLD,
        threshold=prnu.PCE_THRESHOLD,
        backend=backend,
        attested=(mode == "cre-deployed"),
        trust=TRUST[mode],
        payload_digest=payload_mod.payload_digest(payload).hex(),
        signature=signature.hex() if signature else None,
        signer=signer,
    )


# --- local -----------------------------------------------------------------


def _run_local(payload: dict, secret: dict) -> ConfidentialScore:
    """The same arithmetic, in this process.

    Signs when `GENESIS_ATTESTATION_KEY` is set, so the plumbing a verifier
    would exercise is real and testable. The signature is still worth nothing
    as an attestation -- see the module docstring -- which is why `attested`
    is False regardless of whether one was produced.
    """
    pce = enclave.correlate(payload, secret)
    signature = signer = None
    raw = os.environ.get("GENESIS_ATTESTATION_KEY", "").strip()
    if raw:
        from eth_keys import keys

        key = keys.PrivateKey(bytes.fromhex(raw.removeprefix("0x")))
        message = payload_mod.attestation_bytes(payload, pce)
        signature = key.sign_msg(message).to_bytes()
        signer = key.public_key.to_checksum_address()
    return _finish(payload, pce, "local", "local", signature, signer)


def verify_local(payload: dict, result: ConfidentialScore) -> str:
    """Recover the address that signed a local result, or raise.

    Exists so the verifier half is exercised too: a signature nobody ever
    checks is a field, not a mechanism.
    """
    from eth_keys import keys

    sig = keys.Signature(bytes.fromhex(result.signature))
    message = payload_mod.attestation_bytes(payload, result.pce)
    return sig.recover_public_key_from_msg(message).to_checksum_address()


# --- cre -------------------------------------------------------------------


def _run_cre(payload: dict, secret: dict) -> ConfidentialScore:
    """Hand the payload to `cre workflow simulate` and read the score back.

    Simulation rather than deployment because deployment needs private-beta
    enrolment. What this does exercise is real: the CRE compiler, the TEE
    handler constraint, `runtime.getSecret` inside the enclave, and the
    report shape crossing back through `usingTheDons()`.

    K is written to a gitignored `.env` under the workflow directory for the
    length of one run and deleted after, because the CLI takes secret values
    from the environment. It is a cropped, quantised K and it never leaves
    this machine -- but it is still K, so it is cleaned up in a `finally`.
    """
    if not CRE_BIN.exists():
        raise RuntimeError(
            f"no CRE CLI at {CRE_BIN}. Install it, or set GENESIS_CONFIDENTIAL_BACKEND=local"
        )

    env_path = WORKFLOW_ROOT / ".env"
    with tempfile.TemporaryDirectory() as scratch:
        payload_path = Path(scratch) / "payload.json"
        payload_path.write_text(json.dumps(payload))
        try:
            env_path.write_text(_secret_env(secret))
            completed = subprocess.run(
                [str(CRE_BIN), "workflow", "simulate", "genesis",
                 "--target", "staging-settings", "--non-interactive",
                 "--trigger-index", "0", "--http-payload", str(payload_path)],
                cwd=WORKFLOW_ROOT, capture_output=True, text=True, timeout=600,
            )
        finally:
            env_path.unlink(missing_ok=True)

    result = _parse_simulation(completed)
    digest = payload_mod.payload_digest(payload).hex()
    # viem's `sha256` returns a 0x-prefixed hex string; Python's does not.
    if result["digest"].removeprefix("0x") != digest:
        # The enclave hashes what it was actually handed. A mismatch means the
        # score belongs to a different probe, which is the one thing a signed
        # score must never be allowed to be.
        raise RuntimeError(f"enclave scored a different payload: {result['digest']} != {digest}")

    return _finish(payload, result["pceMillis"] / 1000.0, "cre", "cre-simulated", None, None)


def _secret_env(secret: dict) -> str:
    """K as the CLI wants it: one environment variable per CFA plane.

    Split per plane because the CLI passes these to the compiler as process
    arguments and `ARG_MAX` is 1,048,576 on macOS -- measured, not assumed.
    """
    lines = []
    for c in payload_mod.PLANES:
        blob = secret.get(str(c))
        if blob is None:
            continue
        lines.append(f"SECRET_K{c}={json.dumps(blob, separators=(',', ':'))}")
    return "\n".join(lines) + "\n"


def _parse_simulation(completed: subprocess.CompletedProcess) -> dict:
    """Pull the workflow's return value out of the simulator's output.

    The CLI prints it as a JSON-encoded string after a banner. Parsed rather
    than regexed out, so a change in the banner is a loud failure and not a
    silently wrong score.
    """
    if completed.returncode != 0:
        raise RuntimeError(f"cre workflow simulate failed:\n{completed.stdout}\n{completed.stderr}")

    marker = "Workflow Simulation Result:"
    if marker not in completed.stdout:
        raise RuntimeError(f"no simulation result in output:\n{completed.stdout}")

    tail = completed.stdout.split(marker, 1)[1].strip()
    line = next((ln for ln in tail.splitlines() if ln.strip().startswith('"')), None)
    if line is None:
        raise RuntimeError(f"no result value after the banner:\n{completed.stdout}")

    return json.loads(json.loads(line.strip()))

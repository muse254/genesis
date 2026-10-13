"""The endpoints that sign, kept in their own module so the boundary is visible.

`registerImage`'s owner check is the one mechanism no attack in
`docs/adversarial.md` got past; every claim sits downstream of a transaction
sent from here. Transactions go through `cast` (same path as `local-e2e.sh`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from console import catalogue, chain, jobs
from fingerprint import prnu
from ingest import merkle, record
from scoring.app import _bodies, _score_against

router = APIRouter()

CAST_TIMEOUT = 180



#: Owner named in the metadata commitment. `ENS_PARENT_NAME` fallback keeps old `.env`s committing the same string.
OWNER = os.environ.get("GENESIS_OWNER") or os.environ.get("ENS_PARENT_NAME")

def _hmac_key() -> bytes | None:
    """`METADATA_HMAC_KEY` as bytes: hex if it parses (`.env`), else UTF-8 (`local-e2e.sh`)."""
    raw = os.environ.get("METADATA_HMAC_KEY", "").strip()
    if not raw:
        return None
    try:
        return bytes.fromhex(raw.removeprefix("0x"))
    except ValueError:
        return raw.encode("utf-8")


def _key() -> str:
    key = os.environ.get("DEPLOYER_PRIVATE_KEY", "").strip()
    if not key:
        raise HTTPException(503, "DEPLOYER_PRIVATE_KEY is not set; the console cannot sign")
    return key


def _signer() -> tuple[list[str], str | None]:
    """Wallet flags for `cast send`, and the secret to redact from errors.

    A Foundry keystore (`DEPLOYER_ACCOUNT` + `DEPLOYER_PASSWORD_FILE`) wins: the key
    never reaches argv. `DEPLOYER_PRIVATE_KEY` is the fallback.
    """
    account = os.environ.get("DEPLOYER_ACCOUNT", "").strip()
    if account:
        password_file = os.path.expanduser(os.environ.get("DEPLOYER_PASSWORD_FILE", "").strip())
        if not password_file or not os.path.isfile(password_file):
            raise HTTPException(
                503,
                "DEPLOYER_ACCOUNT is set but DEPLOYER_PASSWORD_FILE is not a readable file; "
                "the console cannot unlock the keystore",
            )
        return ["--account", account, "--password-file", password_file], None
    key = _key()
    return ["--private-key", key], key


def _invalidate_state() -> None:
    """Drop the cached `/state` gate after anything that changes it."""
    from console.app import invalidate_state

    invalidate_state()


def cast_send(args: list[str]) -> dict:
    """One transaction and its receipt fields. Raises on failure, so a failed registration can't be reported as one."""
    if not chain.REGISTRY:
        raise HTTPException(503, "REGISTRY_ADDRESS is not set")

    # Without a keystore the key goes on argv (`--interactive` needs a TTY), so it
    # is visible in `ps` for one transaction. OK for a localhost demo driver
    # (`docs/security.md`); this must never become hosted.
    wallet, secret = _signer()
    command = [
        "cast", "send", chain.REGISTRY, *args,
        "--rpc-url", chain.RPC_URL,
        *wallet,
        "--json",
    ]
    try:
        done = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=CAST_TIMEOUT,
            env={**os.environ, "FOUNDRY_DISABLE_NIGHTLY_WARNING": "1"},
        )
    except FileNotFoundError:
        raise HTTPException(503, "cast not found; Foundry is required (see README)")
    except subprocess.TimeoutExpired:
        raise HTTPException(504, f"cast timed out after {CAST_TIMEOUT}s")

    if done.returncode != 0:
        # Translate known reverts into plain words instead of hex.
        for phrase, message in (
            ("image already registered",
             "This photograph is already registered. Registering the same pixels "
             "twice is impossible by design -- verify it instead."),
            ("body already registered",
             "This body is already registered. The slot is claimed and cannot be "
             "re-taken."),
            ("below threshold",
             "The pixels do not clear the threshold; nothing was signed."),
            ("unknown body",
             "The registry has no record of this body. Register the body first "
             "(demo step 2a) -- after a wipe the enrolled fingerprint survives but "
             "its registration does not."),
        ):
            if phrase in done.stderr:
                raise HTTPException(409, message)

        # stderr can echo the key; redact it.
        leaked = (done.stderr.replace(secret, "<key>") if secret else done.stderr).strip()
        raise HTTPException(502, f"transaction failed: {leaked[:400]}")

    import json

    try:
        receipt = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise HTTPException(502, f"unparseable receipt: {done.stdout.strip()[:200]}")

    if str(receipt.get("status", "")).lower() not in ("0x1", "1", "true"):
        raise HTTPException(502, f"transaction reverted: {receipt.get('transactionHash')}")

    tx_hash = receipt.get("transactionHash", "")
    return {
        "txHash": tx_hash,
        "blockNumber": int(str(receipt.get("blockNumber", "0")), 0),
        "explorerUrl": chain.explorer_url(tx_hash, "tx"),
        "links": chain.reference_links(tx_hash),
    }


@router.post("/register-body")
async def register_body(name: str = Form(...), body_commitment: str = Form("")) -> dict:
    """Demo step 2a. Do it first: anyone with a leaked K can claim the slot forever (`docs/security.md`)."""
    bodies = {b["name"]: (body_id, b) for body_id, b in _bodies().items()}
    if name not in bodies:
        raise HTTPException(404, f"no enrolled body {name}")
    body_id, body = bodies[name]

    existing = chain.body("0x" + body_id)
    if existing:
        raise HTTPException(
            409,
            f"body already registered to {existing.owner}. Re-registering is "
            "impossible by design; the slot is claimed.",
        )

    # Precomputed by `python -m ingest commit-body`; never the serial or key.
    # Blank means none; no setter, since its value is predating any dispute.
    camera = body_commitment.strip().lower().removeprefix("0x")
    if camera and (len(camera) != 64 or any(c not in "0123456789abcdef" for c in camera)):
        raise HTTPException(422, "body_commitment must be 32 bytes of hex, or blank")
    camera = "0x" + (camera or "0" * 64)

    receipt = cast_send([
        "registerBody(bytes32,bytes32,bytes32)",
        "0x" + body_id,
        "0x" + body["commitment"],
        camera,
    ])
    _invalidate_state()
    return {"bodyId": "0x" + body_id, "bodyCommitment": camera, **receipt}


@router.post("/register-image")
async def register_image(
    file: UploadFile = File(...),
    body: str = Form(...),
    description: str = Form(""),
) -> dict:
    """Demo step 2b: score, refuse below threshold before the chain, then register."""
    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    body_id, holder = bodies[body]

    # Enrolled is not registered (fresh enrolment, or after `resetAll`). Check
    # now rather than after a minute of scoring ends in a revert.
    try:
        registered = chain.body("0x" + body_id)
    except chain.ChainError as error:
        raise HTTPException(503, f"cannot read the registry: {error}")
    if registered is None:
        raise HTTPException(
            409,
            f"body {holder['name']} is enrolled on this machine but not registered on "
            f"{chain.REGISTRY}. Register the body first -- that is demo step 2a. "
            "After a registry wipe this is expected: the fingerprint survived the "
            "wipe, the registration did not.",
        )

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
    suffix = Path(file.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(file.file.read())
    handle.close()
    path = Path(handle.name)

    try:
        # One scorer: `_score_against` is what core/'s Rust port is parity-tested
        # against, and it handles portrait frames `build_record` alone cannot.
        measured = _score_against(holder, path)
        built = record.build_record(
            path,
            references / f"{holder['name']}.npz",
            hmac_key=_hmac_key(),
            owner=OWNER,
            score=measured["pce"],
        )
        if built.pce_score < prnu.PCE_THRESHOLD:
            raise HTTPException(
                422,
                f"PCE {built.pce_score} is below {prnu.PCE_THRESHOLD}; refused before "
                "the chain. The pixels do not support the claim.",
            )

        # Left-pad to bytes32: the 8-byte pHash otherwise gets a bare cast "parser error".
        def word(value: bytes) -> str:
            return "0x" + value.rjust(32, b"\x00").hex()

        tuple_arg = (
            f"({word(built.image_hash)},{word(built.perceptual_hash)},"
            f"{word(built.body_id)},{built.modification_level},"
            f"{word(built.parent_image_hash)},{word(built.metadata_hmac)},"
            f"{built.pce_score},{built.registered_at})"
        )
        receipt = cast_send([
            "registerImage((bytes32,bytes32,bytes32,uint8,bytes32,bytes32,uint32,uint64))",
            tuple_arg,
        ])
        # The chain gets the hash; the local catalogue gets the meaning.
        catalogue.record_image(
            image_hash="0x" + built.image_hash.hex(),
            perceptual_hash="0x" + built.perceptual_hash.hex(),
            body_id="0x" + built.body_id.hex(),
            body_name=holder["name"],
            pce=built.pce_score,
            registered_at=built.registered_at,
            tx_hash=receipt.get("txHash"),
            block_number=receipt.get("blockNumber"),
            file_name=file.filename,
            file_path=str(getattr(file, "_source_path", "") or ""),
            description=description or "",
        )
        return {
            "imageHash": "0x" + built.image_hash.hex(),
            "perceptualHash": "0x" + built.perceptual_hash.hex(),
            "bodyId": "0x" + built.body_id.hex(),
            "pce": built.pce_score,
            "registeredAt": built.registered_at,
            **receipt,
        }
    finally:
        path.unlink(missing_ok=True)


@router.post("/register-session")
async def register_session(
    files: list[UploadFile] = File(...),
    body: str = Form(...),
) -> dict:
    """Register a whole shoot as one Merkle root via `commitSession`.

    Proves a set was fixed at a time; per-frame `ImageRecord`s still need
    `/register-image`. Frames below threshold are refused and named, not fatal.
    """
    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    resolved_id, holder = bodies[body]
    body_id_hex = resolved_id if str(resolved_id).startswith("0x") else "0x" + str(resolved_id)

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
    reference = references / f"{holder['name']}.npz"

    accepted: list[dict] = []
    refused: list[dict] = []
    written: list[Path] = []

    try:
        for upload in files:
            suffix = Path(upload.filename or "f").suffix or ".bin"
            handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            handle.write(upload.file.read())
            handle.close()
            path = Path(handle.name)
            written.append(path)

            try:
                built = record.build_record(
                    path,
                    reference,
                    hmac_key=_hmac_key(),
                    owner=OWNER,
                    score=_score_against(holder, path)["pce"],
                )
            except Exception as error:      # a corrupt frame is not fatal to a shoot
                refused.append({"name": upload.filename, "reason": str(error)[:160]})
                continue

            if built.pce_score < prnu.PCE_THRESHOLD:
                refused.append({
                    "name": upload.filename,
                    "pce": built.pce_score,
                    "reason": f"below threshold {prnu.PCE_THRESHOLD}",
                })
                continue

            accepted.append({
                "name": upload.filename,
                "imageHash": built.image_hash,
                "pce": built.pce_score,
            })

        if not accepted:
            raise HTTPException(
                422,
                f"no frame cleared {prnu.PCE_THRESHOLD}; nothing was signed. "
                f"{len(refused)} refused.",
            )

        leaves = [a["imageHash"] for a in accepted]
        root = merkle.merkle_root(leaves)
        # Derived, so the same set of frames always gets the same id.
        session_id = hashlib.sha256(b"genesis-session" + root).digest()

        receipt = cast_send([
            "commitSession(bytes32,bytes32,uint32)",
            "0x" + session_id.hex(),
            "0x" + root.hex(),
            str(len(leaves)),
        ])

        for index, entry in enumerate(accepted):
            catalogue.record_image(
                image_hash="0x" + entry["imageHash"].hex(),
                body_id=body_id_hex,
                body_name=holder["name"],
                pce=entry["pce"],
                registered_at=int(time.time()),
                tx_hash=receipt.get("txHash"),
                block_number=receipt.get("blockNumber"),
                session_id="0x" + session_id.hex(),
                file_name=entry["name"],
                description="",
            )

        return {
            "sessionId": "0x" + session_id.hex(),
            "merkleRoot": "0x" + root.hex(),
            "frameCount": len(leaves),
            "accepted": [
                {
                    "name": a["name"],
                    "imageHash": "0x" + a["imageHash"].hex(),
                    "pce": a["pce"],
                    "proof": ["0x" + node.hex() for node in merkle.inclusion_proof(leaves, i)],
                }
                for i, a in enumerate(accepted)
            ],
            "refused": refused,
            **receipt,
        }
    finally:
        for path in written:
            path.unlink(missing_ok=True)


@router.post("/reset")
async def reset_registry(confirm: str = Form(...), clear_enrolments: bool = Form(True)) -> dict:
    """Wipe every record so the demo can run again (body ids are fixed by K, so otherwise a redeploy).

    Gated on the contract's `testMode()`, not config. `confirm` must be the
    registry address, so the operator looks before destroying work.
    """
    if not chain.REGISTRY:
        raise HTTPException(503, "REGISTRY_ADDRESS is not set")

    if not chain.test_mode():
        raise HTTPException(
            409,
            f"{chain.REGISTRY} is not a test registry -- `testMode()` is false, so it "
            "has no reset. This is what a production deployment looks like.",
        )

    if confirm.strip().lower() != chain.REGISTRY.strip().lower():
        raise HTTPException(
            422,
            "confirm must be the registry address you are about to wipe, "
            f"which is {chain.REGISTRY}",
        )

    before = chain.registry_epoch()
    receipt = cast_send(["resetAll()"])
    _invalidate_state()

    # Local state describing the chain must go with it. The archive always goes.
    # References (89 MB each) are deleted, not moved; re-enrolling gives the
    # same K only from the same frames (`docs/adversarial.md`), and the UI warns.
    archived = catalogue.clear()

    cleared: list[str] = []
    if clear_enrolments:
        references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
        for reference in sorted(references.glob("*.npz")):
            cleared.append(reference.stem)
            reference.unlink()
        _bodies.cache_clear()

    # A separate scorer process notices the directory change itself (`scoring.app._bodies`).
    return {
        "registry": chain.REGISTRY,
        "epochBefore": before,
        "epochAfter": chain.registry_epoch(),
        "enrolmentsCleared": cleared,
        "archiveRowsCleared": archived,
        **receipt,
    }


@router.post("/register-image/stream")
async def register_image_stream(
    file: UploadFile = File(...), body: str = Form(...), description: str = Form("")
) -> dict:
    """Demo step 2b as a watchable job; each real phase is an event.

    Most of the wait is the PRNU search, not the chain, so the events say so.
    """
    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    body_id, holder = bodies[body]

    try:
        registered = chain.body("0x" + body_id)
    except chain.ChainError as error:
        raise HTTPException(503, f"cannot read the registry: {error}")
    if registered is None:
        raise HTTPException(
            409,
            f"body {holder['name']} is enrolled on this machine but not registered on "
            f"{chain.REGISTRY}. Register the body first -- that is demo step 2a.",
        )

    suffix = Path(file.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(file.file.read())
    handle.close()
    path = Path(handle.name)

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))

    def work(job: jobs.Job) -> None:
        try:
            job.emit(event="step", phase="reading", label=f"reading {file.filename}")

            def searching(label: str) -> None:
                # Passed through: "7 of 21" shows the wait is finite.
                job.emit(event="step", phase="scoring", label=label)

            measured = _score_against(holder, path, progress=searching)

            job.emit(event="step", phase="record",
                     label=f"building the record — PCE {measured['pce']:.1f}")
            built = record.build_record(
                path, references / f"{holder['name']}.npz", hmac_key=_hmac_key(),
                owner=OWNER, score=measured["pce"],
            )

            if built.pce_score < prnu.PCE_THRESHOLD:
                job.finish(error=(
                    f"PCE {built.pce_score} is below {prnu.PCE_THRESHOLD}; refused "
                    "before the chain. The pixels do not support the claim."
                ))
                return

            job.emit(event="step", phase="signing",
                     label="signing with the body owner's key")
            job.emit(event="step", phase="broadcasting",
                     label="broadcasting and waiting for the receipt")

            def word(value: bytes) -> str:
                return "0x" + value.rjust(32, b"\x00").hex()

            tuple_arg = (
                f"({word(built.image_hash)},{word(built.perceptual_hash)},"
                f"{word(built.body_id)},{built.modification_level},"
                f"{word(built.parent_image_hash)},{word(built.metadata_hmac)},"
                f"{built.pce_score},{built.registered_at})"
            )
            receipt = cast_send([
                "registerImage((bytes32,bytes32,bytes32,uint8,bytes32,bytes32,uint32,uint64))",
                tuple_arg,
            ])

            job.emit(event="step", phase="receipt",
                     label=f"included in block {receipt['blockNumber']}")
            _invalidate_state()
            catalogue.record_image(
                image_hash="0x" + built.image_hash.hex(),
                perceptual_hash="0x" + built.perceptual_hash.hex(),
                body_id="0x" + built.body_id.hex(), body_name=holder["name"],
                pce=float(built.pce_score), registered_at=built.registered_at,
                tx_hash=receipt["txHash"], block_number=receipt["blockNumber"],
                session_id=None, file_name=file.filename, file_path="",
                description=description, noted_at=int(time.time()),
            )
            job.finish({
                "imageHash": "0x" + built.image_hash.hex(),
                "perceptualHash": "0x" + built.perceptual_hash.hex(),
                "bodyId": "0x" + built.body_id.hex(),
                "pce": built.pce_score,
                "registeredAt": built.registered_at,
                **receipt,
            })
        except HTTPException as error:
            job.finish(error=str(error.detail))
        except Exception as error:  # noqa: BLE001 -- the job carries it to the screen
            job.finish(error=f"{type(error).__name__}: {error}")
        finally:
            path.unlink(missing_ok=True)

    job = jobs.start(work)
    return {"jobId": job.id}


@router.get("/register-image/{job_id}/events")
async def register_image_events(job_id: str):
    from fastapi.responses import StreamingResponse

    job = jobs.get(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")

    def stream():
        while True:
            event = job.events.get()
            yield f"data: {json.dumps(event)}\n\n"
            if event.get("event") == "done":
                return

    return StreamingResponse(stream(), media_type="text/event-stream")

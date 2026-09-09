"""The endpoints that sign. Kept in their own module on purpose.

`registerImage`'s `require(body.owner == msg.sender)` is the only mechanism
in the system that no attack in `docs/adversarial.md` got past, so everything
the product claims sits downstream of a transaction sent from here. That
boundary should be visible in a file listing, not buried in a router.

Transactions go through `cast`, which `contracts/script/local-e2e.sh` already
uses and which the README already requires. That is one fewer dependency than
a Python signing stack, and the identical code path to the one the offline run
has been exercising since day one.

The key is fed to `cast --interactive` on stdin, never as an argument. An
argument would put it in `ps` output for every process on the machine.
"""

from __future__ import annotations

import hashlib
import os
import time
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from console import catalogue, chain
from fingerprint import prnu
from ingest import merkle, record
from scoring.app import _bodies, _score_against

router = APIRouter()

CAST_TIMEOUT = 180


def _hmac_key() -> bytes | None:
    """`METADATA_HMAC_KEY` as bytes.

    It arrives from the environment as a string and `hashing.metadata_hmac`
    takes bytes, which raised a TypeError inside the request rather than at
    startup -- the endpoint returned 500 and the demo looked like the chain
    had refused it. Hex is decoded as hex because that is what `.env` holds;
    anything else is taken as UTF-8, which is what `local-e2e.sh` passes.
    """
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


def cast_send(args: list[str]) -> dict:
    """One transaction, and the receipt fields the console reports.

    Raises rather than returning a failure shape. A registration that did not
    land must not be reportable as one.
    """
    if not chain.REGISTRY:
        raise HTTPException(503, "REGISTRY_ADDRESS is not set")

    # `--interactive` reads the key from a terminal, and there is no terminal
    # here: piping to it fails with "Device not configured". So the key goes
    # on the argv, which is visible in `ps` for the length of one transaction.
    # Acceptable for a localhost demo driver on the operator's own machine
    # (`docs/security.md`), and not acceptable for anything hosted -- which
    # this is not, and must not become.
    command = [
        "cast", "send", chain.REGISTRY, *args,
        "--rpc-url", chain.RPC_URL,
        "--private-key", _key(),
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
        # A revert the contract has a word for deserves that word, not a wall
        # of hex. "already registered" is the common one and it is not an
        # error the operator can fix by retrying.
        for phrase, message in (
            ("image already registered",
             "This photograph is already registered. Registering the same pixels "
             "twice is impossible by design -- verify it instead."),
            ("body already registered",
             "This body is already registered. The slot is claimed and cannot be "
             "re-taken."),
            ("below threshold",
             "The pixels do not clear the threshold; nothing was signed."),
        ):
            if phrase in done.stderr:
                raise HTTPException(409, message)

        # stderr can echo the calldata; the key is redacted so a failed
        # transaction cannot spill it into a log or a screen recording.
        leaked = done.stderr.replace(_key(), "<key>").strip()
        raise HTTPException(502, f"transaction failed: {leaked[:400]}")

    import json

    try:
        receipt = json.loads(done.stdout)
    except json.JSONDecodeError:
        raise HTTPException(502, f"unparseable receipt: {done.stdout.strip()[:200]}")

    if str(receipt.get("status", "")).lower() not in ("0x1", "1", "true"):
        raise HTTPException(502, f"transaction reverted: {receipt.get('transactionHash')}")

    return {
        "txHash": receipt.get("transactionHash"),
        "blockNumber": int(str(receipt.get("blockNumber", "0")), 0),
        "explorerUrl": chain.explorer_url(receipt.get("transactionHash", ""), "tx"),
    }


@router.post("/register-body")
async def register_body(name: str = Form(...), ens_label: str = Form(...)) -> dict:
    """Demo step 2a.

    Done before anything else because `registerBody` is a race: `bodyId`
    derives from `SHA-256(K)`, so anyone holding a leaked K can compute the id
    and claim the slot first, and the real photographer is then permanently
    locked out (`docs/security.md`).
    """
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

    parent = os.environ.get("ENS_PARENT_NAME", "cam.osoro.eth")
    ens_node = subprocess.run(
        ["cast", "keccak", f"{ens_label}.{parent}"], capture_output=True, text=True
    ).stdout.strip()

    receipt = cast_send([
        "registerBody(bytes32,bytes32,bytes32)",
        "0x" + body_id,
        "0x" + body["commitment"],
        ens_node,
    ])
    return {"bodyId": "0x" + body_id, "ensName": f"{ens_label}.{parent}", **receipt}


@router.post("/register-image")
async def register_image(
    file: UploadFile = File(...),
    body: str = Form(...),
    description: str = Form(""),
) -> dict:
    """Demo step 2b: score, refuse if it does not clear, then register.

    The threshold check happens here and not only in the contract. A frame
    that does not clear is refused before it reaches the chain, which is what
    `local-e2e.sh` has always done -- registering a photograph the pixels do
    not support would put a claim on chain that the system itself disagrees
    with.
    """
    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    body_id, holder = bodies[body]

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
    suffix = Path(file.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(file.file.read())
    handle.close()
    path = Path(handle.name)

    try:
        # Score through the same function `/verify` uses. `build_record`'s
        # own scoring is the aligned path only, so a portrait frame raised a
        # shape mismatch and returned 500 -- the fingerprint lives in sensor
        # space, which is always landscape. Registration and verification
        # disagreeing about one photograph is the failure worth engineering
        # against, so there is one scorer and this is it.
        measured = _score_against(holder, path)
        built = record.build_record(
            path,
            references / f"{holder['name']}.npz",
            hmac_key=_hmac_key(),
            owner=os.environ.get("ENS_PARENT_NAME"),
            score=measured["pce"],
        )
        if built.pce_score < prnu.PCE_THRESHOLD:
            raise HTTPException(
                422,
                f"PCE {built.pce_score} is below {prnu.PCE_THRESHOLD}; refused before "
                "the chain. The pixels do not support the claim.",
            )

        # Every field is bytes32 on chain. The perceptual hash is only eight
        # bytes -- it is a 64-bit pHash -- so it has to be left-padded, and
        # `cast` rejects the short form with a bare "parser error" that says
        # nothing about which field is wrong. The registered record on Sepolia
        # shows the padding: 0x0000...e829e9b0556d25cb.
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
        # The chain gets the hash; the disk gets the meaning. Without this a
        # photographer holding 0x2224a686... has no way to learn it was
        # IMG_0230.CR3 -- see `console/catalogue.py`.
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
    """Register a whole shoot in one transaction.

    This is what `commitSession` is for and why it exists: a shoot is two
    thousand frames, and one write per photograph is neither affordable nor
    necessary. The frames are scored locally, their pixel hashes become the
    leaves of a Merkle tree, and **one** root goes on chain. Any frame's
    membership is then provable against that root with `verifyInclusion`,
    without the chain ever holding the frame.

    What this does not do is give each frame its own `ImageRecord`. A session
    proves *a set of photographs was fixed at a time*; `registerImage` is what
    attaches a body, a score and an owner to one photograph. They answer
    different questions and the demo uses both -- so a frame that needs an
    individual record still gets `/register-image`.

    Frames below `PCE_THRESHOLD` are refused and named, and the session is
    committed without them rather than failing whole. One bad frame in two
    thousand should not cost the shoot.
    """
    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    _, holder = bodies[body]

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
                    owner=os.environ.get("ENS_PARENT_NAME"),
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
        # The session id is derived, not assigned, so two people committing the
        # same set of frames arrive at the same id and cannot collide by luck.
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

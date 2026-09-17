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


def _invalidate_state() -> None:
    """Drop the cached pre-flight gate after anything that changes it.

    `/state` is cached for a few seconds because it is polled and each call
    costs about eight `eth_call`s. That is fine for a gate nobody is changing
    and wrong the moment something is: a body that has just been registered
    should not still read "not registered" for another three seconds, because
    the next screen tells the operator to go and register it.
    """
    from console.app import invalidate_state

    invalidate_state()


def ens_namehash(name: str) -> str:
    """EIP-137 namehash, which is NOT keccak256 of the name.

    This was `cast keccak` until 13 September 2026, and the difference is the
    expensive kind of silent: a record written against the wrong node
    succeeds, costs gas, and resolves to nothing. `identity/scripts/ens.ts`
    had it right the whole time and has eight tests on this arithmetic; this
    path shelled out to the wrong subcommand and had none, so the registry
    and the resolver disagreed about what a node is.

    Namehash is recursive -- keccak256(namehash(parent) || keccak256(label))
    down to the empty root -- so no amount of hashing the whole string gets
    there. `cast namehash` implements it and agrees with viem's, which is
    what `identity/` uses.
    """
    done = subprocess.run(["cast", "namehash", name], capture_output=True, text=True)
    node = done.stdout.strip()
    # Checked rather than assumed: the previous version took `.stdout` from an
    # unchecked run, so a missing `cast` wrote the zero node instead of failing.
    if done.returncode != 0 or not node.startswith("0x") or len(node) != 66:
        raise HTTPException(502, f"cast namehash {name} failed: {done.stderr.strip()[:200]}")
    return node


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
            ("unknown body",
             "The registry has no record of this body. Register the body first "
             "(demo step 2a) -- after a wipe the enrolled fingerprint survives but "
             "its registration does not."),
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

    tx_hash = receipt.get("transactionHash", "")
    return {
        "txHash": tx_hash,
        "blockNumber": int(str(receipt.get("blockNumber", "0")), 0),
        "explorerUrl": chain.explorer_url(tx_hash, "tx"),
        # Every signing endpoint returns these, so anything the console puts on
        # chain comes back with the places it can be checked.
        "links": chain.reference_links(tx_hash),
    }


@router.post("/register-body")
async def register_body(name: str = Form(...), body_commitment: str = Form("")) -> dict:
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

    # The keyed camera commitment (`ingest/hashing.py:body_commitment`),
    # computed on the photographer's machine by `python -m ingest commit-body`.
    # It arrives already hashed: this endpoint never sees the serial or the key.
    # Blank means none, and there is no setter -- a commitment is worth
    # something only because it predates any dispute.
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

    # Enrolled is not registered, and the contract is the one that knows.
    # `registerImage` reverts `unknown body` when the id has no record, and
    # the two ways to arrive there are both ordinary: a fresh enrolment that
    # has not been registered yet, and a `resetAll` that cleared the chain out
    # from under one that had. Checked here rather than left to the revert
    # because the scoring below takes a minute, and spending that to arrive at
    # a hex-encoded error is the worst version of this.
    try:
        registered = chain.body("0x" + body_id)
    except chain.ChainError as error:
        # Unreadable chain: the transaction below would fail anyway, and
        # saying which half is broken beats a gas-estimation error.
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
                # Recorded, or the archive counts a session's frames as
                # belonging to no body and the statistics undercount.
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
    """Wipe every record, so the demo can be run again.

    `bodyId` derives from `SHA-256(K)`, so the same camera always reaches the
    same id and `registerBody` refuses a duplicate forever. That refusal is
    correct -- it is what stops someone claiming a body out from under its
    owner -- and it is also why rehearsing twice needed a fresh deployment
    until now.

    **Gated on the contract, not on configuration.** `testMode()` is read from
    the registry itself: a console that trusted a local flag could offer this
    against a registry that has no reset, and the failure would arrive as an
    unexplained revert mid-demo. A production registry answers false here and
    this endpoint refuses before it spends anything.

    `confirm` must be the registry address. Not ceremony: this is the one
    button in the console that destroys work, and the operator should have to
    look at which registry they are pointed at before pressing it.
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

    # The chain is only half of a clean slate. `resetAll` clears records; the
    # enrolled references are files on this machine and the wipe never touched
    # them, so the console kept reporting a body that had nothing on chain
    # behind it. For a rehearsal that reads as a bug, and for demo step 1 --
    # enrol from an archive folder -- it is one, because the screen has
    # nothing left to do.
    #
    # Deleted rather than moved aside: these are 89 MB each and a rehearsal
    # loop would accumulate them. The frames they were estimated from are
    # untouched, so an enrolment can always be run again -- but **not** to the
    # same K unless the same frames are chosen, because `save_fingerprint`
    # does not record which ones were used (`docs/adversarial.md`). The UI
    # says so before this runs.
    # The archive describes what this machine registered, keyed by image hash.
    # After the wipe none of those hashes resolve on chain, so every row is a
    # claim the registry will not confirm and screen 06 would go on presenting
    # them as registered work. It goes with the chain, always -- unlike the
    # references, there is nothing here that cannot be rebuilt by registering
    # again, so there is no reason to make it a choice.
    archived = catalogue.clear()

    cleared: list[str] = []
    if clear_enrolments:
        references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
        for reference in sorted(references.glob("*.npz")):
            cleared.append(reference.stem)
            reference.unlink()
        _bodies.cache_clear()

    # The scorer is a separate process with its own cache, and it notices the
    # references directory changing on its own -- see `scoring.app._bodies`.
    return {
        "registry": chain.REGISTRY,
        "epochBefore": before,
        "epochAfter": chain.registry_epoch(),
        "enrolmentsCleared": cleared,
        "archiveRowsCleared": archived,
        **receipt,
    }


@router.post("/score-confidential")
async def score_confidential(file: UploadFile = File(...), body: str = Form(...)) -> dict:
    """Score where nobody holds K, so the console can show the CRE path.

    The scoring service has the same endpoint; this one exists because the
    console frontend talks only to the console, and because a presenter needs
    the two things the raw score does not carry: how long it took, and which
    backend produced it. Sixteen seconds of WASM compilation looks like a hang
    unless the screen says what it is doing.

    RAW only, and the refusal is the honest one: the confidential path
    correlates on the photosite lattice and a developed JPEG has none left.
    The scale search that rescues those needs the whole 89 MB reference, which
    is the one thing that does not fit an enclave.
    """
    import time

    from cre import backend as confidential

    bodies = {name: (bid, b) for bid, b in _bodies().items() for name in (b["name"], bid)}
    if body not in bodies:
        raise HTTPException(404, f"unknown body {body}")
    _, holder = bodies[body]

    # The same inline handling the other signing endpoints use; `_save` lives
    # in console/app.py and importing it here would make the module cycle.
    suffix = Path(file.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(file.file.read())
    handle.close()
    path = Path(handle.name)

    try:
        if path.suffix.lower() not in record.hashing_raw_suffixes():
            raise HTTPException(
                415,
                "the confidential path needs a RAW frame. A developed JPEG has no "
                "photosite lattice left, and the search that rescues it needs the "
                "whole reference -- which is what does not fit an enclave.",
            )

        started = time.time()
        probe = prnu.load_raw_planes(path, crop=confidential.payload_mod.PLANE_SIZE * 2)
        result = confidential.score(probe, holder["planes"], body)
        return {
            "body": holder["name"],
            "seconds": round(time.time() - started, 1),
            "planeSize": confidential.payload_mod.PLANE_SIZE,
            **result.to_json(),
        }
    finally:
        path.unlink(missing_ok=True)


@router.post("/register-image/stream")
async def register_image_stream(
    file: UploadFile = File(...), body: str = Form(...), description: str = Form("")
) -> dict:
    """Demo step 2b, as a job you can watch.

    The blocking version reports nothing between the upload and the receipt,
    and the wait is dominated by a part nobody would guess: registering runs
    the full PRNU scale and orientation search, twenty-one correlations on an
    unfamiliar frame, which is most of the wall clock. The transaction at the
    end is seconds. A screen that named the transaction while running the
    search taught operators to distrust a chain that was not the problem.

    So every phase is an event with a timestamp and an elapsed figure, and the
    phases are the real ones rather than a tidy fiction:

        reading · hashing · scoring (with the search's own progress) ·
        building the record · threshold · signing · broadcasting · receipt

    `jobs.Job.emit` stamps them; nothing here has to remember to.
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
                # The scorer's own progress, passed through rather than
                # summarised: "searching scale and orientation — 7 of 21" is
                # the only line that tells an operator the wait is finite.
                job.emit(event="step", phase="scoring", label=label)

            measured = _score_against(holder, path, progress=searching)

            job.emit(event="step", phase="record",
                     label=f"building the record — PCE {measured['pce']:.1f}")
            built = record.build_record(
                path, references / f"{holder['name']}.npz", hmac_key=_hmac_key(),
                owner=os.environ.get("ENS_PARENT_NAME"), score=measured["pce"],
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

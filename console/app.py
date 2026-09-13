"""The demo console API. Localhost only; it will hold a signing key.

    uvicorn console.app:app --host 127.0.0.1 --port 8100

Spec `docs/console-server.md`, posture `docs/security.md`. This file has
`/health`, `/state` and `/verify`. The signing endpoints come next and stay
in their own module, so the boundary is visible in the file listing.

The pixel work is imported from `scoring.app` rather than reimplemented. The
console and the public verify page must never disagree about what the pixels
say -- if they did, the demo would be showing something the public page
cannot reproduce.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from console import catalogue, chain, jobs, registry, subgraph
from fingerprint import consistency, prnu, stress
from ingest import hashing, record
from scoring.app import _bodies, _score_against

app = FastAPI(title="Genesis demo console")

#: The console is a demo driver, not a product surface. It binds to localhost
#: and only the local frontend may call it (`docs/security.md`).
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get(
        "GENESIS_CONSOLE_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
    ).split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


#: The signing endpoints live in their own module so the one boundary in the
#: system is visible in the file listing (`docs/security.md`).
app.include_router(registry.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "bodies": len(_bodies())}


#: Thresholds for the pre-flight gate. The backend owns these, not the
#: design: a number in a mockup is a guess, and a check that reads NO-GO for a
#: condition that is actually fine will get overridden on camera, which
#: teaches a presenter to ignore the gate.
#:
#: Gas: the demo sends four transactions -- registerBody, registerImage,
#: commitSession, commit -- which on Sepolia costs far under 0.01 ETH. The
#: handoff asked for 0.05, which the deployer's 0.0484 would fail for no real
#: reason.
#:
#: Bodies: one. Two would be better and needs a second physical camera
#: (`docs/e2e-checklist.md` §1), so gating the demo on it would gate it on
#: hardware nobody has.
MIN_BALANCE_WEI = 10**16          # 0.01 ETH
MIN_BODIES = 1
MAX_BLOCK_AGE = 60                # seconds; Sepolia blocks are ~12s


#: `/state` is polled, and every call makes roughly eight sequential
#: `eth_call`s against a public RPC -- which is the slowest thing the console
#: touches and gets slower the more it is asked. Measured: 4.5s, 21.5s and
#: 8.5s on three consecutive calls. Every screen awaits this before doing
#: anything, so that latency was being paid before a registration could even
#: start, and the frontend read it as the registration being slow.
#:
#: Three seconds, because a Sepolia block is twelve and this is a go/no-go
#: gate: stale enough to be cheap, fresh enough that nothing it reports can
#: have changed underneath it unnoticed.
_STATE_TTL = 3.0
_STATE_CACHE: dict = {"at": 0.0, "payload": None}


@app.get("/state")
async def state() -> dict:
    """The go/no-go gate, as rows a table renders without deciding anything.

    Everything here can fail on camera, and a presenter needs to see *which*
    part is down rather than that something is -- so this never raises, and
    every check carries what was measured, what was expected, and whether it
    passes. The frontend renders; it does not evaluate.
    """
    import time as _time

    fresh = _time.time() - _STATE_CACHE["at"] < _STATE_TTL
    if fresh and _STATE_CACHE["payload"] is not None:
        return _STATE_CACHE["payload"]

    checks: list[dict] = []

    def record(name, measured, expected, ok, remedy=None):
        row = {"check": name, "measured": str(measured), "expected": expected, "go": bool(ok)}
        if remedy and not ok:
            row["remedy"] = remedy
        checks.append(row)

    try:
        status = chain.status()
        record("chain id", status["chainId"], f"{chain.EXPECTED_CHAIN_ID} Sepolia",
               status["onExpectedChain"], "point SEPOLIA_RPC_URL at Sepolia")
        record("registry", status["registry"] or "unset", "contract address set",
               bool(status["registry"]), "set REGISTRY_ADDRESS in .env")
        try:
            age = chain.block_age_seconds()
            record("block", f"{status['blockNumber']} · {age}s old",
                   f"advancing, under {MAX_BLOCK_AGE}s", age <= MAX_BLOCK_AGE,
                   "the RPC is stale; switch endpoint")
        except chain.ChainError as error:
            record("block", f"error: {error}", "advancing", False, "switch RPC endpoint")
    except chain.ChainError as error:
        record("chain id", f"unreachable: {error}", f"{chain.EXPECTED_CHAIN_ID} Sepolia",
               False, "check SEPOLIA_RPC_URL")
        status = {}

    deployer = os.environ.get("DEPLOYER_ADDRESS")
    if deployer:
        try:
            wei = chain.balance(deployer)
            record("deployer gas", f"{wei / 1e18:.4f} ETH",
                   f"at least {MIN_BALANCE_WEI / 1e18:.2f} ETH", wei >= MIN_BALANCE_WEI,
                   "top up from a Sepolia faucet")
        except chain.ChainError as error:
            record("deployer gas", f"error: {error}", "balance readable", False)
    else:
        record("deployer gas", "DEPLOYER_ADDRESS unset", "an address to check", False,
               "set DEPLOYER_ADDRESS in .env")

    parent = os.environ.get("ENS_PARENT_NAME", "")
    if parent:
        try:
            ready, detail = chain.ens_parent_ready(parent)
            record("ens parent", parent if ready else detail,
                   f"{parent} has a subregistry", ready,
                   "register the parent at https://app.ens.dev/ and create one "
                   "subname under it -- that is what provisions the subregistry")
        except chain.ChainError as error:
            record("ens parent", f"error: {error}", f"{parent} resolves", False)

    bodies = _bodies()
    record("enrolled bodies", len(bodies), f"at least {MIN_BODIES}",
           len(bodies) >= MIN_BODIES, "run /enrol, or check GENESIS_REFERENCES")

    # Enrolled and registered are different states and the console used to
    # show only the first, which is how a wiped registry led to `registerImage`
    # reverting `unknown body` with no screen offering the step that fixes it.
    body_status = []
    for body_id, body in bodies.items():
        try:
            on_chain = chain.body("0x" + body_id) is not None
        except chain.ChainError:
            on_chain = False
        body_status.append({"name": body["name"], "bodyId": "0x" + body_id,
                            "registered": on_chain})
    if body_status and not any(b["registered"] for b in body_status):
        record("body registered", "no", "the body is on chain", False,
               "register the body on screen 02 -- an image cannot attach to a body "
               "the registry has never heard of")
    elif body_status:
        record("body registered", "yes", "the body is on chain", True)

    try:
        subgraph_ok = bool(subgraph.SUBGRAPH_URL)
    except Exception:
        subgraph_ok = False
    record("perceptual index", subgraph.SUBGRAPH_URL or "unset",
           "subgraph URL set", subgraph_ok,
           "set GENESIS_SUBGRAPH_URL; without it a degraded copy cannot find "
           "its original and step 4 falls back to fingerprint-only")

    # Asked of the contract, not of configuration: the console must not offer
    # a reset button against a registry that has no reset, nor hide one that
    # does. A production registry answers false and the button never appears.
    try:
        resettable = chain.test_mode()
        epoch = chain.registry_epoch()
    except Exception:
        resettable, epoch = False, 0

    payload = {
        "ready": all(c["go"] for c in checks),
        "checks": checks,
        "bodies": [b["name"] for b in bodies.values()],
        "bodyStatus": body_status,
        "threshold": prnu.PCE_THRESHOLD,
        "chain": status,
        "ensParent": parent or None,
        "registry": {"resettable": resettable, "epoch": epoch},
    }
    _STATE_CACHE["at"], _STATE_CACHE["payload"] = _time.time(), payload
    return payload


def invalidate_state() -> None:
    """Drop the cached gate. Called by anything that changes what it reports,
    so a registration or a wipe shows up at once rather than up to three
    seconds later."""
    _STATE_CACHE["at"], _STATE_CACHE["payload"] = 0.0, None


def _save(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(upload.file.read())
    handle.close()
    return Path(handle.name)


def _signals(path: Path, body: dict, result: dict) -> dict:
    """Advisory evidence. Never a verdict -- see `docs/security.md`.

    `bodyConsistency` and `pooledTriangle` need calibration the server does
    not hold until `/enrol` stores it, so they are null rather than a number
    nobody can interpret. The two that need none are returned with
    `calibrated: false`, because the *band* they are read against is what is
    missing, not the measurement.
    """
    signals: dict = {
        "calibrated": False,
        "bodyConsistency": None,
        "pooledTriangle": None,
        "effectiveStrength": None,
        "resamplingPeak": None,
    }
    try:
        if result.get("path") == "aligned":
            planes = (
                prnu.load_raw_planes(path, crop=body["meta"].get("crop"))
                if path.suffix.lower() in record.hashing_raw_suffixes()
                else prnu.load_delivered_planes(path, body["meta"]["cfa_pattern"])
            )
            signals["effectiveStrength"] = consistency.effective_strength(planes, body["planes"])

        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        if path.suffix.lower() not in record.hashing_raw_suffixes():
            with Image.open(path) as opened:
                import numpy as np

                signals["resamplingPeak"] = consistency.resampling_peak(
                    np.asarray(opened.convert("L"), dtype=float)
                )
                # Not advisory in the same sense as the others: this does not
                # say a photograph is forged, it says whether there was
                # anything to measure. A frame with no high-frequency detail
                # carries no fingerprint however genuine it is, and telling a
                # photographer their own soft photograph is "unrecognised"
                # blames the camera for the exposure.
                detail = consistency.high_frequency_content(opened)
                signals["detail"] = round(detail, 1)
                signals["tooSoftToMeasure"] = detail < consistency.DETAIL_FLOOR
    except (ValueError, KeyError, OSError):
        pass  # advisory: a signal that cannot be computed is absent, not fatal
    return signals


def _verify(path: Path, progress=None) -> dict:
    """The verification itself, and the only place `registered` is decided.

    Shared by `/verify` and `/verify/stream`, one implementation on purpose: a
    blocking endpoint and a streaming one that could disagree about the same
    photograph would repeat the mistake registration and verification already
    made once, and the fix there was also to collapse onto one function.

    Takes ownership of `path` and deletes it, because the streaming caller
    outlives the request that saved it.

    Three outcomes, and the difference between the first two is a chain read
    and nothing else:

    - `registered`   a record came back for this pixel hash. The only verdict
                     that carries a claim.
    - `fingerprint-only`  the pixels matched and nothing is registered. **Not
                     a pass.** A fingerprint can be planted by anyone holding
                     one RAW file off the body (`docs/adversarial.md`).
    - `no-record`    neither. Absence means nothing about the image.

    If the RPC is unreachable this raises rather than falling back to
    `fingerprint-only`. Silently downgrading a verdict is how a demo tells a
    comfortable lie, and the downgrade would land on the case that looks most
    like success.
    """
    bodies = _bodies()
    if not bodies:
        path.unlink(missing_ok=True)
        raise HTTPException(503, "no enrolled fingerprints")

    try:
        candidates = []
        for body_id, body in bodies.items():
            scored = _score_against(body, path, progress)
            candidates.append({"bodyId": body_id, "body": body, **scored})
        candidates.sort(key=lambda c: -c["pce"])
        best = candidates[0]

        image_hash = "0x" + hashing.pixel_sha256(path).hex()
        perceptual_hash = f"0x{hashing.perceptual_hash(path):016x}"

        try:
            registration = chain.image(image_hash)
        except chain.ChainError as error:
            raise HTTPException(502, f"chain read failed, verdict withheld: {error}")

        # The lower branch, and the one demo step 4 rides on. A degraded copy
        # has a different pixel hash, so the exact read above misses; the
        # perceptual hash finds a candidate and the chain confirms it. The
        # confirmation is the point -- a pHash hit on its own is a lookup, and
        # `registered` still means a chain read succeeded.
        derived_from = None
        if registration is None:
            try:
                near = subgraph.nearest(perceptual_hash)
            except subgraph.SubgraphError:
                near = None       # index down: fall through, never fabricate
            if near:
                try:
                    candidate = chain.image(near["imageHash"])
                except chain.ChainError as error:
                    raise HTTPException(502, f"chain read failed, verdict withheld: {error}")
                if candidate:
                    registration = candidate
                    derived_from = {
                        "imageHash": near["imageHash"],
                        "hammingDistance": near["distance"],
                        "matchedBy": "perceptual hash",
                    }

        matched = best["pce"] >= prnu.PCE_THRESHOLD
        if registration and derived_from is None:
            # Exact pixel hash. This *is* the registered file, byte for byte.
            verdict = "registered"
        elif registration:
            # A perceptual match the chain confirmed. Weaker on purpose: a
            # pHash is collidable and cheap to forge, so this says the image
            # descends from a registered photograph -- not that it is one.
            # The PCE is reported beside it and here it may well be below
            # threshold, which is the honest state of a degraded copy.
            verdict = "derived"
        elif matched:
            verdict = "fingerprint-only"
        else:
            verdict = "no-record"

        payload: dict = {
            "verdict": verdict,
            "pce": best["pce"],
            "threshold": prnu.PCE_THRESHOLD,
            "method": best.get("path"),
            "orientation": best.get("orientation"),
            "imageHash": image_hash,
            "perceptualHash": perceptual_hash,
            "body": None,
            "registration": None,
            "derivedFrom": derived_from,
            "consistency": None,   # filled below, with the stage report
        }

        signals = _signals(path, best["body"], best)
        payload["consistency"] = signals
        payload["stages"] = consistency.stages(
            matched=matched,
            registered=registration is not None,
            signals=signals,
            path="raw" if best.get("path") == "aligned" else "delivered",
        )

        if registration:
            on_chain_body = chain.body(registration.body_id)
            payload["body"] = {
                "bodyId": registration.body_id,
                "owner": on_chain_body.owner if on_chain_body else None,
                "commitment": on_chain_body.fingerprint_commitment if on_chain_body else None,
                "revoked": on_chain_body.revoked if on_chain_body else None,
                "ensName": os.environ.get("ENS_PARENT_NAME"),
            }
            payload["registration"] = {
                "registeredAt": registration.registered_at,
                "modificationLevel": registration.modification_level,
                "pceAtRegistration": registration.pce_score,
                "explorerUrl": chain.explorer_url(chain.REGISTRY, "address"),
            }
        elif matched:
            # Named, because the page has to say *which* body's fingerprint it
            # is -- and say in the same breath that nobody registered it.
            payload["body"] = {"bodyId": best["bodyId"], "name": best["body"]["name"]}
        else:
            payload["diagnosis"] = _diagnose(path, payload["consistency"] or {})

        return payload
    finally:
        path.unlink(missing_ok=True)


#: Software tags a desktop development leaves behind. Anything with a camera
#: Make and none of these looks like a JPEG straight out of the camera, which
#: `docs/gates.md` measured as carrying no readable fingerprint.
DESKTOP_SOFTWARE = (
    "adobe", "photoshop", "lightroom", "acd", "capture one", "darktable",
    "rawtherapee", "affinity", "dxo", "luminar", "gimp", "pixelmator",
    "apple", "preview",
)


def _diagnose(path: Path, signals: dict) -> str | None:
    """Why there was nothing to find — when we can say, from measurement.

    A bare `no-record` is true and unhelpful. It reads as "not your camera",
    and for two common cases that is the wrong thing to conclude: the image
    may carry no measurable fingerprint at all. Saying which costs nothing and
    stops a photographer distrusting a camera that is fine.

    Only reports what was measured or read. It never guesses at a cause it
    cannot see.
    """
    if signals.get("tooSoftToMeasure"):
        return (
            f"This image has almost no high-frequency detail (median tile "
            f"{signals.get('detail')}, against roughly 1,000-4,000 for files that "
            f"verify). A sensor fingerprint lives in high frequencies, so there is "
            f"nothing here to measure — which is not the same as the camera not "
            f"matching."
        )

    if path.suffix.lower() in record.hashing_raw_suffixes():
        return None

    try:
        from PIL import Image

        with Image.open(path) as opened:
            exif = opened.getexif() or {}
        make = str(exif.get(271, "") or "")
        software = str(exif.get(305, "") or "").lower()
    except Exception:
        return None

    if make and not any(tag in software for tag in DESKTOP_SOFTWARE):
        return (
            "This looks like a JPEG written by the camera itself. Measured on "
            "this body, in-camera JPEGs carry no readable fingerprint — the "
            "camera's noise reduction removes it, because to the camera a "
            "sensor fingerprint is noise (docs/gates.md). Try the RAW, or a "
            "development of it."
        )
    return None


@app.post("/verify")
async def verify(file: UploadFile = File(...)) -> dict:
    """Blocking verification. `/verify/stream` is the same work, reported."""
    return _verify(_save(file))


@app.post("/verify/stream")
async def verify_stream(file: UploadFile = File(...)) -> dict:
    """Start a verification and return a job to watch it.

    An unfamiliar image is slow in a way that looks broken: a file destined
    for `no-record` still pays for all twenty-one correlations of the scale
    search, which can take over a minute with nothing on screen.
    """
    path = _save(file)

    def work(job: jobs.Job) -> None:
        def progress(label: str) -> None:
            # Weighted rather than even. The search is most of the wall clock,
            # so equal shares would sit at 40% for a minute and then jump --
            # the spinner problem with extra steps.
            fraction = 0.06
            if "residual" in label:
                fraction = 0.15
            elif "sensor space" in label or "lattice" in label:
                fraction = 0.80
            elif "searching" in label and " of " in label:
                try:
                    head = label.split("—")[1].split("(")[0].strip()
                    done, total = (int(x) for x in head.split(" of "))
                    fraction = 0.20 + 0.65 * (done / max(total, 1))
                except (ValueError, IndexError):
                    fraction = 0.5
            job.emit(event="step", label=label, fraction=round(fraction, 3))

        result = _verify(path, progress=progress)
        job.emit(event="step", label="reading the chain", fraction=0.97)
        job.finish(result)

    return {"jobId": jobs.start(work).id}


@app.get("/verify/{job_id}/events")
async def verify_events(job_id: str) -> StreamingResponse:
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


@app.post("/degrade")
async def degrade(
    file: UploadFile = File(...),
    longest_edge: int = Form(...),
    quality: int = Form(...),
    strip_metadata: bool = Form(True),
) -> StreamingResponse:
    """Demo step 4: strip, resize, re-encode -- live, not pre-baked.

    `quality` has no default on purpose. `docs/gates.md` measured 1800px at
    q95 scoring 408 and the same pixels at q80 scoring 37: the claim dies
    between them. A default here would hide the one number the demo depends
    on, and would let a presenter show the good rung without knowing they
    chose it.

    Metadata is dropped by re-encoding from the pixel buffer rather than by
    editing tags, so nothing survives in a container this code did not write.
    That is the point of the step -- the fingerprint is in the pixels, and it
    has to be the only thing that carries over.
    """
    import io

    from PIL import Image

    if not 1 <= quality <= 100:
        raise HTTPException(422, "quality must be 1-100")
    if longest_edge < 64:
        raise HTTPException(422, "longest_edge must be at least 64")

    path = _save(file)
    try:
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
        except OSError:
            image = stress.develop(path).convert("RGB")

        width, height = image.size
        if max(width, height) > longest_edge:
            scale = longest_edge / max(width, height)
            image = image.resize(
                (max(1, round(width * scale)), max(1, round(height * scale))),
                Image.LANCZOS,
            )

        buffer = io.BytesIO()
        # No exif= argument: a fresh encode from the pixel buffer carries none.
        image.save(buffer, format="JPEG", quality=quality)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="image/jpeg",
            headers={
                "Content-Disposition": 'attachment; filename="degraded.jpg"',
                "X-Genesis-Size": f"{image.size[0]}x{image.size[1]}",
                "X-Genesis-Quality": str(quality),
            },
        )
    finally:
        path.unlink(missing_ok=True)


#: Where folder browsing may look. The console is localhost-only and already
#: holds a signing key, but a filesystem listing is still a disclosure
#: surface, so it is rooted rather than open. Override for an archive that
#: lives elsewhere -- an external drive, which is where a photographer's forty
#: thousand frames usually are.
BROWSE_ROOT = Path(os.environ.get("GENESIS_BROWSE_ROOT", str(Path.home()))).resolve()


@app.get("/catalogue")
async def catalogue_listing(limit: int = 500) -> dict:
    """What this machine has registered, and how it scored.

    Local only. It holds file paths and free-text descriptions, neither of
    which may go near a network: a path is a map to a RAW file and a RAW file
    is a forgery kit, and a caption is unbounded personal data that would be
    permanent if published. `console/catalogue.py` has the reasoning.
    """
    return {"statistics": catalogue.statistics(), "images": catalogue.listing(limit)}


@app.post("/catalogue/describe")
async def catalogue_describe(image_hash: str = Form(...), description: str = Form(...)) -> dict:
    """Attach a caption to something already registered.

    Deliberately a separate call from registration. A photographer labels an
    archive long after importing it, and making the description part of
    registration would mean either writing it blind or not registering.
    """
    if not catalogue.describe(image_hash, description):
        raise HTTPException(404, f"nothing registered under {image_hash}")
    return {"imageHash": image_hash, "description": description}


@app.get("/browse")
async def browse(path: str | None = None) -> dict:
    """List folders under `BROWSE_ROOT`, with how many RAW frames each holds.

    A browser cannot give a server a filesystem path -- `webkitdirectory`
    hands over file *contents*, which for forty 24-megapixel CR3s means
    uploading well over a gigabyte to a service running on the same disk. So
    the server browses its own filesystem and enrolment keeps taking a path.

    The frame count is the point of the listing. Choosing an enrolment folder
    means choosing one with 40-50 RAW frames in it (`docs/gates.md`), and a
    folder picker that does not say which folders qualify has made the
    operator guess.
    """
    here = Path(path).resolve() if path else BROWSE_ROOT
    if not (here == BROWSE_ROOT or BROWSE_ROOT in here.parents):
        raise HTTPException(403, f"outside the browse root ({BROWSE_ROOT})")
    if not here.is_dir():
        raise HTTPException(404, f"{here} is not a directory")

    raw = record.hashing_raw_suffixes()
    entries = []
    try:
        for child in sorted(here.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            try:
                frames = sum(1 for f in child.iterdir() if f.suffix.lower() in raw)
            except PermissionError:
                frames = -1        # listed, but we cannot count inside it
            entries.append({"name": child.name, "path": str(child), "frames": frames})
    except PermissionError:
        raise HTTPException(403, f"cannot read {here}")

    return {
        "path": str(here),
        "parent": None if here == BROWSE_ROOT else str(here.parent),
        "frames": sum(1 for f in here.iterdir() if f.suffix.lower() in raw),
        "entries": entries,
    }


@app.post("/preview")
async def preview(file: UploadFile = File(...), longest_edge: int = Form(720)) -> StreamingResponse:
    """A browser-renderable thumbnail of any image the pipeline accepts.

    A browser cannot decode a CR3, so an `<img>` pointing at one renders
    nothing at all -- silently, with no error to notice. Every screen that
    shows the photograph it is working on therefore needs the RAW developed
    somewhere, and the only thing on this machine that can develop it is the
    scorer's own decoder.

    Display only. Nothing here feeds a hash, a score or a record: `/verify`
    and `/register-image` read the uploaded file, never this. A preview that
    could influence a verdict would be a second decode path to disagree with
    the first.
    """
    import io

    from PIL import Image

    path = _save(file)
    try:
        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
        except OSError:
            image = stress.develop(path).convert("RGB")

        image.thumbnail((longest_edge, longest_edge), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=82)
        buffer.seek(0)
        return StreamingResponse(
            buffer,
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )
    finally:
        path.unlink(missing_ok=True)


def _serials_disagree(frames: list[Path]) -> dict[str, list[str]]:
    """Group frames by camera serial, and return them only if there is disagreement.

    `docs/gates.md` makes `exiftool -SerialNumber` the first check on any file
    before it is scored, and the reason is measured: two files offered as
    other-body samples turned out to carry our own serial. The procedure said
    so and this endpoint did not do it, which mattered because the obvious
    folder to point it at -- the archive holding the enrolment frames -- also
    holds the two negatives kept for testing. Enrolling from there would have
    averaged a second R10 and a 5D Mark III into K and produced a fingerprint
    belonging to no camera at all, silently, with a plausible commitment.

    Frames whose serial cannot be read are not counted against the check: a
    missing tag is not evidence of a second body, and refusing on it would
    reject formats that simply do not carry one.
    """
    import subprocess
    from collections import defaultdict

    done = subprocess.run(
        ["exiftool", "-s3", "-SerialNumber", "-filename", "-T", *[str(f) for f in frames]],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        return {}  # no exiftool, or it failed: do not block enrolment on a missing tool

    by_serial: dict[str, list[str]] = defaultdict(list)
    for line in done.stdout.splitlines():
        serial, _, filename = line.partition("\t")
        serial = serial.strip()
        if serial and serial != "-":
            by_serial[serial].append(filename.strip())

    return dict(by_serial) if len(by_serial) > 1 else {}


@app.post("/enrol")
async def enrol(
    name: str = Form(...),
    folder: str = Form(default=""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    """Demo step 1. Returns a job id; progress streams from `/enrol/{id}/events`.

    Two ways in, and they exist for different callers. `files` is the console:
    the operating system's own file dialog, which is where a photographer
    already knows how to find their frames. `folder` is a server-side path,
    kept because scripts and the offline run use it and because forty RAW
    frames is half a gigabyte that nobody should upload twice.

    The reference path is never returned. Only the commitment leaves this
    process -- a published fingerprint is a published forgery kit, and so is
    a path that tells a browser where to ask for one (`docs/security.md`).
    """
    #: Uploaded frames land here and are removed when the job ends. Not a
    #: context manager: `work` runs on a thread that outlives this function,
    #: so the directory has to survive until the job says it is done.
    staged: tempfile.TemporaryDirectory | None = None

    if files:
        staged = tempfile.TemporaryDirectory(prefix="genesis-enrol-")
        source = Path(staged.name)
        for upload in files:
            # Names arrive from a browser. `Path(...).name` strips any
            # directory part, so a crafted filename cannot write outside here.
            safe = Path(upload.filename or "frame").name
            (source / safe).write_bytes(upload.file.read())
    elif folder:
        source = Path(folder).expanduser()
        if not source.is_dir():
            raise HTTPException(422, f"{folder} is not a directory")
    else:
        raise HTTPException(422, "choose some frames, or name a folder to enrol from")

    frames = sorted(
        p for p in source.iterdir() if p.suffix.lower() in record.hashing_raw_suffixes()
    )
    if not frames:
        if staged:
            staged.cleanup()
        raise HTTPException(
            422,
            "none of those files are RAW. Enrolment needs the camera's raw frames "
            "-- a developed JPEG has been through the camera's own noise reduction, "
            "which is the thing that removes the fingerprint.",
        )

    mixed = _serials_disagree(frames)
    if mixed:
        if staged:
            staged.cleanup()
        raise HTTPException(
            422,
            "this folder holds frames from more than one camera: "
            + "; ".join(f"{serial} ({', '.join(names)})" for serial, names in mixed.items())
            + ". Enrol one body at a time -- averaging two sensors produces a "
            "fingerprint belonging to neither.",
        )

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
    references.mkdir(parents=True, exist_ok=True)
    out = references / f"{name}.npz"

    def work(job: jobs.Job) -> None:
        try:
            _enrol(job)
        finally:
            # Half a gigabyte of someone's RAW frames. It goes whether the
            # enrolment succeeded or not.
            if staged:
                staged.cleanup()

    def _enrol(job: jobs.Job) -> None:
        job.emit(event="start", frames=len(frames), enough=len(frames) >= 40)

        def progress(index, total, path):
            job.emit(event="frame", index=index + 1, total=total, name=Path(path).name)

        k = prnu.postprocess(prnu.estimate_fingerprint(frames, progress=progress))
        meta = {
            "frames": len(frames),
            "crop": None,
            "cfa_pattern": prnu.cfa_pattern(frames[0]),
            "enrolled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "wavelet": prnu.WAVELET,
            "wavelet_levels": prnu.WAVELET_LEVELS,
            "commitment_version": prnu.COMMITMENT_VERSION.decode(),
        }
        prnu.save_fingerprint(out, k, meta)
        _bodies.cache_clear()

        digest = prnu.commitment(k)
        job.finish(
            {
                "name": name,
                "frames": len(frames),
                "commitment": "0x" + digest.hex(),
                "bodyId": "0x" + record.body_id(digest).hex(),
                "planes": {str(c): list(k[c].shape) for c in sorted(k)},
            }
        )

    job = jobs.start(work)
    return {"jobId": job.id, "frames": len(frames)}


@app.get("/enrol/{job_id}/events")
async def enrol_events(job_id: str) -> StreamingResponse:
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

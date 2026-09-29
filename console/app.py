"""The demo console API. Localhost only; it will hold a signing key.

    uvicorn console.app:app --host 127.0.0.1 --port 8100

Spec `docs/console-server.md`, posture `docs/security.md`. The signing
endpoints live in their own module (`console/registry.py`), so the boundary
is visible in the file listing.

This server does not verify. Verification runs in the app's webview on
`core/`, the code the public verify page runs too, so the console and the
page cannot disagree about what the pixels say (`docs/shared-verify-plan.md`).
What it serves for that is what a webview cannot do itself: the enrolled K
files, RAW decoding, and read-only proxies to the chain and the index.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from console import catalogue, chain, jobs, registry, subgraph
from fingerprint import prnu, stress
from ingest import record
import scoring.app as scoring_app
from scoring.app import _bodies

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
    # /raw/develop sends the image size in headers, which a browser hides
    # from cross-origin script unless they are exposed.
    expose_headers=["X-Width", "X-Height"],
    # WKWebView (the desktop app's webview) preflights every request from its
    # tauri:// page to this loopback server as Private Network Access and
    # fails closed without this -- Starlette answers 400 "Disallowed CORS
    # private-network" otherwise, which surfaces in the app as a bare "Load
    # failed" with nothing in this server's own log to point at why.
    allow_private_network=True,
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
#: commitSession, commit -- which on Sepolia or Base costs far under 0.01 ETH. The
#: handoff asked for 0.05, which the deployer's 0.0484 would fail for no real
#: reason.
#:
#: Bodies: one. Two would be better and needs a second physical camera
#: (`docs/e2e-checklist.md` §1), so gating the demo on it would gate it on
#: hardware nobody has.
MIN_BALANCE_WEI = 10**16          # 0.01 ETH
MIN_BODIES = 1
MAX_BLOCK_AGE = 60                # seconds; Sepolia blocks are ~12s, Base ~2s


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
        record("chain id", status["chainId"], f"{chain.EXPECTED_CHAIN_ID} {chain.CHAIN_NAME}",
               status["onExpectedChain"], f"point RPC_URL at {chain.CHAIN_NAME}")
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
        record("chain id", f"unreachable: {error}", f"{chain.EXPECTED_CHAIN_ID} {chain.CHAIN_NAME}",
               False, "check RPC_URL")
        status = {}

    deployer = os.environ.get("DEPLOYER_ADDRESS")
    if deployer:
        try:
            wei = chain.balance(deployer)
            record("deployer gas", f"{wei / 1e18:.4f} ETH",
                   f"at least {MIN_BALANCE_WEI / 1e18:.2f} ETH", wei >= MIN_BALANCE_WEI,
                   f"fund the deployer with {chain.CHAIN_NAME} ETH")
        except chain.ChainError as error:
            record("deployer gas", f"error: {error}", "balance readable", False)
    else:
        record("deployer gas", "DEPLOYER_ADDRESS unset", "an address to check", False,
               "set DEPLOYER_ADDRESS in .env")

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
        "registry": {"resettable": resettable, "epoch": epoch},
        # What core/ needs to read the chain through /rpc and the index
        # through /subgraph. No URLs: those stay on this side of the proxy.
        "verify": {
            "chain": chain.CHAIN_KEY,
            "registry": chain.REGISTRY or None,
            "explorer": chain.EXPLORER,
            "subgraph": bool(subgraph.SUBGRAPH_URL),
        },
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


# --- what core/ needs from this machine (docs/shared-verify-plan.md) ------
#
# Verification runs in the app's own webview now: core/, the same code the
# web page runs, so the two cannot disagree about a photo. This server
# supplies only what the webview cannot get itself -- the enrolled K files,
# RAW decoding (LibRaw has no WASM build), and the chain and the index behind
# a proxy that keeps any key in their URLs out of the webview. It no longer
# computes a verdict.


@app.get("/bodies")
async def bodies() -> list[dict]:
    """The enrolled bodies core/ scores against, and the crop a RAW decode must
    use for each (its `meta["crop"]`) so the planes line up with K."""
    return [
        {"id": body_id, "name": body["name"], "crop": body["meta"].get("crop")}
        for body_id, body in _bodies().items()
    ]


@app.get("/bodies/{body_id}/fingerprint")
async def fingerprint(body_id: str) -> FileResponse:
    """One body's K file, for core/ to score against in the app's webview.

    K never leaves the machine it was enrolled on (`docs/security.md`, "Where
    K lives"), and this keeps it there: the server binds to loopback, and CORS
    lets only the app's own origins read the response. The webview is on this
    machine; the web page on GitHub Pages never gets here.
    """
    body = _bodies().get(body_id.removeprefix("0x"))
    if body is None:
        raise HTTPException(404, f"no enrolled body {body_id}")
    # Read at call time, from the module _bodies() globs: the file served is
    # always from the directory the body list came from.
    path = scoring_app.REFERENCES / f"{body['name']}.npz"
    return FileResponse(path, media_type="application/octet-stream")


def _raw_upload(upload: UploadFile) -> Path:
    path = _save(upload)
    if path.suffix.lower() not in record.hashing_raw_suffixes():
        path.unlink(missing_ok=True)
        raise HTTPException(400, "not a RAW file; core/ decodes everything else itself")
    return path


@app.post("/raw/develop")
async def raw_develop(file: UploadFile = File(...)) -> Response:
    """A RAW's development as RGB8, row-major, with its size in headers.

    What `ingest/hashing.py` hashes for a RAW, and what the scale search reads
    when the RAW's planes do not line up with K. core/ hashes and scores these
    exact bytes, so the RAW path agrees with Python's by construction.
    """
    import numpy as np

    path = _raw_upload(file)
    try:
        rgb = np.ascontiguousarray(np.asarray(stress.develop(path).convert("RGB")))
    finally:
        path.unlink(missing_ok=True)
    return Response(
        rgb.tobytes(),
        media_type="application/octet-stream",
        headers={"X-Width": str(rgb.shape[1]), "X-Height": str(rgb.shape[0])},
    )


@app.post("/raw/planes")
async def raw_planes(file: UploadFile = File(...), crop: str = Form("none")) -> Response:
    """A RAW's CFA planes, cropped as one body's K was, as a `plane_<c>` .npz."""
    import io

    import numpy as np

    path = _raw_upload(file)
    try:
        planes = prnu.load_raw_planes(path, crop=None if crop == "none" else int(crop))
    finally:
        path.unlink(missing_ok=True)
    buffer = io.BytesIO()
    np.savez(buffer, **{f"plane_{c}": plane for c, plane in planes.items()})
    return Response(buffer.getvalue(), media_type="application/octet-stream")


#: The JSON-RPC methods core/ reads the registry with. Anything else is
#: refused: this proxy exists to keep the RPC URL's key out of the webview,
#: not to lend the webview a node.
READ_METHODS = {"eth_call", "eth_chainId", "eth_blockNumber"}


@app.post("/rpc")
async def rpc(request: Request) -> JSONResponse:
    """Forward read-only JSON-RPC to `RPC_URL`."""
    import httpx

    payload = await request.json()
    calls = payload if isinstance(payload, list) else [payload]
    refused = sorted({str(c.get("method")) for c in calls if c.get("method") not in READ_METHODS})
    if refused:
        raise HTTPException(403, f"read-only proxy: {', '.join(refused)} refused")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(chain.RPC_URL, json=payload)
    return JSONResponse(response.json(), status_code=response.status_code)


@app.post("/subgraph")
async def subgraph_proxy(request: Request) -> JSONResponse:
    """Forward a GraphQL query to `GENESIS_SUBGRAPH_URL`."""
    import httpx

    if not subgraph.SUBGRAPH_URL:
        raise HTTPException(503, "GENESIS_SUBGRAPH_URL is not set")
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(subgraph.SUBGRAPH_URL, json=await request.json())
    return JSONResponse(response.json(), status_code=response.status_code)


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

    Display only. Nothing here feeds a hash, a score or a record:
    verification (core/, from the file or `/raw/*`) and `/register-image`
    read the uploaded file, never this. A preview that
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

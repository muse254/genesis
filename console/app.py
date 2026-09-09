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


@app.get("/state")
async def state() -> dict:
    """The go/no-go gate, as rows a table renders without deciding anything.

    Everything here can fail on camera, and a presenter needs to see *which*
    part is down rather than that something is -- so this never raises, and
    every check carries what was measured, what was expected, and whether it
    passes. The frontend renders; it does not evaluate.
    """
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

    try:
        subgraph_ok = bool(subgraph.SUBGRAPH_URL)
    except Exception:
        subgraph_ok = False
    record("perceptual index", subgraph.SUBGRAPH_URL or "unset",
           "subgraph URL set", subgraph_ok,
           "set GENESIS_SUBGRAPH_URL; without it a degraded copy cannot find "
           "its original and step 4 falls back to fingerprint-only")

    return {
        "ready": all(c["go"] for c in checks),
        "checks": checks,
        "bodies": [b["name"] for b in bodies.values()],
        "threshold": prnu.PCE_THRESHOLD,
        "chain": status,
        "ensParent": parent or None,
    }


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
    except (ValueError, KeyError, OSError):
        pass  # advisory: a signal that cannot be computed is absent, not fatal
    return signals


@app.post("/verify")
async def verify(file: UploadFile = File(...)) -> dict:
    """The one verdict endpoint, and the only place `registered` is decided.

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
        raise HTTPException(503, "no enrolled fingerprints")

    path = _save(file)
    try:
        candidates = []
        for body_id, body in bodies.items():
            scored = _score_against(body, path)
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

        return payload
    finally:
        path.unlink(missing_ok=True)


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


@app.post("/enrol")
async def enrol(folder: str = Form(...), name: str = Form(...)) -> dict:
    """Demo step 1. Returns a job id; progress streams from `/enrol/{id}/events`.

    The reference path is never returned. Only the commitment leaves this
    process -- a published fingerprint is a published forgery kit, and so is
    a path that tells a browser where to ask for one (`docs/security.md`).
    """
    source = Path(folder).expanduser()
    if not source.is_dir():
        raise HTTPException(422, f"{folder} is not a directory")

    frames = sorted(
        p for p in source.iterdir() if p.suffix.lower() in record.hashing_raw_suffixes()
    )
    if not frames:
        raise HTTPException(422, f"no RAW frames in {folder}")

    references = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))
    references.mkdir(parents=True, exist_ok=True)
    out = references / f"{name}.npz"

    def work(job: jobs.Job) -> None:
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

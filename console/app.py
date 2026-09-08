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

from console import chain, jobs, registry
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


@app.get("/state")
async def state() -> dict:
    """Everything that can fail on camera, answered before recording starts.

    Deliberately never raises. A presenter needs to see *which* part is down,
    and an exception here would tell them only that something is.
    """
    report: dict = {"bodies": [b["name"] for b in _bodies().values()]}
    try:
        report["chain"] = chain.status()
    except chain.ChainError as error:
        report["chain"] = {"error": str(error)}

    deployer = os.environ.get("DEPLOYER_ADDRESS")
    if deployer:
        try:
            wei = chain.balance(deployer)
            report["deployer"] = {
                "address": deployer,
                "balanceWei": str(wei),
                "funded": wei > 0,
            }
        except chain.ChainError as error:
            report["deployer"] = {"address": deployer, "error": str(error)}

    report["ensParent"] = os.environ.get("ENS_PARENT_NAME")
    report["threshold"] = prnu.PCE_THRESHOLD
    report["ready"] = bool(
        report["bodies"]
        and report.get("chain", {}).get("onExpectedChain")
        and report.get("chain", {}).get("registry")
    )
    return report


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

        matched = best["pce"] >= prnu.PCE_THRESHOLD
        verdict = "registered" if registration else ("fingerprint-only" if matched else "no-record")

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
            "consistency": _signals(path, best["body"], best),
        }

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

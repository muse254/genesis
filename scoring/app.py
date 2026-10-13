"""FastAPI wrapper around the scorer: upload an image, get a PCE score and hashes.

    uvicorn scoring.app:app --reload

Holding references makes this the trust hole (you take its word for a PCE), so
the hosted instance runs ``GENESIS_PUBLIC=1``, holds no K and only hashes pixels;
scoring runs on the photographer's machine (`docs/security.md`, "Where K lives").
No chain reads here: the caller resolves hashes, so this never decides what is on chain.
"""

from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from fingerprint import prnu, stress
from ingest import hashing, record

#: Enrolled fingerprints, one ``.npz`` per body. K never leaves; only scores and hashes go out.
REFERENCES = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))

#: Public mode loads no reference, refuses to score, and refuses to start beside one,
#: so holding no K is by construction, not by configuration.
PUBLIC = os.environ.get("GENESIS_PUBLIC", "").strip() == "1"


def _refuse_references_in_public_mode() -> None:
    if PUBLIC and REFERENCES.is_dir() and any(REFERENCES.glob("*.npz")):
        raise RuntimeError(
            f"GENESIS_PUBLIC=1 but {REFERENCES} holds references. A public host "
            "must never hold K; move them off this machine."
        )


_refuse_references_in_public_mode()

app = FastAPI(title="Genesis scoring service")

#: The verify page is cross-origin. Wide open is fine: no secrets, no authority,
#: and K never appears in a response.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("GENESIS_ALLOW_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    # Else the desktop app's WKWebView gets its private-network preflight refused.
    allow_private_network=True,
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "public": PUBLIC, "bodies": len(_bodies())}


def _refuse_if_public() -> None:
    if PUBLIC:
        raise HTTPException(
            403,
            "this is the public service and it holds no fingerprints; scoring "
            "runs on the photographer's own machine",
        )


#: The loaded references, and the directory signature they were loaded from.
_BODY_CACHE: dict = {"signature": None, "bodies": {}}


def _signature() -> tuple:
    """Name, size and mtime of every `.npz`: cheap change detection for the cache."""
    return tuple(
        (p.name, p.stat().st_size, p.stat().st_mtime_ns)
        for p in sorted(REFERENCES.glob("*.npz"))
    )


def _bodies() -> dict:
    """Every enrolled body, cached (~90 MB each) and reloaded when the directory changes.

    The console may change enrolments from another process; a stale reference is worse than a slow load.
    """
    if PUBLIC:
        return {}
    signature = _signature()
    if _BODY_CACHE["signature"] == signature:
        return _BODY_CACHE["bodies"]

    found = {}
    for path in sorted(REFERENCES.glob("*.npz")):
        planes, meta = prnu.load_fingerprint(path)
        commitment = prnu.commitment(planes)
        found[record.body_id(commitment).hex()] = {
            "name": path.stem,
            "planes": planes,
            "meta": meta,
            "commitment": commitment.hex(),
        }
    _BODY_CACHE["signature"] = signature
    _BODY_CACHE["bodies"] = found
    return found


def _bodies_cache_clear() -> None:
    """Drop the cache outright."""
    _BODY_CACHE["signature"] = None
    _BODY_CACHE["bodies"] = {}


#: The tests call `_bodies.cache_clear()`.
_bodies.cache_clear = _bodies_cache_clear


def _save(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(upload.file.read())
    handle.close()
    return Path(handle.name)


def _score_against(body: dict, path: Path, progress=None) -> dict:
    """Score one image against one body: aligned per-plane if the lattice survives, else search.

    The pixels decide which path, not the uploader.
    """
    planes, meta = body["planes"], body["meta"]

    def step(label: str) -> None:
        if progress is not None:
            progress(label)

    step("reading the file")
    try:
        if path.suffix.lower() in record.hashing_raw_suffixes():
            probe = prnu.load_raw_planes(path, crop=meta.get("crop"))
        else:
            probe = prnu.load_delivered_planes(path, meta["cfa_pattern"])
        if all(probe[c].shape == planes[c].shape for c in planes if c in probe):
            step("correlating on the photosite lattice")
            return {"pce": prnu.score(probe, planes), "path": "aligned", "orientation": "0 deg"}
    except (ValueError, KeyError):
        pass  # fall through to the search, which assumes nothing about size

    # Portrait JPEGs are turned out of (landscape) sensor space. Rotating back
    # recovered PCE 810 vs 282 from the search on a real frame. Both directions
    # are tried (unknowable from pixels); extra tries raise the null
    # (`docs/gates.md`), so only for portrait probes after aligned failed.
    if path.suffix.lower() not in record.hashing_raw_suffixes():
        from PIL import Image

        Image.MAX_IMAGE_PIXELS = None
        try:
            with Image.open(path) as opened:
                turned = opened.size[1] > opened.size[0]
                source = opened.convert("RGB") if turned else None
        except OSError:
            source = None

        if source is not None:
            step("portrait capture — turning it back into sensor space")
            import tempfile as _tempfile

            best = None
            for angle in (270, 90):
                handle = _tempfile.NamedTemporaryFile(suffix=".png", delete=False)
                handle.close()
                rotated = Path(handle.name)
                try:
                    source.rotate(angle, expand=True).save(rotated)
                    candidate = prnu.load_delivered_planes(rotated, body["meta"]["cfa_pattern"])
                    if all(candidate[c].shape == planes[c].shape for c in planes if c in candidate):
                        pce = prnu.score(candidate, planes)
                        if best is None or pce > best[0]:
                            best = (pce, angle)
                except (ValueError, KeyError, OSError):
                    pass
                finally:
                    rotated.unlink(missing_ok=True)

            if best and best[0] >= prnu.PCE_THRESHOLD:
                return {
                    "pce": best[0],
                    "path": "aligned",
                    "orientation": f"{best[1]} deg",
                    "turned": "portrait capture, rotated back into sensor space",
                }

    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    if path.suffix.lower() in record.hashing_raw_suffixes():
        image = stress.develop(path)
    else:
        with Image.open(path) as opened:
            image = opened.convert("RGB")

    # A flat border breaks the uniform-scale search (measured: 200px white border
    # took PCE 90,846 to 37.9; stripping gave 86,097), so strip it first.
    bordered = image.size
    image = stress.strip_uniform_border(image)
    stripped = image.size != bordered

    step("extracting the noise residual")
    residual = prnu.noise_residual(stress.green_channel(image))

    # Twenty-one correlations (~a minute); report each so callers show a count.
    def searching(done: int, total: int, label: str) -> None:
        step(f"searching scale and orientation — {done + 1} of {total} ({label})")

    match = prnu.crop_and_scale_search(
        residual, prnu.sensor_field(planes), progress=searching if progress else None
    )
    return {
        "pce": match.pce,
        "path": "scale search",
        "orientation": match.orientation,
        "scale": match.scale,
        # A score after cropping is a different claim from one on the file as supplied.
        "borderStripped": f"{bordered[0]}x{bordered[1]} to {image.size[0]}x{image.size[1]}"
        if stripped
        else None,
    }


@app.post("/score")
async def score(file: UploadFile = File(...), body: str | None = Query(default=None)) -> dict:
    """Score an uploaded image against one known body (verification, not closed-set identification)."""
    _refuse_if_public()
    bodies = _bodies()
    if not bodies:
        raise HTTPException(503, f"no enrolled fingerprints in {REFERENCES}")
    if body is not None and body not in bodies:
        raise HTTPException(404, f"unknown body {body}")

    path = _save(file)
    try:
        target = body or next(iter(bodies))
        result = _score_against(bodies[target], path)
        return {
            "bodyId": target,
            "body": bodies[target]["name"],
            "threshold": prnu.PCE_THRESHOLD,
            "match": result["pce"] >= prnu.PCE_THRESHOLD,
            **result,
        }
    finally:
        path.unlink(missing_ok=True)


@app.post("/lookup")
async def lookup(file: UploadFile = File(...)) -> dict:
    """Hashes for the caller to resolve on chain, plus a PRNU verdict against every held body.

    In public mode ``candidates`` is empty and ``verdict`` is ``no-match``.
    """
    path = _save(file)
    try:
        candidates = []
        for body_id, body in _bodies().items():
            result = _score_against(body, path)
            candidates.append(
                {
                    "bodyId": body_id,
                    "body": body["name"],
                    "commitment": body["commitment"],
                    **result,
                }
            )
        candidates.sort(key=lambda c: -c["pce"])

        best = candidates[0] if candidates else None
        return {
            # The caller resolves these on chain; this service does not.
            "imageHash": "0x" + hashing.pixel_sha256(path).hex(),
            "perceptualHash": f"0x{hashing.perceptual_hash(path):016x}",
            "threshold": prnu.PCE_THRESHOLD,
            "verdict": "match" if best and best["pce"] >= prnu.PCE_THRESHOLD else "no-match",
            "candidates": candidates,
        }
    finally:
        path.unlink(missing_ok=True)


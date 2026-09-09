"""FastAPI wrapper around the scorer.

The verify page cannot run PRNU in the browser -- the scorer is Python and
there is no practical WASM path in 13 days. So: upload an image, get back a
PCE score and a registry lookup.

    uvicorn scoring.app:app --reload

This service is the trust hole in the design, and it is on purpose. The
Chainlink CRE confidential workflow (BUILD.md sec.11) eventually replaces
it: published algorithm, secret reference, signed score. That is the honest
reason CRE is in the architecture rather than a sponsor tick.

Chain reads are deliberately NOT here. The page does those with viem, so
this service never becomes the thing that decides what is on chain -- it
only reports what the pixels say.
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

#: Where enrolled fingerprints live. Each ``.npz`` is one body. K never
#: leaves this machine; only scores and hashes go out over HTTP.
REFERENCES = Path(os.environ.get("GENESIS_REFERENCES", "data/references"))

app = FastAPI(title="Genesis scoring service")

#: The verify page is served from a different origin -- Vite on 5173, or
#: wherever it ends up hosted -- so without this the browser refuses every
#: request and the page looks broken for a reason that never reaches the logs.
#: Wide open because this service holds no secrets and takes no authority: it
#: reads pixels and returns a number. The thing worth protecting is K, and K
#: never appears in a response.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("GENESIS_ALLOW_ORIGINS", "*").split(","),
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "bodies": len(_bodies())}


@lru_cache(maxsize=1)
def _bodies() -> dict:
    """Every enrolled body this service can score against.

    Cached: loading a fingerprint is ~90 MB off disk, and doing it per
    request would make the service unusable. Restart to pick up a new
    enrolment.
    """
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
    return found


def _save(upload: UploadFile) -> Path:
    suffix = Path(upload.filename or "upload").suffix or ".bin"
    handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    handle.write(upload.file.read())
    handle.close()
    return Path(handle.name)


def _score_against(body: dict, path: Path, progress=None) -> dict:
    """Score one image against one body, choosing the path the image needs.

    An untouched file still has its photosite lattice, so it can be scored
    plane by plane, which is both stronger and cheaper. A resized one has no
    lattice left and needs the scale and orientation search. Which applies
    is decided by the pixels, not by what the uploader claims.
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

    # A portrait capture is the common reason the shapes disagree. The sensor
    # is physically landscape and RAW is stored in sensor space, so a RAW is
    # unaffected -- but a developed JPEG has been turned, and the aligned path
    # cannot see past that. Turning it back is worth two correlations: on a
    # real portrait frame it recovers 810 where the scale search finds 282.
    #
    # Both directions are tried because only one is right and which one is not
    # knowable from the pixels: 270 gives 810 on that frame and 90 gives -32.
    # Two tries raise the null a little, as any search does (`docs/gates.md`),
    # which is why this is attempted only after the aligned path has already
    # failed and only for a probe that is actually portrait.
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

    # A flat margin defeats the search rather than the fingerprint: padding
    # changes the aspect ratio and `crop_and_scale_search` looks for a uniform
    # scale, so no factor maps the canvas back onto the lattice. Measured on a
    # real file, a 200px white border took 90,846 to 37.9 and cropping it back
    # gave 86,097. Bordered exports are ordinary, so strip before searching.
    bordered = image.size
    image = stress.strip_uniform_border(image)
    stripped = image.size != bordered

    step("extracting the noise residual")
    residual = prnu.noise_residual(stress.green_channel(image))

    # The expensive part, and the reason an unfamiliar image takes a minute:
    # twenty-one correlations, every one of which a file destined for
    # `no-record` still pays for. Reported per correlation so a caller can
    # show a count rather than a spinner.
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
        # Reported, because a score that only exists after cropping is a
        # different claim from one measured on the file as supplied.
        "borderStripped": f"{bordered[0]}x{bordered[1]} to {image.size[0]}x{image.size[1]}"
        if stripped
        else None,
    }


@app.post("/score")
async def score(file: UploadFile = File(...), body: str | None = Query(default=None)) -> dict:
    """Score an uploaded image against one registered body.

    Verification against a *known* body -- not closed-set identification
    among 126 sensors. That distinction is the whole answer to PRNU-Bench's
    73.65% (BUILD.md sec.2).
    """
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
    """Flow C: exact pixel-hash hit, else pHash candidates then PRNU re-score.

    Returns the hashes for the caller to resolve on chain and, when nothing
    resolves exactly, the PRNU verdict against every body this service holds.
    The exact branch dies the moment a platform re-encodes; the lower branch
    is the one that works on images that already left.
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

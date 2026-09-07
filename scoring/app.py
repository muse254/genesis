"""FastAPI wrapper around the scorer.

The verify page cannot run PRNU in the browser -- the scorer is Python and
there is no practical WASM path in 13 days. So: upload an image, get back a
PCE score and a registry lookup.

    uvicorn scoring.app:app --reload

This service is the trust hole in the design, and it is on purpose. The
Chainlink CRE confidential workflow (BUILD.md sec.11) eventually replaces
it: published algorithm, secret reference, signed score. That is the honest
reason CRE is in the architecture rather than a sponsor tick.
"""

from __future__ import annotations

from fastapi import FastAPI

app = FastAPI(title="certify-the-camera scoring service")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/score")
async def score():
    """Score an uploaded image against one registered body.

    Verification against a *known* body -- not closed-set identification
    among 126 sensors. That distinction is the whole answer to PRNU-Bench's
    73.65% (BUILD.md sec.2).
    """
    raise NotImplementedError


@app.post("/lookup")
async def lookup():
    """Flow C: exact pixel-hash hit, else pHash candidates then PRNU re-score."""
    raise NotImplementedError

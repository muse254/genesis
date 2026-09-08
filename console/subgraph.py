"""Perceptual-hash lookup, over the deployed subgraph.

This is the index that lets a *degraded* copy find the registration of the
original it descends from. An exact pixel hash dies the moment a platform
re-encodes; the perceptual hash survives, and the registry has no index on it,
so the subgraph is the index.

What this module does **not** do is decide anything. It returns a candidate
image hash. The caller then reads that hash off the chain, and only that read
may produce `registered` -- a perceptual match is a lookup, not a verdict, and
treating it as one would put the hole back that `acf3f87` closed.
"""

from __future__ import annotations

import os

import httpx

SUBGRAPH_URL = (
    os.environ.get("GENESIS_SUBGRAPH_URL") or os.environ.get("SUBGRAPH_URL") or ""
).strip()

#: Bits of the 64-bit pHash allowed to differ. Measured: on a real photograph
#: the hash moves *zero* bits from 1800px quality 95 down to 400px quality 60
#: (`AI-USE.md`), so this is slack rather than a tuned figure. Too wide and
#: unrelated photographs start colliding, which would attach a registration to
#: the wrong image -- a far worse failure than missing a match.
MAX_HAMMING = 10

QUERY = """
{ images(first: 1000) { id imageHash perceptualHash registeredAt } }
"""


class SubgraphError(RuntimeError):
    """The index could not answer. Surfaced, never swallowed into a verdict."""


def _bits(value: str) -> int:
    return int(value.removeprefix("0x") or "0", 16)


def nearest(perceptual_hash: str, timeout: float = 15.0) -> dict | None:
    """The registered image whose pHash is closest, if it is close enough.

    Returns ``{"imageHash", "distance"}`` or ``None``. A caller must still read
    the returned hash off the chain before saying anything about it.
    """
    if not SUBGRAPH_URL:
        raise SubgraphError("GENESIS_SUBGRAPH_URL is not set")

    try:
        response = httpx.post(SUBGRAPH_URL, json={"query": QUERY}, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as error:
        raise SubgraphError(f"subgraph unreachable: {error}") from error

    if "errors" in payload:
        raise SubgraphError(f"subgraph: {payload['errors']}")

    target = _bits(perceptual_hash)
    best = None
    for image in payload.get("data", {}).get("images", []):
        distance = bin(target ^ _bits(image["perceptualHash"])).count("1")
        if best is None or distance < best["distance"]:
            best = {"imageHash": image["imageHash"], "distance": distance}

    return best if best and best["distance"] <= MAX_HAMMING else None

"""Content hashes: ``pixel_sha256`` (exact identity) and ``perceptual_hash`` (survives re-encode).

Hash the PIXEL DATA, not the file bytes: stripping EXIF must not change
``image_hash``, or every record breaks on upload.
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

import numpy as np
from scipy.fft import dct

#: pHash DCT low-frequency block edge (8 -> 64-bit hash)
PHASH_DCT_SIZE = 8
#: image is reduced to this square before the DCT
PHASH_RESIZE = 32
#: Serialisation tag for :func:`pixel_sha256`. Same one-way door as the
#: fingerprint commitment: change it and every prior record stops matching.
PIXEL_HASH_VERSION = b"genesis-pixels-v1"


def _as_rgb8(image):
    """Canonical pixel form: 8-bit RGB, row-major, no metadata. RAWs are developed first."""
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None

    if isinstance(image, np.ndarray):
        array = image
    elif isinstance(image, (str, Path)):
        path = Path(image)
        if path.suffix.lower() in {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"}:
            from fingerprint import stress

            array = np.asarray(stress.develop(path).convert("RGB"))
        else:
            with Image.open(path) as im:
                array = np.asarray(im.convert("RGB"))
    else:  # a PIL image
        array = np.asarray(image.convert("RGB"))

    array = np.ascontiguousarray(array)
    if array.dtype != np.uint8:
        array = np.clip(array, 0, 255).astype(np.uint8)
    if array.ndim == 2:
        array = np.stack([array] * 3, axis=-1)
    return array


def pixel_sha256(image) -> bytes:
    """SHA-256 over version tag, shape and canonical pixels (shape stops dimension collisions)."""
    array = _as_rgb8(image)
    h = hashlib.sha256()
    h.update(PIXEL_HASH_VERSION)
    for dim in array.shape:
        h.update(int(dim).to_bytes(4, "big"))
    h.update(array.tobytes(order="C"))
    return h.digest()


def perceptual_hash(image) -> int:
    """DCT pHash: grey 32x32, keep the 8x8 low-frequency block, threshold at its median (DC excluded)."""
    from PIL import Image

    array = _as_rgb8(image)
    grey = Image.fromarray(array).convert("L").resize(
        (PHASH_RESIZE, PHASH_RESIZE), Image.LANCZOS
    )
    values = np.asarray(grey, dtype=np.float64)

    coefficients = dct(dct(values, axis=0, norm="ortho"), axis=1, norm="ortho")
    block = coefficients[:PHASH_DCT_SIZE, :PHASH_DCT_SIZE].flatten()

    median = np.median(block[1:])  # skip DC: it is brightness, not structure
    bits = 0
    for n, value in enumerate(block):
        if value > median:
            bits |= 1 << (len(block) - 1 - n)
    return bits


def hamming(a: int, b: int) -> int:
    """Bit distance between two perceptual hashes."""
    return int(a ^ b).bit_count()


#: Version tag for :func:`body_commitment`. Changing the scheme MUST change this,
#: so old commitments fail loudly instead of silently recomputing differently.
BODY_COMMITMENT_VERSION = b"genesis-body-v1"


def body_commitment(key: bytes, *, make, model, serial, owner=None, evidence=None) -> bytes:
    """Bind a bodyId to the physical camera without publishing its serial (length-prefixed HMAC-SHA256).

    Keyed, not a plain hash: serials are ~2^33, so SHA-256(serial) is enumerable.
    Revealed (serial + key) only in a dispute. Strengthens claim 1 in
    `docs/claims.md` only; says nothing about any image or forgery.
    ``evidence`` is a digest the photographer computes; we never see or verify
    the document, only timestamp it.
    """
    mac = hmac.new(key, digestmod=hashlib.sha256)
    mac.update(BODY_COMMITMENT_VERSION)
    if isinstance(evidence, str):
        evidence = bytes.fromhex(evidence.removeprefix("0x"))
    for field in (make, model, serial, owner, evidence):
        if field is None:
            encoded = b""
        elif isinstance(field, (bytes, bytearray)):
            encoded = bytes(field)
        else:
            encoded = str(field).encode("utf-8")
        mac.update(len(encoded).to_bytes(4, "big"))
        mac.update(encoded)
    return mac.digest()


def metadata_hmac(key: bytes, timestamp, geolocation, owner) -> bytes:
    """Length-prefixed HMAC-SHA256 over timestamp, geolocation and owner: commits without revealing."""
    mac = hmac.new(key, digestmod=hashlib.sha256)
    for field in (timestamp, geolocation, owner):
        encoded = b"" if field is None else str(field).encode("utf-8")
        mac.update(len(encoded).to_bytes(4, "big"))
        mac.update(encoded)
    return mac.digest()

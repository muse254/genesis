"""Content hashes for an image record.

Two hashes, doing two different jobs (BUILD.md sec.4, Flow C):

* ``pixel_sha256``  -- exact identity. Dies the moment a platform
  re-encodes. Cheap, and correct for files the photographer still holds.
* ``perceptual_hash`` -- survives resize and re-encode. This is the branch
  that makes the tool work on images that already left.

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
    """Canonical pixel form: 8-bit RGB, row-major, no metadata anywhere.

    A RAW is developed; anything else is read and converted. The point is
    that two files with identical pixels and different EXIF hash the same,
    which is the whole reason this hashes pixels rather than bytes.
    """
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
    """SHA-256 over canonicalised pixel data. Metadata is excluded by design.

    The digest covers a version tag and the image's shape as well as the
    bytes, so that two different rasters cannot collide by sharing a byte
    string at different dimensions.
    """
    array = _as_rgb8(image)
    h = hashlib.sha256()
    h.update(PIXEL_HASH_VERSION)
    for dim in array.shape:
        h.update(int(dim).to_bytes(4, "big"))
    h.update(array.tobytes(order="C"))
    return h.digest()


def perceptual_hash(image) -> int:
    """DCT-based pHash. ~40 lines; written here rather than taking `imagehash`.

    Reduce to a small grey square, take the 2-D DCT, keep the low-frequency
    block, and threshold it at its own median. Low frequencies are what
    survive a resize and a re-encode, which is exactly the branch this hash
    exists to serve. The DC term is dropped because it only carries overall
    brightness and would swamp the median.
    """
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


def body_commitment(key: bytes, *, make, model, serial, owner=None) -> bytes:
    """Bind a bodyId to the physical camera, without publishing its serial.

    HMAC-SHA256 over make, model, serial and owner, length-prefixed like
    :func:`metadata_hmac` so no two different tuples can collide by shuffling
    separators.

    **HMAC and not a plain hash, and that is the whole design.** A camera
    serial is low entropy -- Canon bodies are ten digits, about 2^33 -- so
    `SHA-256(serial)` is not a commitment at all. Anyone can enumerate the
    space in seconds and recover it, which would publish the serial of every
    registered body. Keyed, the space is unreachable without the key.

    Committed at enrolment, revealed only if the claim is ever contested: the
    photographer produces the serial and the key, and anyone recomputes this
    value and compares it against the record. That the commitment predates the
    dispute is what makes the reveal worth anything.

    What this binds and what it does not:

    - It binds a bodyId to a camera someone can physically produce. A
      photographer holding the body can demonstrate that the registration
      made at enrolment names *that* camera.
    - It says nothing about any image. A serial read out of a file's EXIF is
      worth nothing -- `docs/adversarial.md` writes `Canon EOS R10` into a
      forged DNG, and `SerialNumber` is as easy. Only a serial committed at
      enrolment and later checked against the physical body means anything.

    So this strengthens claim 1 in `docs/claims.md`, record integrity. It does
    nothing for claim 2 and nothing against forgery.
    """
    mac = hmac.new(key, digestmod=hashlib.sha256)
    for field in (make, model, serial, owner):
        encoded = b"" if field is None else str(field).encode("utf-8")
        mac.update(len(encoded).to_bytes(4, "big"))
        mac.update(encoded)
    return mac.digest()


def metadata_hmac(key: bytes, timestamp, geolocation, owner) -> bytes:
    """HMAC-SHA256 over timestamp, geolocation and owner.

    Commits without revealing -- which is how a photographer registers a
    geotagged frame without publishing where they stood (BUILD.md sec.5).

    Fields are length-prefixed before hashing so that no two different
    triples can produce the same input string by shuffling separators.
    """
    mac = hmac.new(key, digestmod=hashlib.sha256)
    for field in (timestamp, geolocation, owner):
        encoded = b"" if field is None else str(field).encode("utf-8")
        mac.update(len(encoded).to_bytes(4, "big"))
        mac.update(encoded)
    return mac.digest()

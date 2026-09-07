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

#: pHash DCT low-frequency block edge (8 -> 64-bit hash)
PHASH_DCT_SIZE = 8
#: image is reduced to this square before the DCT
PHASH_RESIZE = 32


def pixel_sha256(image) -> bytes:
    """SHA-256 over canonicalised pixel data. Metadata is excluded by design."""
    raise NotImplementedError


def perceptual_hash(image) -> int:
    """DCT-based pHash. ~40 lines; written here rather than taking `imagehash`."""
    raise NotImplementedError


def hamming(a: int, b: int) -> int:
    """Bit distance between two perceptual hashes."""
    raise NotImplementedError


def metadata_hmac(key: bytes, timestamp, geolocation, owner) -> bytes:
    """HMAC-SHA256 over timestamp, geolocation and owner.

    Commits without revealing -- which is how a photographer registers a
    geotagged frame without publishing where they stood (BUILD.md sec.5).
    """
    raise NotImplementedError

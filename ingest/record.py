"""Birthmark-shaped image records plus a PRNU attestation.

We adopt the Birthmark record field-for-field and substitute two fields
(BUILD.md sec.5):

* manufacturer certificate -> PCE score against a privately held fingerprint
* in-camera ECDSA signature -> ingest-time signing on the photographer's
  machine. This is genuinely weaker than signing inside the body, and the
  README says so rather than hoping nobody asks.

``modification_level``: 0 raw | 1 exposure/WB/denoise/crop | 2 clone,
object removal, generative fill. These map onto the editing rules photo
competitions already publish, which is why the scale is worth keeping.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BodyRecord:
    """One enrolled camera body. Mirrors the Solidity struct."""

    fingerprint_commitment: bytes  # hash of K -- never K itself
    owner: str
    ens_node: bytes
    revoked: bool = False


@dataclass
class ImageRecord:
    """One registered photograph. Mirrors the Solidity struct."""

    image_hash: bytes
    perceptual_hash: bytes
    body_id: bytes
    modification_level: int  # 0 | 1 | 2
    parent_image_hash: bytes  # 0x0 for originals -- this is the edit graph
    metadata_hmac: bytes
    pce_score: int
    registered_at: int


def build_record(image_path, fingerprint, *, parent=None, modification_level=0) -> ImageRecord:
    """Score an image against its body and assemble the record."""
    raise NotImplementedError


def sign_record(record: ImageRecord, private_key: bytes) -> bytes:
    """ECDSA secp256k1 over the record's canonical encoding.

    Ingest-time, on the photographer's machine. Attests custody at import,
    not capture -- do not let the pitch blur those.
    """
    raise NotImplementedError


def to_erc7053_commit(record: ImageRecord) -> dict:
    """Shape a record into an ERC-7053 ``commit()`` call.

    ERC-7053 defines the index and explicitly declines to validate the
    content behind the CIDs. PRNU is that validation.
    """
    raise NotImplementedError

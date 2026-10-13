"""Birthmark-shaped image records with a PRNU attestation.

Substitutes PCE score for the manufacturer certificate, and ingest-time signing
for in-camera ECDSA (weaker: attests custody, not capture).
``modification_level``: 0 raw | 1 exposure/WB/denoise/crop | 2 clone/removal/generative fill.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from eth_hash.auto import keccak

from fingerprint import prnu
from ingest import hashing

#: Canonical encoding tag. Signatures and body ids are computed over this,
#: so changing it invalidates every signature already issued.
RECORD_VERSION = b"genesis-record-v1"


@dataclass
class BodyRecord:
    """One enrolled camera body. Mirrors the Solidity struct."""

    fingerprint_commitment: bytes  # hash of K -- never K itself
    owner: str
    body_commitment: bytes  # ingest.hashing.body_commitment, or zero for none
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


def body_id(fingerprint_commitment: bytes) -> bytes:
    """On-chain body id, derived from the commitment; reveals nothing about K beyond it."""
    return keccak(RECORD_VERSION + b"body" + bytes(fingerprint_commitment))


def build_record(
    image_path,
    fingerprint,
    *,
    parent=None,
    modification_level=0,
    hmac_key=None,
    timestamp=None,
    geolocation=None,
    owner=None,
    score=None,
) -> ImageRecord:
    """Score an image against its body and assemble the record.

    Parameters
    ----------
    image_path : str | Path
        The photograph to register. RAW or delivered.
    fingerprint : str | Path | tuple
        A saved ``.npz``, or the ``(planes, meta)`` pair
        :func:`prnu.load_fingerprint` returns.
    score : float, optional
        A PCE from `scoring.app._score_against`. Pass it for portrait or scaled
        frames: scoring here is the aligned path only, and using that answer
        keeps registration agreeing with verification (core/).
    parent : bytes, optional
        ``image_hash`` this was edited from; absent for an original.
    modification_level : int
        0 raw, 1 exposure/WB/denoise/crop, 2 clone/removal/generative fill.
    hmac_key, timestamp, geolocation, owner
        Fed to :func:`hashing.metadata_hmac`. Without a key the field is zero.

    Returns an unsigned ImageRecord; :func:`sign_record` is a separate step.
    """
    if isinstance(fingerprint, (str, Path)):
        planes, meta = prnu.load_fingerprint(fingerprint)
    else:
        planes, meta = fingerprint

    path = Path(image_path)
    if score is None:
        if path.suffix.lower() in hashing_raw_suffixes():
            probe = prnu.load_raw_planes(path, crop=meta.get("crop"))
        else:
            pattern = meta.get("cfa_pattern")
            if pattern is None:
                raise ValueError("fingerprint has no CFA pattern; a delivered image needs one")
            probe = prnu.load_delivered_planes(path, pattern)
        score = prnu.score(probe, planes)
    else:
        score = float(score)
    commitment = prnu.commitment(planes)

    return ImageRecord(
        image_hash=hashing.pixel_sha256(path),
        perceptual_hash=hashing.perceptual_hash(path).to_bytes(8, "big"),
        body_id=body_id(commitment),
        modification_level=int(modification_level),
        parent_image_hash=bytes(parent) if parent else bytes(32),
        metadata_hmac=(
            hashing.metadata_hmac(hmac_key, timestamp, geolocation, owner)
            if hmac_key
            else bytes(32)
        ),
        # uint32 on chain; a negative score is a non-match, so floor at zero.
        pce_score=max(0, min(int(round(score)), 2**32 - 1)),
        registered_at=int(timestamp if isinstance(timestamp, (int, float)) else time.time()),
    )


def hashing_raw_suffixes():
    return {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"}


def canonical_bytes(record: ImageRecord) -> bytes:
    """The exact bytes a signature covers: fixed order and widths, no JSON."""
    parts = [
        RECORD_VERSION,
        record.image_hash,
        record.perceptual_hash,
        record.body_id,
        record.modification_level.to_bytes(1, "big"),
        record.parent_image_hash,
        record.metadata_hmac,
        record.pce_score.to_bytes(4, "big"),
        record.registered_at.to_bytes(8, "big"),
    ]
    return b"".join(parts)


def sign_record(record: ImageRecord, private_key: bytes) -> bytes:
    """ECDSA secp256k1 over the canonical encoding. Attests custody at import, not capture."""
    from eth_keys import keys

    key = keys.PrivateKey(bytes(private_key))
    return key.sign_msg(canonical_bytes(record)).to_bytes()


def recover_signer(record: ImageRecord, signature: bytes) -> str:
    """The address that signed a record, or a raised error if it did not."""
    from eth_keys import keys

    sig = keys.Signature(bytes(signature))
    return sig.recover_public_key_from_msg(canonical_bytes(record)).to_checksum_address()


def to_erc7053_commit(record: ImageRecord, asset_cid: str | None = None) -> dict:
    """Shape a record into an ERC-7053 ``commit()`` call, PCE included as the content validation.

    Without ``asset_cid``, a local ``genesis:`` URI over the pixel hash stands in.
    """
    return {
        "assetCid": asset_cid or f"genesis:{record.image_hash.hex()}",
        "commitData": json.dumps(
            {
                "version": RECORD_VERSION.decode(),
                **{
                    key: value.hex() if isinstance(value, bytes) else value
                    for key, value in asdict(record).items()
                },
            },
            separators=(",", ":"),
            sort_keys=True,
        ),
    }

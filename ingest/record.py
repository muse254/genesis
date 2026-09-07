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


def body_id(fingerprint_commitment: bytes) -> bytes:
    """The on-chain identifier for a body, derived from its commitment.

    Derived rather than assigned: two people enrolling the same camera reach
    the same id, and the id reveals nothing about K beyond what the
    commitment already does.
    """
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
) -> ImageRecord:
    """Score an image against its body and assemble the record.

    Parameters
    ----------
    image_path : str | Path
        The photograph to register. RAW or delivered.
    fingerprint : str | Path | tuple
        A saved ``.npz``, or the ``(planes, meta)`` pair
        :func:`prnu.load_fingerprint` returns.
    parent : bytes, optional
        ``image_hash`` of the original this was edited from. Absent for an
        original, which is what makes the records an edit graph rather than
        a list.
    modification_level : int
        0 raw, 1 exposure/WB/denoise/crop, 2 clone/removal/generative fill.
    hmac_key, timestamp, geolocation, owner
        Fed to :func:`hashing.metadata_hmac`. Without a key the field is
        zero, which says "nothing committed" rather than "nothing to hide".

    Returns
    -------
    ImageRecord
        Unsigned. :func:`sign_record` is a separate step because the score
        is evidence and the signature is custody, and they are made at
        different moments by different parties.
    """
    if isinstance(fingerprint, (str, Path)):
        planes, meta = prnu.load_fingerprint(fingerprint)
    else:
        planes, meta = fingerprint

    path = Path(image_path)
    if path.suffix.lower() in hashing_raw_suffixes():
        probe = prnu.load_raw_planes(path, crop=meta.get("crop"))
    else:
        pattern = meta.get("cfa_pattern")
        if pattern is None:
            raise ValueError("fingerprint has no CFA pattern; a delivered image needs one")
        probe = prnu.load_delivered_planes(path, pattern)

    score = prnu.score(probe, planes)
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
        # uint32 on chain, and a negative score is a non-match rather than a
        # small one, so it floors at zero.
        pce_score=max(0, min(int(round(score)), 2**32 - 1)),
        registered_at=int(timestamp if isinstance(timestamp, (int, float)) else time.time()),
    )


def hashing_raw_suffixes():
    return {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"}


def canonical_bytes(record: ImageRecord) -> bytes:
    """The exact bytes a signature covers.

    Fixed field order, fixed widths, no JSON: a signature over a
    pretty-printed dictionary is a signature over whitespace.
    """
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
    """ECDSA secp256k1 over the record's canonical encoding.

    Ingest-time, on the photographer's machine. Attests custody at import,
    not capture -- do not let the pitch blur those. A camera that signed
    inside the body would attest capture; this cannot, and the claim has to
    stop where the evidence does.
    """
    from eth_keys import keys

    key = keys.PrivateKey(bytes(private_key))
    return key.sign_msg(canonical_bytes(record)).to_bytes()


def recover_signer(record: ImageRecord, signature: bytes) -> str:
    """The address that signed a record, or a raised error if it did not."""
    from eth_keys import keys

    sig = keys.Signature(bytes(signature))
    return sig.recover_public_key_from_msg(canonical_bytes(record)).to_checksum_address()


def to_erc7053_commit(record: ImageRecord, asset_cid: str | None = None) -> dict:
    """Shape a record into an ERC-7053 ``commit()`` call.

    ERC-7053 defines the index and explicitly declines to validate the
    content behind the CIDs. PRNU is that validation, and it travels in the
    commit data as ``pce_score`` so an indexer can see what the claim rests
    on without fetching anything.

    ``asset_cid`` is the caller's if they have pinned the record somewhere.
    Absent that, a ``genesis:`` URI over the pixel hash stands in -- honest
    about being local rather than a CID that resolves to nothing.
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

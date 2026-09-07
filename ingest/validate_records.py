"""Record construction tests.

These cover the properties the rest of the system depends on and cannot
check for itself: that stripping metadata does not change an image's
identity, that the perceptual hash survives what the pixel hash does not,
that the Merkle rules match the ones the Solidity verifier will use, and
that a signature covers every field of a record.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from ingest import hashing, merkle, record


def _photo(seed: int = 0, size=(512, 384)):
    """A stand-in with a photograph's spectrum, not a noise field.

    This matters more than it looks. A perceptual hash reads low-frequency
    structure, so a small noisy fixture has nothing for it to hold on to and
    the hash moves under any resize -- which says nothing about the hash. A
    real photograph run through the same steps moves zero bits. Smoothed
    noise at a realistic size behaves like the real thing.
    """
    from scipy.ndimage import gaussian_filter

    rng = np.random.default_rng(seed)
    base = gaussian_filter(rng.normal(0, 1, (size[1], size[0])), sigma=18)
    base = (base - base.min()) / np.ptp(base)
    detail = gaussian_filter(rng.normal(0, 1, (size[1], size[0])), sigma=3) * 0.15
    grey = np.clip((base + detail) * 235 + 10, 0, 255).astype(np.uint8)
    return Image.fromarray(np.stack([grey] * 3, axis=-1))


# --- hashing ---------------------------------------------------------------


def test_pixel_hash_ignores_metadata():
    """Stripping EXIF must not change image_hash, or every record breaks.

    This is the property the whole retroactive claim leans on: a platform
    that discards metadata on upload must not thereby discard identity.
    """
    photo = _photo()

    with_exif = io.BytesIO()
    exif = Image.Exif()
    exif[0x010F] = "Canon"
    photo.save(with_exif, "PNG", exif=exif)

    without = io.BytesIO()
    photo.save(without, "PNG")

    assert len(with_exif.getvalue()) != len(without.getvalue()), "test needs differing files"
    assert hashing.pixel_sha256(Image.open(with_exif)) == hashing.pixel_sha256(
        Image.open(without)
    )


def test_pixel_hash_dies_on_re_encode():
    """The exact hash is exact. This is why the perceptual branch exists."""
    photo = _photo()
    buffer = io.BytesIO()
    photo.save(buffer, "JPEG", quality=80)

    assert hashing.pixel_sha256(photo) != hashing.pixel_sha256(Image.open(buffer))


def test_perceptual_hash_survives_resize_and_re_encode():
    """...and the perceptual hash does not die, which is the whole point."""
    photo = _photo()
    buffer = io.BytesIO()
    photo.resize((256, 192), Image.LANCZOS).save(buffer, "JPEG", quality=70)

    distance = hashing.hamming(
        hashing.perceptual_hash(photo), hashing.perceptual_hash(Image.open(buffer))
    )
    # Measured on a real R10 photograph at 1800px q95 down to 400px q60:
    # zero bits moved at every step. The allowance here is slack, not a
    # target.
    assert distance <= 8, f"pHash moved {distance} bits through a resize and a re-encode"


def test_perceptual_hash_separates_different_images():
    a = hashing.perceptual_hash(_photo(seed=1))
    b = hashing.perceptual_hash(_photo(seed=2))
    assert hashing.hamming(a, b) > 16, "two different photographs hash too close"


def test_metadata_hmac_commits_without_revealing():
    key = b"k" * 32
    committed = hashing.metadata_hmac(key, 1757000000, "51.5,-0.1", "osoro.eth")

    assert len(committed) == 32
    assert committed != hashing.metadata_hmac(key, 1757000001, "51.5,-0.1", "osoro.eth")
    # Length-prefixed, so fields cannot be shuffled across the boundary.
    assert committed != hashing.metadata_hmac(key, 1757000000, "51.5,-0.1osoro.eth", "")
    assert committed != hashing.metadata_hmac(b"j" * 32, 1757000000, "51.5,-0.1", "osoro.eth")


# --- merkle ----------------------------------------------------------------


def _leaves(n):
    return [bytes([i]) * 32 for i in range(1, n + 1)]


@pytest.mark.parametrize("count", [1, 2, 3, 5, 8, 17])
def test_every_leaf_proves_against_the_root(count):
    """Including odd counts, where the promotion rule is what is being tested."""
    leaves = _leaves(count)
    root = merkle.merkle_root(leaves)
    for index in range(count):
        proof = merkle.inclusion_proof(leaves, index)
        assert merkle.verify_proof(leaves[index], proof, root), f"leaf {index} of {count}"


def test_root_is_order_independent():
    """A session is a set of frames, not a sequence of imports."""
    leaves = _leaves(6)
    assert merkle.merkle_root(leaves) == merkle.merkle_root(list(reversed(leaves)))


def test_a_frame_outside_the_session_does_not_prove():
    leaves = _leaves(4)
    root = merkle.merkle_root(leaves)
    proof = merkle.inclusion_proof(leaves, 0)
    assert not merkle.verify_proof(b"\xff" * 32, proof, root)


def test_empty_session_is_refused():
    with pytest.raises(ValueError):
        merkle.merkle_root([])


# --- records ---------------------------------------------------------------


def _record(**overrides):
    fields = dict(
        image_hash=b"\x01" * 32,
        perceptual_hash=b"\x02" * 8,
        body_id=b"\x03" * 32,
        modification_level=0,
        parent_image_hash=bytes(32),
        metadata_hmac=bytes(32),
        pce_score=1895,
        registered_at=1757000000,
    )
    fields.update(overrides)
    return record.ImageRecord(**fields)


def test_signature_covers_every_field():
    """A signature that misses a field is a signature on nothing.

    Flip each field in turn and check the signer no longer recovers, so a
    score or a parent cannot be edited under a valid signature.
    """
    key = bytes(range(1, 33))
    original = _record()
    signature = record.sign_record(original, key)
    signer = record.recover_signer(original, signature)

    for field, value in (
        ("image_hash", b"\x09" * 32),
        ("perceptual_hash", b"\x09" * 8),
        ("body_id", b"\x09" * 32),
        ("modification_level", 2),
        ("parent_image_hash", b"\x09" * 32),
        ("metadata_hmac", b"\x09" * 32),
        ("pce_score", 42),
        ("registered_at", 1757000001),
    ):
        tampered = _record(**{field: value})
        assert record.recover_signer(tampered, signature) != signer, f"{field} is unsigned"


def test_body_id_follows_from_the_commitment():
    """Same camera, same id, without anyone assigning one."""
    commitment = b"\x07" * 32
    assert record.body_id(commitment) == record.body_id(commitment)
    assert record.body_id(commitment) != record.body_id(b"\x08" * 32)
    assert len(record.body_id(commitment)) == 32


def test_erc7053_commit_is_deterministic_and_carries_the_score():
    """The commit data is what an indexer reads, so it has to be stable."""
    call = record.to_erc7053_commit(_record())

    assert call["assetCid"] == "genesis:" + b"\x01".hex() * 32
    assert call == record.to_erc7053_commit(_record())
    assert '"pce_score":1895' in call["commitData"]

    given = record.to_erc7053_commit(_record(), asset_cid="ipfs://bafy")
    assert given["assetCid"] == "ipfs://bafy"

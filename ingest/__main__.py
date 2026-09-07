"""CLI for record construction: `python -m ingest record ...`

Emits a record as JSON with 0x-prefixed fields, which is the shape `cast`
wants. This is the seam between the imaging half of the project, which is
Python, and the chain half, which is not.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # invoked as a script rather than a module
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fingerprint import prnu  # noqa: E402
from ingest import hashing, merkle, record  # noqa: E402


def _hex(value, width=None):
    text = bytes(value).hex()
    return "0x" + (text.rjust(width * 2, "0") if width else text)


def cmd_record(args) -> int:
    """Build a record for one image and print it as JSON."""
    planes, meta = prnu.load_fingerprint(args.fingerprint)
    commitment = prnu.commitment(planes)

    built = record.build_record(
        args.image,
        (planes, meta),
        parent=bytes.fromhex(args.parent[2:]) if args.parent else None,
        modification_level=args.modification_level,
        hmac_key=args.hmac_key.encode() if args.hmac_key else None,
        geolocation=args.geolocation,
        owner=args.owner,
    )

    payload = {
        "commitment": _hex(commitment),
        "bodyId": _hex(built.body_id),
        "imageHash": _hex(built.image_hash),
        # bytes8 on the Python side, bytes32 in the struct
        "perceptualHash": _hex(built.perceptual_hash, width=32),
        "modificationLevel": built.modification_level,
        "parentImageHash": _hex(built.parent_image_hash),
        "metadataHmac": _hex(built.metadata_hmac),
        "pceScore": built.pce_score,
        "registeredAt": built.registered_at,
        "matched": built.pce_score >= prnu.PCE_THRESHOLD,
        "threshold": prnu.PCE_THRESHOLD,
    }
    payload["erc7053"] = record.to_erc7053_commit(built)

    if args.session:
        leaves = [built.image_hash] + [hashing.pixel_sha256(p) for p in args.session]
        payload["sessionRoot"] = _hex(merkle.merkle_root(leaves))
        payload["sessionProof"] = [_hex(p) for p in merkle.inclusion_proof(leaves, 0)]
        payload["sessionFrames"] = len(leaves)

    json.dump(payload, sys.stdout, indent=1)
    print()
    return 0 if payload["matched"] else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="ingest", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    r = sub.add_parser("record", help="build a record for one image")
    r.add_argument("image")
    r.add_argument("--fingerprint", required=True)
    r.add_argument("--parent", help="0x-prefixed image hash this was edited from")
    r.add_argument("--modification-level", type=int, default=0, choices=(0, 1, 2))
    r.add_argument("--hmac-key", help="key for the metadata commitment")
    r.add_argument("--geolocation")
    r.add_argument("--owner")
    r.add_argument("--session", nargs="*", help="other frames in the same import")
    r.set_defaults(func=cmd_record)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

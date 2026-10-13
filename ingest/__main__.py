"""CLI for record construction: `python -m ingest record ...`

and for the camera commitment a body is registered with:
`python -m ingest commit-body ...`

Emits a record as JSON with 0x-prefixed fields, which is the shape `cast`
wants. This is the seam between the imaging half of the project, which is
Python, and the chain half, which is not.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import secrets
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


def _body_key(path: Path) -> bytes:
    """Read the photographer's commitment key, or create it once (0600, never printed).

    Lost: the commitment can't be revealed. Leaked: the serial is enumerable again.
    """
    if path.exists():
        key = path.read_bytes()
        if len(key) != 32:
            raise SystemExit(f"{path} is {len(key)} bytes; a commitment key is 32")
        return key
    key = secrets.token_bytes(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(key)
    print(f"created {path} -- back it up; a dispute cannot be answered without it",
          file=sys.stderr)
    return key


def cmd_commit_body(args) -> int:
    """Print the keyed camera commitment `registerBody` takes.

    Serial is prompted (keeps it out of shell history); serial and key never leave this machine.
    """
    serial = args.serial or getpass.getpass("camera serial (not echoed): ").strip()
    if not serial:
        raise SystemExit("a serial is required")
    evidence = None
    if args.evidence:
        evidence = hashlib.sha256(Path(args.evidence).read_bytes()).digest()
    digest = hashing.body_commitment(
        _body_key(Path(args.key_file).expanduser()),
        make=args.make, model=args.model, serial=serial,
        owner=args.owner, evidence=evidence,
    )
    print(_hex(digest))
    return 0


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

    c = sub.add_parser("commit-body", help="the keyed camera commitment for registerBody")
    c.add_argument("--make", required=True, help='e.g. "Canon"')
    c.add_argument("--model", required=True, help='e.g. "EOS R10"')
    c.add_argument("--serial", help="omit to be prompted, which keeps it out of shell history")
    c.add_argument("--owner", help="who the camera belongs to, as they will name themselves in a dispute")
    c.add_argument("--evidence", help="a file (receipt, insurance schedule) to commit a SHA-256 of")
    c.add_argument("--key-file", default="~/.genesis/body-commitment.key",
                   help="32-byte key; created if missing (default: %(default)s)")
    c.set_defaults(func=cmd_commit_body)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

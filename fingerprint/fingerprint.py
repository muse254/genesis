"""CLI for the imaging core: enroll | test | pair | demo.

    python3 fingerprint/fingerprint.py demo                       # sanity check
    python3 fingerprint/fingerprint.py pair --crop 1024 flats/*.CR3
    python3 fingerprint/fingerprint.py enroll --out r10.npz flats/*.CR3
    python3 fingerprint/fingerprint.py test --fingerprint r10.npz shoot/*.CR3

`demo` must PASS before anything else in this repo is worth running.
"""

from __future__ import annotations

import argparse
import sys


def cmd_enroll(args) -> int:
    """Build K from a folder of RAW frames and write it to --out.

    Archive-scan mode (day 5): walk a directory, resume from a partial run,
    report progress. A photographer's archive is tens of thousands of frames.
    """
    raise NotImplementedError


def cmd_test(args) -> int:
    """Score images against a saved fingerprint; print PCE per file.

    With --crop-scale, runs the Gate B search so web-mangled JPEGs still
    resolve.
    """
    raise NotImplementedError


def cmd_pair(args) -> int:
    """Two-frame quick look -- cheap Gate A signal before a full enrolment."""
    raise NotImplementedError


def cmd_demo(args) -> int:
    """End-to-end run on the synthetic sensor. No camera required."""
    raise NotImplementedError


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fingerprint", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    e = sub.add_parser("enroll", help="build a fingerprint from RAW frames")
    e.add_argument("images", nargs="+")
    e.add_argument("--out", required=True)
    e.add_argument("--crop", type=int, default=None)
    e.set_defaults(func=cmd_enroll)

    t = sub.add_parser("test", help="score images against a fingerprint")
    t.add_argument("images", nargs="+")
    t.add_argument("--fingerprint", required=True)
    t.add_argument("--crop-scale", action="store_true", help="Gate B search")
    t.set_defaults(func=cmd_test)

    r = sub.add_parser("pair", help="two-frame quick look")
    r.add_argument("images", nargs=2)
    r.add_argument("--crop", type=int, default=1024)
    r.set_defaults(func=cmd_pair)

    d = sub.add_parser("demo", help="synthetic end-to-end sanity check")
    d.set_defaults(func=cmd_demo)

    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

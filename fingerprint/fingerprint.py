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
import time
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):  # invoked as a script, not as -m fingerprint
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fingerprint import prnu  # noqa: E402


def cmd_enroll(args) -> int:
    """Build K from a folder of RAW frames and write it to --out.

    Archive-scan mode (day 5): walk a directory, resume from a partial run,
    report progress. A photographer's archive is tens of thousands of frames.
    """
    paths = _expand(args.images)
    if len(paths) < 40:
        print(
            f"warning: {len(paths)} frames. Gate A asks for 40-50 -- K will be "
            "noisier than the enrolment procedure intends.",
            file=sys.stderr,
        )

    started = time.time()

    def progress(n, total, path):
        print(f"  [{n + 1:>3}/{total}] {Path(path).name}", file=sys.stderr)

    k = prnu.estimate_fingerprint(paths, crop=args.crop, progress=progress)
    k = prnu.postprocess(k)

    meta = {
        "frames": len(paths),
        "crop": args.crop,
        "cfa_pattern": prnu.cfa_pattern(paths[0]),
        "enrolled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "wavelet": prnu.WAVELET,
        "wavelet_levels": prnu.WAVELET_LEVELS,
        "commitment_version": prnu.COMMITMENT_VERSION.decode(),
    }
    prnu.save_fingerprint(args.out, k, meta)

    print(f"\nenrolled {len(paths)} frames in {time.time() - started:.1f}s")
    for c in sorted(k):
        print(f"  CFA plane {c}: {k[c].shape[0]}x{k[c].shape[1]}")
    print(f"  written to {args.out}")
    print(f"  commitment {prnu.commitment(k).hex()}")
    print("\nK is not published. Only the commitment above goes on chain.")
    return 0


def cmd_test(args) -> int:
    """Score images against a saved fingerprint; print PCE per file.

    With --crop-scale, runs the Gate B search so web-mangled JPEGs still
    resolve.
    """
    reference, meta = prnu.load_fingerprint(args.fingerprint)
    if args.crop_scale:
        return _test_scaled(args, reference, meta)

    print(f"{args.fingerprint}: {meta.get('frames', '?')} enrolment frames\n")

    failures = 0
    for path in _expand(args.images, delivered=True):
        try:
            planes = _load_probe(path, meta)
            pce = prnu.score(planes, reference)
        except ValueError as exc:
            print(f"{Path(path).name}: {exc}")
            failures += 1
            continue

        saturated = max(float((p >= prnu.SATURATION_LEVEL).mean()) for p in planes.values())
        verdict = "MATCH" if pce >= prnu.PCE_THRESHOLD else "no match"
        print(f"{Path(path).name}: {verdict}  PCE {pce:.1f}   {saturated:.1%} saturated")
        failures += pce < prnu.PCE_THRESHOLD

    return 1 if failures else 0


def _test_scaled(args, reference, meta) -> int:
    """Score images that have been resized -- the Gate B path.

    A resized image has no photosite lattice left, so this drops to a single
    combined field and searches for the scale that puts the fingerprint back
    in register.
    """
    from PIL import Image

    from fingerprint import stress

    Image.MAX_IMAGE_PIXELS = None
    field = prnu.sensor_field(reference)
    print(f"{args.fingerprint}: {meta.get('frames', '?')} enrolment frames, scale search\n")

    failures = 0
    for path in _expand(args.images, delivered=True):
        if Path(path).suffix.lower() in RAW_SUFFIXES:
            image = stress.develop(path)
        else:
            with Image.open(path) as im:
                image = im.convert("RGB")

        residual = prnu.noise_residual(stress.green_channel(image))
        match = prnu.crop_and_scale_search(residual, field)

        verdict = "MATCH" if match.pce >= prnu.PCE_THRESHOLD else "no match"
        print(
            f"{Path(path).name}: {verdict}  PCE {match.pce:.1f}  "
            f"scale {match.scale:.3f}  {match.orientation}"
        )
        failures += match.pce < prnu.PCE_THRESHOLD

    return 1 if failures else 0


def cmd_pair(args) -> int:
    """Two-frame quick look -- cheap Gate A signal before a full enrolment."""
    a, b = (prnu.load_raw_planes(p, crop=args.crop) for p in args.images)

    shared = sorted(set(a) & set(b))
    if not shared:
        print("no CFA plane in common", file=sys.stderr)
        return 2

    print(f"crop {args.crop}px, planes {shared}\n")
    for c in shared:
        if a[c].shape != b[c].shape:
            continue
        wa = prnu.noise_residual(a[c])
        wb = prnu.noise_residual(b[c])
        print(f"  plane {c}: PCE {prnu.pce(wa, wb):8.1f}")

    print(
        "\nTwo frames is not an enrolment. A positive number here means the "
        "residuals share structure; it does not mean that structure is PRNU."
    )
    return 0


def cmd_demo(args) -> int:
    """End-to-end run on the synthetic sensor. No camera required."""
    from fingerprint import validate_synthetic as sim

    print("Synthetic sensor, no camera required.")
    print(f"  {sim.SHAPE[0]}x{sim.SHAPE[1]} planes, {sim.FRAMES} enrolment frames")
    print(f"  PRNU strength {sim.PRNU_STRENGTH:.1%}, noise sigma {sim.NOISE_SIGMA:.3f}\n")

    body_a = sim.simulate_sensor(seed=1)
    body_b = sim.simulate_sensor(seed=2)

    started = time.time()
    k = sim.enrol(body_a, seed=100)
    elapsed = time.time() - started

    truth = sim.correlation(k, body_a)
    match = sim.score(sim.simulate_exposure(body_a, seed=900), k)
    others = [sim.score(sim.simulate_exposure(body_b, seed=900 + n), k) for n in range(1, 6)]
    worst = max(abs(x) for x in others)

    print(f"  enrolled in {elapsed:.1f}s")
    print(f"  K vs ground truth        corr {truth:6.3f}   (floor {sim.MIN_TRUTH_CORRELATION})")
    print(f"  held-out frame, body A    PCE {match:8.1f}   (floor {sim.MIN_MATCH_PCE:.0f})")
    print(f"  5 frames from body B      PCE {worst:8.1f}   (ceiling {sim.MAX_MISMATCH_PCE:.0f})")
    print(f"  separation                    {match / max(worst, 1.0):8.1f}x\n")

    checks = [
        (truth >= sim.MIN_TRUTH_CORRELATION, "K correlates with ground truth"),
        (match >= sim.MIN_MATCH_PCE, "same body clears the threshold"),
        (worst <= sim.MAX_MISMATCH_PCE, "other body stays under the ceiling"),
        (match / max(worst, 1.0) >= sim.MIN_SEPARATION, "bodies separate"),
    ]
    for ok, label in checks:
        print(f"  {'ok  ' if ok else 'FAIL'}  {label}")

    passed = all(ok for ok, _ in checks)
    print(f"\n{'PASS' if passed else 'FAIL'}")
    if passed:
        print(
            "\nThis is a synthetic upper bound: a perfectly stable fingerprint, "
            "no lens\nvignetting, no dark current, no demosaic. It proves the "
            "estimator, not the\nproduct. Gate A on real CR3 frames is the "
            "number that counts (docs/gates.md)."
        )
    return 0 if passed else 1


RAW_SUFFIXES = {".cr3", ".cr2", ".crw", ".nef", ".arw", ".dng", ".raf", ".rw2"}
DELIVERED_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".webp"}


def _load_probe(path, meta):
    """Read an image to score, RAW or delivered.

    A delivered file is sampled back onto the photosite lattice the
    fingerprint was enrolled on, which needs the CFA pattern recorded at
    enrolment and only works at native sensor resolution.
    """
    if Path(path).suffix.lower() in DELIVERED_SUFFIXES:
        pattern = meta.get("cfa_pattern")
        if pattern is None:
            raise ValueError(
                "this fingerprint predates CFA-pattern recording, so a delivered "
                "image cannot be mapped back onto its photosite lattice -- re-enrol"
            )
        return prnu.load_delivered_planes(path, pattern)
    return prnu.load_raw_planes(path, crop=meta.get("crop"))


def _expand(images, delivered: bool = False):
    """Accept files and directories; a directory contributes its image files."""
    wanted = RAW_SUFFIXES | DELIVERED_SUFFIXES if delivered else RAW_SUFFIXES
    paths = []
    for item in images:
        p = Path(item)
        if p.is_dir():
            paths.extend(sorted(f for f in p.iterdir() if f.suffix.lower() in wanted))
        else:
            paths.append(p)
    if not paths:
        raise SystemExit("no input files")
    return paths


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

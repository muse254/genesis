"""DEV-ONLY: dump golden fixtures (synthetic images only) for the Rust/WASM port of ``hashing.py``.

    .venv/bin/python -m ingest.dump_hash_fixtures           # regenerate
    python -m ingest.dump_hash_fixtures --check             # check this interpreter

``"expect": "refused"`` cases must error in the browser: a wrong hash would read
as "no record". JPEG hashes are only defined relative to the recorded
Pillow/libjpeg-turbo versions; chroma-sampling variants are where decoders disagree.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin, features

from ingest import hashing

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "rust" / "genesis-prnu" / "tests" / "fixtures" / "hashing"


def synthetic(height: int, width: int, seed: int) -> np.ndarray:
    """Smooth gradients plus noise: structure for the pHash, detail for JPEG."""
    rng = np.random.default_rng(seed)
    y, x = np.mgrid[0:height, 0:width].astype(np.float64)
    base = np.stack(
        [
            128 + 100 * np.sin(x / (width / 3.1) + seed),
            128 + 100 * np.cos(y / (height / 2.3) - seed),
            128 + 90 * np.sin((x + y) / ((width + height) / 5.7)),
        ],
        axis=-1,
    )
    return np.clip(base + rng.normal(0, 18, base.shape), 0, 255).astype(np.uint8)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = []

    def record(name: str, path: Path, kind: str) -> None:
        cases.append(
            {
                "file": path.name,
                "kind": kind,
                "expect": "match",
                "imageHash": "0x" + hashing.pixel_sha256(path).hex(),
                "perceptualHash": f"0x{hashing.perceptual_hash(path):016x}",
            }
        )

    def refused(path: Path, kind: str, why: str) -> None:
        cases.append({"file": path.name, "kind": kind, "expect": "refused", "why": why})

    # PNG: sizes exercising both resize passes, one pass only, and neither.
    for name, (h, w) in {
        "png_97x65": (97, 65),
        "png_180x260": (180, 260),
        "png_32x32": (32, 32),
        "png_32x300": (32, 300),
        "png_1001x33": (1001, 33),
    }.items():
        path = OUT / f"{name}.png"
        Image.fromarray(synthetic(h, w, len(cases))).save(path)
        record(name, path, "png")

    rgba = np.dstack([synthetic(120, 90, 7), np.linspace(0, 255, 120 * 90).reshape(120, 90).astype(np.uint8)])
    Image.fromarray(rgba, "RGBA").save(OUT / "png_rgba.png")
    record("png_rgba", OUT / "png_rgba.png", "png")
    Image.fromarray(synthetic(150, 110, 8)).convert("L").save(OUT / "png_grey.png")
    record("png_grey", OUT / "png_grey.png", "png")

    # Metadata must not move the pixel hash. (JPEG equivalent lives in the
    # browser tests: re-saving a JPEG here would re-encode it.)
    info = PngImagePlugin.PngInfo()
    info.add_text("Author", "someone")
    info.add_text("Comment", "metadata is not pixels")
    Image.open(OUT / "png_97x65.png").save(OUT / "png_97x65_metadata.png", pnginfo=info)
    record("png_97x65_metadata", OUT / "png_97x65_metadata.png", "png")

    # Refused: 16-bit, where Pillow narrows by its own rule.
    wide = (synthetic(40, 50, 10)[..., 0].astype(np.uint16) * 257)
    Image.fromarray(wide).save(OUT / "png_16bit.png")
    refused(OUT / "png_16bit.png", "png", "16-bit")

    # JPEG: one per chroma subsampling, plus progressive and greyscale.
    image = Image.fromarray(synthetic(301, 403, 9))
    for name, options in {
        "jpeg_420": {"subsampling": 2},
        "jpeg_422": {"subsampling": 1},
        "jpeg_444": {"subsampling": 0},
        "jpeg_progressive": {"subsampling": 2, "progressive": True},
    }.items():
        path = OUT / f"{name}.jpg"
        image.save(path, quality=85, **options)
        record(name, path, "jpeg")
    image.convert("L").save(OUT / "jpeg_grey.jpg", quality=85)
    record("jpeg_grey", OUT / "jpeg_grey.jpg", "jpeg")

    # Refused: CMYK (Pillow's conversion, not libjpeg's), and a truncated
    # file (Pillow raises; libjpeg alone would pad it with grey).
    image.convert("CMYK").save(OUT / "jpeg_cmyk.jpg", quality=85)
    refused(OUT / "jpeg_cmyk.jpg", "jpeg", "CMYK")
    whole = (OUT / "jpeg_420.jpg").read_bytes()
    (OUT / "jpeg_truncated.jpg").write_bytes(whole[: len(whole) // 2])
    refused(OUT / "jpeg_truncated.jpg", "jpeg", "truncated")

    manifest = {
        "pillow": Image.__version__,
        "libjpeg_turbo": features.version("libjpeg_turbo"),
        "cases": cases,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {len(cases)} cases to {OUT}")


def check() -> int:
    """Hash the committed fixtures with this interpreter; 0 if all agree."""
    manifest = json.loads((OUT / "manifest.json").read_text())
    pinned = re.search(r"LIBJPEG_TURBO_VERSION=(\S+)", (ROOT / "core" / "jpeg" / "build.sh").read_text())[1]
    problems = []

    have = features.version("libjpeg_turbo")
    if not have == manifest["libjpeg_turbo"] == pinned:
        problems.append(
            f"libjpeg-turbo: this Pillow has {have}, the fixtures {manifest['libjpeg_turbo']}, "
            f"core/jpeg/build.sh pins {pinned}"
        )
    for case in manifest["cases"]:
        path = OUT / case["file"]
        if case["expect"] == "match":
            got = ("0x" + hashing.pixel_sha256(path).hex(), f"0x{hashing.perceptual_hash(path):016x}")
            if got != (case["imageHash"], case["perceptualHash"]):
                problems.append(f"{case['file']}: hashes differ from the fixtures")
        elif case["why"] == "truncated":
            try:
                hashing.pixel_sha256(path)
                problems.append(f"{case['file']}: hashed, but the verify page refuses truncated files")
            except OSError:
                pass

    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{len(manifest['cases'])} fixtures, Pillow {Image.__version__}, libjpeg-turbo {have}: "
          + ("hashes match the verify page" if not problems else f"{len(problems)} problems"))
    return 1 if problems else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        sys.exit(check())
    main()

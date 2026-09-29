"""Dump golden fixtures for the Rust port of the verify-time scoring path.

DEV-ONLY, like ``fingerprint/dump_parity_fixtures.py``, and synthetic only.
Regenerate from the repo root with:

    .venv/bin/python -m fingerprint.dump_search_fixtures

Covers what ``scoring.app._score_against`` does beyond ``score()``
(``docs/shared-verify-plan.md``, phase A): the portrait retry, border
stripping, ``_area_resize``, ``crop_and_scale_search`` and the consistency
signals. Writes to ``rust/genesis-prnu/tests/fixtures/search/``.

Each end-to-end case runs the real ``_score_against`` on a synthetic
delivered image against a synthetic K, and also records every PCE the
search tried (by wrapping ``prnu.pce``), so the port can be checked attempt
by attempt, not only on the winner.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

from fingerprint import consistency, prnu, stress
from fingerprint.validate_synthetic import simulate_exposure, simulate_sensor

OUT = Path(__file__).resolve().parent.parent / "rust" / "genesis-prnu" / "tests" / "fixtures" / "search"

PATTERN = [[0, 1], [3, 2]]  # RGGB, as LibRaw reports for the R10
CHANNELS = {0: 0, 1: 1, 2: 2, 3: 1}
PLANE_SHAPE = (96, 128)  # -> 192x256 RGB


def delivered_rgb(body: dict, seed: int) -> np.ndarray:
    """One held-out exposure through the sensor, mosaicked back into RGB8."""
    held_out = {c: simulate_exposure(k, seed=seed + c) for c, k in body.items()}
    ph, pw = PLANE_SHAPE
    rgb = np.zeros((ph * 2, pw * 2, 3), dtype=np.float32)
    for c, (i, j) in {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}.items():
        rgb[i::2, j::2, CHANNELS[c]] = held_out[c]
    # Fill the unsampled channels too, so greyscale and border logic see a
    # plausible image rather than two-thirds zeros.
    for ch in range(3):
        plane = rgb[:, :, ch]
        plane[plane == 0] = float(np.mean(plane[plane > 0]))
    return (np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)


def main() -> None:
    from scoring.app import _score_against

    OUT.mkdir(parents=True, exist_ok=True)
    manifest: dict = {"cfa_pattern": PATTERN, "cases": [], "area_resize": [], "border": [], "signals": []}

    body = {c: simulate_sensor(shape=PLANE_SHAPE, seed=700 + c) for c in range(4)}
    prnu.save_fingerprint(OUT / "k.npz", body, {"cfa_pattern": PATTERN, "synthetic": True})
    base = Image.fromarray(delivered_rgb(body, seed=7000))

    # --- end to end: _score_against, recording every PCE the search tries ---
    attempts: list[float] = []
    real_pce = prnu.pce

    def recording_pce(residual, reference, squared_size=11):
        value = real_pce(residual, reference, squared_size)
        attempts.append(float(value))
        return value

    prnu.pce = recording_pce
    try:
        bordered = Image.new("RGB", (base.width + 40, base.height + 30), (255, 255, 255))
        bordered.paste(base, (20, 15))
        scenarios = {
            "aligned": base,
            "portrait": base.transpose(Image.Transpose.ROTATE_90),
            "resized": base.resize((154, 115), Image.LANCZOS),
            "mirrored_resized": base.transpose(Image.Transpose.FLIP_LEFT_RIGHT).resize((154, 115), Image.LANCZOS),
            "bordered_resized": bordered.resize((178, 134), Image.LANCZOS),
        }
        for name, image in scenarios.items():
            path = OUT / f"{name}.png"
            image.save(path)
            attempts.clear()
            result = _score_against({"planes": body, "meta": {"cfa_pattern": PATTERN}}, path)
            manifest["cases"].append({"name": name, "file": path.name, "result": result, "attempts": list(attempts)})
    finally:
        prnu.pce = real_pce

    # --- _area_resize, alone: down, up (the search goes to 1.06x), odd sizes ---
    rng = np.random.default_rng(11)
    field = rng.normal(0, 1, size=(53, 71)).astype(np.float32)
    np.save(OUT / "area_field.npy", field)
    for size in [(71, 53), (66, 50), (35, 26), (75, 56), (7, 5)]:
        name = f"area_{size[0]}x{size[1]}.npy"
        np.save(OUT / name, prnu._area_resize(field, size))
        manifest["area_resize"].append({"size": list(size), "file": name})

    # --- strip_uniform_border, alone ---
    scene = np.asarray(base)
    framed = np.full((scene.shape[0] + 24, scene.shape[1] + 36, 3), 250, dtype=np.uint8)
    framed[10:-14, 20:-16] = scene
    top_only = scene.copy()
    top_only[:12] = 255
    too_thick = np.full((scene.shape[0] * 3, scene.shape[1], 3), 0, dtype=np.uint8)
    too_thick[scene.shape[0] : 2 * scene.shape[0]] = scene
    for name, array in {"framed": framed, "top_only": top_only, "too_thick": too_thick, "plain": scene}.items():
        path = OUT / f"border_{name}.png"
        image = Image.fromarray(array)
        image.save(path)
        stripped = stress.strip_uniform_border(image)
        manifest["border"].append({"file": path.name, "size": list(stripped.size), "unchanged": stripped is image})

    # --- signals, on the aligned image ---
    planes = prnu.load_delivered_planes(OUT / "aligned.png", PATTERN)
    grey = np.asarray(base.convert("L"), dtype=float)
    manifest["signals"] = {
        "file": "aligned.png",
        "effectiveStrength": consistency.effective_strength(planes, body),
        "resamplingPeak": consistency.resampling_peak(grey),
        "detail": consistency.high_frequency_content(base),
        "detail_resized": consistency.high_frequency_content(Image.open(OUT / "resized.png")),
    }

    # --- the RAW path's input: planes as the desktop's /raw/decode sends them ---
    np.savez(OUT / "raw_planes.npz", **{f"plane_{c}": p for c, p in planes.items()})
    manifest["raw"] = {"planes": "raw_planes.npz", "developed": "aligned.png", "pce": prnu.score(planes, body)}

    # --- the diagnosis's EXIF branch: in-camera JPEG vs a desktop development ---
    # console/app.py's _diagnose was retired when verification moved to core/
    # (docs/shared-verify-plan.md, phase E). These are its last answers,
    # recorded from it before it went, which core/src/verify.ts must keep.
    in_camera = (
        "This looks like a JPEG written by the camera itself. Measured on this body, in-camera JPEGs carry no readable fingerprint — the camera's noise reduction removes it, because to the camera a sensor fingerprint is noise (docs/gates.md). Try the RAW, or a development of it."
    )
    manifest["diagnose"] = []
    for name, software, diagnosis in [
        ("exif_camera.jpg", None, in_camera),
        ("exif_lightroom.jpg", "Adobe Lightroom Classic 13.0", None),
    ]:
        exif = Image.Exif()
        exif[271] = "Canon"
        exif[272] = "Canon EOS R10"
        if software:
            exif[305] = software
        base.resize((32, 24)).save(OUT / name, exif=exif, quality=85)
        manifest["diagnose"].append({"file": name, "diagnosis": diagnosis})

    # --- stages, for the TypeScript port to match field for field ---
    manifest["stages"] = consistency.stages(
        matched=True,
        registered=False,
        signals={"effectiveStrength": 0.25, "resamplingPeak": 4.0, "bodyConsistency": None},
        path="delivered",
    )

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2, default=float) + "\n")
    for case in manifest["cases"]:
        r = case["result"]
        print(f"{case['name']:18} {r['path']:13} {r.get('orientation')!s:18} pce {r['pce']:10.1f}  attempts {len(case['attempts'])}")


if __name__ == "__main__":
    main()

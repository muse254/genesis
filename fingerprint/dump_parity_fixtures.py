"""Dump golden fixtures from the real fingerprint/prnu.py for the Rust port.

DEV-ONLY, synthetic data only. Run as a module from the repo root, or
`fingerprint/fingerprint.py` shadows the package:

    .venv/bin/python -m fingerprint.dump_parity_fixtures

Writes under rust/genesis-prnu/tests/fixtures/ (see its README.md).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pywt

from fingerprint import prnu
from fingerprint.validate_synthetic import simulate_exposure, simulate_sensor

OUT = Path(__file__).resolve().parent.parent / "rust" / "genesis-prnu" / "tests" / "fixtures"

# Includes a non-power-of-two size to stress boundary handling.
CASES = {
    "case_64x64": (64, 64),
    "case_128x128": (128, 128),
    "case_65x97": (65, 97),
}


def dump_array(name: str, arr: np.ndarray) -> None:
    np.save(OUT / f"{name}.npy", np.asarray(arr))


def dump_wavedec2(prefix: str, plane: np.ndarray, level: int) -> list[dict]:
    """Dump pywt.wavedec2 output for `plane` and return a manifest description."""
    coeffs = pywt.wavedec2(plane, prnu.WAVELET, level=level, mode="symmetric")
    manifest = []

    ca = coeffs[0]
    dump_array(f"{prefix}_L0_approx", ca)
    manifest.append({"level": 0, "band": "approx", "file": f"{prefix}_L0_approx.npy", "shape": list(ca.shape)})

    for lvl, (ch, cv, cd) in enumerate(coeffs[1:], start=1):
        for band_name, band in (("h", ch), ("v", cv), ("d", cd)):
            fname = f"{prefix}_L{lvl}_{band_name}"
            dump_array(fname, band)
            manifest.append(
                {"level": lvl, "band": band_name, "file": f"{fname}.npy", "shape": list(band.shape)}
            )
    return manifest


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    manifest: dict = {
        "wavelet": prnu.WAVELET,
        "wavelet_levels": prnu.WAVELET_LEVELS,
        "wiener_windows": list(prnu.WIENER_WINDOWS),
        "sigma": prnu.SIGMA,
        "saturation_level": prnu.SATURATION_LEVEL,
        "cases": {},
    }

    # --- filter bank ground truth -------------------------------------------
    wavelet = pywt.Wavelet(prnu.WAVELET)
    dec_lo, dec_hi, rec_lo, rec_hi = wavelet.filter_bank
    filter_bank = {
        "name": prnu.WAVELET,
        "dec_lo": list(dec_lo),
        "dec_hi": list(dec_hi),
        "rec_lo": list(rec_lo),
        "rec_hi": list(rec_hi),
    }
    (OUT / "filter_bank_db8.json").write_text(json.dumps(filter_bank, indent=2))

    # --- per-case fixtures ---------------------------------------------------
    for case_name, shape in CASES.items():
        # Not `hash()`: it is salted per process, so fixtures would not reproduce.
        seed = int(hashlib.sha256(case_name.encode()).hexdigest(), 16) % (2**31)
        sensor = simulate_sensor(shape=shape, seed=seed)
        plane = simulate_exposure(sensor, seed=seed + 1)

        dump_array(f"{case_name}_plane", plane)

        levels = min(prnu.WAVELET_LEVELS, pywt.dwt_max_level(min(plane.shape), prnu.WAVELET))
        levels = max(levels, 1)
        wavedec_manifest = dump_wavedec2(f"{case_name}_wavedec2", plane, levels)

        residual = prnu.noise_residual(plane)
        dump_array(f"{case_name}_noise_residual", residual)

        manifest["cases"][case_name] = {
            "shape": list(shape),
            "seed": seed,
            "plane_file": f"{case_name}_plane.npy",
            "levels": levels,
            "wavedec2": wavedec_manifest,
            "noise_residual_file": f"{case_name}_noise_residual.npy",
        }

    # --- two-plane case: cross_correlation / pce / score ----------------------
    two_plane_shape = (96, 80)
    seed_a, seed_b = 1001, 2002

    sensor_a = simulate_sensor(shape=two_plane_shape, seed=seed_a)
    sensor_b = simulate_sensor(shape=two_plane_shape, seed=seed_b)

    candidate = {
        0: simulate_exposure(sensor_a, seed=seed_a + 100),
        1: simulate_exposure(sensor_b, seed=seed_b + 100),
    }
    # Ground-truth PRNU stands in for an enrolled K.
    reference = {0: sensor_a, 1: sensor_b}

    dump_array("two_plane_candidate_0", candidate[0])
    dump_array("two_plane_candidate_1", candidate[1])
    dump_array("two_plane_reference_0", reference[0])
    dump_array("two_plane_reference_1", reference[1])

    residual_0 = prnu.noise_residual(candidate[0])
    expected_0 = candidate[0] * reference[0]
    cc_0 = prnu.cross_correlation(residual_0, expected_0)
    dump_array("two_plane_cc_0", cc_0)
    pce_0 = prnu._pce_of(cc_0)

    score_value = prnu.score(candidate, reference, mask_saturated=True)

    manifest["two_plane_case"] = {
        "shape": list(two_plane_shape),
        "seed_a": seed_a,
        "seed_b": seed_b,
        "candidate_files": ["two_plane_candidate_0.npy", "two_plane_candidate_1.npy"],
        "reference_files": ["two_plane_reference_0.npy", "two_plane_reference_1.npy"],
        "cross_correlation_file": "two_plane_cc_0.npy",
        "pce_of_cc_0": pce_0,
        "score": score_value,
    }

    # --- end-to-end: K (.npz) + delivered PNG + score -------------------------
    # Proves the whole Rust pipeline against one real Python score() call.
    from PIL import Image

    from fingerprint.validate_synthetic import FRAMES

    pattern = [[0, 1], [3, 2]]  # RGGB, as LibRaw reports for the R10
    e2e_shape = (48, 40)  # -> 96x80 RGB delivered image (2x demosaic upscale)
    channels = {0: 0, 1: 1, 2: 2, 3: 1}

    body = {c: simulate_sensor(shape=e2e_shape, seed=500 + c) for c in range(4)}
    enrolment_frames = [
        {c: simulate_exposure(k, seed=600 + 10 * n + c) for c, k in body.items()}
        for n in range(FRAMES)
    ]
    k = prnu.postprocess(prnu.estimate_fingerprint(enrolment_frames))

    k_path = OUT / "e2e_fingerprint.npz"
    meta = {"cfa_pattern": pattern, "frames": FRAMES, "synthetic": True}
    prnu.save_fingerprint(k_path, k, meta)

    # Held-out exposure -> demosaiced RGB image.
    held_out = {c: simulate_exposure(kk, seed=9000 + c) for c, kk in body.items()}
    ph, pw = e2e_shape
    rgb = np.zeros((ph * 2, pw * 2, 3), dtype=np.float32)
    pos = {0: (0, 0), 1: (0, 1), 2: (1, 1), 3: (1, 0)}
    for c, (i, j) in pos.items():
        rgb[i::2, j::2, channels[c]] = held_out[c]

    image_path = OUT / "e2e_delivered.png"
    Image.fromarray((np.clip(rgb, 0.0, 1.0) * 255).astype(np.uint8)).save(image_path)

    delivered_planes = prnu.load_delivered_planes(image_path, pattern, channels)
    e2e_score = prnu.score(delivered_planes, k, mask_saturated=True)

    manifest["e2e_case"] = {
        "shape": list(e2e_shape),
        "k_file": k_path.name,
        "image_file": image_path.name,
        "cfa_pattern": pattern,
        "channels": channels,
        "score": e2e_score,
    }

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()

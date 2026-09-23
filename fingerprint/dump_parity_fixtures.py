"""Dump golden fixtures from the real fingerprint/prnu.py for the Rust port.

THROWAWAY / DEV-ONLY. Not shipped, not imported by anything. Regenerate with
(must be run as a module -- from the repo root -- not as a bare script, or
`fingerprint/fingerprint.py` shadows the `fingerprint` package on sys.path):

    source .venv/bin/activate && python -m fingerprint.dump_parity_fixtures
    # or: .venv/bin/python -m fingerprint.dump_parity_fixtures

Writes everything under rust/genesis-prnu/tests/fixtures/. Only ever writes
*synthetic* data (the same deterministic-sensor construction as
fingerprint/validate_synthetic.py) -- never a real photo or RAW frame. See
that directory's README.md for what each file is.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pywt

from fingerprint import prnu
from fingerprint.validate_synthetic import simulate_exposure, simulate_sensor

OUT = Path(__file__).resolve().parent.parent / "rust" / "genesis-prnu" / "tests" / "fixtures"

# Non-trivial, fast, and at least one non-power-of-two size to stress
# boundary handling (extension length / phase at odd dimensions).
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
        seed = abs(hash(case_name)) % (2**31)
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

    # candidate image planes (what score() receives as `planes`)
    candidate = {
        0: simulate_exposure(sensor_a, seed=seed_a + 100),
        1: simulate_exposure(sensor_b, seed=seed_b + 100),
    }
    # "reference" fingerprint K per plane -- just the ground-truth sensor
    # PRNU fields themselves, standing in for an enrolled K.
    reference = {0: sensor_a, 1: sensor_b}

    dump_array("two_plane_candidate_0", candidate[0])
    dump_array("two_plane_candidate_1", candidate[1])
    dump_array("two_plane_reference_0", reference[0])
    dump_array("two_plane_reference_1", reference[1])

    # cross_correlation on plane 0's residual vs expected, standalone
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

    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"wrote fixtures to {OUT}")


if __name__ == "__main__":
    main()

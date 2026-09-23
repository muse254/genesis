//! Parity tests against the Python reference (`fingerprint/prnu.py`),
//! using fixtures dumped by `fingerprint/dump_parity_fixtures.py` into
//! `tests/fixtures/` (see that directory's `README.md`).
//!
//! Phase 1: the `db8` wavelet transform round-trips independently of
//! Python, and matches `pywt.wavedec2`'s coefficients on the same input.
//! Phase 2: `noise_residual` matches the Python reference's output.
//!
//! Phase 3+ (`cross_correlation`/`pce`/`score`) fixtures exist in this
//! directory too (for a later session) but are not checked here.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use ndarray::Array2;
use ndarray_npy::read_npy;
use serde::Deserialize;

use genesis_prnu::noise::noise_residual;
use genesis_prnu::wavelet::wavedec2;

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

#[derive(Deserialize)]
struct Manifest {
    cases: HashMap<String, Case>,
}

#[derive(Deserialize)]
struct Case {
    plane_file: String,
    levels: usize,
    wavedec2: Vec<BandEntry>,
    noise_residual_file: String,
}

#[derive(Deserialize)]
struct BandEntry {
    level: usize,
    band: String,
    file: String,
}

fn load_manifest() -> Manifest {
    let text = fs::read_to_string(fixtures_dir().join("manifest.json"))
        .expect("manifest.json should exist -- run fingerprint/dump_parity_fixtures.py");
    serde_json::from_str(&text).expect("manifest.json should be valid JSON")
}

fn load_plane(file: &str) -> Array2<f64> {
    let a: Array2<f32> = read_npy(fixtures_dir().join(file)).expect("fixture .npy should load");
    a.mapv(|v| v as f64)
}

/// Relative-or-absolute tolerance: `|a - b| <= atol + rtol * |b|`. Loose
/// enough to allow for f32 (Python) vs f64 (this crate) accumulation
/// differences, tight enough to catch a wrong transform.
fn assert_allclose(name: &str, a: &Array2<f64>, b: &Array2<f64>, rtol: f64, atol: f64) {
    assert_eq!(a.shape(), b.shape(), "{name}: shape mismatch");
    let mut max_err = 0.0f64;
    let mut max_rel = 0.0f64;
    for (x, y) in a.iter().zip(b.iter()) {
        let err = (x - y).abs();
        let tol = atol + rtol * y.abs();
        if err > tol {
            panic!(
                "{name}: mismatch, |{x} - {y}| = {err} exceeds tol {tol} (rtol={rtol}, atol={atol})"
            );
        }
        max_err = max_err.max(err);
        if y.abs() > 1e-12 {
            max_rel = max_rel.max(err / y.abs());
        }
    }
    eprintln!("{name}: max abs err {max_err:.3e}, max rel err {max_rel:.3e}");
}

#[test]
fn wavedec2_matches_pywt_on_all_cases() {
    let manifest = load_manifest();

    for (case_name, case) in &manifest.cases {
        let plane = load_plane(&case.plane_file);
        let dec = wavedec2(&plane, case.levels);

        for entry in &case.wavedec2 {
            let expected = load_plane(&entry.file);
            let got = if entry.level == 0 {
                &dec.approx
            } else {
                let (ch, cv, cd) = &dec.details[entry.level - 1];
                match entry.band.as_str() {
                    "h" => ch,
                    "v" => cv,
                    "d" => cd,
                    other => panic!("unknown band {other}"),
                }
            };
            assert_allclose(
                &format!("{case_name}/L{}_{}", entry.level, entry.band),
                got,
                &expected,
                1e-4,
                1e-5,
            );
        }
    }
}

#[test]
fn wavedec2_roundtrip_matches_original_plane() {
    let manifest = load_manifest();
    for (case_name, case) in &manifest.cases {
        let plane = load_plane(&case.plane_file);
        let dec = wavedec2(&plane, case.levels);
        let rec = dec.waverec2();
        let cropped = rec
            .slice(ndarray::s![0..plane.shape()[0], 0..plane.shape()[1]])
            .to_owned();
        assert_allclose(&format!("{case_name}/roundtrip"), &cropped, &plane, 1e-9, 1e-9);
    }
}

#[test]
fn noise_residual_matches_python_reference() {
    let manifest = load_manifest();
    for (case_name, case) in &manifest.cases {
        let plane_f32: Array2<f32> =
            read_npy(fixtures_dir().join(&case.plane_file)).expect("plane fixture should load");
        let expected = load_plane(&case.noise_residual_file);

        let got = noise_residual(&plane_f32).mapv(|v| v as f64);
        // noise_residual involves many chained shrinkage operations on f32
        // in Python vs f64 here, so allow a looser (but still tight)
        // tolerance than the raw wavelet coefficients.
        assert_allclose(&format!("{case_name}/noise_residual"), &got, &expected, 5e-3, 1e-4);
    }
}

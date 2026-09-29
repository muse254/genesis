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

use genesis_prnu::correlation::{cross_correlation, pce_of, score};
use genesis_prnu::image_decode::load_delivered_planes;
use genesis_prnu::kfile::{cfa_pattern, load_fingerprint};
use genesis_prnu::noise::noise_residual;
use genesis_prnu::wavelet::wavedec2;

fn fixtures_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

#[derive(Deserialize)]
struct Manifest {
    cases: HashMap<String, Case>,
    two_plane_case: TwoPlaneCase,
}

#[derive(Deserialize)]
struct TwoPlaneCase {
    candidate_files: Vec<String>,
    reference_files: Vec<String>,
    cross_correlation_file: String,
    pce_of_cc_0: f64,
    score: f64,
}

#[derive(Deserialize)]
struct E2eCase {
    k_file: String,
    image_file: String,
    score: f64,
}

/// `Manifest` above only has `cases`/`two_plane_case` fields wired up via
/// `serde`'s strictness-by-default (extra JSON fields are ignored, not
/// errors), so `e2e_case` is parsed out separately here.
fn load_e2e_case() -> E2eCase {
    let text = fs::read_to_string(fixtures_dir().join("manifest.json"))
        .expect("manifest.json should exist");
    let v: serde_json::Value = serde_json::from_str(&text).expect("manifest.json should be valid JSON");
    let e2e = &v["e2e_case"];
    E2eCase {
        k_file: e2e["k_file"].as_str().unwrap().to_string(),
        image_file: e2e["image_file"].as_str().unwrap().to_string(),
        score: e2e["score"].as_f64().unwrap(),
    }
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

/// Phase 3: `cross_correlation`, `_pce_of`, `score` -- checked against the
/// `two_plane_case` fixtures dumped by `fingerprint/dump_parity_fixtures.py`
/// (see `tests/fixtures/README.md`).
#[test]
fn cross_correlation_matches_python_reference() {
    let manifest = load_manifest();
    let case = &manifest.two_plane_case;

    let candidate_0: Array2<f32> =
        read_npy(fixtures_dir().join(&case.candidate_files[0])).expect("candidate_0 should load");
    let reference_0: Array2<f32> =
        read_npy(fixtures_dir().join(&case.reference_files[0])).expect("reference_0 should load");
    let expected_cc: Array2<f64> = read_npy(fixtures_dir().join(&case.cross_correlation_file))
        .expect("cross_correlation fixture (float64) should load");

    let residual = noise_residual(&candidate_0).mapv(|v| v as f64);
    let expected_field = ndarray::Zip::from(&candidate_0)
        .and(&reference_0)
        .map_collect(|&p, &k| (p * k) as f64);

    let cc = cross_correlation(&residual, &expected_field);
    assert_allclose("two_plane_case/cross_correlation_0", &cc, &expected_cc, 1e-3, 1e-2);

    let pce = pce_of(&cc, 11);
    let rel = (pce - case.pce_of_cc_0).abs() / case.pce_of_cc_0.abs().max(1.0);
    assert!(
        rel < 0.02,
        "pce_of(cc_0) = {pce}, python = {}, rel err {rel}",
        case.pce_of_cc_0
    );
}

#[test]
fn score_matches_python_reference() {
    let manifest = load_manifest();
    let case = &manifest.two_plane_case;

    let mut planes = std::collections::BTreeMap::new();
    let mut reference = std::collections::BTreeMap::new();
    for (c, (cand_file, ref_file)) in case
        .candidate_files
        .iter()
        .zip(case.reference_files.iter())
        .enumerate()
    {
        let cand: Array2<f32> =
            read_npy(fixtures_dir().join(cand_file)).expect("candidate should load");
        let refr: Array2<f32> =
            read_npy(fixtures_dir().join(ref_file)).expect("reference should load");
        planes.insert(c as i32, cand);
        reference.insert(c as i32, refr);
    }

    let got = score(&planes, &reference, true);
    let rel = (got - case.score).abs() / case.score.abs().max(1.0);
    assert!(rel < 0.02, "score = {got}, python = {}, rel err {rel}", case.score);
}

/// Phase 4 end-to-end: reads a real `.npz` K file with [`load_fingerprint`],
/// decodes a real PNG with [`load_delivered_planes`] using the CFA pattern
/// out of the K file's own `meta` (exactly what the WASM `score()` entry
/// point does), and checks the resulting `score()` against the one real
/// Python `score()` call dumped into `manifest.json`'s `e2e_case`. This is
/// the fixture that proves the whole pipeline, not just each piece alone.
#[test]
fn e2e_score_matches_python_reference() {
    let case = load_e2e_case();

    let k_bytes = fs::read(fixtures_dir().join(&case.k_file)).expect("k .npz should read");
    let fp = load_fingerprint(&k_bytes).expect("k .npz should parse");
    let pattern = cfa_pattern(&fp.meta).expect("meta should have cfa_pattern");

    let image_bytes = fs::read(fixtures_dir().join(&case.image_file)).expect("delivered png should read");
    let planes = load_delivered_planes(&image_bytes, pattern, None).expect("png should decode");

    let got = score(&planes, &fp.planes, true);
    let rel = (got - case.score).abs() / case.score.abs().max(1.0);
    assert!(
        rel < 0.02,
        "e2e score = {got}, python = {}, rel err {rel}",
        case.score
    );
}

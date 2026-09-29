//! Parity of [`genesis_prnu::search`], [`genesis_prnu::resample`] and
//! [`genesis_prnu::consistency`] with the Python verify path, on the
//! synthetic fixtures `fingerprint/dump_search_fixtures.py` writes.
//!
//! Tolerances follow `parity.rs`: PCE within 2% (Rust's noise residual runs
//! in f64, Python's in f32), but every *decision* exact -- which path, which
//! orientation, which scale, what got cropped. A port that lands on the same
//! PCE through a different orientation is wrong.

use std::fs;
use std::path::PathBuf;

use ndarray::Array2;
use ndarray_npy::read_npy;
use serde::Deserialize;
use serde_json::Value;

use genesis_prnu::consistency::{
    effective_strength, high_frequency_content, resampling_peak, DEFAULT_PLANE,
};
use genesis_prnu::hashing::decode_rgb8;
use genesis_prnu::image_decode::planes_from_rgb;
use genesis_prnu::kfile::{cfa_pattern, load_fingerprint};
use genesis_prnu::resample::resize_f32_box;
use genesis_prnu::search::{score_against, strip_uniform_border, Rgb};

#[derive(Deserialize)]
struct Manifest {
    cases: Vec<Case>,
    area_resize: Vec<AreaCase>,
    border: Vec<BorderCase>,
    signals: Value,
}

#[derive(Deserialize)]
struct Case {
    name: String,
    file: String,
    result: Value,
    attempts: Vec<f64>,
}

#[derive(Deserialize)]
struct AreaCase {
    size: [usize; 2],
    file: String,
}

#[derive(Deserialize)]
struct BorderCase {
    file: String,
    size: [usize; 2],
    unchanged: bool,
}

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/search")
}

fn manifest() -> Manifest {
    serde_json::from_str(&fs::read_to_string(dir().join("manifest.json")).unwrap()).unwrap()
}

fn rgb(file: &str) -> Rgb {
    let (data, w, h) = decode_rgb8(&fs::read(dir().join(file)).unwrap()).unwrap();
    Rgb::new(data, w, h)
}

fn close(got: f64, want: f64, rel: f64) -> bool {
    (got - want).abs() <= rel * want.abs().max(1.0)
}

#[test]
fn score_against_matches_python_on_every_path() {
    let fp = load_fingerprint(&fs::read(dir().join("k.npz")).unwrap()).unwrap();
    let pattern = cfa_pattern(&fp.meta).unwrap();
    let m = manifest();
    assert!(m.cases.len() >= 5);

    for case in m.cases {
        let want = &case.result;
        let mut attempts = Vec::new();
        let got = score_against(&rgb(&case.file), &fp.planes, pattern, &mut |label| {
            attempts.push(label.to_string())
        });

        assert_eq!(
            got.path,
            want["path"].as_str().unwrap(),
            "{}: path",
            case.name
        );
        assert_eq!(
            got.orientation,
            want["orientation"].as_str().unwrap(),
            "{}: orientation",
            case.name
        );
        assert_eq!(got.scale, want["scale"].as_f64(), "{}: scale", case.name);
        assert_eq!(
            got.border_stripped.as_deref(),
            want["borderStripped"].as_str(),
            "{}: border",
            case.name
        );
        assert_eq!(got.turned, want["turned"].as_str(), "{}: turned", case.name);
        assert!(
            close(got.pce, want["pce"].as_f64().unwrap(), 0.02),
            "{}: pce {} vs python {}",
            case.name,
            got.pce,
            want["pce"]
        );

        // Every correlation the search tried, losers included, in order.
        assert_eq!(
            got.attempts.len(),
            case.attempts.len(),
            "{}: attempts",
            case.name
        );
        for (i, (g, w)) in got.attempts.iter().zip(&case.attempts).enumerate() {
            assert!(
                close(*g, *w, 0.02),
                "{}: attempt {i}: {g} vs python {w}",
                case.name
            );
        }
        // And one progress label per correlation, as Python reported.
        let searched = attempts
            .iter()
            .filter(|l| l.starts_with("searching"))
            .count();
        assert_eq!(
            searched,
            case.attempts.len(),
            "{}: correlations reported",
            case.name
        );
    }
}

#[test]
fn area_resize_matches_pillow_box_on_float32() {
    let field: Array2<f32> = read_npy(dir().join("area_field.npy")).unwrap();
    for case in manifest().area_resize {
        let want: Array2<f32> = read_npy(dir().join(&case.file)).unwrap();
        let got = resize_f32_box(&field, case.size[0], case.size[1]);
        assert_eq!(got.dim(), want.dim(), "{}", case.file);
        let worst = got
            .iter()
            .zip(want.iter())
            .map(|(a, b)| (a - b).abs())
            .fold(0.0f32, f32::max);
        // Same arithmetic in the same order; only the last float32 bit may move.
        assert!(worst <= 1e-6, "{}: max difference {worst}", case.file);
    }
}

#[test]
fn border_stripping_matches_python() {
    for case in manifest().border {
        let image = rgb(&case.file);
        match strip_uniform_border(&image, 2.0, 0.25) {
            None => {
                assert!(
                    case.unchanged,
                    "{}: python stripped, rust did not",
                    case.file
                );
                assert_eq!([image.width, image.height], case.size);
            }
            Some((l, t, r, b)) => {
                assert!(
                    !case.unchanged,
                    "{}: rust stripped, python did not",
                    case.file
                );
                assert_eq!([r - l, b - t], case.size, "{}", case.file);
            }
        }
    }
}

#[test]
fn signals_match_python() {
    let s = manifest().signals;
    let image = rgb(s["file"].as_str().unwrap());
    let fp = load_fingerprint(&fs::read(dir().join("k.npz")).unwrap()).unwrap();
    let pattern = cfa_pattern(&fp.meta).unwrap();
    let planes = planes_from_rgb(&image.data, image.width, image.height, pattern, None);

    let strength = effective_strength(&planes, &fp.planes, DEFAULT_PLANE).unwrap();
    let want = s["effectiveStrength"].as_f64().unwrap();
    assert!(
        close(strength, want, 0.02),
        "effectiveStrength {strength} vs {want}"
    );

    let peak = resampling_peak(&image, 1024);
    let want = s["resamplingPeak"].as_f64().unwrap();
    assert!(
        (peak - want).abs() <= 1e-6 * want.abs(),
        "resamplingPeak {peak} vs {want}"
    );

    let detail = high_frequency_content(&image);
    let want = s["detail"].as_f64().unwrap();
    assert!(
        (detail - want).abs() <= 1e-9 * want.abs(),
        "detail {detail} vs {want}"
    );

    let resized = rgb("resized.png");
    let detail = high_frequency_content(&resized);
    let want = s["detail_resized"].as_f64().unwrap();
    assert!(
        (detail - want).abs() <= 1e-9 * want.abs(),
        "detail (resized) {detail} vs {want}"
    );
}

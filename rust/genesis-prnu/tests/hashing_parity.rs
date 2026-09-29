//! Parity of [`genesis_prnu::hashing`] with `ingest/hashing.py`, on the
//! synthetic fixtures `ingest/dump_hash_fixtures.py` writes. Exact equality:
//! the pixel hash has no tolerance, and the pHash port is bit-exact too.
//!
//! PNG cases only. The JPEG cases in the same manifest need libjpeg-turbo,
//! which this crate does not link; `verify/test/hashes.test.ts` runs them.

use std::fs;
use std::path::PathBuf;

use serde::Deserialize;

use genesis_prnu::hashing::{decode_rgb8, perceptual_hash, pixel_sha256};

#[derive(Deserialize)]
struct Manifest {
    cases: Vec<Case>,
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase")]
struct Case {
    file: String,
    kind: String,
    expect: String,
    image_hash: Option<String>,
    perceptual_hash: Option<String>,
}

fn dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/hashing")
}

fn cases(kind: &str, expect: &str) -> Vec<Case> {
    let manifest: Manifest =
        serde_json::from_str(&fs::read_to_string(dir().join("manifest.json")).unwrap()).unwrap();
    manifest
        .cases
        .into_iter()
        .filter(|c| c.kind == kind && c.expect == expect)
        .collect()
}

fn hex(bytes: &[u8]) -> String {
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}

#[test]
fn png_hashes_match_python() {
    let pngs = cases("png", "match");
    assert!(pngs.len() >= 8, "expected the PNG cases in the manifest");

    for case in pngs {
        let bytes = fs::read(dir().join(&case.file)).unwrap();
        let (rgb, w, h) = decode_rgb8(&bytes).unwrap();

        let image_hash = format!("0x{}", hex(&pixel_sha256(&rgb, w, h)));
        assert_eq!(
            Some(image_hash),
            case.image_hash,
            "{}: pixel hash",
            case.file
        );

        let phash = format!("0x{:016x}", perceptual_hash(&rgb, w, h));
        assert_eq!(
            Some(phash),
            case.perceptual_hash,
            "{}: perceptual hash",
            case.file
        );
    }
}

#[test]
fn png_metadata_does_not_change_the_hash() {
    let hash = |file: &str| {
        let (rgb, w, h) = decode_rgb8(&fs::read(dir().join(file)).unwrap()).unwrap();
        pixel_sha256(&rgb, w, h)
    };
    assert_eq!(hash("png_97x65.png"), hash("png_97x65_metadata.png"));
}

#[test]
fn refused_pngs_are_refused() {
    let refused = cases("png", "refused");
    assert!(!refused.is_empty());
    for case in refused {
        let bytes = fs::read(dir().join(&case.file)).unwrap();
        assert!(
            decode_rgb8(&bytes).is_err(),
            "{} should be refused",
            case.file
        );
    }
}

#[test]
fn every_jpeg_is_refused_by_the_rust_decoder() {
    for case in cases("jpeg", "match")
        .into_iter()
        .chain(cases("jpeg", "refused"))
    {
        let bytes = fs::read(dir().join(&case.file)).unwrap();
        assert!(
            decode_rgb8(&bytes).is_err(),
            "{} decoded by the image crate",
            case.file
        );
    }
}

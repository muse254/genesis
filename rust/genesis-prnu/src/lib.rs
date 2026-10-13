//! PRNU sensor-fingerprint scoring core: a Rust port of the scoring path of
//! `fingerprint/prnu.py` (enrolment, RAW decoding and `commitment()` stay
//! Python-only). Shared by the web verify page (WASM) and the desktop app.

pub mod consistency;
pub mod correlation;
pub mod hashing;
pub mod image_decode;
pub mod kfile;
pub mod noise;
pub mod resample;
pub mod search;
pub mod wavelet;

pub use correlation::{cross_correlation, pce, pce_of, score};
pub use noise::noise_residual;
pub use search::{score_against, score_against_raw, Rgb, ScoreResult};

//! PRNU sensor-fingerprint scoring core: a Rust port of the scoring path of
//! `fingerprint/prnu.py` (everything except enrolment, RAW decoding, and
//! `commitment()`, which stay Python-only -- see `docs/wasm-scoring-plan.md`).
//!
//! This crate implements Phases 0-4 of that plan: the `db8` wavelet
//! transform ([`wavelet`]), the Mihcak wavelet-Wiener denoiser ([`noise`],
//! `noise_residual`), FFT cross-correlation/PCE/`score` ([`correlation`]),
//! and delivered-image/K-file I/O ([`image_decode`], [`kfile`]). Also the
//! image record's two content hashes ([`hashing`], from `ingest/hashing.py`),
//! which the verify page computes in the browser.
//!
//! And, for one verify implementation shared by the web page and the desktop
//! app (`docs/shared-verify-plan.md`): scoring an image of unknown provenance
//! against a body, including the portrait retry and the scale search
//! ([`search`], on Pillow's resampler in [`resample`]), and the advisory
//! consistency signals ([`consistency`]).

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
pub use search::{score_against, Rgb, ScoreResult};

//! PRNU sensor-fingerprint scoring core: a Rust port of the scoring path of
//! `fingerprint/prnu.py` (everything except enrolment, RAW decoding, and
//! `commitment()`, which stay Python-only -- see `docs/wasm-scoring-plan.md`).
//!
//! This crate implements Phases 0-4 of that plan: the `db8` wavelet
//! transform ([`wavelet`]), the Mihcak wavelet-Wiener denoiser ([`noise`],
//! `noise_residual`), FFT cross-correlation/PCE/`score` ([`correlation`]),
//! and delivered-image/K-file I/O ([`image_decode`], [`kfile`]).

pub mod correlation;
pub mod image_decode;
pub mod kfile;
pub mod noise;
pub mod wavelet;

pub use correlation::{cross_correlation, pce, pce_of, score};
pub use noise::noise_residual;

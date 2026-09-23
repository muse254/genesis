//! PRNU sensor-fingerprint scoring core: a Rust port of the scoring path of
//! `fingerprint/prnu.py` (everything except enrolment, RAW decoding, and
//! `commitment()`, which stay Python-only -- see `docs/wasm-scoring-plan.md`).
//!
//! This crate currently implements Phases 0-2 of that plan: the `db8`
//! wavelet transform ([`wavelet`]) and the Mihcak wavelet-Wiener denoiser
//! ([`noise`], `noise_residual`). Correlation/PCE/`score` (Phase 3) and
//! image/K-file I/O (Phase 4) are not yet ported.

pub mod noise;
pub mod wavelet;

pub use noise::noise_residual;

//! `wasm-bindgen` wrapper around `genesis-prnu`'s scoring core.
//!
//! Exposes exactly one function, [`score`]: takes an image's raw bytes and
//! a K `.npz` file's raw bytes, does everything in-process (decode, CFA
//! sample, noise residual, cross-correlation, PCE), and returns a plain
//! `f64` PCE. See `docs/wasm-scoring-plan.md` Phase 5.
//!
//! **Hard invariant: K bytes never leave this call.** Nothing in this crate
//! performs network I/O -- there is no `fetch`, no `XMLHttpRequest`
//! binding, nothing that could transmit `k_npz_bytes` anywhere. The CFA
//! pattern needed to decode the delivered image comes from the K file's
//! own `meta`, so the JS caller never needs to pass a separate pattern
//! argument, and K bytes are used only for the one in-memory `score()` call
//! before being dropped. See `docs/security.md`, "Where K lives".

use wasm_bindgen::prelude::*;

/// Score a delivered image (JPEG/PNG/TIFF bytes) against an enrolled K
/// `.npz` file (bytes), returning the PCE (compare against
/// `fingerprint/prnu.py`'s `PCE_THRESHOLD = 100.0`).
///
/// Both arguments are plain byte buffers already in this process's memory
/// (e.g. from a JS `File`/`Blob` via `arrayBuffer()`) -- this function does
/// no I/O of its own, so nothing it does can transmit `k_npz_bytes`
/// anywhere.
#[wasm_bindgen]
pub fn score(image_bytes: &[u8], k_npz_bytes: &[u8]) -> Result<f64, JsValue> {
    let fp = genesis_prnu::kfile::load_fingerprint(k_npz_bytes)
        .map_err(|e| JsValue::from_str(&format!("could not read K file: {e}")))?;
    let pattern = genesis_prnu::kfile::cfa_pattern(&fp.meta)
        .map_err(|e| JsValue::from_str(&format!("K file meta has no usable cfa_pattern: {e}")))?;
    let planes = genesis_prnu::image_decode::load_delivered_planes(image_bytes, pattern, None)
        .map_err(|e| JsValue::from_str(&format!("could not decode image: {e}")))?;

    Ok(genesis_prnu::score(&planes, &fp.planes, true))
}

/// The decision threshold from `fingerprint/prnu.py`'s `PCE_THRESHOLD`,
/// exposed so the JS side never has to hardcode it independently.
#[wasm_bindgen(js_name = pceThreshold)]
pub fn pce_threshold() -> f64 {
    100.0
}

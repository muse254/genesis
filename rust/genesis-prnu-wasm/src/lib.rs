//! `wasm-bindgen` wrapper around `genesis-prnu`'s scoring core.
//!
//! Exposes [`score`], for the score page: takes an image's raw bytes and
//! a K `.npz` file's raw bytes, does everything in-process (decode, CFA
//! sample, noise residual, cross-correlation, PCE), and returns a plain
//! `f64` PCE. See `docs/wasm-scoring-plan.md` Phase 5.
//!
//! And, for the verify page, [`image_hashes`] and [`decode_rgb`]: the two
//! content hashes `ingest/hashing.py` computes, so a photo being verified
//! never has to leave the browser either.
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

/// The image record's two hashes, from canonical 8-bit RGB (`width *
/// height * 3` bytes, row-major), as `ingest/hashing.py` computes them:
/// `imageHash` is `0x` + 64 hex digits, `perceptualHash` is `0x` + 16.
///
/// The caller supplies the pixels because decoding is where exactness is
/// won or lost -- see `genesis_prnu::hashing`. The verify page decodes JPEG
/// with libjpeg-turbo (`verify/jpeg/`) and everything else with
/// [`decode_rgb`].
#[wasm_bindgen(js_name = imageHashes)]
pub fn image_hashes(rgb: &[u8], width: usize, height: usize) -> Result<ImageHashes, JsValue> {
    if rgb.len() != width * height * 3 {
        return Err(JsValue::from_str(
            "rgb buffer does not match its dimensions",
        ));
    }
    let digest = genesis_prnu::hashing::pixel_sha256(rgb, width, height);
    Ok(ImageHashes {
        image_hash: format!(
            "0x{}",
            digest
                .iter()
                .map(|b| format!("{b:02x}"))
                .collect::<String>()
        ),
        perceptual_hash: format!(
            "0x{:016x}",
            genesis_prnu::hashing::perceptual_hash(rgb, width, height)
        ),
    })
}

#[wasm_bindgen]
pub struct ImageHashes {
    image_hash: String,
    perceptual_hash: String,
}

#[wasm_bindgen]
impl ImageHashes {
    #[wasm_bindgen(getter, js_name = imageHash)]
    pub fn image_hash(&self) -> String {
        self.image_hash.clone()
    }

    #[wasm_bindgen(getter, js_name = perceptualHash)]
    pub fn perceptual_hash(&self) -> String {
        self.perceptual_hash.clone()
    }
}

/// Decode a PNG or TIFF to canonical 8-bit RGB. JPEG is refused on
/// purpose: this decoder does not reproduce Pillow's JPEG pixels, so it
/// would produce a wrong pixel hash without any error.
#[wasm_bindgen(js_name = decodeRgb)]
pub fn decode_rgb(bytes: &[u8]) -> Result<DecodedRgb, JsValue> {
    let (rgb, width, height) =
        genesis_prnu::hashing::decode_rgb8(bytes).map_err(|e| JsValue::from_str(&e))?;
    Ok(DecodedRgb { rgb, width, height })
}

#[wasm_bindgen]
pub struct DecodedRgb {
    rgb: Vec<u8>,
    width: usize,
    height: usize,
}

#[wasm_bindgen]
impl DecodedRgb {
    #[wasm_bindgen(getter)]
    pub fn rgb(&self) -> Vec<u8> {
        self.rgb.clone()
    }

    #[wasm_bindgen(getter)]
    pub fn width(&self) -> usize {
        self.width
    }

    #[wasm_bindgen(getter)]
    pub fn height(&self) -> usize {
        self.height
    }
}

// ---- Verification against an enrolled body (docs/shared-verify-plan.md) ----
//
// The desktop app holds its enrolled K files and passes them in; the web
// page has none and never calls these. Same invariant as `score` above:
// nothing here does I/O, so K bytes cannot leave this call.

/// An enrolled body's fingerprint, parsed once and reused across images.
#[wasm_bindgen]
pub struct Body {
    planes: std::collections::BTreeMap<i32, ndarray::Array2<f32>>,
    pattern: [[i32; 2]; 2],
    crop: Option<i64>,
}

#[wasm_bindgen]
impl Body {
    /// Parse a K `.npz` (as `fingerprint/prnu.py::save_fingerprint` writes).
    #[wasm_bindgen(constructor)]
    pub fn new(k_npz_bytes: &[u8]) -> Result<Body, JsValue> {
        let fp = genesis_prnu::kfile::load_fingerprint(k_npz_bytes)
            .map_err(|e| JsValue::from_str(&format!("could not read K file: {e}")))?;
        let pattern = genesis_prnu::kfile::cfa_pattern(&fp.meta).map_err(|e| {
            JsValue::from_str(&format!("K file meta has no usable cfa_pattern: {e}"))
        })?;
        let crop = fp.meta.get("crop").and_then(|c| c.as_i64());
        Ok(Body {
            planes: fp.planes,
            pattern,
            crop,
        })
    }

    /// `meta["crop"]`: what a RAW decode for this body must crop to, so its
    /// planes line up with K. `undefined` for none.
    #[wasm_bindgen(getter)]
    pub fn crop(&self) -> Option<i32> {
        self.crop.map(|c| c as i32)
    }
}

fn to_js<T: serde::Serialize>(value: &T) -> Result<JsValue, JsValue> {
    // json_compatible: None becomes null rather than undefined, matching the
    // Python payloads this replaces.
    value
        .serialize(&serde_wasm_bindgen::Serializer::json_compatible())
        .map_err(|e| JsValue::from_str(&e.to_string()))
}

fn stepper(on_step: &js_sys::Function) -> impl FnMut(&str) + '_ {
    move |label: &str| {
        let _ = on_step.call1(&JsValue::NULL, &JsValue::from_str(label));
    }
}

fn rgb(rgb: &[u8], width: usize, height: usize) -> Result<genesis_prnu::Rgb, JsValue> {
    if rgb.len() != width * height * 3 {
        return Err(JsValue::from_str(
            "rgb buffer does not match its dimensions",
        ));
    }
    Ok(genesis_prnu::Rgb::new(rgb.to_vec(), width, height))
}

/// `_score_against` for a decoded image: aligned, then the portrait retry,
/// then border strip and scale search. Returns `{pce, path, orientation,
/// scale, borderStripped, turned, attempts}`. `onStep(label)` is called with
/// the same progress labels the Python used.
#[wasm_bindgen(js_name = scoreAgainst)]
pub fn score_against(
    rgb_bytes: &[u8],
    width: usize,
    height: usize,
    body: &Body,
    on_step: &js_sys::Function,
) -> Result<JsValue, JsValue> {
    let image = rgb(rgb_bytes, width, height)?;
    let result =
        genesis_prnu::score_against(&image, &body.planes, body.pattern, &mut stepper(on_step));
    to_js(&result)
}

/// `_score_against` for a RAW file the desktop decoded in Python: the CFA
/// planes as a `plane_<c>` `.npz`, plus the developed RGB for the search.
#[wasm_bindgen(js_name = scoreAgainstRaw)]
pub fn score_against_raw(
    planes_npz: &[u8],
    rgb_bytes: &[u8],
    width: usize,
    height: usize,
    body: &Body,
    on_step: &js_sys::Function,
) -> Result<JsValue, JsValue> {
    let planes = genesis_prnu::kfile::load_planes(planes_npz)
        .map_err(|e| JsValue::from_str(&format!("could not read RAW planes: {e}")))?;
    let image = rgb(rgb_bytes, width, height)?;
    let result =
        genesis_prnu::score_against_raw(&planes, &image, &body.planes, &mut stepper(on_step));
    to_js(&result)
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
struct Signals {
    effective_strength: Option<f64>,
    resampling_peak: Option<f64>,
    detail: Option<f64>,
}

/// The advisory signals (`console/app.py` `_signals`), each `null` when it
/// does not apply. Advisory only: none of them may raise a verdict.
///
/// `effectiveStrength` needs the image on K's lattice, so it is computed only
/// when `aligned` (from `rawPlanesNpz` for a RAW, else from the pixels).
/// `resamplingPeak` and `detail` read the delivered pixels, so a RAW (which
/// passes `rawPlanesNpz`) gets neither.
#[wasm_bindgen]
pub fn signals(
    rgb_bytes: &[u8],
    width: usize,
    height: usize,
    body: &Body,
    aligned: bool,
    raw_planes_npz: Option<Vec<u8>>,
) -> Result<JsValue, JsValue> {
    use genesis_prnu::consistency::{
        effective_strength, high_frequency_content, resampling_peak, DEFAULT_PLANE,
    };

    let image = rgb(rgb_bytes, width, height)?;
    let is_raw = raw_planes_npz.is_some();
    let planes = match &raw_planes_npz {
        Some(npz) => genesis_prnu::kfile::load_planes(npz).ok(),
        None => Some(genesis_prnu::image_decode::planes_from_rgb(
            &image.data,
            width,
            height,
            body.pattern,
            None,
        )),
    };
    let signals = Signals {
        effective_strength: if aligned {
            planes.and_then(|p| effective_strength(&p, &body.planes, DEFAULT_PLANE))
        } else {
            None
        },
        resampling_peak: (!is_raw).then(|| resampling_peak(&image, 1024)),
        detail: (!is_raw).then(|| high_frequency_content(&image)),
    };
    to_js(&signals)
}

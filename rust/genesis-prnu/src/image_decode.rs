//! Decode a delivered (non-RAW) image and sample it back onto the CFA
//! photosite lattice -- a Rust port of `fingerprint/prnu.py::load_delivered_planes`.
//! See `docs/wasm-scoring-plan.md` Phase 4.
//!
//! [`planes_from_rgb`] does the sampling from pixels already decoded, which
//! is what the verify path uses: JPEG is decoded by libjpeg-turbo so the
//! pixels are Pillow's exactly (`crate::hashing` explains why the `image`
//! crate's decoder is not). [`load_delivered_planes`] decodes with the
//! `image` crate first, for callers holding file bytes.

use std::collections::BTreeMap;

use ndarray::Array2;

/// CFA colour index -> RGB channel, matching `prnu.py`'s default `channels`
/// (`{0: 0, 1: 1, 2: 2, 3: 1}`: red, green, blue, green).
pub fn default_channels() -> BTreeMap<i32, usize> {
    BTreeMap::from([(0, 0), (1, 1), (2, 2), (3, 1)])
}

/// Decode `bytes` (JPEG/PNG/TIFF -- whatever the `image` crate's format
/// guesser recognises) and sample each 2x2 CFA phase from its RGB channel,
/// matching `load_delivered_planes`. `pattern` is the 2x2 CFA layout from
/// the K file's `meta["cfa_pattern"]`; `channels` defaults per
/// [`default_channels`] when `None`.
pub fn load_delivered_planes(
    bytes: &[u8],
    pattern: [[i32; 2]; 2],
    channels: Option<&BTreeMap<i32, usize>>,
) -> Result<BTreeMap<i32, Array2<f32>>, image::ImageError> {
    let rgb = image::load_from_memory(bytes)?.to_rgb8();
    let (width, height) = (rgb.width() as usize, rgb.height() as usize);
    Ok(planes_from_rgb(
        rgb.as_raw(),
        width,
        height,
        pattern,
        channels,
    ))
}

/// Sample each 2x2 CFA phase of canonical RGB8 (`width * height * 3` bytes,
/// row-major) from its RGB channel, scaled to `[0, 1]`.
pub fn planes_from_rgb(
    rgb: &[u8],
    width: usize,
    height: usize,
    pattern: [[i32; 2]; 2],
    channels: Option<&BTreeMap<i32, usize>>,
) -> BTreeMap<i32, Array2<f32>> {
    assert_eq!(
        rgb.len(),
        width * height * 3,
        "rgb buffer does not match its dimensions"
    );
    let default = default_channels();
    let channels = channels.unwrap_or(&default);

    let mut colours: Vec<i32> = pattern.iter().flatten().copied().collect();
    colours.sort_unstable();
    colours.dedup();

    let mut planes = BTreeMap::new();
    for &c in &colours {
        let (mut pi, mut pj) = (0usize, 0usize);
        'outer: for (i, row) in pattern.iter().enumerate() {
            for (j, &colour) in row.iter().enumerate() {
                if colour == c {
                    pi = i;
                    pj = j;
                    break 'outer;
                }
            }
        }
        let ch = *channels.get(&c).unwrap_or(&1);

        let out_h = (height - pi).div_ceil(2);
        let out_w = (width - pj).div_ceil(2);
        let plane = Array2::from_shape_fn((out_h, out_w), |(oi, oj)| {
            let (y, x) = (pi + 2 * oi, pj + 2 * oj);
            rgb[(y * width + x) * 3 + ch] as f32 / 255.0
        });
        planes.insert(c, plane);
    }
    planes
}

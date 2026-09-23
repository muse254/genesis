//! Decode a delivered (non-RAW) image and sample it back onto the CFA
//! photosite lattice -- a Rust port of `fingerprint/prnu.py::load_delivered_planes`.
//! See `docs/wasm-scoring-plan.md` Phase 4.

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
    let img = image::load_from_memory(bytes)?;
    let rgb = img.to_rgb8();
    let (width, height) = (rgb.width() as usize, rgb.height() as usize);

    let default = default_channels();
    let channels = channels.unwrap_or(&default);

    let mut colours: Vec<i32> = pattern.iter().flatten().copied().collect();
    colours.sort_unstable();
    colours.dedup();

    let mut planes = BTreeMap::new();
    for &c in &colours {
        let (mut pi, mut pj) = (0usize, 0usize);
        'outer: for i in 0..2 {
            for j in 0..2 {
                if pattern[i][j] == c {
                    pi = i;
                    pj = j;
                    break 'outer;
                }
            }
        }
        let ch = *channels.get(&c).unwrap_or(&1);

        let out_h = (height - pi + 1) / 2;
        let out_w = (width - pj + 1) / 2;
        let mut plane = Array2::<f32>::zeros((out_h, out_w));
        for oi in 0..out_h {
            let y = pi + 2 * oi;
            for oj in 0..out_w {
                let x = pj + 2 * oj;
                let px = rgb.get_pixel(x as u32, y as u32);
                plane[[oi, oj]] = px[ch] as f32 / 255.0;
            }
        }
        planes.insert(c, plane);
    }

    Ok(planes)
}

//! The two content hashes of an image record -- a Rust port of
//! `ingest/hashing.py`'s `pixel_sha256` and `perceptual_hash`, so the verify
//! page and the desktop app (`core/`) compute them in the browser instead of
//! posting the photo to a scoring service.
//!
//! Both start from canonical 8-bit RGB, row-major. **Producing those bytes is
//! the caller's job, and it is the fragile part**: `pixel_sha256` is exact, so
//! a decoder that differs from Python's by one level in one pixel gives a
//! different hash. Python decodes JPEG with the libjpeg-turbo that Pillow
//! bundles (3.1.4.1 for Pillow 12.3.0), and the `image` crate's JPEG decoder
//! does *not* reproduce it -- measured on `a-piece-of-quiet.jpg`, 15% of bytes
//! differed, by up to 5 levels. The verify page therefore decodes JPEG with
//! that same libjpeg-turbo compiled to WASM (`core/jpeg/`) and hands the
//! RGB here. [`decode_rgb8`] is only for the lossless formats, where any
//! correct decoder agrees.
//!
//! `perceptual_hash` reproduces Pillow's integer `convert("L")` and its
//! fixed-point LANCZOS resize bit for bit (ported from Pillow 12.3.0's
//! `Convert.c` and `Resample.c`), so it matches exactly in practice rather
//! than only within the verify page's 10-bit Hamming slack.

use sha2::{Digest, Sha256};

use crate::resample::resize_l8_lanczos;

/// Must equal `PIXEL_HASH_VERSION` in `ingest/hashing.py`.
pub const PIXEL_HASH_VERSION: &[u8] = b"genesis-pixels-v1";
/// `PHASH_RESIZE` in `ingest/hashing.py`.
const PHASH_RESIZE: usize = 32;
/// `PHASH_DCT_SIZE` in `ingest/hashing.py`.
const PHASH_DCT_SIZE: usize = 8;

/// SHA-256 over the version tag, the array shape `(height, width, 3)` as
/// 4-byte big-endian integers, then the RGB bytes -- the same digest as
/// `pixel_sha256` in `ingest/hashing.py`.
pub fn pixel_sha256(rgb: &[u8], width: usize, height: usize) -> [u8; 32] {
    assert_eq!(
        rgb.len(),
        width * height * 3,
        "rgb buffer does not match its dimensions"
    );
    let mut h = Sha256::new();
    h.update(PIXEL_HASH_VERSION);
    for dim in [height, width, 3] {
        h.update((dim as u32).to_be_bytes());
    }
    h.update(rgb);
    h.finalize().into()
}

/// 64-bit DCT pHash, as `perceptual_hash` in `ingest/hashing.py`: greyscale,
/// LANCZOS down to 32x32, 2-D orthonormal DCT-II, keep the 8x8
/// low-frequency block, one bit per coefficient above the median of the
/// block without its DC term. Bit 63 is coefficient (0, 0).
pub fn perceptual_hash(rgb: &[u8], width: usize, height: usize) -> u64 {
    assert_eq!(
        rgb.len(),
        width * height * 3,
        "rgb buffer does not match its dimensions"
    );

    let grey = grey_l8(rgb);
    let small = resize_l8_lanczos(&grey, width, height, PHASH_RESIZE, PHASH_RESIZE);
    let values: Vec<f64> = small.iter().map(|&v| v as f64).collect();

    // dct(dct(values, axis=0), axis=1), both orthonormal.
    let n = PHASH_RESIZE;
    let basis = dct_basis(n);
    let mut cols = vec![0.0; n * n];
    for k in 0..n {
        for x in 0..n {
            cols[k * n + x] = (0..n).map(|y| basis[k * n + y] * values[y * n + x]).sum();
        }
    }
    let mut coefficients = vec![0.0; n * n];
    for y in 0..n {
        for k in 0..n {
            coefficients[y * n + k] = (0..n).map(|x| basis[k * n + x] * cols[y * n + x]).sum();
        }
    }

    let block: Vec<f64> = (0..PHASH_DCT_SIZE)
        .flat_map(|r| (0..PHASH_DCT_SIZE).map(move |c| (r, c)))
        .map(|(r, c)| coefficients[r * n + c])
        .collect();

    // np.median over the 63 AC terms: odd count, so the exact middle value.
    let mut ac = block[1..].to_vec();
    ac.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let median = ac[ac.len() / 2];

    let mut bits = 0u64;
    for (i, &value) in block.iter().enumerate() {
        if value > median {
            bits |= 1 << (block.len() - 1 - i);
        }
    }
    bits
}

/// Decode a PNG or TIFF to canonical RGB8 `(rgb, width, height)`.
///
/// Refuses JPEG (see the module docs: this decoder would give the wrong
/// pixel hash) and anything above 8 bits per channel, where Pillow's
/// narrowing to RGB is its own rule rather than a plain rescale.
pub fn decode_rgb8(bytes: &[u8]) -> Result<(Vec<u8>, usize, usize), String> {
    use image::{ColorType, ImageFormat};

    let format = image::guess_format(bytes).map_err(|e| e.to_string())?;
    if !matches!(format, ImageFormat::Png | ImageFormat::Tiff) {
        return Err(format!("{format:?} is not decoded here"));
    }
    let img = image::load_from_memory_with_format(bytes, format).map_err(|e| e.to_string())?;
    if !matches!(
        img.color(),
        ColorType::L8 | ColorType::La8 | ColorType::Rgb8 | ColorType::Rgba8
    ) {
        return Err(format!("{:?} images are not supported", img.color()));
    }
    // Alpha is dropped, not composited, matching Pillow's convert("RGB").
    let rgb = img.to_rgb8();
    let (w, h) = (rgb.width() as usize, rgb.height() as usize);
    Ok((rgb.into_raw(), w, h))
}

/// Orthonormal DCT-II matrix, row k = frequency, as scipy's `norm="ortho"`.
fn dct_basis(n: usize) -> Vec<f64> {
    let mut m = vec![0.0; n * n];
    for k in 0..n {
        let scale = if k == 0 {
            (1.0 / n as f64).sqrt()
        } else {
            (2.0 / n as f64).sqrt()
        };
        for i in 0..n {
            m[k * n + i] = scale
                * (std::f64::consts::PI * k as f64 * (2 * i + 1) as f64 / (2 * n) as f64).cos();
        }
    }
    m
}

/// Pillow's `convert("L")` from RGB: `L24(rgb) >> 16` (`Convert.c` `rgb2l`).
/// Shared with [`crate::search`], which greys images the same way.
pub(crate) fn grey_l8(rgb: &[u8]) -> Vec<u8> {
    rgb.as_chunks::<3>()
        .0
        .iter()
        .map(|p| {
            ((p[0] as u32 * 19595 + p[1] as u32 * 38470 + p[2] as u32 * 7471 + 0x8000) >> 16) as u8
        })
        .collect()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn gradient(w: usize, h: usize) -> Vec<u8> {
        (0..w * h)
            .flat_map(|i| {
                let (x, y) = (i % w, i / w);
                [
                    (x * 255 / w) as u8,
                    (y * 255 / h) as u8,
                    ((x + y) * 127 / (w + h)) as u8,
                ]
            })
            .collect()
    }

    #[test]
    fn pixel_hash_binds_the_shape() {
        // The same bytes at different dimensions are different rasters.
        let rgb = gradient(6, 4);
        assert_ne!(pixel_sha256(&rgb, 6, 4), pixel_sha256(&rgb, 4, 6));
        assert_ne!(pixel_sha256(&rgb, 6, 4), pixel_sha256(&rgb, 24, 1));
    }

    #[test]
    fn pixel_hash_sees_a_single_level() {
        let mut rgb = gradient(16, 16);
        let before = pixel_sha256(&rgb, 16, 16);
        rgb[100] ^= 1;
        assert_ne!(before, pixel_sha256(&rgb, 16, 16));
    }

    #[test]
    fn pixel_hash_is_versioned() {
        // Hand-assembled digest, so a change to the preimage layout fails here
        // and not only against the Python fixtures.
        let rgb = [1u8, 2, 3, 4, 5, 6];
        let mut h = Sha256::new();
        h.update(b"genesis-pixels-v1");
        h.update([0, 0, 0, 1, 0, 0, 0, 2, 0, 0, 0, 3]);
        h.update(rgb);
        let want: [u8; 32] = h.finalize().into();
        assert_eq!(pixel_sha256(&rgb, 2, 1), want);
    }

    #[test]
    #[should_panic(expected = "does not match its dimensions")]
    fn wrong_buffer_length_panics() {
        pixel_sha256(&[0; 10], 2, 2);
    }

    #[test]
    fn perceptual_hash_survives_a_downscale() {
        // The job the pHash exists for: a smaller copy still links back. The
        // verify page allows 10 bits; a clean halving should be far inside it.
        // A photo-like fixture, not `gradient`: a pure gradient has dozens of
        // near-zero DCT terms sitting on the median, and Python's own pHash
        // moves 28 bits on it under the same halving.
        let bytes = std::fs::read(concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/tests/fixtures/hashing/png_180x260.png"
        ))
        .unwrap();
        let (rgb, w, h) = decode_rgb8(&bytes).unwrap();
        let full = perceptual_hash(&rgb, w, h);

        let img = image::RgbImage::from_raw(w as u32, h as u32, rgb).unwrap();
        let half = image::imageops::resize(
            &img,
            w as u32 / 2,
            h as u32 / 2,
            image::imageops::FilterType::Triangle,
        );
        let small = perceptual_hash(half.as_raw(), w / 2, h / 2);

        assert!(
            (full ^ small).count_ones() <= 4,
            "moved {} bits",
            (full ^ small).count_ones()
        );
    }

    #[test]
    fn perceptual_hash_tells_different_images_apart() {
        let a = gradient(64, 64);
        let b: Vec<u8> = a.iter().rev().copied().collect();
        assert!((perceptual_hash(&a, 64, 64) ^ perceptual_hash(&b, 64, 64)).count_ones() > 10);
    }

    #[test]
    fn resize_to_the_same_size_is_the_identity() {
        let grey: Vec<u8> = (0..32 * 32).map(|i| (i * 7 % 256) as u8).collect();
        assert_eq!(resize_l8_lanczos(&grey, 32, 32, 32, 32), grey);
    }

    #[test]
    fn resize_keeps_a_flat_image_flat() {
        // Taps sum to 1 in fixed point, so a constant survives exactly.
        let grey = vec![137u8; 500 * 90];
        assert!(resize_l8_lanczos(&grey, 500, 90, 32, 32)
            .iter()
            .all(|&v| v == 137));
    }
}

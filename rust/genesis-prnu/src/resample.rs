//! Pillow's `Image.resize`, for the two cases this crate needs, ported from
//! `libImaging/Resample.c` (Pillow 12.3.0) so results match bit for bit:
//!
//! - [`resize_l8_lanczos`]: mode `L`, `LANCZOS`, 8-bit fixed point. The
//!   perceptual hash's 32x32 reduction ([`crate::hashing`]).
//! - [`resize_f32_box`]: mode `F`, `BOX`, double accumulation with float32
//!   between passes. `prnu._area_resize`, the heart of the scale search
//!   ([`crate::search`]): a resize *averages* neighbours, so K has to be
//!   area-averaged the same way to still line up with a resized photo.
//!
//! Both are two-pass (horizontal, then vertical), each pass skipped when its
//! dimension is unchanged, as `ImagingResampleInner` does. Pillow resamples
//! only the rows the vertical pass will read; that saves work but not a
//! single value, so this resamples all of them.

use ndarray::Array2;

/// `precompute_coeffs`: per output sample, the first input index and the tap
/// count, plus `ksize` normalised taps per sample (unused ones are zero).
struct Coefficients {
    bounds: Vec<(usize, usize)>,
    taps: Vec<f64>,
    ksize: usize,
}

fn precompute(
    in_size: usize,
    out_size: usize,
    filter: fn(f64) -> f64,
    support: f64,
) -> Coefficients {
    // Pillow computes the scale from float box edges; for whole-image
    // resizes those are exact integers, so this is the same division.
    let scale = in_size as f64 / out_size as f64;
    let filterscale = scale.max(1.0);
    let support = support * filterscale;
    let ksize = support.ceil() as usize * 2 + 1;
    let inv = 1.0 / filterscale;

    let mut bounds = Vec::with_capacity(out_size);
    let mut taps = vec![0.0f64; out_size * ksize];
    for xx in 0..out_size {
        let center = (xx as f64 + 0.5) * scale;
        // C's (int) cast truncates toward zero.
        let xmin = ((center - support + 0.5) as i64).max(0) as usize;
        let xmax = ((center + support + 0.5) as i64).min(in_size as i64) as usize - xmin;
        let k = &mut taps[xx * ksize..xx * ksize + xmax];
        let mut ww = 0.0;
        for (x, tap) in k.iter_mut().enumerate() {
            *tap = filter((x as f64 + xmin as f64 - center + 0.5) * inv);
            ww += *tap;
        }
        if ww != 0.0 {
            for tap in k.iter_mut() {
                *tap /= ww;
            }
        }
        bounds.push((xmin, xmax));
    }
    Coefficients {
        bounds,
        taps,
        ksize,
    }
}

fn sinc(x: f64) -> f64 {
    if x == 0.0 {
        return 1.0;
    }
    let x = x * std::f64::consts::PI;
    x.sin() / x
}

fn lanczos(x: f64) -> f64 {
    if (-3.0..3.0).contains(&x) {
        sinc(x) * sinc(x / 3.0)
    } else {
        0.0
    }
}

fn box_filter(x: f64) -> f64 {
    if x > -0.5 && x <= 0.5 {
        1.0
    } else {
        0.0
    }
}

// ---- 8-bit, fixed point ----

const PRECISION_BITS: u32 = 32 - 8 - 2;

/// `normalize_coeffs_8bpc`: taps to fixed point, rounded away from zero.
fn fixed_point(c: &Coefficients) -> Vec<i32> {
    c.taps
        .iter()
        .map(|&k| {
            let scaled = k * (1u32 << PRECISION_BITS) as f64;
            if k < 0.0 {
                (-0.5 + scaled) as i32
            } else {
                (0.5 + scaled) as i32
            }
        })
        .collect()
}

fn clip8(v: i32) -> u8 {
    (v >> PRECISION_BITS).clamp(0, 255) as u8
}

/// Mode `L`, `LANCZOS`: `src` is `w * h` bytes, row-major.
pub fn resize_l8_lanczos(src: &[u8], w: usize, h: usize, out_w: usize, out_h: usize) -> Vec<u8> {
    let horizontal = if out_w != w {
        let c = precompute(w, out_w, lanczos, 3.0);
        let kk = fixed_point(&c);
        let mut out = vec![0u8; out_w * h];
        for y in 0..h {
            let row = &src[y * w..(y + 1) * w];
            for (xx, &(xmin, n)) in c.bounds.iter().enumerate() {
                let k = &kk[xx * c.ksize..];
                let mut ss = 1i32 << (PRECISION_BITS - 1);
                for x in 0..n {
                    ss = ss.wrapping_add(row[xmin + x] as i32 * k[x]);
                }
                out[y * out_w + xx] = clip8(ss);
            }
        }
        out
    } else {
        src.to_vec()
    };

    if out_h == h {
        return horizontal;
    }
    let c = precompute(h, out_h, lanczos, 3.0);
    let kk = fixed_point(&c);
    let mut out = vec![0u8; out_w * out_h];
    for (yy, &(ymin, n)) in c.bounds.iter().enumerate() {
        let k = &kk[yy * c.ksize..];
        for x in 0..out_w {
            let mut ss = 1i32 << (PRECISION_BITS - 1);
            for y in 0..n {
                ss = ss.wrapping_add(horizontal[(ymin + y) * out_w + x] as i32 * k[y]);
            }
            out[yy * out_w + x] = clip8(ss);
        }
    }
    out
}

// ---- float32 ----

/// Mode `F`, `BOX`: `Image.fromarray(field, "F").resize((out_w, out_h), BOX)`.
pub fn resize_f32_box(field: &Array2<f32>, out_w: usize, out_h: usize) -> Array2<f32> {
    let (h, w) = field.dim();
    let horizontal = if out_w != w {
        let c = precompute(w, out_w, box_filter, 0.5);
        Array2::from_shape_fn((h, out_w), |(y, xx)| {
            let (xmin, n) = c.bounds[xx];
            let k = &c.taps[xx * c.ksize..];
            let mut ss = 0.0f64;
            for x in 0..n {
                ss += field[[y, xmin + x]] as f64 * k[x];
            }
            ss as f32
        })
    } else {
        field.clone()
    };

    if out_h == h {
        return horizontal;
    }
    let c = precompute(h, out_h, box_filter, 0.5);
    Array2::from_shape_fn((out_h, out_w), |(yy, x)| {
        let (ymin, n) = c.bounds[yy];
        let k = &c.taps[yy * c.ksize..];
        let mut ss = 0.0f64;
        for y in 0..n {
            ss += horizontal[[ymin + y, x]] as f64 * k[y];
        }
        ss as f32
    })
}

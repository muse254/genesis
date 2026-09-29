//! The advisory signals verification reports beside a verdict -- a port of
//! `fingerprint/consistency.py`'s `effective_strength`, `resampling_peak`
//! and `high_frequency_content`. See `docs/shared-verify-plan.md`, phase A.
//!
//! **Advisory, never a verdict.** Each was measured to overlap between
//! genuine frames and forgeries that clear PCE (best AUC 0.800; see the
//! Python docstrings for the numbers). They may add doubt and may never add
//! confidence; only a chain read grants `registered`.

use std::collections::BTreeMap;

use ndarray::Array2;
use rustfft::num_complex::Complex64;
use rustfft::FftPlanner;

use crate::hashing::grey_l8;
use crate::noise::noise_residual;
use crate::search::Rgb;

/// `consistency.DEFAULT_PLANE`: the second green.
pub const DEFAULT_PLANE: i32 = 3;
/// `consistency.DETAIL_FLOOR`: below this median tile Laplacian variance a
/// frame carries nothing measurable, however genuine it is.
pub const DETAIL_FLOOR: f64 = 200.0;

/// `effective_strength`: `alpha_hat = <W, J*K> / ||J*K||^2` on one plane.
/// `None` when the plane is missing or the lattices differ (Python raises
/// `ValueError`, which the caller treats as "absent").
pub fn effective_strength(
    planes: &BTreeMap<i32, Array2<f32>>,
    k: &BTreeMap<i32, Array2<f32>>,
    plane: i32,
) -> Option<f64> {
    let (image, field) = (planes.get(&plane)?, k.get(&plane)?);
    if image.dim() != field.dim() {
        return None;
    }
    let residual = noise_residual(image);
    let (mut num, mut energy) = (0.0f64, 0.0f64);
    for ((&w, &j), &kk) in residual.iter().zip(image.iter()).zip(field.iter()) {
        let expected = j as f64 * kk as f64;
        num += w as f64 * expected;
        energy += expected * expected;
    }
    Some(if energy <= 0.0 { 0.0 } else { num / energy })
}

/// Greyscale as Pillow's `convert("L")`, as float64 rows.
fn grey(image: &Rgb) -> Array2<f64> {
    let l = grey_l8(&image.data);
    Array2::from_shape_fn((image.height, image.width), |(y, x)| {
        l[y * image.width + x] as f64
    })
}

/// `np.median`: the middle value, or the mean of the two middle values.
fn median(mut v: Vec<f64>) -> f64 {
    v.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let n = v.len();
    if n % 2 == 1 {
        v[n / 2]
    } else {
        (v[n / 2 - 1] + v[n / 2]) / 2.0
    }
}

/// `resampling_peak`: periodicity in the second difference, as left by
/// interpolation. Measured at AUC 0.517, i.e. chance, as a population
/// discriminator; kept because it is nearly free.
pub fn resampling_peak(image: &Rgb, side: usize) -> f64 {
    let g = grey(image);
    let (h, w) = g.dim();
    let side = side.min(h).min(w);
    let (y0, x0) = ((h - side) / 2, (w - side) / 2);
    let crop = g.slice(ndarray::s![y0..y0 + side, x0..x0 + side]);

    // mean over rows of |second difference along each row|
    let n = side.saturating_sub(2);
    if n == 0 {
        return 0.0;
    }
    let mut magnitude = vec![0.0f64; n];
    for row in crop.rows() {
        for (i, m) in magnitude.iter_mut().enumerate() {
            *m += (row[i + 2] - 2.0 * row[i + 1] + row[i]).abs();
        }
    }
    for m in magnitude.iter_mut() {
        *m /= side as f64;
    }
    let mean = magnitude.iter().sum::<f64>() / n as f64;

    // np.hanning(n)
    let window = |i: usize| {
        if n == 1 {
            1.0
        } else {
            0.5 - 0.5 * (2.0 * std::f64::consts::PI * i as f64 / (n - 1) as f64).cos()
        }
    };
    let mut buf: Vec<Complex64> = (0..n)
        .map(|i| Complex64::new((magnitude[i] - mean) * window(i), 0.0))
        .collect();
    FftPlanner::new().plan_fft_forward(n).process(&mut buf);

    // np.fft.rfft keeps the first n/2 + 1 bins.
    let mut spectrum: Vec<f64> = buf[..n / 2 + 1].iter().map(|c| c.norm()).collect();
    for s in spectrum.iter_mut().take(4) {
        *s = 0.0; // DC and the lowest bins carry scene, not lattice
    }
    let max = spectrum.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let med = median(spectrum);
    if med <= 0.0 {
        0.0
    } else {
        max / med
    }
}

/// `high_frequency_content`: median Laplacian variance over a 6x6 grid of
/// tiles of up to 600px. Tiled, so a portrait with a sharp face and a soft
/// background still counts as detailed; only soft-everywhere is flagged.
pub fn high_frequency_content(image: &Rgb) -> f64 {
    let g = grey(image);
    let (h, w) = g.dim();
    let (grid, size) = (6usize, 600usize.min(h).min(w));

    let mut values = Vec::with_capacity(grid * grid);
    for i in 0..grid {
        for j in 0..grid {
            let y = ((h - size) as f64 * i as f64 / (grid - 1) as f64) as usize;
            let x = ((w - size) as f64 * j as f64 / (grid - 1) as f64) as usize;
            values.push(laplace_variance(&g, y, x, size));
        }
    }
    median(values)
}

/// Population variance of `scipy.ndimage.laplace` over one tile, with
/// scipy's default `reflect` boundary (`d c b a | a b c d`): the neighbour
/// past an edge is the edge itself.
fn laplace_variance(g: &Array2<f64>, y0: usize, x0: usize, size: usize) -> f64 {
    let at = |y: isize, x: isize| {
        let yy = y.clamp(0, size as isize - 1) as usize;
        let xx = x.clamp(0, size as isize - 1) as usize;
        g[[y0 + yy, x0 + xx]]
    };
    let n = (size * size) as f64;
    let (mut sum, mut sum_sq) = (0.0f64, 0.0f64);
    let mut values = Vec::with_capacity(size * size);
    for y in 0..size as isize {
        for x in 0..size as isize {
            let c = at(y, x);
            let v =
                (at(y - 1, x) + at(y + 1, x) - 2.0 * c) + (at(y, x - 1) + at(y, x + 1) - 2.0 * c);
            sum += v;
            values.push(v);
        }
    }
    let mean = sum / n;
    for v in values {
        sum_sq += (v - mean) * (v - mean);
    }
    sum_sq / n
}

#[cfg(test)]
mod tests {
    use super::*;

    fn flat(w: usize, h: usize, v: u8) -> Rgb {
        Rgb::new(vec![v; w * h * 3], w, h)
    }

    #[test]
    fn a_flat_image_has_no_detail() {
        assert_eq!(high_frequency_content(&flat(40, 30, 128)), 0.0);
    }

    #[test]
    fn a_checkerboard_is_all_detail() {
        let (w, h) = (40, 30);
        let data = (0..w * h)
            .flat_map(|i| [((i % w + i / w) % 2 * 255) as u8; 3])
            .collect();
        assert!(high_frequency_content(&Rgb::new(data, w, h)) > DETAIL_FLOOR);
    }

    #[test]
    fn median_matches_numpy() {
        assert_eq!(median(vec![3.0, 1.0, 2.0]), 2.0);
        assert_eq!(median(vec![4.0, 1.0, 2.0, 3.0]), 2.5);
    }

    #[test]
    fn strength_is_absent_without_a_shared_lattice() {
        let a = BTreeMap::from([(3, Array2::<f32>::zeros((4, 4)))]);
        let b = BTreeMap::from([(3, Array2::<f32>::zeros((4, 5)))]);
        assert_eq!(effective_strength(&a, &b, 3), None);
        assert_eq!(effective_strength(&a, &BTreeMap::new(), 3), None);
    }
}

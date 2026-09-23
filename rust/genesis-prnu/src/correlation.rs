//! Circular cross-correlation, PCE, and `score` -- a Rust port of
//! `fingerprint/prnu.py::cross_correlation`/`_pce_of`/`pce`/`score`. See
//! `docs/wasm-scoring-plan.md` Phase 3.

use std::collections::BTreeMap;
use std::sync::Arc;

use ndarray::Array2;
use rustfft::num_complex::Complex64;
use rustfft::{Fft, FftPlanner};

/// Fraction of full scale at which a photosite counts as saturated, matching
/// `prnu.py`'s `SATURATION_LEVEL`.
pub const SATURATION_LEVEL: f32 = 0.99;

/// Zero-mean a field in `f64`, matching `_zero_mean_flat`.
fn zero_mean_flat(a: &Array2<f64>) -> Array2<f64> {
    let mean = a.iter().sum::<f64>() / (a.len() as f64);
    a.mapv(|v| v - mean)
}

/// 1-D FFT along `axis` of a complex 2-D array, forward if `inverse` is
/// false. `FftPlanner` caches algorithms per length, so reuse it across the
/// row pass and the column pass.
fn fft_axis(a: &mut Array2<Complex64>, axis: ndarray::Axis, inverse: bool) {
    let n = a.len_of(axis);
    if n == 0 {
        return;
    }
    let mut planner = FftPlanner::new();
    let fft: Arc<dyn Fft<f64>> = if inverse {
        planner.plan_fft_inverse(n)
    } else {
        planner.plan_fft_forward(n)
    };

    let other = if axis == ndarray::Axis(0) {
        ndarray::Axis(1)
    } else {
        ndarray::Axis(0)
    };
    let other_len = a.len_of(other);

    for i in 0..other_len {
        let mut line: Vec<Complex64> = if axis == ndarray::Axis(0) {
            a.column(i).to_vec()
        } else {
            a.row(i).to_vec()
        };
        fft.process(&mut line);
        if axis == ndarray::Axis(0) {
            for (j, v) in line.into_iter().enumerate() {
                a[[j, i]] = v;
            }
        } else {
            for (j, v) in line.into_iter().enumerate() {
                a[[i, j]] = v;
            }
        }
    }
}

/// 2-D FFT (rows then columns), matching `numpy.fft.fft2`'s default axis
/// order for a 2-D array (unnormalised, like `numpy`'s forward transform).
fn fft2(a: &Array2<f64>) -> Array2<Complex64> {
    let mut c = a.mapv(|v| Complex64::new(v, 0.0));
    fft_axis(&mut c, ndarray::Axis(1), false);
    fft_axis(&mut c, ndarray::Axis(0), false);
    c
}

/// 2-D inverse FFT, matching `numpy.fft.ifft2` (normalised by `1/(h*w)`).
fn ifft2(a: &Array2<Complex64>) -> Array2<Complex64> {
    let mut c = a.clone();
    fft_axis(&mut c, ndarray::Axis(1), true);
    fft_axis(&mut c, ndarray::Axis(0), true);
    let n = (a.shape()[0] * a.shape()[1]) as f64;
    c.mapv(|v| v / n)
}

/// Circular cross-correlation surface of two zero-meaned fields, via FFT.
/// Matches `cross_correlation`: `real(ifft2(fft2(a) * conj(fft2(b))))`.
pub fn cross_correlation(a: &Array2<f64>, b: &Array2<f64>) -> Array2<f64> {
    assert_eq!(a.shape(), b.shape(), "cross_correlation: shape mismatch");
    let a0 = zero_mean_flat(a);
    let b0 = zero_mean_flat(b);

    let fa = fft2(&a0);
    let fb = fft2(&b0);
    let prod = ndarray::Zip::from(&fa)
        .and(&fb)
        .map_collect(|&x, &y| x * y.conj());
    let cc = ifft2(&prod);
    cc.mapv(|v| v.re)
}

/// Peak-to-Correlation-Energy of a correlation surface, matching `_pce_of`:
/// peak of `|cc|`, excluding a `(2*half+1)^2` neighbourhood around it
/// (circular wraparound), energy = mean of the squared remainder, signed by
/// the sign of the peak.
pub fn pce_of(cc: &Array2<f64>, squared_size: usize) -> f64 {
    let (h, w) = (cc.shape()[0], cc.shape()[1]);

    let mut peak_idx = (0usize, 0usize);
    let mut peak_abs = f64::NEG_INFINITY;
    let mut peak_val = 0.0f64;
    for i in 0..h {
        for j in 0..w {
            let v = cc[[i, j]];
            if v.abs() > peak_abs {
                peak_abs = v.abs();
                peak_val = v;
                peak_idx = (i, j);
            }
        }
    }

    let half = (squared_size / 2) as i64;
    let mut mask = Array2::<bool>::from_elem((h, w), true);
    for di in -half..=half {
        for dj in -half..=half {
            let ii = (((peak_idx.0 as i64 + di) % h as i64) + h as i64) % h as i64;
            let jj = (((peak_idx.1 as i64 + dj) % w as i64) + w as i64) % w as i64;
            mask[[ii as usize, jj as usize]] = false;
        }
    }

    let mut sum_sq = 0.0f64;
    let mut count = 0usize;
    for i in 0..h {
        for j in 0..w {
            if mask[[i, j]] {
                sum_sq += cc[[i, j]] * cc[[i, j]];
                count += 1;
            }
        }
    }
    if count == 0 {
        return 0.0;
    }
    let energy = sum_sq / (count as f64);
    if energy <= 0.0 {
        return 0.0;
    }
    peak_val.signum() * peak_val * peak_val / energy
}

/// `pce`: PCE between a test residual and a reference field, matching
/// `prnu.py::pce` (default `squared_size=11`).
pub fn pce(residual: &Array2<f64>, reference: &Array2<f64>, squared_size: usize) -> f64 {
    pce_of(&cross_correlation(residual, reference), squared_size)
}

/// One verdict for one image against one body's fingerprint, matching
/// `prnu.py::score`. `planes`/`reference` are CFA colour index -> plane,
/// `f32` as `noise_residual` expects.
pub fn score(
    planes: &BTreeMap<i32, Array2<f32>>,
    reference: &BTreeMap<i32, Array2<f32>>,
    mask_saturated: bool,
) -> f64 {
    let shared: Vec<i32> = reference.keys().filter(|c| planes.contains_key(c)).copied().collect();
    if shared.is_empty() {
        panic!("no CFA plane in common between image and fingerprint");
    }

    let mut total: Option<Array2<f64>> = None;

    for c in shared {
        let plane = &planes[&c];
        let k = &reference[&c];
        assert_eq!(plane.shape(), k.shape(), "score: plane {c} shape mismatch");

        let mut residual = crate::noise::noise_residual(plane);
        let mut expected = ndarray::Zip::from(plane).and(k).map_collect(|&p, &kk| p * kk);

        if mask_saturated {
            let keep = plane.mapv(|p| if p < SATURATION_LEVEL { 1.0f32 } else { 0.0f32 });
            residual = ndarray::Zip::from(&residual).and(&keep).map_collect(|&r, &m| r * m);
            expected = ndarray::Zip::from(&expected).and(&keep).map_collect(|&e, &m| e * m);
        }

        let residual64 = residual.mapv(|v| v as f64);
        let expected64 = expected.mapv(|v| v as f64);
        let cc = cross_correlation(&residual64, &expected64);

        let mean_sq = cc.iter().map(|v| v * v).sum::<f64>() / (cc.len() as f64);
        let rms = mean_sq.sqrt();
        if rms <= 0.0 {
            continue;
        }
        let normalised = cc.mapv(|v| v / rms);
        total = Some(match total {
            None => normalised,
            Some(t) => t + normalised,
        });
    }

    match total {
        Some(t) => pce_of(&t, 11),
        None => 0.0,
    }
}

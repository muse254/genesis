//! Mihcak wavelet-domain Wiener denoiser (`noise_residual`), a Rust port of
//! `fingerprint/prnu.py::noise_residual`/`_variance_estimate`. See
//! `docs/wasm-scoring-plan.md` Phase 2.

use ndarray::Array2;

use crate::wavelet::{clamp_levels, wavedec2};

/// [F09] Appendix A Step 1: decomposition depth, matching `prnu.py`'s
/// `WAVELET_LEVELS`.
pub const WAVELET_LEVELS: usize = 4;
/// [F09] Appendix A Step 2: local-variance window sizes, matching `prnu.py`'s
/// `WIENER_WINDOWS`.
pub const WIENER_WINDOWS: [usize; 4] = [3, 5, 7, 9];
/// Assumed sensor noise sigma, `[0, 1]` scale, matching `prnu.py`'s `SIGMA`.
pub const SIGMA: f64 = 2.0 / 255.0;

/// 1-D box filter with `mode="constant"` (zero-padding) boundary handling,
/// matching `scipy.ndimage.uniform_filter`'s behaviour for a 1-D line:
/// every output element is the sum over a `size`-wide window divided by
/// `size` -- out-of-bounds window positions contribute zero to the sum but
/// still count towards the divisor, they are not excluded from it (that is
/// what distinguishes `mode="constant"` from e.g. clamping the edge value).
/// The window for output index `i` is `[i - size/2, i - size/2 + size - 1]`
/// (integer division), scipy's default `origin=0` convention -- confirmed
/// empirically against `scipy.ndimage.uniform_filter` for both even and odd
/// `size`.
fn box_filter_1d(x: &[f64], size: usize) -> Vec<f64> {
    let n = x.len();
    let mut prefix = vec![0.0f64; n + 1];
    for i in 0..n {
        prefix[i + 1] = prefix[i] + x[i];
    }
    let left = (size / 2) as i64;
    let size_f = size as f64;

    (0..n)
        .map(|i| {
            let lo = i as i64 - left;
            let hi = lo + size as i64 - 1;
            let clipped_lo = lo.max(0);
            let clipped_hi = hi.min(n as i64 - 1);
            let sum = if clipped_lo > clipped_hi {
                0.0
            } else {
                prefix[(clipped_hi + 1) as usize] - prefix[clipped_lo as usize]
            };
            sum / size_f
        })
        .collect()
}

/// Separable 2-D box filter (`scipy.ndimage.uniform_filter(a, size=size,
/// mode="constant")`): 1-D box filter along axis 0, then along axis 1 (order
/// does not matter for a separable box average).
fn box_filter_2d(a: &Array2<f64>, size: usize) -> Array2<f64> {
    let (h, w) = (a.shape()[0], a.shape()[1]);

    let mut tmp = Array2::<f64>::zeros((h, w));
    for j in 0..w {
        let col: Vec<f64> = a.column(j).to_vec();
        let filtered = box_filter_1d(&col, size);
        for (i, v) in filtered.into_iter().enumerate() {
            tmp[[i, j]] = v;
        }
    }

    let mut out = Array2::<f64>::zeros((h, w));
    for i in 0..h {
        let row: Vec<f64> = tmp.row(i).to_vec();
        let filtered = box_filter_1d(&row, size);
        for (j, v) in filtered.into_iter().enumerate() {
            out[[i, j]] = v;
        }
    }
    out
}

/// Mihcak local-variance estimate: minimum, over [`WIENER_WINDOWS`], of a
/// box-filtered squared-coefficient local mean minus `sigma2`, floored at
/// zero. Matches `_variance_estimate`.
fn variance_estimate(coef: &Array2<f64>, sigma2: f64) -> Array2<f64> {
    let squared = coef.mapv(|v| v * v);

    let mut est: Option<Array2<f64>> = None;
    for &w in WIENER_WINDOWS.iter() {
        let local = box_filter_2d(&squared, w);
        let v = local.mapv(|x| (x - sigma2).max(0.0));
        est = Some(match est {
            None => v,
            Some(prev) => {
                let mut out = prev;
                ndarray::Zip::from(&mut out).and(&v).for_each(|a, &b| {
                    if b < *a {
                        *a = b;
                    }
                });
                out
            }
        });
    }
    est.unwrap()
}

/// Extract the PRNU noise residual `W` from one CFA plane, matching
/// `fingerprint/prnu.py::noise_residual` exactly (up to floating-point
/// precision -- this implementation computes in `f64` throughout, the
/// Python reference in `f32`).
///
/// `db8` decomposition to `min(WAVELET_LEVELS, dwt_max_level(min(shape)))`
/// levels (clamped, never below 1), per-detail-coefficient Wiener shrinkage
/// `c * sigma^2 / (var + sigma^2)` with `var` the Mihcak minimum-over-windows
/// local variance estimate, approximation band zeroed, reconstruct, crop
/// back to the input shape.
pub fn noise_residual(plane: &Array2<f32>) -> Array2<f32> {
    let shape = (plane.shape()[0], plane.shape()[1]);
    let plane64 = plane.mapv(|v| v as f64);
    let sigma2 = SIGMA * SIGMA;

    let levels = clamp_levels(shape, WAVELET_LEVELS);
    let mut dec = wavedec2(&plane64, levels);

    dec.approx.fill(0.0);
    fn shrink(band: &mut Array2<f64>, sigma2: f64) {
        let var = variance_estimate(band, sigma2);
        ndarray::Zip::from(band).and(&var).for_each(|c, &v| {
            *c = *c * sigma2 / (v + sigma2);
        });
    }
    for (ch, cv, cd) in dec.details.iter_mut() {
        shrink(ch, sigma2);
        shrink(cv, sigma2);
        shrink(cd, sigma2);
    }

    let residual = dec.waverec2();
    let cropped = residual.slice(ndarray::s![0..shape.0, 0..shape.1]);
    cropped.mapv(|v| v as f32)
}

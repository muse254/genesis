//! `db8`, symmetric-boundary 2-D DWT/IDWT -- a Rust port of the exact
//! numerical convention `pywt.wavedec2`/`pywt.waverec2` use with
//! `mode="symmetric"`.
//!
//! PyWavelets does not ship readable source for this in the wheel installed
//! in this repo's `.venv` (only compiled extensions), so the boundary
//! convention below was reverse-engineered empirically: feeding small known
//! arrays into `pywt.dwt`/`pywt.idwt`/`pywt.dwt2`/`pywt.idwt2` and comparing
//! against hand-built extend+convolve+downsample candidates until an exact
//! match was found across many signal lengths (odd, even, and lengths
//! smaller than the filter itself). See the session notes for the
//! experiment; the findings, confirmed at every step against real
//! `pywt` output:
//!
//! - Extension: **whole-sample symmetric** (edge sample repeated), i.e.
//!   exactly `numpy.pad(x, pad, mode="symmetric")` -- despite the name,
//!   PyWavelets' "symmetric" mode duplicates the edge sample
//!   (`...,c,b,a,|a,b,c,...|,...,c,b,a,...`), not the half-sample variant
//!   that skips it. This also has to work when `pad` exceeds the signal
//!   length (deep decomposition levels on a small image), which
//!   `numpy.pad`'s "symmetric" mode does via periodic reflection with period
//!   `2n`; the index formula below reproduces that.
//! - Padding amount: `pad = filter_len - 2` if the signal length is even,
//!   `filter_len - 1` if odd.
//! - Forward: convolve the extended signal with the filter (`numpy.convolve`,
//!   "full" mode), then take every second sample starting at index `pad + 1`,
//!   for `dwt_coeff_len = (n + filter_len - 1) / 2` (integer division)
//!   samples.
//! - Inverse: zero-upsample each coefficient band by 2, convolve each with
//!   its reconstruction filter ("full" mode), sum, then take `n` samples
//!   starting at index `filter_len - 2` (this offset is constant, unlike the
//!   forward one -- verified across even/odd/short lengths).
//! - 2-D is separable exactly like `pywt.dwt2`/`idwt2`: filter columns
//!   (axis 1, along each row) first into low/high, then filter rows (axis 0,
//!   along each column) of each into four bands. `dwt2` labels: filtering
//!   rows-of-low with (lo, hi) gives (approx, horizontal-detail
//!   `cH`); rows-of-high with (lo, hi) gives (vertical-detail `cV`,
//!   diagonal-detail `cD`). Confirmed against `pywt.dwt2` directly.
//! - `dwt_max_level(n, "db8")` (used to clamp decomposition depth on small
//!   images, matching `fingerprint/prnu.py`'s `noise_residual`) is
//!   `floor(log2(n / (filter_len - 1)))` for `n > filter_len - 1`, else `0`
//!   -- confirmed against `pywt.dwt_max_level` for n in 1..2000.

use ndarray::{Array2, Axis};

/// `db8` filter taps, PyWavelets' own convention (`pywt.Wavelet("db8").filter_bank`),
/// dumped verbatim in `tests/fixtures/filter_bank_db8.json`. Do not substitute
/// a generic Daubechies-8 reference -- sign/normalization conventions vary.
pub const FILTER_LEN: usize = 16;

pub const DEC_LO: [f64; FILTER_LEN] = [
    -0.00011747678412476953,
    0.0006754494064505693,
    -0.00039174037337694705,
    -0.004870352993451574,
    0.008746094047405777,
    0.013981027917398282,
    -0.044088253930794755,
    -0.017369301001807547,
    0.12874742662047847,
    0.0004724845739132828,
    -0.2840155429615469,
    -0.015829105256349306,
    0.5853546836542067,
    0.6756307362972898,
    0.31287159091429995,
    0.05441584224310401,
];

pub const DEC_HI: [f64; FILTER_LEN] = [
    -0.05441584224310401,
    0.31287159091429995,
    -0.6756307362972898,
    0.5853546836542067,
    0.015829105256349306,
    -0.2840155429615469,
    -0.0004724845739132828,
    0.12874742662047847,
    0.017369301001807547,
    -0.044088253930794755,
    -0.013981027917398282,
    0.008746094047405777,
    0.004870352993451574,
    -0.00039174037337694705,
    -0.0006754494064505693,
    -0.00011747678412476953,
];

pub const REC_LO: [f64; FILTER_LEN] = [
    0.05441584224310401,
    0.31287159091429995,
    0.6756307362972898,
    0.5853546836542067,
    -0.015829105256349306,
    -0.2840155429615469,
    0.0004724845739132828,
    0.12874742662047847,
    -0.017369301001807547,
    -0.044088253930794755,
    0.013981027917398282,
    0.008746094047405777,
    -0.004870352993451574,
    -0.00039174037337694705,
    0.0006754494064505693,
    -0.00011747678412476953,
];

pub const REC_HI: [f64; FILTER_LEN] = [
    -0.00011747678412476953,
    -0.0006754494064505693,
    -0.00039174037337694705,
    0.004870352993451574,
    0.008746094047405777,
    -0.013981027917398282,
    -0.044088253930794755,
    0.017369301001807547,
    0.12874742662047847,
    -0.0004724845739132828,
    -0.2840155429615469,
    0.015829105256349306,
    0.5853546836542067,
    -0.6756307362972898,
    0.31287159091429995,
    -0.05441584224310401,
];

/// `pywt.dwt_max_level(n, "db8")`: how many levels of `db8` decomposition
/// `n` samples can carry before the extension swamps the signal.
pub fn dwt_max_level(n: usize) -> usize {
    if n < FILTER_LEN {
        return 0;
    }
    ((n as f64) / ((FILTER_LEN - 1) as f64)).log2().floor() as usize
}

/// `dwt_coeff_len`: the output length of one 1-D `db8` decomposition of an
/// `n`-sample signal in symmetric mode.
fn dwt_coeff_len(n: usize) -> usize {
    (n + FILTER_LEN - 1) / 2
}

/// Whole-sample symmetric extension index, matching `numpy.pad(x, pad,
/// mode="symmetric")`: reflects with the edge sample repeated, periodic with
/// period `2n`, valid for any signed offset `j` (including `|j| >> n`).
fn symmetric_index(j: i64, n: usize) -> usize {
    let n = n as i64;
    let period = 2 * n;
    let m = j.rem_euclid(period);
    (if m < n { m } else { period - 1 - m }) as usize
}

/// One-level 1-D `db8` DWT of `x` with a single filter (`DEC_LO` or
/// `DEC_HI`), symmetric mode.
fn dwt1d(x: &[f64], filt: &[f64; FILTER_LEN]) -> Vec<f64> {
    let n = x.len();
    let pad: i64 = if n.is_multiple_of(2) {
        (FILTER_LEN - 2) as i64
    } else {
        (FILTER_LEN - 1) as i64
    };
    let ext_len = n as i64 + 2 * pad;

    // extended signal, index 0 of `ext` corresponds to original index -pad
    let ext: Vec<f64> = (0..ext_len)
        .map(|i| x[symmetric_index(i - pad, n)])
        .collect();

    let out_len = dwt_coeff_len(n);
    let offset = (pad + 1) as usize;

    // full linear convolution, but only the samples we need (every other one
    // starting at `offset`) -- avoid materialising the whole "full" array.
    (0..out_len)
        .map(|k| {
            let center = offset + 2 * k; // index into the (virtual) full convolution
            let mut acc = 0.0f64;
            for (tap, &h) in filt.iter().enumerate() {
                let ext_idx = center as i64 - tap as i64;
                if ext_idx >= 0 && (ext_idx as usize) < ext.len() {
                    acc += h * ext[ext_idx as usize];
                }
            }
            acc
        })
        .collect()
}

/// One-level 1-D `db8` inverse DWT: reconstruct `n` samples from
/// approximation/detail coefficients `ca`/`cd` using `rec_lo`/`rec_hi`.
fn idwt1d(ca: &[f64], cd: &[f64], n: usize) -> Vec<f64> {
    debug_assert_eq!(ca.len(), cd.len());
    let offset = FILTER_LEN - 2;
    let up_len = 2 * ca.len();
    let full_len = up_len + FILTER_LEN - 1;
    debug_assert!(offset + n <= full_len);

    // Both `ca` and `cd` are zero-upsampled at *even* positions (like
    // `numpy`'s `u[0::2] = c`), each convolved ("full" mode) with its own
    // reconstruction filter, and the two full arrays added elementwise --
    // NOT interleaved by parity into one combined sum. (An earlier version
    // of this function wrongly assumed cd's upsampling sat at odd
    // positions, which happened to type-check but silently produced wrong
    // numbers -- caught by the round-trip test.)
    (0..n)
        .map(|i| {
            let center = offset + i;
            let mut acc = 0.0f64;
            for tap in 0..FILTER_LEN {
                let up_idx = center as i64 - tap as i64;
                if up_idx < 0 || (up_idx as usize) >= up_len {
                    continue;
                }
                let up_idx = up_idx as usize;
                if up_idx.is_multiple_of(2) {
                    acc += REC_LO[tap] * ca[up_idx / 2] + REC_HI[tap] * cd[up_idx / 2];
                }
            }
            acc
        })
        .collect()
}

/// Apply `dwt1d` along `axis` (0 = down each column, 1 = across each row) of
/// a 2-D array, with the given filter.
fn dwt_axis(a: &Array2<f64>, filt: &[f64; FILTER_LEN], axis: Axis) -> Array2<f64> {
    let other_axis = if axis == Axis(0) { Axis(1) } else { Axis(0) };
    let other_len = a.len_of(other_axis);
    let n = a.len_of(axis);
    let out_len = dwt_coeff_len(n);

    let mut out_shape = a.raw_dim();
    out_shape[axis.index()] = out_len;
    let mut out = Array2::<f64>::zeros((out_shape[0], out_shape[1]));

    for i in 0..other_len {
        let line: Vec<f64> = if axis == Axis(0) {
            a.column(i).to_vec()
        } else {
            a.row(i).to_vec()
        };
        let transformed = dwt1d(&line, filt);
        if axis == Axis(0) {
            for (j, v) in transformed.into_iter().enumerate() {
                out[[j, i]] = v;
            }
        } else {
            for (j, v) in transformed.into_iter().enumerate() {
                out[[i, j]] = v;
            }
        }
    }
    out
}

/// Apply `idwt1d` along `axis`, reconstructing `n` samples in that axis from
/// `ca`/`cd` bands.
fn idwt_axis(ca: &Array2<f64>, cd: &Array2<f64>, n: usize, axis: Axis) -> Array2<f64> {
    let other_axis = if axis == Axis(0) { Axis(1) } else { Axis(0) };
    let other_len = ca.len_of(other_axis);

    let mut out_shape = ca.raw_dim();
    out_shape[axis.index()] = n;
    let mut out = Array2::<f64>::zeros((out_shape[0], out_shape[1]));

    for i in 0..other_len {
        let (ca_line, cd_line): (Vec<f64>, Vec<f64>) = if axis == Axis(0) {
            (ca.column(i).to_vec(), cd.column(i).to_vec())
        } else {
            (ca.row(i).to_vec(), cd.row(i).to_vec())
        };
        let rec = idwt1d(&ca_line, &cd_line, n);
        if axis == Axis(0) {
            for (j, v) in rec.into_iter().enumerate() {
                out[[j, i]] = v;
            }
        } else {
            for (j, v) in rec.into_iter().enumerate() {
                out[[i, j]] = v;
            }
        }
    }
    out
}

/// One level's detail bands: `(horizontal, vertical, diagonal)`.
type Details = (Array2<f64>, Array2<f64>, Array2<f64>);

/// One level of 2-D `db8` DWT: `(approx, (horizontal, vertical, diagonal))`,
/// matching `pywt.dwt2`'s `(cA, (cH, cV, cD))`.
fn dwt2(a: &Array2<f64>) -> (Array2<f64>, Details) {
    let lo_cols = dwt_axis(a, &DEC_LO, Axis(1));
    let hi_cols = dwt_axis(a, &DEC_HI, Axis(1));

    let ll = dwt_axis(&lo_cols, &DEC_LO, Axis(0)); // approx
    let lh = dwt_axis(&lo_cols, &DEC_HI, Axis(0)); // horizontal detail (cH)
    let hl = dwt_axis(&hi_cols, &DEC_LO, Axis(0)); // vertical detail (cV)
    let hh = dwt_axis(&hi_cols, &DEC_HI, Axis(0)); // diagonal detail (cD)

    (ll, (lh, hl, hh))
}

/// One level of 2-D `db8` inverse DWT, reconstructing an array of `shape`
/// from `(approx, (ch, cv, cd))`, matching `pywt.idwt2`.
fn idwt2(
    approx: &Array2<f64>,
    ch: &Array2<f64>,
    cv: &Array2<f64>,
    cd: &Array2<f64>,
    shape: (usize, usize),
) -> Array2<f64> {
    let lo_cols_rec = idwt_axis(approx, ch, shape.0, Axis(0));
    let hi_cols_rec = idwt_axis(cv, cd, shape.0, Axis(0));
    idwt_axis(&lo_cols_rec, &hi_cols_rec, shape.1, Axis(1))
}

/// A detail band triple `(horizontal, vertical, diagonal)`, one per
/// decomposition level.
pub type DetailBands = (Array2<f64>, Array2<f64>, Array2<f64>);

/// Full multi-level 2-D `db8` wavelet decomposition, matching
/// `pywt.wavedec2(plane, "db8", level=levels, mode="symmetric")`.
///
/// `coeffs()[0]` is the coarsest approximation band; `coeffs()[1..]` are
/// detail-band triples from coarsest level down to level 1 (finest) -- the
/// same order `pywt.wavedec2`'s returned list uses.
pub struct Wavedec2 {
    pub approx: Array2<f64>,
    pub details: Vec<DetailBands>,
    /// Input shape at the *start* of each level's decomposition (needed to
    /// reconstruct exactly, since IDWT lengths are ambiguous by one sample
    /// without it). `shapes[0]` is the finest (level 1) input shape --
    /// i.e. the original image; `shapes[i]` for level `i+1`'s input.
    /// Stored coarsest-first to line up with `details`.
    shapes: Vec<(usize, usize)>,
}

/// `min(WAVELET_LEVELS, pywt.dwt_max_level(min(shape), "db8"))`, clamped to
/// at least 1 -- exactly `fingerprint/prnu.py::noise_residual`'s clamp.
pub fn clamp_levels(shape: (usize, usize), wanted: usize) -> usize {
    let max_level = dwt_max_level(shape.0.min(shape.1));
    wanted.min(max_level).max(1)
}

/// Decompose `plane` into `levels` levels of `db8`, symmetric mode.
pub fn wavedec2(plane: &Array2<f64>, levels: usize) -> Wavedec2 {
    assert!(levels >= 1, "wavedec2 requires at least one level");

    let mut details = Vec::with_capacity(levels);
    let mut shapes = Vec::with_capacity(levels);
    let mut cur = plane.clone();

    for _ in 0..levels {
        shapes.push((cur.shape()[0], cur.shape()[1]));
        let (approx, band) = dwt2(&cur);
        details.push(band);
        cur = approx;
    }

    details.reverse();
    shapes.reverse();

    Wavedec2 {
        approx: cur,
        details,
        shapes,
    }
}

impl Wavedec2 {
    /// Reconstruct the original plane, matching
    /// `pywt.waverec2(coeffs, "db8", mode="symmetric")` cropped to the
    /// original shape (which is exactly what `noise_residual` does).
    pub fn waverec2(&self) -> Array2<f64> {
        let mut cur = self.approx.clone();
        for (i, (ch, cv, cd)) in self.details.iter().enumerate() {
            let shape = self.shapes[i];
            cur = idwt2(&cur, ch, cv, cd, shape);
        }
        cur
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip_random_shapes() {
        for &(h, w, levels) in &[
            (8usize, 8usize, 1usize),
            (9, 8, 1),
            (65, 97, 2),
            (128, 128, 3),
            (64, 64, 4),
        ] {
            let mut plane = Array2::<f64>::zeros((h, w));
            let mut seed: u64 = (h * 131 + w) as u64;
            for v in plane.iter_mut() {
                seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1);
                *v = ((seed >> 11) as f64 / (1u64 << 53) as f64) * 2.0 - 1.0;
            }
            let dec = wavedec2(&plane, levels);
            let rec = dec.waverec2();
            for (a, b) in plane.iter().zip(rec.iter()) {
                assert!((a - b).abs() < 1e-9, "roundtrip mismatch: {a} vs {b}");
            }
        }
    }

    #[test]
    fn dwt_max_level_matches_pywt_formula() {
        assert_eq!(dwt_max_level(15), 0);
        assert_eq!(dwt_max_level(64), 2);
        assert_eq!(dwt_max_level(128), 3);
        assert_eq!(dwt_max_level(65), 2);
    }
}

//! Scoring an image of unknown provenance against one body: the port of
//! `scoring/app.py::_score_against` and what it calls in `fingerprint/`
//! (`prnu.crop_and_scale_search`, `sensor_field`, `_area_resize`;
//! `stress.strip_uniform_border`, `green_channel`). See
//! `docs/shared-verify-plan.md`, phase A.
//!
//! Three paths, tried in order, decided by the pixels and never by what the
//! uploader claims:
//!
//! 1. **aligned** -- the image still sits on the photosite lattice, so it is
//!    scored plane by plane ([`crate::score`]). Stronger and cheaper.
//! 2. **portrait** -- a portrait capture has been turned; the sensor is
//!    landscape. Both quarter turns are tried, and one is kept only if it
//!    clears the threshold.
//! 3. **scale search** -- resized: no lattice left. A flat added border is
//!    stripped first, then orientation and scale are searched.
//!
//! Works on canonical RGB8 rather than file bytes, so JPEG pixels come from
//! libjpeg-turbo and match Pillow's (`crate::hashing` explains why).

use std::collections::BTreeMap;

use ndarray::{s, Array2, ArrayView2};

use crate::correlation::{pce, score};
use crate::hashing::grey_l8;
use crate::image_decode::planes_from_rgb;
use crate::noise::noise_residual;
use crate::resample::resize_f32_box;

/// `prnu.py`'s `PCE_THRESHOLD`.
pub const PCE_THRESHOLD: f64 = 100.0;

/// A decoded image: canonical RGB8, row-major.
#[derive(Clone, Debug, PartialEq)]
pub struct Rgb {
    pub data: Vec<u8>,
    pub width: usize,
    pub height: usize,
}

impl Rgb {
    pub fn new(data: Vec<u8>, width: usize, height: usize) -> Self {
        assert_eq!(
            data.len(),
            width * height * 3,
            "rgb buffer does not match its dimensions"
        );
        Rgb {
            data,
            width,
            height,
        }
    }

    fn pixel(&self, x: usize, y: usize) -> [u8; 3] {
        let i = (y * self.width + x) * 3;
        [self.data[i], self.data[i + 1], self.data[i + 2]]
    }

    fn from_fn(width: usize, height: usize, f: impl Fn(usize, usize) -> [u8; 3]) -> Self {
        let mut data = Vec::with_capacity(width * height * 3);
        for y in 0..height {
            for x in 0..width {
                data.extend_from_slice(&f(x, y));
            }
        }
        Rgb {
            data,
            width,
            height,
        }
    }

    /// Pillow `rotate(angle, expand=True)` for `angle` 90 or 270, which Pillow
    /// does as an exact transpose. Angles are anticlockwise.
    pub fn rotate(&self, angle: u32) -> Self {
        let (w, h) = (self.width, self.height);
        match angle {
            90 => Rgb::from_fn(h, w, |x, y| self.pixel(w - 1 - y, x)),
            270 => Rgb::from_fn(h, w, |x, y| self.pixel(y, h - 1 - x)),
            _ => panic!("only quarter turns are exact"),
        }
    }

    /// `image.crop((left, top, right, bottom))`.
    pub fn crop(&self, left: usize, top: usize, right: usize, bottom: usize) -> Self {
        Rgb::from_fn(right - left, bottom - top, |x, y| {
            self.pixel(left + x, top + y)
        })
    }
}

/// `stress.green_channel`: the green channel in `[0, 1]`, float32.
pub fn green_channel(image: &Rgb) -> Array2<f32> {
    Array2::from_shape_fn((image.height, image.width), |(y, x)| {
        image.data[(y * image.width + x) * 3 + 1] as f32 / 255.0
    })
}

/// `prnu.sensor_field`: mean of the green planes (1 and 3), or of every plane
/// if there are no greens. A resized photo has no lattice left, so the
/// per-plane fingerprints are collapsed before comparing.
pub fn sensor_field(planes: &BTreeMap<i32, Array2<f32>>) -> Array2<f32> {
    let mut chosen: Vec<&Array2<f32>> = [1, 3].iter().filter_map(|c| planes.get(c)).collect();
    if chosen.is_empty() {
        chosen = planes.values().collect();
    }
    let mut sum = chosen[0].clone();
    for p in &chosen[1..] {
        sum += *p;
    }
    sum / chosen.len() as f32
}

/// `stress.strip_uniform_border`: the crop box `(left, top, right, bottom)`
/// that removes a flat added margin, or `None` to leave the image alone.
///
/// A line counts as border only if its greyscale std is at most `tolerance`
/// levels; at most `max_fraction` of each side goes; and all four sides must
/// agree, so a blown sky alone is scene, not frame.
pub fn strip_uniform_border(
    image: &Rgb,
    tolerance: f64,
    max_fraction: f64,
) -> Option<(usize, usize, usize, usize)> {
    let (w, h) = (image.width, image.height);
    let grey = grey_l8(&image.data);
    let limit_v = (h as f64 * max_fraction) as usize;
    let limit_h = (w as f64 * max_fraction) as usize;

    let flat = |values: &mut dyn Iterator<Item = u8>, n: usize| -> bool {
        let v: Vec<f64> = values.map(f64::from).collect();
        let mean = v.iter().sum::<f64>() / n as f64;
        let var = v.iter().map(|x| (x - mean) * (x - mean)).sum::<f64>() / n as f64;
        var.sqrt() <= tolerance
    };
    let row = |y: usize| flat(&mut grey[y * w..(y + 1) * w].iter().copied(), w);
    let col = |x: usize| flat(&mut (0..h).map(|y| grey[y * w + x]), h);
    let run = |limit: usize, is_flat: &dyn Fn(usize) -> bool| {
        (0..limit).take_while(|&i| is_flat(i)).count()
    };

    let top = run(limit_v, &|i| row(i));
    let bottom = run(limit_v, &|i| row(h - 1 - i));
    let left = run(limit_h, &|i| col(i));
    let right = run(limit_h, &|i| col(w - 1 - i));

    if top.min(bottom).min(left).min(right) == 0 {
        return None;
    }
    let (right_edge, bottom_edge) = (w - right, h - bottom);
    if right_edge - left < w / 2 || bottom_edge - top < h / 2 {
        return None;
    }
    Some((left, top, right_edge, bottom_edge))
}

/// `prnu.ScaleMatch`.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct ScaleMatch {
    pub pce: f64,
    pub scale: f64,
    /// Quarter turns anticlockwise applied to the candidate.
    pub rotation: u32,
    /// Whether the candidate was flipped left-right.
    pub mirrored: bool,
}

impl ScaleMatch {
    /// How the candidate sits relative to the sensor, in words.
    pub fn orientation(&self) -> String {
        let turn = format!("{} deg", self.rotation * 90);
        if self.mirrored {
            format!("mirrored, {turn}")
        } else {
            turn
        }
    }
}

/// `numpy.linspace(0.94, 1.06, 13)`, computed the way numpy does it.
fn default_scales() -> Vec<f64> {
    let (start, stop, num) = (0.94f64, 1.06f64, 13usize);
    let step = (stop - start) / (num - 1) as f64;
    let mut scales: Vec<f64> = (0..num).map(|i| i as f64 * step + start).collect();
    scales[num - 1] = stop;
    scales
}

/// `np.rot90(np.fliplr(a) if flip else a, turns)`, as a contiguous array.
fn orient(a: &Array2<f32>, turns: u32, flip: bool) -> Array2<f32> {
    let mut v: ArrayView2<f32> = a.view();
    if flip {
        v = v.slice_move(s![.., ..;-1]);
    }
    for _ in 0..turns % 4 {
        // rot90 once: flip left-right, then transpose.
        v = v.slice_move(s![.., ..;-1]).reversed_axes();
    }
    v.as_standard_layout().into_owned()
}

/// `prnu.crop_and_scale_search`, non-exhaustive (its default): settle the
/// orientation at nominal scale across all eight, then scan the 13 scales
/// with the winner. `progress(done, total, label)` is called before each of
/// the 21 correlations.
pub fn crop_and_scale_search(
    residual: &Array2<f32>,
    reference: &Array2<f32>,
    progress: &mut dyn FnMut(usize, usize, &str),
) -> ScaleMatch {
    search_traced(residual, reference, progress).0
}

/// [`crop_and_scale_search`], also returning every attempt in the order
/// tried, so parity can be checked on the losers and not only the winner.
fn search_traced(
    residual: &Array2<f32>,
    reference: &Array2<f32>,
    progress: &mut dyn FnMut(usize, usize, &str),
) -> (ScaleMatch, Vec<ScaleMatch>) {
    let mut tried = Vec::new();
    let scales = default_scales();
    let orientations: Vec<(u32, bool)> = [false, true]
        .iter()
        .flat_map(|&flip| (0..4).map(move |t| (t, flip)))
        .collect();
    let total = orientations.len() + scales.len();
    let mut done = 0;

    let mut attempt = |turns: u32, flip: bool, f: f64| -> ScaleMatch {
        let side = if flip { "mirrored " } else { "" };
        progress(
            done,
            total,
            &format!("{side}rot {} scale {f:.3}", turns * 90),
        );
        done += 1;
        let candidate = orient(residual, turns, flip);
        let (height, width) = candidate.dim();
        // Python's int(round(x)) rounds half to even.
        let resized = resize_f32_box(
            reference,
            (width as f64 * f).round_ties_even() as usize,
            (height as f64 * f).round_ties_even() as usize,
        );
        let h = resized.nrows().min(height);
        let w = resized.ncols().min(width);
        let a = candidate.slice(s![..h, ..w]).mapv(f64::from);
        let b = resized.slice(s![..h, ..w]).mapv(f64::from);
        let found = ScaleMatch {
            pce: pce(&a, &b, 11),
            scale: f,
            rotation: turns,
            mirrored: flip,
        };
        tried.push(found);
        found
    };

    // Python's max() keeps the first of equal values, hence strictly greater.
    let best = |a: ScaleMatch, b: ScaleMatch| if b.pce.abs() > a.pce.abs() { b } else { a };

    let mut settled: Option<ScaleMatch> = None;
    for &(t, m) in &orientations {
        let r = attempt(t, m, 1.0);
        settled = Some(settled.map_or(r, |s| best(s, r)));
    }
    let settled = settled.unwrap();

    let mut winner: Option<ScaleMatch> = None;
    for &f in &scales {
        let r = attempt(settled.rotation, settled.mirrored, f);
        winner = Some(winner.map_or(r, |s| best(s, r)));
    }
    (winner.unwrap(), tried)
}

/// What [`score_against`] found, mirroring the dict `_score_against` returns.
#[derive(Clone, Debug, PartialEq)]
pub struct ScoreResult {
    pub pce: f64,
    /// `"aligned"` or `"scale search"`.
    pub path: &'static str,
    pub orientation: String,
    /// Set on the scale-search path.
    pub scale: Option<f64>,
    /// `"{w}x{h} to {w'}x{h'}"` when a border was stripped before the search.
    pub border_stripped: Option<String>,
    /// Set when a portrait capture was turned back into sensor space.
    pub turned: Option<&'static str>,
    /// Every PCE the scale search tried, in order; empty on the aligned path.
    pub attempts: Vec<f64>,
}

/// Score `planes` (probe) against `reference` (K) on the aligned path, if the
/// two share a lattice: every CFA plane they have in common must match in
/// shape, and there must be at least one.
fn aligned(
    planes: &BTreeMap<i32, Array2<f32>>,
    reference: &BTreeMap<i32, Array2<f32>>,
) -> Option<f64> {
    let shared: Vec<&i32> = reference
        .keys()
        .filter(|c| planes.contains_key(c))
        .collect();
    if shared.is_empty() || shared.iter().any(|c| planes[c].dim() != reference[c].dim()) {
        return None;
    }
    Some(score(planes, reference, true))
}

/// `scoring/app.py::_score_against` for a delivered (non-RAW) image.
///
/// `pattern` is the K file's `meta["cfa_pattern"]`. `step` receives the same
/// progress labels the Python reported, so the desktop's progress display
/// keeps its wording.
pub fn score_against(
    image: &Rgb,
    reference: &BTreeMap<i32, Array2<f32>>,
    pattern: [[i32; 2]; 2],
    step: &mut dyn FnMut(&str),
) -> ScoreResult {
    step("reading the file");
    let probe = planes_from_rgb(&image.data, image.width, image.height, pattern, None);
    if let Some(value) = aligned(&probe, reference) {
        step("correlating on the photosite lattice");
        return ScoreResult {
            pce: value,
            path: "aligned",
            orientation: "0 deg".into(),
            scale: None,
            border_stripped: None,
            turned: None,
            attempts: Vec::new(),
        };
    }

    // A portrait capture: the sensor is landscape and a developed JPEG has
    // been turned. Only one direction is right, and the pixels don't say
    // which, so both are tried -- and only after the aligned path failed.
    if image.height > image.width {
        step("portrait capture — turning it back into sensor space");
        let mut best: Option<(f64, u32)> = None;
        for angle in [270, 90] {
            let turned = image.rotate(angle);
            let probe = planes_from_rgb(&turned.data, turned.width, turned.height, pattern, None);
            if let Some(value) = aligned(&probe, reference) {
                if best.is_none_or(|(b, _)| value > b) {
                    best = Some((value, angle));
                }
            }
        }
        if let Some((value, angle)) = best.filter(|(v, _)| *v >= PCE_THRESHOLD) {
            return ScoreResult {
                pce: value,
                path: "aligned",
                orientation: format!("{angle} deg"),
                scale: None,
                border_stripped: None,
                turned: Some("portrait capture, rotated back into sensor space"),
                attempts: Vec::new(),
            };
        }
    }

    // A flat margin defeats the search, not the fingerprint: padding changes
    // the aspect ratio, so no uniform scale maps it back. Strip it first.
    let (image, border_stripped) = match strip_uniform_border(image, 2.0, 0.25) {
        Some((l, t, r, b)) => {
            let cropped = image.crop(l, t, r, b);
            let note = format!(
                "{}x{} to {}x{}",
                image.width, image.height, cropped.width, cropped.height
            );
            (cropped, Some(note))
        }
        None => (image.clone(), None),
    };

    step("extracting the noise residual");
    let residual = noise_residual(&green_channel(&image));
    let (found, tried) = search_traced(
        &residual,
        &sensor_field(reference),
        &mut |done, total, label| {
            step(&format!(
                "searching scale and orientation — {} of {total} ({label})",
                done + 1
            ))
        },
    );
    ScoreResult {
        pce: found.pce,
        path: "scale search",
        orientation: found.orientation(),
        scale: Some(found.scale),
        border_stripped,
        turned: None,
        attempts: tried.iter().map(|m| m.pce).collect(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_scales_match_numpy() {
        let s = default_scales();
        assert_eq!(s.len(), 13);
        assert_eq!(s[0], 0.94);
        assert_eq!(s[12], 1.06);
        assert!((s[6] - 1.0).abs() < 1e-12);
    }

    #[test]
    fn orient_matches_numpy_rot90_and_fliplr() {
        // [[1, 2, 3], [4, 5, 6]]
        let a = Array2::from_shape_vec((2, 3), vec![1.0f32, 2., 3., 4., 5., 6.]).unwrap();
        // np.rot90(a) == [[3, 6], [2, 5], [1, 4]]
        assert_eq!(
            orient(&a, 1, false).into_raw_vec_and_offset().0,
            vec![3., 6., 2., 5., 1., 4.]
        );
        // np.rot90(a, 2) == [[6, 5, 4], [3, 2, 1]]
        assert_eq!(
            orient(&a, 2, false).into_raw_vec_and_offset().0,
            vec![6., 5., 4., 3., 2., 1.]
        );
        // np.rot90(a, 3) == [[4, 1], [5, 2], [6, 3]]
        assert_eq!(
            orient(&a, 3, false).into_raw_vec_and_offset().0,
            vec![4., 1., 5., 2., 6., 3.]
        );
        // np.fliplr(a) == [[3, 2, 1], [6, 5, 4]]
        assert_eq!(
            orient(&a, 0, true).into_raw_vec_and_offset().0,
            vec![3., 2., 1., 6., 5., 4.]
        );
    }

    #[test]
    fn rotate_matches_pillow_transpose() {
        // 2 wide, 1 tall: pixels A then B.
        let a = Rgb::new(vec![1, 1, 1, 2, 2, 2], 2, 1);
        // ROTATE_90 (anticlockwise): B on top of A.
        assert_eq!(a.rotate(90).data, vec![2, 2, 2, 1, 1, 1]);
        // ROTATE_270 (clockwise): A on top of B.
        assert_eq!(a.rotate(270).data, vec![1, 1, 1, 2, 2, 2]);
        assert_eq!((a.rotate(90).width, a.rotate(90).height), (1, 2));
    }
}

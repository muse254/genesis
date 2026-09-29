//! Read-only `.npz` K-file reader, matching `fingerprint/prnu.py::save_fingerprint`'s
//! layout. See `docs/wasm-scoring-plan.md` Phase 4.
//!
//! Enrolment (`save_fingerprint`) stays Python-only -- this only *reads*
//! what it wrote: one `plane_<c>.npy` (float32) per CFA colour, a
//! `meta.npy` (a 0-d numpy array wrapping a JSON string), and a
//! `commitment.npy` (raw SHA-256 bytes as uint8). `ndarray-npy`'s `NpzReader`
//! (feature `npz`/`compressed_npz`, already a dependency) handles the zip
//! container and the numeric arrays directly; `meta.npy` needs a small
//! hand-rolled parser below because numpy's 0-d fixed-width-unicode dtype
//! (`<U<n>`, UCS-4 code units) isn't a type `ndarray-npy` reads.

use std::collections::BTreeMap;
use std::io::{Cursor, Read};

use ndarray::{Array2, Ix2, OwnedRepr};
use ndarray_npy::NpzReader;

/// A loaded K file: CFA-plane fingerprints, enrolment metadata (parsed
/// JSON), and the raw commitment bytes.
pub struct Fingerprint {
    pub planes: BTreeMap<i32, Array2<f32>>,
    pub meta: serde_json::Value,
    pub commitment: Vec<u8>,
}

#[derive(Debug)]
pub enum KFileError {
    Zip(String),
    Npy(String),
    Json(String),
    MissingPlanes,
    MissingMeta,
}

impl std::fmt::Display for KFileError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            KFileError::Zip(e) => write!(f, "npz/zip error: {e}"),
            KFileError::Npy(e) => write!(f, "npy parse error: {e}"),
            KFileError::Json(e) => write!(f, "meta JSON error: {e}"),
            KFileError::MissingPlanes => write!(f, "no plane_<c> arrays found in .npz"),
            KFileError::MissingMeta => write!(f, "no meta.npy found in .npz"),
        }
    }
}
impl std::error::Error for KFileError {}

/// Load a fingerprint `.npz` from raw bytes (as read from disk or handed in
/// from JS as a `Uint8Array` in the WASM build -- this function never
/// touches the filesystem or the network itself).
pub fn load_fingerprint(bytes: &[u8]) -> Result<Fingerprint, KFileError> {
    let cursor = Cursor::new(bytes);
    let mut npz = NpzReader::new(cursor).map_err(|e| KFileError::Zip(format!("{e:?}")))?;
    let names = npz.names().map_err(|e| KFileError::Zip(format!("{e:?}")))?;

    let mut planes = BTreeMap::new();
    let mut meta_bytes: Option<Vec<u8>> = None;
    let mut commitment: Vec<u8> = Vec::new();

    for name in &names {
        if let Some(rest) = name.strip_prefix("plane_") {
            let rest = rest.strip_suffix(".npy").unwrap_or(rest);
            let c: i32 = rest
                .parse()
                .map_err(|_| KFileError::Npy(format!("bad plane key {name}")))?;
            let arr: ndarray::ArrayBase<OwnedRepr<f32>, Ix2> = npz
                .by_name(name)
                .map_err(|e| KFileError::Npy(format!("{name}: {e:?}")))?;
            planes.insert(c, arr);
        } else if name == "meta.npy" || name == "meta" {
            // Extract the raw member bytes ourselves -- ndarray-npy has no
            // unicode-dtype reader.
            meta_bytes = Some(read_raw_member(bytes, name).map_err(KFileError::Npy)?);
        } else if name == "commitment.npy" || name == "commitment" {
            let arr: ndarray::ArrayBase<OwnedRepr<u8>, ndarray::Ix1> = npz
                .by_name(name)
                .map_err(|e| KFileError::Npy(format!("{name}: {e:?}")))?;
            commitment = arr.to_vec();
        }
    }

    if planes.is_empty() {
        return Err(KFileError::MissingPlanes);
    }
    let meta_bytes = meta_bytes.ok_or(KFileError::MissingMeta)?;
    let meta_str = parse_npy_unicode_scalar(&meta_bytes).map_err(KFileError::Npy)?;
    let meta: serde_json::Value =
        serde_json::from_str(&meta_str).map_err(|e| KFileError::Json(e.to_string()))?;

    Ok(Fingerprint {
        planes,
        meta,
        commitment,
    })
}

/// Load bare CFA planes from an `.npz` holding `plane_<c>` float32 arrays and
/// nothing else required -- what the desktop's RAW decoder sends
/// (`console/app.py` `/raw/decode`), since LibRaw has no WASM build.
pub fn load_planes(bytes: &[u8]) -> Result<BTreeMap<i32, Array2<f32>>, KFileError> {
    let mut npz =
        NpzReader::new(Cursor::new(bytes)).map_err(|e| KFileError::Zip(format!("{e:?}")))?;
    let names = npz.names().map_err(|e| KFileError::Zip(format!("{e:?}")))?;
    let mut planes = BTreeMap::new();
    for name in &names {
        if let Some(rest) = name.strip_prefix("plane_") {
            let rest = rest.strip_suffix(".npy").unwrap_or(rest);
            let c: i32 = rest
                .parse()
                .map_err(|_| KFileError::Npy(format!("bad plane key {name}")))?;
            let arr: Array2<f32> = npz
                .by_name(name)
                .map_err(|e| KFileError::Npy(format!("{name}: {e:?}")))?;
            planes.insert(c, arr);
        }
    }
    if planes.is_empty() {
        return Err(KFileError::MissingPlanes);
    }
    Ok(planes)
}

/// The CFA pattern (`meta["cfa_pattern"]`, a 2x2 list of CFA colour
/// indices) out of a loaded fingerprint's metadata, matching how
/// `fingerprint/fingerprint.py`/`console/app.py` store it at enrolment
/// (`meta = {"cfa_pattern": prnu.cfa_pattern(...), ...}`).
pub fn cfa_pattern(meta: &serde_json::Value) -> Result<[[i32; 2]; 2], KFileError> {
    let p = meta
        .get("cfa_pattern")
        .ok_or_else(|| KFileError::Json("meta has no cfa_pattern".into()))?;
    let rows = p
        .as_array()
        .ok_or_else(|| KFileError::Json("cfa_pattern not an array".into()))?;
    if rows.len() != 2 {
        return Err(KFileError::Json("cfa_pattern is not 2x2".into()));
    }
    let mut out = [[0i32; 2]; 2];
    for (i, row) in rows.iter().enumerate() {
        let cols = row
            .as_array()
            .ok_or_else(|| KFileError::Json("cfa_pattern row not an array".into()))?;
        if cols.len() != 2 {
            return Err(KFileError::Json("cfa_pattern is not 2x2".into()));
        }
        for (j, v) in cols.iter().enumerate() {
            out[i][j] = v
                .as_i64()
                .ok_or_else(|| KFileError::Json("cfa_pattern entry not an int".into()))?
                as i32;
        }
    }
    Ok(out)
}

/// Re-open the zip container ourselves to pull one member's raw file bytes
/// (post-decompression), independent of `ndarray-npy`'s typed readers.
fn read_raw_member(zip_bytes: &[u8], name: &str) -> Result<Vec<u8>, String> {
    let cursor = Cursor::new(zip_bytes);
    let mut archive = zip::ZipArchive::new(cursor).map_err(|e| e.to_string())?;
    // `npz.names()` already stripped a trailing ".npy" (matching NumPy's own
    // behaviour), but the raw zip entries still have it -- try both, same
    // fallback order as `NpzReader::by_name`.
    let has_bare = archive.by_name(name).is_ok();
    let mut file = if has_bare {
        archive.by_name(name).map_err(|e| format!("{name}: {e}"))?
    } else {
        archive
            .by_name(&format!("{name}.npy"))
            .map_err(|e| format!("{name}: {e}"))?
    };
    let mut buf = Vec::with_capacity(file.size() as usize);
    file.read_to_end(&mut buf).map_err(|e| e.to_string())?;
    Ok(buf)
}

/// Parse a `.npy` file wrapping a 0-d fixed-width-unicode scalar
/// (`np.array(some_str)`'s on-disk format): magic + version + header
/// (an ASCII Python-literal dict naming `descr`/`shape`/`fortran_order`),
/// then the raw data as UCS-4 code units (4 bytes each), little- or
/// big-endian per `descr`, null-padded to the fixed width.
fn parse_npy_unicode_scalar(bytes: &[u8]) -> Result<String, String> {
    if bytes.len() < 10 || &bytes[0..6] != b"\x93NUMPY" {
        return Err("not an .npy file (bad magic)".into());
    }
    let major = bytes[6];
    let (header_len, header_start): (usize, usize) = if major == 1 {
        let len = u16::from_le_bytes([bytes[8], bytes[9]]) as usize;
        (len, 10)
    } else {
        let len = u32::from_le_bytes([bytes[8], bytes[9], bytes[10], bytes[11]]) as usize;
        (len, 12)
    };
    let header_end = header_start + header_len;
    let header = std::str::from_utf8(&bytes[header_start..header_end])
        .map_err(|e| format!("header not utf8: {e}"))?;

    let descr_key = "'descr':";
    let descr_pos = header.find(descr_key).ok_or("no 'descr' in npy header")?;
    let after = &header[descr_pos + descr_key.len()..];
    let q1 = after.find('\'').ok_or("malformed descr")?;
    let rest = &after[q1 + 1..];
    let q2 = rest.find('\'').ok_or("malformed descr")?;
    let descr = &rest[..q2]; // e.g. "<U55" or ">U55"

    if descr.len() < 3 || (descr.as_bytes()[1] != b'U') {
        return Err(format!(
            "unsupported meta dtype {descr}, expected unicode <U*/>U*"
        ));
    }
    let big_endian = descr.as_bytes()[0] == b'>';
    let n_chars: usize = descr[2..]
        .parse()
        .map_err(|_| format!("bad unicode width in {descr}"))?;

    let data = &bytes[header_end..];
    let needed = n_chars * 4;
    if data.len() < needed {
        return Err(format!(
            "meta.npy data too short: {} < {needed}",
            data.len()
        ));
    }

    let mut s = String::with_capacity(n_chars);
    for i in 0..n_chars {
        let off = i * 4;
        let code = if big_endian {
            u32::from_be_bytes([data[off], data[off + 1], data[off + 2], data[off + 3]])
        } else {
            u32::from_le_bytes([data[off], data[off + 1], data[off + 2], data[off + 3]])
        };
        if code == 0 {
            continue; // null padding to the fixed width
        }
        if let Some(c) = char::from_u32(code) {
            s.push(c);
        }
    }
    Ok(s)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_a_real_numpy_unicode_scalar_npy() {
        // Built by: np.save(f, np.array('{"a": 1}'))
        // Header + UCS4 data laid out exactly as numpy's format module does.
        let json = r#"{"a": 1}"#;
        let mut npy = Vec::new();
        npy.extend_from_slice(b"\x93NUMPY");
        npy.push(1); // major
        npy.push(0); // minor
        let descr = format!("<U{}", json.chars().count());
        let mut header = format!("{{'descr': '{descr}', 'fortran_order': False, 'shape': (), }}");
        // pad so total length (10 + header.len() + 1 for '\n') % 64 == 0
        let base = 10 + header.len() + 1;
        let pad = (64 - base % 64) % 64;
        header.push_str(&" ".repeat(pad));
        header.push('\n');
        npy.extend_from_slice(&(header.len() as u16).to_le_bytes());
        npy.extend_from_slice(header.as_bytes());
        for c in json.chars() {
            npy.extend_from_slice(&(c as u32).to_le_bytes());
        }

        let got = parse_npy_unicode_scalar(&npy).unwrap();
        assert_eq!(got, json);
    }
}

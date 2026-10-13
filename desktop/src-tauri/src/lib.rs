//! The desktop shell around the Genesis console.
//!
//! The Python imaging core runs in this process via PyO3, serving the same
//! FastAPI app over loopback, so the frontend needs no change. RAW and K stay
//! on this machine (`docs/security.md`, "Where K lives"). Dev uses
//! `desktop/.venv312`; release bundles a relocatable CPython
//! (`desktop/scripts/bundle-python.sh`). See `desktop/PACKAGING.md`.

use std::path::PathBuf;
use std::thread;

use pyo3::prelude::*;
use pyo3::types::PyDict;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// A free loopback port: a fixed one could collide with a second console and
/// the app would silently talk to the wrong backend.
fn free_port() -> std::io::Result<u16> {
  Ok(std::net::TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

/// Origins the console API must accept requests from: the bundled webview on
/// macOS/Linux, on Windows, and the Vite dev server.
const WEBVIEW_ORIGINS: &str =
  "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://127.0.0.1:5173,http://localhost:5173";

/// Bundled resources, computed by hand because this runs before the
/// interpreter (and so before any `AppHandle`) exists. macOS: `Contents/Resources`;
/// elsewhere: `resources/` beside the executable.
#[cfg(not(debug_assertions))]
fn resources_dir() -> Result<PathBuf, Box<dyn std::error::Error>> {
  let exe = std::env::current_exe()?;
  #[cfg(target_os = "macos")]
  {
    Ok(exe
      .parent() // Contents/MacOS
      .and_then(|p| p.parent()) // Contents
      .ok_or("executable path too shallow")?
      .join("Resources"))
  }
  #[cfg(not(target_os = "macos"))]
  {
    Ok(exe.parent().ok_or("executable has no parent directory")?.join("resources"))
  }
}

/// `sys.path` for the embedded interpreter. Dev uses `desktop/.venv312` so
/// Python edits need no rebuild. Release uses the bundled copy of our source,
/// never the repo's packages, which hold RAW fixtures (`docs/security.md`).
#[cfg(debug_assertions)]
fn python_search_paths() -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
  let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize()?;
  let venv_site_packages = root.join("desktop/.venv312/lib/python3.12/site-packages");
  if !venv_site_packages.is_dir() {
    return Err(format!(
      "{} not found -- run: uv venv desktop/.venv312 --python 3.12 && \
       uv pip install --python desktop/.venv312/bin/python -r requirements.txt",
      venv_site_packages.display()
    )
    .into());
  }
  Ok(vec![root.join("desktop/sidecar"), venv_site_packages, root])
}

#[cfg(not(debug_assertions))]
fn python_search_paths() -> Result<Vec<PathBuf>, Box<dyn std::error::Error>> {
  let runtime = resources_dir()?.join("python-runtime");
  // python-build-standalone's Windows layout puts `Lib\site-packages` at the root.
  #[cfg(target_os = "windows")]
  let site_packages = runtime.join("Lib/site-packages");
  #[cfg(not(target_os = "windows"))]
  let site_packages = runtime.join("lib/python3.12/site-packages");
  Ok(vec![resources_dir()?.join("app-src"), site_packages])
}

/// Must run before `prepare_freethreaded_python()`: Python reads `PYTHONHOME`
/// only at init, and without it libpython fails to boot with no useful error.
#[cfg(not(debug_assertions))]
fn set_pythonhome() -> Result<(), Box<dyn std::error::Error>> {
  std::env::set_var("PYTHONHOME", resources_dir()?.join("python-runtime"));
  // The bundle should not be writable, and on iCloud-synced folders a .pyc
  // rename() was measured to hang interpreter startup.
  std::env::set_var("PYTHONDONTWRITEBYTECODE", "1");
  Ok(())
}

/// Runs `console.app` on a dedicated thread that lives as long as the process.
fn start_backend(app: &tauri::AppHandle, port: u16) -> Result<(), Box<dyn std::error::Error>> {
  let data = app.path().app_data_dir()?;
  let references = data.join("references");
  std::fs::create_dir_all(&references)?;
  let catalogue = data.join("catalogue.db");

  let search_paths = python_search_paths()?;

  thread::Builder::new()
    .name("genesis-backend".into())
    .spawn(move || {
      let result = Python::with_gil(|py| -> PyResult<()> {
        // `os.environ` was snapshotted when the interpreter started, so
        // `std::env::set_var` here is too late; write through `os.environ`.
        let environ = py.import("os")?.getattr("environ")?;
        environ.set_item("GENESIS_REFERENCES", references.to_string_lossy().into_owned())?;
        environ.set_item("GENESIS_CATALOGUE", catalogue.to_string_lossy().into_owned())?;
        environ.set_item("GENESIS_CONSOLE_ORIGINS", WEBVIEW_ORIGINS)?;
        // Without these, console/chain.py falls back to Sepolia with no registry,
        // so every camera reads "not registered". setdefault: a dev's env still wins.
        environ.call_method1("setdefault", ("GENESIS_CHAIN", "base"))?;
        environ.call_method1("setdefault", ("REGISTRY_ADDRESS", "0xBa5Ea549c9e1414C14038dB050e0caCB4f9E48cB"))?;
        environ.call_method1("setdefault", ("GENESIS_SUBGRAPH_URL", "https://api.studio.thegraph.com/query/1758974/genesis/v1.0.0-base"))?;

        let sys = py.import("sys")?;
        let sys_path = sys.getattr("path")?;
        for entry in search_paths.iter().rev() {
          sys_path.call_method1("insert", (0, entry.to_string_lossy().into_owned()))?;
        }

        let console_app = py.import("console.app")?;
        let app_object = console_app.getattr("app")?;

        // embedded_runner no-ops uvicorn's signal handlers; see its docstring.
        let runner = py.import("embedded_runner")?;
        let kwargs = PyDict::new(py);
        runner.call_method("run", (app_object, "127.0.0.1", port), Some(&kwargs))?;
        Ok(())
      });
      if let Err(error) = result {
        Python::with_gil(|py| error.print(py));
      }
    })?;

  Ok(())
}

/// Score a delivered (JPEG/PNG/TIFF) image against a K file natively, via
/// `genesis_prnu::score()`. Unused: verification runs in the webview on the
/// same WASM as the web page, which measured no slower. RAW probes, the
/// crop/scale search and enrolment stay Python-only.
///
/// K and image bytes are never written to disk or sent anywhere
/// (`docs/security.md`, "Where K lives").
#[tauri::command]
fn score_delivered_image(image_bytes: Vec<u8>, k_npz_bytes: Vec<u8>) -> Result<f64, String> {
  let fp = genesis_prnu::kfile::load_fingerprint(&k_npz_bytes).map_err(|e| e.to_string())?;
  let pattern = genesis_prnu::kfile::cfa_pattern(&fp.meta).map_err(|e| e.to_string())?;
  let planes = genesis_prnu::image_decode::load_delivered_planes(&image_bytes, pattern, None)
    .map_err(|e| e.to_string())?;
  Ok(genesis_prnu::score(&planes, &fp.planes, true))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  // PYTHONHOME must be set before the interpreter initializes, just below.
  #[cfg(not(debug_assertions))]
  set_pythonhome().expect("could not locate the bundled Python runtime");
  pyo3::prepare_freethreaded_python();

  tauri::Builder::default()
    .invoke_handler(tauri::generate_handler![score_delivered_image])
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      let port = free_port()?;
      start_backend(app.handle(), port)?;

      // The window is built here rather than in tauri.conf.json so the page
      // learns the backend's port before any of its scripts run.
      WebviewWindowBuilder::new(app, "main", WebviewUrl::default())
        .title("Genesis")
        .inner_size(1280.0, 820.0)
        .min_inner_size(960.0, 640.0)
        .initialization_script(format!(
          "window.__GENESIS_CONSOLE__ = 'http://127.0.0.1:{port}';"
        ))
        .build()?;
      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("error while building the Genesis app")
    .run(|_app, _event| {});
}

#[cfg(test)]
mod score_delivered_image_tests {
    //! Checks this crate's plumbing reproduces the core crate's e2e fixture
    //! score; numeric parity with Python is tested in genesis-prnu itself.

    use super::score_delivered_image;
    use std::fs;
    use std::path::Path;

    #[test]
    fn matches_the_core_crates_own_e2e_fixture() {
        let fixtures =
            Path::new(env!("CARGO_MANIFEST_DIR")).join("../../rust/genesis-prnu/tests/fixtures");

        let manifest_text = fs::read_to_string(fixtures.join("manifest.json"))
            .expect("manifest.json should read");
        let manifest: serde_json::Value =
            serde_json::from_str(&manifest_text).expect("manifest.json should be valid JSON");
        let expected = manifest["e2e_case"]["score"]
            .as_f64()
            .expect("e2e_case.score should be a number");

        let k_bytes = fs::read(fixtures.join("e2e_fingerprint.npz")).expect("k fixture should read");
        let image_bytes =
            fs::read(fixtures.join("e2e_delivered.png")).expect("image fixture should read");

        let got = score_delivered_image(image_bytes, k_bytes)
            .expect("scoring the fixture pair should succeed");

        let rel = (got - expected).abs() / expected.abs().max(1.0);
        assert!(rel < 0.02, "score = {got}, expected = {expected}, rel err {rel}");
    }
}

//! The desktop shell around the Genesis console.
//!
//! The imaging core is Python (`fingerprint/`, `ingest/`, `console/`), and it
//! now runs **inside this process**: an embedded interpreter (PyO3), on a
//! worker thread, serving the same FastAPI app the browser console always
//! has, over loopback -- so the frontend's `fetch()` calls need no change.
//! There is no second process, no subprocess to spawn or race against, and
//! nothing to kill on exit -- when this process ends, so does the
//! interpreter it holds. Everything that touches the RAW archive or K stays
//! on this machine either way (`docs/security.md`, "Where K lives").
//!
//! This supersedes the sidecar approach (`desktop/sidecar/genesis_console.py`,
//! `desktop/scripts/build-sidecar.sh`), kept for reference and because
//! nothing here was asked to delete them. The one piece still used from that
//! world is the pattern of a single loopback HTTP server; what changed is
//! who runs the interpreter that hosts it.
//!
//! **Packaging.** PyO3 embeds the *interpreter* by linking `libpython3.12`;
//! it does not by itself bundle a Python installation or third-party
//! packages -- those still have to physically exist on disk somewhere the
//! interpreter can find them. Dev points at a real environment already on
//! disk (`desktop/.venv312`). Release points at a relocatable CPython
//! (python-build-standalone, fetched and populated by
//! `desktop/scripts/bundle-python.sh`) bundled as a Tauri resource, so the
//! shipped app needs no Python installed on the machine it runs on at all.
//! See `desktop/PACKAGING.md`.

use std::path::PathBuf;
use std::thread;

use pyo3::prelude::*;
use pyo3::types::PyDict;
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};

/// A free loopback port for the console API, chosen at launch. A fixed port
/// collides with anything else a photographer runs, including a second copy
/// of the console, and the app would silently talk to the wrong backend.
fn free_port() -> std::io::Result<u16> {
  Ok(std::net::TcpListener::bind("127.0.0.1:0")?.local_addr()?.port())
}

/// Origins the console API must accept requests from: the bundled webview on
/// macOS/Linux, on Windows, and the Vite dev server.
const WEBVIEW_ORIGINS: &str =
  "tauri://localhost,http://tauri.localhost,https://tauri.localhost,http://127.0.0.1:5173,http://localhost:5173";

/// Where the bundled resources live, relative to the running executable --
/// computed by hand rather than through `tauri::Manager::path()`, because
/// this has to run **before** the interpreter initializes (see `run()`),
/// which is before there is an `App`/`AppHandle` to ask.
///
/// macOS bundle layout: `Genesis.app/Contents/MacOS/genesis` is the
/// executable, `Genesis.app/Contents/Resources/` is where `tauri.conf.json`'s
/// `bundle.resources` lands. Windows and Linux bundles place resources
/// beside the executable instead, which `resource_dir()`-the-method also
/// has to special-case -- ours does not need to, since it only has to agree
/// with itself, consistently, before and after the app exists.
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

/// `sys.path` entries the embedded interpreter needs: our own packages
/// (`console`, `fingerprint`, `ingest`, `scoring`) plus their third-party
/// dependencies, plus `embedded_runner` itself.
///
/// Dev points at a real environment already on disk (`desktop/.venv312`),
/// so a Python change needs no rebuild -- the same promise the old
/// sidecar's dev path made. Release points at the bundled resource
/// `desktop/scripts/bundle-python.sh` assembles: a relocatable CPython plus
/// this project's third-party dependencies installed into it, plus a copy
/// of our own source (`resources/app-src`) -- never the real `fingerprint/`
/// etc. from the repo, which hold local RAW fixtures that must never leave
/// this machine (`docs/security.md`).
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
  // python-build-standalone's own layout differs on Windows: `Lib\site-packages`
  // at the runtime root, not `lib/python3.12/site-packages`
  // (`desktop/scripts/bundle-python.sh` assembles both shapes; this just has
  // to agree with whichever one it produced for the platform being built).
  #[cfg(target_os = "windows")]
  let site_packages = runtime.join("Lib/site-packages");
  #[cfg(not(target_os = "windows"))]
  let site_packages = runtime.join("lib/python3.12/site-packages");
  Ok(vec![resources_dir()?.join("app-src"), site_packages])
}

/// Set once, before `pyo3::prepare_freethreaded_python()` runs, and never
/// again: Python reads `PYTHONHOME` only at interpreter initialization.
/// Without it the linked `libpython` hunts for a standard library near
/// itself or on the machine that built it, neither of which exists on
/// whatever machine this actually runs on, and fails to boot at all --
/// before any of our own code, or its own errors, can say why.
#[cfg(not(debug_assertions))]
fn set_pythonhome() -> Result<(), Box<dyn std::error::Error>> {
  std::env::set_var("PYTHONHOME", resources_dir()?.join("python-runtime"));
  // Writing a .pyc cache into the bundle would need the bundle writable,
  // which it should not be, and on a synced folder (iCloud Drive under
  // ~/Documents, for a dev build in place) a rename() into it can simply
  // hang rather than fail -- measured, importing `encodings` at
  // interpreter startup never returned. There is no cache benefit to lose:
  // this process starts once and this interpreter never restarts within it.
  std::env::set_var("PYTHONDONTWRITEBYTECODE", "1");
  Ok(())
}

/// Runs `console.app` on a dedicated OS thread, for as long as the process
/// lives. Never joined: there is nothing to hand back, and the thread ends
/// only when the process does.
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
        // `os.environ` is a Python dict, built once from the C environment
        // when the `os` module first imports -- which happened already,
        // inside `pyo3::prepare_freethreaded_python()`, before this thread
        // existed. A `std::env::set_var` from here arrives too late for
        // Python to ever see: it changes the C-level table a snapshot was
        // already taken from. Writing through `os.environ` itself, instead,
        // is what actually reaches `console/chain.py` and friends, which
        // all read `os.environ.get(...)` -- and it is the one thing here
        // that does have to happen after the interpreter exists.
        let environ = py.import("os")?.getattr("environ")?;
        environ.set_item("GENESIS_REFERENCES", references.to_string_lossy().into_owned())?;
        environ.set_item("GENESIS_CATALOGUE", catalogue.to_string_lossy().into_owned())?;
        environ.set_item("GENESIS_CONSOLE_ORIGINS", WEBVIEW_ORIGINS)?;

        let sys = py.import("sys")?;
        let sys_path = sys.getattr("path")?;
        for entry in search_paths.iter().rev() {
          sys_path.call_method1("insert", (0, entry.to_string_lossy().into_owned()))?;
        }

        let console_app = py.import("console.app")?;
        let app_object = console_app.getattr("app")?;

        // uvicorn.Server would install signal handlers here if it believed
        // itself to be on the process's main thread -- see
        // `embedded_runner.py`'s docstring for why that belief is wrong for
        // us specifically, and why the workaround lives in Python rather
        // than here.
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  // Order matters and cannot be undone: PYTHONHOME has to be in the
  // environment before the interpreter first initializes, which
  // `prepare_freethreaded_python()` does immediately below. Setting it any
  // later -- inside `setup()`, say, once an `AppHandle` exists to compute
  // it more conveniently from -- would be too late to matter.
  #[cfg(not(debug_assertions))]
  set_pythonhome().expect("could not locate the bundled Python runtime");
  pyo3::prepare_freethreaded_python();

  tauri::Builder::default()
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

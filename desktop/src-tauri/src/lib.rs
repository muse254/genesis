//! The desktop shell around the Genesis console.
//!
//! The imaging core is Python (`fingerprint/`, `ingest/`, `console/`), so the
//! app starts it as a local process and the webview talks to it over
//! loopback, exactly as the browser console always has. Everything that
//! touches the RAW archive or K stays on this machine (`docs/security.md`,
//! "Where K lives").

use std::sync::Mutex;

use tauri::{Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::{process::CommandChild, ShellExt};

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

/// The running backend, so it can be stopped when the app exits rather than
/// left holding the port.
enum Backend {
  #[cfg(not(debug_assertions))]
  Sidecar(CommandChild),
  #[cfg(debug_assertions)]
  Dev(std::process::Child),
}

struct BackendState(Mutex<Option<Backend>>);

/// Environment for the backend. Data lives in the per-user app data
/// directory, never beside the binary and never in a repository.
fn backend_env(
  app: &tauri::AppHandle,
  port: u16,
) -> Result<Vec<(String, String)>, Box<dyn std::error::Error>> {
  let data = app.path().app_data_dir()?;
  let references = data.join("references");
  std::fs::create_dir_all(&references)?;
  Ok(vec![
    ("GENESIS_REFERENCES".into(), references.to_string_lossy().into_owned()),
    ("GENESIS_CATALOGUE".into(), data.join("catalogue.db").to_string_lossy().into_owned()),
    ("GENESIS_CONSOLE_ORIGINS".into(), WEBVIEW_ORIGINS.into()),
    ("GENESIS_CONSOLE_PORT".into(), port.to_string()),
    // The backend exits when its stdin closes, so it cannot outlive the app
    // however the app ends (`desktop/sidecar/genesis_console.py`).
    ("GENESIS_EXIT_WITH_PARENT".into(), "1".into()),
  ])
}

/// Release builds run the bundled, self-contained backend.
#[cfg(not(debug_assertions))]
fn start_backend(app: &tauri::AppHandle, port: u16) -> Result<Backend, Box<dyn std::error::Error>> {
  let (_rx, child) = app
    .shell()
    .sidecar("genesis-console")?
    .envs(backend_env(app, port)?)
    .spawn()?;
  Ok(Backend::Sidecar(child))
}

/// Development builds run the repository's own interpreter, so a Python
/// change needs no rebuild. The repo root is two levels above `src-tauri`.
#[cfg(debug_assertions)]
fn start_backend(app: &tauri::AppHandle, port: u16) -> Result<Backend, Box<dyn std::error::Error>> {
  let root = std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join("../..").canonicalize()?;
  let python = root.join(".venv/bin/python");
  let child = std::process::Command::new(python)
    .args(["desktop/sidecar/genesis_console.py"])
    .current_dir(&root)
    .envs(backend_env(app, port)?)
    .stdin(std::process::Stdio::piped())
    .spawn()?;
  Ok(Backend::Dev(child))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .manage(BackendState(Mutex::new(None)))
    .setup(|app| {
      if cfg!(debug_assertions) {
        app.handle().plugin(
          tauri_plugin_log::Builder::default()
            .level(log::LevelFilter::Info)
            .build(),
        )?;
      }

      let port = free_port()?;
      let backend = start_backend(app.handle(), port)?;
      *app.state::<BackendState>().0.lock().unwrap() = Some(backend);

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
    .run(|app, event| {
      if let RunEvent::Exit = event {
        if let Some(backend) = app.state::<BackendState>().0.lock().unwrap().take() {
          match backend {
            #[cfg(not(debug_assertions))]
            Backend::Sidecar(child) => {
              let _ = child.kill();
            }
            #[cfg(debug_assertions)]
            Backend::Dev(mut child) => {
              let _ = child.kill();
            }
          }
        }
      }
    });
}

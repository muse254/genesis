# Genesis desktop

The photographer's app: enrol a camera, register photographs, verify. It is
the console (`console/` + `console-ui/`) in a Tauri window, with the Python
backend bundled as a sidecar so nothing needs installing.

Everything that touches the RAW archive or K runs on this machine
(`docs/security.md`, "Where K lives"). Data lives in the per-user app data
directory, e.g. `~/Library/Application Support/io.github.muse254.genesis/`.

## Develop

```bash
npm --prefix console-ui install
cd desktop && cargo tauri dev        # runs .venv/bin/python, no freezing needed
```

## Build

```bash
python -m pip install pyinstaller    # in the environment with requirements.txt
desktop/scripts/build-sidecar.sh     # -> src-tauri/binaries/genesis-console-<triple>
cd desktop && cargo tauri build
```

CI builds macOS, Windows and Linux installers into a draft release:
`.github/workflows/desktop.yml`.

## How it runs

- The app picks a free loopback port, starts the backend on it, and injects
  the address into the page before any script runs.
- The backend exits when its stdin closes, so it never outlives the app.
- Builds are unsigned. macOS asks for right-click → Open the first time;
  Windows SmartScreen asks for "More info" → "Run anyway".

Measured on an M-series Mac, 17 Sept: the sidecar is 49 MB, cold start
13–34 s (the one-file bundle unpacks on every launch), and a CR3 verify takes
about 10 s.

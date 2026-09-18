# Genesis desktop

The photographer's app: enrol a camera, register photographs, verify. It is
the console (`console/` + `console-ui/`) in a Tauri window. The Python
imaging core runs **embedded in the app's own process** (PyO3) — no separate
program to install, and no sidecar process to spawn. See `PACKAGING.md` for
why and how, including two real bugs an embedded interpreter has that a
subprocess never did.

Everything that touches the RAW archive or K runs on this machine
(`docs/security.md`, "Where K lives"). Data lives in the per-user app data
directory, e.g. `~/Library/Application Support/io.github.muse254.genesis/`.

## Develop

```bash
npm --prefix console-ui install
uv venv desktop/.venv312 --python 3.12
uv pip install --python desktop/.venv312/bin/python -r ../requirements.txt
cd desktop && cargo tauri dev
```

`desktop/.venv312` is where the dev build's embedded interpreter looks for
`numpy`, `rawpy` and the rest — a real environment on disk, so a Python
change needs no rebuild.

## Build

```bash
desktop/scripts/bundle-python.sh     # -> src-tauri/resources/{python-runtime,app-src}
cd desktop && cargo tauri build
```

`bundle-python.sh` fetches a relocatable CPython (not the system one) and
installs this project's dependencies into it, so the shipped app needs no
Python installed on the machine it runs on. CI builds macOS, Windows and
Linux installers into a draft release: `.github/workflows/desktop.yml`
(Windows and Linux are implemented, not yet verified — `PACKAGING.md` says
so plainly).

## How it runs

- The app picks a free loopback port, starts the embedded interpreter
  serving `console.app` on it in a worker thread, and injects the address
  into the page before any script runs.
- One process. Quitting the app quits the interpreter with it — there is
  nothing else to kill.
- Builds are unsigned. macOS asks for right-click → Open the first time;
  Windows SmartScreen asks for "More info" → "Run anyway".

Measured on an M-series Mac, 18 Sept: **2 second cold start** (down from
13–35s with the superseded PyInstaller sidecar — `PACKAGING.md`), and a real
Canon CR3 decoded through the bundled runtime with nothing but the built
`.app` on the test machine.

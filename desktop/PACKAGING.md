# Packaging: the imaging core, embedded

18 September 2026. Replaces the sidecar architecture (`genesis_console.py`,
`build-sidecar.sh`, both kept for reference and unreferenced) with the
imaging core running inside the app's own process.

## What changed, and why

The desktop app used to spawn its Python backend as a **separate process**:
a PyInstaller one-file binary, started as a Tauri sidecar. That worked, but
carried a real cost, measured: **13 to 35 seconds** to cold-start, because a
one-file bundle unpacks its entire contents to a temp directory on every
launch. The page had no way to know when the subprocess would be ready, and
a first version of the app parked on "CONSOLE UNREACHABLE" forever if the
user looked before the subprocess was up — a real bug, not hypothetical,
fixed once in the sidecar's frontend and then made moot by removing the
subprocess entirely.

Now the imaging core runs **embedded in the Rust process itself**, via
[PyO3](https://pyo3.rs): a real CPython interpreter, on a dedicated worker
thread, serving the same FastAPI app (`console/app.py`) over loopback HTTP —
so the frontend's `fetch()` calls need no change at all. There is one
process. Quitting the app quits everything; there is nothing to spawn, race
against, or kill separately.

**Measured, 18 September, this machine:** 2 second cold start (down from
13–35s), and a real Canon CR3 decoded end-to-end through the bundled runtime
(`rawpy` → LibRaw → JPEG, via `/preview`) in a release build with no Python,
`.venv`, or PyInstaller sidecar anywhere on the test machine.

## What PyO3 does and does not solve

PyO3 embeds the **interpreter** — it links `libpython3.12` into the binary.
It does not bundle a Python *installation* or third-party packages; those
still have to physically exist on disk somewhere the interpreter can find
them. Two environments, two answers:

- **Dev** (`cargo tauri dev`): points at `desktop/.venv312`, a real
  environment already on disk. A Python change needs no rebuild — the same
  promise the old sidecar's dev path made.
- **Release**: points at a **relocatable CPython**
  ([python-build-standalone](https://github.com/astral-sh/python-build-standalone),
  fetched via `uv python install`) with this project's dependencies
  installed into it, bundled as a Tauri resource
  (`desktop/scripts/bundle-python.sh` assembles it; `tauri.conf.json`'s
  `bundle.resources` ships it). A machine with no Python installed at all
  can still run the shipped app.

## Two things that only bite in an embedded interpreter

Neither is hypothetical — both were hit and fixed building this.

**`PYTHONHOME` must be set before the interpreter initializes, and cannot be
changed after.** `pyo3::prepare_freethreaded_python()` calls `Py_Initialize`
the first time anything touches Python; without `PYTHONHOME` pointing at the
bundled runtime *before that call*, the linked `libpython` hunts for a
standard library near itself or on the machine that built it — neither
exists on the machine actually running the app, and it never even boots to
print an error. `run()` sets it, then calls `prepare_freethreaded_python()`,
in that order, and that order cannot be undone once the interpreter starts.

**`os.environ`, once Python has booted, is a snapshot, not a window onto the
real environment.** Rust's `std::env::set_var()` after that point changes the
process's environment table; it does not retroactively update the Python
dict already built from it. `console/chain.py` and the rest read
`os.environ.get(...)`, so anything they need — `GENESIS_REFERENCES`,
`GENESIS_CATALOGUE`, `GENESIS_CONSOLE_ORIGINS` — has to be written through
Python's own `os.environ` object (`py.import("os")?.getattr("environ")?`),
from inside the worker thread, after the interpreter exists. Missing this
was silent and specific: the webview's own origin (`tauri://localhost`) was
never in the allowed-origins list, so every request failed CORS, while a
`curl` from a terminal — a different origin — worked perfectly and made the
bug look like it wasn't there.

**One packaging-specific one:** don't let Python write `.pyc` bytecode
caches into the bundle. `PYTHONDONTWRITEBYTECODE=1` is set alongside
`PYTHONHOME`. The bundle should be read-only regardless, and on a synced
folder (iCloud Drive under `~/Documents`, hit while developing in place) a
`rename()` into a cache directory can simply hang rather than fail —
measured: importing `encodings` at interpreter startup never returned. There
is no cache to lose: this interpreter starts once and never restarts within
the process's life.

## Building it

```bash
# once, or whenever requirements.txt changes:
desktop/scripts/bundle-python.sh

cd desktop && cargo tauri build --bundles app
```

`bundle-python.sh` fetches a relocatable CPython 3.12.9 for the host
platform, installs `requirements.txt` into it, copies this project's own
`console/`, `fingerprint/`, `ingest/`, `scoring/` source (git-tracked `.py`
files only — never the local RAW fixtures those packages hold on disk, which
must never leave this machine, `docs/security.md`), and drops the result at
`desktop/src-tauri/resources/`, which `tauri.conf.json` bundles.

## What is proven, and what is not

**Proven, macOS, 18 September:** `cargo tauri dev` and a full release
`.app`, cold-started from a clean `Application Support` directory and clean
WebKit storage, no Python or Xcode-adjacent tooling required on the test
machine beyond what `bundle-python.sh` fetched itself.

**Not proven: Windows and Linux.** `bundle-python.sh` and
`desktop/src-tauri/src/lib.rs`'s `resources_dir()`/`python_search_paths()`
both branch for those platforms, following the same pattern
python-build-standalone documents for them — but neither has been built or
run. The first real CI run against `.github/workflows/desktop.yml` on those
runners is their actual test, not this document's say-so.

## Size

~217 MB per platform (a relocatable CPython plus `numpy`, `scipy`, `rawpy`
and the rest of `requirements.txt`), versus ~49 MB for the old PyInstaller
sidecar. The trade is a real one: about four times the disk, for a fifteen-
to seventeen-times faster cold start and one fewer process to reason about.
Shrinking it (dropping `tcl`/`tk` from the bundled runtime, which this
project never imports) is future work, not yet done.

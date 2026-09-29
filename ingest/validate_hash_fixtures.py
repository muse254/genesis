"""The browser's hash fixtures still describe this Python.

``rust/genesis-prnu/tests/fixtures/hashing/manifest.json`` is what the Rust
and WASM ports are tested against (``cargo test``, ``core/``'s
``npm test``). If ``hashing.py`` changes, or Pillow is upgraded and brings a
different libjpeg-turbo, the ports keep passing against the stale manifest
while the verify page quietly stops matching what Python registers. These
tests fail first, so the manifest gets regenerated
(``python -m ingest.dump_hash_fixtures``) and the ports rechecked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import features

from ingest import hashing

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "rust" / "genesis-prnu" / "tests" / "fixtures" / "hashing"
MANIFEST = json.loads((FIXTURES / "manifest.json").read_text())


def test_libjpeg_turbo_matches_the_manifest_and_the_wasm_build():
    pinned = re.search(r"LIBJPEG_TURBO_VERSION=(\S+)", (ROOT / "core" / "jpeg" / "build.sh").read_text())[1]
    assert features.version("libjpeg_turbo") == MANIFEST["libjpeg_turbo"] == pinned, (
        "Pillow's libjpeg-turbo, the fixtures and core/jpeg/build.sh must agree; "
        "see verify/README.md"
    )


@pytest.mark.parametrize("case", [c for c in MANIFEST["cases"] if c["expect"] == "match"], ids=lambda c: c["file"])
def test_manifest_hashes_are_current(case):
    path = FIXTURES / case["file"]
    assert "0x" + hashing.pixel_sha256(path).hex() == case["imageHash"]
    assert f"0x{hashing.perceptual_hash(path):016x}" == case["perceptualHash"]


def test_truncated_fixture_is_refused_by_python_too():
    # The browser refuses it to match this; if Pillow ever starts accepting
    # truncated files, the browser's refusal needs revisiting.
    with pytest.raises(OSError):
        hashing.pixel_sha256(FIXTURES / "jpeg_truncated.jpg")


#!/usr/bin/env bash
# Capture a Chainlink CRE simulation transcript, for submission evidence.
#
# The CRE prize accepts "a Confidential Workflow simulation using the CRE CLI
# or a live deployment", with evidence such as terminal output or execution
# logs. This produces that transcript, against a real frame, and writes it to
# a file you can attach.
#
# It does NOT produce an attestation. The simulator is not a real enclave --
# the CLI says so in its own banner and the banner is kept in the output
# deliberately. `docs/cre.md` is the honest reading.
#
#   cre/capture-evidence.sh <frame.CR3> [out.txt]
set -euo pipefail

FRAME="${1:?usage: capture-evidence.sh <frame.CR3> [out.txt]}"
OUT="${2:-cre-simulation-$(date -u +%Y%m%dT%H%M%SZ).log}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CRE_BIN="${CRE_BIN:-$HOME/.cre/bin/cre}"

cd "$ROOT"
[ -f .env ] && { set -a; . ./.env; set +a; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"; rm -f "$ROOT/cre/workflow/.env"' EXIT

echo "== building the payload from $FRAME (residual extracted locally)"
.venv/bin/python - "$FRAME" "$STAGE" <<'PY'
import json, sys
sys.path.insert(0, ".")
from fingerprint import prnu
from cre import payload as P

frame, stage = sys.argv[1], sys.argv[2]
reference = sorted(__import__("pathlib").Path(
    __import__("os").environ.get("GENESIS_REFERENCES", "data/references")).glob("*.npz"))
if not reference:
    raise SystemExit("no enrolled body -- run /enrol first")

ref = prnu.load_fingerprint(reference[0])[0]
planes = prnu.load_raw_planes(frame, crop=P.PLANE_SIZE * 2)
json.dump(P.build_payload(planes, reference[0].stem), open(f"{stage}/payload.json", "w"))
json.dump(P.build_secret(ref), open(f"{stage}/secret.json", "w"))
print(f"   payload built from {reference[0].stem}; K cropped to {P.PLANE_SIZE}² int8")
PY

# K goes into a gitignored .env for the length of the run and no longer. It is
# a cropped, quantised K and it never leaves this machine.
.venv/bin/python - "$STAGE" <<'PY'
import json, sys
stage = sys.argv[1]
secret = json.load(open(f"{stage}/secret.json"))
open("cre/workflow/.env", "w").write(
    "\n".join(f"SECRET_K{c}=" + json.dumps(secret[str(c)], separators=(",", ":"))
              for c in range(4)) + "\n")
PY

echo "== running the confidential workflow in the CRE simulator"
( cd cre/workflow && "$CRE_BIN" workflow simulate genesis \
    --target staging-settings --non-interactive --trigger-index 0 \
    --http-payload "$STAGE/payload.json" ) | tee "$OUT"

# The transcript is evidence and must not become a leak. K is base64 in the
# environment, never echoed -- but check rather than assume.
# Checked in Python rather than grep: BSD grep rejects `{400,}` in an ERE and
# exits non-zero, which made this read as "clean" while checking nothing. A
# safety check that silently does not run is worse than no check at all.
LEAK="$(.venv/bin/python -c '
import re, sys
text = open(sys.argv[1], errors="replace").read()
hit = re.search(r"SECRET_K", text) or re.search(r"[A-Za-z0-9+/]{400,}", text)
print("LEAK" if hit else "CLEAN")
' "$OUT")"

if [ "$LEAK" != "CLEAN" ]; then
  echo "!! the transcript looks like it contains key material; not keeping it"
  rm -f "$OUT"
  exit 1
fi

echo
echo "== wrote $OUT"
echo "   It names the TEE constraint resolved, the binary and config hashes,"
echo "   the enforced simulation limits, and the score. It does NOT contain K,"
echo "   and it is NOT an attestation -- see docs/cre.md."

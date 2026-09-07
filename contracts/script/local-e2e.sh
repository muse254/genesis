#!/usr/bin/env bash
#
# Enrol -> register -> look up, entirely offline against a local anvil.
#
# This is the demo path (docs/demo-script.md) minus ENS and the subgraph, and
# it is the thing to run before touching a testnet: if it does not work here
# it will not work there, and here it costs nothing and takes seconds.
#
#   anvil &
#   contracts/script/local-e2e.sh data/references/r10.npz path/to/frame.CR3
#
set -euo pipefail

FINGERPRINT="${1:?usage: local-e2e.sh <fingerprint.npz> <image> [session frames...]}"
IMAGE="${2:?usage: local-e2e.sh <fingerprint.npz> <image> [session frames...]}"
shift 2

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
RPC="${RPC:-http://127.0.0.1:8545}"
# anvil's first account. Local only -- never put a funded key in a repo.
PK="${PK:-0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80}"
export FOUNDRY_DISABLE_NIGHTLY_WARNING=1

cast block-number --rpc-url "$RPC" >/dev/null 2>&1 || {
  echo "no chain at $RPC -- start one with: anvil" >&2
  exit 1
}

echo "== building the record (this scores the image against the fingerprint)"
REC=$("$PYTHON" -m ingest record "$IMAGE" --fingerprint "$FINGERPRINT" \
        --hmac-key "demo-key" --geolocation "51.5074,-0.1278" --owner "osoro.eth" \
        ${@:+--session "$@"}) || {
  echo "the image does not match this fingerprint -- nothing to register" >&2
  exit 1
}
g() { printf '%s' "$REC" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin)['$1'])"; }

echo "   PCE $(g pceScore) against a threshold of $(g threshold)"

echo "== deploying the registry"
ADDRESS=$(forge create "$ROOT/contracts/src/Registry.sol:Registry" \
  --root "$ROOT/contracts" --rpc-url "$RPC" --private-key "$PK" --broadcast \
  | awk '/Deployed to:/ {print $3}')
echo "   $ADDRESS"

BODY=$(g bodyId); ENS=$(cast keccak "r10-4471.cam.osoro.eth")
echo "== registering the body"
cast send "$ADDRESS" "registerBody(bytes32,bytes32,bytes32)" \
  "$BODY" "$(g commitment)" "$ENS" --rpc-url "$RPC" --private-key "$PK" >/dev/null

IMAGE_HASH=$(g imageHash)
echo "== registering the photograph"
cast send "$ADDRESS" \
  "registerImage((bytes32,bytes32,bytes32,uint8,bytes32,bytes32,uint32,uint64))" \
  "($IMAGE_HASH,$(g perceptualHash),$BODY,$(g modificationLevel),$(g parentImageHash),$(g metadataHmac),$(g pceScore),$(g registeredAt))" \
  --rpc-url "$RPC" --private-key "$PK" >/dev/null

SESSION=""
if printf '%s' "$REC" | grep -q sessionRoot; then
  SESSION=$(cast keccak "session:$IMAGE_HASH")
  echo "== committing the session ($(g sessionFrames) frames, one root)"
  cast send "$ADDRESS" "commitSession(bytes32,bytes32,uint32)" \
    "$SESSION" "$(g sessionRoot)" "$(g sessionFrames)" \
    --rpc-url "$RPC" --private-key "$PK" >/dev/null
fi

echo
echo "== reading it back, as a verifier would"
FIELDS="images(bytes32)(bytes32,bytes32,bytes32,uint8,bytes32,bytes32,uint32,uint64)"
echo "   exposed on body : $(cast call "$ADDRESS" "$FIELDS" "$IMAGE_HASH" --rpc-url "$RPC" | sed -n 3p)"
echo "   recorded PCE    : $(cast call "$ADDRESS" "$FIELDS" "$IMAGE_HASH" --rpc-url "$RPC" | sed -n 7p)"
echo "   registered at   : $(cast call "$ADDRESS" "$FIELDS" "$IMAGE_HASH" --rpc-url "$RPC" | sed -n 8p)"
echo "   ERC-7053 entries: $(cast call "$ADDRESS" "commitCountFor(string)(uint256)" "genesis:${IMAGE_HASH#0x}" --rpc-url "$RPC")"

if [ -n "$SESSION" ]; then
  PROOF=$(printf '%s' "$REC" | "$PYTHON" -c "import json,sys; print('['+','.join(json.load(sys.stdin)['sessionProof'])+']')")
  echo "   in the session  : $(cast call "$ADDRESS" "verifyInclusion(bytes32,bytes32,bytes32[])(bool)" "$SESSION" "$IMAGE_HASH" "$PROOF" --rpc-url "$RPC")"
  echo "   a frame that is not: $(cast call "$ADDRESS" "verifyInclusion(bytes32,bytes32,bytes32[])(bool)" "$SESSION" "$(cast keccak 'another shoot')" "$PROOF" --rpc-url "$RPC")"
fi

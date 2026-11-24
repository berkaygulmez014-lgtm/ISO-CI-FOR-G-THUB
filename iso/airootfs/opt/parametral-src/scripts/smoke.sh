#!/usr/bin/env bash
# End-to-end smoke test of the *shipped* entry points (two real processes, real sockets).
set -euo pipefail
cd "$(dirname "$0")/.."
TMP=$(mktemp -d)
export PARAMETRAL_STATE="$TMP/state"
export PARAMETRAL_RUNTIME="$TMP/run"
export XDG_RUNTIME_DIR="$TMP/run-xdg"
export PYTHONPATH=src
KEY="${PARAMETRAL_OPERATOR_KEY:-$HOME/.local/state/parametral/operator.key}"

mkdir -p "$PARAMETRAL_RUNTIME" "$XDG_RUNTIME_DIR"

echo "== starting parametral-harddeny =="
python3 bin/parametral-harddeny --rules policy/hard_deny.v1.json --key "$KEY" \
  --socket "$PARAMETRAL_RUNTIME/harddeny.sock" > "$TMP/harddeny.log" 2>&1 &
HD_PID=$!
OS_PID=""
trap '[ -n "$HD_PID" ] && kill $HD_PID 2>/dev/null || true; [ -n "$OS_PID" ] && kill $OS_PID 2>/dev/null || true; rm -rf "$TMP"' EXIT

for _ in $(seq 1 100); do [ -S "$PARAMETRAL_RUNTIME/harddeny.sock" ] && break; sleep 0.05; done
[ -S "$PARAMETRAL_RUNTIME/harddeny.sock" ] || { echo 'parametral-harddeny did not start'; cat "$TMP/harddeny.log"; exit 1; }
cat "$TMP/harddeny.log"

echo "== oracle check: git (allow), modprobe (deny) =="
python3 -m parametral.cli harddeny check exec.run --scope '{"command":"git"}' | head -3
python3 -m parametral.cli harddeny check exec.run --scope '{"command":"modprobe"}' | head -3

echo "== starting parametrald =="
python3 bin/parametrald --harddeny-socket "$PARAMETRAL_RUNTIME/harddeny.sock" > "$TMP/osd.log" 2>&1 &
OS_PID=$!
for _ in $(seq 1 100); do [ -S "$PARAMETRAL_RUNTIME/v1/control.sock" ] && break; sleep 0.05; done
[ -S "$PARAMETRAL_RUNTIME/v1/control.sock" ] || { echo 'parametrald did not start'; cat "$TMP/osd.log"; exit 1; }
cat "$TMP/osd.log"

echo "== status =="
python3 bin/parametral status

echo "== doctor =="
python3 bin/parametral doctor

echo "SMOKE OK"

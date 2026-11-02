#!/usr/bin/env bash
# AstroGuard-QFV 60K experiment: cap neural training at 15 epochs.
# Copy into the repository root beside run_60k.py.
set -euo pipefail
cd "$(dirname "$0")"

PY=".venv/bin/python"
if [[ ! -x "$PY" || ! -f run_60k.py ]]; then
  echo "Run this script from the AstroGuard project directory containing .venv and run_60k.py" >&2
  exit 1
fi

ACTION="${1:-}"
PROFILE="${2:-}"
if [[ "$ACTION" != "train" && "$ACTION" != "analyze" ]]; then
  echo "Usage: bash train_60k_15epochs.sh {train|analyze} {classical|matched}" >&2
  exit 2
fi
if [[ "$PROFILE" != "classical" && "$PROFILE" != "matched" ]]; then
  echo "Profile must be classical or matched" >&2
  exit 2
fi

TAG="${PROFILE}_15ep"
DEVICE=auto
EXTRA=()
if [[ "$PROFILE" == "matched" ]]; then
  DEVICE=cpu
  EXTRA=(--matched-train 3000)
fi

COMMON=(--profile "$PROFILE" --tag "$TAG" --epochs 15 --batch 32 --device "$DEVICE" \
        --seeds 42 142 242 342 442 "${EXTRA[@]}")

if [[ "$ACTION" == "train" ]]; then
  exec "$PY" run_60k.py train "${COMMON[@]}"
else
  exec "$PY" run_60k.py analyze "${COMMON[@]}" --bootstrap 3000
fi

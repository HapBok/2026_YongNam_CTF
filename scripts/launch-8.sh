#!/usr/bin/env bash
set -euo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ "${1:-}" == "--mock" ]]; then
  exec python3 "$TASK_ROOT/ctfctl.py" --root "$TASK_ROOT" start --workers 8 --mock
fi
exec python3 "$TASK_ROOT/ctfctl.py" --root "$TASK_ROOT" start --workers 8


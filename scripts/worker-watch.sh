#!/usr/bin/env bash
set -uo pipefail
TASK_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
while true; do
  python3 "$TASK_ROOT/ctfctl.py" --root "$TASK_ROOT" worker "$@"
  result=$?
  if [[ $result -eq 0 || $result -eq 130 ]]; then
    exit "$result"
  fi
  printf 'Worker exited with %s; retrying registration after lease TTL.\n' "$result"
  sleep 16
done

#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
if command -v python3 >/dev/null 2>&1; then
  exec python3 scripts/start.py
elif command -v python >/dev/null 2>&1; then
  exec python scripts/start.py
else
  echo "Python 3.12+ is required. Install it and rerun ./start.sh." >&2
  exit 1
fi

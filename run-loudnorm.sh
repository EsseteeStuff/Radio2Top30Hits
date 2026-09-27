#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ -n "${VIRTUAL_ENV:-}" ]; then
  python -m loudnorm "$@"
else
  python3 -m loudnorm "$@"
fi

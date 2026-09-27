#!/usr/bin/env bash
# Start de GUI voor Radio 2 Top 30 Hits.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "[x] python3 niet gevonden. Installeer Python 3.10 of nieuwer." >&2
    exit 1
fi

for binary in ffmpeg yt-dlp; do
    if ! command -v "$binary" >/dev/null 2>&1; then
        echo "[!] '$binary' ontbreekt. Zie README.md voor de installatie-instructies." >&2
    fi
done

exec python3 -m radio2 "$@"

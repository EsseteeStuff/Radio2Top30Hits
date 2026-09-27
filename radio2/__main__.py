"""Startpunt: ``python3 -m radio2``."""

from __future__ import annotations

import sys


def main() -> int:
    try:
        from .gui import main as gui_main
    except ImportError as exc:
        print(f"[x] Kan de GUI niet laden: {exc}", file=sys.stderr)
        print("    Is 'python3-tk' geïnstalleerd? Zie README.md.", file=sys.stderr)
        return 1
    gui_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

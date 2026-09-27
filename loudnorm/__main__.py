"""Startpunt van de app die de luidheid van mp3's gelijktrekt.

Gebruik:  python3 -m loudnorm
"""

from __future__ import annotations

import importlib.util
import sys


def main() -> int:
    if importlib.util.find_spec("tkinter") is None:
        print("Tkinter ontbreekt. Installeer bijvoorbeeld python3-tk.",
              file=sys.stderr)
        return 1

    from .gui import main as start_gui

    return start_gui()


if __name__ == "__main__":
    raise SystemExit(main())

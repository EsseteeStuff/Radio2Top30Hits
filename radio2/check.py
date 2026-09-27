"""Controleert of alles aanwezig is om het programma te kunnen draaien.

Gebruik::

    python3 -m radio2.check
"""

from __future__ import annotations

import importlib.util
import shutil
import sys
from importlib import metadata

from . import browsers, config

OK = "ok"
FAIL = "fail"
WARN = "warn"

_COLORS = {
    OK: ("\033[32m", "OK  "),
    FAIL: ("\033[31m", "FOUT"),
    WARN: ("\033[33m", "let op"),
}

#: (module, importnaam, package, noodzakelijk)
PACKAGES = [
    ("yt_dlp", "yt-dlp", "YouTube-downloaden", True),
    ("requests", "requests", "de website ophalen", True),
    ("bs4", "beautifulsoup4", "de HTML uitlezen", True),
    ("lxml", "lxml", "snelle HTML-parser", True),
    ("mutagen", "mutagen", "ID3-tags schrijven", True),
    ("tkinter", None, "de GUI", True),
    ("secretstorage", "secretstorage", "Chromium-cookies ontsluiten (Linux)", False),
]


def _has_colors() -> bool:
    return sys.stdout.isatty()


def _symbol(mark: str) -> str:
    """Symbool met kleur, of een leesbaar alternatief zonder ANSI-ondersteuning."""
    char, plain = _COLORS[mark]
    return f"{char}{mark}\033[0m" if _has_colors() else plain


def _version(dist: str) -> str:
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return "onbekend"


def check_python() -> list[str]:
    problems: list[str] = []
    print(f"{_symbol(OK)}  Python {sys.version.split()[0]}")
    if sys.version_info < (3, 10):
        print(f"{_symbol(FAIL)}  Te oud: minimaal 3.10 nodig")
        problems.append("Python 3.10 of nieuwer")
    return problems


def check_packages() -> list[str]:
    problems: list[str] = []
    print("\nPython-pakketten")
    for module, dist, purpose, required in PACKAGES:
        found = importlib.util.find_spec(module) is not None
        if found:
            label = f"  {_version(dist)}" if dist else ""
            print(f"{_symbol(OK)}  {module:<15}{label:<12} {purpose}")
        elif required:
            print(f"{_symbol(FAIL)}  {module:<15}{'ontbreekt':<12} {purpose}")
            problems.append(dist or module)
        else:
            print(f"{_symbol(WARN)}  {module:<15}{'ontbreekt':<12} {purpose}")
    return problems


def check_binary(name: str, purpose: str) -> str | None:
    path = shutil.which(name)
    if path:
        print(f"{_symbol(OK)}  {name:<15}{path}")
    else:
        print(f"{_symbol(FAIL)}  {name:<15}{'ontbreekt':<12} {purpose}")
    return path


def check_browsers() -> None:
    print("\nBrowsers met profiel (voor de cookies)")
    usable = browsers.usable_browsers()
    recommended = browsers.recommended_browser()
    for browser in browsers.detect_browsers():
        if not browser.usable:
            continue
        note = ""
        if recommended and browser.key == recommended.key:
            note = "  <- aanbevolen"
        elif browser.is_default:
            note = "  <- standaardbrowser"
        print(f"{_symbol(OK)}  {browser.label:<15}{browser.profile_path}{note}")
    if not usable:
        print(
            f"{_symbol(WARN)}  Geen browserprofiel gevonden.\n"
            f"      Installeer bijvoorbeeld Chromium of Firefox, start het één keer\n"
            f"      en log in op YouTube. Zonder cookies werkt het downloaden anoniem."
        )


def check_js_runtime() -> None:
    print("\nJavaScript-runtime (voor YouTube)")
    runtime = config.detect_js_runtime()
    if runtime:
        for name, info in runtime.items():
            print(f"{_symbol(OK)}  {name:<15}{info['path']}")
        if sys.platform.startswith("linux") and "deno" not in runtime and not shutil.which("deno"):
            print(
                f"{_symbol(WARN)}  Deno zit niet in je PATH, maar het programma\n"
                f"      vindt het toch op. Voeg {info['path']} toe aan PATH als je\n"
                f"      het zelf wilt gebruiken."
            )
    else:
        print(
            f"{_symbol(WARN)}  Geen JS-runtime gevonden.\n"
            f"      Installeer Deno:  curl -fsSL https://deno.land/install.sh | sh\n"
            f"      Zonder runtime kunnen sommige YouTube-formaten ontbreken."
        )


def main() -> int:
    print("=" * 66)
    print("  Radio 2 Top 30 Hits - installatiecontrole")
    print("=" * 66)

    problems = check_python()
    check_packages()

    print("\nExterne programma's")
    for name, purpose in (("ffmpeg", "mp3-conversie"), ("yt-dlp", "YouTube-downloaden")):
        if not check_binary(name, purpose):
            problems.append(name)

    check_browsers()
    check_js_runtime()

    print()
    if problems:
        print("=" * 66)
        print("  Er ontbreekt nog:")
        for item in problems:
            print(f"    - {item}")
        print("=" * 66)
        return 1

    print("=" * 66)
    print("  Alles is aanwezig. Start het programma met ./run.sh")
    print("=" * 66)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

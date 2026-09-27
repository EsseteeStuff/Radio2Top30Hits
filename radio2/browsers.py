"""Detectie van geïnstalleerde browsers met een profiel, en van de standaardbrowser.

Wordt gebruikt om de cookies van de juiste browser aan yt-dlp door te geven, zodat
YouTube bot-detectie vermijdt. Op Windows/macOS kiezen we standaard de browser die
als standaardbrowser is ingesteld; op Linux heeft Chromium de voorkeur.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: Naam zoals yt-dlp het noemt → weergavenaam voor de GUI.
BROWSER_LABELS: dict[str, str] = {
    "chromium": "Chromium",
    "chrome": "Google Chrome",
    "firefox": "Firefox",
    "brave": "Brave",
    "edge": "Microsoft Edge",
    "vivaldi": "Vivaldi",
    "opera": "Opera",
}

#: Voorkeursvolgorde wanneer er geen standaardbrowser te bepalen valt.
PREFERENCE_ORDER = ("chromium", "chrome", "firefox", "brave", "edge", "vivaldi", "opera")


@dataclass(frozen=True)
class Browser:
    """Een browser die yt-dlp kan gebruiken."""

    key: str
    label: str
    has_profile: bool
    profile_path: str = ""
    is_default: bool = False

    @property
    def usable(self) -> bool:
        return self.has_profile


# --------------------------------------------------------------------------
# Profielpaden per besturingssysteem
# --------------------------------------------------------------------------
def _profile_candidates(key: str) -> list[Path]:
    home = Path.home()
    if sys.platform.startswith("linux"):
        table = {
            "chromium": [home / ".config" / "chromium"],
            "chrome": [home / ".config" / "google-chrome"],
            "brave": [home / ".config" / "BraveSoftware" / "Brave-Browser"],
            "vivaldi": [home / ".config" / "vivaldi"],
            "opera": [home / ".config" / "opera"],
            "edge": [home / ".config" / "microsoft-edge"],
            "firefox": [home / ".mozilla" / "firefox" / "Profiles"],
        }
        return table.get(key, [])

    if sys.platform == "darwin":
        support = home / "Library" / "Application Support"
        table = {
            "chrome": [support / "Google" / "Chrome"],
            "chromium": [support / "Chromium"],
            "brave": [support / "BraveSoftware" / "Brave-Browser"],
            "vivaldi": [support / "Vivaldi"],
            "opera": [support / "com.operasoftware.Opera"],
            "edge": [support / "Microsoft Edge"],
            "firefox": [support / "Firefox" / "Profiles"],
        }
        return table.get(key, [])

    if sys.platform.startswith("win"):
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        table = {
            "chrome": [local / "Google" / "Chrome" / "User Data"],
            "chromium": [local / "Chromium" / "User Data"],
            "brave": [local / "BraveSoftware" / "Brave-Browser" / "User Data"],
            "vivaldi": [local / "Vivaldi" / "User Data"],
            "opera": [roaming / "Opera Software" / "Opera Stable"],
            "edge": [local / "Microsoft" / "Edge" / "User Data"],
            "firefox": [roaming / "Mozilla" / "Firefox" / "Profiles"],
        }
        return table.get(key, [])

    return []


# --------------------------------------------------------------------------
# Standaardbrowser bepalen
# --------------------------------------------------------------------------
def _linux_default_browser() -> str | None:
    try:
        result = subprocess.run(
            ["xdg-settings", "get", "default-web-browser"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    desktop = result.stdout.strip()
    if not desktop:
        return None

    # 'firefox_firefox.desktop' -> 'firefox'
    name = desktop.removesuffix(".desktop").lower()
    if "chromium" in name:
        return "chromium"
    if "chrome" in name:
        return "chrome"
    if "firefox" in name:
        return "firefox"
    if "brave" in name:
        return "brave"
    if "vivaldi" in name:
        return "vivaldi"
    if "opera" in name:
        return "opera"
    if "edge" in name:
        return "edge"
    return None


def _macos_default_browser() -> str | None:
    plist = (
        Path.home()
        / "Library"
        / "Preferences"
        / "com.apple.LaunchServices"
        / "com.apple.launchservices.secure.plist"
    )
    if not plist.exists():
        return None
    try:
        with plist.open("rb") as handle:
            data = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException):
        return None

    handler = data.get("LSHandlerURLScheme", {})
    for scheme in ("http", "https"):
        value = handler.get(scheme)
        if not isinstance(value, str):
            continue
        lowered = value.lower()
        for key in PREFERENCE_ORDER:
            if key in lowered:
                return key
        if "cros" in lowered:
            return "chrome"
        if "edg" in lowered:
            return "edge"
    return None


def _windows_default_browser() -> str | None:
    try:
        import winreg  # type: ignore[import-not-found]
    except ImportError:
        return None
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\Shell\Associations"
            r"\UrlAssociations\http\UserChoice",
        ) as key:
            prog_id = winreg.QueryValueEx(key, "ProgId")[0]
    except OSError:
        return None

    mapping = {
        "ChromeHTML": "chrome",
        "ChromiumHTM": "chromium",
        "FirefoxURL": "firefox",
        "MSEdgeHTM": "edge",
        "BraveHTML": "brave",
        "VivaldiHTM": "vivaldi",
        "OperaStable": "opera",
    }
    return mapping.get(prog_id)


def default_browser_key() -> str | None:
    """Sleutel van de standaardbrowser, of ``None`` als die niet te bepalen is."""
    try:
        if sys.platform.startswith("linux"):
            return _linux_default_browser()
        if sys.platform == "darwin":
            return _macos_default_browser()
        if sys.platform.startswith("win"):
            return _windows_default_browser()
    except Exception:  # pragma: no cover - detectie mag nooit crashen
        return None
    return None


# --------------------------------------------------------------------------
# Detectie
# --------------------------------------------------------------------------
def detect_browsers() -> list[Browser]:
    """Alle bekende browsers terug, inclusief of ze een profiel hebben."""
    default_key = default_browser_key()
    found: dict[str, Browser] = {}

    for key in PREFERENCE_ORDER:
        candidates = _profile_candidates(key)
        existing = next((path for path in candidates if path.exists()), None)
        found[key] = Browser(
            key=key,
            label=BROWSER_LABELS.get(key, key.title()),
            has_profile=existing is not None,
            profile_path=str(existing) if existing else "",
            is_default=(key == default_key),
        )

    return [found[key] for key in PREFERENCE_ORDER]


def usable_browsers() -> list[Browser]:
    """Browsers die een profiel hebben, dus waarvan we cookies kunnen lezen."""
    return [browser for browser in detect_browsers() if browser.usable]


def recommended_browser() -> Browser | None:
    """Beste browser-keuze voor dit systeem.

    * Windows/macOS: de standaardbrowser indien die een profiel heeft.
    * Linux: Chromium indien aanwezig, anders de standaardbrowser, anders de
      eerste browser met een profiel.
    * Geen profiel gevonden: de standaardbrowser, zodat de gebruiker ten minste
      de instructie te zien krijgt om in te loggen.
    """
    browsers = detect_browsers()
    by_key = {browser.key: browser for browser in browsers}
    with_profile = [browser for browser in browsers if browser.usable]
    default_key = default_browser_key()

    if sys.platform.startswith("linux"):
        if by_key.get("chromium") and by_key["chromium"].usable:
            return by_key["chromium"]
        if default_key and default_key in by_key and by_key[default_key].usable:
            return by_key[default_key]
    else:
        if default_key and default_key in by_key and by_key[default_key].usable:
            return by_key[default_key]
        if with_profile:
            return with_profile[0]

    if with_profile:
        return with_profile[0]
    if default_key and default_key in by_key:
        return by_key[default_key]
    return None

"""Constanten en configuratie voor Radio 2 Top 30 Hits."""

from __future__ import annotations

from dataclasses import dataclass

APP_TITLE = "Radio 2 Top 30 Hits"
APP_SUBTITLE = "Hitnoteringen scraper  •  YouTube downloader  •  MP3 organizer"

# --------------------------------------------------------------------------
# Website (hitnoteringen.be)
# --------------------------------------------------------------------------
CHART_SLUG = "vrt-radio-2-top-30"
URL_TEMPLATE = "https://www.hitnoteringen.be/hitlijsten/{slug}/{year}-{week:02d}"

#: De Top 30 bestaat pas vanaf 1970, en begint dat jaar in week 18.
CHART_START_YEAR = 1970
CHART_FIRST_WEEK = 18

#: Maximaal weeknummer dat we proberen (52 of 53).
MAX_WEEK = 53

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

#: Seconden tussen twee scrape-requests (houdt de server vriendelijk).
REQUEST_DELAY = 1.2
REQUEST_RETRIES = 3

# --------------------------------------------------------------------------
# Metadata / ID3-tags
# --------------------------------------------------------------------------
ALBUM = "Oldies but Goldies"
GENRE = "Pop"
COMMENT = "Mijn Muziek Collectie"

# --------------------------------------------------------------------------
# Bestandsnamen in de WORKDIR
# --------------------------------------------------------------------------
MP4_DIRNAME = "mp4"
MP3_DIRNAME = "mp3"
MANIFEST_NAME = "manifest.json"
SHUFFLE_STATE_NAME = "shuffle_state.json"

#: Media-uitgangen die we naar mp3 converteren.
MEDIA_SUFFIXES = (".mp4", ".m4a", ".webm", ".mkv", ".mov", ".opus", ".ogg", ".aac", ".flac")


def hits_filename(begin_year: int, end_year: int) -> str:
    """Naam van de hitslijst, bv. ``hits_1970_1975.txt``."""
    return f"hits_{begin_year}_{end_year}.txt"


def detect_js_runtime() -> dict | None:
    """Zoek een JavaScript-runtime voor yt-dlp.

    YouTube-extractie heeft er tegenwoordig een nodig; zonder runtime kunnen
    sommige formaten ontbreken. Deno heeft de voorkeur, Node is de fallback.
    Het pad wordt expliciet doorgegeven zodat het ook werkt als de runtime
    niet in je PATH staat (zoals bij de standaard Deno-installatie het geval is).
    """
    import os
    import shutil
    import sys
    from pathlib import Path

    home = Path.home()
    suffix = ".exe" if sys.platform.startswith("win") else ""

    deno_candidates = [
        os.environ.get("DENO_INSTALL"),
        home / ".deno" / "bin",
        "/usr/local/bin",
        "/opt/homebrew/bin",
        home / ".local" / "bin",
    ]
    for directory in deno_candidates:
        if not directory:
            continue
        path = Path(directory) / f"deno{suffix}"
        if path.is_file():
            return {"deno": {"path": str(path)}}

    deno = shutil.which("deno")
    if deno:
        return {"deno": {"path": deno}}

    node = shutil.which("node")
    if node:
        return {"node": {"path": node}}

    return None


@dataclass(frozen=True)
class JobConfig:
    """Alle instellingen voor één run van het programma."""

    workdir: str
    music_dir: str
    begin_year: int
    end_year: int
    browser: str = ""  # leeg = geen cookies gebruiken
    audio_only: bool = True
    bitrate: str = "192k"

    @property
    def hits_path(self) -> str:
        import os

        return os.path.join(self.workdir, hits_filename(self.begin_year, self.end_year))

    @property
    def mp4_dir(self) -> str:
        import os

        return os.path.join(self.workdir, MP4_DIRNAME)

    @property
    def mp3_dir(self) -> str:
        import os

        return os.path.join(self.workdir, MP3_DIRNAME)

    @property
    def manifest_path(self) -> str:
        import os

        return os.path.join(self.workdir, MANIFEST_NAME)

    @property
    def shuffle_state_path(self) -> str:
        import os

        return os.path.join(self.workdir, SHUFFLE_STATE_NAME)

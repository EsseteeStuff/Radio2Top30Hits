"""Bewaren en teruglezen van de GUI-instellingen tussen sessies.

Standaard bewaarplek per besturingssysteem:

* Linux:   ``~/.config/radio2top30hits/settings.json``
* macOS:   ``~/Library/Application Support/Radio2Top30Hits/settings.json``
* Windows: ``%APPDATA%\\Radio2Top30Hits\\settings.json``

Het bewaren mag nooit de werkgang blokkeren, dus fouten worden stilzwijgend
genegeerd: een onleesbaar of beschadigd bestand betekent gewoon standaardwaarden.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

SETTINGS_VERSION = 1

VALID_BITRATES = ("128k", "192k", "256k", "320k")

#: Standaardwaarden; ook de type-informatie wordt gebruikt bij het teruglezen.
DEFAULTS: dict[str, object] = {
    "workdir": "",
    "music_dir": "",
    "begin_year": 1970,
    "end_year": 1975,
    "browser": "",  # sleutel van yt-dlp, bv. 'chromium' of '' voor anoniem
    "audio_only": True,
    "bitrate": "192k",
}


def settings_path() -> Path:
    """Het pad van het instellingenbestand voor dit systeem."""
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "Radio2Top30Hits" / "settings.json"

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Application Support"
            / "Radio2Top30Hits"
            / "settings.json"
        )

    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "radio2top30hits" / "settings.json"


def restore() -> tuple[dict[str, object], set[str]]:
    """Lees de opgeslagen instellingen, met validatie per veld.

    Geeft de waarden terug en de verzameling sleutels die daadwerkelijk in het
    bestand stonden. Die tweede waarde is nodig om te kunnen onderscheiden
    tussen "er is nog niets opgeslagen" en "de gebruiker koos bewust voor
    anoniem downloaden" — anders zou de aanbevolen browser worden overschreven.
    """
    result = dict(DEFAULTS)
    present: set[str] = set()

    try:
        with settings_path().open("r", encoding="utf-8") as handle:
            stored = json.load(handle)
    except (OSError, json.JSONDecodeError, ValueError):
        return result, present

    if not isinstance(stored, dict):
        return result, present

    for key, default in DEFAULTS.items():
        if key not in stored or type(stored[key]) is not type(default):
            continue
        result[key] = stored[key]
        present.add(key)

    # Jaartallen en bitrate nogmaals toetsen, ook als het type klopt.
    for key in ("begin_year", "end_year"):
        value = result[key]
        if not isinstance(value, int) or not 1970 <= value <= 2100:
            result[key] = DEFAULTS[key]
            present.discard(key)
    if result["bitrate"] not in VALID_BITRATES:
        result["bitrate"] = DEFAULTS["bitrate"]
        present.discard("bitrate")

    for key in ("workdir", "music_dir", "browser"):
        if not isinstance(result[key], str):
            result[key] = DEFAULTS[key]
            present.discard(key)

    return result, present


def save(values: dict[str, object]) -> bool:
    """Schrijf de instellingen weg. Geeft terug of het gelukt is."""
    payload = {"version": SETTINGS_VERSION}
    for key in DEFAULTS:
        payload[key] = values.get(key, DEFAULTS[key])

    path = settings_path()
    tmp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp_path, path)
        return True
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        return False

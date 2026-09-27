"""Kleine hulpfUNCTies: bestandsnamen, normalisatie, prefix-breedte."""

from __future__ import annotations

import os
import re
import unicodedata

#: Tekens die niet in een bestandsnaam mogen, op alle ondersteunde OS'en.
_INVALID_CHARS = '<>:"/\\|?*\0'

_WHITESPACE_RE = re.compile(r"\s+")
_PREFIX_RE = re.compile(r"^\s*\d{1,5}\s*[-_.]\s*")


def clean_text(value: str | None) -> str:
    """Whitespace normaliseren en unicode samenvoegen."""
    text = unicodedata.normalize("NFC", str(value or ""))
    text = text.replace("\u00a0", " ").replace("\u200b", "")
    return _WHITESPACE_RE.sub(" ", text).strip()


def _truncate_utf8(text: str, max_bytes: int) -> str:
    """Inkorten op UTF-8-grenzen zodat Windows (260 kar. limiet) niet breekt."""
    while text and len(text.encode("utf-8")) > max_bytes:
        cut = len(text) - 1
        while cut > 0 and (ord(text[cut]) & 0xC0) == 0x80:
            cut -= 1
        text = text[:cut].rstrip(" .")
    return text


def safe_filename(name: str, fallback: str = "onbekend", max_bytes: int = 150) -> str:
    """Maak een naam geschikt voor bestanden op Linux, Windows en macOS."""
    text = unicodedata.normalize("NFC", str(name or ""))
    text = "".join(" " if ch in _INVALID_CHARS else ch for ch in text)
    text = _WHITESPACE_RE.sub(" ", text).strip(" .")
    if not text:
        return fallback
    return _truncate_utf8(text, max_bytes) or fallback


def track_filename(artist: str, title: str) -> str:
    """``"George Harrison - My Sweet Lord"`` → veilige bestandsnaam."""
    artist_part = safe_filename(artist, fallback="onbekende artiest")
    title_part = safe_filename(title, fallback="onbekende titel")
    return f"{artist_part} - {title_part}"


def track_key(artist: str, title: str) -> str:
    """Genormaliseerde sleutel voor vergelijking/deduplicatie."""
    return f"{clean_text(artist).casefold()}||{clean_text(title).casefold()}"


def split_artist_title(stem: str) -> tuple[str, str]:
    """Haal artiest en titel uit ``"artiest - titel"`` (eerste koppelstreek)."""
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip()
    return stem.strip(), ""


def strip_prefix(filename: str) -> str:
    """Verwijder een eventuele nummerprefix, bv. ``0007-``."""
    stem = os.path.splitext(os.path.basename(filename))[0]
    return _PREFIX_RE.sub("", stem).strip()


def prefix_width(count: int) -> int:
    """Aantal cijfers in de prefix, afhankelijk van het aantal bestanden."""
    if count <= 9:
        return 2
    if count <= 99:
        return 3
    if count <= 999:
        return 4
    return 5


def numbered_name(stem: str, index: int, width: int) -> str:
    """``("My Sweet Lord", 7, 4)`` → ``"0007 - My Sweet Lord"``."""
    return f"{index:0{width}d} - {stem}"


def unique_path(path: str) -> str:
    """Voeg ``(1)``, ``(2)`` … toe totdat het pad vrij is."""
    if not os.path.exists(path):
        return path
    root, ext = os.path.splitext(path)
    counter = 1
    while True:
        candidate = f"{root} ({counter}){ext}"
        if not os.path.exists(candidate):
            return candidate
        counter += 1

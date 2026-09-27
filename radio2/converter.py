"""Converteren van mp4/m4a/webm naar mp3 met ffmpeg, plus het schrijven van ID3-tags."""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable

from mutagen.easyid3 import EasyID3
from mutagen.id3 import COMM, ID3, ID3NoHeaderError
from mutagen.mp3 import MP3

from . import config
from .utils import split_artist_title, track_filename

Logger = Callable[[str], None]
StopEvent = Callable[[], bool]


class Cancelled(Exception):
    """De gebruiker heeft op Stop geklikt."""


def ffmpeg_path() -> str:
    return shutil.which("ffmpeg") or "ffmpeg"


def media_files(directory: str) -> list[str]:
    """Alle te converteren bestanden in ``directory``, alfabetisch gesorteerd."""
    if not os.path.isdir(directory):
        return []
    names = [
        name
        for name in os.listdir(directory)
        if name.lower().endswith(config.MEDIA_SUFFIXES)
        and os.path.getsize(os.path.join(directory, name)) > 0
    ]
    return [os.path.join(directory, name) for name in sorted(names)]


def convert_one(
    src: str,
    dst_dir: str,
    artist: str,
    title: str,
    year: int,
    bitrate: str,
    log: Logger,
    should_stop: StopEvent,
) -> str | None:
    """Converteer één bestand naar mp3 en schrijf de ID3-tags. Geeft het pad terug."""
    stem = track_filename(artist, title)
    dst = os.path.join(dst_dir, f"{stem}.mp3")

    if os.path.exists(dst):
        try:
            os.remove(dst)
        except OSError as exc:
            log(f"    [x] Kan bestaand bestand niet overschrijven: {exc}")
            return None

    cmd = [
        ffmpeg_path(),
        "-hide_banner",
        "-loglevel", "error",
        "-nostdin",
        "-y",
        "-i", src,
        "-vn",                       # geen video
        "-map_metadata", "-1",       # oude/nonsense-tags weggooien
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        "-ar", "44100",
        "-id3v2_version", "3",
        "-write_id3v1", "1",
        dst,
    ]

    process = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        while process.poll() is None:
            if should_stop():
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise Cancelled()
            try:
                process.wait(timeout=0.2)
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()

    if process.returncode != 0:
        log(f"    [x] ffmpeg faalde voor {os.path.basename(src)}")
        if os.path.exists(dst):
            os.remove(dst)
        return None

    if not os.path.exists(dst) or os.path.getsize(dst) == 0:
        log(f"    [x] Leeg of ontbrekend mp3 voor {os.path.basename(src)}")
        return None

    write_tags(dst, artist=artist, title=title, year=year, log=log)
    return dst


def write_tags(path: str, artist: str, title: str, year: int, log: Logger) -> None:
    """Zet de ID3-tags met mutagen; ffmpeg wordt niet vertrouwd voor dit werk.

    De standaardvelden gaan via EasyID3. Het commentaar bestaat daar niet tussen
    en moet via het ID3 ``COMM``-frame, anders raakt het er helemaal niets van.
    """
    try:
        audio = MP3(path, ID3=EasyID3)
    except (ID3NoHeaderError, OSError) as exc:
        log(f"    [x] Kan mp3 niet openen voor tags: {exc}")
        return

    fields = {
        "artist": [artist],
        "title": [title],
        "album": [config.ALBUM],
        "date": [str(year)],
        "genre": [config.GENRE],
    }
    for key, value in fields.items():
        try:
            audio[key] = value
        except (KeyError, ValueError) as exc:
            log(f"    [!] Tag '{key}' niet geschreven: {exc}")

    try:
        audio.save()
    except (OSError, ValueError) as exc:
        log(f"    [x] Tags niet opgeslagen: {exc}")
        return

    try:
        tags = ID3(path)
        tags.delall("COMM")
        tags.add(COMM(encoding=3, lang="eng", desc="", text=config.COMMENT))
        tags.save()
    except (OSError, ValueError) as exc:
        log(f"    [!] Commentaar niet geschreven: {exc}")



def convert_all(
    mp4_dir: str,
    mp3_dir: str,
    manifest: dict[str, dict[str, str]],
    year: int,
    bitrate: str,
    log: Logger,
    should_stop: StopEvent,
    on_progress: Callable[[int, int, str], None],
) -> tuple[int, int]:
    """Converteer alle media in ``mp4_dir``. Geeft ``(ok, gefaald)`` terug.

    Het mp4-bestand wordt pas verwijderd als de mp3 succesvol is gemaakt.
    """
    os.makedirs(mp3_dir, exist_ok=True)
    sources = media_files(mp4_dir)
    total = len(sources)
    if not total:
        log("  [4/6] Geen media om te converteren.")
        return 0, 0

    log(f"  [4/6] {total} bestand(en) converteren naar mp3 ({bitrate}) …")

    converted = 0
    failed = 0

    for index, src in enumerate(sources, start=1):
        if should_stop():
            raise Cancelled()

        name = os.path.basename(src)
        info = manifest.get(name, {})
        if info:
            artist = info.get("artist") or ""
            title = info.get("title") or ""
        else:
            # Terugvaloptie: naam is "artiest - titel.ext".
            artist, title = split_artist_title(os.path.splitext(name)[0])

        on_progress(index, total, os.path.basename(src))
        log(f"  [{index:>{len(str(total))}}/{total}] {name}")

        try:
            result = convert_one(
                src, mp3_dir, artist, title, year, bitrate, log, should_stop
            )
        except Cancelled:
            raise
        except OSError as exc:
            log(f"    [x] I/O-fout: {exc}")
            result = None

        if result is None:
            failed += 1
            continue

        try:
            os.remove(src)
        except OSError as exc:
            log(f"    [!] mp4 kon niet verwijderd worden: {exc}")

        # Restanten van deze track opruimen.
        stem = os.path.splitext(name)[0]
        remove_siblings(mp4_dir, stem)

        converted += 1
        size_mb = os.path.getsize(result) / 1_048_576
        log(f"      → {os.path.basename(result)} ({size_mb:.1f} MB)")

    # Restanten van de mislukte conversies opruimen, zoals gevraagd.
    cleanup_leftovers(mp4_dir, log)
    return converted, failed


def remove_siblings(directory: str, stem: str) -> None:
    """Verwijder alle media-bestanden met dezelfde stamnaam (ook deelschrijvers)."""
    if not os.path.isdir(directory):
        return
    for name in os.listdir(directory):
        if not name.lower().endswith(config.MEDIA_SUFFIXES):
            continue
        if os.path.splitext(name)[0] == stem:
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass


def cleanup_leftovers(mp4_dir: str, log: Logger) -> None:
    """Verwijder alle overgebleven media- en restbestanden uit de mp4-map."""
    if not os.path.isdir(mp4_dir):
        return
    leftovers = [
        name
        for name in os.listdir(mp4_dir)
        if name.lower().endswith(config.MEDIA_SUFFIXES + (".part", ".ytdl", ".temp"))
    ]
    if not leftovers:
        return
    for name in sorted(leftovers):
        try:
            os.remove(os.path.join(mp4_dir, name))
            log(f"  [4/6] Restbestand opgeruimd: {name}")
        except OSError:
            pass

"""Downloaden van de nummers via yt-dlp, met de cookies van de lokale browser."""

from __future__ import annotations

import json
import os
from typing import Callable

import yt_dlp
from yt_dlp.utils import DownloadError

from . import config
from .scraper import Cancelled, Track
from .utils import safe_filename, track_filename

Logger = Callable[[str], None]
StopEvent = Callable[[], bool]
ProgressFn = Callable[[int, int, str], None]

#: Fouten die erop wijzen dat de cookies onbruikbaar zijn (niet ingelogd,
#: verlopen of versleuteld zonder keyring).
_COOKIE_ERRORS = (
    "cookies",
    "reloaded",
    "decrypt",
    "secretstorage",
    "keyring",
    "not logged in",
    "login required",
    "sign in to confirm",
    "premium account",
    "age-restricted",
)


class _Cancelled(Exception):
    """Onderbreekt yt-dlp vanuit de progress-hook."""


class _Logger:
    """Routeert yt-dlp's eigen uitvoer naar onze logcallback."""

    def __init__(self, log: Logger) -> None:
        self._log = log
        self._verbose = False

    def debug(self, msg: str) -> None:  # noqa: D102
        if self._verbose and msg.strip().startswith("["):
            return
        text = msg.strip()
        if text:
            self._log(f"    {text}")

    def info(self, msg: str) -> None:  # noqa: D102
        text = msg.strip()
        if text:
            self._log(f"    {text}")

    def warning(self, msg: str) -> None:  # noqa: D102
        text = msg.strip()
        if text:
            self._log(f"    [waarschuwing] {text}")

    def error(self, msg: str) -> None:  # noqa: D102
        text = msg.strip()
        if text:
            self._log(f"    [fout] {text}")

    def set_verbose(self, verbose: bool) -> None:
        self._verbose = verbose


def load_manifest(path: str) -> dict[str, dict[str, str]]:
    """Lees de manifest met bestandsnaam → {artiest, titel}."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_manifest(path: str, manifest: dict[str, dict[str, str]]) -> None:
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
    os.replace(tmp_path, path)


def build_ydl_opts(
    outtmpl: str,
    log: Logger,
    should_stop: StopEvent,
    on_progress: Callable[[dict], None],
    browser: str,
    audio_only: bool,
) -> dict:
    """Stel de yt-dlp-opties samen."""
    if audio_only:
        media_format = "bestaudio/best"
    else:
        media_format = "bestvideo[height<=480]+bestaudio/bestvideo+bestaudio/best"

    def progress_hook(status: dict) -> None:
        if should_stop():
            raise _Cancelled()
        on_progress(status)

    def match_filter(info, *, incomplete=False):  # noqa: ANN001, ARG001
        # Sla live-uitzendingen en hele compilaties over.
        duration = info.get("duration") or 0
        if duration > 15 * 60:
            return "te lang (> 15 min, waarschijnlijk een compilatie)"
        if 0 < duration < 45:
            return "te kort (< 45 sec)"
        return None

    opts: dict = {
        "outtmpl": {"default": outtmpl},
        "format": media_format,
        "merge_output_format": "mp4",
        "noplaylist": True,
        "playlist_items": "1",
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
        "no_color": True,
        "logger": _Logger(log),
        "progress_hooks": [progress_hook],
        "match_filter": match_filter,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 5,
        "socket_timeout": 30,
        "sleep_interval": 1,
        "max_sleep_interval": 3,
        "concurrent_fragment_downloads": 1,
        "writethumbnail": False,
        "overwrites": False,
        "continuedl": True,
        "ignoreerrors": False,
        "default_search": "ytsearch",
        "encoding": "utf-8",
    }
    if browser:
        opts["cookiesfrombrowser"] = (browser, None, None, None)

    js_runtime = config.detect_js_runtime()
    if js_runtime:
        opts["js_runtimes"] = js_runtime
    return opts


def existing_download(track: Track, mp4_dir: str) -> str | None:
    """Pad van een al gedownload nummer, of ``None``.

    Gezocht wordt zowel zonder als met container-afleiding, zodat een
    onderbroken run herkend wordt.
    """
    stem = track_filename(track.artist, track.title)
    for suffix in config.MEDIA_SUFFIXES:
        candidate = os.path.join(mp4_dir, stem + suffix)
        if os.path.exists(candidate) and os.path.getsize(candidate) > 0:
            return candidate
    return None


def remove_partials(mp4_dir: str, stem: str) -> None:
    """Verwijder ``.part``/``.ytdl``-restanten van een mislukte download."""
    if not os.path.isdir(mp4_dir):
        return
    for name in os.listdir(mp4_dir):
        if name.startswith(stem) and name.endswith((".part", ".ytdl", ".temp")):
            try:
                os.remove(os.path.join(mp4_dir, name))
            except OSError:
                pass


def download_track(
    track: Track,
    mp4_dir: str,
    log: Logger,
    should_stop: StopEvent,
    browser: str,
    audio_only: bool,
) -> str | None:
    """Download één nummer. Geeft het pad terug, of ``None`` bij een fout."""
    stem = track_filename(track.artist, track.title)
    query = f"{track.artist} {track.title} official audio"

    last_reported = -10

    def on_progress(status: dict) -> None:
        nonlocal last_reported
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        done = status.get("downloaded_bytes") or 0
        if not total:
            return
        percent = int(done * 100 / total)
        # Alleen loggen bij hele tientallen, zodat de log leesbaar blijft.
        if percent >= 100 or percent // 10 > last_reported // 10:
            last_reported = percent
            log(f"      {percent:>3}% gedownload")

    def attempt(with_cookies: bool) -> str | None:
        opts = build_ydl_opts(
            outtmpl=os.path.join(mp4_dir, f"{safe_filename(stem)}.%(ext)s"),
            log=log,
            should_stop=should_stop,
            on_progress=on_progress,
            browser=browser if with_cookies else "",
            audio_only=audio_only,
        )
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(f"ytsearch1:{query}", download=True)
        entries = info.get("entries") if isinstance(info, dict) else None
        target = entries[0] if entries else info
        path = ydl.prepare_filename(target)
        return path

    try:
        return attempt(with_cookies=bool(browser))
    except _Cancelled:
        remove_partials(mp4_dir, stem)
        raise Cancelled()
    except DownloadError as exc:
        message = str(exc)
        if browser and any(marker in message.lower() for marker in _COOKIE_ERRORS):
            log(f"    [!] Cookies van '{browser}' werken niet: {message.strip()}")
            log("    [i] Opnieuw proberen zonder cookies (anoniem) …")
            remove_partials(mp4_dir, stem)
            try:
                return attempt(with_cookies=False)
            except _Cancelled:
                raise Cancelled()
            except DownloadError as retry_exc:
                log(f"    [x] Mislukt: {str(retry_exc).strip()}")
                return None
        log(f"    [x] Mislukt: {message.strip()}")
        return None
    except Exception as exc:  # noqa: BLE001 - netwerk-/decoderfouten
        log(f"    [x] Onverwachte fout: {exc}")
        return None

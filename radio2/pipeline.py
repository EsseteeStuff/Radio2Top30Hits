"""De volledige werkgang: scrapen, downloaden, converteren, verplaatsen, shufflen."""

from __future__ import annotations

import os
import random
import threading
import time
from typing import Callable

from . import config, converter, downloader, organizer
from .scraper import Cancelled as ScrapeCancelled
from .scraper import Track, build_hits_list

Logger = Callable[[str], None]
ProgressFn = Callable[[int, int, str], None]


class Cancelled(Exception):
    """De gebruiker heeft op Stop geklikt."""


class Pipeline:
    """Voert de volledige werkgang uit in een achtergrondthread."""

    def __init__(self, cfg: config.JobConfig, log: Logger, progress: ProgressFn) -> None:
        self.cfg = cfg
        self.log = log
        self.progress = progress
        self._stop = threading.Event()

    # ------------------------------------------------------------------
    # Stop
    # ------------------------------------------------------------------
    def stop(self) -> None:
        self._stop.set()

    def _should_stop(self) -> bool:
        return self._stop.is_set()

    def _checkpoint(self) -> None:
        if self._should_stop():
            raise Cancelled()

    # ------------------------------------------------------------------
    # Voorwaarden
    # ------------------------------------------------------------------
    def _validate(self) -> None:
        cfg = self.cfg
        errors: list[str] = []

        if not cfg.workdir:
            errors.append("Kies een WORKDIR.")
        elif not os.path.isdir(cfg.workdir):
            errors.append(f"WORKDIR bestaat niet: {cfg.workdir}")

        if not cfg.music_dir:
            errors.append("Kies een MUZIEKFOLDER.")
        elif not os.path.isdir(cfg.music_dir):
            errors.append(f"MUZIEKFOLDER bestaat niet: {cfg.music_dir}")

        if cfg.begin_year < config.CHART_START_YEAR:
            errors.append(
                f"BEGINJAAR moet {config.CHART_START_YEAR} of later zijn."
            )
        if cfg.end_year < cfg.begin_year:
            errors.append("EINDJAAR moet gelijk zijn aan of later dan BEGINJAAR.")

        if errors:
            raise ValueError("\n".join(f"• {message}" for message in errors))

    # ------------------------------------------------------------------
    # Stap 3: downloaden
    # ------------------------------------------------------------------
    def _download(self, tracks: list[Track]) -> int:
        cfg = self.cfg
        os.makedirs(cfg.mp4_dir, exist_ok=True)

        manifest = downloader.load_manifest(cfg.manifest_path)
        pending: list[Track] = []

        for track in tracks:
            existing = downloader.existing_download(track, cfg.mp4_dir)
            if existing:
                name = os.path.basename(existing)
                stem = os.path.splitext(name)[0]
                manifest.setdefault(name, {"artist": track.artist, "title": track.title})
                self.log(f"  [3/6] {stem} — al gedownload")
            else:
                pending.append(track)

        downloader.save_manifest(cfg.manifest_path, manifest)

        if not pending:
            self.log("  [3/6] Alles is al gedownload.")
            return 0

        total = len(pending)
        self.log(
            f"  [3/6] {total} nummer(s) downloaden"
            f"{' (alleen audio)' if cfg.audio_only else ' (met video, max 480p)'}"
            f" naar {os.path.basename(cfg.mp4_dir)}/ …"
        )
        if cfg.browser:
            self.log(f"       Cookies: {cfg.browser}")
        js = config.detect_js_runtime()
        if js:
            runtime, info = next(iter(js.items()))
            self.log(f"       JS-runtime: {runtime} ({info['path']})")
        else:
            self.log("       [i] Geen JS-runtime gevonden; sommige YouTube-formaten")
            self.log("           kunnen dan ontbreken. Zie README.md over Deno.")

        downloaded = 0
        failed = 0
        for index, track in enumerate(pending, start=1):
            self._checkpoint()

            self.log(
                f"  [{index:>{len(str(total))}}/{total}] {track.artist} - {track.title}"
            )

            path = downloader.download_track(
                track=track,
                mp4_dir=cfg.mp4_dir,
                log=self.log,
                should_stop=self._should_stop,
                browser=cfg.browser,
                audio_only=cfg.audio_only,
            )

            if path is None:
                failed += 1
            else:
                downloaded += 1
                downloader.save_manifest(
                    cfg.manifest_path,
                    {**manifest, os.path.basename(path): {"artist": track.artist, "title": track.title}},
                )
                manifest[os.path.basename(path)] = {
                    "artist": track.artist,
                    "title": track.title,
                }

            self.progress(index, total, f"{track.artist} - {track.title}")

            if index < total:
                time.sleep(random.uniform(1.0, 2.5))  # wees beleidvol tegenover YouTube

        self.log(f"  [3/6] Klaar: {downloaded} gedownload, {failed} mislukt.")
        return failed

    # ------------------------------------------------------------------
    # Stap 2: dubbele controle, vóór het downloaden
    # ------------------------------------------------------------------
    def _dedupe(self, tracks: list[Track]) -> list[Track]:
        """Haal nummers die al in de muziekmap staan uit de downloadlijst."""
        self.log("  [2/6] De muziekmap controleren op bestaande nummers …")
        fresh, skipped = organizer.filter_duplicates(tracks, self.cfg.music_dir)
        if skipped:
            self.log(
                f"       {len(skipped)} nummer(s) staan er al → uit de downloadlijst gelaten."
            )
        else:
            self.log("       Niets te deduperen.")
        return fresh

    # ------------------------------------------------------------------
    # Volledige werkgang
    # ------------------------------------------------------------------
    def run(self) -> None:
        cfg = self.cfg
        started = time.time()

        try:
            self._validate()
        except ValueError as exc:
            self.log(f"[x] {exc}")
            self.progress(0, 1, "Fout in de instellingen")
            return

        self.log("")
        self.log("=" * 62)
        self.log(f"  {config.APP_TITLE}")
        self.log(f"  WORKDIR      : {cfg.workdir}")
        self.log(f"  MUZIEKFOLDER : {cfg.music_dir}")
        self.log(f"  JAREN        : {cfg.begin_year} – {cfg.end_year}")
        self.log("=" * 62)

        os.makedirs(cfg.workdir, exist_ok=True)
        os.makedirs(cfg.music_dir, exist_ok=True)
        os.makedirs(cfg.mp4_dir, exist_ok=True)
        os.makedirs(cfg.mp3_dir, exist_ok=True)

        try:
            # 1 — scrapen
            tracks = build_hits_list(
                begin_year=cfg.begin_year,
                end_year=cfg.end_year,
                hits_path=cfg.hits_path,
                log=self.log,
                should_stop=self._should_stop,
            )
            self._checkpoint()
            self.progress(0, 0, "Hitslijst klaar")

            if not tracks:
                self.log("  [x] Geen hits gevonden. Controleer het jaarbereik.")
                return

            # 2 — dubbele eruit, vóór het downloaden
            fresh = self._dedupe(tracks)
            self._checkpoint()
            self.progress(0, 0, "Downloadlijst gefilterd")

            # 3 — downloaden
            download_failures = self._download(fresh)
            self._checkpoint()

            # 4 — converteren
            manifest = downloader.load_manifest(cfg.manifest_path)
            converted, convert_failures = converter.convert_all(
                mp4_dir=cfg.mp4_dir,
                mp3_dir=cfg.mp3_dir,
                manifest=manifest,
                year=cfg.begin_year,
                bitrate=cfg.bitrate,
                log=self.log,
                should_stop=self._should_stop,
                on_progress=lambda done, total, name: self.progress(done, total, name),
            )
            self._checkpoint()

            # 5 — verplaatsen
            self.log("  [5/6] Mp3's verplaatsen naar de muziekmap …")
            moved = organizer.move_to_music(cfg.mp3_dir, cfg.music_dir, self.log)
            self.log(f"       {moved} bestand(en) verplaatst.")
            self._checkpoint()

            # 6 — shufflen en nummeren
            self.log("  [6/6] Collectie shufflen en hernummeren …")
            seed = random.randint(0, 2**31 - 1)
            numbered = organizer.shuffle_music(cfg.music_dir, self.log, seed=seed)
            organizer.set_track_numbers(numbered)
            organizer.write_shuffle_state(
                cfg.shuffle_state_path,
                seed=seed,
                count=len(numbered),
                width=organizer.prefix_width(len(numbered)),
            )

            elapsed = time.time() - started
            self.log("")
            self.log("=" * 62)
            self.log("  KLAAR")
            self.log(
                f"  Hits: {len(tracks)}   |   nieuw te downloaden: {len(fresh)}"
                f"   |   gedownload: {len(fresh) - download_failures}"
            )
            self.log(f"  Geconverteerd: {converted}   |   verplaatst: {moved}")
            if convert_failures or download_failures:
                self.log(
                    f"  Aandacht: {download_failures} download(s) en "
                    f"{convert_failures} conversie(s) mislukt."
                )
            self.log(f"  Totaal in de muziekmap: {len(organizer.mp3_files(cfg.music_dir))} mp3's")
            self.log(f"  Shuffle-seed: {seed}")
            self.log(f"  Duur: {int(elapsed // 60)}m {int(elapsed % 60)}s")
            self.log("=" * 62)
            self.progress(1, 1, "Klaar")

        except (Cancelled, ScrapeCancelled):
            self.log("")
            self.log("[…] Gestopt door de gebruiker. Opnieuw starten gaat verder waar je was.")
        except Exception as exc:  # noqa: BLE001 - laat niets ongezien
            self.log("")
            self.log(f"[x] Onverwachte fout: {exc.__class__.__name__}: {exc}")
            import traceback

            for line in traceback.format_exc().splitlines():
                self.log(f"    {line}")

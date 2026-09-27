"""Deduplicatie, verplaatsen naar de muziekmap, shufflen en hernummeren."""

from __future__ import annotations

import json
import os
import random
import shutil
from typing import Callable, Iterable, Sequence

from .scraper import Track
from .utils import (
    numbered_name,
    prefix_width,
    split_artist_title,
    strip_prefix,
    track_key,
)

Logger = Callable[[str], None]


def mp3_files(directory: str) -> list[str]:
    """Alle mp3's in ``directory``, gesorteerd op bestandsnaam."""
    if not os.path.isdir(directory):
        return []
    names = [name for name in os.listdir(directory) if name.lower().endswith(".mp3")]
    return [os.path.join(directory, name) for name in sorted(names)]


def existing_tracks(music_dir: str) -> dict[str, str]:
    """Welke nummers staan er al, en onder welke bestandsnaam?

    Geeft een mapping van genormaliseerde sleutel → bestandsnaam (zonder prefix).
    """
    found: dict[str, str] = {}
    for path in mp3_files(music_dir):
        stem = strip_prefix(path)
        artist, title = split_artist_title(stem)
        if not title:
            continue
        found[track_key(artist, title)] = os.path.basename(path)
    return found


def filter_duplicates(
    tracks: Sequence[Track], music_dir: str
) -> tuple[list[Track], list[Track]]:
    """Haal de nummers weg die al in de muziekmap staan.

    Geeft ``(nieuw, overgeslagen)`` terug.
    """
    existing = existing_tracks(music_dir)
    if not existing:
        return list(tracks), []

    fresh: list[Track] = []
    skipped: list[Track] = []
    seen: set[str] = set()

    for track in tracks:
        key = track_key(track.artist, track.title)
        if key in existing:
            skipped.append(track)
            continue
        if key in seen:  # komt meermaals in de hitslijst voor
            continue
        seen.add(key)
        fresh.append(track)

    return fresh, skipped


def move_to_music(mp3_dir: str, music_dir: str, log: Logger) -> int:
    """Verplaats alle mp3's uit ``mp3_dir`` naar ``music_dir``. Geeft aantal terug."""
    os.makedirs(music_dir, exist_ok=True)
    sources = mp3_files(mp3_dir)
    if not sources:
        log("  [5/6] Geen mp3's om te verplaatsen.")
        return 0

    moved = 0
    for src in sources:
        target = os.path.join(music_dir, os.path.basename(src))
        if os.path.exists(target):
            try:
                size_a, size_b = os.path.getsize(src), os.path.getsize(target)
            except OSError:
                size_a = size_b = -1
            if size_a == size_b and size_a > 0:
                os.remove(src)  # identiek: geen tweede kopie bewaren
                moved += 1
                continue
        try:
            shutil.move(src, target)
            moved += 1
        except (OSError, shutil.Error) as exc:
            log(f"  [5/6] Kon {os.path.basename(src)} niet verplaatsen: {exc}")

    # De mp3-map weer leegmaken op restbestanden na.
    if os.path.isdir(mp3_dir):
        for name in os.listdir(mp3_dir):
            try:
                os.remove(os.path.join(mp3_dir, name))
            except OSError:
                pass
    return moved


def _group_of(stem: str) -> str:
    """De artiest waarop we groeperen; het deel vóór de eerste koppelstreek."""
    artist, _ = split_artist_title(stem)
    return artist.casefold()


def shuffle_with_separation(
    items: Sequence,
    key_of: Callable[[object], str],
    rng: random.Random,
    max_passes: int = 400,
) -> list:
    """Schud ``items`` en voorkom dat twee buren dezelfde sleutel hebben.

    De items zelf worden mee geschud, dus een bijbehorend bestand blijft altijd
    aan zijn eigen naam hangen. Botsingen die na een gewone shuffle overblijven
    worden opgelost door twee items te ruilen, maar alleen als die ruil geen
    nieuwe botsing oplevert.
    """
    order = list(items)
    rng.shuffle(order)

    count = len(order)
    if count < 3:
        return order

    keys = [key_of(item) for item in order]

    def neighbours(index: int) -> list[int]:
        found = []
        if index > 0:
            found.append(index - 1)
        if index < count - 1:
            found.append(index + 1)
        return found

    for _ in range(max_passes):
        conflicts = [i for i in range(count - 1) if keys[i] == keys[i + 1]]
        if not conflicts:
            break

        fixed = 0
        for i in conflicts:
            for _attempt in range(24):
                j = rng.randrange(count)
                if abs(j - i) <= 1:
                    continue
                # Na de ruil staat 'target' op i en 'moving' op j; beide moeten
                # dan verschillen van hun nieuwe buren, anders verleggen we het
                # probleem alleen maar naar een andere plek.
                moving, target = keys[i], keys[j]
                if any(target == keys[k] for k in neighbours(i)):
                    continue
                if any(moving == keys[k] for k in neighbours(j)):
                    continue
                order[i], order[j] = order[j], order[i]
                keys[i], keys[j] = keys[j], keys[i]
                fixed += 1
                break

        # Geen vooruitgang meer: stop, anders blijven we eindeloos proberen
        # (bijvoorbeeld als één artiest het grootste deel van de lijst vormt).
        if fixed == 0:
            break

    return order


def shuffle_music(music_dir: str, log: Logger, seed: int | None = None) -> list[str]:
    """Schud de collectie en geef alles een oplopende prefix.

    Elk bestand behoudt zijn eigen naam; alleen de volgorde verandert. De
    shuffle is reproduceerbaar: dezelfde seed geeft dezelfde volgorde, en de
    seed wordt bewaard zodat je later kunt nakijken hoe die volgorde ontstond.
    """
    paths = mp3_files(music_dir)
    if not paths:
        return []

    rng = random.Random(seed)

    # Elke entry is (pad, stamnaam): die twee horen onlos van elkaar te blijven.
    pairs = [(path, strip_prefix(path)) for path in paths]
    ordered = shuffle_with_separation(
        pairs, key_of=lambda pair: _group_of(pair[1]), rng=rng
    )

    # Zorg dat elke naam uniek blijft, ook als twee bestanden dezelfde stam hebben.
    seen: set[str] = set()
    finalised: list[tuple[str, str]] = []
    for path, stem in ordered:
        candidate = stem
        suffix = 2
        while candidate.casefold() in seen:
            candidate = f"{stem} ({suffix})"
            suffix += 1
        seen.add(candidate.casefold())
        finalised.append((path, candidate))

    width = prefix_width(len(finalised))

    # In twee stappen hernoemen zodat er geen naam-botsingen ontstaan.
    staging: list[tuple[str, str]] = []
    for index, (old_path, stem) in enumerate(finalised, start=1):
        final_name = f"{numbered_name(stem, index, width)}.mp3"
        temp_name = f".shuffle-{os.getpid()}-{index}.tmp"
        staging.append((final_name, temp_name))
        try:
            os.rename(old_path, os.path.join(music_dir, temp_name))
        except OSError as exc:
            log(f"  [6/6] Hernoemen mislukt: {exc}")
            return []

    results: list[str] = []
    for final_name, temp_name in staging:
        temp_path = os.path.join(music_dir, temp_name)
        final_path = os.path.join(music_dir, final_name)
        try:
            os.rename(temp_path, final_path)
            results.append(final_path)
        except OSError as exc:
            log(f"  [6/6] Hernoemen mislukt: {exc}")

    groups = [_group_of(stem) for _, stem in finalised]
    adjacent = sum(1 for a, b in zip(groups, groups[1:]) if a == b)

    log(
        f"  [6/6] {len(results)} nummers geschud en genummerd met "
        f"{width} cijfers (seed {seed})."
    )
    if adjacent:
        log(
            f"       {adjacent} plek(ken) met dezelfde artiest achter elkaar; "
            "dat kon niet anders in deze collectie."
        )
    else:
        log("       Geen enkele twee nummers van dezelfde artiest spelen achter elkaar.")
    return results


def set_track_numbers(paths: Iterable[str]) -> None:
    """Zet het tracknummer gelijk aan de prefix, zodat spelers netjes doorlopen."""
    from mutagen.easyid3 import EasyID3
    from mutagen.id3 import ID3NoHeaderError
    from mutagen.mp3 import MP3

    for index, path in enumerate(paths, start=1):
        try:
            audio = MP3(path, ID3=EasyID3)
        except (ID3NoHeaderError, OSError, ValueError):
            continue
        try:
            audio["tracknumber"] = [str(index)]
            audio.save()
        except (OSError, ValueError, KeyError):
            pass


def write_shuffle_state(path: str, seed: int, count: int, width: int) -> None:
    """Bewaar het shuffle-log zodat de volgorde achteraf te reconstrueren is."""
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"seed": seed, "count": count, "prefix_width": width}, handle)
    except OSError:
        pass

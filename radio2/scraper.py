"""Scrapen van de VRT Radio 2 Top 30 op hitnoteringen.be.

De pagina bevat twee blokken met entries: een "Top 3" en de "Volledige lijst".
Alleen de volledige lijst wordt gebruikt, anders staan de eerste drie nummers
er dubbel in.
"""

from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass
from typing import Callable, Iterable, Iterator

import requests
from bs4 import BeautifulSoup

from . import config
from .utils import clean_text

Logger = Callable[[str], None]
StopEvent = Callable[[], bool]


class Cancelled(Exception):
    """De gebruiker heeft op Stop geklikt."""


@dataclass(frozen=True)
class Track:
    """Eén nummer uit de hitlijst."""

    artist: str
    title: str
    year: int


def week_url(year: int, week: int) -> str:
    return config.URL_TEMPLATE.format(slug=config.CHART_SLUG, year=year, week=week)


def first_week(year: int) -> int:
    """Week 1, behalve voor 1970 waar de lijst in week 18 begint."""
    if year == config.CHART_START_YEAR:
        return config.CHART_FIRST_WEEK
    return 1


def week_range(begin_year: int, end_year: int) -> Iterator[tuple[int, int]]:
    """Alle (jaar, week)-combinaties van beginjaar t/m eindjaar."""
    for year in range(begin_year, end_year + 1):
        for week in range(first_week(year), config.MAX_WEEK + 1):
            yield year, week


def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": config.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "nl-BE,nl;q=0.9,en;q=0.8",
        }
    )
    return session


def _get(session: requests.Session, url: str, log: Logger) -> requests.Response | None:
    """HTTP GET met retries. Geeft ``None`` terug bij een 404 (week bestaat niet)."""
    for attempt in range(1, config.REQUEST_RETRIES + 1):
        try:
            response = session.get(url, timeout=30)
        except requests.RequestException as exc:
            if attempt == config.REQUEST_RETRIES:
                log(f"    ! Verbinding mislukt ({exc.__class__.__name__}), sla over")
                return None
            time.sleep(1.5 * attempt)
            continue

        if response.status_code == 404:
            return None
        if response.status_code >= 500 and attempt < config.REQUEST_RETRIES:
            time.sleep(1.5 * attempt)
            continue
        if response.status_code >= 400:
            log(f"    ! HTTP {response.status_code}, sla deze week over")
            return None
        return response

    return None


def parse_entries(html: str) -> list[tuple[str, str]]:
    """Haal ``(artiest, titel)`` uit de volledige lijst van één pagina."""
    soup = BeautifulSoup(html, "lxml")

    # Voorkeur: de "Volledige lijst" (bevat de nummers 1..N zonder duplicaten).
    entries = soup.select("ol.chart li.entry")
    if not entries:
        entries = soup.select("ol.chart li")

    pairs: list[tuple[str, str]] = []
    for entry in entries:
        artist_span = entry.select_one("span.artiest")
        title_span = entry.select_one("span.titel")
        if not artist_span or not title_span:
            continue
        artist = clean_text(artist_span.get_text())
        title = clean_text(title_span.get_text())
        if artist and title:
            pairs.append((artist, title))

    if pairs:
        return pairs

    # Terugvaloptie: rechtstreeks de chartentry-div's (incl. het Top 3-blok).
    for block in soup.select("div.chartentry"):
        artist_span = block.select_one("span.artiest")
        title_span = block.select_one("span.titel")
        if not artist_span or not title_span:
            continue
        artist = clean_text(artist_span.get_text())
        title = clean_text(title_span.get_text())
        if artist and title:
            pairs.append((artist, title))
    return pairs


def scrape_week(
    session: requests.Session,
    year: int,
    week: int,
    log: Logger,
    should_stop: StopEvent,
) -> list[tuple[str, str]] | None:
    """Eén week scrapen. ``None`` als die week niet bestaat."""
    if should_stop():
        raise Cancelled()

    url = week_url(year, week)
    response = _get(session, url, log)
    if response is None:
        return None

    return parse_entries(response.text)


def load_hits(path: str) -> list[Track]:
    """Lees een bestaand hits-bestand (``artiest - song - jaar`` per regel)."""
    tracks: list[Track] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            head, _, year_part = line.rpartition(" - ")
            if not head or not year_part.isdigit():
                continue
            artist, _, title = head.partition(" - ")
            artist = artist.strip()
            title = title.strip()
            if artist and title:
                tracks.append(Track(artist, title, int(year_part)))
    return tracks


def save_hits(path: str, tracks: Iterable[Track]) -> None:
    """Schrijf de hitslijst weg; de lijst blijft uniek."""
    seen: set[tuple[str, str, int]] = set()
    lines: list[str] = []

    for track in tracks:
        marker = (track.artist.casefold(), track.title.casefold(), track.year)
        if marker in seen:
            continue
        seen.add(marker)
        lines.append(f"{track.artist} - {track.title} - {track.year}")

    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
        if lines:
            handle.write("\n")
    os.replace(tmp_path, path)


def build_hits_list(
    begin_year: int,
    end_year: int,
    hits_path: str,
    log: Logger,
    should_stop: StopEvent,
) -> list[Track]:
    """Bouw (of hergebruik) de hitslijst en geef de unieke nummers terug.

    Bestaat ``hits_path`` al, dan wordt die ongewijzigd gebruikt: herstarten na
    een onderbreking kost dan geen extra scrape-verzoeken.
    """
    if os.path.exists(hits_path):
        existing = load_hits(hits_path)
        if existing:
            log(
                f"  [i] {os.path.basename(hits_path)} bestaat al "
                f"({len(existing)} unieke hits) → hergebruikt, geen nieuw scrapen."
            )
            return existing
        log(f"  [!] {os.path.basename(hits_path)} is leeg → opnieuw scrapen")

    session = _make_session()
    collected: list[Track] = []
    seen: set[tuple[str, str]] = set()
    weeks_found = 0
    weeks_missing = 0

    log(f"  [1/6] Hitlijsten scrapen van {begin_year} tot en met {end_year} …")

    for year, week in week_range(begin_year, end_year):
        if should_stop():
            raise Cancelled()

        pairs = scrape_week(session, year, week, log, should_stop)
        if pairs is None:
            weeks_missing += 1
            continue

        weeks_found += 1
        new_in_week = 0
        for artist, title in pairs:
            marker = (artist.casefold(), title.casefold())
            if marker in seen:
                continue
            seen.add(marker)
            # De derde kolom is volgens opdracht altijd het beginjaar.
            collected.append(Track(artist, title, begin_year))
            new_in_week += 1

        log(f"  {year}-{week:02d}  {len(pairs):>2} nummers, {new_in_week:>2} nieuw "
            f"(totaal {len(collected)})")

        # Tussentijds wegschrijven, zodat een crash niets kost.
        save_hits(hits_path, collected)
        time.sleep(config.REQUEST_DELAY + random.uniform(0, 0.4))

    save_hits(hits_path, collected)

    log(
        f"  [1/6] Klaar: {len(collected)} unieke hits uit {weeks_found} weeklijsten"
        f" ({weeks_missing} week(en) bestonden niet)."
    )
    log(f"      {os.path.basename(hits_path)}")
    return collected

"""Motor voor het gelijktrekken van de luidheid van mp3-bestanden.

De motor doet drie dingen en praat met de GUI via terugroepfuncties:

1. :func:`meet` bepaalt van elk bestand de geintegreerde luidheid, de dynamiek
   en de true peak. Dat kost alleen decoderen, dus het gaat snel.
2. :func:`normaliseer` rekent per bestand de benodigde versterking uit en
   herschrijft het naar een tweede map.
3. :func:`wissel` zet de tweede map over de eerste heen, eventueel met een
   back-up van de originelen.

Alle uitvoer gaat via de meegegeven ``log``-functie, zodat de GUI niets anders
hoeft te doen dan een regel tekst tonen.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

#: Besturingssysteem-standaardvoldoende, ruim onder de grens van knippen.
PLAFOND = -1.0
#: Hierboven zou er echt vervorming ontstaan; dit is een harde grens.
NOODGRENS = 0.0
#: Drempel van de klem in dBFS. Onder PLAFOND om marge te houden voor de
#: inter-sample overshoot die het mp3-formaat zelf introduceert.
KLEM = -1.5
#: Aantal keer dat we een bestand mogen bijsturen als de piek te hoog blijft.
MAX_BIJSTUREN = 3

_ebur = re.compile(
    r"Integrated loudness:\s*I:\s*(-?[\d.]+)"
    r".*?Loudness range:\s*LRA:\s*(-?[\d.]+)"
    r".*?True peak:\s*Peak:\s*(-?[\d.]+)",
    re.S,
)

LEVERANCIERS = ("ffmpeg", "ffprobe")


class Fout(Exception):
    """Een probleem dat de gebruiker moet oplossen voordat er iets kan starten."""


# ----------------------------------------------------------------------
# Instellingen en meetresultaten
# ----------------------------------------------------------------------
@dataclass
class Instellingen:
    bronmap: Path
    doel: float = -14.0
    bitrate: str | None = "192k"  # None betekent: per bestand het origineel
    workers: int = 8
    doelmap: Path | None = None
    back_up: bool = True
    plafond: float = PLAFOND
    noodgrens: float = NOODGRENS

    def uitvoermap(self) -> Path:
        if self.doelmap is not None:
            return self.doelmap
        return self.bronmap.with_name(self.bronmap.name + "_genormaliseerd")

    def reserveer_ruimte(self) -> None:
        self.doelmap = self.uitvoermap()


@dataclass
class Meting:
    bestand: str
    lufs: float
    lra: float
    tp: float
    kbps: int
    duur: float


@dataclass
class Resultaat:
    bestand: str
    lufs: float | None = None
    tp: float | None = None
    geklemd: bool = False
    bijgestuurd: float = 0.0
    status: str = "nieuw"
    fout: str = ""


@dataclass
class Overzicht:
    bestanden: list[Meting] = field(default_factory=list)
    resultaten: list[Resultaat] = field(default_factory=list)
    mislukt: int = 0
    overgeslagen: int = 0
    doel: float = -14.0

    # -- samenvattingen -------------------------------------------------
    def luidheid_van(self, attr: str) -> tuple[float, float, float]:
        """(min, mediaan, max) vanuitkomsten, of een lege trip bij niets."""
        waarden = sorted(getattr(r, attr) for r in self.resultaten
                         if getattr(r, attr) is not None)
        if not waarden:
            return (0.0, 0.0, 0.0)
        return (waarden[0], waarden[len(waarden) // 2], waarden[-1])

    def statistieken(self, instellingen: "Instellingen") -> dict:
        """Alles wat de GUI nodig heeft voor het overzicht na afloop."""
        lmin, lmed, lmax = self.luidheid_van("lufs")
        _, _, tpmax = self.luidheid_van("tp")
        binnen = sum(1 for r in self.resultaten
                     if r.lufs is not None
                     and abs(r.lufs - instellingen.doel) <= 0.5)
        geklemd = sum(1 for r in self.resultaten if r.geklemd)
        over_grens = [r for r in self.resultaten
                      if r.tp is not None and r.tp > instellingen.plafond]
        knip = [r for r in self.resultaten
                if r.tp is not None and r.tp >= instellingen.noodgrens]
        return {
            "aantal": len(self.resultaten),
            "mislukt": self.mislukt,
            "overgeslagen": self.overgeslagen,
            "lufs_min": lmin, "lufs_mediaan": lmed, "lufs_max": lmax,
            "tp_max": tpmax,
            "binnen_tolerante": binnen,
            "geklemd": geklemd,
            "over_plafond": len(over_grens),
            "knip": len(knip),
        }

    def bewaar_meting(self, map_: Path, bestanden: list[str]) -> None:
        """Meetgegevens wegschrijven, zodat heropenen niet opnieuw meet."""
        _schrijf_cache(map_, bestanden, [vars(m) for m in self.bestanden])

    @classmethod
    def laad_meting(cls, map_: Path, bestanden: list[str],
                    doel: float) -> "Overzicht | None":
        regels = _lees_cache(map_, bestanden)
        if not regels:
            return None
        try:
            metingen = [Meting(**regel) for regel in regels]
        except (TypeError, KeyError):
            return None
        return cls(bestanden=metingen, doel=doel)


# ----------------------------------------------------------------------
# Vooraf
# ----------------------------------------------------------------------
def controleer_omgeving() -> list[str]:
    """Ontbrekende programma's. Leeg betekent: klaar."""
    ontbreekt = [naam for naam in LEVERANCIERS if shutil.which(naam) is None]
    return ontbreekt


# ----------------------------------------------------------------------
# Meetcache
#
# Meten kost tijd (circa twee minuten per uur muziek), dus de uitkomst wordt
# bewaard in de gebruikerscache. De vingerafdruk (het pad, het aantal bestanden
# en de grootste wijzigingstijd) bepaalt of de cache nog klopt.
# ----------------------------------------------------------------------
def cachemap() -> Path:
    basis = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    pad = Path(basis) / "loudnorm"
    pad.mkdir(parents=True, exist_ok=True)
    return pad


def _cachepad(map_: Path) -> Path:
    sleutel = hashlib.sha256(str(map_.resolve()).encode("utf-8")).hexdigest()[:20]
    return cachemap() / f"{sleutel}.json"


def nieuwste_wijziging(map_: Path, bestanden: list[str]) -> float:
    """Grootste wijzigingstijd in de map; 0.0 als er niets te vinden is."""
    nieuwste = 0.0
    for naam in bestanden:
        try:
            nieuwste = max(nieuwste, (map_ / naam).stat().st_mtime)
        except OSError:
            pass
    return nieuwste


def _vingerafdruk(map_: Path, bestanden: list[str]) -> str:
    ruw = "|".join([str(map_.resolve()), str(len(bestanden)),
                    f"{nieuwste_wijziging(map_, bestanden):.0f}"])
    return hashlib.sha256(ruw.encode("utf-8")).hexdigest()


def wis_cache(map_: Path) -> None:
    """Meetgegevens van deze map weggooien."""
    try:
        _cachepad(map_).unlink(missing_ok=True)
    except OSError:
        pass


def _schrijf_cache(map_: Path, bestanden: list[str], gegevens: list[dict]) -> None:
    try:
        _cachepad(map_).write_text(
            json.dumps({"vingerafdruk": _vingerafdruk(map_, bestanden),
                        "bestanden": gegevens}, ensure_ascii=False),
            encoding="utf-8")
    except OSError:
        pass  # een cache wegschrijven mag nooit de werkgang blokkeren


def _lees_cache(map_: Path, bestanden: list[str]) -> list[dict] | None:
    try:
        ruw = json.loads(_cachepad(map_).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if ruw.get("vingerafdruk") != _vingerafdruk(map_, bestanden):
        return None
    regels = ruw.get("bestanden")
    if not isinstance(regels, list) or not regels:
        return None
    return regels


def scan(map_: Path) -> list[str]:
    """Alle mp3-bestanden in de bovenste laag van de map."""
    if not map_.is_dir():
        raise Fout(f"Map bestaat niet: {map_}")
    if not os.access(map_, os.R_OK | os.W_OK):
        raise Fout(f"Map is niet leesbaar of schrijfbaar: {map_}")
    return sorted(naam for naam in os.listdir(map_)
                  if naam.lower().endswith(".mp3")
                  and os.path.isfile(map_ / naam))


def tel_submappen(map_: Path) -> int:
    """Hoeveel submappen er zijn die óók mp3's bevatten (die slaan we over)."""
    aantal = 0
    for item in map_.iterdir():
        if not item.is_dir():
            continue
        try:
            if any(p.suffix.lower() == ".mp3" for p in item.iterdir()):
                aantal += 1
        except OSError:
            continue
    return aantal


def schatting(overzicht: "Overzicht", workers: int) -> dict:
    """Duur en benodigde tijd, op basis van de al gemeten lengtes."""
    seconden = sum(m.duur for m in overzicht.bestanden)
    # gemeten tijdens het bouwen van dit programma: ongeveer 102x realtime
    # herschrijven met libmp3lame op dit aantal parallelle processen.
    return {
        "aantal": len(overzicht.bestanden),
        "uren": seconden / 3600,
        "norm_minuten": seconden / 102 / workers / 60,
    }


# ----------------------------------------------------------------------
# Meten
# ----------------------------------------------------------------------
def _meet_een(pad: Path) -> tuple[float, float, float] | None:
    """(lufs, lra, true peak) van één bestand."""
    try:
        uit = subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostats", "-i", str(pad),
             "-af", "ebur128=peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        return None
    gevonden = _ebur.search(uit.stderr.split("Summary:")[-1])
    if not gevonden:
        return None
    lufs, lra, tp = gevonden.groups()
    try:
        return (float(lufs), float(lra), float(tp))
    except ValueError:
        return None


def _eigenschappen(pad: Path) -> tuple[int, float]:
    """(kbit/s, duur in seconden) van één bestand."""
    try:
        uit = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=bit_rate", "-show_entries", "format=duration",
             "-of", "json", str(pad)],
            capture_output=True, text=True, timeout=60)
        gegevens = json.loads(uit.stdout or "{}")
        stroom = (gegevens.get("streams") or [{}])[0]
        bitrate = int(stroom.get("bit_rate") or 0)
        duur = float((gegevens.get("format") or {}).get("duration") or 0)
        return (bitrate // 1000, duur)
    except (ValueError, KeyError, IndexError, subprocess.TimeoutExpired):
        return (0, 0.0)


def meet(
    map_: Path,
    bestanden: list[str],
    workers: int,
    stop: threading.Event,
    voortgang,
) -> Overzicht:
    """Meet de luidheid van alle bestanden. Kan onderbroken worden."""
    overzicht = Overzicht()
    totaal = len(bestanden)
    klaar = 0

    def verwerk(naam: str) -> Meting | None:
        if stop.is_set():
            return None
        pad = map_ / naam
        gemeten = _meet_een(pad)
        if gemeten is None:
            return None
        kbps, duur = _eigenschappen(pad)
        return Meting(bestand=naam, lufs=gemeten[0], lra=gemeten[1],
                      tp=gemeten[2], kbps=kbps, duur=duur)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for meting in pool.map(verwerk, bestanden):
            klaar += 1
            if meting is not None:
                overzicht.bestanden.append(meting)
            elif stop.is_set():
                break
            if klaar % 10 == 0 or klaar == totaal:
                voortgang(klaar, totaal,
                          f"meten {klaar}/{totaal}  "
                          f"({len(overzicht.bestanden)} gelukt)")
            if stop.is_set():
                break
    return overzicht


# ----------------------------------------------------------------------
# Normaliseren
# ----------------------------------------------------------------------
def _filterketen(winst: float, drempel: float, geklemd: bool) -> str:
    delen = [f"volume={winst:.3f}dB"]
    if geklemd:
        delen.append(f"alimiter=limit={10 ** (drempel / 20):.5f}"
                     ":level=disabled:attack=5:release=50")
    return ",".join(delen)


def _encodeer(bron: Path, doelpad: Path, keten: str, bitrate: str | None) -> tuple[bool, str]:
    """Schrijf één mp3. Geeft (gelukt, foutmelding)."""
    tmp = doelpad.with_name(doelpad.name + ".tmp.mp3")
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
           "-i", str(bron), "-af", keten]
    if bitrate:
        cmd += ["-c:a", "libmp3lame", "-b:a", bitrate]
    else:
        # Geen vaste bitrate gevraagd: laat de encoder zelf kiezen op kwaliteit.
        cmd += ["-c:a", "libmp3lame", "-q:a", "2"]
    cmd += ["-map_metadata", "0", "-map_chapters", "0", str(tmp)]
    try:
        uit = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        return False, "time-out"
    if uit.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        regels = (uit.stderr or "").strip().splitlines()
        tmp.unlink(missing_ok=True)
        return False, regels[-1] if regels else f"exitcode {uit.returncode}"
    os.replace(tmp, doelpad)
    return True, ""


def _meet_eindbestand(pad: Path) -> tuple[float | None, float | None]:
    gemeten = _meet_een(pad)
    if gemeten is None:
        return (None, None)
    return (gemeten[0], gemeten[2])


def normaliseer(
    instellingen: Instellingen,
    overzicht: Overzicht,
    stop: threading.Event,
    voortgang,
) -> Overzicht:
    """Herschrijf alle gemeten bestanden met de gewenste luidheid."""
    doelmap = instellingen.uitvoermap()
    doelmap.mkdir(parents=True, exist_ok=True)

    metingen = overzicht.bestanden
    totaal = len(metingen)
    klaar = 0
    slot = threading.Lock()
    resultaten: list[Resultaat] = []

    def verwerk(meting: Meting) -> Resultaat:
        uitkomst = Resultaat(bestand=meting.bestand)
        if stop.is_set():
            uitkomst.status = "gestopt"
            return uitkomst

        bron = instellingen.bronmap / meting.bestand
        doelpad = doelmap / meting.bestand
        bitrate = instellingen.bitrate
        if not bitrate:
            # per bestand de oorspronkelijke bitrate aanhouden
            bitrate = f"{meting.kbps}k" if meting.kbps else None

        winst = instellingen.doel - meting.lufs
        uitkomst.geklemd = meting.tp + winst > instellingen.plafond
        # De klemdrempel beweegt mee bij bijsturen: draai je alleen het volume
        # terug, dan klemt de limiter de pieken opnieuw op zijn eigen drempel en
        # komt de true peak toch niet omlaag.
        drempel = KLEM

        if doelpad.exists() and doelpad.stat().st_size > 0:
            with slot:
                overzicht.overgeslagen += 1
        else:
            gelukt, fout = _encodeer(bron, doelpad,
                                    _filterketen(winst, drempel, uitkomst.geklemd),
                                    bitrate)
            if not gelukt:
                uitkomst.status = "mislukt"
                uitkomst.fout = fout
                return uitkomst

        lufs, tp = _meet_eindbestand(doelpad)
        for _ in range(MAX_BIJSTUREN):
            if stop.is_set() or tp is None or tp <= instellingen.plafond:
                break
            # Komt de piek toch boven 0 dBFS (alleen mogelijk als de bron zelf
            # al geknipt is), dan sturen we verder bij, met extra marge.
            if tp >= instellingen.noodgrens:
                bijstelling = instellingen.noodgrens - tp - 0.5
            else:
                bijstelling = instellingen.plafond - tp
            uitkomst.bijgestuurd = round(uitkomst.bijgestuurd + bijstelling, 3)
            winst += bijstelling
            drempel += bijstelling
            gelukt, fout = _encodeer(bron, doelpad,
                                    _filterketen(winst, drempel, uitkomst.geklemd),
                                    bitrate)
            if not gelukt:
                uitkomst.status = "mislukt"
                uitkomst.fout = f"bijsturen: {fout}"
                return uitkomst
            lufs, tp = _meet_eindbestand(doelpad)

        uitkomst.lufs = lufs
        uitkomst.tp = tp
        uitkomst.status = "klaar"
        return uitkomst

    with ThreadPoolExecutor(max_workers=instellingen.workers) as pool:
        for uitkomst in pool.map(verwerk, metingen):
            klaar += 1
            resultaten.append(uitkomst)
            if uitkomst.status == "mislukt":
                with slot:
                    overzicht.mislukt += 1
            voortgang(klaar, totaal,
                      f"normaliseren {klaar}/{totaal}  "
                      f"(mislukt {overzicht.mislukt})")
            if stop.is_set() and klaar >= totaal:
                break

    overzicht.resultaten = resultaten
    return overzicht


# ----------------------------------------------------------------------
# Afronden
# ----------------------------------------------------------------------
def controleer_resultaat(
    bronmap: Path, doelmap: Path, bestanden: list[str]
) -> dict:
    """Vergelijk de nieuwe map met de oude: aantal, bitrate, duur, leesbaar."""
    rapport = {
        "aantal_bron": len(bestanden),
        "aantal_nieuw": 0, "ontbreekt": [], "extra": [],
        "onleesbaar": [], "verkeerde_bitrate": [], "afwijkende_duur": [],
        "grootte_bron": 0, "grootte_nieuw": 0,
    }
    nieuw = {p.name for p in doelmap.glob("*.mp3")}
    rapport["aantal_nieuw"] = len(nieuw)
    rapport["ontbreekt"] = sorted(set(bestanden) - nieuw)
    rapport["extra"] = sorted(nieuw - set(bestanden))
    slot = threading.Lock()

    def controleer(naam: str) -> None:
        nieuwpad = doelmap / naam
        oudpad = bronmap / naam
        try:
            rapport["grootte_nieuw"] += nieuwpad.stat().st_size
            rapport["grootte_bron"] += oudpad.stat().st_size
        except OSError:
            pass
        uit = subprocess.run(["ffmpeg", "-v", "error", "-i", str(nieuwpad),
                              "-f", "null", "-"],
                             capture_output=True, text=True, timeout=300)
        if uit.returncode != 0 or uit.stderr.strip():
            with slot:
                rapport["onleesbaar"].append(naam)
            return
        oud = _eigenschappen(oudpad)
        nieuw_ = _eigenschappen(nieuwpad)
        if abs(oud[1] - nieuw_[1]) > 0.05:
            with slot:
                rapport["afwijkende_duur"].append(naam)

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(controleer, sorted(nieuw)))
    return rapport


def wissel(bronmap: Path, doelmap: Path, back_up: bool, log) -> dict:
    """Zet de genormaliseerde map over de bronmap heen.

    Met ``back_up`` gaan de originelen eerst naar een naastgelegen map, zodat
    er niets verloren gaat. Zonder back-up wordt de oude map verwijderd; dat kan
    alleen als de nieuwe map klaarstaat, want anders blijft er niets over.
    """
    if not doelmap.is_dir():
        raise Fout(f"De nieuwe map ontbreekt: {doelmap}")
    if not bronmap.is_dir():
        raise Fout(f"De oude map ontbreekt: {bronmap}")

    doel_nieuw = bronmap
    reserve = bronmap.with_name(bronmap.name + "_origineel")
    if reserve.exists():
        index = 2
        while (bronmap.with_name(f"{bronmap.name}_origineel.{index}")).exists():
            index += 1
        reserve = bronmap.with_name(f"{bronmap.name}_origineel.{index}")

    if back_up:
        os.rename(bronmap, reserve)
        log(f"originelen bewaard in {reserve.name}")
    try:
        # rename lukt alleen als het doel niet bestaat of leeg is; bij het
        # overschrijven zonder back-up moet de oude map dus eerst weg.
        if not back_up:
            shutil.rmtree(bronmap)
        os.rename(doelmap, doel_nieuw)
    except OSError as fout:
        if back_up and not bronmap.exists():
            os.rename(reserve, bronmap)          # terugdraaien
            log("het omschrijven is mislukt; de originelen zijn teruggezet")
        raise Fout(f"Het omschrijven is mislukt: {fout}") from fout
    return {"reserve": reserve if back_up else None, "bron": doel_nieuw}

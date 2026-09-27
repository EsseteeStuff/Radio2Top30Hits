# Radio 2 Top 30 Hits

Een programma met GUI dat de [VRT Radio 2 Top 30](https://www.hitnoteringen.be/hitlijsten/vrt-radio-2-top-30)
scrapt, de nummers van YouTube downloadt, ze naar mp3 converteert met ID3-tags, en
je muziekmap vervolgens schudt en hernummert.

![Python](https://img.shields.io/badge/python-3.10%2B-blue) ![Platforms](https://img.shields.io/badge/platforms-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)

---

## Snel starten

```bash
# 1. controleer of alles aanwezig is
python3 -m radio2.check

# 2. start het programma
./run.sh
```

Vul de twee mappen en het jaarbereik in, klik op **Starten**. De rest gaat
automatisch. Instellingen worden onthouden, dus de volgende keer hoef je alleen de
jaren aan te passen of meteen opnieuw te klikken.

Er staat nog een tweede programma in deze map, dat alleen de luidheid van je
mp3's gelijktrekt: [Luidheid Normaliseren](#luidheid-gelijktrekken-loudnorm).

---

## Inhoudsopgave

1. [Wat het programma doet](#wat-het-programma-doet)
2. [Benodigde software](#benodigde-software)
3. [Handleiding](#handleiding)
4. [Instellingen worden onthouden](#instellingen-worden-onthouden)
5. [Bestanden in de WORKDIR](#bestanden-in-de-workdir)
6. [Stoppen en herstarten](#stoppen-en-herstarten)
7. [Veelvoorkomende problemen](#veelvoorkomende-problemen)
8. [Luidheid gelijktrekken](#luidheid-gelijktrekken-loudnorm)
9. [Projectstructuur](#projectstructuur)

---

## Wat het programma doet

De werkgang bestaat uit zes stappen, die je in het uitvoerveld van het venster
ziet verschijnen:

| # | Stap | Wat er gebeurt |
| - | ---- | -------------- |
| 1 | **Scrapen** | Alle weeklijsten tussen BEGINJAAR en EINDJAAR worden opgehaald van hitnoteringen.be, per week `…/vrt-radio-2-top-30/jaar-week`. De lijst begint in 1970, en dat jaar begint in **week 18**. Weeken die niet bestaan (zoals 1971-53) worden stilzwijgend overgeslagen. |
| 2 | **Hitslijst** | Het resultaat komt in `hits_BEGINJAAR_EINDJAAR.txt`, één regel per nummer: `artiest - song - BEGINJAAR`. Dubbele regels worden eruit gehaald. Bestaat het bestand al, dan wordt het hergebruikt in plaats van opnieuw te scrapen. |
| 3 | **Downloaden** | Elk nummer wordt op YouTube gezocht (`artiest titel official audio`) en gedownload in `WORKDIR/mp4/`. |
| 4 | **Dedupliceren** | De muziekmap wordt doorzocht op bestaande `artiest - song`-mp3's; het prefix wordt genegeerd. Wat er al staat wordt uit de downloadlijst gehaald. |
| 5 | **Converteren** | Alles in `mp4/` wordt met ffmpeg omgezet naar mp3 met ID3-tags en daarna naar `WORKDIR/mp3/` gekopieerd. De mp4 wordt verwijderd zodra de mp3 klaar is. |
| 6 | **Verplaatsen en ordenen** | De mp3's gaan naar je MUZIEKFOLDER, waarna de hele map geschud en doorgenummerd wordt. |

### De ID3-tags

| Veld    | Waarde                  |
| ------- | ----------------------- |
| Artist  | de artiest              |
| Title   | de titel van het nummer |
| Album   | `Oldies but Goldies`    |
| Year    | het BEGINJAAR           |
| Genre   | `Pop`                   |
| Comment | `Mijn Muziek Collectie` |
| Track   | het nummer uit de prefix |

### Prefix en shuffle

De collectie wordt geschud, waarbij twee nummers van dezelfde artiest nooit direct
achter elkaar komen te staan (voor zover dat mogelijk is binnen je collectie). Daarna
krijgt elk bestand een oplopende prefix, afhankelijk van het totale aantal:

| Aantal mp3's | Voorbeeld                             |
| ------------ | ------------------------------------- |
| 1 – 9        | `01 - George Harrison - My Sweet Lord.mp3` |
| 10 – 99      | `047 - The Beatles - Hey Jude.mp3`    |
| 100 – 999    | `0123 - The Beatles - Hey Jude.mp3`   |
| 1000+        | `00045 - The Beatles - Hey Jude.mp3`  |

Omdat bestanden alfabetisch worden getoord, speelt je muziekspeler ze zo op een rij.

> Let op: bij elke run wordt de **hele** muziekmap opnieuw genummerd vanaf 1, en
> ook de al bestaande nummers krijgen een nieuwe plek. De ID3-tag `Year` van
> bestaande nummers blijft ongewijzigd; alleen nieuwe nummers krijgen het
> BEGINJAAR van hun eigen run.

---

## Benodigde software

Controleer in één keer of alles er is:

```bash
python3 -m radio2.check
```

Het script laat zien wat er aanwezig is, wat ontbreekt en hoe je het moet
installeren. Exitcode `0` betekent: klaar om te starten.

### Overzicht

| Wat | Nodig | Waarvoor |
| --- | ----- | -------- |
| Python 3.10+ | ja | het programma zelf |
| Tkinter | ja | de GUI; op Linux een apart pakket |
| ffmpeg | ja | converteren naar mp3 |
| yt-dlp | ja | downloaden van YouTube |
| requests, beautifulsoup4, lxml | ja | de website ophalen en uitlezen |
| mutagen | ja | ID3-tags schrijven |
| secretstorage | alleen Linux | Chromium/Chrome-cookies ontsluiten |
| Een browser met profiel | aanbevolen | YouTube-cookies tegen bot-detectie |
| Deno of Node | aanbevolen | YouTube heeft een JS-runtime nodig |

### 1. Python 3.10 of nieuwer

```bash
python3 --version
```

### 2. ffmpeg

Voor het converteren naar mp3.

```bash
# Debian / Ubuntu
sudo apt install ffmpeg

# Fedora
sudo dnf install ffmpeg

# Arch
sudo pacman -S ffmpeg

# macOS
brew install ffmpeg

# Windows
winget install Gyan.FFmpeg
```

### 3. Tkinter (de GUI)

Tkinter zit normaal bij Python, maar op Linux is het een apart pakket:

```bash
# Debian / Ubuntu
sudo apt install python3-tk

# Fedora
sudo dnf install python3-tkinter

# Arch
sudo pacman -S tk
```

Op macOS en Windows zit het in de officiële installatie van python.org.

### 4. Python-pakketten

```bash
pip3 install -r requirements.txt
```

| Pakket           | Waarvoor                                     |
| ---------------- | -------------------------------------------- |
| `yt-dlp`         | downloaden van YouTube                       |
| `requests`       | de website ophalen                           |
| `beautifulsoup4` | de HTML uitlezen                             |
| `lxml`           | snelle HTML-parser (achtergrond van bs4)     |
| `mutagen`        | de ID3-tags schrijven en lezen              |
| `secretstorage`  | alleen op Linux: Chromium-cookies ontsluiten |

> **Let op — Debian/Ubuntu.** Daar blokkeert het systeem `pip3 install` voor het
> systeem-Python (PEP 668, *"externally-managed-environment"*). Installeer de
> pakketten dan met `apt`:
>
> ```bash
> sudo apt install yt-dlp python3-requests python3-bs4 python3-lxml \
>                  python3-mutagen python3-secretstorage
> ```
>
> Let op: het apt-pakket heet `yt-dlp`, niet `python3-yt-dlp`. Wil je juist de
> nieuwste yt-dlp, gebruik dan `pipx install yt-dlp` of
> `pip3 install --break-system-packages yt-dlp`.

### 5. Een browser met een profiel (aanbevolen)

yt-dlp gebruikt de cookies van je browser om de bot-detectie van YouTube te
vermijden.

> **Advies:** installeer een browser die je niet dagelijks gebruikt (bijvoorbeeld
> Chromium naast Firefox), start hem **één keer** en log in op je YouTube-account.
> Zo hoef je je gewone browser niet te sluiten om aan de cookies te komen.

Het programma kiest automatisch:

| Besturingssysteem | Voorkeur                                         |
| ----------------- | ------------------------------------------------ |
| Windows, macOS    | de browser die als standaardbrowser is ingesteld |
| Linux             | Chromium, anders de standaardbrowser             |

Staat er geen geschikte browser met profiel, kies dan in de GUI
`Geen cookies (anoniem)`. Downloaden werkt dan ook, maar met meer kans op
bot-detectie.

### 6. Deno (aanbevolen)

YouTube-extractie heeft tegenwoordig een JavaScript-runtime nodig; zonder runtime
kunnen sommige formaten ontbreken.

```bash
curl -fsSL https://deno.land/install.sh | sh
```

Het programma zoekt Deno zelf, ook op de standaard installatielocatie `~/.deno/bin`
(waar het niet in je `PATH` staat). Is Deno niet geïnstalleerd, dan valt het terug
op Node als dat aanwezig is.

---

## Handleiding

### Stap 0 — controleer de installatie

```bash
python3 -m radio2.check
```

Alles groen? Ga door. Zie je `FOUT`, installeer dan wat er ontbreekt.

### Stap 1 — start het programma

```bash
./run.sh
```

Of, als `./run.sh` niet uitvoerbaar is:

```bash
bash run.sh
```

Of helemaal direct, zonder script:

```bash
python3 -m radio2
```

### Stap 2 — vul de velden in

| Veld | Betekenis |
| ---- | --------- |
| **WORKDIR** | Map voor alle tussenbestanden: de hitslijst, de `mp4/`- en `mp3/`-mappen. Kan een aparte werkschijf of SSD zijn. |
| **MUZIEKFOLDER** | De map waar je mp3's uiteindelijk terechtkomen. Dit is je echte muziekcollectie. |
| **BEGINJAAR** | Eerste jaar van de Top 30. Vanaf **1970** (dat jaar begint in week 18). |
| **EINDJAAR** | Laatste jaar, tot en met. |
| **BROWSER-COOKIES** | Welke browser yt-dlp mag gebruiken. Zie [boven](#5-een-browser-met-een-profiel-aanbevolen). |
| **AUDIOKWALITEIT** | 128k, 192k (standaard), 256k of 320k. |
| **Alleen audio downloaden** | Aan laten staan; video is voor een mp3 toch nutteloos. Uitzetten kan soms betere resultaten geven, omdat dan ook de officiële videoversie wordt meegenomen. |

Rechtsboven in het venster staan twee knoppen om te bladeren. Je mag ook
handmatig typen; het pad wordt bij het starten gecontroleerd.

Twee dingen die het programma voor je controleert:

- bestaan beide mappen, en zijn ze schrijfbaar?
- ligt BEGINJAAR niet na EINDJAAR, en liggen beide tussen 1970 en 2100?

Klopt er iets niet, dan krijg je een melding in plaats van een halve run.

### Stap 3 — klik op Starten

De voortbalk en het uitvoerveld lopen van onder naar boven mee. De zes stappen
verschijnen een voor een, met per nummer een regel. Onderaan zie je hoeveel
nummers er nog moeten.

De eerste run over één jaar duurt al enkele minuten; er wordt immers
gepolitseerd (zie [Stoppen en herstarten](#stoppen-en-herstarten)).

### Stap 4 — laat het werken

Je kunt het venster open laten en gewoon wegklikken. De voortgang staat op
schijf, dus een herstart is nooit verloren werk.

### Stap 5 — luisteren

Open MUZIEKFOLDER in je muziekspeler. De bestanden staan in de volgorde waarin je
ze hebt opgeslagen, met de nummers van dezelfde artiest gespreid door de lijst.

---

## Instellingen worden onthouden

Je hoeft niet elke keer opnieuw te bladeren. De WORKDIR, MUZIEKFOLDER, de jaren,
de browser-keuze, de audiokwaliteit en de audio-only-instelling worden bewaard
zodra je op **Starten** klikt of het programma afsluit:

| Besturingssysteem | Locatie |
| ----------------- | ------- |
| Linux             | `~/.config/radio2top30hits/settings.json` |
| macOS             | `~/Library/Application Support/Radio2Top30Hits/settings.json` |
| Windows           | `%APPDATA%\Radio2Top30Hits\settings.json` |

Onderaan het venster staat het pad; klik erop om de map te openen.

Een beschadigd of onleesbaar bestand wordt genegeerd — het programma start dan
gewoon met de standaardwaarden. Elk veld wordt apart gecontroleerd, dus één fout
veld laat de rest gewoon staan. Verwijder `settings.json` als je opnieuw wilt
beginnen. Staat een onthouden map er niet meer, dan blijft het pad staan (handig
bij een externe schijf die je later weer koppelt) en verschijnt er een waarschuwing
in het uitvoerveld.

---

## Bestanden in de WORKDIR

```
WORKDIR/
├── hits_1970_1975.txt   de unieke hitslijst (artiest - song - jaar)
├── manifest.json        welk mp3 bij welk nummer hoort
├── shuffle_state.json   de gebruikte shuffle-seed
├── mp4/                 downloads (leeg na afloop)
└── mp3/                 geconverteerde bestanden (leeg na afloop)
```

`mp4/` en `mp3/` worden na afloop leeggemaakt: alles wat bruikbaar is staat in je
muziekmap. De drie bestanden blijven staan, zodat je kunt nagaan wat er is
gebeurd.

---

## Stoppen en herstarten

**Stoppen** onderbreekt veilig, midden in een download. Geen bestand raakt
beschadigd, en bij **Starten** gaat het verder waar het was:

- De hitslijst wordt na elke week weggeschreven en bij een herstart hergebruikt in
  plaats van opnieuw te scrapen.
- Al gedownloade bestanden worden herkend en niet dubbel gedownload.
- Een mp4 wordt pas verwijderd als de mp3 klaar is.
- Nummers die al in je muziekmap staan worden overgeslagen.

Er wordt gepolitseerd om je niet te overbelasten: bij het scrapen zit er 1,2
tot 1,6 seconden tussen twee verzoeken, en tussen twee downloads 1 tot 2,5
seconden, plus de eigen pauzes van yt-dlp. Bij een groot jaarbereik kan dat
aardig oplopen — 1971 alleen is al 247 unieke nummers.

---

## Veelvoorkomende problemen

### `pip3 install` werkt niet met *"externally-managed-environment"*

Debian/Ubuntu blokkeert pip voor het systeem-Python. Zie
[Python-pakketten](#4-python-pakketten) hierboven voor de `apt`-alternatieven.

### `The page needs to be reloaded` of `Sign in to confirm you're not a bot`

YouTube wil dat je ingelogd bent. Kies in de GUI een browser waar je **daadwerkelijk
in ingelogd bent** op YouTube. Het programma valt dan automatisch terug op anoniem
downloaden, maar dat slaagt vaker mis.

Log je nog niet ingelogd, start de browser één keer, ga naar youtube.com en log in.
Daarna in de GUI opnieuw **Starten** klikken is genoeg.

### Op Windows: de cookie-database is op slot

Chrome en Edge vergrendelen hun cookie-bestand zolang de browser draait. Sluit de
browser, of verhuis je cookies naar een aparte browser die je alleen even opent.

### Er worden steeds dezelfde nummers gemist

Sommige nummers staan niet op YouTube, of alleen als heel korte fragmenten. Het
programma weigert alles korter dan 45 seconden en langer dan 15 minuten
(waarschijnlijk een compilatie) en logt dat als mislukt. Dat is geen fout in het
programma; zo'n nummer staat dan gewoon niet in de collectie.

### `--break-system-packages` of `externally-managed-environment` in de log

Alleen zichtbaar als je zelf pakketten installeert. Het programma zelf gebruikt
geen pip.

### Het downloaden is heel langzaam

Twee dingen: het jaarbereik is groot, en er wordt gewart op YouTube. Kies een
kortere periode, of laat het een nacht draaien. De voortbalk laat zien hoe ver
je bent, en **Stoppen** bewaart alles tot dat punt.

### Een map is verdwenen (externe schijf)

Het programma onthoudt het pad, ook als de map er niet is, en waarschuwt in het
uitvoerveld. Koppel de schijf terug en klik opnieuw **Starten**; of blader opnieuw
naar de juiste map.

### Ik wil helemaal opnieuw beginnen

Verwijder `settings.json` (het pad staat onderaan het venster) en leeg de
`WORKDIR`. Let op: bij de volgende run wordt je hele muziekmap opnieuw geschud en
hernummerd.

---

## Luidheid gelijktrekken (loudnorm)

Er staat een tweede programma in deze map: **Luidheid Normaliseren**. Dat haalt
de verschillen in volume uit een map mp3's weg, zodat je collectie overal even
hard klinkt. De nummers blijven hetzelfde, alleen het volume wordt gelijkgetrokken.

```bash
./run-loudnorm.sh
```

Dat is alles wat nodig is: geen browser, geen YouTube, alleen ffmpeg.

### Wat je ervoor nodig hebt

Alleen Python 3.10+ met Tkinter en `ffmpeg`. De Python-pakketten van het
Radio 2-programma zijn hier niet nodig. Controleer het met:

```bash
ffmpeg -version
```

### Zo werkt het

1. **Kies de map** met de knop *Bladeren*. Alleen de bestanden in die map zelf
   worden gebruikt; submappen worden overgeslagen.
2. **Druk op Meten.** Het programma bepaalt van elk bestand de luidheid. Dat
   kost even, maar er wordt nog niets gewijzigd. Je ziet daarna:
   - het kleinste, grootste en gemiddelde niveau;
   - de mediaan, en hoeveel LU het bereik is;
   - een balkgrafiek met de verdeling, en waar het doelniveau ligt;
   - hoeveel bestanden er al echt afgeknipt zijn (piek boven 0 dBFS);
   - een schatting van hoe lang het normaliseren gaat duren.
3. **Kies een doelniveau** en eventueel een andere bitrate. Bij elk niveau staat
   wat de gevolgen zijn; bij -11 LUFS krijgen zachte nummers veel meer
   versterking, en dus ook meer ruis.
4. **Druk op Starten.** De bestanden worden eerst naar een aparte werkmap
   geschreven, daarna gecontroleerd, en pas als alles goed is gaat de nieuwe
   map de oude vervangen.

De meting wordt onthouden in `~/.cache/loudnorm`. Tweede je op Meten voor
dezelfde map, dan is dat meteen klaar.

### Veiligheid

- Er wordt **nooit over de oude map heen geschreven** terwijl er nog gewerkt
  wordt. Het programma werkt in `Mapnaam_genormaliseerd`.
- Na afloop volgt een controle: aantal bestanden, leesbaarheid en afwijkende
  duur. Is er iets mis, dan blijft de oude map ongemoeid en krijg je een foutmelding.
- Standaard staan de originelen daarna in `Mapnaam_origineel`. Die map is pas
  veilig te verwijderen als je het resultaat hebt beluisterd.
- De weergegeven meting wordt ongeldig zodra je de map wijzigt of de map
  opnieuw laat beschrijven. Je moet dan opnieuw meten; anders zou je op
  verouderde cijfers normaliseren.

### De doelniveaus

| Niveau | Wanneer |
|---|---|
| **-14 LUFS** | de standaard van YouTube en Spotify, en vrijwel altijd de mediaan van je collectie |
| -13 LUFS | iets luider, nog gematigd |
| -12 LUFS | ongeveer 2 dB luider dan de standaard |
| **-11 LUFS** | duidelijk hoorbaar boven andere programma's; zachte nummers krijgen veel versterking en dus meer ruis |
| -16 LUFS | de minste versterking nodig, dus de minste ruisversterking; je zet je volume verder op |

### Waarom niet gewoon 192 kbit/s

Een bestaand bestand hoger dan 192 kbit/s "ophogen" levert geen extra kwaliteit
op: het codec-formaat bepaalt wat erin zit. Bij luidheid geldt hetzelfde. Daarom
hercodeert dit programma alles naar 192 kbit/s en rekent het volume gelijk in
dezelfde rondegang. Kies je *behouden*, dan blijft elk bestand op zijn eigen
bitrate.

### Pieken en de grens van 0 dBFS

Een mp3 die te hard gaat, gaat niet alleen te hard, hij gaat ook vervormen. Het
programme houdt daarom de piek onder -1 dBFS en komt nooit boven 0 dBFS. Heeft
een nummer een piek die te dicht tegen dat plafond komt, dan wordt de versterking
iets teruggedraaid. Dat betekent dat zo'n nummer dan op -17 LUFS uitkomt in
plaats van -14, en dus stiller is dan de rest. Dat is een bewuste keuze: een
korte vervorming is storender dan een iets stiller nummer.

Is een nummer in het origineel al afgeknipt (piek boven 0 dBFS), dan is dat
reparatie niet meer mogelijk; de schade zit al in het bestand. Het programma
laat het dan zo rusten en houdt er geen nieuwe schade bovenop.

### Stoppen

Tijdens meten of normaliseren kun je op Stoppen drukken. Het lopende bestand
wordt afgemaakt. Start je daarna opnieuw, dan gaat het verder waar je was:
klaargezette bestanden in de werkmap worden hergebruikt en alleen de ontbrekende
worden nog gemaakt.

---

## Projectstructuur

```
radio2/                 het Radio 2-programma
├── __main__.py     startpunt
├── check.py        installatiecontrole
├── gui.py          de GUI
├── pipeline.py     de werkgang en volgorde van de stappen
├── scraper.py      hitnoteringen.be scrapen + hitslijst
├── downloader.py   yt-dlp, met cookies en JS-runtime
├── converter.py    ffmpeg naar mp3 + ID3-tags
├── organizer.py    dedupe, verplaatsen, shufflen, hernummeren
├── browsers.py     browser- en standaardbrowserdetectie
├── settings.py     instellingen onthouden tussen sessies
├── config.py       constanten en instellingen
└── utils.py        bestandsnamen, normalisatie, prefixbreedte

loudnorm/               het luidheidprogramma
├── __main__.py     startpunt
├── core.py         meten, normaliseren, controleren, omschrijven
└── gui.py          de GUI
```

## Licentie

GPL-3.0 — zie [LICENSE](LICENSE).

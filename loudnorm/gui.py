"""GUI voor het gelijktrekken van de luidheid van een map mp3's."""

from __future__ import annotations

import os
import queue
import shutil
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import core

# ----------------------------------------------------------------------
# Kleurenpalet, bewust hetzelfde als bij de Radio 2-app
# ----------------------------------------------------------------------
BG = "#14161a"
PANEL = "#1c1f26"
PANEL_ALT = "#23262f"
FIELD = "#2a2e38"
BORDER = "#343945"
TEXT = "#e8eaed"
MUTED = "#9aa0ac"
FAINT = "#6d7480"
ACCENT = "#cd0828"
SUCCESS = "#3ddc84"
LOG_BG = "#0f1115"
LOG_TEXT = "#c8cdd6"
DANGER = "#8b1a2b"
DISABLED_BG = "#3a3f4a"
DISABLED_FG = "#6d7480"
WARN = "#e8a33d"

FONT_STACK = ("Inter", "Segoe UI", "SF Pro Display", "Ubuntu", "DejaVu Sans", "Helvetica")

TITEL = "Luidheid Normaliseren"

#: Doelniveaus met uitleg, in plaats van kale getallen.
NIVEAUS = [
    ("-14 LUFS  (aanbevolen)", -14.0,
     "De standaard van YouTube en Spotify, en vrijwel altijd de mediaan van je collectie."),
    ("-13 LUFS", -13.0, "Iets luider dan de standaard, nog steeds gematigd."),
    ("-12 LUFS", -12.0, "Ongeveer 2 dB luider dan de standaard."),
    ("-11 LUFS  (luid)", -11.0, "Duidelijk hoorbaar boven andere programma's; zachte nummers krijgen meer versterking en dus meer ruis."),
    ("-16 LUFS  (rustig)", -16.0, "De minste versterking nodig, dus de minste ruisversterking. Je moet je volume verder opzetten."),
]

#: Bitrates; None betekent: per bestand de oorspronkelijke bitrate aanhouden.
BITRATES = [
    ("192k  (aanbevolen)", "192k"),
    ("128k  (kleinste bestanden)", "128k"),
    ("256k  (ruim)", "256k"),
    ("320k  (grootste bestanden)", "320k"),
    ("behouden", None),
]


def pick_font(root: tk.Misc) -> str:
    beschikbaar = set(tkfont.families(root))
    for naam in FONT_STACK:
        if naam in beschikbaar:
            return naam
    return "TkDefaultFont"


def lighten(kleur: str, hoeveel: int = 22) -> str:
    waarde = kleur.lstrip("#")
    kanalen = [int(waarde[i:i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(min(255, k + hoeveel) for k in kanalen)


def suggested_workers() -> int:
    """Een verstandig aantal parallelle ffmpeg-processen."""
    try:
        cpu = len(os.sched_getaffinity(0))
    except AttributeError:
        cpu = os.cpu_count() or 4
    return max(2, min(12, cpu - 2))


def _duur(seconden: float) -> str:
    """Een aantal seconden als '3 uur 20 minuten' of '45 seconden'."""
    seconden = int(round(seconden))
    if seconden < 60:
        return f"{seconden} seconde" if seconden == 1 else f"{seconden} seconden"
    minuten, _ = divmod(seconden, 60)
    if minuten < 60:
        return f"{minuten} minuut" if minuten == 1 else f"{minuten} minuten"
    uren, rest = divmod(minuten, 60)
    if uren < 24:
        if not rest:
            return f"{uren} uur"
        return f"{uren} uur {rest} minuten"
    dagen, uren = divmod(uren, 24)
    dagen_woord = "dag" if dagen == 1 else "dagen"
    if not uren:
        return f"{dagen} {dagen_woord}"
    return f"{dagen} {dagen_woord} {uren} uur"


def _grootte(bytes_: int) -> str:
    """Een aantal bytes leesbaar maken, met de passende eenheid."""
    waarde = float(bytes_)
    for eenheid in ("B", "kB", "MB", "GB", "TB"):
        if waarde < 1000 or eenheid == "TB":
            if eenheid == "B":
                return f"{int(waarde)} {eenheid}"
            return f"{waarde:.1f} {eenheid}"
        waarde /= 1000
    return f"{waarde:.1f} TB"


def muziekmap_voorstellen() -> str:
    """Gok een logische muziekmap, zodat het veld niet leeg begint."""
    huizen = [Path.home() / "Muziek", Path.home() / "Muziek" / "Music",
              Path.home() / "Music", Path.home() / "Mijn Muziek"]
    for kandidaat in huizen:
        if kandidaat.is_dir():
            return str(kandidaat)
    return str(Path.home())


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.family = pick_font(root)

        self._queue: queue.Queue = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._after_id: str | None = None
        self._fase: str = "klaar"          # klaar | meten | normaliseren | afgerond
        self._overzicht: core.Overzicht | None = None
        self._instellingen: core.Instellingen | None = None
        self._bestanden: list[str] = []
        self._schatting: dict = {}
        # Waar de zichtbare meting bij hoort. Verandert er iets aan de map of
        # aan de bestanden zelf, dan is de meting niet meer geldig.
        self._gemeten_map: Path | None = None
        self._gemeten_mtime: float = 0.0

        self.map_var = tk.StringVar(value=muziekmap_voorstellen())
        self.niveau_var = tk.StringVar(value=NIVEAUS[0][0])
        self.bitrate_var = tk.StringVar(value=BITRATES[0][0])
        self.backup_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Gereed")
        self.samenvatting_var = tk.StringVar(
            value="Kies een map en druk op Meten om te zien hoeveel de luidheid "
                  "uiteenloopt.")
        self.voortgang_var = tk.DoubleVar(value=0.0)

        self._build_window()
        self._build_styles()
        self._build_ui()
        self._controleer_omgeving()

        # Een andere map betekent: de zichtbare meting hoort daar niet meer bij.
        self.map_var.trace_add("write", self._map_gewijzigd)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._after_id = self.root.after(80, self._drain)
        self._werkknoppen()

    # ------------------------------------------------------------------
    # Venster en stijlen
    # ------------------------------------------------------------------
    def _build_window(self) -> None:
        self.root.title(TITEL)
        self.root.configure(bg=BG)
        self.root.minsize(900, 780)
        self.root.geometry("980x900")

    def _build_styles(self) -> None:
        stijl = ttk.Style(self.root)
        stijl.theme_use("clam")

        stijl.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                        bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER,
                        insertcolor=TEXT, borderwidth=1, relief="solid",
                        padding=(10, 8))
        stijl.map("TEntry", bordercolor=[("focus", ACCENT)],
                  lightcolor=[("focus", ACCENT)])

        stijl.configure("TCombobox", fieldbackground=FIELD, background=FIELD,
                        foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, borderwidth=1,
                        relief="solid", padding=(10, 7))
        stijl.map("TCombobox",
                  fieldbackground=[("readonly", FIELD), ("disabled", DISABLED_BG)],
                  foreground=[("readonly", TEXT), ("disabled", DISABLED_FG)],
                  bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  arrowcolor=[("disabled", DISABLED_FG)])
        stijl.configure("Opt.TCombobox", fieldbackground=FIELD, background=FIELD,
                        foreground=TEXT, arrowcolor=MUTED, bordercolor=BORDER,
                        lightcolor=BORDER, darkcolor=BORDER, borderwidth=1,
                        relief="solid", padding=(10, 7))
        stijl.map("Opt.TCombobox",
                  fieldbackground=[("readonly", FIELD), ("disabled", DISABLED_BG)],
                  foreground=[("readonly", TEXT), ("disabled", DISABLED_FG)],
                  bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)],
                  arrowcolor=[("disabled", DISABLED_FG)])

        stijl.configure("Opt.Horizontal.TProgressbar", troughcolor=FIELD,
                        background=ACCENT, bordercolor=FIELD, lightcolor=ACCENT,
                        darkcolor=ACCENT, thickness=8)

        stijl.configure("Opt.TCheckbutton", background=PANEL, foreground=TEXT,
                        focuscolor=PANEL, font=(self.family, 10))
        stijl.map("Opt.TCheckbutton",
                  background=[("active", PANEL)], foreground=[("disabled", FAINT)],
                  indicatorcolor=[("selected", ACCENT), ("!selected", FIELD)])

    # ------------------------------------------------------------------
    # Opbouw
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(4, weight=1)

        self._build_header()
        self._build_map()
        self._build_meting()
        self._build_opties()
        self._build_uitvoer()
        self._build_voettekst()

    def _build_header(self) -> None:
        kop = tk.Frame(self.root, bg=BG)
        kop.grid(row=0, column=0, sticky="ew", padx=26, pady=(22, 14))

        tk.Label(kop, text=TITEL, bg=BG, fg=TEXT,
                 font=(self.family, 21, "bold")).pack(side="left")
        tk.Label(kop,
                 text="Trek de luidheid van je mp3's gelijk, zonder de kwaliteit te verliezen.",
                 bg=BG, fg=MUTED, font=(self.family, 10)).pack(side="left", padx=(16, 0))

        self.badge = tk.Label(kop, text="Gereed", bg=PANEL_ALT, fg=MUTED,
                              font=(self.family, 9, "bold"), padx=12, pady=5)
        self.badge.pack(side="right")

    def _build_map(self) -> None:
        paneel = self._paneel(self.root, 1)
        binnen = tk.Frame(paneel, bg=PANEL)
        binnen.grid(row=0, column=0, sticky="ew", padx=22, pady=18)
        binnen.grid_columnconfigure(0, weight=1)

        self._label(binnen, "MAP MET MP3-BESTANDEN", 0, 0, 0)
        self.map_veld = ttk.Entry(binnen, textvariable=self.map_var,
                                  font=(self.family, 11))
        self.map_veld.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.blader_knop = self._knop(binnen, "Bladeren", self._kies_map,
                                      secondary=True)
        self.blader_knop.grid(row=1, column=1, padx=(10, 0), pady=(6, 0))

        self.hint = tk.Label(
            binnen,
            text="Alleen de bestanden in deze map zelf; submappen worden overgeslagen.",
            bg=PANEL, fg=FAINT, font=(self.family, 8), anchor="w")
        self.hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _build_meting(self) -> None:
        paneel = self._paneel(self.root, 2)
        paneel.grid_rowconfigure(1, weight=1)
        binnen = tk.Frame(paneel, bg=PANEL)
        binnen.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 14))
        binnen.grid_columnconfigure(0, weight=1)
        binnen.grid_columnconfigure(1, weight=1)

        kopregel = tk.Frame(binnen, bg=PANEL)
        kopregel.grid(row=0, column=0, columnspan=2, sticky="ew")
        tk.Label(kopregel, text="METING", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).pack(side="left")
        self.meet_knop = self._knop(kopregel, "Meten", self._start_meten,
                                    secondary=True)
        self.meet_knop.pack(side="right")

        self.samenvatting = tk.Label(
            binnen, textvariable=self.samenvatting_var, bg=PANEL, fg=MUTED,
            font=(self.family, 10), anchor="w", justify="left")
        self.samenvatting.grid(row=1, column=0, sticky="nw", pady=(10, 0))

        self.grafiek = tk.Canvas(binnen, height=104, bg=PANEL_ALT,
                                 highlightthickness=0, bd=0)
        self.grafiek.grid(row=1, column=1, sticky="nsew", padx=(22, 0), pady=(10, 0))

    def _build_opties(self) -> None:
        paneel = self._paneel(self.root, 3)
        binnen = tk.Frame(paneel, bg=PANEL)
        binnen.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 16))
        binnen.grid_columnconfigure(1, weight=1)
        binnen.grid_columnconfigure(3, weight=1)

        self._label(binnen, "DOELNIVEAU", 0, 0, 0)
        self.niveau_combo = ttk.Combobox(
            binnen, textvariable=self.niveau_var, state="readonly",
            values=[n[0] for n in NIVEAUS], font=(self.family, 10),
            style="Opt.TCombobox", width=26)
        self.niveau_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.niveau_combo.bind("<<ComboboxSelected>>", lambda _e: self._niveau_gewijzigd())

        self._label(binnen, "BITRATE", 0, 2, 20)
        self.bitrate_combo = ttk.Combobox(
            binnen, textvariable=self.bitrate_var, state="readonly",
            values=[b[0] for b in BITRATES], font=(self.family, 10),
            style="Opt.TCombobox", width=22)
        self.bitrate_combo.grid(row=1, column=2, columnspan=2, sticky="ew",
                                padx=(20, 0), pady=(6, 0))

        self.niveau_hint = tk.Label(binnen, text=NIVEAUS[0][2], bg=PANEL, fg=FAINT,
                                    font=(self.family, 8), anchor="w", justify="left",
                                    wraplength=430)
        self.niveau_hint.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

        self.keuze_hint = tk.Label(binnen, text="", bg=PANEL, fg=FAINT,
                                   font=(self.family, 8), anchor="w", justify="left",
                                   wraplength=430)
        self.keuze_hint.grid(row=2, column=2, columnspan=2, sticky="w",
                             padx=(20, 0), pady=(8, 0))

        self.backup_check = ttk.Checkbutton(
            binnen, text="Originelen bewaren als back-up na afloop",
            variable=self.backup_var, style="Opt.TCheckbutton")
        self.backup_check.grid(row=3, column=0, columnspan=4, sticky="w",
                               pady=(14, 0))

    def _build_uitvoer(self) -> None:
        paneel = self._paneel(self.root, 4)
        paneel.grid_rowconfigure(3, weight=1)
        paneel.grid_columnconfigure(0, weight=1)

        kopregel = tk.Frame(paneel, bg=PANEL)
        kopregel.grid(row=0, column=0, columnspan=2, sticky="ew", padx=22,
                       pady=(16, 0))
        tk.Label(kopregel, text="UITVOER", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).pack(side="left")
        self.status_label = tk.Label(kopregel, textvariable=self.status_var, bg=PANEL,
                                     fg=MUTED, font=(self.family, 9))
        self.status_label.pack(side="right")

        self.voortgang = ttk.Progressbar(
            paneel, variable=self.voortgang_var, maximum=100.0,
            style="Opt.Horizontal.TProgressbar")
        self.voortgang.grid(row=1, column=0, columnspan=2, sticky="ew",
                            padx=22, pady=(10, 12))

        self.log_veld = ScrolledText(paneel, wrap="word", height=12,
                                     bg=LOG_BG, fg=LOG_TEXT, bd=0,
                                     insertbackground=TEXT, padx=12, pady=10,
                                     font=("DejaVu Sans Mono", 9),
                                     state="disabled", relief="flat")
        self.log_veld.grid(row=3, column=0, sticky="nsew", padx=22, pady=(0, 18))
        self.log_veld.tag_configure("fout", foreground=DANGER)
        self.log_veld.tag_configure("waarschuwing", foreground=WARN)
        self.log_veld.tag_configure("goed", foreground=SUCCESS)
        self.log_veld.tag_configure("kop", foreground=TEXT, font=("DejaVu Sans Mono", 9, "bold"))

    def _build_voettekst(self) -> None:
        voet = tk.Frame(self.root, bg=BG)
        voet.grid(row=5, column=0, sticky="ew", padx=26, pady=(16, 22))

        self.stop_knop = self._knop(voet, "■  Stoppen", self._stoppen, danger=True)
        self.stop_knop.pack(side="right")
        self.start_knop = self._knop(voet, "▶  Starten", self._starten)
        self.start_knop.pack(side="right", padx=(0, 10))

        self.voettekst = tk.Label(voet, text="", bg=BG, fg=FAINT,
                                  font=(self.family, 8), anchor="w")
        self.voettekst.pack(side="left")

    # ------------------------------------------------------------------
    # Kleine bouwstenen
    # ------------------------------------------------------------------
    def _paneel(self, ouder: tk.Widget, rij: int) -> tk.Frame:
        paneel = tk.Frame(ouder, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1)
        paneel.grid(row=rij, column=0, sticky="ew", padx=26, pady=(0, 14))
        paneel.grid_columnconfigure(0, weight=1)
        return paneel

    def _label(self, ouder: tk.Widget, tekst: str, rij: int, kolom: int,
               padx: int = 0) -> None:
        tk.Label(ouder, text=tekst, bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).grid(
            row=rij, column=kolom, sticky="w", padx=(padx, 0))

    def _knop(self, ouder: tk.Widget, tekst: str, commando, *,
              secondary: bool = False, danger: bool = False) -> tk.Button:
        achtergrond = ACCENT
        voorgrond = "#ffffff"
        if secondary:
            achtergrond = FIELD
            voorgrond = TEXT
        elif danger:
            achtergrond = DANGER
        knop = tk.Button(
            ouder, text=tekst, command=commando, bg=achtergrond, fg=voorgrond,
            activebackground=lighten(achtergrond), activeforeground=voorgrond,
            font=(self.family, 10, "bold"), relief="flat", bd=0, padx=18, pady=9,
            cursor="hand2", highlightthickness=0)
        knop.bind("<Enter>", lambda _e, k=knop: k.configure(
            bg=lighten(achtergrond)))
        knop.bind("<Leave>", lambda _e, k=knop, c=achtergrond: k.configure(bg=c))
        return knop

    # ------------------------------------------------------------------
    # Logboek en voortgang
    # ------------------------------------------------------------------
    def log(self, tekst: str, tag: str = "") -> None:
        self._queue.put(("log", (tekst, tag)))

    def _append(self, tekst: str, tag: str = "") -> None:
        self.log_veld.configure(state="normal")
        self.log_veld.insert("end", tekst + "\n", tag)
        self.log_veld.see("end")
        self.log_veld.configure(state="disabled")

    def _werkknoppen(self) -> None:
        bezig = self._thread is not None and self._thread.is_alive()
        self.start_knop.configure(
            state="disabled" if bezig else "normal",
            bg=DISABLED_BG if bezig else ACCENT,
            fg=DISABLED_FG if bezig else "#ffffff", cursor="" if bezig else "hand2")
        self.stop_knop.configure(
            state="normal" if bezig else "disabled",
            bg=DANGER if bezig else DISABLED_BG,
            fg="#ffffff" if bezig else DISABLED_FG, cursor="hand2" if bezig else "")
        self.meet_knop.configure(
            state="disabled" if bezig else "normal",
            bg=DISABLED_BG if bezig else FIELD,
            fg=DISABLED_FG if bezig else TEXT, cursor="" if bezig else "hand2")
        self.blader_knop.configure(
            state="disabled" if bezig else "normal",
            bg=DISABLED_BG if bezig else FIELD,
            fg=DISABLED_FG if bezig else TEXT, cursor="" if bezig else "hand2")
        for widget in (self.niveau_combo, self.bitrate_combo, self.backup_check):
            widget.configure(state="disabled" if bezig else ("readonly"
                             if isinstance(widget, ttk.Combobox) else "normal"))
        self.map_veld.configure(state="disabled" if bezig else "normal")

    def _drain(self) -> None:
        self._after_id = self.root.after(80, self._drain)
        klaar_met_werk = False
        while True:
            try:
                soort, payload = self._queue.get_nowait()
            except queue.Empty:
                break
            if soort == "log":
                self._append(payload[0], payload[1])
            elif soort == "voortgang":
                deel, totaal, tekst = payload
                if totaal:
                    self.voortgang_var.set(100.0 * deel / totaal)
                if tekst:
                    self.status_var.set(tekst)
            elif soort == "fase":
                self._fase = payload
                self._badge()
            elif soort == "samenvatting":
                self._toon_samenvatting(payload)
            elif soort == "klaar":
                self._thread = None
                klaar_met_werk = True
            elif soort == "uitkomst":
                self._toon_uitkomst(payload)
            elif soort == "map_veranderd":
                # Na de wissel klopt de meting niet meer: de map bevat nu
                # andere bestanden dan toen er gemeten is.
                self._gemeten_map = None
                self._gemeten_mtime = 0.0
                self._overzicht = None
                self._werkknoppen()
        if klaar_met_werk:
            self._werkknoppen()
            self._badge()

    def _badge(self) -> None:
        teksten = {
            "klaar": ("Gereed", MUTED),
            "meten": ("Bezig met meten", WARN),
            "normaliseren": ("Bezig", WARN),
            "afgerond": ("Klaar", SUCCESS),
            "gestopt": ("Gestopt", DANGER),
        }
        tekst, kleur = teksten.get(self._fase, ("", MUTED))
        self.badge.configure(text=tekst, fg=kleur)

    # ------------------------------------------------------------------
    # Map kiezen
    # ------------------------------------------------------------------
    def _kies_map(self) -> None:
        start = self.map_var.get().strip() or str(Path.home())
        gekozen = filedialog.askdirectory(
            parent=self.root, title="Kies de map met mp3-bestanden",
            initialdir=start if os.path.isdir(start) else str(Path.home()),
            mustexist=True)
        if gekozen:
            self.map_var.set(gekozen)
            self._reset_meting()

    def _reset_meting(self) -> None:
        self._overzicht = None
        self._bestanden = []
        self._schatting = {}
        self._gemeten_map = None
        self._gemeten_mtime = 0.0
        self.voortgang_var.set(0.0)
        self.samenvatting_var.set(
            "Druk op Meten om te zien hoeveel de luidheid in deze map uiteenloopt.")
        self._wis_grafiek()
        self._werkknoppen()

    def _meting_geldig(self) -> bool:
        """Klopt de zichtbare meting nog bij de huidige inhoud van de map?

        Er zijn drie manieren waarop de meting achterloopt: een andere map is
        gekozen, er zijn bestanden bijgekomen of verdwenen, of een bestand is
        herschreven. In alle drie de gevallen moet opnieuw gemeten worden.
        """
        if self._overzicht is None or self._gemeten_map is None:
            return False
        if self._gemeten_map != Path(self.map_var.get().strip()):
            return False
        try:
            huidig = core.scan(self._gemeten_map)
        except core.Fout:
            return False
        if huidig != self._bestanden:
            return False
        return core.nieuwste_wijziging(self._gemeten_map,
                                       self._bestanden) == self._gemeten_mtime

    def _map_gewijzigd(self, *_args) -> None:
        """Het tekstveld toont een andere map dan die gemeten is."""
        if self._gemeten_map is None:
            return
        if Path(self.map_var.get().strip()) == self._gemeten_map:
            return
        if self._overzicht is not None and not (
                self._thread is not None and self._thread.is_alive()):
            self._reset_meting()

    def _wis_grafiek(self) -> None:
        self.grafiek.delete("all")
        self.grafiek.create_text(2, 52, text="meting verschijnt hier", anchor="w",
                                 fill=FAINT, font=(self.family, 9))

    # ------------------------------------------------------------------
    # Meten
    # ------------------------------------------------------------------
    def _controleer_omgeving(self) -> None:
        ontbreekt = core.controleer_omgeving()
        self._wis_grafiek()
        if ontbreekt:
            self.samenvatting_var.set(
                "Er ontbreekt software: " + ", ".join(ontbreekt) + ". Installeer ffmpeg.")
            self.log(f"[x] Ontbreekt: {', '.join(ontbreekt)}", "fout")
            self.start_knop.configure(state="disabled", bg=DISABLED_BG, fg=DISABLED_FG)
            self.meet_knop.configure(state="disabled", bg=DISABLED_BG, fg=DISABLED_FG)
        else:
            self.log(f"ffmpeg gevonden: {shutil.which('ffmpeg')}", "goed")
            self.log(f"Parallelle processen: {suggested_workers()}")

    def _start_meten(self, _gebruik_cache: bool = True) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        pad = self.map_var.get().strip()
        map_ = Path(pad)
        try:
            bestanden = core.scan(map_)
        except core.Fout as fout:
            messagebox.showerror("Map", str(fout), parent=self.root)
            return
        if not bestanden:
            messagebox.showwarning(
                "Map", "In deze map staan geen mp3-bestanden.", parent=self.root)
            return
        self._bestanden = bestanden
        doel = self._huidig_doel() or -14.0

        if _gebruik_cache:
            bewaard = core.Overzicht.laad_meting(map_, bestanden, doel)
            if bewaard is not None:
                self.log("")
                self.log(f"Opgeslagen meting hergebruikt: {len(bewaard.bestanden)} "
                         "bestanden (niets opnieuw gedecodeerd).", "goed")
                self._toon_samenvatting(bewaard)
                self._werkknoppen()
                return

        submappen = core.tel_submappen(map_)
        self._stop.clear()
        self._fase = "meten"
        self._badge()
        self._werkknoppen()
        self.log("")
        self.log(f"Meten van {len(bestanden)} bestanden in {pad}", "kop")
        if submappen:
            self.log(f"[!] {submappen} submap/map met mp3's wordt overgeslagen.",
                     "waarschuwing")

        def voortgang(deel: int, totaal: int, tekst: str) -> None:
            self._queue.put(("voortgang", (deel, totaal, tekst)))

        def schrijf(tekst: str, tag: str = "") -> None:
            # alleen de wachtrij; de GUI raakt dit vanuit _drain()
            self._queue.put(("log", (tekst, tag)))

        def draai() -> None:
            overzicht = core.meet(map_, bestanden, suggested_workers(),
                                 self._stop, voortgang)
            if self._stop.is_set():
                self._queue.put(("fase", "gestopt"))
                schrijf("[…] Meten afgebroken.", "waarschuwing")
                self._queue.put(("klaar", None))
                return
            if not overzicht.bestanden:
                schrijf("[x] Geen enkel bestand kon worden gemeten.", "fout")
                self._queue.put(("fase", "gestopt"))
                self._queue.put(("klaar", None))
                return
            overzicht.bewaar_meting(map_, bestanden)
            self._queue.put(("samenvatting", overzicht))
            self._queue.put(("fase", "klaar"))
            self._queue.put(("klaar", None))

        self._thread = threading.Thread(target=draai, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------
    # Meting tonen
    # ------------------------------------------------------------------
    def _toon_samenvatting(self, overzicht: core.Overzicht) -> None:
        self._overzicht = overzicht
        map_ = Path(self.map_var.get().strip())
        self._gemeten_map = map_
        self._gemeten_mtime = core.nieuwste_wijziging(map_, self._bestanden)
        l = sorted(m.lufs for m in overzicht.bestanden)
        laagst, mediaan, hoogst = l[0], l[len(l) // 2], l[-1]
        spreiding = hoogst - laagst
        knip = [m for m in overzicht.bestanden if m.tp >= 0]

        kleur = WARN if spreiding > 6 else SUCCESS
        self.samenvatting_var.set(
            f"{len(l)} bestanden   ·   {laagst:.1f} tot {hoogst:.1f} LUFS   ·   "
            f"verschil {spreiding:.1f} LU   ·   mediaan {mediaan:.1f}")
        self.samenvatting.configure(fg=kleur)

        self._teken_grafiek(l)
        self._niveau_gewijzigd()

        if spreiding <= 0.5:
            self.log("[i] De luidheid loopt nauwelijks uiteen; normaliseren "
                     "heeft weinig effect.", "waarschuwing")
        else:
            self.log(f"De luidheid loopt {spreiding:.1f} LU uiteen "
                     f"({laagst:.1f} tot {hoogst:.1f} LUFS).", "kop")
        if knip:
            self.log(f"[!] {len(knip)} bestanden hebben al een piek boven 0 dBFS "
                     f"en zijn dus al echt afgeknipt in het origineel.", "waarschuwing")

        duur = sum(m.duur for m in overzicht.bestanden)
        schatting = core.schatting(overzicht, suggested_workers())
        self.log(f"Totale afspeeltijd: {_duur(duur)}", "kop")

        minuten = schatting["norm_minuten"]  # schatting is de dict hierboven
        if minuten < 1:
            tijdstekst = "minder dan een minuut"
        elif minuten < 90:
            aantal = int(round(minuten))
            tijdstekst = (f"ongeveer {aantal} minuut" if aantal == 1
                          else f"ongeveer {aantal} minuten")
        else:
            tijdstekst = f"ongeveer {minuten / 60:.1f} uur"
        self.voettekst.configure(
            text=f"{len(l)} bestanden, {_duur(schatting['uren'] * 3600)} muziek  ·  "
                 f"normaliseren duurt {tijdstekst}")
        self._schatting = schatting

    def _teken_grafiek(self, waarden: list[float]) -> None:
        self.grafiek.delete("all")
        breedte = max(1, self.grafiek.winfo_width() or 360)
        hoogte = 104
        marge = 8

        laag = min(-32.0, (min(waarden) - 2) // 2 * 2)
        hoog = max(-4.0, (max(waarden) + 2) // 2 * 2)
        stappen = 2.0
        emmers: dict[int, int] = {}
        for w in waarden:
            emmer = int((w - laag) // stappen)
            emmers[emmer] = emmers.get(emmer, 0) + 1
        maximum = max(emmers.values()) or 1

        aantal = max(1, int((hoog - laag) / stappen))
        slot_breedte = (breedte - marge * 2) / aantal

        for i in range(aantal):
            onder = laag + i * stappen
            teller = emmers.get(i, 0)
            if teller:
                staaf_hoogte = (hoogte - 26) * teller / maximum
                x0 = marge + i * slot_breedte + 1
                self.grafiek.create_rectangle(
                    x0, hoogte - 16 - staaf_hoogte,
                    x0 + max(1, slot_breedte - 2), hoogte - 16,
                    fill=ACCENT, outline="")
            if i % 4 == 0:
                self.grafiek.create_text(
                    marge + i * slot_breedte, hoogte - 12, text=f"{int(onder)}",
                    anchor="nw", fill=FAINT, font=(self.family, 7))

        # De overige doelniveaus als lichte streep, zodat je ziet waar ze
        # liggen; alleen het gekozen niveau krijgt een label.
        gekozen = self._huidig_doel()
        for doel in self._mogelijke_doelen():
            if not laag <= doel <= hoog or doel == gekozen:
                continue
            y = hoogte - 16 - (hoogte - 26) * (doel - laag) / (hoog - laag)
            self.grafiek.create_line(marge, y, breedte - marge - 46, y,
                                     fill=BORDER, dash=(1, 4))
        if gekozen is not None and laag <= gekozen <= hoog:
            y = hoogte - 16 - (hoogte - 26) * (gekozen - laag) / (hoog - laag)
            self.grafiek.create_line(marge, y, breedte - marge, y,
                                     fill=SUCCESS, dash=(2, 3))
            self.grafiek.create_text(breedte - marge - 2, y - 2,
                                     text=f"doel {gekozen:.0f}",
                                     anchor="se", fill=SUCCESS, font=(self.family, 7))

        self.grafiek.create_text(4, 4, text="LUFS", anchor="nw", fill=FAINT,
                                 font=(self.family, 7))

    def _mogelijke_doelen(self) -> list[float]:
        return [n[1] for n in NIVEAUS]

    def _niveau_gewijzigd(self) -> None:
        for label, _waarde, uitleg in NIVEAUS:
            if label == self.niveau_var.get():
                self.niveau_hint.configure(text=uitleg)
                break
        if self._overzicht is not None:
            # de doellijn in de grafiek mee laten bewegen
            self._teken_grafiek(sorted(m.lufs for m in self._overzicht.bestanden))
            l = sorted(m.lufs for m in self._overzicht.bestanden)
            mediaan = l[len(l) // 2]
            doel = self._huidig_doel()
            if doel is None:
                return
            verschil = mediaan - doel
            if abs(verschil) < 0.2:
                self.keuze_hint.configure(
                    text=f"De mediaan ({mediaan:.1f} LUFS) ligt vrijwel op dit niveau.",
                    fg=FAINT)
            else:
                # Ligt een bestand onder het doel, dan moet het harder; ligt het
                # erboven, dan moet het zachter. Elk aantal heeft dus zijn eigen
                # richting, los van hoe de mediaan ten opzichte van het doel ligt.
                omhoog = sum(1 for m in self._overzicht.bestanden
                             if m.lufs < doel - 0.2)
                omlaag = sum(1 for m in self._overzicht.bestanden
                             if m.lufs > doel + 0.2)
                self.keuze_hint.configure(
                    text=f"{omhoog} bestanden gaan omhoog, {omlaag} gaan omlaag.",
                    fg=FAINT)

    def _huidig_doel(self) -> float | None:
        for label, waarde, _ in NIVEAUS:
            if label == self.niveau_var.get():
                return waarde
        return None

    def _huidige_bitrate(self) -> str | None:
        for label, waarde in BITRATES:
            if label == self.bitrate_var.get():
                return waarde
        return "192k"

    # ------------------------------------------------------------------
    # Normaliseren
    # ------------------------------------------------------------------
    def _starten(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if self._overzicht is None:
            messagebox.showinfo(
                "Eerst meten",
                "Druk eerst op Meten. Dan zie je hoeveel de luidheid uiteenloopt "
                "en hoe lang het ongeveer duurt.", parent=self.root)
            return
        if not self._meting_geldig():
            messagebox.showwarning(
                "Map is veranderd",
                "De map is sinds de meting veranderd, of er is al een keer "
                "genormaliseerd. Meet opnieuw voordat je start.",
                parent=self.root)
            self._reset_meting()
            return

        doel = self._huidig_doel()
        if doel is None:
            return
        bronmap = Path(self.map_var.get().strip())
        uitvoermap = bronmap.with_name(bronmap.name + "_genormaliseerd")

        if uitvoermap.exists():
            opnieuw = messagebox.askyesno(
                "Werkmap bestaat al",
                f"{uitvoermap.name} bestaat al.\n\n"
                "Ja: die map wordt verwijderd en alles wordt opnieuw herschreven.\n"
                "Nee: bestanden die daar al klaarstaan worden hergebruikt, de "
                "rest wordt alsnog gemaakt. Dat is handig na een stop.",
                parent=self.root)
            if opnieuw:
                shutil.rmtree(uitvoermap)
            else:
                klaar = sum(1 for _ in uitvoermap.glob("*.mp3"))
                self.log(f"{klaar} bestanden in de werkmap worden hergebruikt.")

        instellingen = core.Instellingen(
            bronmap=bronmap, doel=doel, bitrate=self._huidige_bitrate(),
            workers=suggested_workers(), doelmap=uitvoermap,
            back_up=self.backup_var.get())
        self._instellingen = instellingen

        overzicht = self._overzicht
        # Alles wat de werkthread nodig heeft, nu vastleggen. Tk-variabelen
        # mogen daar niet meer vanuit de achtergronddraad worden gelezen.
        back_up = instellingen.back_up
        bitrate_tekst = self._huidige_bitrate() or "behouden"
        bestandsnamen = [m.bestand for m in overzicht.bestanden]

        self._stop.clear()
        self._fase = "normaliseren"
        self._badge()
        self._werkknoppen()
        self.log("")
        self.log(f"Normaliseren naar {doel:.0f} LUFS, bitrate {bitrate_tekst}", "kop")
        self.log(f"Werkmap: {uitvoermap.name}", "kop")

        def voortgang(deel: int, totaal: int, tekst: str) -> None:
            self._queue.put(("voortgang", (deel, totaal, tekst)))

        def schrijf(tekst: str, tag: str = "") -> None:
            # alleen de wachtrij; de GUI raakt dit vanuit _drain()
            self._queue.put(("log", (tekst, tag)))

        def draai() -> None:
            kern = core.normaliseer(instellingen, overzicht, self._stop, voortgang)
            if self._stop.is_set():
                self._queue.put(("fase", "gestopt"))
                schrijf("[…] Gestopt. Opnieuw starten gaat verder waar je was.",
                        "waarschuwing")
                self._queue.put(("klaar", None))
                return
            schrijf("")
            schrijf(f"Klaar met herschrijven: {len(kern.resultaten)} bestanden, "
                    f"{kern.mislukt} mislukt.", "kop")
            schrijf("Controleren…")
            rapport = core.controleer_resultaat(bronmap, uitvoermap, bestandsnamen)
            for tekst, tag in self._rapport_regels(rapport):
                schrijf(tekst, tag)

            if rapport["ontbreekt"] or rapport["onleesbaar"] or kern.mislukt:
                schrijf("[!] De controle is niet volledig schoon; de oude map is "
                        "ongewijzigd gelaten.", "fout")
                self._queue.put(("fase", "gestopt"))
                self._queue.put(("klaar", None))
                return

            if not back_up:
                schrijf("[!] Je hebt gekozen voor geen back-up; de originelen "
                        "worden overschreven.", "waarschuwing")
            schrijf("Omschrijven…")
            # De meting beschreef de oude bestanden; na de wissel is hij
            # niet meer geldig, dus weggooien.
            core.wis_cache(bronmap)
            uitkomst = core.wissel(bronmap, uitvoermap, back_up, schrijf)
            schrijf(f"De map {bronmap.name} is nu de genormaliseerde versie.",
                    "goed")
            if uitkomst["reserve"]:
                schrijf(f"De originelen staan in {uitkomst['reserve'].name}. "
                        "Verwijder die map als je tevreden bent.", "goed")
            self._queue.put(("uitkomst", kern.statistieken(instellingen)))
            self._queue.put(("map_veranderd", None))
            self._queue.put(("fase", "afgerond"))
            self._queue.put(("klaar", None))

        self._thread = threading.Thread(target=draai, daemon=True)
        self._thread.start()

    def _rapport_regels(self, rapport: dict) -> list[tuple[str, str]]:
        """Het controleverslag als (tekst, kleur) -paren, zonder GUI-aanroepen."""
        regels: list[tuple[str, str]] = []
        regels.append((
            f"  aantal: {rapport['aantal_nieuw']} van {rapport['aantal_bron']}",
            "fout" if rapport["ontbreekt"] else "goed"))
        for sleutel, tekst in (("ontbreekt", "ontbreekt in de nieuwe map"),
                               ("onleesbaar", "niet leesbaar"),
                               ("afwijkende_duur", "afwijkende duur"),
                               ("extra", "onverwacht extra bestand")):
            if rapport[sleutel]:
                regels.append((f"  {tekst}: {len(rapport[sleutel])}", "fout"))
                for naam in rapport[sleutel][:5]:
                    regels.append((f"    {naam}", "fout"))
        oud = _grootte(rapport["grootte_bron"])
        nieuw = _grootte(rapport["grootte_nieuw"])
        verschil = rapport["grootte_nieuw"] - rapport["grootte_bron"]
        teken = "+" if verschil >= 0 else "-"
        regels.append((f"  grootte: {oud} -> {nieuw} "
                       f"({teken}{_grootte(abs(verschil))})", ""))
        return regels

    def _toon_uitkomst(self, s: dict) -> None:
        self.samenvatting_var.set(
            f"Klaar  ·  {s['aantal']} bestanden  ·  mediaan "
            f"{s['lufs_mediaan']:.1f} LUFS  ·  piek max {s['tp_max']:.1f} dBFS")
        self.samenvatting.configure(fg=SUCCESS)
        self.log("")
        self.log("Uitkomst", "kop")
        self.log(f"  luidheid   : {s['lufs_min']:.1f} tot {s['lufs_max']:.1f} LUFS, "
                 f"mediaan {s['lufs_mediaan']:.1f}")
        self.log(f"  op doel    : {s['binnen_tolerante']} van {s['aantal']} "
                 f"binnen 0,5 LU", "goed")
        self.log(f"  geklemd    : {s['geklemd']} bestanden")
        self.log(f"  boven -1 dB: {s['over_plafond']} (max {s['tp_max']:.2f} dBFS)",
                 "goed" if s["over_plafond"] == 0 else "waarschuwing")
        self.log(f"  afgeknipt  : {s['knip']}", "goed" if s["knip"] == 0 else "fout")
        self._wis_grafiek_na_afloop(s)

    def _wis_grafiek_na_afloop(self, s: dict) -> None:
        self.grafiek.delete("all")
        breedte = max(1, self.grafiek.winfo_width() or 360)
        hoogte = 104
        lo = s["lufs_min"] - 1
        hi = s["lufs_max"] + 1
        if hi - lo < 1:
            hi = lo + 1
        doel = self._huidig_doel() or -14.0
        y = hoogte - 16 - (hoogte - 26) * (doel - lo) / (hi - lo)
        self.grafiek.create_rectangle(8, 16, breedte - 8, hoogte - 16,
                                      fill="#2a2e38", outline="")
        self.grafiek.create_line(8, y, breedte - 8, y, fill=SUCCESS, dash=(2, 3))
        self.grafiek.create_text(4, 4, text="LUFS  (na afloop)", anchor="nw",
                                 fill=FAINT, font=(self.family, 7))
        self.grafiek.create_text(breedte - 4, y - 4, text=f"doel {doel:.0f}",
                                 anchor="se", fill=SUCCESS, font=(self.family, 8, "bold"))

    # ------------------------------------------------------------------
    # Stoppen en sluiten
    # ------------------------------------------------------------------
    def _stoppen(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        self._stop.set()
        self.status_var.set("Stoppen…")
        self.stop_knop.configure(state="disabled", bg=DISABLED_BG, fg=DISABLED_FG,
                                 cursor="")
        self.log("[…] Stoppen aangevraagd; het lopende bestand wordt afgemaakt.",
                 "waarschuwing")

    def _on_close(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            if not messagebox.askyesno(
                    "Afsluiten", "Het programma is nog bezig. Stoppen en afsluiten?",
                    parent=self.root):
                return
            self._stop.set()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0

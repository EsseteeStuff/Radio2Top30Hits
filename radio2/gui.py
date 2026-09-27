"""Moderne Tkinter-GUI voor Radio 2 Top 30 Hits."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from . import browsers, config, settings
from .pipeline import Pipeline

# ----------------------------------------------------------------------
# Kleurenpalet
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

FONT_STACK = ("Inter", "Segoe UI", "SF Pro Display", "Ubuntu", "DejaVu Sans", "Helvetica")

#: Label van de optie zonder cookies; de bijbehorende sleutel is leeg.
NO_COOKIES = "Geen cookies (anoniem)"


def pick_font(root: tk.Misc) -> str:
    """Beschikbare UI-lettertype uit de lijst kiezen."""
    available = set(tkfont.families(root))
    for name in FONT_STACK:
        if name in available:
            return name
    return "TkDefaultFont"


def lighten(hex_color: str, amount: int = 22) -> str:
    """Een kleur iets lichter maken voor de hover-effecten."""
    value = hex_color.lstrip("#")
    channels = [int(value[i : i + 2], 16) for i in (0, 2, 4)]
    return "#%02x%02x%02x" % tuple(min(255, channel + amount) for channel in channels)


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.family = pick_font(root)
        self._queue: queue.Queue = queue.Queue()
        self._pipeline: Pipeline | None = None
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._settled = False

        self.cfg_workdir = tk.StringVar()
        self.cfg_musicdir = tk.StringVar()
        self.begin_year = tk.StringVar(value="1970")
        self.end_year = tk.StringVar(value="1975")
        self.browser_var = tk.StringVar()
        self.audio_only = tk.BooleanVar(value=True)
        self.bitrate = tk.StringVar(value="192k")
        self.status_text = tk.StringVar(value="Gereed")

        self._value_to_key: dict[str, str] = {}

        self._build_window()
        self._build_styles()
        self._build_ui()
        self._detect_browsers()
        self._load_settings()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._after_id: str | None = self.root.after(80, self._drain)

    # ------------------------------------------------------------------
    # Venster en stijlen
    # ------------------------------------------------------------------
    def _build_window(self) -> None:
        self.root.title(config.APP_TITLE)
        self.root.configure(bg=BG)
        self.root.minsize(880, 680)
        self.root.geometry("960x840")

    def _build_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")

        style.configure(
            "TEntry",
            fieldbackground=FIELD,
            foreground=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            insertcolor=TEXT,
            borderwidth=1,
            relief="solid",
            padding=(10, 8),
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)], lightcolor=[("focus", ACCENT)])

        style.configure(
            "TCombobox",
            fieldbackground=FIELD,
            background=FIELD,
            foreground=TEXT,
            arrowcolor=TEXT,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            borderwidth=1,
            relief="solid",
            padding=(8, 7),
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", TEXT)],
            bordercolor=[("focus", ACCENT)],
            selectbackground=[("readonly", FIELD)],
            selectforeground=[("readonly", TEXT)],
        )
        # De dropdownlijst is geen gewone widget en kleurt anders; dit werkt wel.
        self.root.option_add("*TCombobox*Listbox.background", FIELD)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style.configure("Horizontal.TProgressbar", troughcolor=FIELD, background=ACCENT,
                        bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT, thickness=6)

        # ttk.Checkbutton kent geen font-optie; die hoort in de stijl.
        style.configure("Opt.TCheckbutton", background=PANEL, foreground=TEXT,
                        focuscolor=PANEL, font=(self.family, 9))
        style.map("Opt.TCheckbutton", background=[("active", PANEL)],
                  foreground=[("active", ACCENT)])

    # ------------------------------------------------------------------
    # Opbouw
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill="both", expand=True, padx=26, pady=(20, 18))
        outer.columnconfigure(0, weight=1)
        # Alleen het log-paneel mag groeien; de rest houdt zijn eigen hoogte.
        outer.rowconfigure(3, weight=1)

        self._build_header(outer)
        tk.Frame(outer, bg=BORDER, height=1).grid(
            row=1, column=0, sticky="ew", pady=(14, 16)
        )
        self._build_settings(outer)
        self._build_output(outer)
        self._build_footer(outer)

    def _build_header(self, parent: tk.Widget) -> None:
        header = tk.Frame(parent, bg=BG)
        header.grid(row=0, column=0, sticky="ew")
        header.columnconfigure(0, weight=1)

        tk.Label(
            header, text=config.APP_TITLE, bg=BG, fg=TEXT,
            font=(self.family, 22, "bold"), anchor="w",
        ).grid(row=0, column=0, sticky="w")
        tk.Label(
            header, text=config.APP_SUBTITLE, bg=BG, fg=MUTED,
            font=(self.family, 9), anchor="w",
        ).grid(row=1, column=0, sticky="w", pady=(2, 0))

        self.badge = tk.Label(
            header, text="●  READY", bg=PANEL_ALT, fg=SUCCESS,
            font=(self.family, 8, "bold"), padx=12, pady=6,
        )
        self.badge.grid(row=0, column=1, rowspan=2, sticky="ne")

    def _build_settings(self, parent: tk.Widget) -> None:
        settings = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                            highlightthickness=1)
        settings.grid(row=2, column=0, sticky="ew")
        settings.columnconfigure(0, weight=1)

        inner = tk.Frame(settings, bg=PANEL)
        inner.grid(row=0, column=0, sticky="ew", padx=22, pady=18)
        inner.columnconfigure(0, weight=1)

        self._folder_row(inner, 0, "WORKDIR",
                         "Alle tussenbestanden komen hier.",
                         self.cfg_workdir, self._pick_workdir)
        self._folder_row(inner, 1, "MUZIEKFOLDER",
                         "Definitieve bestemming van de mp3's.",
                         self.cfg_musicdir, self._pick_musicdir)

        tk.Frame(inner, bg=BORDER, height=1).grid(row=2, column=0, sticky="ew", pady=14)

        self._build_years(inner)
        self._build_options(inner)

    def _build_years(self, parent: tk.Widget) -> None:
        meta = tk.Frame(parent, bg=PANEL)
        meta.grid(row=3, column=0, sticky="ew")
        meta.columnconfigure(4, weight=1)

        tk.Label(meta, text="BEGINJAAR", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).grid(row=0, column=0, sticky="w")
        self.begin_entry = ttk.Entry(meta, textvariable=self.begin_year, width=6,
                                     font=(self.family, 12), justify="center")
        self.begin_entry.grid(row=1, column=0, sticky="w", pady=(5, 0))

        tk.Label(meta, text="EINDJAAR", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).grid(row=0, column=2, sticky="w", padx=(20, 0))
        self.end_entry = ttk.Entry(meta, textvariable=self.end_year, width=6,
                                   font=(self.family, 12), justify="center")
        self.end_entry.grid(row=1, column=2, sticky="w", padx=(20, 0), pady=(5, 0))

        tk.Label(
            meta,
            text="De lijst begint in 1970 (week 18). Weeknummers die niet bestaan\n"
                 "worden automatisch overgeslagen.",
            bg=PANEL, fg=FAINT, font=(self.family, 8), justify="left",
        ).grid(row=0, column=4, rowspan=2, sticky="w", padx=(26, 0))

        tk.Frame(parent, bg=BORDER, height=1).grid(row=4, column=0, sticky="ew", pady=14)

    def _build_options(self, parent: tk.Widget) -> None:
        options = tk.Frame(parent, bg=PANEL)
        options.grid(row=5, column=0, sticky="ew")
        options.columnconfigure(1, weight=1)

        tk.Label(options, text="BROWSER-COOKIES", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).grid(row=0, column=0, sticky="w")
        self.browser_combo = ttk.Combobox(options, textvariable=self.browser_var,
                                          state="readonly", font=(self.family, 10))
        self.browser_combo.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        tk.Label(
            options,
            text="Vermijdt bot-detectie. Log één keer in op YouTube in deze browser, "
                 "of kies 'Geen cookies'.",
            bg=PANEL, fg=FAINT, font=(self.family, 8), justify="left", wraplength=470,
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(5, 0))

        tk.Label(options, text="AUDIOKWALITEIT", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).grid(row=0, column=3, sticky="w", padx=(24, 0))
        ttk.Combobox(
            options, textvariable=self.bitrate, state="readonly", width=9,
            values=["128k", "192k", "256k", "320k"], font=(self.family, 10),
        ).grid(row=1, column=3, sticky="w", padx=(24, 0), pady=(5, 0))

        ttk.Checkbutton(
            options, text="Alleen audio downloaden (sneller, video is niet nodig)",
            variable=self.audio_only, style="Opt.TCheckbutton",
        ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(12, 0))

    def _build_output(self, parent: tk.Widget) -> None:
        output = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER,
                          highlightthickness=1)
        output.grid(row=3, column=0, sticky="nsew")
        output.rowconfigure(3, weight=1)
        output.columnconfigure(0, weight=1)

        head = tk.Frame(output, bg=PANEL)
        head.grid(row=0, column=0, sticky="ew", padx=20, pady=(16, 8))
        tk.Label(head, text="UITVOER", bg=PANEL, fg=MUTED,
                 font=(self.family, 9, "bold")).pack(side="left")
        self.status_label = tk.Label(head, textvariable=self.status_text, bg=PANEL,
                                     fg=MUTED, font=(self.family, 9))
        self.status_label.pack(side="right")

        self.bar = ttk.Progressbar(output, mode="determinate", maximum=1000)
        self.bar.grid(row=1, column=0, sticky="ew", padx=20)

        self.log = ScrolledText(
            output, bg=LOG_BG, fg=LOG_TEXT, insertbackground=LOG_TEXT,
            relief="flat", bd=0, padx=14, pady=12, wrap="word",
            font=("DejaVu Sans Mono", 9), state="disabled",
            highlightthickness=1, highlightbackground=BORDER,
        )
        self.log.grid(row=3, column=0, sticky="nsew", padx=20, pady=(12, 20))
        self.log.tag_configure("info", foreground="#7f8796")
        self.log.tag_configure("ok", foreground=SUCCESS)
        self.log.tag_configure("err", foreground="#ff6b81")
        self.log.tag_configure("warn", foreground="#ffb454")
        self.log.tag_configure("head", foreground="#ffffff")

    def _build_footer(self, parent: tk.Widget) -> None:
        footer = tk.Frame(parent, bg=BG)
        footer.grid(row=4, column=0, sticky="ew", pady=(16, 0))

        self.stop_button = self._flat_button(footer, "■  Stoppen", self._on_stop,
                                             DANGER, "#ffffff")
        self.stop_button.pack(side="right")
        self.start_button = self._flat_button(footer, "▶  Starten", self._on_start,
                                              ACCENT, "#ffffff")
        self.start_button.pack(side="right", padx=(0, 10))

        try:
            shown = settings.settings_path()
        except Exception:  # noqa: BLE001 - mag het programma nooit blokkeren
            shown = None
        if shown:
            home = str(Path.home())
            text = str(shown).replace(home, "~", 1) if str(shown).startswith(home) else str(shown)
            hint = tk.Label(footer, text=f"Instellingen worden onthouden in {text}", bg=BG,
                            fg=FAINT, font=(self.family, 8), anchor="w", cursor="hand2")
            hint.pack(side="left")
            hint.bind("<Button-1>", self._open_settings_folder)
            hint.bind("<Enter>", lambda _e: hint.configure(fg=MUTED))
            hint.bind("<Leave>", lambda _e: hint.configure(fg=FAINT))

    def _open_settings_folder(self, _event=None) -> None:
        """Klik op het pad om de map met instellingen te openen."""
        map_ = settings.settings_path().parent
        if not map_.is_dir():
            return
        try:
            if sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(map_)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(map_)])
            else:
                os.startfile(str(map_))  # type: ignore[attr-defined]
        except OSError:
            pass

    def _flat_button(self, parent: tk.Widget, text: str, command, bg: str, fg: str):
        button = tk.Button(
            parent, text=text, command=command, bg=bg, fg=fg, bd=0,
            relief="flat", highlightthickness=0, activebackground=lighten(bg),
            activeforeground=fg, font=(self.family, 11, "bold"),
            padx=26, pady=11, cursor="hand2",
        )
        button.bind("<Enter>", lambda _e: button.configure(bg=lighten(bg)))
        button.bind("<Leave>", lambda _e: button.configure(bg=bg))
        return button

    def _folder_row(self, parent: tk.Widget, row: int, title: str, hint: str,
                    variable: tk.StringVar, command) -> None:
        block = tk.Frame(parent, bg=PANEL)
        block.grid(row=row, column=0, sticky="ew", pady=(0, 12))
        block.columnconfigure(1, weight=1)

        labels = tk.Frame(block, bg=PANEL)
        labels.grid(row=0, column=0, sticky="w", padx=(0, 14))
        tk.Label(labels, text=title, bg=PANEL, fg=MUTED, anchor="w",
                 font=(self.family, 9, "bold")).pack(anchor="w")
        tk.Label(labels, text=hint, bg=PANEL, fg=FAINT, anchor="w",
                 font=(self.family, 8)).pack(anchor="w")

        ttk.Entry(block, textvariable=variable, font=(self.family, 10)).grid(
            row=0, column=1, sticky="ew", padx=(0, 10))
        self._flat_button(block, "Bladeren…", command, PANEL_ALT, TEXT).grid(
            row=0, column=2, sticky="e")

    # ------------------------------------------------------------------
    # Browsers
    # ------------------------------------------------------------------
    def _detect_browsers(self) -> None:
        found = browsers.detect_browsers()
        recommended = browsers.recommended_browser()

        labels: list[str] = []
        self._value_to_key = {}
        for browser in found:
            if not browser.usable:
                continue
            note = ""
            if recommended and browser.key == recommended.key:
                note = "  (aanbevolen)"
            elif browser.is_default:
                note = "  (standaardbrowser)"
            label = f"{browser.label}{note}"
            labels.append(label)
            self._value_to_key[label] = browser.key

        labels.append(NO_COOKIES)
        self.browser_combo["values"] = labels
        # Ook de anonieme optie krijgt een sleutel (een lege string), zodat die
        # keuze net zo goed teruggezet kan worden als een echte browser.
        self._value_to_key[NO_COOKIES] = ""

        chosen = NO_COOKIES
        if recommended:
            for label in labels:
                if self._value_to_key.get(label) == recommended.key:
                    chosen = label
                    break
        self.browser_var.set(chosen)

        if recommended and not recommended.usable:
            self.append_log(
                f"[!] {recommended.label} is je standaardbrowser maar heeft nog geen profiel. "
                "Start die browser één keer, log in op YouTube en herstart dit programma.",
                "warn",
            )
        elif not any(self._value_to_key.get(label) for label in labels[:-1]):
            self.append_log(
                "[!] Geen browserprofiel gevonden. Installeer bijvoorbeeld Chromium of "
                "Firefox, start het één keer en log in op YouTube.",
                "warn",
            )

    # ------------------------------------------------------------------
    # Instellingen onthouden
    # ------------------------------------------------------------------
    def _load_settings(self) -> None:
        """Vul de velden met wat er vorige keer is gebruikt."""
        stored, present = settings.restore()

        if stored["workdir"]:
            self.cfg_workdir.set(str(stored["workdir"]))
        if stored["music_dir"]:
            self.cfg_musicdir.set(str(stored["music_dir"]))
        self.begin_year.set(str(stored["begin_year"]))
        self.end_year.set(str(stored["end_year"]))
        self.audio_only.set(bool(stored["audio_only"]))
        self.bitrate.set(str(stored["bitrate"]))

        # De browser wordt opgeslagen als sleutel, niet als label: het label kan
        # veranderen wanneer de (aanbevolen)-markering verschuift. Alleen terugzetten
        # als er echt iets opgeslagen staat, anders blijft de aanbeveling staan.
        if "browser" in present:
            key = str(stored["browser"])
            for label, value in self._value_to_key.items():
                if value == key:
                    self.browser_var.set(label)
                    break

        if present:
            self.status_text.set("Instellingen teruggezet")

        # Mappen die niet meer bestaan meteen even noemen.
        for variable, naam in ((self.cfg_workdir, "WORKDIR"), (self.cfg_musicdir, "MUZIEKFOLDER")):
            pad = variable.get()
            if pad and not os.path.isdir(pad):
                self.append_log(f"[!] Onthouden {naam} bestaat niet meer: {pad}", "warn")

    def _save_settings(self) -> None:
        """Onthoud de huidige invulling voor de volgende start."""
        try:
            cfg = self._build_config()
        except ValueError:
            return  # ongeldige invoer: niets bruikbaars om te bewaren

        if not settings.save(
            {
                "workdir": cfg.workdir,
                "music_dir": cfg.music_dir,
                "begin_year": cfg.begin_year,
                "end_year": cfg.end_year,
                "browser": cfg.browser,
                "audio_only": cfg.audio_only,
                "bitrate": cfg.bitrate,
            }
        ):
            self.append_log("[i] Instellingen konden niet worden bewaard.", "warn")

    # ------------------------------------------------------------------
    # Mapkiezen
    # ------------------------------------------------------------------
    def _pick_workdir(self) -> None:
        path = filedialog.askdirectory(title="Kies de WORKDIR", mustexist=False)
        if path:
            self.cfg_workdir.set(path)

    def _pick_musicdir(self) -> None:
        path = filedialog.askdirectory(title="Kies de MUZIEKFOLDER", mustexist=True)
        if path:
            self.cfg_musicdir.set(path)

    # ------------------------------------------------------------------
    # Logboek
    # ------------------------------------------------------------------
    def append_log(self, text: str, tag: str = "") -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n", tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _log_queued(self, text: str) -> None:
        stripped = text.strip()
        if stripped.startswith("=") or stripped.startswith("KLAAR"):
            tag = "head"
        elif stripped.startswith("[x]"):
            tag = "err"
        elif stripped.startswith("[!]") or "waarschuwing" in stripped:
            tag = "warn"
        elif stripped.startswith("[i]") or stripped.startswith("•"):
            tag = "info"
        elif "→" in text:
            tag = "ok"
        else:
            tag = ""
        self.append_log(text, tag)

    # ------------------------------------------------------------------
    # Start en stop
    # ------------------------------------------------------------------
    def _on_start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        try:
            cfg = self._build_config()
        except ValueError as exc:
            messagebox.showerror("Instellingen", exc, parent=self.root)
            return

        self._save_settings()

        self._stopping = False
        self._settled = False
        self.start_button.configure(bg=DISABLED_BG, fg=DISABLED_FG, text="Bezig…")
        self.stop_button.configure(bg=DANGER, fg="#ffffff", text="■  Stoppen")
        self.badge.configure(text="●  RUNNING", fg=ACCENT)
        self.status_text.set("Starten…")
        self.bar["value"] = 0

        self._pipeline = Pipeline(cfg, self._enqueue, self._enqueue_progress)
        self._thread = threading.Thread(target=self._pipeline.run, daemon=True)
        self._thread.start()

    def _on_stop(self) -> None:
        if not self._thread or not self._thread.is_alive():
            return
        self._stopping = True
        self.stop_button.configure(bg=DISABLED_BG, fg=DISABLED_FG, text="Stoppen…")
        self.status_text.set("Bezig met stoppen…")
        if self._pipeline:
            self._pipeline.stop()

    def _build_config(self) -> config.JobConfig:
        try:
            begin = int(self.begin_year.get().strip())
            end = int(self.end_year.get().strip())
        except ValueError:
            raise ValueError("BEGINJAAR en EINDJAAR moeten geldige getallen zijn.") from None

        return config.JobConfig(
            workdir=os.path.expanduser(self.cfg_workdir.get().strip()),
            music_dir=os.path.expanduser(self.cfg_musicdir.get().strip()),
            begin_year=begin,
            end_year=end,
            browser=self._value_to_key.get(self.browser_var.get(), ""),
            audio_only=self.audio_only.get(),
            bitrate=self.bitrate.get(),
        )

    # ------------------------------------------------------------------
    # Berichten uit de workerthread
    # ------------------------------------------------------------------
    def _enqueue(self, text: str) -> None:
        self._queue.put(("log", text))

    def _enqueue_progress(self, done: int, total: int, label: str) -> None:
        self._queue.put(("progress", (done, total, label)))

    def _drain(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log":
                    self._log_queued(payload)
                else:
                    done, total, label = payload
                    self._apply_progress(done, total, label)
        except queue.Empty:
            pass

        running = bool(self._thread and self._thread.is_alive())
        if not running and not self._settled:
            self._settled = True
            stopped = self._stopping
            self._stopping = False
            self._set_idle(stopped)

        self._after_id = self.root.after(80, self._drain)

    def _apply_progress(self, done: int, total: int, label: str) -> None:
        if total > 0:
            self.bar["value"] = min(1000, int(done * 1000 / total))
            if label:
                self.status_text.set(label)
        else:
            if label:
                self.status_text.set(label)

    def _set_idle(self, stopped: bool = False) -> None:
        self.start_button.configure(bg=ACCENT, fg="#ffffff", text="▶  Starten")
        self.stop_button.configure(bg=DANGER, fg="#ffffff", text="■  Stoppen")
        self.badge.configure(text="●  READY", fg=SUCCESS)
        if stopped:
            self.status_text.set("Gestopt — opnieuw starten gaat verder")

    def _on_close(self) -> None:
        if self._thread and self._thread.is_alive():
            if not messagebox.askyesno(
                "Afsluiten",
                "Het programma is nog bezig. Stoppen en afsluiten?",
                parent=self.root,
            ):
                return
            self._save_settings()
            if self._pipeline:
                self._pipeline.stop()
        else:
            self._save_settings()

        # De geplande poll-callback afzeggen, anders vuurt die nog een
        # 'invalid command name' af nadat het venster weg is.
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self.root.destroy()


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()

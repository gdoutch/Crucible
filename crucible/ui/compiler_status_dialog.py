"""The compiler status page -- Help -> Compiler status.

One row per registered language: what auto-detection found (or "Checking…"
while a probe is still running in the background), the install instructions
and a Download button when it is missing, and a Browse button that lets the
candidate point at a compiler auto-detection could not find on its own.

Browse does not teach any language plugin a new place to look. It prepends
the chosen file's directory onto this process's own PATH and re-runs the
same `detect_toolchain()` that "Re-check" already runs -- see
`workspace.apply_compiler_path_overrides` -- so every plugin's existing
PATH-based search just finds it there, with no plugin-specific browse code
anywhere. That is also why Python has no row here worth a Browse button:
it is never "missing", so there is nothing this page could do for it.
"""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .. import languages, workspace
from ..i18n import t
from ..languages import Language
from .theme import Palette

BADGE_OK = "✓"
BADGE_BAD = "✗"


def show(master, palette: Palette, settings: dict) -> "CompilerStatusDialog":
    """Open the dialog, or bring the existing one to front.

    Non-modal and a singleton for the same reason: installing a missing
    compiler happens outside this window, in a browser and an installer, and
    the candidate should be able to come back and press Re-check without
    first having to close and reopen this page to get back to it.
    """
    existing: CompilerStatusDialog | None = getattr(master, "_compiler_status_dialog", None)
    if existing is not None and existing.winfo_exists():
        existing.deiconify()
        existing.lift()
        existing.focus_force()
        return existing
    dialog = CompilerStatusDialog(master, palette, settings)
    master._compiler_status_dialog = dialog
    return dialog


class CompilerStatusDialog(tk.Toplevel):
    def __init__(self, master, palette: Palette, settings: dict) -> None:
        super().__init__(master)
        self._palette = palette
        #: The same dict `CrucibleApp.settings` holds -- mutated in place and
        #: saved through `workspace`, exactly like every other setting here.
        self._settings = settings
        self._events: queue.Queue = queue.Queue()
        self._checking: set[str] = set()
        self._rows: dict[str, _LanguageRow] = {}
        self._pump_job: str | None = None

        self.title(t("app.menu.help.compiler_status"))
        self.configure(background=palette.window_bg)
        self.transient(master)
        self.minsize(520, 320)
        self.geometry("680x560")
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build()
        self.update_idletasks()
        self._center_over(master)
        self._pump()

        for language in languages.all_languages():
            if language.detected_toolchain() is None:
                self._start_check(language.id)

    # -- construction --------------------------------------------------

    def _build(self) -> None:
        palette = self._palette
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=t("app.menu.help.compiler_status"),
                 style="Heading.TLabel").pack(anchor="w")
        ttk.Label(outer, text=t("app.compiler_status.subtitle"),
                 style="Muted.TLabel", wraplength=620,
                 justify="left").pack(anchor="w", pady=(2, 10))

        # A plain Canvas is the only way ttk gets a scrollable region taller
        # than the window -- there is no scrollable ttk.Frame. The mousewheel
        # binding is scoped to while the pointer is actually over this canvas
        # (bind on Enter, unbind on Leave) rather than bound globally for the
        # dialog's whole lifetime, which would otherwise hijack scrolling in
        # the main window the moment this page opened behind it.
        holder = ttk.Frame(outer, style="Panel.TFrame")
        holder.pack(fill="both", expand=True)
        canvas = tk.Canvas(holder, background=palette.panel_bg,
                           highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._canvas = canvas

        self._list = ttk.Frame(canvas, style="Panel.TFrame")
        window = canvas.create_window((0, 0), window=self._list, anchor="nw")
        self._list.bind("<Configure>",
                        lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                   lambda e: canvas.itemconfigure(window, width=e.width))

        def _wheel(event) -> None:
            canvas.yview_scroll(int(-event.delta / 120), "units")
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", _wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        for language in languages.all_languages():
            row = _LanguageRow(self._list, self._palette, language, self)
            row.pack(fill="x")
            self._rows[language.id] = row

        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 0))
        ttk.Button(buttons, text=t("app.compiler_status.recheck_all_button"),
                  command=self._recheck_all).pack(side="left")
        ttk.Button(buttons, text=t("app.compiler_status.close_button"),
                  style="Run.TButton", command=self._on_close).pack(side="right")

    def _center_over(self, master) -> None:
        master.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

    # -- detection, on a background thread like every other slow probe here --

    def _start_check(self, language_id: str, refresh: bool = False) -> None:
        if language_id in self._checking:
            return
        self._checking.add(language_id)
        self._refresh_row(language_id)

        def worker() -> None:
            try:
                languages.get(language_id).toolchain(refresh=refresh)
            except Exception:
                pass  # a plugin's own detection failing is still "checked"
            self._events.put(language_id)

        threading.Thread(target=worker, daemon=True,
                         name=f"crucible-compiler-status-{language_id}").start()

    def recheck(self, language_id: str) -> None:
        self._start_check(language_id, refresh=True)

    def _recheck_all(self) -> None:
        for language_id in self._rows:
            self.recheck(language_id)

    def _refresh_row(self, language_id: str) -> None:
        row = self._rows.get(language_id)
        if row is not None:
            row.render()

    def _pump(self) -> None:
        try:
            while True:
                language_id = self._events.get_nowait()
                self._checking.discard(language_id)
                self._refresh_row(language_id)
        except queue.Empty:
            pass
        if self.winfo_exists():
            self._pump_job = self.after(80, self._pump)

    # -- actions delegated to by each row --------------------------------

    def is_checking(self, language_id: str) -> bool:
        return language_id in self._checking

    def override_for(self, language_id: str) -> str:
        overrides = self._settings.get("compiler_path_overrides", {})
        return overrides.get(language_id, "") if isinstance(overrides, dict) else ""

    def browse_for(self, language: Language) -> None:
        filetypes = []
        if sys.platform == "win32":
            filetypes.append((t("app.compiler_status.browse_executables_filter"), "*.exe"))
        filetypes.append((t("app.compiler_status.browse_all_files_filter"), "*"))
        chosen = filedialog.askopenfilename(
            parent=self,
            title=t("app.compiler_status.browse_dialog_title",
                    language=language.display_name),
            filetypes=filetypes,
        )
        if not chosen:
            return
        directory = str(Path(chosen).resolve().parent)
        workspace.set_compiler_path_override(language.id, directory, self._settings)
        self.recheck(language.id)

    def reset_override(self, language_id: str) -> None:
        workspace.clear_compiler_path_override(language_id, self._settings)
        self._refresh_row(language_id)

    def open_download(self, language: Language) -> None:
        status = language.detected_toolchain()
        url = status.download_url if status else ""
        if not url:
            return
        try:
            opened = webbrowser.open(url)
        except Exception:
            opened = False
        if not opened:
            messagebox.showerror(
                t("app.compiler_status.could_not_open_link_title"),
                t("app.compiler_status.could_not_open_link_message", url=url),
                parent=self)

    # -- lifecycle --------------------------------------------------------

    def _on_close(self) -> None:
        try:
            self._canvas.unbind_all("<MouseWheel>")
        except tk.TclError:
            pass
        if self._pump_job is not None:
            try:
                self.after_cancel(self._pump_job)
            except tk.TclError:
                pass
        if getattr(self.master, "_compiler_status_dialog", None) is self:
            self.master._compiler_status_dialog = None
        self.destroy()


class _LanguageRow(ttk.Frame):
    """One language's card: status, detail, remedy, and its buttons.

    Rebuilt from scratch on every `render()` rather than having each action
    update individual widgets in place -- the states involved (checking /
    found / missing / missing-with-an-override-that-did-not-help) are few
    enough, and different enough in shape, that tracking which widgets exist
    already would be more bookkeeping than just describing what each state
    looks like and rebuilding it.
    """

    def __init__(self, parent, palette: Palette, language: Language,
                dialog: CompilerStatusDialog) -> None:
        super().__init__(parent, style="Panel.TFrame", padding=(12, 10))
        self._palette = palette
        self._language = language
        self._dialog = dialog
        self._body = ttk.Frame(self, style="Panel.TFrame")
        self._body.pack(fill="x", expand=True)
        self.render()

    def render(self) -> None:
        for child in self._body.winfo_children():
            child.destroy()
        for child in self.winfo_children():
            if child is not self._body:
                child.destroy()

        language = self._language
        dialog = self._dialog
        checking = dialog.is_checking(language.id)
        status = None if checking else language.detected_toolchain()

        header = ttk.Frame(self._body, style="Panel.TFrame")
        header.pack(fill="x")

        if status is None:
            badge, badge_style = "…", "Warn.TLabel"
            summary = t("app.compiler_status.checking")
        else:
            ok = status.available
            badge = BADGE_OK if ok else BADGE_BAD
            badge_style = "Ok.TLabel" if ok else "Fail.TLabel"
            summary = status.summary

        ttk.Label(header, text=badge, style=badge_style,
                 font=("", 11, "bold")).pack(side="left")
        ttk.Label(header, text=f"  {language.display_name}", style="Panel.TLabel",
                 font=("", 10, "bold")).pack(side="left")

        actions = ttk.Frame(header, style="Panel.TFrame")
        actions.pack(side="right")
        recheck = ttk.Button(actions, text=t("app.compiler_status.recheck_button"),
                             command=lambda: dialog.recheck(language.id))
        recheck.pack(side="right")
        # No Browse button for a language that is never "missing" -- see the
        # module docstring for why Python is the one language this applies to.
        if language.id != "python":
            browse = ttk.Button(actions, text=t("app.compiler_status.browse_button"),
                                command=lambda: dialog.browse_for(language))
            browse.pack(side="right", padx=(0, 6))
            if checking:
                browse.configure(state="disabled")
        if checking:
            recheck.configure(state="disabled")

        ttk.Label(self._body, text=summary, style="Panel.TLabel",
                 wraplength=560, justify="left").pack(anchor="w", pady=(4, 0))

        if status is not None:
            if status.detail:
                ttk.Label(self._body, text=status.detail, style="Muted.TLabel",
                         wraplength=560, justify="left").pack(anchor="w", pady=(2, 0))

            if not status.available:
                if status.remedy:
                    ttk.Label(self._body, text=status.remedy, style="Muted.TLabel",
                             wraplength=560, justify="left").pack(anchor="w", pady=(6, 0))
                if status.download_url:
                    ttk.Button(self._body, text=t("app.compiler_status.download_button"),
                              command=lambda: dialog.open_download(language)
                              ).pack(anchor="w", pady=(8, 0))

            override = dialog.override_for(language.id)
            if override:
                note = ttk.Frame(self._body, style="Panel.TFrame")
                note.pack(fill="x", pady=(8, 0))
                ttk.Label(note, text=t("app.compiler_status.override_heading"),
                         style="Muted.TLabel").pack(side="left")
                ttk.Label(note, text=override, style="Panel.TLabel",
                         wraplength=400).pack(side="left", padx=(4, 8))
                ttk.Button(note, text=t("app.compiler_status.reset_override_button"),
                          command=lambda: dialog.reset_override(language.id)
                          ).pack(side="left")
                if not status.available:
                    ttk.Label(self._body, text=t("app.compiler_status.still_not_found_after_browse"),
                             style="Fail.TLabel").pack(anchor="w", pady=(2, 0))

        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(10, 0))

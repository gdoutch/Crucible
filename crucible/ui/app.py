"""The Crucible main window."""

from __future__ import annotations

import itertools
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from .. import guides, i18n, languages, profiles, randomise, runner, workspace
from ..i18n import t
from ..problem import DIFFICULTIES, Library, Problem, TestCase, load_library
from ..randomise import GeneratedSuite
from ..runner import ERROR, FAIL, PASS, SKIPPED, TIMEOUT, SubmissionResult, TestOutcome
from .editor import CodeEditor, mono_font
from .panes import CollapsiblePane, PaneStack
from .profile_dialog import choose_profile
from .theme import PALETTES, Palette, apply_theme

#: Single source of truth for the product name -- window title, wordmark and
#: every dialog read from here.
APP_NAME = "Crucible"

BADGE_OK = "✓"       # check mark
BADGE_BAD = "✗"      # ballot X
BADGE_PENDING = "…"  # ellipsis
PROGRESS_SOLVED = "★"  # this profile has passed every test at least once

#: Prefixes of the group rows the problem tree inserts above the problems
#: themselves -- by language, or (within one language) by difficulty. Neither
#: is a real problem id, so a click on one is not a selection.
_GROUP_PREFIXES = ("lang:", "diff:")

#: Maps a runner status constant to its display text's locale key. A function
#: rather than a dict built once at import time, so a locale switched after
#: start-up is reflected the next time a status is shown, not frozen at
#: whatever the active locale was when the module first loaded.
_STATUS_LABEL_KEY = {
    PASS: "app.status.pass", FAIL: "app.status.fail", ERROR: "app.status.error",
    TIMEOUT: "app.status.timeout", SKIPPED: "app.status.skipped",
}


def _status_label(status: str) -> str:
    key = _STATUS_LABEL_KEY.get(status)
    return t(key) if key else status


def _difficulty_label(difficulty: str) -> str:
    key = f"app.difficulty.{difficulty}"
    return t(key) if difficulty in DIFFICULTIES else difficulty


class _ReadOnlyText(tk.Text):
    """A Text the user can select and scroll but not type into.

    `state="disabled"` would also block programmatic inserts, so instead we
    swallow key events and re-enable only while we are writing.
    """

    def __init__(self, master, palette: Palette, **kwargs) -> None:
        kwargs.setdefault("wrap", "word")
        kwargs.setdefault("relief", "flat")
        kwargs.setdefault("padx", 12)
        kwargs.setdefault("pady", 10)
        super().__init__(master, background=palette.editor_bg,
                         foreground=palette.text_primary,
                         insertbackground=palette.editor_bg,
                         selectbackground=palette.selection,
                         highlightthickness=0, borderwidth=0, **kwargs)
        self.bind("<Key>", self._block_keys)

    @staticmethod
    def _block_keys(event):
        allowed = {"Up", "Down", "Left", "Right", "Prior", "Next", "Home", "End"}
        if event.keysym in allowed:
            return None
        if event.state & 0x4 and event.keysym.lower() in {"c", "a"}:
            return None  # Ctrl+C / Ctrl+A
        return "break"

    def replace_all(self, writer) -> None:
        self.configure(state="normal")
        self.delete("1.0", "end")
        writer()
        self.see("1.0")


class CrucibleApp(tk.Tk):
    def __init__(self, problems_root: Path) -> None:
        super().__init__()

        self.problems_root = problems_root
        self.settings = workspace.load_settings()
        #: Filled in once a profile is active -- see `_resolve_startup_profile`.
        #: Empty until then so nothing that runs before it needs to check for
        #: `None`; there is simply nothing solved and nowhere to save yet.
        self._profile: profiles.Profile | None = None
        self.seeds: dict[str, int] = {}
        self._progress: dict[str, dict] = {}
        self.palette: Palette = PALETTES.get(self.settings["theme"], PALETTES["dark"])

        self.title(APP_NAME)
        self.minsize(1040, 700)
        # Only the size is remembered, never the position: a saved position is
        # a way to open off the edge of a screen that is no longer plugged in.
        saved_size = self._layout().get("window")
        self.geometry(saved_size if isinstance(saved_size, str)
                      and re.fullmatch(r"\d{3,5}x\d{3,5}", saved_size)
                      else "1320x880")

        self.style = apply_theme(self, self.palette)
        self._mono = mono_font(self.settings["font_size"])
        self._mono_small = mono_font(max(self.settings["font_size"] - 1, 8))

        # cross-thread plumbing
        self._events: queue.Queue = queue.Queue()
        self._verify_queue: queue.PriorityQueue = queue.PriorityQueue()
        self._verify_seq = itertools.count()
        #: (problem id, with_data) pairs already handed to the worker.
        self._requested: set[tuple[str, bool]] = set()
        self._verification: dict[str, SubmissionResult | None] = {}
        #: None while a data set is being built; a GeneratedSuite once it is.
        self._generation: dict[str, GeneratedSuite | None] = {}
        #: Languages whose toolchain detection is in flight on a background
        #: thread. Detection is slow enough to freeze the window if it is done
        #: inline -- see `_refresh_toolchain_label`.
        self._detecting: set[str] = set()
        #: Languages whose detection raised. Kept so the label settles on
        #: "detection failed" instead of retrying on every refresh.
        self._detect_failed: set[str] = set()
        #: Set by Tools → re-check, so the report is shown once detection has
        #: actually finished rather than while it is still running.
        self._pending_toolchain_report = False

        self._library = Library()
        self._problem: Problem | None = None
        self._outcome_rows: dict[str, TestOutcome] = {}
        self._pending_tests: dict[str, TestCase] = {}
        self._running = False
        self._cancel = threading.Event()
        self._override_gate: set[str] = set()
        self._autosave_job: str | None = None
        #: Problems whose worked solution has already been opened this
        #: session, so the "are you sure" is asked once rather than every time.
        self._revealed: set[str] = set()
        #: Ticks in the View menu, one per collapsible pane. Populated by
        #: `_build_menu`; empty until then so an early relayout is harmless.
        self._pane_vars: dict[str, tk.BooleanVar] = {}
        self._layout_restored = False

        self._build_toolbar()
        self._build_banner()
        self._build_body()
        self._build_statusbar()
        # After the body, so the View menu can be wired straight to the panes
        # it toggles rather than looking them up later by name.
        self._build_menu()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda _e: self._on_go())
        self.bind("<Control-Return>", lambda _e: self._on_go())
        self.bind("<Control-s>", lambda _e: self._save_draft(force=True))
        self.bind("<Control-r>", lambda _e: self._on_new_data())
        self.bind("<F1>", lambda _e: self._open_guide(guides.HINT))
        self.bind("<F2>", lambda _e: self._open_guide(guides.DIAGRAM))
        for index, key in enumerate(self._pane_keys, start=1):
            self.bind(f"<Control-Key-{index}>",
                      lambda _e, k=key: self._toggle_pane(k))
        self.bind("<Control-Key-0>", lambda _e: self._reset_layout())

        # Sizes are pixels, so the window has to have a real one before they
        # mean anything. `after_idle` is too early -- nothing is mapped yet and
        # every pane still measures zero -- so wait for the first configure
        # that reports a height worth dividing up.
        self.rows.paned.bind("<Configure>", self._maybe_restore_layout, add="+")

        self._start_verify_worker()
        self.after(60, self._pump)
        # Loading the library is the last step of resolving which profile is
        # active, not a separate one -- the tree it builds needs to know whose
        # solved badges and whose last-open problem to show.
        self.after(10, self._resolve_startup_profile)

    # ------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        opts = dict(background=self.palette.panel_bg,
                    foreground=self.palette.text_primary,
                    activebackground=self.palette.accent,
                    activeforeground="#ffffff", borderwidth=0)

        file_menu = tk.Menu(menubar, tearoff=0, **opts)
        file_menu.add_command(label=t("app.menu.file.save_draft"),
                              command=lambda: self._save_draft(force=True))
        file_menu.add_command(label=t("app.menu.file.reset"),
                              command=self._reset_to_starter)
        file_menu.add_separator()
        file_menu.add_command(label=t("app.menu.file.reload"), command=self._load_library)
        file_menu.add_separator()
        file_menu.add_command(label=t("app.menu.file.quit"), command=self._on_close)
        menubar.add_cascade(label=t("app.menu.file.title"), menu=file_menu)

        # Editing commands live on the editor widget, not here -- this menu is
        # how anyone finds out they exist. Each entry drives the same method
        # the key binding does, so the two cannot drift apart.
        edit_menu = tk.Menu(menubar, tearoff=0, **opts)
        edit_menu.add_command(label=t("app.menu.edit.undo"),
                              command=lambda: self.editor.text.event_generate("<<Undo>>"))
        edit_menu.add_command(label=t("app.menu.edit.redo"),
                              command=lambda: self.editor.text.event_generate("<<Redo>>"))
        edit_menu.add_separator()
        edit_menu.add_command(label=t("app.menu.edit.cut_line"),
                              command=self.editor.cut_line)
        edit_menu.add_command(label=t("app.menu.edit.duplicate_line"),
                              command=self.editor.duplicate_lines)
        edit_menu.add_command(label=t("app.menu.edit.delete_line"),
                              command=self.editor.delete_lines)
        edit_menu.add_command(label=t("app.menu.edit.move_up"),
                              command=lambda: self.editor.move_lines(-1))
        edit_menu.add_command(label=t("app.menu.edit.move_down"),
                              command=lambda: self.editor.move_lines(1))
        edit_menu.add_separator()
        edit_menu.add_command(label=t("app.menu.edit.toggle_comment"),
                              command=self.editor.toggle_comment)
        edit_menu.add_separator()
        edit_menu.add_command(label=t("app.menu.edit.find"),
                              command=lambda: self.editor.open_find(replace=False))
        edit_menu.add_command(label=t("app.menu.edit.replace"),
                              command=lambda: self.editor.open_find(replace=True))
        edit_menu.add_command(label=t("app.menu.edit.find_next"),
                              command=lambda: self.editor.step_match(1))
        edit_menu.add_command(label=t("app.menu.edit.find_previous"),
                              command=lambda: self.editor.step_match(-1))
        menubar.add_cascade(label=t("app.menu.edit.title"), menu=edit_menu)

        run_menu = tk.Menu(menubar, tearoff=0, **opts)
        run_menu.add_command(label=t("app.menu.run.go"), command=self._on_go)
        run_menu.add_command(label=t("app.menu.run.stop"), command=self._on_stop)
        run_menu.add_separator()
        run_menu.add_command(label=t("app.menu.run.new_data"), command=self._on_new_data)
        menubar.add_cascade(label=t("app.menu.run.title"), menu=run_menu)

        # Who drafts, seeds and solved badges belong to. Just a label and one
        # action -- the picker dialog is where switching and creating happen,
        # so there is nothing to duplicate here.
        self.profile_menu = tk.Menu(menubar, tearoff=0, **opts)
        self.profile_menu.add_command(
            label=t("app.menu.profile.current", username=t("app.menu.profile.unknown")),
            state="disabled")
        self.profile_menu.add_separator()
        self.profile_menu.add_command(label=t("app.menu.profile.switch"),
                                      command=self._switch_profile)
        menubar.add_cascade(label=t("app.menu.profile.title"), menu=self.profile_menu)

        # Guides open in the browser rather than in a pane: they are documents,
        # and the point of reading one is to have it beside the editor rather
        # than on top of it.
        self.guides_menu = tk.Menu(menubar, tearoff=0, **opts)
        #: Menu order, and the order `_refresh_guides_menu` walks to set each
        #: entry's state -- one list so the two cannot drift apart.
        self._guide_order = (guides.DIAGRAM, guides.HINT, guides.SOLUTION)
        self.guides_menu.add_command(
            label=t("app.menu.guides.diagram"),
            command=lambda: self._open_guide(guides.DIAGRAM))
        self.guides_menu.add_command(
            label=t("app.menu.guides.hint"),
            command=lambda: self._open_guide(guides.HINT))
        self.guides_menu.add_command(
            label=t("app.menu.guides.solution"),
            command=lambda: self._open_guide(guides.SOLUTION))
        self.guides_menu.add_separator()
        self.guides_menu.add_command(label=t("app.menu.guides.what_are_these"),
                                     command=self._show_guides_help)
        menubar.add_cascade(label=t("app.menu.guides.title"), menu=self.guides_menu)

        view_menu = tk.Menu(menubar, tearoff=0, **opts)
        # Checkbuttons rather than commands, so the menu doubles as the answer
        # to "where has the editor gone?" -- the ticks say which panes are open.
        for index, key in enumerate(self._pane_keys, start=1):
            pane = self._pane(key)
            variable = tk.BooleanVar(value=not pane.collapsed)
            self._pane_vars[key] = variable
            view_menu.add_checkbutton(
                label=t("app.menu.view.pane_toggle", label=pane.label.title(), index=index),
                variable=variable, selectcolor=self.palette.accent,
                command=lambda k=key: self._toggle_pane(k))
        view_menu.add_command(label=t("app.menu.view.reset_layout"),
                              command=self._reset_layout)
        view_menu.add_separator()
        view_menu.add_command(label=t("app.menu.view.toggle_theme"),
                              command=self._toggle_theme)
        view_menu.add_command(label=t("app.menu.view.larger_font"),
                              command=lambda: self._change_font(1))
        view_menu.add_command(label=t("app.menu.view.smaller_font"),
                              command=lambda: self._change_font(-1))
        menubar.add_cascade(label=t("app.menu.view.title"), menu=view_menu)

        # One radiobutton per bundled locale, so adding a new
        # crucible/locales/<code>.json makes it selectable here with no
        # further wiring. Picking one only saves the choice for next launch
        # -- see _set_locale for why this doesn't re-render live, the same
        # reason _toggle_theme doesn't either.
        language_menu = tk.Menu(menubar, tearoff=0, **opts)
        self.locale_var = tk.StringVar(value=i18n.get_locale())
        for locale in i18n.available_locales():
            language_menu.add_radiobutton(
                label=i18n.locale_display_name(locale),
                value=locale, variable=self.locale_var,
                selectcolor=self.palette.accent,
                command=lambda loc=locale: self._set_locale(loc))
        menubar.add_cascade(label=t("app.menu.language.title"), menu=language_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, **opts)
        tools_menu.add_command(label=t("app.menu.tools.recheck_compilers"),
                               command=self._recheck_toolchains)
        tools_menu.add_command(label=t("app.menu.tools.verify_all"),
                               command=self._verify_all)
        tools_menu.add_separator()
        tools_menu.add_command(label=t("app.menu.tools.open_problems_folder"),
                               command=lambda: self._open_folder(self.problems_root))
        tools_menu.add_command(label=t("app.menu.tools.open_drafts_folder"),
                               command=lambda: self._open_folder(self._profile_root()))
        menubar.add_cascade(label=t("app.menu.tools.title"), menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0, **opts)
        help_menu.add_command(label=t("app.menu.help.compiler_status"), command=self._show_toolchains)
        help_menu.add_command(label=t("app.menu.help.authoring"),
                              command=self._show_authoring_help)
        help_menu.add_command(label=t("app.menu.help.about"), command=self._show_about)
        menubar.add_cascade(label=t("app.menu.help.title"), menu=help_menu)

        self.configure(menu=menubar)
        self._refresh_guides_menu()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(12, 10, 12, 6))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text=APP_NAME.upper(), style="Brand.TLabel").pack(
            side="left", padx=(0, 12))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y",
                                                   padx=(0, 12), pady=2)

        ttk.Label(bar, text=t("app.toolbar.language_label")).pack(side="left")
        self.language_var = tk.StringVar()
        self.language_box = ttk.Combobox(bar, textvariable=self.language_var,
                                         state="readonly", width=12)
        self.language_box.pack(side="left", padx=(6, 16))
        self.language_box.bind("<<ComboboxSelected>>",
                               lambda _e: self._populate_problem_tree())

        self.problem_title = ttk.Label(bar, text=t("app.toolbar.no_problem_selected"),
                                       style="Heading.TLabel")
        self.problem_title.pack(side="left")
        self.problem_meta = ttk.Label(bar, text="", style="Muted.TLabel")
        self.problem_meta.pack(side="left", padx=(10, 0))

        self.go_button = ttk.Button(bar, text=t("app.toolbar.go_button"), style="Run.TButton",
                                    command=self._on_go, state="disabled")
        self.go_button.pack(side="right")
        ttk.Button(bar, text=t("app.toolbar.reset_button"), command=self._reset_to_starter).pack(
            side="right", padx=(0, 8))
        self.new_data_button = ttk.Button(bar, text=t("app.toolbar.new_data_button"),
                                          command=self._on_new_data,
                                          state="disabled")
        self.new_data_button.pack(side="right", padx=(0, 8))

    def _build_body(self) -> None:
        """The four panes, each one collapsible to its title bar.

        Two stacks: the problem list beside everything else, and the three
        working panes above one another inside that. Only the inner three
        carry a maximise button -- "just the problem list" is not a view
        anybody wants, whereas "just the problem" very much is.
        """
        self.columns = PaneStack(self, "horizontal", on_change=self._on_panes_moved)
        self.columns.paned.pack(side="top", fill="both", expand=True,
                                padx=12, pady=(0, 6))

        problems = CollapsiblePane(self.columns.paned, self.palette,
                                   "problems", t("app.pane.problems"), orient="horizontal")
        self._build_problem_list(problems.body)
        self.columns.add(problems, weight=0)

        self.rows = PaneStack(self.columns.paned, "vertical",
                              on_change=self._on_panes_moved)
        self.columns.add(self.rows.paned, weight=4)

        def row(key: str, label: str, build, weight: int) -> None:
            pane = CollapsiblePane(self.rows.paned, self.palette, key, label,
                                   maximisable=True)
            build(pane)
            self.rows.add(pane, weight=weight)

        # Reading and writing get equal billing. Which of the two you actually
        # want is a thing that changes minute by minute, and the maximise
        # button answers it far better than a default ever could.
        row("statement", t("app.pane.statement"), self._build_statement, 4)
        row("editor", t("app.pane.editor"), self._build_editor, 4)
        row("results", t("app.pane.results"), self._build_results, 3)

        #: Menu order and Ctrl+1..4 order, outermost pane first.
        self._pane_keys = ("problems", "statement", "editor", "results")

    def _build_problem_list(self, master) -> None:
        frame = ttk.Frame(master, width=260)
        frame.pack_propagate(False)
        frame.pack(fill="both", expand=True)

        self.problem_tree = ttk.Treeview(frame, columns=("progress", "badge"),
                                         show="tree headings", selectmode="browse")
        self.problem_tree.heading("#0", text=t("app.tree.column_problem"))
        # The glyphs double as their own legend: a header showing the same
        # mark the column fills in with is a shorter explanation than any
        # tooltip -- "this column is about ✓/✗" needs no further words.
        self.problem_tree.heading("progress", text=PROGRESS_SOLVED)
        self.problem_tree.heading("badge", text=BADGE_OK)
        self.problem_tree.column("#0", width=178, stretch=True)
        self.problem_tree.column("progress", width=24, anchor="center", stretch=False)
        self.problem_tree.column("badge", width=30, anchor="center", stretch=False)

        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.problem_tree.yview)
        self.problem_tree.configure(yscrollcommand=scroll.set)
        self.problem_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.problem_tree.tag_configure("group", foreground=self.palette.text_muted)
        self.problem_tree.tag_configure("ok", foreground=self.palette.ok)
        self.problem_tree.tag_configure("bad", foreground=self.palette.fail)
        self.problem_tree.bind("<<TreeviewSelect>>", self._on_problem_selected)

    def _build_statement(self, pane: CollapsiblePane) -> None:
        holder = ttk.Frame(pane.body, style="Panel.TFrame")
        holder.pack(fill="both", expand=True)

        # `height` here is a floor, not a target: ttk treats a pane's requested
        # size as the smallest it may be squeezed to, so every one of these is
        # chosen to leave the pane weights room to do the actual dividing up.
        self.statement = _ReadOnlyText(holder, self.palette, height=10)
        scroll = ttk.Scrollbar(holder, orient="vertical",
                               command=self.statement.yview)
        self.statement.configure(yscrollcommand=scroll.set)
        self.statement.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configure_statement_tags()

    def _build_editor(self, pane: CollapsiblePane) -> None:
        self.editor_filename = ttk.Label(pane.extra, text="",
                                         style="PaneTitle.TLabel")
        self.editor_filename.pack(side="right")

        self.editor = CodeEditor(pane.body, self.palette,
                                 self.settings["font_size"], height=8)
        self.editor.pack(fill="both", expand=True)
        self.editor.text.bind("<<TextChanged>>", self._on_code_changed, add="+")

    def _build_results(self, pane: CollapsiblePane) -> None:
        self.notebook = ttk.Notebook(pane.body)
        self.notebook.pack(fill="both", expand=True)

        self.tests_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.tests_tab, text=t("app.results.unit_tests_tab"))

        split = ttk.PanedWindow(self.tests_tab, orient="horizontal")
        split.pack(fill="both", expand=True)

        left = ttk.Frame(split)
        split.add(left, weight=3)
        self.test_tree = ttk.Treeview(
            left, columns=("status", "name", "time"), show="headings",
            selectmode="browse", height=5)
        self.test_tree.heading("status", text=t("app.results.column_result"))
        self.test_tree.heading("name", text=t("app.results.column_test_case"))
        self.test_tree.heading("time", text=t("app.results.column_time"))
        self.test_tree.column("status", width=86, anchor="w", stretch=False)
        self.test_tree.column("name", width=280, stretch=True)
        self.test_tree.column("time", width=70, anchor="e", stretch=False)
        tscroll = ttk.Scrollbar(left, orient="vertical", command=self.test_tree.yview)
        self.test_tree.configure(yscrollcommand=tscroll.set)
        self.test_tree.pack(side="left", fill="both", expand=True)
        tscroll.pack(side="right", fill="y")

        self.test_tree.tag_configure(PASS, foreground=self.palette.ok)
        self.test_tree.tag_configure(FAIL, foreground=self.palette.fail)
        self.test_tree.tag_configure(ERROR, foreground=self.palette.error)
        self.test_tree.tag_configure(TIMEOUT, foreground=self.palette.warn)
        self.test_tree.tag_configure("pending", foreground=self.palette.text_muted)
        self.test_tree.bind("<<TreeviewSelect>>", self._on_test_selected)

        detail_holder = ttk.Frame(split)
        split.add(detail_holder, weight=4)
        self.detail = _ReadOnlyText(detail_holder, self.palette, wrap="none",
                                    height=5)
        dscroll = ttk.Scrollbar(detail_holder, orient="vertical",
                                command=self.detail.yview)
        self.detail.configure(yscrollcommand=dscroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        dscroll.pack(side="right", fill="y")
        self._configure_detail_tags()

        # Added so that it keeps its place in the tab order, then hidden: a
        # build nobody has asked for yet has nothing to say, and an empty tab
        # sitting there is one more thing to wonder about before pressing Go.
        self.build_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.build_tab, text=t("app.results.build_output_tab"))
        self.notebook.hide(self.build_tab)
        self._build_tab_shown = False

        self.build_output = _ReadOnlyText(self.build_tab, self.palette,
                                          wrap="none", height=5,
                                          font=self._mono_small)
        bscroll = ttk.Scrollbar(self.build_tab, orient="vertical",
                                command=self.build_output.yview)
        self.build_output.configure(yscrollcommand=bscroll.set)
        self.build_output.pack(side="left", fill="both", expand=True)
        bscroll.pack(side="right", fill="y")
        self.build_output.tag_configure("err", foreground=self.palette.fail)
        self.build_output.tag_configure("warn", foreground=self.palette.warn)
        self.build_output.tag_configure("muted", foreground=self.palette.text_muted)

    def _build_banner(self) -> None:
        """The verdict on the current problem, above the panes rather than in
        them.

        It reports on the *problem* -- suite verified, data set building, or
        disabled because the reference fails -- so it has no business being
        inside a pane that can be collapsed out of sight.
        """
        holder = ttk.Frame(self, padding=(12, 0, 12, 6))
        holder.pack(side="top", fill="x")
        holder.columnconfigure(0, weight=1)

        self.banner = tk.Label(holder, text="", anchor="w", padx=10, pady=6,
                               background=self.palette.panel_bg,
                               foreground=self.palette.text_muted)
        self.banner.grid(row=0, column=0, sticky="ew")
        self.banner_button = ttk.Button(holder, text=t("app.results.run_anyway_button"),
                                        command=self._override_reference_gate)

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(12, 6))
        bar.pack(side="bottom", fill="x")

        self.toolchain_label = ttk.Label(bar, text=t("app.statusbar.checking_compilers"),
                                         style="Status.TLabel")
        self.toolchain_label.pack(side="left")

        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y", padx=10)
        self.profile_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.profile_label.pack(side="left")

        self.progress = ttk.Progressbar(bar, mode="determinate", length=180)
        self.result_label = ttk.Label(bar, text="", style="Status.TLabel")
        self.result_label.pack(side="right")

    def _configure_statement_tags(self) -> None:
        p = self.palette
        base = tkfont.nametofont("TkDefaultFont").actual()["family"]
        self.statement.configure(font=(base, 10))
        self.statement.tag_configure("h1", font=(base, 13, "bold"),
                                     foreground=p.text_primary, spacing1=8, spacing3=6)
        self.statement.tag_configure("h2", font=(base, 11, "bold"),
                                     foreground=p.text_primary, spacing1=8, spacing3=4)
        self.statement.tag_configure("body", spacing3=4, lmargin1=0, lmargin2=0)
        self.statement.tag_configure("bullet", lmargin1=18, lmargin2=32, spacing3=2)
        self.statement.tag_configure("code", font=self._mono_small,
                                     foreground=p.syn_string)
        self.statement.tag_configure("codeblock", font=self._mono_small,
                                     background=p.panel_bg, lmargin1=18, lmargin2=18,
                                     spacing1=2, spacing3=2)
        self.statement.tag_configure("muted", foreground=p.text_muted)

    def _configure_detail_tags(self) -> None:
        p = self.palette
        self.detail.configure(font=self._mono_small)
        self.detail.tag_configure("label", foreground=p.text_muted)
        self.detail.tag_configure("value", foreground=p.text_primary)
        self.detail.tag_configure("ok", foreground=p.ok)
        self.detail.tag_configure("bad", foreground=p.fail)
        self.detail.tag_configure("warn", foreground=p.warn)
        self.detail.tag_configure("hint", foreground=p.text_muted)

    # ------------------------------------------------------------------
    # panes
    # ------------------------------------------------------------------

    def _stack_and_pane(self, key: str) -> tuple[PaneStack, CollapsiblePane]:
        for stack in (self.columns, self.rows):
            pane = stack.pane(key)
            if pane is not None:
                return stack, pane
        raise KeyError(key)  # a typo in _pane_keys, caught on the first run

    def _pane(self, key: str) -> CollapsiblePane:
        return self._stack_and_pane(key)[1]

    def _toggle_pane(self, key: str) -> None:
        stack, pane = self._stack_and_pane(key)
        stack.toggle(pane)

    def _reset_layout(self) -> None:
        self.columns.reset()
        self.rows.reset()

    def _on_panes_moved(self) -> None:
        for key, variable in self._pane_vars.items():
            variable.set(not self._pane(key).collapsed)

    def _layout(self) -> dict:
        layout = self.settings.get("layout")
        return layout if isinstance(layout, dict) else {}

    def _maybe_restore_layout(self, _event=None) -> None:
        """Restore once, the first time the panes have room to be restored into."""
        if self._layout_restored or self.rows.paned.winfo_height() < 50:
            return
        self._layout_restored = True
        self._restore_layout()

    def _restore_layout(self) -> None:
        """Put the panes back where they were left, or lay them out fresh.

        Sizes are saved in pixels and the window size is restored first, so
        they land where they were; `PaneStack` rescales them anyway if the
        window has since been opened at a different size.
        """
        layout = self._layout()
        self.update_idletasks()
        for name, stack in (("columns", self.columns), ("rows", self.rows)):
            saved = layout.get(name)
            if isinstance(saved, dict):
                stack.restore(saved)
            else:
                stack.reset()

    def _save_layout(self) -> None:
        self.settings["layout"] = {
            "window": f"{self.winfo_width()}x{self.winfo_height()}",
            "columns": self.columns.state(),
            "rows": self.rows.state(),
        }

    # ------------------------------------------------------------------
    # profiles
    # ------------------------------------------------------------------

    def _profile_root(self) -> Path:
        """Where this profile's drafts and data-set seeds live.

        Falls back to the shared app directory if asked before a profile is
        active, which nothing after startup should ever do -- but a fallback
        that quietly writes to the right *kind* of place beats one of the
        call sites raising while a background thread is mid-request.
        """
        return profiles.profile_dir(self._profile.id) if self._profile else workspace.app_dir()

    def _resolve_startup_profile(self) -> None:
        """The one-time decision of who is using the app this launch.

        Silent unless there is a genuine decision to make: a returning
        profile is resumed exactly as the window used to just open, and the
        picker only appears the very first time, when there is nobody to
        resume. Switching later is a deliberate menu action, not something
        every launch interrupts you to ask about.
        """
        current = profiles.current_profile()
        if current is None:
            current = choose_profile(self, self.palette, allow_cancel=False)
        self._activate_profile(current)
        self._load_library()

    def _switch_profile(self) -> None:
        chosen = choose_profile(self, self.palette, allow_cancel=True)
        if chosen is None or (self._profile is not None and chosen.id == self._profile.id):
            return
        self._save_draft(force=True)  # flush the outgoing profile's work first
        self._activate_profile(chosen)
        self._load_library()

    def _activate_profile(self, profile: profiles.Profile) -> None:
        self._profile = profile
        self.seeds = workspace.load_seeds(root=self._profile_root())
        self._progress = profiles.load_progress(profile.id)
        # Forces the next `_on_problem_selected` to do a real reload even if
        # the tree lands back on the problem that was already open -- its
        # draft and data set belong to whoever was using the app before.
        self._problem = None
        self._refresh_profile_label()
        self.profile_menu.entryconfigure(
            0, label=t("app.menu.profile.current", username=profile.username))

    def _refresh_profile_label(self) -> None:
        if self._profile is None:
            self.profile_label.configure(text="")
            return
        solved = sum(1 for p in self._library.problems
                    if self._progress.get(p.id, {}).get("solved"))
        total = len(self._library.problems)
        note = (t("app.statusbar.solved_note", solved=solved, total=total) if total
                else t("app.statusbar.no_problems_loaded"))
        self.profile_label.configure(
            text=t("app.statusbar.profile_status", username=self._profile.username, note=note))

    def _record_progress(self, problem_id: str, result: SubmissionResult) -> None:
        """Log one Go against the active profile's record for this problem.

        Keyed by the id passed in from the run itself, not `self._problem` --
        the candidate may have already moved to another problem while this
        one was still building, and the attempt belongs to the problem it was
        actually run against.
        """
        if self._profile is None:
            return
        entry = profiles.record_attempt(
            self._profile.id, problem_id,
            passed=result.all_passed, summary=result.summary())
        self._progress[problem_id] = entry
        self._update_progress_badge(problem_id)
        self._refresh_profile_label()

    # ------------------------------------------------------------------
    # library loading
    # ------------------------------------------------------------------

    def _load_library(self) -> None:
        self._save_draft(force=True)
        self._library = load_library(self.problems_root)
        self._verification.clear()
        self._requested.clear()
        # Reloading re-reads the problem files, so the Problem objects holding
        # the current data sets are gone. Seeds survive, so the same cases come
        # straight back -- but they have to be built again.
        self._generation.clear()
        self._problem = None

        present = self._library.languages_present
        names = [languages.get(lid).display_name for lid in present]
        all_languages = t("app.toolbar.all_languages")
        self.language_box.configure(values=[all_languages] + names)
        if not self.language_var.get() or self.language_var.get() not in [all_languages] + names:
            self.language_var.set(names[0] if len(names) == 1 else all_languages)

        self._refresh_toolchain_label()
        self._populate_problem_tree()
        # Covers the case where the tree ended up with nothing to select, so
        # `_on_problem_selected` never ran to do this itself.
        self._refresh_guides_menu()
        self._refresh_profile_label()

        for problem in self._library.problems:
            self._request_preparation(problem, priority=5, with_data=False)

        if self._library.errors:
            errors = "\n".join(t("app.dialog.bullet_line", error=e)
                               for e in self._library.errors[:12])
            messagebox.showwarning(
                t("app.dialog.problem_files_skipped_title"),
                t("app.dialog.problem_files_skipped_message", errors=errors),
                parent=self,
            )

        if not self._library.problems:
            messagebox.showinfo(
                t("app.dialog.no_problems_found_title"),
                t("app.dialog.no_problems_found_message", root=self.problems_root),
                parent=self,
            )

    def _populate_problem_tree(self) -> None:
        """Fill the tree for whatever the language picker currently says.

        "All" groups by language, same as always -- there is no one language
        left to subdivide by difficulty. Picking one language does exactly
        that subdividing instead: the picker has already answered "which
        language", so the grouping question left for the tree to answer is
        "how hard", which is the one a candidate picking what to attempt next
        actually has.
        """
        self.problem_tree.delete(*self.problem_tree.get_children())
        wanted = self.language_var.get()
        chosen_id = next((lid for lid in self._library.languages_present
                          if languages.get(lid).display_name == wanted), None)

        if chosen_id is not None:
            self._populate_by_difficulty(chosen_id)
        else:
            self._populate_by_language(wanted)

        first = next((p.id for p in self._library.problems
                      if self.problem_tree.exists(p.id)), None)
        remembered = self._profile.last_problem if self._profile else ""
        target = remembered if remembered and self.problem_tree.exists(remembered) else first
        if target:
            self.problem_tree.selection_set(target)
            self.problem_tree.see(target)

    def _populate_by_language(self, wanted: str) -> None:
        for language_id in self._library.languages_present:
            language = languages.get(language_id)
            if wanted not in (t("app.toolbar.all_languages"), language.display_name):
                continue
            problems = self._library.by_language(language_id)
            if not problems:
                continue
            group = self.problem_tree.insert(
                "", "end", iid=f"lang:{language_id}",
                text=t("app.tree.group_row", name=language.display_name, count=len(problems)),
                open=True, tags=("group",))
            for problem in problems:
                self._insert_problem_row(group, problem)

    def _populate_by_difficulty(self, language_id: str) -> None:
        problems = self._library.by_language(language_id)
        for difficulty in DIFFICULTIES:
            bucket = [p for p in problems if p.difficulty == difficulty]
            if not bucket:
                continue
            group = self.problem_tree.insert(
                "", "end", iid=f"diff:{difficulty}",
                text=t("app.tree.group_row", name=_difficulty_label(difficulty), count=len(bucket)),
                open=True, tags=("group",))
            for problem in bucket:
                self._insert_problem_row(group, problem)

    def _insert_problem_row(self, group: str, problem: Problem) -> None:
        self.problem_tree.insert(
            group, "end", iid=problem.id, text=t("app.tree.problem_row", title=problem.title),
            values=(self._progress_badge_for(problem.id), self._badge_for(problem.id)))

    def _badge_for(self, problem_id: str) -> str:
        if problem_id not in self._verification:
            return ""
        result = self._verification[problem_id]
        if result is None:
            return BADGE_PENDING
        if result.toolchain_missing:
            return ""  # unknown, not broken -- we never got to run the tests
        return BADGE_OK if result.all_passed else BADGE_BAD

    def _update_badge(self, problem_id: str) -> None:
        if not self.problem_tree.exists(problem_id):
            return
        badge = self._badge_for(problem_id)
        self.problem_tree.set(problem_id, "badge", badge)
        tag = {BADGE_OK: "ok", BADGE_BAD: "bad"}.get(badge, "")
        self.problem_tree.item(problem_id, tags=(tag,) if tag else ())

    def _progress_badge_for(self, problem_id: str) -> str:
        """Whether *this profile* has ever passed every test for this problem.

        Deliberately not the same column as `_badge_for`: that one is about
        the problem's own health (does the reference solution pass?), this
        one is about the candidate (have they solved it?) -- two different
        questions that happen to both render as a small glyph.
        """
        return PROGRESS_SOLVED if self._progress.get(problem_id, {}).get("solved") else ""

    def _update_progress_badge(self, problem_id: str) -> None:
        if self.problem_tree.exists(problem_id):
            self.problem_tree.set(problem_id, "progress", self._progress_badge_for(problem_id))

    # ------------------------------------------------------------------
    # problem selection
    # ------------------------------------------------------------------

    def _on_problem_selected(self, _event=None) -> None:
        selection = self.problem_tree.selection()
        if not selection:
            return
        problem_id = selection[0]
        if problem_id.startswith(_GROUP_PREFIXES):
            return
        problem = self._library.get(problem_id)
        if problem is None or problem is self._problem:
            return

        self._save_draft(force=True)
        self._problem = problem
        if self._profile is not None:
            self._profile.last_problem = problem.id
            profiles.set_last_problem(self._profile.id, problem.id)

        language = problem.language
        self.title(t("app.window_title_with_problem", app_name=APP_NAME, title=problem.title))
        self.problem_title.configure(text=problem.title)
        self.problem_meta.configure(
            text=t("app.toolbar.problem_meta", language=language.display_name,
                  difficulty=_difficulty_label(problem.difficulty).lower())
                 + (t("app.toolbar.problem_meta_topics_suffix",
                      topics=", ".join(problem.topics)) if problem.topics else ""))
        self.editor_filename.configure(text=language.solution_filename)

        self._render_statement(problem)
        self.editor.set_language(language.keywords, language.line_comment)
        draft = workspace.load_draft(problem.id, Path(language.solution_filename).suffix,
                                     root=self._profile_root())
        self.editor.set_source(draft if draft is not None else problem.starter_code)
        self.editor.clear_error_marks()

        self._clear_build_output()
        self.result_label.configure(text="")
        # Queue first, so `_show_test_cases` can already see that a data set is
        # on its way and say so rather than showing a suspiciously short list.
        self._request_preparation(problem, priority=0, with_data=True)
        self._show_test_cases(problem)
        self._refresh_banner()
        self._refresh_go_button()
        self._refresh_guides_menu()
        self.editor.focus_editor()

    def _render_statement(self, problem: Problem) -> None:
        def write() -> None:
            text = self.statement
            text.insert("end", problem.title + "\n", "h1")
            in_code = False
            for raw in problem.statement.splitlines():
                line = raw.rstrip()
                if line.strip().startswith("```"):
                    in_code = not in_code
                    continue
                if in_code:
                    text.insert("end", line + "\n", "codeblock")
                elif line.startswith("## "):
                    text.insert("end", line[3:] + "\n", "h2")
                elif line.startswith("# "):
                    text.insert("end", line[2:] + "\n", "h1")
                elif line.lstrip().startswith(("- ", "* ")):
                    self._insert_inline(text, "• " + line.lstrip()[2:] + "\n",
                                        "bullet")
                else:
                    self._insert_inline(text, line + "\n", "body")
            text.configure(state="normal")

        self.statement.replace_all(write)

    def _insert_inline(self, widget: tk.Text, line: str, base_tag: str) -> None:
        """Render `backtick code` spans inside a paragraph."""
        for index, chunk in enumerate(line.split("`")):
            if not chunk:
                continue
            widget.insert("end", chunk, (base_tag, "code") if index % 2 else base_tag)

    # ------------------------------------------------------------------
    # test list
    # ------------------------------------------------------------------

    def _show_test_cases(self, problem: Problem) -> None:
        """Populate the tree *before* anything is run.

        The test cases are the specification, so they go on screen the moment a
        problem is opened rather than being revealed as a reward for running.
        """
        self.test_tree.delete(*self.test_tree.get_children())
        self._outcome_rows.clear()
        self._pending_tests.clear()

        for index, test in enumerate(problem.tests):
            row = f"test{index}"
            self._pending_tests[row] = test
            self.test_tree.insert(
                "", "end", iid=row,
                values=(t("app.results.not_run"), test.display_name, ""), tags=("pending",))

        if self._data_pending(problem):
            self.test_tree.insert(
                "", "end", iid="generating",
                values=("", t("app.results.randomised_building_row",
                             count=problem.generator.count), ""), tags=("pending",))

        children = self.test_tree.get_children()
        if children and children[0] != "generating":
            self.test_tree.selection_set(children[0])
        else:
            self._clear_detail()

    def _on_test_selected(self, _event=None) -> None:
        selection = self.test_tree.selection()
        if not selection:
            return
        row = selection[0]
        outcome = self._outcome_rows.get(row)
        test = outcome.test if outcome else self._pending_tests.get(row)
        if test is None:
            self._clear_detail()
            return
        self._render_detail(test, outcome)

    def _render_detail(self, test: TestCase, outcome: TestOutcome | None) -> None:
        def block(label: str, body: str, tag: str = "value") -> None:
            self.detail.insert("end", label + "\n", "label")
            shown = body if body.strip() else t("app.detail.empty_value")
            for line in shown.splitlines() or [""]:
                self.detail.insert("end", "    " + line + "\n", tag)
            self.detail.insert("end", "\n")

        def write() -> None:
            if test.description:
                self.detail.insert("end", test.description + "\n\n", "hint")
            if test.generated:
                self.detail.insert("end", t("app.detail.randomised_note"), "hint")

            if outcome is not None:
                tag = {PASS: "ok", FAIL: "bad", ERROR: "bad",
                       TIMEOUT: "warn"}.get(outcome.status, "value")
                self.detail.insert("end", _status_label(outcome.status), tag)
                if outcome.message:
                    self.detail.insert(
                        "end", t("app.detail.status_message_suffix", message=outcome.message),
                        "hint")
                self.detail.insert("end", "\n\n")

            block(t("app.detail.input_label"), test.stdin)
            block(t("app.detail.expected_label"), test.expected_stdout)

            if outcome is None:
                self.detail.insert("end", t("app.detail.press_go_hint"), "hint")
                return

            if outcome.status != SKIPPED:
                block(t("app.detail.your_output_label"), outcome.actual,
                      "ok" if outcome.passed else "bad")
            if outcome.stderr.strip():
                block(t("app.detail.stderr_label"), outcome.stderr, "warn")

        self.detail.replace_all(write)

    def _clear_detail(self) -> None:
        self.detail.replace_all(lambda: None)

    # ------------------------------------------------------------------
    # running
    # ------------------------------------------------------------------

    def _refresh_go_button(self) -> None:
        problem = self._problem
        self.new_data_button.configure(
            state="normal" if problem is not None and problem.randomised
                              and not self._running else "disabled")
        if self._running:
            self.go_button.configure(text=t("app.toolbar.stop_button"), state="normal")
            return
        blocked = problem is not None and (self._reference_blocks_run(problem)
                                           or self._data_pending(problem))
        state = "normal" if problem is not None and not blocked else "disabled"
        self.go_button.configure(text=t("app.toolbar.go_button"), state=state)

    def _reference_blocks_run(self, problem: Problem) -> bool:
        """The gate from the spec: a problem whose own reference solution fails
        its tests is broken, and running against it would waste the
        candidate's time."""
        if problem.id in self._override_gate:
            return False
        result = self._verification.get(problem.id)
        if result is None or result.toolchain_missing:
            # Not verified yet, or unverifiable on this machine. Neither means
            # the problem is broken, so leave Go enabled -- pressing it gives
            # the candidate the install instructions.
            return False
        return not result.all_passed

    def _on_go(self) -> None:
        if self._running:
            self._on_stop()
            return
        problem = self._problem
        if problem is None or self._reference_blocks_run(problem):
            return
        if self._data_pending(problem):
            # Running now would report a pass over a suite that is about to
            # grow. Better to wait the fraction of a second.
            return

        # Only pre-flight against a status already in hand. If detection is
        # still running this waits for it on the build thread instead of
        # freezing the window here -- `build()` reports the same remedy into
        # the build pane, so a missing compiler is still explained, just
        # without a dialog in front of it.
        status = problem.language.detected_toolchain()
        if status is not None and not status.available:
            self._write_build_output(status.remedy or status.detail, failed=True)
            self._show_build_tab(select=True)
            messagebox.showerror(t("app.dialog.no_compiler_available_title"), status.remedy
                                 or status.summary, parent=self)
            return

        self._save_draft(force=True)
        source = self.editor.get_source()
        self.editor.clear_error_marks()
        self._show_test_cases(problem)
        self._clear_build_output()

        self._running = True
        self._cancel.clear()
        self._refresh_go_button()
        self.progress.configure(value=0, maximum=max(len(problem.tests), 1))
        self.progress.pack(side="right", padx=(0, 12))
        self.result_label.configure(text=t("app.statusbar.building"))

        def worker() -> None:
            def progress(outcome: TestOutcome, index: int, total: int) -> None:
                self._events.put(("progress", outcome, index, total))
            result = runner.run_submission(problem, source, progress, self._cancel)
            self._events.put(("done", problem.id, result))

        threading.Thread(target=worker, daemon=True,
                         name=f"crucible-run-{problem.id}").start()

    def _on_stop(self) -> None:
        if self._running:
            self._cancel.set()
            self.result_label.configure(text=t("app.statusbar.stopping"))

    def _on_run_finished(self, problem_id: str, result: SubmissionResult) -> None:
        self._running = False
        self.progress.pack_forget()
        self._refresh_go_button()

        if not result.build.ok:
            self._write_build_output(
                result.build.output or t("app.build.build_failed_fallback"), failed=True)
            self._show_build_tab(select=True)
            self.result_label.configure(text=t("app.statusbar.build_failed"))
            self._mark_all_pending_as(t("app.results.not_run"))
            self._record_progress(problem_id, result)
            return

        self._write_build_output(
            result.build.output or t("app.build.compiled_no_warnings"),
            failed=False, command=result.build.command)
        # The tab is there to be read if a warning needs chasing, but the
        # results are what was asked for, so they stay in front.
        self._show_build_tab(select=False)

        summary = result.summary()
        self.result_label.configure(text=summary)
        if result.all_passed:
            self._flash_banner(t("app.banner.all_passed", total=result.total),
                               self.palette.ok)
        else:
            failed = result.total - result.passed
            self._flash_banner(t("app.banner.summary_to_go", summary=summary, failed=failed),
                               self.palette.fail)

        self._record_progress(problem_id, result)

        first_failure = next((row for row, o in self._outcome_rows.items()
                              if not o.passed), None)
        if first_failure:
            self.test_tree.selection_set(first_failure)
            self.test_tree.see(first_failure)

    def _mark_all_pending_as(self, label: str) -> None:
        for row in self.test_tree.get_children():
            if row not in self._outcome_rows:
                self.test_tree.set(row, "status", label)

    def _apply_progress(self, outcome: TestOutcome, index: int, total: int) -> None:
        row = f"test{index - 1}"
        if not self.test_tree.exists(row):
            return
        self._outcome_rows[row] = outcome
        self.test_tree.item(
            row,
            values=(_status_label(outcome.status),
                    outcome.test.display_name,
                    t("app.results.duration_ms", ms=outcome.duration * 1000)
                    if outcome.duration else ""),
            tags=(outcome.status,))
        self.progress.configure(value=index)
        self.result_label.configure(text=t("app.statusbar.running_test", index=index, total=total))
        if self.test_tree.selection() and self.test_tree.selection()[0] == row:
            self._render_detail(outcome.test, outcome)

    # ------------------------------------------------------------------
    # randomised data sets
    # ------------------------------------------------------------------

    def _seed_for(self, problem_id: str) -> int:
        """The data set this problem is on, minting one the first time.

        Seeds are remembered on disk so that a problem you come back to
        tomorrow still has the cases you were reading yesterday.
        """
        seed = self.seeds.get(problem_id)
        if seed is None:
            seed = randomise.new_seed()
            self.seeds[problem_id] = seed
            workspace.save_seeds(self.seeds, root=self._profile_root())
        return seed

    def _data_pending(self, problem: Problem) -> bool:
        """True while this problem's randomised cases are still being built."""
        return problem.randomised and self._generation.get(problem.id) is None

    def _on_new_data(self) -> None:
        """Reshuffle: a new data set for the current problem.

        The draft is left alone. The point of a new data set is to re-solve the
        same problem against numbers you have not seen, not to start over.
        """
        problem = self._problem
        if problem is None or not problem.randomised or self._running:
            return

        self.seeds[problem.id] = randomise.new_seed()
        workspace.save_seeds(self.seeds, root=self._profile_root())

        problem.generated_tests = ()
        problem.seed = None
        self._generation.pop(problem.id, None)
        self._verification.pop(problem.id, None)
        self._requested.discard((problem.id, True))

        self._request_preparation(problem, priority=0, with_data=True)
        self._show_test_cases(problem)
        self._update_badge(problem.id)
        self._refresh_banner()
        self._refresh_go_button()

    def _on_generated(self, problem_id: str, suite: GeneratedSuite) -> None:
        self._generation[problem_id] = suite
        if self._problem is None or self._problem.id != problem_id:
            return
        if not self._running:
            self._show_test_cases(self._problem)
        self._refresh_banner()
        self._refresh_go_button()

    # ------------------------------------------------------------------
    # reference verification
    # ------------------------------------------------------------------

    def _start_verify_worker(self) -> None:
        """One background thread prepares problems: build the data set, then
        verify the reference against the suite that data set came out of.

        Both steps belong to the same job because the second is a statement
        about the first -- verifying a suite before its randomised half exists
        would be verifying something nobody is going to be asked to solve.

        `with_data` is what keeps the two apart. The background sweep that
        badges the whole library asks for verification only: data sets are
        built for the problem someone is actually looking at, not for ten
        others they may never open. Building all of them up front would put a
        compile-and-run of every problem in front of the one that matters.
        """
        def worker() -> None:
            while True:
                _priority, _seq, problem_id, with_data = self._verify_queue.get()
                if problem_id is None:
                    return
                problem = self._library.get(problem_id)
                if problem is None:
                    continue
                if with_data and self._data_pending(problem):
                    suite = randomise.generate(problem, self.seeds[problem_id])
                    # Sole writer of these two fields; the UI thread only reads
                    # them after the event below has been handed over.
                    randomise.apply(problem, suite)
                    self._events.put(("generated", problem_id, suite))
                # A with_data job always re-verifies: the suite it just built
                # is not the one any earlier pass looked at.
                if with_data or self._verification.get(problem_id) is None:
                    result = runner.verify_reference(problem)
                    self._events.put(("verified", problem_id, result))

        self._verify_thread = threading.Thread(target=worker, daemon=True,
                                               name="crucible-verify")
        self._verify_thread.start()

    def _request_preparation(self, problem: Problem, priority: int,
                             with_data: bool) -> None:
        """Queue a problem for the worker. `priority` 0 is user-driven (the
        problem just opened), higher numbers are the background sweep.

        The two kinds of request are tracked separately, so opening a problem
        the sweep has already badged still gets its data set built -- and a
        priority-0 entry jumps whatever the sweep has left to do, rather than
        leaving the banner on "checking..." while unrelated problems compile.
        """
        if (problem.id, with_data) in self._requested:
            return
        self._requested.add((problem.id, with_data))

        if with_data and problem.randomised:
            self._generation.setdefault(problem.id, None)
            self._seed_for(problem.id)  # minted here so only this thread writes
            # Any earlier verdict was about a suite this problem is about to
            # stop having, so the banner goes back to "checking".
            self._verification[problem.id] = None
        else:
            self._verification.setdefault(problem.id, None)

        self._verify_queue.put((priority, next(self._verify_seq),
                                problem.id, with_data))
        self._update_badge(problem.id)

    def _on_verified(self, problem_id: str, result: SubmissionResult) -> None:
        self._verification[problem_id] = result
        self._update_badge(problem_id)
        if self._problem is not None and self._problem.id == problem_id:
            self._refresh_banner()
            self._refresh_go_button()

    def _refresh_banner(self) -> None:
        problem = self._problem
        self.banner_button.grid_remove()
        if problem is None:
            self.banner.configure(text="", background=self.palette.panel_bg)
            return

        result = self._verification.get(problem.id, "missing")
        visible = len(problem.visible_tests)
        hidden = len(problem.tests) - visible

        if self._data_pending(problem):
            self.banner.configure(
                text=t("app.banner.building_data_set", seed=self._seed_for(problem.id)),
                background=self.palette.panel_bg,
                foreground=self.palette.text_muted)
            return

        if result == "missing" or result is None:
            self.banner.configure(
                text=t("app.banner.checking_suite"),
                background=self.palette.panel_bg,
                foreground=self.palette.text_muted)
            return

        suite = self._generation.get(problem.id)
        if suite is not None and suite.error:
            # A broken generator is the author's problem, not the candidate's,
            # and it does not disable anything: the hand-written cases are
            # still perfectly good tests.
            self.banner.configure(
                text=t("app.banner.generator_unavailable", error=suite.error,
                      count=len(problem.fixed_tests)),
                background=self.palette.panel_bg,
                foreground=self.palette.warn)
            return

        suffix = t("app.banner.hidden_suffix", count=hidden) if hidden else ""
        if result.toolchain_missing:
            # Nothing is wrong with the problem -- this machine just has no
            # compiler for it yet. Say so, and say where to fix it.
            self.banner.configure(
                text=t("app.banner.no_compiler_installed",
                      language=problem.language.display_name),
                background=self.palette.panel_bg,
                foreground=self.palette.warn)
        elif result.all_passed:
            self.banner.configure(
                text=t("app.banner.verified", badge=BADGE_OK, total=result.total,
                      suffix=suffix, visible=visible,
                      note=self._data_set_note(problem)),
                background=self.palette.panel_bg, foreground=self.palette.ok)
        else:
            detail = (result.build.output.splitlines()[0]
                      if not result.build.ok and result.build.output
                      else t("app.banner.passed_fraction", passed=result.passed,
                            total=result.total))
            self.banner.configure(
                text=t("app.banner.disabled", badge=BADGE_BAD, detail=detail),
                background=self.palette.panel_bg, foreground=self.palette.fail)
            self.banner_button.grid(row=0, column=1, padx=(8, 0))

    def _data_set_note(self, problem: Problem) -> str:
        """The tail of the verified banner for a problem with random data."""
        if not problem.generated_tests:
            return ""
        return t("app.banner.data_set_note", count=len(problem.generated_tests),
                 seed=problem.seed)

    def _override_reference_gate(self) -> None:
        if self._problem is None:
            return
        self._override_gate.add(self._problem.id)
        self._refresh_banner()
        self._refresh_go_button()
        self.banner_button.grid_remove()

    def _flash_banner(self, message: str, colour: str) -> None:
        self.banner.configure(text=message, foreground=colour)
        self.after(4000, self._refresh_banner)

    def _verify_all(self) -> None:
        self._override_gate.clear()
        self._requested.clear()
        self._verification.clear()
        for problem in self._library.problems:
            self._request_preparation(problem, priority=1, with_data=True)
        self.result_label.configure(
            text=t("app.statusbar.verifying_problems", count=len(self._library.problems)))

    # ------------------------------------------------------------------
    # build output
    # ------------------------------------------------------------------

    def _clear_build_output(self) -> None:
        self.build_output.replace_all(lambda: None)
        if self._build_tab_shown:
            self.notebook.select(self.tests_tab)  # hiding the selected tab
            self.notebook.hide(self.build_tab)
            self._build_tab_shown = False

    def _show_build_tab(self, select: bool) -> None:
        """Bring the build output back, once there is a build to talk about.

        `add` on a hidden tab restores it where it was, so it always reappears
        to the right of the tests rather than wherever it was last hidden from.
        """
        if not self._build_tab_shown:
            self.notebook.add(self.build_tab)
            self._build_tab_shown = True
        self.notebook.select(self.build_tab if select else self.tests_tab)

    def _write_build_output(self, text: str, failed: bool,
                            command: str = "") -> None:
        def write() -> None:
            if command:
                self.build_output.insert("end", t("app.build.command_line", command=command), "muted")
            for line in text.splitlines():
                lowered = line.lower()
                tag = ("err" if "error" in lowered
                       else "warn" if "warning" in lowered else "")
                self.build_output.insert("end", line + "\n", tag)
            if not failed and "warning" not in text.lower():
                self.build_output.insert("end", t("app.build.succeeded"), "muted")

        self.build_output.replace_all(write)

    # ------------------------------------------------------------------
    # event pump
    # ------------------------------------------------------------------

    def _pump(self) -> None:
        try:
            while True:
                message = self._events.get_nowait()
                kind = message[0]
                if kind == "progress":
                    self._apply_progress(message[1], message[2], message[3])
                elif kind == "done":
                    self._on_run_finished(message[1], message[2])
                elif kind == "verified":
                    self._on_verified(message[1], message[2])
                elif kind == "generated":
                    self._on_generated(message[1], message[2])
                elif kind == "toolchain":
                    self._on_toolchain_detected(message[1], message[2])
        except queue.Empty:
            pass
        self.after(60, self._pump)

    # ------------------------------------------------------------------
    # drafts, settings, misc actions
    # ------------------------------------------------------------------

    def _on_code_changed(self, _event=None) -> None:
        if not self.settings.get("autosave", True):
            return
        if self._autosave_job is not None:
            self.after_cancel(self._autosave_job)
        self._autosave_job = self.after(1200, self._save_draft)

    def _save_draft(self, force: bool = False) -> None:
        self._autosave_job = None
        if self._problem is None:
            return
        if not force and not self.settings.get("autosave", True):
            return
        suffix = Path(self._problem.language.solution_filename).suffix
        workspace.save_draft(self._problem.id, suffix, self.editor.get_source(),
                             root=self._profile_root())

    def _reset_to_starter(self) -> None:
        if self._problem is None:
            return
        if not messagebox.askyesno(
                t("app.dialog.reset_code_title"),
                t("app.dialog.reset_code_message"), parent=self):
            return
        suffix = Path(self._problem.language.solution_filename).suffix
        workspace.clear_draft(self._problem.id, suffix, root=self._profile_root())
        self.editor.set_source(self._problem.starter_code)
        self.editor.clear_error_marks()

    def _toggle_theme(self) -> None:
        self.settings["theme"] = "light" if self.palette.name == "dark" else "dark"
        workspace.save_settings(self.settings)
        messagebox.showinfo(
            t("app.dialog.theme_changed_title"),
            t("app.dialog.theme_changed_message", app_name=APP_NAME),
            parent=self)

    def _set_locale(self, locale: str) -> None:
        """Save which locale to start in next time -- deliberately not a
        live re-render. Every menu, dialog and pane title already on screen
        was built once, at startup, from `t(...)` calls; re-doing that for a
        window this size, mid-session, without leaving something half
        updated, is a lot of machinery for what `_apply_saved_locale` (see
        `crucible.__main__`) already gets for free on the next launch. The
        radiobutton itself still flips immediately, via `self.locale_var`,
        so the choice reads back correctly without needing the rest of the
        window to follow it."""
        self.settings["locale"] = locale
        workspace.save_settings(self.settings)
        messagebox.showinfo(
            t("app.dialog.language_changed_title"),
            t("app.dialog.language_changed_message",
              language=i18n.locale_display_name(locale), app_name=APP_NAME),
            parent=self)

    def _change_font(self, delta: int) -> None:
        size = max(8, min(22, self.settings["font_size"] + delta))
        self.settings["font_size"] = size
        workspace.save_settings(self.settings)
        self.editor._font.configure(size=size)
        self.editor.text.configure(
            tabs=(self.editor._font.measure(" " * 4),))

    def _recheck_toolchains(self) -> None:
        """Tools → re-check. Same slow detection, so same background treatment.

        The report is not shown here: `_on_toolchain_detected` puts it up once
        the last language has actually finished, rather than describing state
        that is still being looked up.
        """
        self._pending_toolchain_report = True
        for language in languages.all_languages():
            self._detect_toolchain_async(language.id, refresh=True)
        self._refresh_toolchain_label()

    def _refresh_toolchain_label(self) -> None:
        """Show each language's toolchain, detecting anything unknown off-thread.

        This runs as part of loading the library, which happens during
        startup. Detection can take ten seconds -- locating MSVC shells out to
        vcvars64.bat -- so asking for it inline here would freeze the window
        for the whole of it before anything was on screen. Instead the label
        goes up immediately with "detecting…" against whatever is not known
        yet, and `_on_toolchain_detected` fills it in when the answer lands.
        """
        parts, missing = [], False
        pending: list[str] = []
        for language_id in self._library.languages_present or languages.known_ids():
            language = languages.get(language_id)
            status = language.detected_toolchain()
            if status is None:
                if language_id in self._detect_failed:
                    parts.append(t("app.statusbar.detection_failed", name=language.display_name))
                    missing = True
                    continue
                pending.append(language_id)
                parts.append(t("app.statusbar.detecting", name=language.display_name))
                continue
            parts.append(status.summary)
            missing = missing or not status.available
        self.toolchain_label.configure(
            text=t("app.statusbar.separator").join(parts) or t("app.statusbar.no_languages_registered"),
            foreground=self.palette.warn if missing else self.palette.text_muted)
        for language_id in pending:
            self._detect_toolchain_async(language_id)

    def _detect_toolchain_async(self, language_id: str, refresh: bool = False) -> None:
        """Run one language's detection on a thread, reporting back via `_pump`.

        `Language.toolchain` is itself locked, so a detection the verify worker
        has already started is waited on rather than duplicated.
        """
        if language_id in self._detecting:
            return
        self._detecting.add(language_id)
        self._detect_failed.discard(language_id)

        def worker() -> None:
            failed = False
            try:
                languages.get(language_id).toolchain(refresh=refresh)
            except Exception:
                # A plugin's detection is not supposed to raise -- the ones
                # here catch their own subprocess errors -- but if one does,
                # its status stays None, and a label that treated that as
                # "still unknown" would dispatch another thread for it every
                # time it refreshed. Record the failure so it settles instead.
                failed = True
            finally:
                # Reported even on failure, or the label would sit on
                # "detecting…" forever with nothing left to clear it.
                self._events.put(("toolchain", language_id, failed))

        threading.Thread(target=worker, daemon=True,
                         name=f"crucible-toolchain-{language_id}").start()

    def _on_toolchain_detected(self, language_id: str, failed: bool = False) -> None:
        self._detecting.discard(language_id)
        if failed:
            self._detect_failed.add(language_id)
        # Everything not yet known is already in flight, so this settles rather
        # than starting another round.
        self._refresh_toolchain_label()
        if self._pending_toolchain_report and not self._detecting:
            # A re-check that has now finished for every language.
            self._pending_toolchain_report = False
            self._verify_all()
            self._show_toolchains()

    def _show_toolchains(self) -> None:
        lines = []
        for language in languages.all_languages():
            status = language.detected_toolchain()
            if status is None:
                # Still being looked up. Saying so beats blocking the window
                # on it just to fill in one line of a dialog.
                lines.append(t("app.dialog.compiler_status_detecting_line",
                              badge=BADGE_BAD, language=language.display_name))
                lines.append("")
                continue
            mark = BADGE_OK if status.available else BADGE_BAD
            lines.append(t("app.dialog.compiler_status_line", mark=mark,
                          language=language.display_name, summary=status.summary))
            if status.detail:
                lines.append("    " + status.detail.replace("\n", "\n    "))
            if not status.available and status.remedy:
                lines.append("")
                lines.append(status.remedy)
            lines.append("")
        messagebox.showinfo(t("app.menu.help.compiler_status"), "\n".join(lines).strip(), parent=self)

    def _show_authoring_help(self) -> None:
        messagebox.showinfo(
            t("app.menu.help.authoring"),
            t("app.dialog.authoring_help_message", root=self.problems_root),
            parent=self)

    # ------------------------------------------------------------------
    # guides
    # ------------------------------------------------------------------

    def _refresh_guides_menu(self) -> None:
        """Grey out a guide the current problem does not ship.

        A problem without guides is not broken, so the entries are disabled
        rather than hidden -- the menu stays the same shape, and it is obvious
        that the pages are a thing that could exist here.
        """
        available = guides.find_all(self._problem) if self._problem else {}
        for index, kind in enumerate(self._guide_order):
            self.guides_menu.entryconfigure(
                index, state="normal" if kind in available else "disabled")

    def _open_guide(self, kind: str) -> None:
        problem = self._problem
        if problem is None:
            return

        guide = guides.find(problem, kind)
        if guide is None:
            path = guides.guide_path(problem, kind)
            kind_lower = guides.kind_label(kind).lower()
            messagebox.showinfo(
                t("app.dialog.no_guide_title", kind=kind_lower),
                t("app.dialog.no_guide_message", title=problem.title,
                  kind=kind_lower, path=path),
                parent=self)
            return

        if kind == guides.SOLUTION and not self._confirm_reveal(problem):
            return

        if not guides.open_in_browser(guide):
            messagebox.showerror(
                t("app.dialog.could_not_open_guide_title"),
                t("app.dialog.could_not_open_guide_message", path=guide.path),
                parent=self)

    def _confirm_reveal(self, problem: Problem) -> bool:
        """Ask once per problem before showing the whole answer.

        The app's one rule is that the reference solution is never shown. A
        worked solution is a deliberate exception to that, so it is worth
        making it a deliberate act -- and worth pointing at the hint, which is
        what most people actually wanted.
        """
        if problem.id in self._revealed:
            return True
        has_hint = guides.find(problem, guides.HINT) is not None
        nudge = t("app.dialog.show_solution_hint_nudge") if has_hint else ""
        if not messagebox.askyesno(
                t("app.dialog.show_solution_title"),
                t("app.dialog.show_solution_message", title=problem.title, nudge=nudge),
                parent=self):
            return False
        self._revealed.add(problem.id)
        return True

    def _show_guides_help(self) -> None:
        messagebox.showinfo(
            t("app.dialog.guides_help_title"),
            t("app.dialog.guides_help_message"),
            parent=self)

    def _show_about(self) -> None:
        username = self._profile.username if self._profile else t("app.dialog.about_no_profile")
        messagebox.showinfo(
            t("app.dialog.about_title", app_name=APP_NAME),
            t("app.dialog.about_message", app_name=APP_NAME,
              problems_root=self.problems_root, username=username,
              profile_root=self._profile_root(),
              python_version=sys.version.split()[0]),
            parent=self)

    def _open_folder(self, path: Path) -> None:
        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror(t("app.dialog.could_not_open_folder_title"), str(exc), parent=self)

    def _on_close(self) -> None:
        self._save_draft(force=True)
        self._save_layout()
        workspace.save_settings(self.settings)
        self._cancel.set()
        self.destroy()

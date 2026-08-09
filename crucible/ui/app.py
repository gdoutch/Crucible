"""The Crucible main window."""

from __future__ import annotations

import itertools
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from .. import guides, languages, randomise, runner, workspace
from ..problem import Library, Problem, TestCase, load_library
from ..randomise import GeneratedSuite
from ..runner import ERROR, FAIL, PASS, SKIPPED, TIMEOUT, SubmissionResult, TestOutcome
from .editor import CodeEditor, mono_font
from .theme import PALETTES, Palette, apply_theme

#: Single source of truth for the product name -- window title, wordmark and
#: every dialog read from here.
APP_NAME = "Crucible"

BADGE_OK = "✓"       # check mark
BADGE_BAD = "✗"      # ballot X
BADGE_PENDING = "…"  # ellipsis

STATUS_LABEL = {
    PASS: "PASS", FAIL: "FAIL", ERROR: "ERROR",
    TIMEOUT: "TIMEOUT", SKIPPED: "skipped",
}


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
        self.seeds = workspace.load_seeds()
        self.palette: Palette = PALETTES.get(self.settings["theme"], PALETTES["dark"])

        self.title(APP_NAME)
        self.geometry("1320x880")
        self.minsize(1040, 700)

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

        self._build_menu()
        self._build_toolbar()
        self._build_body()
        self._build_statusbar()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<F5>", lambda _e: self._on_go())
        self.bind("<Control-Return>", lambda _e: self._on_go())
        self.bind("<Control-s>", lambda _e: self._save_draft(force=True))
        self.bind("<Control-r>", lambda _e: self._on_new_data())
        self.bind("<F1>", lambda _e: self._open_guide(guides.HINT))

        self._start_verify_worker()
        self.after(60, self._pump)
        self.after(10, self._load_library)

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
        file_menu.add_command(label="Save draft\tCtrl+S",
                              command=lambda: self._save_draft(force=True))
        file_menu.add_command(label="Reset to starter code",
                              command=self._reset_to_starter)
        file_menu.add_separator()
        file_menu.add_command(label="Reload problems", command=self._load_library)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        run_menu = tk.Menu(menubar, tearoff=0, **opts)
        run_menu.add_command(label="Go -- run all tests\tF5", command=self._on_go)
        run_menu.add_command(label="Stop", command=self._on_stop)
        run_menu.add_separator()
        run_menu.add_command(label="New data set\tCtrl+R", command=self._on_new_data)
        menubar.add_cascade(label="Run", menu=run_menu)

        # Guides open in the browser rather than in a pane: they are documents,
        # and the point of reading one is to have it beside the editor rather
        # than on top of it.
        self.guides_menu = tk.Menu(menubar, tearoff=0, **opts)
        self.guides_menu.add_command(
            label="Hint for this problem\tF1",
            command=lambda: self._open_guide(guides.HINT))
        self.guides_menu.add_command(
            label="Worked solution for this problem…",
            command=lambda: self._open_guide(guides.SOLUTION))
        self.guides_menu.add_separator()
        self.guides_menu.add_command(label="What are these?",
                                     command=self._show_guides_help)
        menubar.add_cascade(label="Guides", menu=self.guides_menu)

        view_menu = tk.Menu(menubar, tearoff=0, **opts)
        view_menu.add_command(label="Toggle light / dark theme",
                              command=self._toggle_theme)
        view_menu.add_command(label="Larger editor font",
                              command=lambda: self._change_font(1))
        view_menu.add_command(label="Smaller editor font",
                              command=lambda: self._change_font(-1))
        menubar.add_cascade(label="View", menu=view_menu)

        tools_menu = tk.Menu(menubar, tearoff=0, **opts)
        tools_menu.add_command(label="Re-check compilers",
                               command=self._recheck_toolchains)
        tools_menu.add_command(label="Verify every problem's reference solution",
                               command=self._verify_all)
        tools_menu.add_separator()
        tools_menu.add_command(label="Open problems folder",
                               command=lambda: self._open_folder(self.problems_root))
        tools_menu.add_command(label="Open drafts folder",
                               command=lambda: self._open_folder(workspace.drafts_dir()))
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0, **opts)
        help_menu.add_command(label="Compiler status", command=self._show_toolchains)
        help_menu.add_command(label="Writing your own problems",
                              command=self._show_authoring_help)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.configure(menu=menubar)
        self._refresh_guides_menu()

    def _build_toolbar(self) -> None:
        bar = ttk.Frame(self, padding=(12, 10, 12, 6))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text=APP_NAME.upper(), style="Brand.TLabel").pack(
            side="left", padx=(0, 12))
        ttk.Separator(bar, orient="vertical").pack(side="left", fill="y",
                                                   padx=(0, 12), pady=2)

        ttk.Label(bar, text="Language").pack(side="left")
        self.language_var = tk.StringVar()
        self.language_box = ttk.Combobox(bar, textvariable=self.language_var,
                                         state="readonly", width=12)
        self.language_box.pack(side="left", padx=(6, 16))
        self.language_box.bind("<<ComboboxSelected>>",
                               lambda _e: self._populate_problem_tree())

        self.problem_title = ttk.Label(bar, text="No problem selected",
                                       style="Heading.TLabel")
        self.problem_title.pack(side="left")
        self.problem_meta = ttk.Label(bar, text="", style="Muted.TLabel")
        self.problem_meta.pack(side="left", padx=(10, 0))

        self.go_button = ttk.Button(bar, text="▶  Go", style="Run.TButton",
                                    command=self._on_go, state="disabled")
        self.go_button.pack(side="right")
        ttk.Button(bar, text="Reset", command=self._reset_to_starter).pack(
            side="right", padx=(0, 8))
        self.new_data_button = ttk.Button(bar, text="New data",
                                          command=self._on_new_data,
                                          state="disabled")
        self.new_data_button.pack(side="right", padx=(0, 8))

    def _build_body(self) -> None:
        outer = ttk.PanedWindow(self, orient="horizontal")
        outer.pack(side="top", fill="both", expand=True, padx=12, pady=(0, 6))

        outer.add(self._build_problem_list(outer), weight=0)

        right = ttk.PanedWindow(outer, orient="vertical")
        outer.add(right, weight=4)

        right.add(self._build_statement(right), weight=2)
        right.add(self._build_editor(right), weight=4)
        right.add(self._build_results(right), weight=3)

    def _build_problem_list(self, master) -> ttk.Frame:
        frame = ttk.Frame(master, width=260)
        frame.pack_propagate(False)

        ttk.Label(frame, text="PROBLEMS", style="Muted.TLabel").pack(
            anchor="w", pady=(0, 6))

        self.problem_tree = ttk.Treeview(frame, columns=("badge",),
                                         show="tree headings", selectmode="browse")
        self.problem_tree.heading("#0", text="Problem")
        self.problem_tree.heading("badge", text="")
        self.problem_tree.column("#0", width=195, stretch=True)
        self.problem_tree.column("badge", width=34, anchor="center", stretch=False)

        scroll = ttk.Scrollbar(frame, orient="vertical",
                               command=self.problem_tree.yview)
        self.problem_tree.configure(yscrollcommand=scroll.set)
        self.problem_tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        self.problem_tree.tag_configure("group", foreground=self.palette.text_muted)
        self.problem_tree.tag_configure("ok", foreground=self.palette.ok)
        self.problem_tree.tag_configure("bad", foreground=self.palette.fail)
        self.problem_tree.bind("<<TreeviewSelect>>", self._on_problem_selected)
        return frame

    def _build_statement(self, master) -> ttk.Frame:
        frame = ttk.Frame(master)
        ttk.Label(frame, text="THE PROBLEM", style="Muted.TLabel").pack(
            anchor="w", pady=(4, 4))

        holder = ttk.Frame(frame, style="Panel.TFrame")
        holder.pack(fill="both", expand=True)

        self.statement = _ReadOnlyText(holder, self.palette, height=8)
        scroll = ttk.Scrollbar(holder, orient="vertical",
                               command=self.statement.yview)
        self.statement.configure(yscrollcommand=scroll.set)
        self.statement.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configure_statement_tags()
        return frame

    def _build_editor(self, master) -> ttk.Frame:
        frame = ttk.Frame(master)
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(6, 4))
        ttk.Label(header, text="YOUR SOLUTION", style="Muted.TLabel").pack(side="left")
        self.editor_filename = ttk.Label(header, text="", style="Muted.TLabel")
        self.editor_filename.pack(side="right")

        self.editor = CodeEditor(frame, self.palette, self.settings["font_size"])
        self.editor.pack(fill="both", expand=True)
        self.editor.text.bind("<<TextChanged>>", self._on_code_changed, add="+")
        return frame

    def _build_results(self, master) -> ttk.Frame:
        frame = ttk.Frame(master)

        self.banner = tk.Label(frame, text="", anchor="w", padx=10, pady=6,
                               background=self.palette.panel_bg,
                               foreground=self.palette.text_muted)
        self.banner.pack(fill="x", pady=(6, 0))
        self.banner_button = ttk.Button(frame, text="Run anyway",
                                        command=self._override_reference_gate)

        self.notebook = ttk.Notebook(frame)
        self.notebook.pack(fill="both", expand=True, pady=(6, 0))

        tests_tab = ttk.Frame(self.notebook)
        self.notebook.add(tests_tab, text="Unit Tests")

        split = ttk.PanedWindow(tests_tab, orient="horizontal")
        split.pack(fill="both", expand=True)

        left = ttk.Frame(split)
        split.add(left, weight=3)
        self.test_tree = ttk.Treeview(
            left, columns=("status", "name", "time"), show="headings",
            selectmode="browse")
        self.test_tree.heading("status", text="Result")
        self.test_tree.heading("name", text="Test case")
        self.test_tree.heading("time", text="Time")
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
        self.detail = _ReadOnlyText(detail_holder, self.palette, wrap="none")
        dscroll = ttk.Scrollbar(detail_holder, orient="vertical",
                                command=self.detail.yview)
        self.detail.configure(yscrollcommand=dscroll.set)
        self.detail.pack(side="left", fill="both", expand=True)
        dscroll.pack(side="right", fill="y")
        self._configure_detail_tags()

        build_tab = ttk.Frame(self.notebook)
        self.notebook.add(build_tab, text="Build Output")
        self.build_output = _ReadOnlyText(build_tab, self.palette, wrap="none",
                                          font=self._mono_small)
        bscroll = ttk.Scrollbar(build_tab, orient="vertical",
                                command=self.build_output.yview)
        self.build_output.configure(yscrollcommand=bscroll.set)
        self.build_output.pack(side="left", fill="both", expand=True)
        bscroll.pack(side="right", fill="y")
        self.build_output.tag_configure("err", foreground=self.palette.fail)
        self.build_output.tag_configure("warn", foreground=self.palette.warn)
        self.build_output.tag_configure("muted", foreground=self.palette.text_muted)
        return frame

    def _build_statusbar(self) -> None:
        bar = ttk.Frame(self, style="Panel.TFrame", padding=(12, 6))
        bar.pack(side="bottom", fill="x")

        self.toolchain_label = ttk.Label(bar, text="Checking compilers…",
                                         style="Status.TLabel")
        self.toolchain_label.pack(side="left")

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
        self.language_box.configure(values=["All"] + names)
        if not self.language_var.get() or self.language_var.get() not in ["All"] + names:
            self.language_var.set(names[0] if len(names) == 1 else "All")

        self._refresh_toolchain_label()
        self._populate_problem_tree()
        # Covers the case where the tree ended up with nothing to select, so
        # `_on_problem_selected` never ran to do this itself.
        self._refresh_guides_menu()

        for problem in self._library.problems:
            self._request_preparation(problem, priority=5, with_data=False)

        if self._library.errors:
            messagebox.showwarning(
                "Problem files skipped",
                "These files could not be loaded:\n\n"
                + "\n".join(f"• {e}" for e in self._library.errors[:12]),
                parent=self,
            )

        if not self._library.problems:
            messagebox.showinfo(
                "No problems found",
                f"No problem files were found under:\n{self.problems_root}\n\n"
                "See Help → Writing your own problems.",
                parent=self,
            )

    def _populate_problem_tree(self) -> None:
        self.problem_tree.delete(*self.problem_tree.get_children())
        wanted = self.language_var.get()

        for language_id in self._library.languages_present:
            language = languages.get(language_id)
            if wanted not in ("All", language.display_name):
                continue
            problems = self._library.by_language(language_id)
            if not problems:
                continue
            group = self.problem_tree.insert(
                "", "end", iid=f"lang:{language_id}",
                text=f"{language.display_name}  ({len(problems)})",
                open=True, tags=("group",))
            for problem in problems:
                self.problem_tree.insert(
                    group, "end", iid=problem.id,
                    text=f"  {problem.title}",
                    values=(self._badge_for(problem.id),))

        first = next((p.id for p in self._library.problems
                      if self.problem_tree.exists(p.id)), None)
        remembered = self.settings.get("last_problem")
        target = remembered if remembered and self.problem_tree.exists(remembered) else first
        if target:
            self.problem_tree.selection_set(target)
            self.problem_tree.see(target)

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

    # ------------------------------------------------------------------
    # problem selection
    # ------------------------------------------------------------------

    def _on_problem_selected(self, _event=None) -> None:
        selection = self.problem_tree.selection()
        if not selection:
            return
        problem_id = selection[0]
        if problem_id.startswith("lang:"):
            return
        problem = self._library.get(problem_id)
        if problem is None or problem is self._problem:
            return

        self._save_draft(force=True)
        self._problem = problem
        self.settings["last_problem"] = problem.id

        language = problem.language
        self.title(f"{APP_NAME} — {problem.title}")
        self.problem_title.configure(text=problem.title)
        self.problem_meta.configure(
            text=f"{language.display_name}  ·  {problem.difficulty}"
                 + (f"  ·  {', '.join(problem.topics)}" if problem.topics else ""))
        self.editor_filename.configure(text=language.solution_filename)

        self._render_statement(problem)
        self.editor.set_language(language.keywords, language.line_comment)
        draft = workspace.load_draft(problem.id, Path(language.solution_filename).suffix)
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
                values=("not run", test.display_name, ""), tags=("pending",))

        if self._data_pending(problem):
            self.test_tree.insert(
                "", "end", iid="generating",
                values=("", f"building {problem.generator.count} randomised "
                            f"case(s)…", ""), tags=("pending",))

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
            shown = body if body.strip() else "(empty)"
            for line in shown.splitlines() or [""]:
                self.detail.insert("end", "    " + line + "\n", tag)
            self.detail.insert("end", "\n")

        def write() -> None:
            if test.description:
                self.detail.insert("end", test.description + "\n\n", "hint")
            if test.generated:
                self.detail.insert(
                    "end", "Randomised input. The expected output below is what "
                           "the reference solution prints for it.\n\n", "hint")

            if outcome is not None:
                tag = {PASS: "ok", FAIL: "bad", ERROR: "bad",
                       TIMEOUT: "warn"}.get(outcome.status, "value")
                self.detail.insert("end", f"{STATUS_LABEL.get(outcome.status)}", tag)
                if outcome.message:
                    self.detail.insert("end", f"  — {outcome.message}", "hint")
                self.detail.insert("end", "\n\n")

            block("INPUT (stdin)", test.stdin)
            block("EXPECTED OUTPUT", test.expected_stdout)

            if outcome is None:
                self.detail.insert(
                    "end", "Press Go to run your solution against this case.\n", "hint")
                return

            if outcome.status != SKIPPED:
                block("YOUR OUTPUT", outcome.actual,
                      "ok" if outcome.passed else "bad")
            if outcome.stderr.strip():
                block("STDERR", outcome.stderr, "warn")

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
            self.go_button.configure(text="■  Stop", state="normal")
            return
        blocked = problem is not None and (self._reference_blocks_run(problem)
                                           or self._data_pending(problem))
        state = "normal" if problem is not None and not blocked else "disabled"
        self.go_button.configure(text="▶  Go", state=state)

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

        status = problem.language.toolchain()
        if not status.available:
            self.notebook.select(1)
            self._write_build_output(status.remedy or status.detail, failed=True)
            messagebox.showerror("No compiler available", status.remedy
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
        self.result_label.configure(text="Building…")

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
            self.result_label.configure(text="Stopping…")

    def _on_run_finished(self, problem_id: str, result: SubmissionResult) -> None:
        self._running = False
        self.progress.pack_forget()
        self._refresh_go_button()

        if not result.build.ok:
            self.notebook.select(1)
            self._write_build_output(result.build.output or "Build failed.", failed=True)
            self.result_label.configure(text="Build failed")
            self._mark_all_pending_as("not run")
            return

        self._write_build_output(
            result.build.output or "Compiled with no warnings.",
            failed=False, command=result.build.command)
        self.notebook.select(0)

        summary = result.summary()
        self.result_label.configure(text=summary)
        if result.all_passed:
            self._flash_banner(f"All {result.total} tests passed — nice work.",
                               self.palette.ok)
        else:
            failed = result.total - result.passed
            self._flash_banner(f"{summary}  ({failed} to go)", self.palette.fail)

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
            values=(STATUS_LABEL.get(outcome.status, outcome.status),
                    outcome.test.display_name,
                    f"{outcome.duration * 1000:.0f} ms" if outcome.duration else ""),
            tags=(outcome.status,))
        self.progress.configure(value=index)
        self.result_label.configure(text=f"Running test {index} of {total}…")
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
            workspace.save_seeds(self.seeds)
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
        workspace.save_seeds(self.seeds)

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
        self.banner_button.pack_forget()
        if problem is None:
            self.banner.configure(text="", background=self.palette.panel_bg)
            return

        result = self._verification.get(problem.id, "missing")
        visible = len(problem.visible_tests)
        hidden = len(problem.tests) - visible

        if self._data_pending(problem):
            self.banner.configure(
                text=f"Building data set #{self._seed_for(problem.id)} — "
                     f"generating fresh inputs and asking the reference "
                     f"solution what each one should produce…",
                background=self.palette.panel_bg,
                foreground=self.palette.text_muted)
            return

        if result == "missing" or result is None:
            self.banner.configure(
                text="Checking this problem's test suite against its reference "
                     "solution…",
                background=self.palette.panel_bg,
                foreground=self.palette.text_muted)
            return

        suite = self._generation.get(problem.id)
        if suite is not None and suite.error:
            # A broken generator is the author's problem, not the candidate's,
            # and it does not disable anything: the hand-written cases are
            # still perfectly good tests.
            self.banner.configure(
                text=f"⚠  Randomised data unavailable — {suite.error}. "
                     f"The {len(problem.fixed_tests)} hand-written case(s) "
                     f"still run.",
                background=self.palette.panel_bg,
                foreground=self.palette.warn)
            return

        suffix = f" ({hidden} hidden)" if hidden else ""
        if result.toolchain_missing:
            # Nothing is wrong with the problem -- this machine just has no
            # compiler for it yet. Say so, and say where to fix it.
            self.banner.configure(
                text=f"No {problem.language.display_name} compiler installed, so "
                     f"the test suite could not be checked yet. "
                     f"Press Go, or see Help → Compiler status, for install steps.",
                background=self.palette.panel_bg,
                foreground=self.palette.warn)
        elif result.all_passed:
            self.banner.configure(
                text=f"{BADGE_OK}  Test suite verified — the reference solution "
                     f"passes all {result.total} cases{suffix}. "
                     f"All {visible} case(s) below are shown in full."
                     + self._data_set_note(problem),
                background=self.palette.panel_bg, foreground=self.palette.ok)
        else:
            detail = (result.build.output.splitlines()[0]
                      if not result.build.ok and result.build.output
                      else f"{result.passed}/{result.total} passed")
            self.banner.configure(
                text=f"{BADGE_BAD}  This problem is disabled: its own reference "
                     f"solution does not pass its tests ({detail}). "
                     f"The problem file needs fixing.",
                background=self.palette.panel_bg, foreground=self.palette.fail)
            self.banner_button.pack(side="right", padx=(0, 4))

    def _data_set_note(self, problem: Problem) -> str:
        """The tail of the verified banner for a problem with random data."""
        if not problem.generated_tests:
            return ""
        return (f"  {len(problem.generated_tests)} of them are randomised "
                f"(data set #{problem.seed} — press Ctrl+R for another).")

    def _override_reference_gate(self) -> None:
        if self._problem is None:
            return
        self._override_gate.add(self._problem.id)
        self._refresh_banner()
        self._refresh_go_button()
        self.banner_button.pack_forget()

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
            text=f"Verifying {len(self._library.problems)} problems…")

    # ------------------------------------------------------------------
    # build output
    # ------------------------------------------------------------------

    def _clear_build_output(self) -> None:
        self.build_output.replace_all(lambda: None)

    def _write_build_output(self, text: str, failed: bool,
                            command: str = "") -> None:
        def write() -> None:
            if command:
                self.build_output.insert("end", f"$ {command}\n\n", "muted")
            for line in text.splitlines():
                lowered = line.lower()
                tag = ("err" if "error" in lowered
                       else "warn" if "warning" in lowered else "")
                self.build_output.insert("end", line + "\n", tag)
            if not failed and "warning" not in text.lower():
                self.build_output.insert("end", "\nBuild succeeded.\n", "muted")

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
        workspace.save_draft(self._problem.id, suffix, self.editor.get_source())

    def _reset_to_starter(self) -> None:
        if self._problem is None:
            return
        if not messagebox.askyesno(
                "Reset code",
                "Replace your code with the starter code for this problem?\n"
                "Your current work will be discarded.", parent=self):
            return
        suffix = Path(self._problem.language.solution_filename).suffix
        workspace.clear_draft(self._problem.id, suffix)
        self.editor.set_source(self._problem.starter_code)
        self.editor.clear_error_marks()

    def _toggle_theme(self) -> None:
        self.settings["theme"] = "light" if self.palette.name == "dark" else "dark"
        workspace.save_settings(self.settings)
        messagebox.showinfo(
            "Theme changed",
            f"The new theme will be applied next time you start {APP_NAME}.",
            parent=self)

    def _change_font(self, delta: int) -> None:
        size = max(8, min(22, self.settings["font_size"] + delta))
        self.settings["font_size"] = size
        workspace.save_settings(self.settings)
        self.editor._font.configure(size=size)
        self.editor.text.configure(
            tabs=(self.editor._font.measure(" " * 4),))

    def _recheck_toolchains(self) -> None:
        for language in languages.all_languages():
            language.toolchain(refresh=True)
        self._refresh_toolchain_label()
        self._verify_all()
        self._show_toolchains()

    def _refresh_toolchain_label(self) -> None:
        parts, missing = [], False
        for language_id in self._library.languages_present or languages.known_ids():
            status = languages.get(language_id).toolchain()
            parts.append(status.summary)
            missing = missing or not status.available
        self.toolchain_label.configure(
            text="   |   ".join(parts) or "No languages registered",
            foreground=self.palette.warn if missing else self.palette.text_muted)

    def _show_toolchains(self) -> None:
        lines = []
        for language in languages.all_languages():
            status = language.toolchain()
            mark = BADGE_OK if status.available else BADGE_BAD
            lines.append(f"{mark} {language.display_name}: {status.summary}")
            if status.detail:
                lines.append("    " + status.detail.replace("\n", "\n    "))
            if not status.available and status.remedy:
                lines.append("")
                lines.append(status.remedy)
            lines.append("")
        messagebox.showinfo("Compiler status", "\n".join(lines).strip(), parent=self)

    def _show_authoring_help(self) -> None:
        messagebox.showinfo(
            "Writing your own problems",
            "A problem is one JSON file under:\n"
            f"{self.problems_root}\n\n"
            "Required fields:\n"
            "  title, language, statement, harness, tests,\n"
            "  and reference_solution (or reference_solution_b64)\n\n"
            "The harness supplies main(); the candidate supplies the function.\n"
            "Each test is {name, stdin, expected_stdout, description}.\n\n"
            "Every reference solution is run against the full suite before the\n"
            "problem is offered -- a problem whose reference fails is disabled.\n\n"
            "Optional 'generator' adds randomised cases:\n"
            "  {\"count\": 4, \"source\": \"def generate(rng, count): ...\"}\n"
            "It returns inputs only -- {name, stdin, description} -- and the\n"
            "expected output is captured from the reference solution, so the\n"
            "two can never disagree. Ctrl+R draws a new data set.\n\n"
            "See README.md for the full schema and a worked example.",
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
        for index, kind in enumerate((guides.HINT, guides.SOLUTION)):
            self.guides_menu.entryconfigure(
                index, state="normal" if kind in available else "disabled")

    def _open_guide(self, kind: str) -> None:
        problem = self._problem
        if problem is None:
            return

        guide = guides.find(problem, kind)
        if guide is None:
            path = guides.guide_path(problem, kind)
            messagebox.showinfo(
                f"No {guides.KINDS[kind].lower()} for this problem",
                f"{problem.title} does not ship a "
                f"{guides.KINDS[kind].lower()} page.\n\n"
                f"One would live at:\n{path}\n\n"
                "See Guides → What are these? for the convention.",
                parent=self)
            return

        if kind == guides.SOLUTION and not self._confirm_reveal(problem):
            return

        if not guides.open_in_browser(guide):
            messagebox.showerror(
                "Could not open the guide",
                f"No browser could be launched for:\n{guide.path}\n\n"
                "The page is an ordinary HTML file -- open it by hand.",
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
        nudge = ("\n\nThe hint (F1) gives you the idea without the code."
                 if has_hint else "")
        if not messagebox.askyesno(
                "Show the worked solution?",
                f"This opens the complete answer to {problem.title}, with the "
                f"code and an explanation of every part of it.{nudge}\n\n"
                "Open it?",
                parent=self):
            return False
        self._revealed.add(problem.id)
        return True

    def _show_guides_help(self) -> None:
        messagebox.showinfo(
            "About the guides",
            "Each problem can ship two pages, opened in your browser:\n\n"
            "  Hint             the idea, the traps, and the cases to think\n"
            "                   about -- no answer in it\n"
            "  Worked solution  the whole answer, a trace of it running, and\n"
            "                   the wrong turns worth recognising\n\n"
            "They live beside the problem file and are found by name:\n\n"
            "  c_sum_array.json\n"
            "  c_sum_array.hint.html\n"
            "  c_sum_array.solution.html\n\n"
            "There is nothing to register -- drop the files next to the JSON\n"
            "and this menu picks them up. They share problems/guides.css.\n\n"
            "'python -m crucible --guides' lists which problems are missing "
            "one.",
            parent=self)

    def _show_about(self) -> None:
        messagebox.showinfo(
            f"About {APP_NAME}",
            f"{APP_NAME}\n\n"
            "A practice harness for compiled and interpreted languages.\n"
            "Test cases are always shown in full; reference solutions never are.\n\n"
            f"Problems: {self.problems_root}\n"
            f"Drafts:   {workspace.drafts_dir()}\n"
            f"Python:   {sys.version.split()[0]}",
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
            messagebox.showerror("Could not open folder", str(exc), parent=self)

    def _on_close(self) -> None:
        self._save_draft(force=True)
        workspace.save_settings(self.settings)
        self._cancel.set()
        self.destroy()

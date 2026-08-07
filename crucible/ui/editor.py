"""Code editor widget: line numbers, syntax highlighting, sane tab behaviour.

Nothing here is language specific -- the highlighter is driven by the keyword
list and comment style carried on the `Language` object, so a new language gets
highlighting for free.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .theme import Palette

TAB_WIDTH = 4


def mono_font(size: int = 11) -> tkfont.Font:
    """First monospace family actually installed, rather than a hopeful guess."""
    available = set(tkfont.families())
    for family in ("Cascadia Mono", "Consolas", "SF Mono", "Menlo",
                   "DejaVu Sans Mono", "Liberation Mono", "Courier New"):
        if family in available:
            return tkfont.Font(family=family, size=size)
    return tkfont.Font(family="TkFixedFont", size=size)


class _ProxiedText(tk.Text):
    """A Text that emits `<<TextChanged>>` for anything that moves content or
    the viewport, which is what the gutter and highlighter need to react to.

    Tk gives no such event natively, so we intercept the widget's Tcl command.
    """

    def __init__(self, master, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self._original = f"{self._w}_original"
        self.tk.call("rename", self._w, self._original)
        self.tk.createcommand(self._w, self._proxy)

    def _proxy(self, *args):
        try:
            result = self.tk.call((self._original,) + args)
        except tk.TclError as exc:
            message = str(exc)
            # Harmless: Ctrl+X / Ctrl+C with no selection.
            if "tagged with \"sel\"" in message or "text doesn't contain" in message:
                return None
            raise

        moved = (
            args[0] in ("insert", "delete", "replace")
            or args[:3] == ("mark", "set", "insert")
            or args[:2] in (("xview", "moveto"), ("xview", "scroll"),
                            ("yview", "moveto"), ("yview", "scroll"))
        )
        if moved:
            self.event_generate("<<TextChanged>>", when="tail")
        return result


class _LineNumbers(tk.Canvas):
    def __init__(self, master, text: tk.Text, palette: Palette, font: tkfont.Font):
        super().__init__(master, width=52, highlightthickness=0,
                         background=palette.gutter_bg, takefocus=0)
        self._text = text
        self._palette = palette
        self._font = font

    def redraw(self) -> None:
        self.delete("all")
        current = self._text.index("insert").split(".")[0]
        index = self._text.index("@0,0")
        width = self.winfo_width()
        while True:
            info = self._text.dlineinfo(index)
            if info is None:
                break
            line = index.split(".")[0]
            is_current = line == current
            self.create_text(
                width - 8, info[1],
                anchor="ne", text=line, font=self._font,
                fill=self._palette.gutter_fg_active if is_current
                else self._palette.gutter_fg,
            )
            index = self._text.index(f"{index}+1line")


class CodeEditor(ttk.Frame):
    """The candidate's editing surface."""

    def __init__(self, master, palette: Palette, font_size: int = 11) -> None:
        super().__init__(master)
        self._palette = palette
        self._font = mono_font(font_size)
        self._highlight_job: str | None = None
        self._pattern: re.Pattern[str] | None = None
        self._keywords: frozenset[str] = frozenset()
        self._line_comment = "//"

        self.text = _ProxiedText(
            self, wrap="none", undo=True, maxundo=-1, autoseparators=True,
            font=self._font, background=palette.editor_bg,
            foreground=palette.editor_fg, insertbackground=palette.caret,
            selectbackground=palette.selection, selectforeground=palette.editor_fg,
            relief="flat", padx=8, pady=6, tabs=(self._font.measure(" " * TAB_WIDTH),),
            insertwidth=2, borderwidth=0,
        )
        self._gutter = _LineNumbers(self, self.text, palette, self._font)

        vbar = ttk.Scrollbar(self, orient="vertical", command=self._yview)
        hbar = ttk.Scrollbar(self, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        self._gutter.grid(row=0, column=0, sticky="ns")
        self.text.grid(row=0, column=1, sticky="nsew")
        vbar.grid(row=0, column=2, sticky="ns")
        hbar.grid(row=1, column=1, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(1, weight=1)

        self._configure_tags()
        self._bind_keys()
        self.text.bind("<<TextChanged>>", self._on_changed)
        self._gutter.bind("<Configure>", lambda _e: self._gutter.redraw())

    # -- public API --------------------------------------------------------

    def set_language(self, keywords, line_comment: str) -> None:
        """Point the highlighter at a different language."""
        self._keywords = frozenset(keywords)
        self._line_comment = line_comment
        self._pattern = _build_pattern(line_comment)
        self._schedule_highlight()

    def get_source(self) -> str:
        return self.text.get("1.0", "end-1c")

    def set_source(self, source: str, mark_clean: bool = True) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", source)
        self.text.mark_set("insert", "1.0")
        self.text.see("1.0")
        if mark_clean:
            self.text.edit_reset()
            self.text.edit_modified(False)
        self._highlight()
        self._gutter.redraw()

    def set_editable(self, editable: bool) -> None:
        self.text.configure(state="normal" if editable else "disabled")

    def focus_editor(self) -> None:
        self.text.focus_set()

    def goto_line(self, line: int) -> None:
        """Used when the candidate clicks a compiler diagnostic."""
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{line}.0")
        self.text.tag_remove("errorline", "1.0", "end")
        self.text.tag_add("errorline", f"{line}.0", f"{line}.end+1c")
        self.focus_editor()

    def clear_error_marks(self) -> None:
        self.text.tag_remove("errorline", "1.0", "end")

    # -- appearance --------------------------------------------------------

    def _configure_tags(self) -> None:
        p = self._palette
        self.text.tag_configure("keyword", foreground=p.syn_keyword)
        self.text.tag_configure("string", foreground=p.syn_string)
        self.text.tag_configure("comment", foreground=p.syn_comment)
        self.text.tag_configure("number", foreground=p.syn_number)
        self.text.tag_configure("preproc", foreground=p.syn_preproc)
        self.text.tag_configure("errorline", background=p.error_line)
        # Background-only marks sit beneath the colour tags so they never
        # fight over foreground.
        self.text.tag_lower("errorline")

    # -- editing behaviour -------------------------------------------------

    def _bind_keys(self) -> None:
        self.text.bind("<Tab>", self._on_tab)
        self.text.bind("<Shift-Tab>", self._on_shift_tab)
        self.text.bind("<ISO_Left_Tab>", self._on_shift_tab)  # X11 shift-tab
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<BackSpace>", self._on_backspace)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Control-A>", self._select_all)
        self.text.bind("<Control-slash>", self._toggle_comment)

    def _select_all(self, _event=None) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        return "break"

    def _on_tab(self, _event=None) -> str:
        if self.text.tag_ranges("sel"):
            self._shift_selection(indent=True)
            return "break"
        # Tab to the next multiple of TAB_WIDTH rather than always four spaces.
        column = int(self.text.index("insert").split(".")[1])
        self.text.insert("insert", " " * (TAB_WIDTH - column % TAB_WIDTH))
        return "break"

    def _on_shift_tab(self, _event=None) -> str:
        self._shift_selection(indent=False)
        return "break"

    def _shift_selection(self, indent: bool) -> None:
        try:
            first = int(self.text.index("sel.first").split(".")[0])
            last = int(self.text.index("sel.last").split(".")[0])
        except tk.TclError:
            first = last = int(self.text.index("insert").split(".")[0])

        for line in range(first, last + 1):
            start = f"{line}.0"
            if indent:
                self.text.insert(start, " " * TAB_WIDTH)
            else:
                existing = self.text.get(start, f"{line}.{TAB_WIDTH}")
                strip = len(existing) - len(existing.lstrip(" "))
                if strip:
                    self.text.delete(start, f"{line}.{strip}")
        self.text.tag_add("sel", f"{first}.0", f"{last}.end")

    def _on_return(self, _event=None) -> str:
        """Keep the current indent, and add one level after an opening brace or
        a colon so the candidate is not fighting the editor."""
        line_start = self.text.index("insert linestart")
        current = self.text.get(line_start, "insert")
        indent = len(current) - len(current.lstrip(" "))
        stripped = current.rstrip()
        if stripped.endswith(("{", ":", "(")):
            indent += TAB_WIDTH

        self.text.insert("insert", "\n" + " " * indent)
        self.text.see("insert")
        return "break"

    def _on_backspace(self, _event=None) -> str | None:
        """Delete a full indent level when sitting in leading whitespace."""
        if self.text.tag_ranges("sel"):
            return None
        index = self.text.index("insert")
        line, column = (int(part) for part in index.split("."))
        if column == 0:
            return None
        before = self.text.get(f"{line}.0", index)
        if before.strip():
            return None
        back = column % TAB_WIDTH or TAB_WIDTH
        self.text.delete(f"{line}.{column - back}", index)
        return "break"

    def _toggle_comment(self, _event=None) -> str:
        """Ctrl+/ comments the selected lines, or uncomments them if they are
        already commented. Blank lines are left alone so the block keeps its
        shape."""
        try:
            first = int(self.text.index("sel.first").split(".")[0])
            last = int(self.text.index("sel.last").split(".")[0])
        except tk.TclError:
            first = last = int(self.text.index("insert").split(".")[0])

        lines = [(n, self.text.get(f"{n}.0", f"{n}.end"))
                 for n in range(first, last + 1)]
        meaningful = [(n, text) for n, text in lines if text.strip()]
        if not meaningful:
            return "break"

        marker = self._line_comment
        uncomment = all(text.lstrip().startswith(marker) for _, text in meaningful)

        for number, text in meaningful:
            stripped = text.lstrip()
            column = len(text) - len(stripped)
            if uncomment:
                width = len(marker)
                if stripped[width:width + 1] == " ":
                    width += 1
                self.text.delete(f"{number}.{column}", f"{number}.{column + width}")
            else:
                self.text.insert(f"{number}.{column}", marker + " ")
        return "break"

    def _yview(self, *args):
        self.text.yview(*args)
        self._gutter.redraw()

    # -- highlighting ------------------------------------------------------

    def _on_changed(self, _event=None) -> None:
        self._gutter.redraw()
        self._schedule_highlight()

    def _schedule_highlight(self) -> None:
        """Coalesce highlighting to one pass per idle burst -- retagging on
        every keystroke is visibly laggy once a file gets past a screenful."""
        if self._highlight_job is not None:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(60, self._highlight)

    def _highlight(self) -> None:
        self._highlight_job = None
        if self._pattern is None:
            return
        source = self.text.get("1.0", "end-1c")
        for tag in ("keyword", "string", "comment", "number", "preproc"):
            self.text.tag_remove(tag, "1.0", "end")

        for match in self._pattern.finditer(source):
            kind = match.lastgroup
            if kind is None:
                continue
            if kind == "ident":
                if match.group() not in self._keywords:
                    continue
                kind = "keyword"
            start = f"1.0+{match.start()}c"
            end = f"1.0+{match.end()}c"
            self.text.tag_add(kind, start, end)


def _build_pattern(line_comment: str) -> re.Pattern[str]:
    """One alternation, ordered so comments and strings win over everything
    else -- which is exactly the precedence a real lexer would apply."""
    comment = re.escape(line_comment) + r"[^\n]*"
    if line_comment == "//":
        comment = r"//[^\n]*|/\*.*?\*/"
        strings = r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\''
        preproc = r"^[ \t]*\#[^\n]*"
    else:
        strings = (r'"""(?:.|\n)*?"""|\'\'\'(?:.|\n)*?\'\'\''
                   r'|"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
        preproc = r"^[ \t]*@[\w.]+"

    return re.compile(
        rf"(?P<comment>{comment})"
        rf"|(?P<string>{strings})"
        rf"|(?P<preproc>{preproc})"
        rf"|(?P<number>\b\d[\d.xXa-fA-F]*\b)"
        rf"|(?P<ident>[A-Za-z_]\w*)",
        re.MULTILINE | re.DOTALL,
    )

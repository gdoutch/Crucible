"""Code editor widget: line numbers, syntax highlighting, sane tab behaviour.

Nothing here is language specific -- the highlighter is driven by the keyword
list and comment style carried on the `Language` object, so a new language gets
highlighting for free.
"""

from __future__ import annotations

import contextlib
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from .theme import Palette

TAB_WIDTH = 4

#: The three bracket families every language here uses. C leans hardest on
#: `{}` -- every function body and block is one -- but `()` and `[]` get the
#: same treatment for free, and Python's are still worth matching too.
_OPENERS = "([{"
_CLOSERS = ")]}"
_PARTNER = dict(zip(_OPENERS, _CLOSERS))
_PARTNER.update(zip(_CLOSERS, _OPENERS))

#: Typing the key inserts the pair and leaves the caret between the two.
#: Quotes are in here too, and are their own partner -- which is why typing
#: one has to decide whether it is opening or closing before it does anything.
_AUTO_PAIRS = {"(": ")", "[": "]", "{": "}", '"': '"', "'": "'"}

#: Characters that can close something, and so may be typed over rather than
#: inserted a second time.
_AUTO_CLOSERS = frozenset(_AUTO_PAIRS.values())

#: A pair is not opened when the caret is directly in front of one of these,
#: because `(` before `foo` almost always means "wrap what follows", and
#: `()foo` is never what was wanted.
def _is_word_char(char: str) -> bool:
    return char.isalnum() or char == "_"


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
            #
            # Note for callers: this also swallows the error from *querying*
            # a selection that is not there, e.g. `index("sel.first")`. The
            # None returned here comes back through Tkinter as the string
            # "None", so `except tk.TclError` around such a call never fires
            # and an int() of it raises ValueError instead. Ask
            # `tag_ranges("sel")` whether there is a selection -- see
            # `CodeEditor._line_span`.
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
        # `height=1` because a Canvas otherwise asks for seven centimetres of
        # it, and this one is stretched to the Text beside it anyway -- left
        # alone, that request becomes the smallest the editor's pane can be.
        super().__init__(master, width=52, height=1, highlightthickness=0,
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

    def __init__(self, master, palette: Palette, font_size: int = 11,
                 height: int = 20) -> None:
        """`height` is in lines, and is a floor rather than a target -- it
        becomes the smallest the editor's pane can be dragged to."""
        super().__init__(master)
        self._palette = palette
        self._font = mono_font(font_size)
        self._highlight_job: str | None = None
        self._pattern: re.Pattern[str] | None = None
        self._keywords: frozenset[str] = frozenset()
        self._line_comment = "//"
        #: Spans of the current find, and which one the caret is parked on.
        self._matches: list[tuple[str, str]] = []
        self._match_index = 0

        self.text = _ProxiedText(
            self, wrap="none", undo=True, maxundo=-1, autoseparators=True,
            height=height, font=self._font, background=palette.editor_bg,
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

        self._build_find_bar()
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
        # Switching problems: whatever was being searched for belongs to the
        # file being replaced, not the one arriving.
        if self._find_visible:
            self._close_find()
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

    # The editing commands, exposed so the Edit menu drives exactly the same
    # code the key bindings do. Without this the menu would be a second
    # implementation, free to drift out of step with the keyboard.

    def cut_line(self) -> None:
        self._on_cut()

    def duplicate_lines(self) -> None:
        self._duplicate_lines()

    def delete_lines(self) -> None:
        self._delete_lines()

    def move_lines(self, delta: int) -> None:
        self._move_lines(delta)

    def toggle_comment(self) -> None:
        self._toggle_comment()

    def open_find(self, replace: bool = False) -> None:
        self._open_find(replace=replace)

    def step_match(self, delta: int) -> None:
        self._step_match(delta)

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
        # Bracket tags are configured last, which in Tk gives newly created
        # tags the highest display priority -- so a matched or dangling
        # bracket still shows on top of an error line underneath it.
        self.text.tag_configure("bracket_match", background=p.bracket_match_bg)
        self.text.tag_configure("bracket_error", background=p.fail,
                                foreground=p.editor_bg)
        # Find hits are configured last so they win over everything, including
        # a bracket pair or an error line sitting under the same characters.
        # The two reuse existing palette entries rather than adding more: a
        # muted wash for "also matches", and the accent for "you are here".
        self.text.tag_configure("find_match", background=p.bracket_match_bg)
        self.text.tag_configure("find_current", background=p.accent,
                                foreground=p.editor_bg)

    # -- editing behaviour -------------------------------------------------

    def _bind_keys(self) -> None:
        # Bracket and quote pairing. Bound as a catch-all on the character
        # rather than per-key, so it does not depend on the keyboard layout's
        # names for `{` and friends. Tk fires only the most specific binding
        # for a keypress, so <Return>, <Tab> and <BackSpace> below still win
        # over this one.
        self.text.bind("<Key>", self._on_keypress)

        self.text.bind("<Tab>", self._on_tab)
        self.text.bind("<Shift-Tab>", self._on_shift_tab)
        self.text.bind("<ISO_Left_Tab>", self._on_shift_tab)  # X11 shift-tab
        self.text.bind("<Return>", self._on_return)
        self.text.bind("<BackSpace>", self._on_backspace)
        self.text.bind("<Control-a>", self._select_all)
        self.text.bind("<Control-A>", self._select_all)
        self.text.bind("<Control-slash>", self._toggle_comment)

        # Whole-line editing. These are the commands people coming from
        # VS Code or a JetBrains IDE reach for without thinking, and notice
        # immediately when they are missing.
        self.text.bind("<Control-x>", self._on_cut)
        self.text.bind("<Control-X>", self._on_cut)
        self.text.bind("<Control-c>", self._on_copy)
        self.text.bind("<Control-C>", self._on_copy)
        self.text.bind("<Control-d>", self._duplicate_lines)
        self.text.bind("<Control-D>", self._duplicate_lines)
        self.text.bind("<Control-Shift-K>", self._delete_lines)
        self.text.bind("<Control-Shift-k>", self._delete_lines)
        self.text.bind("<Alt-Up>", lambda _e: self._move_lines(-1))
        self.text.bind("<Alt-Down>", lambda _e: self._move_lines(1))
        self.text.bind("<Control-BackSpace>", self._delete_word_left)
        self.text.bind("<Control-Delete>", self._delete_word_right)

        # Find and replace.
        self.text.bind("<Control-f>", lambda _e: self._open_find(replace=False))
        self.text.bind("<Control-F>", lambda _e: self._open_find(replace=False))
        self.text.bind("<Control-h>", lambda _e: self._open_find(replace=True))
        self.text.bind("<Control-H>", lambda _e: self._open_find(replace=True))
        self.text.bind("<F3>", lambda _e: self._step_match(1))
        self.text.bind("<Shift-F3>", lambda _e: self._step_match(-1))
        # Only claim Escape when there is a find bar for it to close, so it
        # stays available to anything else that wants it.
        self.text.bind("<Escape>",
                       lambda _e: self._close_find() if self._find_visible else None)

    def _select_all(self, _event=None) -> str:
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        return "break"

    # -- whole-line commands ------------------------------------------------

    @contextlib.contextmanager
    def _atomic_edit(self):
        """Group everything inside into a single undo step.

        Necessary because the widget runs with `autoseparators=True`, so Tk
        drops an undo separator between edits of its own accord. A command
        built out of a delete followed by an insert -- moving a line, say --
        would otherwise take two presses of Ctrl+Z to reverse, which is not
        what "I moved one line" should cost to undo.
        """
        self.text.edit_separator()
        self.text.configure(autoseparators=False)
        try:
            yield
        finally:
            self.text.configure(autoseparators=True)
            self.text.edit_separator()

    def _line_span(self) -> tuple[int, int]:
        """The line numbers a whole-line command should act on: every line the
        selection touches, or just the caret's line when there is none.

        Uses `tag_ranges`, not `index("sel.first")`, deliberately. The latter
        raises inside Tcl when nothing is selected, and `_ProxiedText._proxy`
        swallows that error and returns None -- which Tkinter then hands back
        as the *string* "None", so the `except tk.TclError` a caller would
        reasonably write never fires and an `int()` blows up instead.
        `tag_ranges` just returns an empty tuple.

        A selection ending exactly at column 0 stops short of that last line
        rather than including a line the user can see they did not highlight.
        """
        ranges = self.text.tag_ranges("sel")
        if not ranges:
            line = int(self.text.index("insert").split(".")[0])
            return line, line
        first = int(str(ranges[0]).split(".")[0])
        last, column = (int(part) for part in str(ranges[1]).split("."))
        if column == 0 and last > first:
            last -= 1
        return first, last

    def _on_cut(self, _event=None) -> str | None:
        """Ctrl+X. With a selection this is the ordinary cut, so it is left to
        Tk; with none, it takes the whole line -- newline included, so that
        pasting it back puts a line in rather than splicing text mid-line."""
        if self.text.tag_ranges("sel"):
            return None
        return self._clip_lines(cut=True)

    def _on_copy(self, _event=None) -> str | None:
        if self.text.tag_ranges("sel"):
            return None
        return self._clip_lines(cut=False)

    def _clip_lines(self, cut: bool) -> str:
        first, last = self._line_span()
        start, end = f"{first}.0", f"{last + 1}.0"
        block = self.text.get(start, end)
        if not block:
            return "break"
        self.clipboard_clear()
        self.clipboard_append(block)
        if cut:
            column = int(self.text.index("insert").split(".")[1])
            with self._atomic_edit():
                self.text.delete(start, end)
            # Land on the line that moved up into the gap, at the column the
            # caret was on -- or the end of it, if that line is shorter.
            width = len(self.text.get(f"{first}.0", f"{first}.end"))
            self.text.mark_set("insert", f"{first}.{min(column, width)}")
            self.text.see("insert")
        return "break"

    def _duplicate_lines(self, _event=None) -> str:
        """Ctrl+D. The copy goes below, and the caret follows it, so pressing
        it twice gives two copies rather than fighting over one."""
        first, last = self._line_span()
        block = self.text.get(f"{first}.0", f"{last}.end")
        column = int(self.text.index("insert").split(".")[1])
        with self._atomic_edit():
            self.text.insert(f"{last}.end", "\n" + block)
        self.text.mark_set("insert", f"{last + 1 + (last - first)}.{column}")
        self.text.see("insert")
        return "break"

    def _delete_lines(self, _event=None) -> str:
        first, last = self._line_span()
        with self._atomic_edit():
            self.text.delete(f"{first}.0", f"{last + 1}.0")
        self.text.see("insert")
        return "break"

    def _move_lines(self, delta: int) -> str:
        """Alt+Up / Alt+Down. Moves the caret's line, or the whole selected
        block, keeping the selection so it can be pressed repeatedly."""
        first, last = self._line_span()
        total = int(self.text.index("end-1c").split(".")[0])
        if (delta < 0 and first <= 1) or (delta > 0 and last >= total):
            return "break"

        had_selection = bool(self.text.tag_ranges("sel"))
        column = int(self.text.index("insert").split(".")[1])
        block = self.text.get(f"{first}.0", f"{last}.end")

        target = first + delta
        with self._atomic_edit():
            self.text.delete(f"{first}.0", f"{last + 1}.0")
            self.text.insert(f"{target}.0", block + "\n")

        moved_last = target + (last - first)
        self.text.mark_set("insert", f"{target}.{column}")
        if had_selection:
            self.text.tag_remove("sel", "1.0", "end")
            self.text.tag_add("sel", f"{target}.0", f"{moved_last}.end")
        self.text.see("insert")
        return "break"

    def _delete_word_left(self, _event=None) -> str:
        start = self.text.index("insert")
        target = self.text.index(f"{start} -1c wordstart")
        # At the very start of a word the index above lands on the caret
        # itself; step back one more so the key always removes something.
        if self.text.compare(target, ">=", start):
            target = self.text.index(f"{start} -1c")
        with self._atomic_edit():
            self.text.delete(target, start)
        return "break"

    def _delete_word_right(self, _event=None) -> str:
        start = self.text.index("insert")
        target = self.text.index(f"{start} wordend")
        if self.text.compare(target, "<=", start):
            target = self.text.index(f"{start} +1c")
        with self._atomic_edit():
            self.text.delete(start, target)
        return "break"

    # -- bracket and quote pairing ------------------------------------------

    def _on_keypress(self, event) -> str | None:
        """Insert `()`, `[]`, `{}`, `""` or `''` as a pair, caret in the middle.

        Returns None for anything not handled, which lets Tk's own class
        binding insert the character exactly as before.
        """
        char = event.char
        if not char or len(char) != 1 or self.text.cget("state") == "disabled":
            return None

        # Typing the closer that is already sitting under the caret steps over
        # it instead of adding a second one -- otherwise finishing a call by
        # typing `)` would leave `())`. Only without a selection, which means
        # something else entirely.
        if (char in _AUTO_CLOSERS and not self.text.tag_ranges("sel")
                and self.text.get("insert") == char):
            self.text.mark_set("insert", "insert+1c")
            return "break"

        if char in _AUTO_PAIRS:
            return self._insert_pair(char)
        return None

    def _insert_pair(self, char: str) -> str | None:
        closer = _AUTO_PAIRS[char]
        ranges = self.text.tag_ranges("sel")

        if ranges:
            # With text selected, the pair goes around it. Replacing a
            # selection with a bare `(` is almost always a mistake, and
            # wrapping is what the keystroke plainly looks like it means.
            start, end = str(ranges[0]), str(ranges[1])
            with self._atomic_edit():
                self.text.insert(end, closer)
                self.text.insert(start, char)
            self.text.tag_add("sel", f"{start}+1c", f"{end}+1c")
            self.text.mark_set("insert", f"{end}+1c")
            return "break"

        if not self._should_pair(char):
            return None

        with self._atomic_edit():
            self.text.insert("insert", char + closer)
        self.text.mark_set("insert", "insert-1c")
        return "break"

    def _should_pair(self, char: str) -> bool:
        """Whether opening `char` here should bring its partner along."""
        following = self.text.get("insert")

        if char in "\"'":
            preceding = self.text.get("insert-1c")
            # An apostrophe inside a word is punctuation, not a char literal:
            # `don't` must not become `don''t`. A backslash means it is being
            # escaped, so it is not opening anything either.
            if _is_word_char(preceding) or preceding == "\\":
                return False
            # An odd number of this quote already on the line means the caret
            # is inside a string, and the one being typed closes it.
            if self._inside_quote(char):
                return False

        # `(` in front of a word wraps it; it does not want a partner.
        return not (following and _is_word_char(following))

    def _inside_quote(self, quote: str) -> bool:
        """Is the caret inside a `quote`-delimited run on this line?

        Counts unescaped delimiters rather than reading the highlighter's
        tags, because the highlighter is debounced and its tags are stale for
        the first few tens of milliseconds after a keystroke -- exactly when
        this question gets asked.
        """
        text = self.text.get(self.text.index("insert linestart"), "insert")
        count, escaped = 0, False
        for character in text:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == quote:
                count += 1
        return count % 2 == 1

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
        first, last = self._line_span()
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
        a colon so the candidate is not fighting the editor.

        Pressing Return with the caret between a freshly opened pair -- the
        `{|}` that typing `{` now leaves behind -- opens the block out over
        three lines and parks the caret on the middle one, which is the whole
        reason auto-closing a brace is worth having in C.
        """
        line_start = self.text.index("insert linestart")
        current = self.text.get(line_start, "insert")
        indent = len(current) - len(current.lstrip(" "))
        stripped = current.rstrip()
        opening = stripped.endswith(("{", ":", "("))

        if opening and self.text.get("insert") in _CLOSERS:
            line = int(self.text.index("insert").split(".")[0])
            inner = indent + TAB_WIDTH
            with self._atomic_edit():
                self.text.insert("insert",
                                 "\n" + " " * inner + "\n" + " " * indent)
            self.text.mark_set("insert", f"{line + 1}.{inner}")
            self.text.see("insert")
            return "break"

        if opening:
            indent += TAB_WIDTH
        self.text.insert("insert", "\n" + " " * indent)
        self.text.see("insert")
        return "break"

    def _on_backspace(self, _event=None) -> str | None:
        """Delete a full indent level when sitting in leading whitespace, and
        take both halves of an empty pair when sitting inside one."""
        if self.text.tag_ranges("sel"):
            return None

        # `{|}` -- undo the pairing in one press rather than leaving the
        # orphaned `}` the keystroke never asked for.
        preceding = self.text.get("insert-1c")
        if (preceding in _AUTO_PAIRS
                and self.text.get("insert") == _AUTO_PAIRS[preceding]):
            with self._atomic_edit():
                self.text.delete("insert-1c", "insert+1c")
            return "break"

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
        first, last = self._line_span()
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

    # -- find and replace ---------------------------------------------------

    def _build_find_bar(self) -> None:
        """A strip under the editor, hidden until Ctrl+F or Ctrl+H asks for it.

        Gridded into the row below the horizontal scrollbar and removed with
        `grid_remove`, which keeps its configuration -- so showing it again is
        one call and the editor above simply gives up the few pixels.
        """
        self._find_visible = False
        self._find_var = tk.StringVar()
        self._replace_var = tk.StringVar()
        self._case_var = tk.BooleanVar(value=False)

        bar = ttk.Frame(self, padding=(6, 4))
        self._find_bar = bar

        ttk.Label(bar, text="Find").grid(row=0, column=0, padx=(0, 6))
        self._find_entry = ttk.Entry(bar, textvariable=self._find_var, width=24)
        self._find_entry.grid(row=0, column=1, sticky="ew")

        self._find_status = ttk.Label(bar, text="", width=12)
        self._find_status.grid(row=0, column=2, padx=6)

        ttk.Button(bar, text="▲", width=3,
                   command=lambda: self._step_match(-1)).grid(row=0, column=3)
        ttk.Button(bar, text="▼", width=3,
                   command=lambda: self._step_match(1)).grid(row=0, column=4)
        ttk.Checkbutton(bar, text="Aa", variable=self._case_var,
                        command=self._refresh_find).grid(row=0, column=5, padx=6)
        ttk.Button(bar, text="✕", width=3,
                   command=self._close_find).grid(row=0, column=6)

        self._replace_label = ttk.Label(bar, text="Replace")
        self._replace_entry = ttk.Entry(bar, textvariable=self._replace_var, width=24)
        self._replace_one = ttk.Button(bar, text="Replace",
                                       command=self._replace_current)
        self._replace_all_btn = ttk.Button(bar, text="All",
                                           command=self._replace_all)
        bar.columnconfigure(1, weight=1)

        # Typing in the box searches as you go; Enter walks the results.
        self._find_var.trace_add("write", lambda *_: self._refresh_find())
        for widget in (self._find_entry, self._replace_entry):
            widget.bind("<Return>", lambda _e: self._step_match(1))
            widget.bind("<Shift-Return>", lambda _e: self._step_match(-1))
            widget.bind("<Escape>", lambda _e: self._close_find())
        self._replace_entry.bind("<Control-Return>", lambda _e: self._replace_all())

    def _open_find(self, replace: bool) -> str:
        self._find_bar.grid(row=2, column=0, columnspan=3, sticky="ew")
        self._find_visible = True

        for widget, column in ((self._replace_label, 7), (self._replace_entry, 8),
                               (self._replace_one, 9), (self._replace_all_btn, 10)):
            if replace:
                widget.grid(row=0, column=column, padx=(6, 0))
            else:
                widget.grid_remove()

        # Seed from the selection, the way every editor does -- select a word,
        # press Ctrl+F, and it is already the thing being searched for.
        try:
            selected = self.text.get("sel.first", "sel.last")
            if selected and "\n" not in selected:
                self._find_var.set(selected)
        except tk.TclError:
            pass

        self._refresh_find()
        self._find_entry.focus_set()
        self._find_entry.select_range(0, "end")
        return "break"

    def _close_find(self) -> str:
        if self._find_visible:
            self._find_bar.grid_remove()
            self._find_visible = False
        self.text.tag_remove("find_match", "1.0", "end")
        self.text.tag_remove("find_current", "1.0", "end")
        self._matches = []
        self.focus_editor()
        return "break"

    def _refresh_find(self, keep_index: bool = False) -> None:
        """Retag every hit. Called on each keystroke in the box, and again
        whenever the document changes underneath an open bar."""
        self.text.tag_remove("find_match", "1.0", "end")
        self.text.tag_remove("find_current", "1.0", "end")
        needle = self._find_var.get()
        self._matches = []
        if not needle:
            self._update_find_status()
            return

        index = "1.0"
        while True:
            hit = self.text.search(needle, index, stopindex="end",
                                   nocase=not self._case_var.get())
            if not hit:
                break
            end = f"{hit}+{len(needle)}c"
            self._matches.append((hit, self.text.index(end)))
            self.text.tag_add("find_match", hit, end)
            index = end

        if not self._matches:
            self._update_find_status()
            return
        if not keep_index:
            # Start from wherever the caret is rather than the top of the file.
            caret = self.text.index("insert")
            self._match_index = next(
                (i for i, (start, _) in enumerate(self._matches)
                 if self.text.compare(start, ">=", caret)), 0)
        self._match_index = min(self._match_index, len(self._matches) - 1)
        self._show_current_match(scroll=False)

    def _show_current_match(self, scroll: bool = True) -> None:
        self.text.tag_remove("find_current", "1.0", "end")
        if not self._matches:
            self._update_find_status()
            return
        start, end = self._matches[self._match_index]
        self.text.tag_add("find_current", start, end)
        if scroll:
            self.text.mark_set("insert", start)
            self.text.see(start)
        self._update_find_status()

    def _step_match(self, delta: int) -> str:
        if not self._find_visible:
            return self._open_find(replace=False)
        if self._matches:
            self._match_index = (self._match_index + delta) % len(self._matches)
            self._show_current_match()
        return "break"

    def _update_find_status(self) -> None:
        if not self._find_var.get():
            self._find_status.configure(text="")
        elif not self._matches:
            self._find_status.configure(text="no matches")
        else:
            self._find_status.configure(
                text=f"{self._match_index + 1} of {len(self._matches)}")

    def _replace_current(self) -> str:
        if not self._matches:
            return "break"
        start, end = self._matches[self._match_index]
        with self._atomic_edit():
            self.text.delete(start, end)
            self.text.insert(start, self._replace_var.get())
        # The list is stale the moment the text changes, so rebuild it -- but
        # stay at the same ordinal, which is now the *next* hit.
        self._refresh_find(keep_index=True)
        return "break"

    def _replace_all(self) -> str:
        needle = self._find_var.get()
        if not needle:
            return "break"
        replacement = self._replace_var.get()
        count, index = 0, "1.0"
        # One undo step for the whole sweep -- undoing a "replace all" one
        # occurrence at a time would be its own small cruelty.
        with self._atomic_edit():
            while True:
                hit = self.text.search(needle, index, stopindex="end",
                                       nocase=not self._case_var.get())
                if not hit:
                    break
                self.text.delete(hit, f"{hit}+{len(needle)}c")
                self.text.insert(hit, replacement)
                # Resume past the replacement, so a replacement containing the
                # needle cannot be found again and loop forever.
                index = self.text.index(f"{hit}+{max(len(replacement), 1)}c")
                count += 1
        self._refresh_find()
        self._find_status.configure(text=f"replaced {count}")
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
        if self._pattern is not None:
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

        # Bracket matching reads the string/comment tags just rebuilt above,
        # so it has to run after them -- otherwise a `(` inside a string
        # comment gets matched as if it were code.
        self._match_brackets()

        # An open find bar goes stale as soon as the document changes under
        # it. Retagging here rather than on every keystroke means it rides the
        # same debounce as the highlighter instead of adding a second one.
        if self._find_visible:
            self._refresh_find(keep_index=True)

    # -- bracket matching ---------------------------------------------------

    def _is_code(self, index: str) -> bool:
        """False inside a string or a comment, where a bracket character does
        not participate in the program's actual nesting."""
        tags = self.text.tag_names(index)
        return "string" not in tags and "comment" not in tags

    def _bracket_before_or_after_caret(self) -> str | None:
        """The index of a bracket character touching the caret, preferring
        the one just behind it -- so pressing `)` highlights the pair you
        just closed rather than whatever the caret happens to sit in front
        of next."""
        insert = self.text.index("insert")
        for index in (f"{insert}-1c", insert):
            char = self.text.get(index)
            if char in _PARTNER and self._is_code(index):
                return index
        return None

    def _find_partner(self, index: str) -> str | None:
        """Scan for the bracket that closes (or opens) the one at `index`,
        tracking nesting depth within the same bracket family and skipping
        anything tagged as a string or a comment. None if the file is
        unbalanced past this point."""
        char = self.text.get(index)
        other = _PARTNER[char]
        step = "+1c" if char in _OPENERS else "-1c"

        depth = 1
        cursor = index
        while True:
            previous = cursor
            cursor = self.text.index(f"{cursor}{step}")
            if cursor == previous:
                return None  # walked off the start or end of the document
            if not self._is_code(cursor):
                continue
            found = self.text.get(cursor)
            if found == char:
                depth += 1
            elif found == other:
                depth -= 1
                if depth == 0:
                    return cursor

    def _match_brackets(self) -> None:
        self.text.tag_remove("bracket_match", "1.0", "end")
        self.text.tag_remove("bracket_error", "1.0", "end")

        index = self._bracket_before_or_after_caret()
        if index is None:
            return

        partner = self._find_partner(index)
        if partner is None:
            self.text.tag_add("bracket_error", index, f"{index}+1c")
            return
        self.text.tag_add("bracket_match", index, f"{index}+1c")
        self.text.tag_add("bracket_match", partner, f"{partner}+1c")


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

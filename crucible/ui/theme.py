"""Colour palettes and ttk styling.

The `clam` ttk theme is used on every platform because it is the only built-in
that honours background/foreground settings consistently -- the native Windows
theme silently ignores most colour options, which would leave half the window
unthemed.
"""

from __future__ import annotations

from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    name: str

    window_bg: str
    panel_bg: str
    border: str
    text_primary: str
    text_muted: str
    accent: str

    editor_bg: str
    editor_fg: str
    caret: str
    selection: str
    gutter_bg: str
    gutter_fg: str
    gutter_fg_active: str
    error_line: str

    syn_keyword: str
    syn_string: str
    syn_comment: str
    syn_number: str
    syn_preproc: str

    #: Background behind a matched bracket pair -- the caret is touching one
    #: of `(){}[]` and its partner was found. Distinct from `selection` and
    #: `error_line` so the three never read as the same thing.
    bracket_match_bg: str

    ok: str
    fail: str
    error: str
    warn: str
    row_alt: str


DARK = Palette(
    name="dark",
    window_bg="#1b1d23",
    panel_bg="#22252d",
    border="#33374a",
    text_primary="#e4e6ec",
    text_muted="#8b91a3",
    accent="#5aa2f7",
    editor_bg="#1a1c22",
    editor_fg="#e4e6ec",
    caret="#5aa2f7",
    selection="#2d4767",
    gutter_bg="#1a1c22",
    gutter_fg="#4b5062",
    gutter_fg_active="#9aa1b5",
    error_line="#3b2530",
    syn_keyword="#7aa2f7",
    syn_string="#9ece6a",
    syn_comment="#636b7f",
    syn_number="#ff9e64",
    syn_preproc="#bb9af7",
    bracket_match_bg="#4a3c1a",
    ok="#5ed4a8",
    fail="#f7768e",
    error="#ffa657",
    warn="#e0af68",
    row_alt="#1f222a",
)

LIGHT = Palette(
    name="light",
    window_bg="#f2f3f6",
    panel_bg="#ffffff",
    border="#d5d8e0",
    text_primary="#1f2328",
    text_muted="#656d76",
    accent="#0969da",
    editor_bg="#ffffff",
    editor_fg="#1f2328",
    caret="#0969da",
    selection="#cfe4ff",
    gutter_bg="#f4f5f8",
    gutter_fg="#adb3bd",
    gutter_fg_active="#57606a",
    error_line="#ffe9ec",
    syn_keyword="#0550ae",
    syn_string="#0a7c42",
    syn_comment="#6e7781",
    syn_number="#b35900",
    syn_preproc="#8250df",
    bracket_match_bg="#fff2b8",
    ok="#116329",
    fail="#cf222e",
    error="#bc4c00",
    warn="#9a6700",
    row_alt="#f7f8fa",
)

PALETTES = {"dark": DARK, "light": LIGHT}


def apply_theme(root, palette: Palette) -> ttk.Style:
    style = ttk.Style(root)
    style.theme_use("clam")

    p = palette
    root.configure(background=p.window_bg)

    style.configure(".", background=p.window_bg, foreground=p.text_primary,
                    fieldbackground=p.panel_bg, bordercolor=p.border,
                    lightcolor=p.panel_bg, darkcolor=p.panel_bg,
                    focuscolor=p.accent)

    style.configure("TFrame", background=p.window_bg)
    style.configure("Panel.TFrame", background=p.panel_bg)
    style.configure("TLabel", background=p.window_bg, foreground=p.text_primary)
    style.configure("Panel.TLabel", background=p.panel_bg, foreground=p.text_primary)
    style.configure("Muted.TLabel", background=p.window_bg, foreground=p.text_muted)
    style.configure("Heading.TLabel", background=p.window_bg,
                    foreground=p.text_primary, font=("", 10, "bold"))
    style.configure("Brand.TLabel", background=p.window_bg,
                    foreground=p.accent, font=("", 13, "bold"))
    style.configure("Status.TLabel", background=p.panel_bg, foreground=p.text_muted)
    # Pane title bars. The chevron and the title are recoloured per widget on
    # hover, so both start from the muted colour the style sets here.
    style.configure("PaneTitle.TLabel", background=p.window_bg,
                    foreground=p.text_muted)
    style.configure("PaneStrip.TFrame", background=p.panel_bg)
    style.configure("PaneStripTitle.TLabel", background=p.panel_bg,
                    foreground=p.text_muted)
    style.configure("Ok.TLabel", background=p.window_bg, foreground=p.ok)
    style.configure("Fail.TLabel", background=p.window_bg, foreground=p.fail)
    style.configure("Warn.TLabel", background=p.window_bg, foreground=p.warn)

    style.configure("TLabelframe", background=p.window_bg, bordercolor=p.border)
    style.configure("TLabelframe.Label", background=p.window_bg,
                    foreground=p.text_muted)

    style.configure("TButton", background=p.panel_bg, foreground=p.text_primary,
                    bordercolor=p.border, padding=(10, 5), relief="flat")
    style.map("TButton",
              background=[("active", p.border), ("disabled", p.panel_bg)],
              foreground=[("disabled", p.text_muted)])

    style.configure("Run.TButton", background=p.accent, foreground="#ffffff",
                    font=("", 10, "bold"), padding=(18, 7))
    style.map("Run.TButton",
              background=[("active", p.accent), ("disabled", p.border)],
              foreground=[("disabled", p.text_muted)])

    style.configure("TCombobox", fieldbackground=p.panel_bg,
                    background=p.panel_bg, foreground=p.text_primary,
                    arrowcolor=p.text_muted, bordercolor=p.border, padding=4)
    style.map("TCombobox",
              fieldbackground=[("readonly", p.panel_bg)],
              foreground=[("readonly", p.text_primary)])

    style.configure("Treeview", background=p.panel_bg, fieldbackground=p.panel_bg,
                    foreground=p.text_primary, bordercolor=p.border,
                    rowheight=24, relief="flat")
    style.configure("Treeview.Heading", background=p.window_bg,
                    foreground=p.text_muted, relief="flat", padding=(6, 4))
    style.map("Treeview",
              background=[("selected", p.selection)],
              foreground=[("selected", p.text_primary)])
    style.map("Treeview.Heading", background=[("active", p.border)])

    style.configure("TNotebook", background=p.window_bg, bordercolor=p.border,
                    tabmargins=(2, 4, 2, 0))
    style.configure("TNotebook.Tab", background=p.window_bg,
                    foreground=p.text_muted, padding=(14, 6), borderwidth=0)
    style.map("TNotebook.Tab",
              background=[("selected", p.panel_bg)],
              foreground=[("selected", p.text_primary)])

    style.configure("TPanedwindow", background=p.window_bg)
    style.configure("Sash", background=p.border, gripcount=0, sashthickness=6)

    style.configure("TScrollbar", background=p.panel_bg, troughcolor=p.window_bg,
                    bordercolor=p.window_bg, arrowcolor=p.text_muted,
                    relief="flat")
    style.map("TScrollbar", background=[("active", p.border)])

    style.configure("TProgressbar", background=p.accent, troughcolor=p.panel_bg,
                    bordercolor=p.border, lightcolor=p.accent, darkcolor=p.accent)

    style.configure("TSeparator", background=p.border)

    return style

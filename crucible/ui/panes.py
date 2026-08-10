"""Collapsible panes.

A `PaneStack` wraps a `ttk.PanedWindow`, and every `CollapsiblePane` inside one
carries a clickable title bar. Collapsing leaves that bar on screen rather than
removing the pane, so there is always something to click to get it back -- a
panel you can lose with no way to ask for it again is worse than one that is
merely in the way.

Sizing is done here rather than left to ttk. `ttk::panedwindow` hands each pane
its requested size and shares out only what is left over, which is the wrong
rule for this window twice: a pane that has just collapsed to a title bar is
giving up space that has to go somewhere specific, and a pane whose contents
happen to ask for a lot (a Text defaults to twenty-four lines) would otherwise
crowd out its neighbours whatever weight it was given. `_relayout` works out
the size every pane should end up with and drives the sashes there directly.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable

from .theme import Palette

CHEVRON_OPEN = "▾"
CHEVRON_SHUT = "▸"
GLYPH_MAXIMISE = "⤢"

#: Width of the rail a horizontally-collapsed pane leaves behind.
STRIP_WIDTH = 26

#: Used only if the Sash style does not report a thickness; theme.py sets 6.
FALLBACK_SASH = 6


class CollapsiblePane(ttk.Frame):
    """One pane of a `PaneStack`: a title bar over a body you can hide.

    `orient` is the orientation of the stack this pane will live in, which is
    what decides where the space goes when it collapses. In a vertical stack
    the horizontal title bar is already thin, so it simply stays. In a
    horizontal one it is the *width* that has to go, so the bar is swapped for
    a narrow rail with the title set one letter per line.
    """

    def __init__(self, master, palette: Palette, key: str, label: str, *,
                 orient: str = "vertical", maximisable: bool = False) -> None:
        super().__init__(master)
        self._palette = palette
        #: Stable name used to save this pane's state; not shown anywhere.
        self.key = key
        self.label = label
        self.orient = orient
        self.collapsed = False

        #: Replaced by the PaneStack that adopts this pane.
        self.on_toggle: Callable[[], None] = lambda: None
        self.on_maximise: Callable[[], None] = lambda: None

        self.bar = ttk.Frame(self, padding=(0, 5, 2, 5))
        self._chevron = ttk.Label(self.bar, text=CHEVRON_OPEN, width=2,
                                  style="PaneTitle.TLabel")
        self._chevron.pack(side="left")
        self._title = ttk.Label(self.bar, text=label, style="PaneTitle.TLabel")
        self._title.pack(side="left")

        if maximisable:
            # Packed before `extra` so it stays the rightmost thing on the bar.
            button = ttk.Label(self.bar, text=GLYPH_MAXIMISE,
                               style="PaneTitle.TLabel")
            button.pack(side="right", padx=(10, 2))
            self._clickable(button, self._fire_maximise, solo=button)

        #: Where the window packs anything that belongs beside the title.
        self.extra = ttk.Frame(self.bar)
        self.extra.pack(side="right")

        self.body = ttk.Frame(self)

        self.strip = ttk.Frame(self, width=STRIP_WIDTH, style="PaneStrip.TFrame")
        self.strip.pack_propagate(False)
        rail_chevron = ttk.Label(self.strip, text=CHEVRON_SHUT,
                                 style="PaneStripTitle.TLabel")
        rail_chevron.pack(pady=(7, 8))
        # One character per line: a vertical label without a rotated font.
        rail_title = ttk.Label(self.strip, text="\n".join(label.replace(" ", "")),
                               justify="center", style="PaneStripTitle.TLabel")
        rail_title.pack()

        for widget in (self.bar, self._chevron, self._title,
                       self.strip, rail_chevron, rail_title):
            self._clickable(widget, self._fire_toggle)

        self._render()

    # -- state -------------------------------------------------------------

    def set_collapsed(self, collapsed: bool) -> None:
        if collapsed == self.collapsed:
            return
        self.collapsed = collapsed
        self._render()

    def collapsed_thickness(self) -> int:
        """How much room this pane needs once collapsed.

        Measured off the bar and the rail rather than off the pane, because the
        caller asks while the pane is still open and still full size.
        """
        self.update_idletasks()
        if self.orient == "horizontal":
            return max(self.strip.winfo_reqwidth(), STRIP_WIDTH)
        return self.bar.winfo_reqheight()

    def _render(self) -> None:
        for child in (self.bar, self.body, self.strip):
            child.pack_forget()
        if self.collapsed and self.orient == "horizontal":
            self.strip.pack(fill="both", expand=True)
        else:
            self.bar.pack(fill="x")
            if not self.collapsed:
                self.body.pack(fill="both", expand=True)
        self._chevron.configure(
            text=CHEVRON_SHUT if self.collapsed else CHEVRON_OPEN)

    # -- title bar behaviour -----------------------------------------------

    def _fire_toggle(self) -> None:
        self.on_toggle()

    def _fire_maximise(self) -> None:
        self.on_maximise()

    def _clickable(self, widget, action, solo=None) -> None:
        """Make `widget` act as part of a title bar.

        `solo` limits the hover highlight to one label -- the maximise glyph
        lights up on its own, so it reads as a separate control rather than as
        another way of hitting the chevron.
        """
        widget.configure(cursor="hand2")
        widget.bind("<Button-1>", lambda _e: action())
        widget.bind("<Enter>", lambda _e: self._hover(True, solo))
        widget.bind("<Leave>", lambda _e: self._hover(False, solo))

    def _hover(self, active: bool, solo=None) -> None:
        colour = (self._palette.text_primary if active
                  else self._palette.text_muted)
        for widget in (solo,) if solo is not None else (self._chevron, self._title):
            widget.configure(foreground=colour)


@dataclass
class _Slot:
    """A pane's place in the stack, and how big it wants to be."""

    widget: tk.Widget
    weight: int
    #: None for a plain child -- a nested stack, say -- which cannot collapse.
    pane: CollapsiblePane | None
    #: Size to restore this slot to. Refreshed from the screen before every
    #: relayout, so a sash the user dragged is respected rather than undone.
    extent: int | None = None

    @property
    def collapsed(self) -> bool:
        return self.pane is not None and self.pane.collapsed


class PaneStack:
    """A `ttk.PanedWindow` whose panes collapse to their title bars."""

    def __init__(self, master, orient: str,
                 on_change: Callable[[], None] | None = None) -> None:
        self.orient = orient
        self.paned = ttk.PanedWindow(master, orient=orient)
        self._slots: list[_Slot] = []
        self._on_change = on_change

    # -- building ----------------------------------------------------------

    def add(self, widget, weight: int = 1) -> None:
        slot = _Slot(widget=widget, weight=weight,
                     pane=widget if isinstance(widget, CollapsiblePane) else None)
        self._slots.append(slot)
        self.paned.add(widget, weight=weight)
        if slot.pane is not None:
            pane = slot.pane
            pane.on_toggle = lambda p=pane: self.toggle(p)
            pane.on_maximise = lambda p=pane: self.maximise(p)

    @property
    def panes(self) -> list[CollapsiblePane]:
        return [slot.pane for slot in self._slots if slot.pane is not None]

    def pane(self, key: str) -> CollapsiblePane | None:
        return next((p for p in self.panes if p.key == key), None)

    # -- collapsing --------------------------------------------------------

    def toggle(self, pane: CollapsiblePane) -> None:
        self.set_collapsed(pane, not pane.collapsed)

    def set_collapsed(self, pane: CollapsiblePane, collapsed: bool) -> None:
        if pane.collapsed == collapsed:
            return
        self._remember()
        pane.set_collapsed(collapsed)
        self._settle()

    def maximise(self, pane: CollapsiblePane) -> None:
        """Give one pane the whole stack, or hand the space back.

        Deliberately a toggle against what is on screen rather than against a
        remembered mode: if the user collapses something by hand in between,
        the button still does the obvious thing next time it is pressed.
        """
        others = [p for p in self.panes if p is not pane]
        alone = not pane.collapsed and all(p.collapsed for p in others)
        self._remember()
        pane.set_collapsed(False)
        for other in others:
            other.set_collapsed(not alone)
        self._settle()

    def reset(self) -> None:
        """Back to the proportions the window was designed with."""
        for pane in self.panes:
            pane.set_collapsed(False)
        for slot in self._slots:
            slot.extent = None
        self._settle()

    def _settle(self) -> None:
        # A collapsed pane must not take a share of the next window resize, or
        # it would slowly grow back out of its own title bar.
        for slot in self._slots:
            self.paned.pane(slot.widget, weight=0 if slot.collapsed else slot.weight)
        self._relayout()
        if self._on_change is not None:
            self._on_change()

    # -- saving and restoring ----------------------------------------------

    def state(self) -> dict:
        self._remember()
        return {
            "sizes": [slot.extent or self._extent_of(slot.widget)
                      for slot in self._slots],
            "collapsed": [p.key for p in self.panes if p.collapsed],
        }

    def restore(self, state) -> None:
        """Take the saved state as a suggestion, not as gospel.

        It comes from a file on disk that anyone may have edited, so every
        piece of it is checked and anything unrecognisable is simply not
        applied -- a mangled settings file costs you your pane sizes, not
        your window.
        """
        if not isinstance(state, dict):
            return
        collapsed = state.get("collapsed")
        collapsed = set(collapsed) if isinstance(collapsed, list) else set()
        for pane in self.panes:
            pane.set_collapsed(pane.key in collapsed)

        sizes = state.get("sizes")
        if isinstance(sizes, list) and len(sizes) == len(self._slots):
            for slot, size in zip(self._slots, sizes):
                if isinstance(size, int) and not isinstance(size, bool) and size > 1:
                    slot.extent = size
        self._settle()

    # -- sizing ------------------------------------------------------------

    def _remember(self) -> None:
        """Read the sizes back off the screen, before something changes them.

        Only the open panes have a size worth reading, and they are rescaled
        to the total they held between them beforehand rather than taken
        literally. That is what makes maximise reversible: while a pane is the
        only one open it is far bigger than it should be remembered as, but
        it is still the same fraction of the open panes as it was, and the
        collapsed ones keep the sizes they will want back.
        """
        open_slots = [slot for slot in self._slots if not slot.collapsed]
        sizes = [self._extent_of(slot.widget) for slot in open_slots]
        if not sizes or any(size <= 1 for size in sizes):
            return  # not on screen; nothing to learn from it

        known = [slot.extent for slot in open_slots]
        scale = sum(known) / sum(sizes) if all(known) else 1.0
        for slot, size in zip(open_slots, sizes):
            slot.extent = max(int(size * scale), 1)

    def _relayout(self) -> None:
        sizes = self._target_sizes()
        if sizes is None:
            return
        gap = self._sash_thickness()
        position = 0
        # Top to bottom: ttk shoves the later sashes out of the way when one
        # grows past them, and each is then set to its own target in turn.
        for index, size in enumerate(sizes[:-1]):
            position += size
            try:
                self.paned.sashpos(index, position)
            except tk.TclError:
                return  # window going away mid-layout
            position += gap

    def _target_sizes(self) -> list[int] | None:
        if len(self._slots) < 2:
            return None
        self.paned.update_idletasks()
        free = (self._extent_of(self.paned)
                - self._sash_thickness() * (len(self._slots) - 1))
        if free < 50:
            return None  # not on screen yet; ttk's own first pass will do

        sizes: dict[int, int] = {}
        for index, slot in enumerate(self._slots):
            fixed = self._fixed_size(slot)
            if fixed is not None:
                sizes[index] = fixed
                free -= fixed

        sharing = [(i, s) for i, s in enumerate(self._slots) if i not in sizes]
        if sharing and free > 0:
            wanted = [max(self._wanted(s, free, sharing), 1.0) for _i, s in sharing]
            scale = free / sum(wanted)
            for (index, _slot), size in zip(sharing, wanted):
                sizes[index] = int(size * scale)
        # Whatever the rounding leaves over falls to the last pane, which is
        # the only one no sash position is set for.
        return [sizes.get(index, 0) for index in range(len(self._slots))]

    def _fixed_size(self, slot: _Slot) -> int | None:
        """The size of a pane that takes no part in sharing out the space."""
        if slot.collapsed and slot.pane is not None:
            return slot.pane.collapsed_thickness()
        if slot.weight == 0:
            # Weight 0 says "do not take a share of a resize", so what this
            # pane naturally asks for is the whole answer -- the problem list
            # stays the width it was designed to be however wide the window is.
            return slot.extent or self._request_of(slot.widget)
        return None

    def _wanted(self, slot: _Slot, free: int, sharing) -> float:
        """How big a pane would like to be, in units the caller then scales."""
        if slot.extent:
            return float(slot.extent)
        total = sum(s.weight for _i, s in sharing) or 1
        return free * slot.weight / total

    def _extent_of(self, widget) -> int:
        return (widget.winfo_height() if self.orient == "vertical"
                else widget.winfo_width())

    def _request_of(self, widget) -> int:
        return (widget.winfo_reqheight() if self.orient == "vertical"
                else widget.winfo_reqwidth())

    def _sash_thickness(self) -> int:
        try:
            return int(self.paned.tk.call("ttk::style", "lookup", "Sash",
                                          "-sashthickness"))
        except (tk.TclError, ValueError):
            return FALLBACK_SASH

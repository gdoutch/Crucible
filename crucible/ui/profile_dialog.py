"""The profile picker: choose an existing profile, or start a blank one.

A plain modal `Toplevel` rather than `tkinter.simpledialog`, because picking
from a list is the point. Profile matching is exact and case-sensitive (see
`crucible.profiles`), so retyping a name from memory is not a reliable way
back into it -- there has to be a list.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from .. import profiles
from ..i18n import t
from .theme import Palette


def choose_profile(master, palette: Palette, *,
                   allow_cancel: bool) -> profiles.Profile | None:
    """Block until a profile is chosen. `None` only if `allow_cancel` and the
    dialog was dismissed without picking one."""
    dialog = _ProfileDialog(master, palette, allow_cancel=allow_cancel)
    return dialog.result


class _ProfileDialog(tk.Toplevel):
    def __init__(self, master, palette: Palette, *, allow_cancel: bool) -> None:
        super().__init__(master)
        self.result: profiles.Profile | None = None
        self._allow_cancel = allow_cancel
        self._profiles = profiles.list_profiles()

        self.title(t("profile_dialog.window_title"))
        self.configure(background=palette.window_bg)
        self.transient(master)
        self.resizable(False, False)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.bind("<Escape>", lambda _e: self._cancel())

        body = ttk.Frame(self, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text=t("profile_dialog.heading"),
                 style="Heading.TLabel").pack(anchor="w")
        ttk.Label(body, text=t("profile_dialog.subtitle"),
                 style="Muted.TLabel").pack(anchor="w", pady=(2, 10))

        self._build_list(body, palette)
        self._build_new_row(body)
        self._build_buttons(body, allow_cancel)

        (self.listbox if self._profiles else self._new_entry).focus_set()
        self.update_idletasks()
        self._center_over(master)
        self.grab_set()
        self.wait_window(self)

    # -- construction --------------------------------------------------

    def _build_list(self, body, palette: Palette) -> None:
        holder = ttk.Frame(body, style="Panel.TFrame")
        holder.pack(fill="both", expand=True)

        # A plain tk.Listbox, not a ttk widget -- ttk has none, and this is
        # the one place the picker needs a scrolling list of names rather
        # than the tree or table widgets the rest of the app uses.
        self.listbox = tk.Listbox(
            holder, height=6, activestyle="none", exportselection=False,
            background=palette.panel_bg, foreground=palette.text_primary,
            selectbackground=palette.selection, selectforeground=palette.text_primary,
            highlightthickness=0, relief="flat", borderwidth=0)
        self.listbox.pack(side="left", fill="both", expand=True, padx=1, pady=1)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")

        for profile in self._profiles:
            self.listbox.insert("end", t("profile_dialog.list_row", username=profile.username))
        if self._profiles:
            self.listbox.selection_set(0)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._open_selected())
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._refresh_open_button())

    def _build_new_row(self, body) -> None:
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(10, 0))
        ttk.Label(row, text=t("profile_dialog.new_profile_label")).pack(side="left")
        self._new_name = tk.StringVar()
        self._new_entry = ttk.Entry(row, textvariable=self._new_name)
        self._new_entry.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._new_entry.bind("<Return>", lambda _e: self._create())

    def _build_buttons(self, body, allow_cancel: bool) -> None:
        row = ttk.Frame(body)
        row.pack(fill="x", pady=(14, 0))
        ttk.Button(row, text=t("profile_dialog.delete_button"), command=self._delete).pack(side="left")
        if allow_cancel:
            ttk.Button(row, text=t("profile_dialog.cancel_button"), command=self._cancel).pack(
                side="right", padx=(8, 0))
        ttk.Button(row, text=t("profile_dialog.create_button"), command=self._create).pack(
            side="right", padx=(8, 0))
        self._open_button = ttk.Button(row, text=t("profile_dialog.open_button"), style="Run.TButton",
                                       command=self._open_selected)
        self._open_button.pack(side="right")
        self._refresh_open_button()

    # -- actions ----------------------------------------------------------

    def _selected_profile(self) -> profiles.Profile | None:
        selection = self.listbox.curselection()
        return self._profiles[selection[0]] if selection else None

    def _refresh_open_button(self) -> None:
        self._open_button.configure(
            state="normal" if self.listbox.curselection() else "disabled")

    def _open_selected(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        # Re-opened by username rather than handed straight back, so
        # `last_opened` moves and it becomes `current_profile()` the same way
        # a freshly created one does.
        self.result = profiles.open_profile(profile.username)
        self.destroy()

    def _create(self) -> None:
        try:
            self.result = profiles.open_profile(self._new_name.get())
        except ValueError as exc:
            messagebox.showwarning(t("profile_dialog.invalid_username_title"), str(exc), parent=self)
            return
        self.destroy()

    def _delete(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if not messagebox.askyesno(
                t("profile_dialog.delete_confirm_title"),
                t("profile_dialog.delete_confirm_message", username=profile.username),
                parent=self):
            return
        profiles.delete_profile(profile.id)
        index = self.listbox.curselection()[0]
        self.listbox.delete(index)
        del self._profiles[index]
        self._refresh_open_button()

    def _cancel(self) -> None:
        if not self._allow_cancel:
            return  # a first run has nothing to fall back to -- must choose
        self.result = None
        self.destroy()

    # -- geometry -----------------------------------------------------------

    def _center_over(self, master) -> None:
        master.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + (master.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")

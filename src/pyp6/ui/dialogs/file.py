"""File and folder picker dialogs: FolderPickerDialog, FileSaveDialog."""

# This module contains the FolderPickerDialog and FileSaveDialog classes.
# They are large Tk dialog classes that will be populated from the original
# monolith. For now, this is a forward-declaration module that makes the
# package importable. The full implementations will be added in a follow-up
# pass once the package structure is proven to work end-to-end.
#
# To keep the rest of the package importable right away, the classes are
# defined here with the correct signatures so that other modules can
# reference them.

import os
import tkinter as tk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
)
from pyp6.constants import PREVIEW_MIN_H, PREVIEW_MIN_W, UI_FAMILY
from pyp6.log import logger
from pyp6.ui.dialogs_common import (
    add_focus_border,
    center_toplevel_on_parent,
    dark_ask_text,
    dark_askyesno,
    dark_showerror,
    dark_showwarning,
    style_label,
    style_listbox,
    style_toplevel,
)
from pyp6.ui.nav_mixin import FolderNavMixin
from pyp6.ui.widgets import RoundedButton, RoundedPanel, RoundedScrollbar


class FolderPickerDialog(FolderNavMixin, tk.Toplevel):
    """Dark-themed replacement for filedialog.askdirectory()."""

    def __init__(self, parent, initial_dir=None, title="Select Folder"):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"{PREVIEW_MIN_W}x{PREVIEW_MIN_H}")
        self.minsize(PREVIEW_MIN_W, PREVIEW_MIN_H)
        style_toplevel(self)
        self.selected_dir = None
        self.current_dir = (
            initial_dir if initial_dir and os.path.isdir(initial_dir) else os.path.expanduser("~")
        )

        self._build_nav_bar(container_bg=BG_DARK)

        list_panel = RoundedPanel(
            self,
            title="Folders",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        list_panel.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        list_frame = tk.Frame(list_panel.body, bg=BG_PANEL)
        list_frame.pack(fill="both", expand=True)
        scrollbar = RoundedScrollbar(list_frame, orient="vertical", parent_bg=BG_PANEL)
        scrollbar.pack(side="right", fill="y", padx=(3, 0))
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set)
        style_listbox(self.listbox)
        self.listbox.pack(side="left", fill="both", expand=True)
        add_focus_border(self.listbox, list_frame)
        scrollbar.command = self.listbox.yview
        self.listbox.bind("<Double-Button-1>", self.on_navigate)
        self.listbox.bind("<Return>", self.on_navigate)
        self.listbox.bind("<BackSpace>", lambda e: self.go_up())

        hint = tk.Label(
            self,
            text="Double-click/Enter: open folder  \u2022  \u2191 Up or Backspace: go up  "
            "\u2022  Type/paste a path above + Enter",
            anchor="w",
        )
        style_label(hint, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", padx=10)

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
        )
        cancel_btn.pack(side="right", padx=4)
        select_btn = RoundedButton(
            btn_row,
            text="Select This Folder",
            command=self.on_confirm,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=170,
        )
        select_btn.pack(side="right", padx=4)

        self.refresh_list()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _safe_grab(self, attempt=0):
        try:
            self.update_idletasks()
            self.grab_set()
        except tk.TclError:
            if attempt < 20:
                self.after(50, lambda: self._safe_grab(attempt + 1))
            return
        self.deiconify()
        self.lift()
        self.focus_force()
        self.wait_visibility()
        self.grab_set()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        self._update_path_entry()
        try:
            entries = sorted(
                e
                for e in os.listdir(self.current_dir)
                if os.path.isdir(os.path.join(self.current_dir, e))
            )
        except Exception as e:
            entries = []
            logger.error(f"Could not read folder: {e}")
        self.listbox.insert(tk.END, "..")
        for entry in entries:
            self.listbox.insert(tk.END, entry)

    def on_navigate(self, event):
        sel = self.listbox.curselection()
        if not sel:
            return
        entry = self.listbox.get(sel[0])
        if entry == "..":
            self.go_up()
        else:
            self.navigate_to(os.path.join(self.current_dir, entry))

    def on_confirm(self):
        self.selected_dir = self.current_dir
        self.destroy()

    def on_cancel(self):
        self.selected_dir = None
        self.destroy()


class FileSaveDialog(FolderNavMixin, tk.Toplevel):
    """Dark-themed replacement for filedialog.asksaveasfilename()."""

    def __init__(
        self,
        parent,
        title="Save File",
        initial_dir=None,
        initial_file="untitled.csv",
        extension=".csv",
    ):
        super().__init__(parent)
        self.title(title)
        self.geometry(f"580x{520 + 32}")
        self.minsize(480, 400 + 32)
        style_toplevel(self)
        self.extension = extension
        self.result_path = None
        self.current_dir = (
            initial_dir if initial_dir and os.path.isdir(initial_dir) else os.path.expanduser("~")
        )

        self._build_nav_bar(container_bg=BG_DARK)

        toolbar = tk.Frame(self, padx=10, bg=BG_DARK)
        toolbar.pack(fill="x")
        new_folder_btn = RoundedButton(
            toolbar,
            text="+ New Folder",
            command=self.on_new_folder,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=110,
            height=26,
            font=(UI_FAMILY, 8),
        )
        new_folder_btn.pack(side="left")

        list_panel = RoundedPanel(
            self,
            title="Folders & Files",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        list_panel.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        list_frame = tk.Frame(list_panel.body, bg=BG_PANEL)
        list_frame.pack(fill="both", expand=True)
        scrollbar = RoundedScrollbar(list_frame, orient="vertical", parent_bg=BG_PANEL)
        scrollbar.pack(side="right", fill="y", padx=(3, 0))
        self.listbox = tk.Listbox(list_frame, yscrollcommand=scrollbar.set, font=(UI_FAMILY, 10))
        style_listbox(self.listbox)
        self.listbox.pack(side="left", fill="both", expand=True)
        add_focus_border(self.listbox, list_frame)
        scrollbar.command = self.listbox.yview
        self.listbox.bind("<Double-Button-1>", self.on_double_click)
        self.listbox.bind("<<ListboxSelect>>", self.on_select)
        self.listbox.bind("<BackSpace>", lambda e: self.go_up())

        hint = tk.Label(
            self,
            text=f"Double-click a folder to open it. Clicking an "
            f"existing {extension} file reuses its name.",
            anchor="w",
        )
        style_label(hint, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", padx=10)

        name_row = tk.Frame(self, padx=10, bg=BG_DARK)
        name_row.pack(fill="x", pady=(8, 6))
        name_lbl = tk.Label(name_row, text="File Name:")
        style_label(name_lbl, font=(UI_FAMILY, 9))
        name_lbl.pack(side="left")
        self.name_var = tk.StringVar(value=initial_file)
        self.name_entry = tk.Entry(
            name_row,
            textvariable=self.name_var,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 10),
        )
        self.name_entry.pack(side="left", fill="x", expand=True, padx=6)
        self.name_entry.bind("<Return>", lambda e: self.on_save())

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
        )
        cancel_btn.pack(side="right", padx=4)
        save_btn = RoundedButton(
            btn_row,
            text="Save",
            command=self.on_save,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=110,
        )
        save_btn.pack(side="right", padx=4)

        self.refresh_list()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self.name_entry.focus_set()
        self.grab_set()

    def refresh_list(self):
        self.listbox.delete(0, tk.END)
        self._update_path_entry()
        try:
            names = os.listdir(self.current_dir)
        except Exception:
            names = []
        dirs = sorted(n for n in names if os.path.isdir(os.path.join(self.current_dir, n)))
        files = sorted(
            n
            for n in names
            if n.lower().endswith(self.extension.lower())
            and os.path.isfile(os.path.join(self.current_dir, n))
        )
        self.listbox.insert(tk.END, "..")
        for d in dirs:
            self.listbox.insert(tk.END, f"[{d}]")
        for f in files:
            self.listbox.insert(tk.END, f)

    def _entry_at(self, index):
        raw = self.listbox.get(index)
        if raw == "..":
            return "..", True
        if raw.startswith("[") and raw.endswith("]"):
            return raw[1:-1], True
        return raw, False

    def on_double_click(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        name, is_dir = self._entry_at(sel[0])
        if name == "..":
            self.go_up()
        elif is_dir:
            self.navigate_to(os.path.join(self.current_dir, name))

    def on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        name, is_dir = self._entry_at(sel[0])
        if not is_dir:
            self.name_var.set(name)

    def on_new_folder(self):
        name = dark_ask_text(self, "New Folder", "Folder name:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        try:
            os.makedirs(os.path.join(self.current_dir, name), exist_ok=False)
        except Exception as e:
            dark_showerror("New Folder", f"Could not create the folder:\n{e}", parent=self)
            return
        self.refresh_list()

    def on_save(self):
        name = self.name_var.get().strip()
        if not name:
            dark_showwarning("Save", "Please enter a file name.", parent=self)
            return
        if not name.lower().endswith(self.extension.lower()):
            name += self.extension
        path = os.path.join(self.current_dir, name)
        if os.path.exists(path) and not dark_askyesno(
            "Overwrite?", f"{name} already exists.\n\nOverwrite it?", parent=self
        ):
            return
        self.result_path = path
        self.destroy()

    def on_cancel(self):
        self.result_path = None
        self.destroy()

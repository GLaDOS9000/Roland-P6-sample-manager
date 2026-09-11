"""Preset save / load dialogs: PresetSaveDialog, PresetLoadDialog."""

import os
import tkinter as tk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_ORANGE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
)
from pyp6.config import is_preset_folder, read_preset_manifest
from pyp6.constants import BANKS, UI_FAMILY
from pyp6.log import logger
from pyp6.ui.dialogs_common import (
    add_focus_border,
    center_toplevel_on_parent,
    dark_ask_text,
    dark_askyesno,
    dark_showerror,
    style_checkbutton,
    style_label,
    style_listbox,
    style_toplevel,
)
from pyp6.ui.nav_mixin import FolderNavMixin
from pyp6.ui.widgets import RoundedButton, RoundedPanel, RoundedScrollbar


class PresetSaveDialog(FolderNavMixin, tk.Toplevel):
    """Navigate to a folder, name the preset, and choose which banks to
    include. Clicking an existing preset folder pre-fills its name - saving
    then only overwrites the checked banks, leaving the rest of that
    preset's banks untouched (partial overwrite)."""

    def __init__(self, parent, app, initial_dir=None):
        super().__init__(parent)
        self.app = app
        self.title("Save Preset")
        self.geometry(f"580x{600 + 32}")
        self.minsize(580, 600 + 32)
        style_toplevel(self)
        self.current_dir = initial_dir or os.path.expanduser("~")
        self.result_dir = None

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
            text="Folders marked \U0001f3b9 already contain a preset - "
            "click one to overwrite it (only checked banks are replaced).",
            anchor="w",
        )
        style_label(hint, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", padx=10)

        name_row = tk.Frame(self, padx=10, bg=BG_DARK)
        name_row.pack(fill="x", pady=(8, 6))
        name_lbl = tk.Label(name_row, text="Preset Name:")
        style_label(name_lbl, font=(UI_FAMILY, 9))
        name_lbl.pack(side="left")
        self.name_var = tk.StringVar()
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

        banks_panel = RoundedPanel(
            self,
            title="Banks to Save",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        banks_panel.pack(fill="x", padx=10, pady=(0, 8))
        self.bank_vars = {}
        bank_row = tk.Frame(banks_panel.body, bg=BG_PANEL)
        bank_row.pack(fill="x", pady=(10, 4))
        for bank in BANKS:
            has_samples = self.app.bank_has_samples(bank)
            var = tk.BooleanVar(value=has_samples)
            self.bank_vars[bank] = var
            cb = tk.Checkbutton(bank_row, text=bank, variable=var)
            style_checkbutton(cb)
            cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
            cb.pack(side="left", padx=6)
        select_row = tk.Frame(banks_panel.body, bg=BG_PANEL)
        select_row.pack(fill="x")
        all_btn = RoundedButton(
            select_row,
            text="All",
            command=lambda: self._set_all_banks(True),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        all_btn.pack(side="left", padx=(0, 4))
        none_btn = RoundedButton(
            select_row,
            text="None",
            command=lambda: self._set_all_banks(False),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        none_btn.pack(side="left")

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        cancel_btn.pack(side="right", padx=4)
        save_btn = RoundedButton(
            btn_row,
            text="Save",
            command=self.on_save,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=90,
        )
        save_btn.pack(side="right", padx=4)

        self._entries = []
        self.refresh_list()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _set_all_banks(self, value):
        for var in self.bank_vars.values():
            var.set(value)

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

    def on_new_folder(self):
        name = dark_ask_text(self, "New Folder", "Folder name:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        if any(c in name for c in '\\/:*?"<>|'):
            dark_showerror(
                "Invalid Name", "The folder name can't contain: \\ / : * ? \" < > |", parent=self
            )
            return
        new_path = os.path.join(self.current_dir, name)
        if os.path.exists(new_path):
            dark_showerror(
                "Already Exists", f"'{name}' already exists in this folder.", parent=self
            )
            return
        try:
            os.makedirs(new_path)
        except Exception as e:
            logger.exception(f"Could not create folder {new_path!r}")
            dark_showerror("Could Not Create Folder", str(e), parent=self)
            return
        self.navigate_to(new_path)

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
        self._entries = [".."]
        self.listbox.insert(tk.END, "..")
        for entry in entries:
            self._entries.append(entry)
            full = os.path.join(self.current_dir, entry)
            if is_preset_folder(full):
                idx = self.listbox.size()
                self.listbox.insert(tk.END, f"\U0001f3b9 {entry}")
                self.listbox.itemconfig(idx, fg=ACCENT_ORANGE)
            else:
                self.listbox.insert(tk.END, entry)

    def on_double_click(self, event):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._entries):
            return
        entry = self._entries[sel[0]]
        if entry == "..":
            self.go_up()
        else:
            self.navigate_to(os.path.join(self.current_dir, entry))

    def on_select(self, event):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._entries):
            return
        entry = self._entries[sel[0]]
        if entry != "..":
            full = os.path.join(self.current_dir, entry)
            if is_preset_folder(full):
                self.name_var.set(entry)  # one click to target an existing preset for overwrite

    def on_save(self):
        name = self.name_var.get().strip()
        if not name:
            dark_showerror("Name Required", "Please enter a preset name.", parent=self)
            return
        if any(c in name for c in '\\/:*?"<>|'):
            dark_showerror(
                "Invalid Name", "The preset name can't contain: \\ / : * ? \" < > |", parent=self
            )
            return
        banks_to_save = [b for b, var in self.bank_vars.items() if var.get()]
        if not banks_to_save:
            dark_showerror("No Banks Selected", "Check at least one bank to save.", parent=self)
            return

        target = os.path.join(self.current_dir, name)
        if is_preset_folder(self.current_dir):
            proceed = dark_askyesno(
                "Nested Preset?",
                "You are currently inside a preset folder. Saving here would put a "
                "preset inside another preset, which is confusing to manage later.\n\n"
                "Save here anyway?",
                parent=self,
            )
            if not proceed:
                return

        if is_preset_folder(target):
            proceed = dark_askyesno(
                "Overwrite Preset?",
                f"'{name}' already exists as a preset.\n\n"
                f"The checked bank(s) ({', '.join(banks_to_save)}) will be overwritten. "
                f"Other banks already saved in this preset are left as-is.\n\nContinue?",
                parent=self,
            )
            if not proceed:
                return
        elif os.path.isdir(target):
            # An existing folder that is NOT a preset - writing into it would
            # scatter BANK_*/preset.json into someone's unrelated directory.
            proceed = dark_askyesno(
                "Folder Already Exists",
                f"'{name}' already exists but is not a preset folder.\n\n"
                "Preset files would be written into that existing folder.\n\nContinue?",
                parent=self,
            )
            if not proceed:
                return

        try:
            self.result_dir = self.app.save_preset_to_folder(self.current_dir, name, banks_to_save)
        except Exception as e:
            logger.exception(
                f"save_preset_to_folder failed: dir={self.current_dir!r}, name={name!r}"
            )
            dark_showerror("Save Error", str(e), parent=self)
            return
        self.destroy()

    def on_cancel(self):
        self.result_dir = None
        self.destroy()


class PresetLoadDialog(FolderNavMixin, tk.Toplevel):
    """Navigate to and click a preset folder, then choose which of its
    banks to actually load. Banks not present in that preset simply aren't
    offered as an option."""

    def __init__(self, parent, app, initial_dir=None, preselect_path=None):
        super().__init__(parent)
        self.app = app
        self.title("Load Preset")
        self.geometry(f"580x{600 + 32}")
        self.minsize(580, 600 + 32)
        style_toplevel(self)
        self.current_dir = initial_dir or os.path.expanduser("~")
        self.result_dir = None
        self.result_banks = []
        self.result_target_override = None
        self.selected_preset_dir = None
        self._preselect_path = preselect_path

        self._build_nav_bar(container_bg=BG_DARK)

        list_panel = RoundedPanel(
            self,
            title="Presets",
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
            text="Folders marked \U0001f3b9 contain a preset - click one to see its banks.",
            anchor="w",
        )
        style_label(hint, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", padx=10)

        self.banks_panel = RoundedPanel(
            self,
            title="Banks to Load",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        self.banks_panel.pack(fill="x", padx=10, pady=(8, 8))
        self.bank_vars = {}
        self.bank_checkbuttons = {}
        bank_row = tk.Frame(self.banks_panel.body, bg=BG_PANEL)
        bank_row.pack(fill="x", pady=(10, 4))
        for bank in BANKS:
            var = tk.BooleanVar(value=False)
            self.bank_vars[bank] = var
            cb = tk.Checkbutton(
                bank_row,
                text=bank,
                variable=var,
                state="disabled",
                command=self._on_bank_checkbox_changed,
            )
            style_checkbutton(cb)
            cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
            cb.pack(side="left", padx=6)
            self.bank_checkbuttons[bank] = cb
        self.no_preset_label = tk.Label(
            self.banks_panel.body, text="No preset selected yet.", anchor="w"
        )
        style_label(self.no_preset_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.no_preset_label.pack(fill="x")

        current_bank_letter = self.app.current_bank.get()
        self.to_current_bank_var = tk.BooleanVar(value=False)
        self.to_current_bank_cb = tk.Checkbutton(
            self.banks_panel.body,
            text=f"Load into current bank (Bank {current_bank_letter}) instead of its original slot",
            variable=self.to_current_bank_var,
            state="disabled",
        )
        style_checkbutton(self.to_current_bank_cb)
        self.to_current_bank_cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
        self.to_current_bank_cb.pack(fill="x", pady=(6, 0))

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        cancel_btn.pack(side="right", padx=4)
        self.load_btn = RoundedButton(
            btn_row,
            text="Load",
            command=self.on_load,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=90,
            state="disabled",
        )
        self.load_btn.pack(side="right", padx=4)

        self._entries = []
        self.refresh_list()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _on_bank_checkbox_changed(self):
        """The 'load into current bank' option only makes sense with exactly
        one bank checked - otherwise it's ambiguous which one would go
        there. Enable/disable it accordingly, and uncheck it if it's no
        longer a valid choice."""
        checked_count = sum(1 for var in self.bank_vars.values() if var.get())
        if checked_count == 1:
            self.to_current_bank_cb.config(state="normal")
        else:
            self.to_current_bank_var.set(False)
            self.to_current_bank_cb.config(state="disabled")

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
        self._entries = [".."]
        self.listbox.insert(tk.END, "..")
        for entry in entries:
            self._entries.append(entry)
            full = os.path.join(self.current_dir, entry)
            if is_preset_folder(full):
                idx = self.listbox.size()
                self.listbox.insert(tk.END, f"\U0001f3b9 {entry}")
                self.listbox.itemconfig(idx, fg=ACCENT_ORANGE)
            else:
                self.listbox.insert(tk.END, entry)

        if self._preselect_path:
            target_name = os.path.basename(self._preselect_path.rstrip(os.sep))
            for i, entry in enumerate(self._entries):
                if entry == target_name:
                    self.listbox.selection_set(i)
                    self.listbox.see(i)
                    self._show_preset_banks(os.path.join(self.current_dir, entry))
                    break
            self._preselect_path = None  # only auto-apply once

    def on_double_click(self, event):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._entries):
            return
        entry = self._entries[sel[0]]
        if entry == "..":
            self.go_up()
        else:
            self.navigate_to(os.path.join(self.current_dir, entry))

    def on_select(self, event):
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(self._entries):
            self._show_preset_banks(None)
            return
        entry = self._entries[sel[0]]
        if entry == "..":
            self._show_preset_banks(None)
            return
        full = os.path.join(self.current_dir, entry)
        if is_preset_folder(full):
            self._show_preset_banks(full)
        else:
            self._show_preset_banks(None)

    def _show_preset_banks(self, preset_dir):
        self.selected_preset_dir = preset_dir
        manifest = read_preset_manifest(preset_dir) if preset_dir else None
        available_banks = set((manifest or {}).get("banks", {}).keys())

        for bank, cb in self.bank_checkbuttons.items():
            if bank in available_banks:
                cb.config(state="normal")
                self.bank_vars[bank].set(True)
            else:
                self.bank_vars[bank].set(False)
                cb.config(state="disabled")

        if manifest is None:
            self.no_preset_label.config(text="No preset selected yet.")
            self.no_preset_label.pack(fill="x")
            self.load_btn.config_state("disabled")
        else:
            self.no_preset_label.pack_forget()
            self.load_btn.config_state("normal")
        self._on_bank_checkbox_changed()

    def on_load(self):
        if not self.selected_preset_dir:
            return
        banks_to_load = [b for b, var in self.bank_vars.items() if var.get()]
        if not banks_to_load:
            dark_showerror("No Banks Selected", "Check at least one bank to load.", parent=self)
            return

        target_override = None
        if len(banks_to_load) == 1 and self.to_current_bank_var.get():
            target_override = self.app.current_bank.get()

        target_banks = [target_override] if target_override else banks_to_load
        will_overwrite = [b for b in target_banks if self.app.bank_has_samples(b)]
        if will_overwrite:
            proceed = dark_askyesno(
                "Overwrite Loaded Pads?",
                f"Bank(s) {', '.join(will_overwrite)} currently have samples loaded. "
                f"Loading this preset will replace them.\n\nContinue?",
                parent=self,
            )
            if not proceed:
                return

        self.result_dir = self.selected_preset_dir
        self.result_banks = banks_to_load
        self.result_target_override = target_override
        self.destroy()

    def on_cancel(self):
        self.result_dir = None
        self.destroy()

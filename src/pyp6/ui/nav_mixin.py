"""Shared address-bar + quick-access folder navigation mixin."""

import os
import tkinter as tk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    BG_DARK,
    BG_INPUT,
    BORDER_COLOR,
    BTN_BLUE,
    FG_MUTED,
    FG_TEXT,
)
from pyp6.constants import UI_FAMILY
from pyp6.ui.dialogs_common import dark_showwarning, style_label
from pyp6.ui.widgets import RoundedButton


class FolderNavMixin:
    """Shared address-bar + quick-access folder navigation. Any class using
    this must keep a `self.current_dir` and implement `self.refresh_list()`."""

    def _build_nav_bar(self, container_bg=BG_DARK):
        top = tk.Frame(self, padx=10, pady=10, bg=container_bg)
        top.pack(fill="x")
        up_btn = RoundedButton(
            top,
            text="\u2191 Up",
            command=self.go_up,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=container_bg,
            width=60,
            height=28,
        )
        up_btn.pack(side="left", padx=(0, 6))
        self.path_entry = tk.Entry(
            top,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
        )
        self.path_entry.pack(side="left", fill="x", expand=True)
        self.path_entry.bind("<Return>", self.go_to_typed_path)
        go_btn = RoundedButton(
            top,
            text="Go",
            command=self.go_to_typed_path,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=container_bg,
            width=50,
            height=28,
        )
        go_btn.pack(side="left", padx=(6, 0))

        quick_row = tk.Frame(self, padx=10, bg=container_bg)
        quick_row.pack(fill="x", pady=(4, 0))
        quick_lbl = tk.Label(quick_row, text="Quick access:")
        style_label(quick_lbl, bg=container_bg, fg=FG_MUTED, font=(UI_FAMILY, 8))
        quick_lbl.pack(side="left", padx=(0, 6))
        for label, path in self._quick_access_locations():
            qb = RoundedButton(
                quick_row,
                text=label,
                command=lambda p=path: self.navigate_to(p),
                bg=BG_INPUT,
                fg=FG_TEXT,
                parent_bg=container_bg,
                width=80,
                height=24,
                font=(UI_FAMILY, 8, "bold"),
            )
            qb.pack(side="left", padx=2)

    def _quick_access_locations(self):
        home = os.path.expanduser("~")
        candidates = [
            ("Home", home),
            ("Desktop", os.path.join(home, "Desktop")),
            ("Downloads", os.path.join(home, "Downloads")),
        ]

        if os.name == "nt":
            import string

            for letter in string.ascii_uppercase:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    candidates.append((f"{letter}:\\", drive))
        else:
            candidates.append(("Root /", "/"))
            candidates.append(("Media", "/run/media"))
            candidates.append(("Mnt", "/mnt"))
            candidates.append(("Volumes", "/Volumes"))  # macOS

        return [(label, path) for label, path in candidates if os.path.isdir(path)]

    def navigate_to(self, path):
        if os.path.isdir(path):
            self.current_dir = path
            self.refresh_list()
        else:
            dark_showwarning("Not Found", f"Folder does not exist:\n{path}", parent=self)

    def go_up(self):
        parent_dir = os.path.dirname(self.current_dir.rstrip(os.sep)) or os.sep
        self.navigate_to(parent_dir)

    def go_to_typed_path(self, event=None):
        typed = self.path_entry.get().strip()
        if not typed:
            return
        typed = os.path.expanduser(typed)
        self.navigate_to(typed)

    def _update_path_entry(self):
        if hasattr(self, "path_entry"):
            self.path_entry.delete(0, tk.END)
            self.path_entry.insert(0, self.current_dir)

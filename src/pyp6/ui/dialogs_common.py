"""Shared dialog helpers, message boxes, tooltips and styling functions.

These are used by virtually every UI module and must not depend on any
specific dialog subclass.
"""

import tkinter as tk
from tkinter import ttk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
    BTN_BLUE,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
)
from pyp6.config import load_tooltips_enabled
from pyp6.constants import (
    TOOLTIP_DELAY_MS,
    TOOLTIP_WRAPLENGTH,
    UI_FAMILY,
)

# ---------------------------------------------------------------------------
# Styling helpers
# ---------------------------------------------------------------------------


def style_toplevel(win):
    win.configure(bg=BG_DARK)


def style_label(lbl, bg=None, fg=None, **kw):
    bg = bg if bg is not None else BG_DARK
    fg = fg if fg is not None else FG_TEXT
    lbl.config(bg=bg, fg=fg, **kw)


def style_listbox(lb):
    lb.config(
        bg=BG_INPUT,
        fg=FG_TEXT,
        selectbackground=ACCENT_BLUE,
        selectforeground="#00131A",
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER_COLOR,
        highlightcolor=ACCENT_BLUE,
        font=(UI_FAMILY, 10),
    )


_TREEVIEW_STYLE_READY = False


def ensure_dark_treeview_style():
    """Configures a dark ttk.Treeview style once per process."""
    global _TREEVIEW_STYLE_READY
    if _TREEVIEW_STYLE_READY:
        return
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure(
        "Dark.Treeview",
        background=BG_INPUT,
        fieldbackground=BG_INPUT,
        foreground=FG_TEXT,
        borderwidth=0,
        relief="flat",
        rowheight=22,
        font=(UI_FAMILY, 10),
        bordercolor=BG_INPUT,
        lightcolor=BG_INPUT,
        darkcolor=BG_INPUT,
    )
    style.map("Dark.Treeview", bordercolor=[("focus", BG_INPUT)])
    style.map(
        "Dark.Treeview",
        background=[("selected", ACCENT_BLUE)],
        foreground=[("selected", "#00131A")],
    )
    style.configure(
        "Dark.Treeview.Heading",
        background=BG_PANEL,
        foreground=FG_MUTED,
        relief="flat",
        font=(UI_FAMILY, 9, "bold"),
    )
    style.map("Dark.Treeview.Heading", background=[("active", BG_PANEL)])
    style.layout("Dark.Treeview", style.layout("Treeview"))

    style.configure(
        "Dark.Vertical.TScrollbar",
        background=BG_INPUT,
        troughcolor=BG_PANEL,
        bordercolor=BG_PANEL,
        arrowcolor=FG_MUTED,
        relief="flat",
        arrowsize=12,
        width=10,
    )
    style.map(
        "Dark.Vertical.TScrollbar", background=[("active", ACCENT_BLUE), ("pressed", ACCENT_BLUE)]
    )

    _TREEVIEW_STYLE_READY = True


def add_focus_border(widget, container=None):
    """Gives a widget the same border behaviour tk.Listbox gets for free."""
    box = container if container is not None else widget.master
    box.configure(
        highlightthickness=1, highlightbackground=BORDER_COLOR, highlightcolor=BORDER_COLOR
    )

    def on_focus(_event=None):
        box.configure(highlightbackground=ACCENT_BLUE, highlightcolor=ACCENT_BLUE)

    def off_focus(_event=None):
        box.configure(highlightbackground=BORDER_COLOR, highlightcolor=BORDER_COLOR)

    widget.bind("<FocusIn>", on_focus, add="+")
    widget.bind("<FocusOut>", off_focus, add="+")
    widget.bind("<Button-1>", on_focus, add="+")
    return box


def style_checkbutton(cb, bg=None):
    bg = bg or BG_DARK
    cb.config(
        bg=bg,
        fg=FG_TEXT,
        selectcolor=BG_INPUT,
        activebackground=bg,
        activeforeground=FG_TEXT,
        disabledforeground=FG_MUTED,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=(UI_FAMILY, 9),
    )


def center_toplevel_on_parent(win, parent):
    """Centers a Toplevel over its parent (or the screen, if no parent)."""
    try:
        win.update_idletasks()
        need_w, need_h = win.winfo_reqwidth(), win.winfo_reqheight()
        cap_w = int(win.winfo_screenwidth() * 0.95)
        cap_h = int(win.winfo_screenheight() * 0.90)
        cur_w, cur_h = win.winfo_width(), win.winfo_height()
        want_w, want_h = min(need_w, cap_w), min(need_h, cap_h)
        if want_w > cur_w or want_h > cur_h:
            win.geometry(f"{max(cur_w, want_w)}x{max(cur_h, want_h)}")
            win.update_idletasks()
        try:
            min_w, min_h = win.minsize()
            win.minsize(max(min_w, want_w), max(min_h, want_h))
        except Exception:
            win.minsize(want_w, want_h)
        w, h = win.winfo_width(), win.winfo_height()
        if parent is not None:
            x = parent.winfo_rootx() + (parent.winfo_width() - w) // 2
            y = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        else:
            x = (win.winfo_screenwidth() - w) // 2
            y = (win.winfo_screenheight() - h) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Dark message dialogs
# ---------------------------------------------------------------------------


class _DarkMessageDialog(tk.Toplevel):
    """Dark-themed replacement for tkinter.messagebox popups."""

    _ICONS = {
        "info": ("\u2139", ACCENT_BLUE),
        "warning": ("\u26a0", ACCENT_ORANGE),
        "error": ("\u2715", ACCENT_RED),
        "question": ("?", ACCENT_BLUE),
    }

    def __init__(self, parent, title, message, kind="info", buttons="ok"):
        super().__init__(parent)
        self.title(title or "")
        style_toplevel(self)
        self.resizable(False, False)
        self.result = None

        icon_char, icon_color = self._ICONS.get(kind, self._ICONS["info"])

        body = tk.Frame(self, bg=BG_DARK, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        top_row = tk.Frame(body, bg=BG_DARK)
        top_row.pack(fill="both", expand=True)

        icon_label = tk.Label(top_row, text=icon_char, font=(UI_FAMILY, 20, "bold"))
        style_label(icon_label, fg=icon_color)
        icon_label.pack(side="left", padx=(0, 14), anchor="n")

        msg_label = tk.Label(top_row, text=str(message), justify="left", anchor="w", wraplength=380)
        style_label(msg_label, font=(UI_FAMILY, 10))
        msg_label.pack(side="left", fill="both", expand=True)

        # Import here to avoid circular dependency at module level
        from pyp6.ui.widgets import RoundedButton

        btn_row = tk.Frame(body, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(16, 0))

        if buttons == "yesno":
            no_btn = RoundedButton(
                btn_row,
                text="No",
                command=self._on_no,
                bg=BG_INPUT,
                fg=FG_TEXT,
                parent_bg=BG_DARK,
                width=80,
            )
            no_btn.pack(side="right", padx=4)
            yes_btn = RoundedButton(
                btn_row,
                text="Yes",
                command=self._on_yes,
                bg=BTN_GREEN,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=80,
            )
            yes_btn.pack(side="right", padx=4)
        else:
            ok_btn = RoundedButton(
                btn_row,
                text="OK",
                command=self._on_ok,
                bg=BTN_BLUE,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=80,
            )
            ok_btn.pack(side="right", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.transient(parent)
        self.update_idletasks()
        self._center_on_parent(parent)
        self._safe_grab()

    def _center_on_parent(self, parent):
        center_toplevel_on_parent(self, parent)

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
        self.focus_set()

    def _on_ok(self):
        self.result = True
        self.destroy()

    def _on_yes(self):
        self.result = True
        self.destroy()

    def _on_no(self):
        self.result = False
        self.destroy()

    def _on_close(self):
        self.destroy()


def _dark_msg_parent(parent):
    return parent or getattr(tk, "_default_root", None)


def dark_showinfo(title=None, message=None, parent=None, **kwargs):
    root = _dark_msg_parent(parent)
    dlg = _DarkMessageDialog(root, title, message, kind="info", buttons="ok")
    root.wait_window(dlg)


def dark_showwarning(title=None, message=None, parent=None, **kwargs):
    root = _dark_msg_parent(parent)
    dlg = _DarkMessageDialog(root, title, message, kind="warning", buttons="ok")
    root.wait_window(dlg)


def dark_showerror(title=None, message=None, parent=None, **kwargs):
    root = _dark_msg_parent(parent)
    dlg = _DarkMessageDialog(root, title, message, kind="error", buttons="ok")
    root.wait_window(dlg)


def dark_askyesno(title=None, message=None, parent=None, **kwargs):
    root = _dark_msg_parent(parent)
    dlg = _DarkMessageDialog(root, title, message, kind="question", buttons="yesno")
    root.wait_window(dlg)
    return bool(dlg.result)


class _DarkTextPromptDialog(tk.Toplevel):
    """Dark-themed replacement for tkinter.simpledialog.askstring."""

    def __init__(self, parent, title, prompt, initial=""):
        super().__init__(parent)
        self.title(title or "")
        style_toplevel(self)
        self.resizable(False, False)
        self.result = None

        from pyp6.ui.widgets import RoundedButton

        body = tk.Frame(self, bg=BG_DARK, padx=20, pady=16)
        body.pack(fill="both", expand=True)

        prompt_label = tk.Label(body, text=prompt, anchor="w", justify="left", wraplength=320)
        style_label(prompt_label, font=(UI_FAMILY, 10))
        prompt_label.pack(fill="x", pady=(0, 8))

        self.entry_var = tk.StringVar(value=initial)
        entry = tk.Entry(
            body,
            textvariable=self.entry_var,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 10),
            width=32,
        )
        entry.pack(fill="x")
        entry.bind("<Return>", lambda e: self._on_ok())
        entry.bind("<Escape>", lambda e: self._on_cancel())
        entry.focus_set()
        entry.select_range(0, tk.END)

        btn_row = tk.Frame(body, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(16, 0))
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self._on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=80,
        )
        cancel_btn.pack(side="right", padx=4)
        ok_btn = RoundedButton(
            btn_row,
            text="OK",
            command=self._on_ok,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=80,
        )
        ok_btn.pack(side="right", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.transient(parent)
        self.update_idletasks()
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

    def _on_ok(self):
        self.result = self.entry_var.get()
        self.destroy()

    def _on_cancel(self):
        self.result = None
        self.destroy()


def dark_ask_text(parent, title, prompt, initial=""):
    root = _dark_msg_parent(parent)
    dlg = _DarkTextPromptDialog(root, title, prompt, initial)
    root.wait_window(dlg)
    return dlg.result


# ---------------------------------------------------------------------------
# Tooltips
# ---------------------------------------------------------------------------

TOOLTIPS_ENABLED = load_tooltips_enabled()


def set_tooltips_enabled(enabled):
    """Turns tooltips on/off for the whole app at runtime."""
    global TOOLTIPS_ENABLED
    TOOLTIPS_ENABLED = bool(enabled)
    if not TOOLTIPS_ENABLED:
        Tooltip.hide_active()


_TOOLTIP_BINDTAG = "PyP6Tooltip"
_TOOLTIP_CLASS_BOUND = False


def _tooltip_click_handler(event):
    tip = getattr(getattr(event, "widget", None), "_pyp6_tooltip", None)
    if tip is not None:
        tip._on_leave()
    else:
        Tooltip.hide_active()


class Tooltip:
    """A small delayed hover popup for one widget."""

    _active = None

    def __init__(self, widget, text, delay=TOOLTIP_DELAY_MS, wraplength=TOOLTIP_WRAPLENGTH):
        self.widget = widget
        self.text = text
        self.delay = delay
        self.wraplength = wraplength
        self._after_id = None
        self._tip = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Destroy>", self._on_destroy, add="+")
        self._install_click_binding(widget)

    @staticmethod
    def _install_click_binding(widget):
        global _TOOLTIP_CLASS_BOUND
        try:
            if not _TOOLTIP_CLASS_BOUND:
                widget.bind_class(_TOOLTIP_BINDTAG, "<ButtonPress>", _tooltip_click_handler)
                _TOOLTIP_CLASS_BOUND = True
            tags = widget.bindtags()
            if _TOOLTIP_BINDTAG not in tags:
                widget.bindtags((_TOOLTIP_BINDTAG,) + tuple(tags))
        except tk.TclError:
            pass

    @classmethod
    def hide_active(cls):
        if cls._active is not None:
            cls._active._hide()

    def set_text(self, text):
        self.text = text
        if self._tip is not None:
            self._hide()

    def _on_enter(self, event=None):
        self._cancel()
        if not TOOLTIPS_ENABLED or not self.text:
            return
        try:
            self._after_id = self.widget.after(self.delay, self._show)
        except tk.TclError:
            self._after_id = None

    def _on_leave(self, event=None):
        self._cancel()
        self._hide()

    def _on_destroy(self, event=None):
        if event is not None and getattr(event, "widget", None) is not self.widget:
            return
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except (tk.TclError, ValueError):
                pass
            self._after_id = None

    def _show(self):
        self._after_id = None
        if not TOOLTIPS_ENABLED or self._tip is not None:
            return
        try:
            if not self.widget.winfo_exists() or not self.widget.winfo_ismapped():
                return
            px, py = self.widget.winfo_pointerxy()
            if self.widget.winfo_containing(px, py) is not self.widget:
                return
        except tk.TclError:
            return
        Tooltip.hide_active()
        try:
            tip = tk.Toplevel(self.widget)
            tip.withdraw()
            tip.wm_overrideredirect(True)
            tip.configure(bg=BORDER_LIGHT)
            label = tk.Label(
                tip,
                text=self.text,
                justify="left",
                anchor="w",
                bg=BG_INPUT,
                fg=FG_TEXT,
                font=(UI_FAMILY, 9),
                wraplength=self.wraplength,
                padx=8,
                pady=5,
                bd=0,
                highlightthickness=0,
            )
            label.pack(padx=1, pady=1)
            tip.update_idletasks()
            x, y = self._position(tip)
            tip.wm_geometry(f"+{x}+{y}")
            try:
                tip.attributes("-topmost", True)
            except tk.TclError:
                pass
            tip.deiconify()
            self._tip = tip
            Tooltip._active = self
        except tk.TclError:
            self._tip = None

    def _position(self, tip):
        w = self.widget
        tw, th = tip.winfo_reqwidth(), tip.winfo_reqheight()
        x = w.winfo_rootx()
        y = w.winfo_rooty() + w.winfo_height() + 8
        sw, sh = w.winfo_screenwidth(), w.winfo_screenheight()
        if x + tw > sw - 4:
            x = max(4, sw - tw - 4)
        if y + th > sh - 4:
            y = max(4, w.winfo_rooty() - th - 8)
        return x, y

    def _hide(self):
        if self._tip is not None:
            try:
                self._tip.destroy()
            except tk.TclError:
                pass
            self._tip = None
        if Tooltip._active is self:
            Tooltip._active = None


def add_tooltip(widget, text, **kwargs):
    """Attaches hover help to a widget."""
    if widget is None or not text:
        return None
    try:
        tip = Tooltip(widget, text, **kwargs)
    except tk.TclError:
        return None
    try:
        widget._pyp6_tooltip = tip
    except Exception:
        pass
    return tip

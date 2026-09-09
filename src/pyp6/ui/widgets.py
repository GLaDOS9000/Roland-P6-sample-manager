"""Custom rounded Tk widgets: RoundedButton, RoundedDropdown, RoundedPanel, RoundedScrollbar."""

import time
import tkinter as tk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
    BTN_BLUE,
    FG_MUTED,
    FG_TEXT,
    HOVER_BG,
)
from pyp6.constants import UI_FAMILY

# Performance counters - shared with __main__ startup diagnostics.
_PERF = {
    "panel_redraws": 0,
    "panel_redraw_time": 0.0,
    "button_draws": 0,
    "button_draw_time": 0.0,
    "dropdown_draws": 0,
    "dropdown_draw_time": 0.0,
}


class RoundedButton(tk.Canvas):
    def __init__(
        self,
        parent,
        text="",
        command=None,
        bg=BTN_BLUE,
        fg="#FFFFFF",
        parent_bg=None,
        width=110,
        height=32,
        radius=10,
        font=(UI_FAMILY, 9, "bold"),
        state="normal",
        outline_color=None,
    ):
        parent_bg = parent_bg or parent.cget("bg")
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.command = command
        self.bg_color = bg
        self.fg_color = fg
        self.text = text
        self.font = font
        self.radius = min(radius, height // 2)
        self.width = width
        self.height = height
        self._state = state
        self.outline_color = outline_color
        self._draw()
        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **kw)
        self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **kw)
        self.create_arc(
            x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", **kw
        )
        self.create_arc(
            x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", **kw
        )
        self.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)

    def _draw(self, hover=False):
        _t0 = time.time()
        self.delete("all")
        fill = self._lighten(self.bg_color) if hover and self._state == "normal" else self.bg_color
        if self._state == "disabled":
            fill = BORDER_COLOR
        self._round_rect(
            1, 1, self.width - 1, self.height - 1, self.radius, fill=fill, outline=fill
        )
        if self.outline_color and self._state == "normal":
            self._round_outline(
                1, 1, self.width - 1, self.height - 1, self.radius, self.outline_color, 2
            )
        text_fg = self.fg_color if self._state == "normal" else FG_MUTED
        self.create_text(
            self.width / 2, self.height / 2, text=self.text, fill=text_fg, font=self.font
        )
        _PERF["button_draws"] += 1
        _PERF["button_draw_time"] += time.time() - _t0

    def _round_outline(self, x1, y1, x2, y2, r, color, width=2):
        """Rounded-rectangle ring: four corner arcs plus four straight edges.

        Deliberately not _round_rect with an empty fill - that shape is made
        of pieslices and rectangles, so outlining it draws the corner radii
        and the seams between the pieces straight across the button.
        """
        inset = width / 2
        x1, y1, x2, y2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
        r = max(1, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
        for cx, cy, start in (
            (x1, y1, 90),
            (x2 - 2 * r, y1, 0),
            (x1, y2 - 2 * r, 180),
            (x2 - 2 * r, y2 - 2 * r, 270),
        ):
            self.create_arc(
                cx,
                cy,
                cx + 2 * r,
                cy + 2 * r,
                start=start,
                extent=90,
                style="arc",
                outline=color,
                width=width,
            )
        self.create_line(x1 + r, y1, x2 - r, y1, fill=color, width=width)
        self.create_line(x1 + r, y2, x2 - r, y2, fill=color, width=width)
        self.create_line(x1, y1 + r, x1, y2 - r, fill=color, width=width)
        self.create_line(x2, y1 + r, x2, y2 - r, fill=color, width=width)

    def _darken(self, hex_color, amount=26):
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        r, g, b = (max(0, c - amount) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _lighten(self, hex_color, amount=18):
        hex_color = hex_color.lstrip("#")
        r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
        r, g, b = (min(255, c + amount) for c in (r, g, b))
        return f"#{r:02x}{g:02x}{b:02x}"

    def _on_enter(self, event):
        if self._state == "normal":
            self._draw(hover=True)
            self.config(cursor="hand2")

    def _on_leave(self, event):
        self._draw(hover=False)

    def _on_click(self, event):
        if self._state == "normal" and self.command:
            self.command()

    def set_outline(self, color):
        """Ring around the button, or None to remove it."""
        if color != self.outline_color:
            self.outline_color = color
            self._draw()

    def config_state(self, state):
        self._state = state
        self._draw()


class RoundedDropdown(tk.Canvas):
    def __init__(
        self,
        parent,
        variable,
        values,
        command=None,
        parent_bg=None,
        width=110,
        height=30,
        radius=10,
        font=(UI_FAMILY, 9, "bold"),
        value_color_fn=None,
        entry_builder=None,
    ):
        parent_bg = parent_bg or parent.cget("bg")
        super().__init__(
            parent,
            width=width,
            height=height,
            bg=parent_bg,
            highlightthickness=0,
            bd=0,
            cursor="hand2",
        )
        self.variable = variable
        self.values = values
        self.command = command
        self.width = width
        self.height = height
        self.radius = min(radius, height // 2)
        self.font = font
        # Optional callable(value) -> color-string-or-None, checked fresh
        # every time the menu opens (not cached), so it can reflect live
        # state - e.g. highlighting which banks currently hold samples.
        self.value_color_fn = value_color_fn
        # Optional callable(menu, value, kwargs) -> True if it added its own
        # entry for that value. Lets a caller turn one entry into a cascade
        # (the bank selector uses this for Move/Copy To) without this generic
        # widget having to know anything about banks.
        self.entry_builder = entry_builder
        self._draw()
        self.bind("<ButtonRelease-1>", self._open_menu)
        self.bind("<Enter>", lambda e: self._draw(hover=True))
        self.bind("<Leave>", lambda e: self._draw(hover=False))
        self.variable.trace_add("write", lambda *a: self._draw())

    def _round_rect(self, x1, y1, x2, y2, r, **kw):
        self.create_arc(x1, y1, x1 + 2 * r, y1 + 2 * r, start=90, extent=90, style="pieslice", **kw)
        self.create_arc(x2 - 2 * r, y1, x2, y1 + 2 * r, start=0, extent=90, style="pieslice", **kw)
        self.create_arc(
            x1, y2 - 2 * r, x1 + 2 * r, y2, start=180, extent=90, style="pieslice", **kw
        )
        self.create_arc(
            x2 - 2 * r, y2 - 2 * r, x2, y2, start=270, extent=90, style="pieslice", **kw
        )
        self.create_rectangle(x1 + r, y1, x2 - r, y2, **kw)
        self.create_rectangle(x1, y1 + r, x2, y2 - r, **kw)

    def _draw(self, hover=False):
        _t0 = time.time()
        self.delete("all")
        fill = HOVER_BG if hover else BG_INPUT
        self._round_rect(
            1, 1, self.width - 1, self.height - 1, self.radius, fill=fill, outline=fill
        )
        self.create_text(
            14,
            self.height / 2,
            text=str(self.variable.get()),
            fill=FG_TEXT,
            font=self.font,
            anchor="w",
        )
        self.create_text(
            self.width - 14,
            self.height / 2,
            text="\u25be",
            fill=ACCENT_BLUE,
            font=(UI_FAMILY, 8),
            anchor="e",
        )
        _PERF["dropdown_draws"] += 1
        _PERF["dropdown_draw_time"] += time.time() - _t0

    def _open_menu(self, event):
        menu = tk.Menu(
            self,
            tearoff=0,
            bg=BG_INPUT,
            fg=FG_TEXT,
            activebackground=ACCENT_BLUE,
            activeforeground="#00131A",
            font=self.font,
            bd=0,
            relief="flat",
        )
        for v in self.values:
            color = self.value_color_fn(v) if self.value_color_fn else None
            kwargs = {"foreground": color} if color else {}
            if self.entry_builder and self.entry_builder(menu, v, kwargs):
                continue  # the builder supplied its own entry for this value
            menu.add_command(label=str(v), command=lambda val=v: self._select(val), **kwargs)
        menu.bind("<Escape>", lambda e: menu.unpost())
        menu.tk_popup(event.x_root, event.y_root)

    def _select(self, val):
        self.variable.set(val)
        self._draw()
        if self.command:
            self.command(val)


class RoundedPanel(tk.Frame):
    """A Canvas-backed panel with rounded corners, a lighter border, and a
    title label, used in place of tk.LabelFrame (which cannot have rounded
    corners). Add child widgets to `.body`, not to the panel itself.

    Both the canvas (background) and body (content) occupy the same grid
    cell of `self`, so `self`'s size is naturally driven by body's packed
    content (exactly like a LabelFrame would size itself) -- no manual
    width/height math needed."""

    def __init__(
        self,
        parent,
        title="",
        parent_bg=None,
        panel_bg=BG_PANEL,
        border=BORDER_LIGHT,
        radius=14,
        title_fg=ACCENT_BLUE,
        title_font=(UI_FAMILY, 10, "bold"),
        body_padx=14,
        body_pady=(30, 12),
    ):
        parent_bg = parent_bg or parent.cget("bg")
        super().__init__(parent, bg=parent_bg)
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self._panel_bg = panel_bg
        self._border = border
        self._border_width = 1
        self._radius = radius
        self._title = title
        self._title_fg = title_fg
        self._title_font = title_font

        self.canvas = tk.Canvas(self, bg=parent_bg, highlightthickness=0, bd=0, width=1, height=1)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        self.body = tk.Frame(self, bg=panel_bg)
        self.body.grid(row=0, column=0, sticky="nsew", padx=body_padx, pady=body_pady)

        self.canvas.bind("<Configure>", lambda e: self._redraw())

    def _round_rect(self, x1, y1, x2, y2, r, fill=None, outline=None, width=1):
        # 1) Filled background: pieslices/rectangles use fill as their own
        #    outline color too, so no stray radius/seam lines are visible.
        self.canvas.create_arc(
            x1,
            y1,
            x1 + 2 * r,
            y1 + 2 * r,
            start=90,
            extent=90,
            style="pieslice",
            fill=fill,
            outline=fill,
        )
        self.canvas.create_arc(
            x2 - 2 * r,
            y1,
            x2,
            y1 + 2 * r,
            start=0,
            extent=90,
            style="pieslice",
            fill=fill,
            outline=fill,
        )
        self.canvas.create_arc(
            x1,
            y2 - 2 * r,
            x1 + 2 * r,
            y2,
            start=180,
            extent=90,
            style="pieslice",
            fill=fill,
            outline=fill,
        )
        self.canvas.create_arc(
            x2 - 2 * r,
            y2 - 2 * r,
            x2,
            y2,
            start=270,
            extent=90,
            style="pieslice",
            fill=fill,
            outline=fill,
        )
        self.canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
        self.canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)

        # 2) Border: drawn once on top, as pure arcs (no radius lines) + straight edges.
        if outline:
            self.canvas.create_arc(
                x1,
                y1,
                x1 + 2 * r,
                y1 + 2 * r,
                start=90,
                extent=90,
                style="arc",
                outline=outline,
                width=width,
            )
            self.canvas.create_arc(
                x2 - 2 * r,
                y1,
                x2,
                y1 + 2 * r,
                start=0,
                extent=90,
                style="arc",
                outline=outline,
                width=width,
            )
            self.canvas.create_arc(
                x1,
                y2 - 2 * r,
                x1 + 2 * r,
                y2,
                start=180,
                extent=90,
                style="arc",
                outline=outline,
                width=width,
            )
            self.canvas.create_arc(
                x2 - 2 * r,
                y2 - 2 * r,
                x2,
                y2,
                start=270,
                extent=90,
                style="arc",
                outline=outline,
                width=width,
            )
            self.canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width)
            self.canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width)
            self.canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width)
            self.canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width)

    def set_title(self, title):
        """Panels whose heading carries a live count need this - the title is
        painted on the canvas, so it cannot just be a Label to reconfigure."""
        if title != self._title:
            self._title = title
            self._redraw()

    def set_border_color(self, color, width=None):
        """Changes the border color (and optionally its width) and forces a
        redraw, bypassing the size-based cache in _redraw() (which would
        otherwise skip drawing since only the color, not the size, changed).
        Used for drag-and-drop hover feedback - a color change alone at the
        default 1px width is easy to miss at a glance, so hover states
        should also pass a thicker width."""
        self._border = color
        if width is not None:
            self._border_width = width
        self._last_size = None
        self._redraw()

    def _redraw(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 4 or h < 4:
            return
        # <Configure> fires repeatedly while the layout settles, often with a
        # size that hasn't actually changed. Redrawing ~14 canvas items each
        # time is pure waste (and on X11 every item is a server round-trip),
        # so bail out unless the size really differs.
        if getattr(self, "_last_size", None) == (w, h):
            return
        self._last_size = (w, h)

        _t0 = time.time()
        self.canvas.delete("all")
        r = min(self._radius, w // 2, h // 2)
        self._round_rect(
            1,
            1,
            w - 1,
            h - 1,
            r,
            fill=self._panel_bg,
            outline=self._border,
            width=self._border_width,
        )
        if self._title:
            self.canvas.create_text(
                16, 16, text=self._title, anchor="w", fill=self._title_fg, font=self._title_font
            )
        _PERF["panel_redraws"] += 1
        _PERF["panel_redraw_time"] += time.time() - _t0


class RoundedScrollbar(tk.Canvas):
    """Canvas scrollbar in the app's palette, since ttk.Scrollbar follows the
    ttk theme and ignores the color scheme entirely.

    Hides itself whenever the content fits, so it behaves like the rest of
    the UI where chrome only appears when it has something to do. Works under
    grid or pack - it asks the widget which manager placed it.
    """

    THICKNESS = 10

    def __init__(self, parent, orient="vertical", command=None, parent_bg=None, auto_hide=True):
        self.orient = orient
        self.command = command
        parent_bg = parent_bg or parent.cget("bg")
        # Both axes on purpose. Tk's Canvas defaults are 10c x 7c - roughly
        # 378 x 265 px - and leaving the long axis at that makes the
        # scrollbar demand that much room from whatever holds it. fill="x"
        # or fill="y" stretches it to the real length anyway, so asking for
        # 1 px costs nothing.
        kw = (
            {"width": self.THICKNESS, "height": 1}
            if orient == "vertical"
            else {"height": self.THICKNESS, "width": 1}
        )
        super().__init__(parent, bg=parent_bg, highlightthickness=0, bd=0, **kw)
        self._first, self._last = 0.0, 1.0
        self._visible = True
        # With auto_hide off, set() only ever redraws. Callers that place the
        # scrollbar themselves need it to stay exactly where they put it -
        # having two places decide the same thing is how it ends up nowhere.
        self.auto_hide = auto_hide
        self._pack_info = None
        self._drag_origin = None
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_origin", None))

    def _span(self):
        return self.winfo_height() if self.orient == "vertical" else self.winfo_width()

    def set(self, first, last):
        self._first, self._last = float(first), float(last)
        fits = self._first <= 0.0 and self._last >= 1.0
        if not self.auto_hide or not self.winfo_manager():
            self._draw()
            return
        if fits and self._visible:
            self._visible = False
            self._hide()
        elif not fits and not self._visible:
            self._visible = True
            self._show()
        if self._visible:
            self._draw()

    def _hide(self):
        """winfo_manager() reports whichever manager owns the widget, so the
        same scrollbar works in a grid-based dialog and a pack-based one."""
        if self.winfo_manager() == "pack":
            info = dict(self.pack_info())
            if "in" in info:  # pack() spells this one in_
                info["in_"] = info.pop("in")
            self._pack_info = info
            self.pack_forget()
        else:
            self.grid_remove()

    def _show(self):
        if getattr(self, "_pack_info", None) is not None:
            try:
                self.pack(**self._pack_info)
            except tk.TclError:
                self.pack(
                    **{
                        k: v
                        for k, v in self._pack_info.items()
                        if k not in ("in_", "after", "before")
                    }
                )
        else:
            self.grid()

    def _draw(self):
        self.delete("all")
        span = self._span()
        if span < 4:
            return
        t = self.THICKNESS
        pad = 2
        if self.orient == "vertical":
            self._pill(pad, pad, t - pad, span - pad, BG_INPUT)
        else:
            self._pill(pad, pad, span - pad, t - pad, BG_INPUT)
        lo = int(self._first * span)
        hi = max(int(self._last * span), lo + 16)
        if self.orient == "vertical":
            self._pill(pad, lo + pad, t - pad, min(hi, span) - pad, BORDER_LIGHT)
        else:
            self._pill(lo + pad, pad, min(hi, span) - pad, t - pad, BORDER_LIGHT)

    def _pill(self, x1, y1, x2, y2, color):
        r = min((x2 - x1), (y2 - y1)) / 2
        if r <= 0 or x2 <= x1 or y2 <= y1:
            return
        self.create_oval(x1, y1, x1 + 2 * r, y1 + 2 * r, fill=color, outline=color)
        self.create_oval(x2 - 2 * r, y2 - 2 * r, x2, y2, fill=color, outline=color)
        self.create_rectangle(
            x1 + r if x2 - x1 > y2 - y1 else x1,
            y1 if x2 - x1 > y2 - y1 else y1 + r,
            x2 - r if x2 - x1 > y2 - y1 else x2,
            y2 if x2 - x1 > y2 - y1 else y2 - r,
            fill=color,
            outline=color,
        )

    def _fraction(self, event):
        span = max(self._span(), 1)
        pos = event.y if self.orient == "vertical" else event.x
        return max(0.0, min(1.0, pos / span))

    def _on_press(self, event):
        span = max(self._span(), 1)
        pos = event.y if self.orient == "vertical" else event.x
        lo, hi = self._first * span, self._last * span
        if lo <= pos <= hi:
            # Grab the thumb where it was clicked instead of jumping, so the
            # content doesn't leap under the cursor on the first pixel of drag.
            self._drag_origin = (pos - lo) / span
        else:
            self._drag_origin = (self._last - self._first) / 2
            self._scroll_to(self._fraction(event) - self._drag_origin)

    def _on_drag(self, event):
        if self._drag_origin is None:
            return
        self._scroll_to(self._fraction(event) - self._drag_origin)

    def _scroll_to(self, first):
        if not self.command:
            return
        page = self._last - self._first
        first = max(0.0, min(1.0 - page, first))
        self.command("moveto", first)

"""Wavetable synth dialogs: WaveformCreatorDialog, SynthDialog."""

import os
import re
import time
import tkinter as tk

import numpy as np

try:
    import sounddevice as sd

    from pyp6.audio.playback import play_audio
except ImportError:
    sd = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BTN_BLUE,
    BTN_GREEN,
    BTN_ORANGE,
    BTN_PURPLE,
    BTN_RED,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
    WAVE_COLOR,
)
from pyp6.config import (
    load_default_autoplay,
    load_drawn_library,
    load_last_cycle_dir,
    save_drawn_library,
    save_last_cycle_dir,
)
from pyp6.constants import (
    UI_FAMILY,
    WT_DRAW_POINTS,
    WT_MAX_SEG_FRAMES,
    WT_MAX_SELECTED,
    WT_MORPH_HEIGHT,
    WT_MORPH_MAX_POINTS,
    WT_MORPH_SHOWN,
    WT_PREVIEW_SECONDS,
    WT_REGISTERS,
    WT_SEGMENTS,
    WT_SR,
)
from pyp6.synth.engine import (
    WTSynth,
    midi_to_hz,
    midi_to_name,
    name_to_midi,
    wt_build,
    wt_harmonics_for,
    wt_render_sweep,
    wt_split_steps,
    wt_tuning_info,
)
from pyp6.synth.waveforms import (
    WT_FAMILIES,
    WT_FAMILY_MAP,
    apply_morph_curve,
    wt_family_entry,
    wt_load_cycle_file,
    wt_points_to_cycle,
)
from pyp6.theme import blend_colors, readable_on
from pyp6.ui.dialogs_common import (
    add_tooltip,
    center_toplevel_on_parent,
    dark_askyesno,
    dark_showerror,
    dark_showwarning,
    style_checkbutton,
    style_label,
    style_listbox,
    style_toplevel,
)
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel, RoundedScrollbar

# ---------------------------------------------------------------------------
# WaveformCreatorDialog
# ---------------------------------------------------------------------------


class WaveformCreatorDialog(tk.Toplevel):
    """Build one cycle twice - by hand or from a file - and morph A to B.

    Two lanes rather than one because a single shape would fill its share of
    the table with the same sound repeated - the morph is what a wavetable is
    for. Leaving B untouched copies A into it, which gives a static block on
    purpose.
    """

    POINTS = WT_DRAW_POINTS

    PRESETS = {
        "Sine": lambda t: np.sin(2 * np.pi * t),
        "Triangle": lambda t: 2.0 * np.abs(2.0 * ((t + 0.25) % 1.0) - 1.0) - 1.0,
        "Saw": lambda t: 2.0 * t - 1.0,
        "Rev Saw": lambda t: 1.0 - 2.0 * t,
        "Square": lambda t: np.where(t < 0.5, 1.0, -1.0),
        "Pulse": lambda t: np.where(t < 0.25, 1.0, -1.0),
        "Half Sin": lambda t: (v := np.abs(np.sin(2 * np.pi * t)), v - v.mean())[1],
        "Noise": lambda t: (rng := np.random.default_rng(), rng.uniform(-1.0, 1.0, len(t)))[1],
        "Flat": lambda t: np.zeros_like(t),
    }

    def __init__(self, parent, app, entry=None, on_apply=None):
        super().__init__(parent)
        self.app = app
        self.on_apply = on_apply
        self.result = None
        self.title("Waveform Creator")
        style_toplevel(self)
        self.minsize(1200, 680)
        self.geometry("1440x740")

        # ------------------------------------------------------------------ #
        # State                                                               #
        # ------------------------------------------------------------------ #
        t = np.arange(self.POINTS) / float(self.POINTS)
        self.lanes = {
            "A": np.array((entry or {}).get("a") or self.PRESETS["Sine"](t), dtype=float),
            "B": np.array((entry or {}).get("b") or self.PRESETS["Saw"](t), dtype=float),
        }
        for k, v in self.lanes.items():
            if v.size != self.POINTS:
                self.lanes[k] = np.interp(t, np.linspace(0, 1, v.size, endpoint=False), v)
        self.active = tk.StringVar(value="A")
        self.name_var = tk.StringVar(value=(entry or {}).get("name") or "Custom")
        self.show_result = tk.BooleanVar(value=True)
        self._last_xy = None
        self._preview_playing = False
        self._loaded_note = None
        self.freq_vars = {"A": tk.DoubleVar(value=1.0), "B": tk.DoubleVar(value=1.0)}
        self.phase_vars = {"A": tk.IntVar(value=0), "B": tk.IntVar(value=0)}
        self._base_lanes = {k: v.copy() for k, v in self.lanes.items()}
        self.shape_vars = {
            "A": tk.StringVar(value="Custom" if entry else "Sine"),
            "B": tk.StringVar(value="Custom" if entry else "Saw"),
        }
        cfg = getattr(self.app, "_wt_last_config", None) or {}
        self.root_note_var = tk.StringVar(value=cfg.get("note", "C2"))
        self.fine_tune_var = tk.IntVar(value=0)
        self.smooth_passes = tk.IntVar(value=0)
        self.morph_skew_var = tk.DoubleVar(value=float((entry or {}).get("morph_skew") or 0.0))
        self.morph_shape_var = tk.DoubleVar(value=float((entry or {}).get("morph_shape") or 0.0))

        for lane in ("A", "B"):
            self.freq_vars[lane].trace_add(
                "write", lambda *_, ln=lane: self._recompute_and_redraw(ln)
            )
            self.phase_vars[lane].trace_add(
                "write", lambda *_, ln=lane: self._recompute_and_redraw(ln)
            )
        self.smooth_passes.trace_add("write", lambda *_: self._recompute_and_redraw_both())
        self.root_note_var.trace_add("write", lambda *_: self._redraw())
        self.morph_skew_var.trace_add("write", lambda *_: self._on_morph_curve_change())
        self.morph_shape_var.trace_add("write", lambda *_: self._on_morph_curve_change())

        PRESET_NAMES = list(self.PRESETS.keys())
        ROOT_NOTES = [midi_to_name(m) for m in range(12, 97)]  # C0–B7

        # ------------------------------------------------------------------ #
        # Head: name, lane selector, band-limit toggle                       #
        # ------------------------------------------------------------------ #
        head = tk.Frame(self, padx=14, pady=10, bg=BG_DARK)
        head.pack(fill="x")
        name_lbl = tk.Label(head, text="Name:")
        style_label(name_lbl, font=(UI_FAMILY, 9))
        name_lbl.pack(side="left")
        self.name_entry = tk.Entry(
            head,
            textvariable=self.name_var,
            width=18,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 10),
        )
        self.name_entry.pack(side="left", padx=(6, 18))
        for lane in ("A", "B"):
            rb = tk.Radiobutton(
                head, text=f"Shape {lane}", variable=self.active, value=lane, command=self._redraw
            )
            style_checkbutton(rb)
            rb.pack(side="left", padx=(0, 10))
        cb = tk.Checkbutton(
            head,
            text="Show what will actually sound",
            variable=self.show_result,
            command=self._redraw,
        )
        style_checkbutton(cb)
        cb.pack(side="left", padx=(12, 0))
        add_tooltip(
            cb,
            "Overlays the band-limited result on top of your line. The two "
            "differ wherever the drawing is sharper than the segment can "
            "hold, and that difference is what you will hear.",
        )

        # ------------------------------------------------------------------ #
        # Body: left (Cycle) | right (Wavetable)                             #
        # ------------------------------------------------------------------ #
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=14)

        left_col = tk.Frame(body, bg=BG_DARK)
        right_col = tk.Frame(body, bg=BG_DARK)

        _COL_GAP = 10
        _LEFT_FRAC = 0.35  # left gets 35 %, right gets 65 %

        def _layout_body(event=None):
            w = body.winfo_width()
            h = body.winfo_height()
            if w < 2 or h < 2:
                return
            lw = max(1, int(w * _LEFT_FRAC) - _COL_GAP // 2)
            rw = max(1, w - lw - _COL_GAP)
            left_col.place(x=0, y=0, width=lw, height=h)
            right_col.place(x=lw + _COL_GAP, y=0, width=rw, height=h)

        body.bind("<Configure>", lambda e: _layout_body())

        # -- Left: Cycle panel (drawing canvas) --
        cycle_panel = RoundedPanel(
            left_col,
            title="Cycle",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        cycle_panel.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(
            cycle_panel.body, bg=WAVE_BG, highlightthickness=0, height=200, cursor="pencil"
        )
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Button-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<Configure>", lambda e: self._redraw())
        self.info = tk.Label(cycle_panel.body, text="", anchor="w")
        style_label(self.info, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.info.pack(fill="x", pady=(4, 0))

        # -- Left: per-lane shape controls --
        lane_panel = tk.Frame(left_col, bg=BG_DARK)
        lane_panel.pack(fill="x", pady=(6, 0))
        for lane in ("A", "B"):
            row = tk.Frame(lane_panel, bg=BG_DARK)
            row.pack(fill="x", pady=1)
            lbl = tk.Label(row, text=f"Shape {lane}", width=8, anchor="w")
            style_label(lbl, font=(UI_FAMILY, 8, "bold"))
            lbl.pack(side="left")
            shape_dd = RoundedDropdown(
                row,
                self.shape_vars[lane],
                PRESET_NAMES,
                command=lambda lbl=None, ln=lane: self._on_shape_change(ln),
                parent_bg=BG_DARK,
                width=90,
                height=24,
                font=(UI_FAMILY, 8),
            )
            shape_dd.pack(side="left", padx=(0, 4))
            add_tooltip(shape_dd, f"Load a preset waveform into shape {lane}.")
            load_btn = RoundedButton(
                row,
                text="Load\u2026",
                command=lambda ln=lane: self._load_file_lane(ln),
                bg=BTN_PURPLE,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=58,
                height=24,
                font=(UI_FAMILY, 8),
            )
            load_btn.pack(side="left", padx=(0, 10))
            add_tooltip(load_btn, f"Load a single-cycle WAV file into shape {lane}.")
            tk.Label(row, text="Freq \u00d7", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
                side="left"
            )
            freq_sb = tk.Spinbox(
                row,
                textvariable=self.freq_vars[lane],
                from_=0.5,
                to=8.0,
                increment=0.5,
                width=4,
                format="%.1f",
                bg=BG_INPUT,
                fg=FG_TEXT,
                insertbackground=FG_TEXT,
                buttonbackground=BG_INPUT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
                font=(UI_FAMILY, 8),
            )
            freq_sb.pack(side="left", padx=(2, 8))
            add_tooltip(freq_sb, f"Frequency multiplier for shape {lane} — updates live.")
            tk.Label(row, text="Phase", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
                side="left"
            )
            phase_sb = tk.Spinbox(
                row,
                textvariable=self.phase_vars[lane],
                from_=0,
                to=355,
                increment=5,
                width=4,
                bg=BG_INPUT,
                fg=FG_TEXT,
                insertbackground=FG_TEXT,
                buttonbackground=BG_INPUT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
                font=(UI_FAMILY, 8),
            )
            phase_sb.pack(side="left", padx=(2, 2))
            tk.Label(row, text="\u00b0", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
                side="left", padx=(0, 10)
            )
            add_tooltip(phase_sb, f"Phase shift in degrees for shape {lane} — updates live.")

        # -- Left: root note, smooth, swap --
        ctrl_left = tk.Frame(left_col, bg=BG_DARK)
        ctrl_left.pack(fill="x", pady=(4, 8))
        tk.Label(ctrl_left, text="\u266a Root", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left"
        )
        root_dd = RoundedDropdown(
            ctrl_left,
            self.root_note_var,
            ROOT_NOTES,
            parent_bg=BG_DARK,
            width=68,
            height=24,
            font=(UI_FAMILY, 8),
        )
        root_dd.pack(side="left", padx=(4, 2))
        add_tooltip(root_dd, "Root note for band-limit preview and audio sweep.")
        tk.Label(ctrl_left, text="Fine", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left", padx=(8, 0)
        )
        fine_sb = tk.Spinbox(
            ctrl_left,
            textvariable=self.fine_tune_var,
            from_=-99,
            to=99,
            increment=1,
            width=4,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            buttonbackground=BG_INPUT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            font=(UI_FAMILY, 8),
        )
        fine_sb.pack(side="left", padx=(2, 2))
        tk.Label(ctrl_left, text="\u00a2", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left", padx=(0, 12)
        )
        add_tooltip(fine_sb, "Fine tune in cents (±99¢) applied to the audio sweep preview.")
        tk.Label(ctrl_left, text="Smooth", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left"
        )
        smooth_sb = tk.Spinbox(
            ctrl_left,
            textvariable=self.smooth_passes,
            from_=0,
            to=20,
            increment=1,
            width=3,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            buttonbackground=BG_INPUT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            font=(UI_FAMILY, 8),
        )
        smooth_sb.pack(side="left", padx=(2, 12))
        add_tooltip(
            smooth_sb,
            "Smoothing passes applied to both shapes — 0 = off.\n"
            "Attenuates high harmonics. Fully reversible: set back to 0 to restore.",
        )
        swap_btn = RoundedButton(
            ctrl_left,
            text="Swap A \u21c4 B",
            command=self._swap_lanes,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
            height=24,
            font=(UI_FAMILY, 8),
        )
        swap_btn.pack(side="left", padx=2)
        add_tooltip(swap_btn, "Swaps shapes A and B — reverses the morph direction.")

        # -- Right: Wavetable panel (morph strip + curve thumbnail) --
        morph_panel = RoundedPanel(
            right_col,
            title="Wavetable",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        morph_panel.pack(fill="both", expand=True)
        self.morph_strip = tk.Canvas(morph_panel.body, bg=WAVE_BG, highlightthickness=0, height=160)
        self.morph_strip.pack(fill="both", expand=True)
        self.morph_strip.bind("<Configure>", lambda e: self._draw_morph_strip())
        add_tooltip(
            self.morph_strip,
            "Live preview of all morph steps from shape A to shape B.\n"
            "Nearest curve = A, furthest = B.",
        )
        curve_sep = tk.Label(morph_panel.body, text="Morph curve", anchor="w")
        style_label(curve_sep, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 7))
        curve_sep.pack(fill="x", pady=(8, 0))
        self.curve_canvas = tk.Canvas(morph_panel.body, bg=WAVE_BG, highlightthickness=0, height=70)
        self.curve_canvas.pack(fill="x", pady=(2, 4))
        self.curve_canvas.bind("<Configure>", lambda e: self._draw_curve_thumbnail())
        add_tooltip(
            self.curve_canvas,
            "Shape of the A\u2192B transition across the wavetable.\n"
            "Diagonal = linear.  Curve = shaped by Skew and Shape below.",
        )

        # -- Right: morph curve params + play --
        ctrl_right = tk.Frame(right_col, bg=BG_DARK)
        ctrl_right.pack(fill="x", pady=(4, 8))
        tk.Label(ctrl_right, text="Skew", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left"
        )
        skew_sb = tk.Spinbox(
            ctrl_right,
            textvariable=self.morph_skew_var,
            from_=-2.0,
            to=2.0,
            increment=0.1,
            width=5,
            format="%.1f",
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            buttonbackground=BG_INPUT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            font=(UI_FAMILY, 8),
        )
        skew_sb.pack(side="left", padx=(2, 10))
        add_tooltip(
            skew_sb,
            "Ease-in / ease-out:\n"
            "  0 = linear\n"
            "+2 = strong ease-in  (morph spends more time near A)\n"
            "\u22122 = strong ease-out (morph jumps to B quickly)",
        )
        tk.Label(ctrl_right, text="Shape", bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8)).pack(
            side="left"
        )
        shape_sb = tk.Spinbox(
            ctrl_right,
            textvariable=self.morph_shape_var,
            from_=-2.0,
            to=2.0,
            increment=0.1,
            width=5,
            format="%.1f",
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            buttonbackground=BG_INPUT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            font=(UI_FAMILY, 8),
        )
        shape_sb.pack(side="left", padx=(2, 10))
        add_tooltip(
            shape_sb,
            "S-curve / Reverse-S:\n"
            "  0 = linear\n"
            "+2 = strong S-curve   (frames cluster at A and B extremes)\n"
            "\u22122 = strong reverse-S (frames cluster in the middle of the sweep)",
        )
        self.prev_btn = RoundedButton(
            ctrl_right,
            text="\u25b6",
            command=self._toggle_preview,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=40,
            height=24,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.prev_btn.pack(side="right", padx=(2, 0))
        add_tooltip(self.prev_btn, "Plays the A\u2192B morph sweep at the selected root note.")

        # ------------------------------------------------------------------ #
        # Foot: delete / cancel / apply                                      #
        # ------------------------------------------------------------------ #
        foot = tk.Frame(self, padx=14, pady=10, bg=BG_DARK)
        foot.pack(fill="x")
        if entry:
            self.btn_delete = RoundedButton(
                foot,
                text="Delete",
                command=self._delete,
                bg=BTN_RED,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=110,
            )
            self.btn_delete.pack(side="left")
            add_tooltip(
                self.btn_delete,
                "Removes this waveform from the saved library and from the "
                "step order. Wavetables already built with it keep working - "
                "their audio is on the pad, not here.",
            )
        cancel = RoundedButton(
            foot, text="Cancel", command=self._cancel, bg=BG_INPUT, fg=FG_TEXT, parent_bg=BG_DARK
        )
        cancel.pack(side="right", padx=4)
        ok = RoundedButton(
            foot,
            text="Use Waveform",
            command=self._apply,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=150,
        )
        ok.pack(side="right", padx=4)

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self.after(50, self._redraw)
        self._safe_grab()

    def _safe_grab(self):
        try:
            self.grab_set()
        except tk.TclError:
            pass

    # ----------------------------------------------------------- morph curve
    def _on_morph_curve_change(self):
        """Debounced: redraw thumbnail and morph strip when curve params change."""
        attr = "_mc_job"
        job = getattr(self, attr, None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        try:
            setattr(self, attr, self.after(25, self._exec_morph_curve_change))
        except (tk.TclError, ValueError):
            pass

    def _exec_morph_curve_change(self):
        self._mc_job = None
        try:
            self._draw_curve_thumbnail()
            self._draw_morph_strip()
        except (tk.TclError, ValueError):
            pass

    def _draw_curve_thumbnail(self):
        """Draws the current morph curve shape on self.curve_canvas."""
        c = self.curve_canvas
        c.delete("all")
        w = max(2, c.winfo_width())
        h = max(2, c.winfo_height())
        if w < 10 or h < 10:
            return
        skew = self.morph_skew_var.get()
        shape = self.morph_shape_var.get()
        # Reference diagonal (linear)
        ref = blend_colors(WAVE_BG, FG_MUTED, 0.35)
        c.create_line(0, h, w, 0, fill=ref, dash=(2, 3))
        # Axis tick marks at 0.25 / 0.5 / 0.75
        for frac in (0.25, 0.5, 0.75):
            x = int(frac * w)
            y = int((1.0 - frac) * h)
            c.create_line(x - 2, y, x + 2, y, fill=ref)
        # Curve
        n = 80
        m_arr = np.linspace(0.0, 1.0, n)
        ms_arr = apply_morph_curve(m_arr, skew, shape)
        pts = []
        for i in range(n):
            pts += [m_arr[i] * w, (1.0 - ms_arr[i]) * h]
        c.create_line(*pts, fill=ACCENT_BLUE, width=2)
        # Labels
        c.create_text(3, h - 3, text="A", anchor="sw", fill=FG_MUTED, font=(UI_FAMILY, 7))
        c.create_text(w - 3, 3, text="B", anchor="ne", fill=FG_MUTED, font=(UI_FAMILY, 7))

    # ----------------------------------------------------------- drawing
    def _geom(self):
        w = max(2, self.canvas.winfo_width())
        h = max(2, self.canvas.winfo_height())
        return w, h, h / 2.0

    def _x_to_index(self, x):
        w, _h, _m = self._geom()
        return int(min(self.POINTS - 1, max(0, round(x / w * (self.POINTS - 1)))))

    def _y_to_value(self, y):
        _w, h, mid = self._geom()
        return float(min(1.0, max(-1.0, (mid - y) / (mid - 6))))

    def _on_press(self, event):
        self._last_xy = (event.x, event.y)
        self._set_point(event.x, event.y)

    def _on_drag(self, event):
        # A fast drag skips pixels, so the span since the last event is filled
        # in - otherwise the drawing gets holes that read as vertical jumps.
        if self._last_xy:
            x0, y0 = self._last_xy
            steps = max(1, int(abs(event.x - x0)))
            for i in range(1, steps + 1):
                f = i / steps
                self._set_point(x0 + (event.x - x0) * f, y0 + (event.y - y0) * f)
        else:
            self._set_point(event.x, event.y)
        self._last_xy = (event.x, event.y)
        self._redraw()

    def _on_release(self, _event=None):
        self._last_xy = None
        self._redraw()

    def _set_point(self, x, y):
        lane = self.active.get()
        self._base_lanes[lane][self._x_to_index(x)] = self._y_to_value(y)
        self._loaded_note = None
        self._recompute_lane(lane)

    def _load_preset(self, label, lane=None):
        lane = lane or self.active.get()
        t = np.arange(self.POINTS) / float(self.POINTS)
        self._base_lanes[lane] = np.asarray(self.PRESETS[label](t), dtype=float)
        self._loaded_note = None
        self._recompute_lane(lane)
        self._redraw()

    def _on_shape_change(self, lane):
        label = self.shape_vars[lane].get()
        if label in self.PRESETS:
            self._load_preset(label, lane=lane)

    def _load_file_lane(self, lane):
        try:
            hz = midi_to_hz(name_to_midi(self.root_note_var.get()))
        except Exception:
            hz = 65.41
        start_dir = load_last_cycle_dir() or getattr(self.app, "import_root", None)
        from pyp6.ui.dialogs.audio import AudioPreviewDialog

        browser = AudioPreviewDialog(self, initial_dir=start_dir, cycle_hz=hz)
        self.wait_window(browser)
        try:
            if browser.current_dir and os.path.isdir(browser.current_dir):
                save_last_cycle_dir(browser.current_dir)
        except Exception:
            pass
        self._safe_grab()
        path = browser.selected_path
        if not path:
            return
        try:
            pts, info = wt_load_cycle_file(path, self.POINTS)
        except Exception as e:
            dark_showerror(
                "Load Waveform", f"Could not read this file as a waveform cycle:\n{e}", parent=self
            )
            return
        if info["long"]:
            keep_hz = (info["rate"] or WT_SR) / float(info["frames"]) * (WT_DRAW_POINTS // 2)
            if not dark_askyesno(
                "Not a Single Cycle?",
                f"This file is {info['frames']} frames long. A single-cycle waveform is usually a few hundred.\n\n"
                f"The whole file becomes one cycle, so only its lowest {WT_DRAW_POINTS // 2} harmonics survive - "
                f"everything above about {keep_hz:.0f} Hz in this file is discarded.\n\nLoad it anyway?",
                parent=self,
            ):
                return
        self._base_lanes[lane] = np.asarray(pts, dtype=float)
        self.shape_vars[lane].set("Custom")
        self._loaded_note = (
            f"{os.path.basename(path)}  \u00b7  {info['frames']} frames "
            f"@ {info['rate']} Hz  \u00b7  {info['harmonics']} harmonics"
        )
        self._recompute_lane(lane)
        self._redraw()

    def _load_file(self):
        self._load_file_lane(self.active.get())

    def _copy_lane(self):
        src = self.active.get()
        dst = "B" if src == "A" else "A"
        # Copy the current transformed output into the destination base
        self._base_lanes[dst] = self.lanes[src].copy()
        self.freq_vars[dst].set(1.0)
        self.phase_vars[dst].set(0)
        self._recompute_lane(dst)
        self._redraw()

    def _swap_lanes(self):
        # Swap base waveform data
        self._base_lanes["A"], self._base_lanes["B"] = (
            self._base_lanes["B"].copy(),
            self._base_lanes["A"].copy(),
        )
        # Swap per-lane parameters
        for var in (self.freq_vars, self.phase_vars, self.shape_vars):
            a_val, b_val = var["A"].get(), var["B"].get()
            var["A"].set(b_val)
            var["B"].set(a_val)
        self._recompute_lane("A")
        self._recompute_lane("B")
        self._redraw()

    def _recompute_lane(self, lane):
        """Apply freq/phase from _base_lanes[lane] → lanes[lane]."""
        vals = self._base_lanes[lane].copy()
        N = len(vals)
        phase_deg = self.phase_vars[lane].get()
        if phase_deg:
            shift = int(round(phase_deg / 360.0 * N)) % N
            vals = np.roll(vals, shift)
        freq = self.freq_vars[lane].get()
        if freq != 1.0 and freq > 0:
            idx_f = np.arange(N, dtype=float) * freq % N
            i0 = idx_f.astype(int) % N
            i1 = (i0 + 1) % N
            frac = idx_f - np.floor(idx_f)
            vals = vals[i0] * (1.0 - frac) + vals[i1] * frac
        n_passes = self.smooth_passes.get()
        for _ in range(n_passes):
            vals = (np.roll(vals, 1) + 2.0 * vals + np.roll(vals, -1)) / 4.0
        self.lanes[lane] = vals

    def _recompute_and_redraw_both(self):
        """Debounced: recompute both lanes (used by global smooth spinbox)."""
        attr = "_rr_job_both"
        job = getattr(self, attr, None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        try:
            setattr(self, attr, self.after(25, self._exec_recompute_both))
        except (tk.TclError, ValueError):
            pass

    def _exec_recompute_both(self):
        self._rr_job_both = None
        try:
            self._recompute_lane("A")
            self._recompute_lane("B")
            self._redraw()
        except (tk.TclError, ValueError):
            pass

    def _recompute_and_redraw(self, lane):
        """Debounced: coalesces rapid spinbox events into a single redraw."""
        attr = f"_rr_job_{lane}"
        job = getattr(self, attr, None)
        if job:
            try:
                self.after_cancel(job)
            except tk.TclError:
                pass
        try:
            setattr(self, attr, self.after(25, lambda: self._exec_recompute(lane, attr)))
        except (tk.TclError, ValueError):
            pass

    def _exec_recompute(self, lane, attr):
        setattr(self, attr, None)
        try:
            self._recompute_lane(lane)
            self._redraw()
        except (tk.TclError, ValueError):
            pass

    def _band_limited(self, values):
        """One cycle as the segment will hold it, at the current settings.

        Deliberately one cycle, not one segment. A segment holds R of them -
        two in the Mid and Lead registers - so rendering the whole segment
        drew two waves on top of a drawing that shows one, at the same width.
        The band limit is what matters here, and it is identical either way.
        """
        try:
            midi = name_to_midi(self.root_note_var.get())
        except Exception:
            midi = name_to_midi("C2")
        cfg = getattr(self.app, "_wt_last_config", None) or {}
        cycles = max(1, int(cfg.get("cycles", 1)))
        up = int(cfg.get("up", 0))
        try:
            L, _f, _c = wt_tuning_info(midi, cycles)
            h, _hm = wt_harmonics_for(L, cycles, up)
        except Exception:
            L, h, cycles = 674, 337, 1
        one = max(16, L // cycles)
        s = WTSynth(one, 1, max(1, min(h, one // 2)))
        return wt_points_to_cycle(values, s), h, min(h, self.POINTS // 2)

    _MORPH_STEPS = 12  # matches WT_MORPH_SHOWN default in SynthDialog

    def _strip_geometry(self):
        """Identical layout to SynthDialog._morph_geometry, on morph_strip."""
        c = self.morph_strip
        w = max(2, c.winfo_width())
        h = max(2, c.winfo_height())
        margin = 6
        usable = h - 2 * margin
        if usable < 20 or w < 60:
            return None
        depth_x = w * 0.22
        depth_y = usable * 0.5
        amp = (usable - depth_y) / 2.0
        base_y = h - margin - amp
        return w, h, depth_x, depth_y, amp, base_y, w - depth_x - 4

    def _strip_points(self, vals, idx, shown, geo):
        """Identical to SynthDialog._morph_points."""
        _w, h, depth_x, depth_y, amp, base_y, front_w = geo
        frac = idx / max(1, shown - 1)
        ox, oy = depth_x * frac, -depth_y * frac
        step = max(1, len(vals) // 220)
        pts = []
        for i in range(0, len(vals), step):
            pts += [ox + i / (len(vals) - 1) * front_w, base_y + oy - vals[i] * amp]
        return pts, ox, oy

    def _draw_morph_strip(self):
        """Isometric morph strip — same visual style as SynthDialog's morph canvas."""
        c = self.morph_strip
        c.delete("all")
        geo = self._strip_geometry()
        if geo is None:
            return
        w, h = geo[0], geo[1]
        shown = self._MORPH_STEPS
        skew = self.morph_skew_var.get()
        shape = self.morph_shape_var.get()
        a, b = self.lanes["A"], self.lanes["B"]
        shapes = []
        for j in range(shown):
            m = j / (shown - 1)
            m_s = float(apply_morph_curve(m, skew, shape))
            vals = a * (1.0 - m_s) + b * m_s
            peak = np.max(np.abs(vals))
            shapes.append(vals / peak if peak > 1e-12 else vals)
        line = readable_on(WAVE_COLOR, WAVE_BG, 7.0)
        for idx in range(shown - 1, -1, -1):
            pts, _ox, _oy = self._strip_points(shapes[idx], idx, shown, geo)
            far = idx / max(1, shown - 1)
            col = blend_colors(line, WAVE_BG, 0.62 * far)
            poly = pts + [pts[-2], h, pts[0], h]
            c.create_polygon(*poly, fill=WAVE_BG, outline="")
            c.create_line(*pts, fill=col, width=2 if idx == 0 else 1, tags=f"step{idx}")
        c.create_text(4, h - 10, text="A", anchor="w", fill=FG_MUTED, font=(UI_FAMILY, 7, "bold"))
        c.create_text(w - 4, 10, text="B", anchor="e", fill=FG_MUTED, font=(UI_FAMILY, 7))
        self._highlight_strip_step(None)

    def _highlight_strip_step(self, frac):
        """Highlights the step currently sounding (frac 0..1). None clears."""
        c = self.morph_strip
        c.delete("stripmark")
        if frac is None:
            return
        geo = self._strip_geometry()
        if geo is None:
            return
        shown = self._MORPH_STEPS
        skew = self.morph_skew_var.get()
        shape = self.morph_shape_var.get()
        a, b = self.lanes["A"], self.lanes["B"]
        idx = int(min(shown - 1, max(0, round(frac * (shown - 1)))))
        m = idx / (shown - 1)
        m_s = float(apply_morph_curve(m, skew, shape))
        vals = a * (1.0 - m_s) + b * m_s
        peak = np.max(np.abs(vals))
        vals = vals / peak if peak > 1e-12 else vals
        pts, _ox, _oy = self._strip_points(vals, idx, shown, geo)
        c.create_line(*pts, fill=ACCENT_ORANGE, width=2, tags="stripmark")

    def _redraw(self):
        c = self.canvas
        c.delete("all")
        w, h, mid = self._geom()
        grid = blend_colors(WAVE_BG, FG_MUTED, 0.25)
        for frac in (0.25, 0.5, 0.75):
            c.create_line(w * frac, 0, w * frac, h, fill=grid, dash=(2, 4))
        c.create_line(0, mid, w, mid, fill=blend_colors(WAVE_BG, FG_MUTED, 0.45))

        src = self.active.get()
        dst = "B" if src == "A" else "A"
        vals = self.lanes[src]
        other = self.lanes[dst]
        span = mid - 6

        def poly(values, color, width, dash=None):
            pts = []
            for i, v in enumerate(values):
                pts += [i / (len(values) - 1) * w, mid - v * span]
            kw = dict(fill=color, width=width, smooth=False)
            if dash:
                kw["dash"] = dash
            c.create_line(*pts, **kw)

        poly(other, blend_colors(WAVE_BG, FG_MUTED, 0.55), 1, dash=(3, 3))
        poly(vals, readable_on(WAVE_COLOR, WAVE_BG, 7.0), 2)

        usable = min(self.POINTS // 2, 1)
        if self.show_result.get():
            band, h_avail, usable = self._band_limited(vals)
            step = max(1, len(band) // 600)
            poly(band[::step], ACCENT_ORANGE, 1)
            self.info.config(
                text=f"Shape {self.active.get()}  \u00b7  drawn with {self.POINTS} points "
                f"\u2192 {usable} harmonics usable  \u00b7  the segment allows "
                f"{h_avail}  \u00b7  orange is what will sound"
            )
        else:
            self.info.config(
                text=f"Shape {self.active.get()}  \u00b7  dashed line is the "
                f"other shape  \u00b7  the family morphs A \u2192 B"
            )
        note = getattr(self, "_loaded_note", None)
        if note:
            self.info.config(text=self.info.cget("text") + "\n" + note)

        self._draw_morph_strip()
        self._draw_curve_thumbnail()

    # ----------------------------------------------------------- preview
    def _toggle_preview(self):
        if self._preview_playing:
            self._stop_preview()
            return
        try:
            cfg = getattr(self.app, "_wt_last_config", None) or {}
            try:
                midi = name_to_midi(self.root_note_var.get()) + self.fine_tune_var.get() / 100.0
            except Exception:
                midi = name_to_midi(cfg.get("note", "C2"))
            audio = wt_render_sweep(
                self._entry(), midi, int(cfg.get("cycles", 1)), int(cfg.get("up", 0)), 24
            )
            play_audio(audio, WT_SR)
        except Exception as e:
            dark_showerror("Preview", f"Could not play the sweep:\n{e}", parent=self)
            return
        self._preview_playing = True
        self._strip_token = object()
        self.prev_btn.text = "\u25a0"
        self.prev_btn._draw()
        self.after(int(WT_PREVIEW_SECONDS * 1000) + 100, self._stop_preview)
        self._tick_strip_marker(self._strip_token, time.time())

    def _tick_strip_marker(self, token, t0):
        if token is not getattr(self, "_strip_token", None):
            return
        elapsed = time.time() - t0
        if elapsed >= WT_PREVIEW_SECONDS:
            self._highlight_strip_step(None)
            return
        self._highlight_strip_step(elapsed / WT_PREVIEW_SECONDS)
        self.after(40, lambda: self._tick_strip_marker(token, t0))

    def _stop_preview(self):
        if not self._preview_playing:
            return
        self._preview_playing = False
        self._strip_token = None
        try:
            sd.stop()
        except Exception:
            pass
        try:
            self.prev_btn.text = "\u25b6"
            self.prev_btn._draw()
        except tk.TclError:
            pass
        self._highlight_strip_step(None)

    # ----------------------------------------------------------- result
    def _entry(self):
        skew = round(self.morph_skew_var.get(), 4)
        shape = round(self.morph_shape_var.get(), 4)
        d = {
            "kind": "draw",
            "name": self.name_var.get().strip() or "Custom",
            # Rounded on the way out: a preset folder is meant to be
            # swapped around, and full float repr would triple its size
            # for precision no ear can use.
            "a": [round(float(v), 4) for v in self.lanes["A"]],
            "b": [round(float(v), 4) for v in self.lanes["B"]],
        }
        if skew:
            d["morph_skew"] = skew
        if shape:
            d["morph_shape"] = shape
        return d

    def _apply(self):
        self._stop_preview()
        self.result = self._entry()
        if self.on_apply:
            self.on_apply(self.result)
        self.destroy()

    def _delete(self):
        name = self.name_var.get().strip() or "Custom"
        if not dark_askyesno(
            "Delete Waveform",
            f'Remove "{name}" from the saved waveforms?\n\n'
            "Wavetables already built with it are not affected.",
            parent=self,
        ):
            return
        self._stop_preview()
        self.result = {"delete": name}
        if self.on_apply:
            self.on_apply(self.result)
        self.destroy()

    def _cancel(self):
        self._stop_preview()
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# SynthDialog
# ---------------------------------------------------------------------------


class SynthDialog(tk.Toplevel):
    """The wavetable builder, themed to match the main window.

    Bank and pad come from the calling pad, so there is no bank/pad picker
    here; the init patch and poly switch live on the pad itself. Everything
    else from the standalone tool is present."""

    def __init__(self, parent, app, bank, pad, initial_config=None):
        super().__init__(parent)
        style_toplevel(self)
        self.title(f"Synth  \u2014  Bank {bank}  Pad {pad}")
        self.app = app
        # bank/pad are only used for the window title above. The PRM is
        # written by the pad itself, from wherever it sits at that moment -
        # keeping copies here would invite writing a stale PHRASE.
        self.result = None
        self.prev_family = None
        self.prev_playing = False
        self.transient(parent)
        self.resizable(True, True)

        cfg = dict(initial_config or {})
        self.var_mode = tk.StringVar(value=cfg.get("mode", "Simple"))
        self.var_reg = tk.StringVar(value=cfg.get("register", "Bass"))
        self.var_note = tk.StringVar(value=cfg.get("note", "C2"))
        self.var_up = tk.IntVar(value=int(cfg.get("up", 0)))
        self.var_save_map = tk.BooleanVar(value=bool(cfg.get("save_map", False)))
        self.var_autoplay = tk.BooleanVar(value=load_default_autoplay())
        # The two listboxes keep holding plain names; the drawn shapes live
        # here and are looked up by name. Putting dicts into a Listbox would
        # have meant rewriting every selection, reorder and duplicate check.
        #
        # Starts from the saved library, then this pad's own shapes are laid
        # over it. The pad wins on a name clash: its table was built from
        # that exact shape, and a same-named entry in the library would
        # otherwise silently change what a rebuild produces.
        self.custom = load_drawn_library()
        for entry in cfg.get("custom") or []:
            nm = entry.get("name")
            if nm:
                self.custom[nm] = entry

        self._build()
        base = WT_REGISTERS[self.var_reg.get()][0]
        self.dd_note.values = [midi_to_name(base + o) for o in range(-6, 7)]
        if cfg.get("families"):
            dropped, over_limit = [], []
            for name in cfg["families"]:
                # Drawn families are not in WT_FAMILY_MAP - they live in
                # self.custom, restored from the config a few lines above.
                if not (name in WT_FAMILY_MAP or name in self.custom):
                    dropped.append(name)
                elif self.lb_sel.size() >= WT_MAX_SELECTED:
                    over_limit.append(name)
                else:
                    self.lb_sel.insert("end", name)
            if over_limit:
                dropped.extend(over_limit)
            if dropped:
                # Silently shortening the step order would change the table
                # on the next build without the user noticing.
                self.after(
                    60,
                    lambda d=list(dropped), o=list(over_limit): dark_showwarning(
                        "Step Order Shortened",
                        "This pad's wavetable used families that could not all be "
                        "restored:\n\n"
                        + "\n".join(f"\u2022 {n}" for n in d)
                        + (
                            f"\n\nThe step order is limited to {WT_MAX_SELECTED} families."
                            if o
                            else ""
                        )
                        + "\n\nThey have been left out of the step order. Rebuilding "
                        "now would produce a different table.",
                        parent=self,
                    ),
                )
        self._apply_mode(restore=bool(cfg))
        center_toplevel_on_parent(self, parent)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()

    # -- layout ------------------------------------------------------------

    def _scrolled_list(self, parent, title=None):
        """Returns (outer, listbox). With a title the list is wrapped in a
        RoundedPanel, matching how the Chop dialog frames its two lists."""
        panel = None
        if title is not None:
            panel = RoundedPanel(
                parent,
                title=title,
                parent_bg=parent.cget("bg"),
                panel_bg=BG_PANEL,
                radius=12,
                title_font=(UI_FAMILY, 9, "bold"),
                body_padx=10,
                body_pady=(24, 8),
            )
            parent = panel.body
        box = tk.Frame(parent, bg=BG_PANEL)
        box.rowconfigure(0, weight=1)
        box.columnconfigure(0, weight=1)
        lb = tk.Listbox(box, selectmode="extended", exportselection=False, height=13)
        style_listbox(lb)
        lb.grid(row=0, column=0, sticky="nsew")
        vs = RoundedScrollbar(box, orient="vertical", command=lb.yview, parent_bg=BG_PANEL)
        vs.grid(row=0, column=1, sticky="ns", padx=(3, 0))
        hs = RoundedScrollbar(box, orient="horizontal", command=lb.xview, parent_bg=BG_PANEL)
        hs.grid(row=1, column=0, sticky="ew", pady=(3, 0))
        lb.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)

        def wheel(event):
            if getattr(event, "num", None) == 4:
                lb.yview_scroll(-1, "units")
            elif getattr(event, "num", None) == 5:
                lb.yview_scroll(1, "units")
            else:
                lb.yview_scroll(-1 if event.delta > 0 else 1, "units")
            return "break"

        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            lb.bind(seq, wheel)
        if panel is not None:
            box.pack(fill="both", expand=True)
            return panel, lb
        return box, lb

    def _build(self):
        root = tk.Frame(self, bg=BG_DARK, padx=14, pady=14)
        root.pack(fill="both", expand=True)

        modebar = tk.Frame(root, bg=BG_DARK)
        modebar.pack(fill="x", pady=(0, 10))
        lbl = tk.Label(modebar, text="Mode")
        style_label(lbl, font=(UI_FAMILY, 9, "bold"))
        lbl.pack(side="left")
        for txt in ("Simple", "Advanced"):
            rb = tk.Radiobutton(
                modebar, text=txt, value=txt, variable=self.var_mode, command=self._apply_mode
            )
            style_checkbutton(rb)
            rb.pack(side="left", padx=(10, 0))
        self.lbl_mode_hint = tk.Label(modebar, text="")
        style_label(self.lbl_mode_hint, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.lbl_mode_hint.pack(side="left", padx=(16, 0))
        add_tooltip(
            modebar,
            "Simple bakes all 16 waveform families into the table and only "
            "asks for the register. Advanced lets you pick the root note, the "
            "upward playing range and exactly which families go in.",
        )

        # --- pitch ---
        pitch_panel = RoundedPanel(root, title="PITCH", parent_bg=BG_DARK, title_fg=ACCENT_BLUE)
        pitch_panel.pack(fill="x")
        pf = pitch_panel.body

        row = tk.Frame(pf, bg=BG_PANEL)
        row.pack(fill="x")
        l1 = tk.Label(row, text="Register")
        style_label(l1, bg=BG_PANEL, font=(UI_FAMILY, 9))
        l1.pack(side="left")
        dd = RoundedDropdown(
            row,
            self.var_reg,
            list(WT_REGISTERS),
            command=lambda _v=None: self._on_register(),
            parent_bg=BG_PANEL,
            width=90,
            height=26,
            font=(UI_FAMILY, 9),
        )
        dd.pack(side="left", padx=(6, 18))
        add_tooltip(
            dd,
            "Bass keeps the full harmonic content and is meant to be played at "
            "the root note or below. Mid and Lead are band limited so they stay "
            "alias-free one or two octaves up.",
        )

        self.adv_row = tk.Frame(row, bg=BG_PANEL)
        self.adv_row.pack(side="left")
        self.lbl_note = tk.Label(self.adv_row, text="Root note")
        style_label(self.lbl_note, bg=BG_PANEL, font=(UI_FAMILY, 9))
        self.lbl_note.pack(side="left")
        self.dd_note = RoundedDropdown(
            self.adv_row,
            self.var_note,
            ["C2"],
            command=lambda _v=None: self._refresh(),
            parent_bg=BG_PANEL,
            width=70,
            height=26,
            font=(UI_FAMILY, 9),
        )
        self.dd_note.pack(side="left", padx=(6, 18))
        add_tooltip(
            self.dd_note,
            "The note the wavetable is tuned to, six semitones either side of "
            "the register default. Baking your key in here means the pad plays "
            "at 1:1 with no interpolation loss.",
        )

        self.lbl_up = tk.Label(self.adv_row, text="Plays up to")
        style_label(self.lbl_up, bg=BG_PANEL, font=(UI_FAMILY, 9))
        self.lbl_up.pack(side="left")
        self.sp_up = tk.Spinbox(
            self.adv_row,
            from_=0,
            to=36,
            width=4,
            textvariable=self.var_up,
            command=self._refresh,
            bg=BG_INPUT,
            fg=FG_TEXT,
            buttonbackground=BG_INPUT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            insertbackground=FG_TEXT,
            font=(UI_FAMILY, 9),
        )
        self.sp_up.pack(side="left", padx=6)
        self.sp_up.bind("<KeyRelease>", lambda e: self._refresh())
        self.lbl_up_unit = tk.Label(self.adv_row, text="semitones above root")
        style_label(self.lbl_up_unit, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.lbl_up_unit.pack(side="left")
        add_tooltip(
            self.sp_up,
            "How far above the root note you intend to play. Aliasing only "
            "happens when transposing up, so this sets the band limit: "
            "harmonics = maximum / 2^(semitones/12).",
        )

        self.lbl_info = tk.Label(pf, text="", justify="left")
        style_label(self.lbl_info, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.lbl_info.pack(fill="x", pady=(8, 0))

        # --- wavetable ---
        # No panel around this section: each list carries its own frame, and a
        # box drawn around both of them just competed with those two.
        self.wt_panel = tk.Frame(root, bg=BG_DARK)
        self.wt_panel.pack(fill="both", expand=True, pady=(12, 0))
        wf = self.wt_panel
        wf.columnconfigure(0, weight=1)
        wf.columnconfigure(2, weight=1)
        wf.rowconfigure(1, weight=1)

        box_a, self.lb_avail = self._scrolled_list(wf, title="Available")
        box_a.grid(row=1, column=0, sticky="nsew")
        self._fill_available()
        # Double-click moves a built-in across, but reopens a drawing for
        # editing - there is no other way back into a shape you made.
        self.lb_avail.bind("<Double-Button-1>", self._on_avail_double)
        self.lb_avail.bind("<<ListboxSelect>>", lambda e: self._pick_preview(self.lb_avail))

        col = tk.Frame(wf, bg=BG_DARK)
        col.grid(row=1, column=1, padx=8)
        # Clearing everything lives in the footer next to Apply/Cancel, the
        # same place the Chop dialog puts Clear Selection. An arrow glyph in
        # this column would have been one more thing to decode.
        for txt, cmd, tip in (
            ("\u2192", self._move_right, "Moves the highlighted families into the step order."),
            ("\u2190", self._move_left, "Takes the highlighted families back out."),
            (
                "\u25b2",
                lambda: self._reorder(-1),
                "Moves the highlighted families one place earlier.",
            ),
            ("\u25bc", lambda: self._reorder(1), "Moves the highlighted families one place later."),
        ):
            b = RoundedButton(
                col,
                text=txt,
                command=cmd,
                bg=BG_INPUT,
                fg=FG_TEXT,
                parent_bg=BG_DARK,
                width=40,
                height=26,
                font=(UI_FAMILY, 10, "bold"),
            )
            b.pack(pady=3)
            add_tooltip(b, tip)

        # Between the two lists, since it previews the family highlighted in
        # either one. Glyph only: the family name would have set the width of
        # the whole column, and it changes with every click.
        self.btn_prev = RoundedButton(
            col,
            text="\u25b6",
            command=self._toggle_preview,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=40,
            height=26,
            state="disabled",
            font=(UI_FAMILY, 10, "bold"),
        )
        self.btn_prev.pack(pady=(14, 3))
        add_tooltip(
            self.btn_prev,
            "Plays a sweep through the family highlighted in either column, at "
            "the configured root note and with the same band limit the finished "
            "table will have.",
        )

        self.btn_draw = RoundedButton(
            col,
            text="\u270e",
            command=self._open_draw,
            bg=BTN_ORANGE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=40,
            height=26,
            font=(UI_FAMILY, 11, "bold"),
        )
        self.btn_draw.pack(pady=(14, 3))
        add_tooltip(
            self.btn_draw,
            "Opens the Waveform Creator: build a waveform by hand or load a "
            "single-cycle file, and it joins the list on the left as its own "
            "family. Two shapes are made, and the family morphs from one to "
            "the other.\nDouble-click one of your own waveforms to edit it "
            "again.",
        )

        # Red only while a drawn family is highlighted. The built-in sixteen
        # cannot be deleted, so an always-red button would promise something
        # it refuses to do most of the time.
        self.btn_del = RoundedButton(
            col,
            text="\u2715",
            command=self._delete_custom,
            bg=BTN_RED,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=40,
            height=26,
            font=(UI_FAMILY, 11, "bold"),
            state="disabled",
        )
        self.btn_del.pack(pady=3)
        add_tooltip(
            self.btn_del,
            "Deletes the highlighted hand-drawn waveform - from the list, "
            "from the step order and from the saved library. Only the drawn "
            "ones can go; the built-in families are fixed.\nWavetables already "
            "built with it keep working.",
        )

        box_s, self.lb_sel = self._scrolled_list(wf, title="Step Order")
        box_s.grid(row=1, column=2, sticky="nsew")
        self.lb_sel.bind("<Double-Button-1>", lambda e: self._move_left())
        self.lb_sel.bind("<<ListboxSelect>>", lambda e: self._pick_preview(self.lb_sel))

        # Fixed-height box + wraplength tied to the panel width: the label can
        # never widen the dialog, and it cannot change its height either.
        alloc_box = tk.Frame(wf, bg=BG_DARK, height=44)
        alloc_box.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        alloc_box.grid_propagate(False)
        self.lbl_alloc = tk.Label(alloc_box, text="", justify="left", anchor="nw")
        style_label(self.lbl_alloc, bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.lbl_alloc.place(x=0, y=0, relwidth=1.0, relheight=1.0)
        alloc_box.bind(
            "<Configure>", lambda e: self.lbl_alloc.config(wraplength=max(200, e.width - 4))
        )

        morph_panel = RoundedPanel(
            wf,
            title="Morph",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        morph_panel.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.morph_canvas = tk.Canvas(
            morph_panel.body, bg=WAVE_BG, highlightthickness=0, height=WT_MORPH_HEIGHT
        )
        self.morph_canvas.pack(fill="x")
        self.morph_canvas.bind("<Configure>", lambda e: self._schedule_morph_work(autoplay=False))
        add_tooltip(
            self.morph_canvas,
            "The waveforms this family steps through, front to back: the "
            "first step nearest, the last furthest away. During preview the "
            "step being played is highlighted.",
        )
        self._morph_cache = None

        prev = tk.Frame(wf, bg=BG_DARK)
        prev.grid(row=4, column=0, columnspan=3, sticky="w", pady=(8, 0))
        self.cb_autoplay = tk.Checkbutton(
            prev, text="Autoplay on click", variable=self.var_autoplay
        )
        style_checkbutton(self.cb_autoplay)
        self.cb_autoplay.pack(side="left", padx=(0, 14))
        add_tooltip(
            self.cb_autoplay,
            "Plays the morph sweep as soon as you click a family, instead "
            "of waiting for the play button. Clicking a different family "
            "always stops whatever is running.\nThe starting position of "
            "this switch is set under Settings \u2192 Defaults.",
        )
        self.lbl_prev = tk.Label(prev, text="")
        style_label(self.lbl_prev, bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.lbl_prev.pack(side="left")

        # --- footer ---
        foot = tk.Frame(root, bg=BG_DARK)
        self.foot = foot
        foot.pack(fill="x", pady=(12, 0))
        self.btn_clear = RoundedButton(
            foot,
            text="Clear Selection",
            command=self._clear_all,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=130,
        )
        self.btn_clear.pack(side="left", padx=(0, 12))
        add_tooltip(self.btn_clear, "Empties the step order on the right. Nothing else is changed.")
        self.cb_map = tk.Checkbutton(
            foot, text="Save waveform overview (CSV)", variable=self.var_save_map
        )
        style_checkbutton(self.cb_map)
        self.cb_map.pack(side="left")
        add_tooltip(
            self.cb_map,
            "Writes a table listing what sits on every one of the 255 steps: "
            "family, morph position and start frame. A file dialog opens after "
            "you click Apply.",
        )

        # Deliberately identical to the Chop dialog's footer: same colours,
        # same widths, same padding, same order.
        cancel_btn = RoundedButton(
            foot, text="Cancel", command=self._cancel, bg=BG_INPUT, fg=FG_TEXT, parent_bg=BG_DARK
        )
        cancel_btn.pack(side="right", padx=4)
        self.btn_apply = RoundedButton(
            foot,
            text="Build Wavetable",
            command=self._apply,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=150,
        )
        self.btn_apply.pack(side="right", padx=4)
        add_tooltip(
            self.btn_apply,
            "Builds the wavetable and puts it on the pad together with its "
            ".PRM settings file. On the P-6 set SIZE to 1 and sweep START to "
            "step through the waveforms.",
        )

        # Same reasoning as lbl_alloc - status text length varies a lot.
        self.lbl_status = tk.Label(root, text="", justify="left", anchor="w", wraplength=560)
        style_label(self.lbl_status, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        self.lbl_status.pack(fill="x", pady=(8, 0))

    # -- logic -------------------------------------------------------------

    def _simple(self):
        return self.var_mode.get() == "Simple"

    def _apply_mode(self, restore=False):
        simple = self._simple()
        self._stop_preview()
        self._status("")
        if simple:
            self.adv_row.pack_forget()
            self.wt_panel.pack_forget()
            self.lbl_mode_hint.config(
                text=f"all {len(WT_FAMILIES)} families across {WT_SEGMENTS} steps"
            )
        else:
            self.adv_row.pack(side="left")
            self.wt_panel.pack(fill="both", expand=True, pady=(12, 0), before=self.foot)
            self.lbl_mode_hint.config(text="")
        if hasattr(self, "lb_avail"):
            self._fill_available()
        if not restore:
            self._on_register()
        else:
            self._refresh()
        self._pin_size()

    def _pin_size(self):
        """Freezes the window at the size the current mode needs.

        Tk keeps a Toplevel glued to its requested size until an explicit
        width x height geometry is set. Setting one here means later content
        changes - a longer allocation line, a status message - redraw inside
        the window instead of resizing it. Called on every mode switch so
        Simple and Advanced can still have different sizes.
        """
        try:
            self.geometry("")  # recompute from content once
            self.update_idletasks()
            w = max(self.winfo_reqwidth(), 520)
            h = max(self.winfo_reqheight(), 200)
            self.minsize(w, h)
            self.geometry(f"{w}x{h}")
        except Exception:
            pass

    def _on_register(self):
        base, cycles, up = WT_REGISTERS[self.var_reg.get()]
        self.dd_note.values = [midi_to_name(base + o) for o in range(-6, 7)]
        self.var_note.set(midi_to_name(base))
        self.var_up.set(up)
        self._refresh()

    def _selection(self):
        return list(self.lb_sel.get(0, "end"))

    def _active_selection(self):
        """Names, in step order. Simple mode always uses all built-ins."""
        return [n for n, _f in WT_FAMILIES] if self._simple() else self._selection()

    def _resolve(self, name):
        """Name -> what the engine needs: a drawn entry, or the name itself."""
        return self.custom.get(name, name)

    def _resolved_selection(self):
        return [self._resolve(n) for n in self._active_selection()]

    def _unique_custom_name(self, base="Custom", allow=None):
        """A free name based on `base`. `allow` is the one name that may be
        kept - the shape currently being edited."""
        taken = (set(self.custom) | {nm for nm, _f in WT_FAMILIES}) - {allow}
        if base not in taken:
            return base
        # Strip a trailing counter first, so editing "Custom 2" into a clash
        # gives "Custom 3" rather than "Custom 2 2".
        stem = re.sub(r"\s+\d+$", "", base) or base
        n = 2
        while f"{stem} {n}" in taken:
            n += 1
        return f"{stem} {n}"

    def _open_draw(self, existing=None):
        # The draw dialog previews at the pitch this dialog is set to, so it
        # needs the current settings, not the ones from the last build.
        midi, cycles, up = self._current_pitch()
        self.app._wt_last_config = {"note": self.var_note.get(), "cycles": cycles, "up": up}
        entry = self.custom.get(existing) if existing else None
        dlg = WaveformCreatorDialog(self, self.app, entry=entry)
        self.wait_window(dlg)
        if not dlg.result:
            return
        if dlg.result.get("delete"):
            gone = existing or dlg.result["delete"]
            self.custom.pop(gone, None)
            save_drawn_library(
                {
                    n: e
                    for n, e in self.custom.items()
                    if isinstance(e, dict) and e.get("kind") == "draw"
                }
            )
            for i in reversed(range(self.lb_sel.size())):
                if self.lb_sel.get(i) == gone:
                    self.lb_sel.delete(i)
            self._fill_available()
            self._refresh()
            self._status(f"{gone} deleted.", "warn")
            return
        new = dlg.result
        old_name = existing
        # Renaming has to carry the step order with it, otherwise the entry
        # in the right-hand list would point at a name that no longer exists.
        if old_name and old_name != new["name"] and old_name in self.custom:
            del self.custom[old_name]
            items = self._selection()
            self.lb_sel.delete(0, "end")
            for it in items:
                self.lb_sel.insert("end", new["name"] if it == old_name else it)
        # Reusing a name used to overwrite the older shape without a word.
        # Numbering it instead keeps both, and the status line says so -
        # a drawing cannot be reconstructed once it is gone.
        wanted = new["name"]
        new["name"] = self._unique_custom_name(wanted, allow=old_name)
        renamed = new["name"] != wanted
        self.custom[new["name"]] = new
        self._morph_shape_cache = None  # the shape changed under its name
        if not save_drawn_library(
            {
                n: e
                for n, e in self.custom.items()
                if isinstance(e, dict) and e.get("kind") == "draw"
            }
        ):
            self._status("Waveform kept for this pad, but the library could not be written.", "bad")
        self._fill_available()
        # A shape you just drew is almost certainly meant to be used, so it
        # goes straight into the step order - unless it is already there
        # (editing an existing one) or there is no room left.
        note = f'"{wanted}" was already taken, saved as "{new["name"]}".  ' if renamed else ""
        cur = self._selection()
        if new["name"] not in cur:
            if len(cur) < WT_MAX_SELECTED:
                self.lb_sel.insert("end", new["name"])
                self._status(
                    f"{note}{new['name']} added to the step order.", "warn" if renamed else "good"
                )
            else:
                self._status(
                    f"{note}{new['name']} is in the list on the left. The "
                    f"step order is full ({WT_MAX_SELECTED}), so it was "
                    f"not added - take something out to make room.",
                    "warn",
                )
        elif renamed:
            self._status(note.strip(), "warn")
        self._refresh()

    def _fill_available(self):
        """Built-ins first, then the drawn ones, so the fixed set keeps a
        stable order no matter how many shapes get added."""
        self.lb_avail.delete(0, "end")
        for nm, _f in WT_FAMILIES:
            self.lb_avail.insert("end", nm)
        for nm in self.custom:
            self.lb_avail.insert("end", nm)
        self._sync_delete_button()

    def _on_avail_double(self, _event=None):
        sel = self.lb_avail.curselection()
        if sel and self.lb_avail.get(sel[0]) in self.custom:
            self._edit_selected_custom()
        else:
            self._move_right()

    def _edit_selected_custom(self, _event=None):
        sel = self.lb_avail.curselection()
        if not sel:
            return
        name = self.lb_avail.get(sel[0])
        if name in self.custom:
            self._open_draw(existing=name)

    def _move_right(self):
        cur = self._selection()
        added, skipped, no_room = 0, [], []
        for i in self.lb_avail.curselection():
            name = self.lb_avail.get(i)
            if name in cur:
                skipped.append(name)
                continue
            if len(cur) >= WT_MAX_SELECTED:
                no_room.append(name)
                continue
            self.lb_sel.insert("end", name)
            cur.append(name)
            added += 1
        self._refresh()
        if no_room:
            self._status(
                f"The step order holds {WT_MAX_SELECTED} families at most. "
                f"No room for {', '.join(no_room)} - take something out "
                f"first.",
                "warn",
            )
            return
        # Silently doing nothing is the worst outcome here - the click looks
        # broken. Each family can only appear once, so say so.
        if skipped and not added:
            self._status(
                "Already in the step order: "
                + ", ".join(skipped)
                + ".  Each family can be used once; reorder it with the "
                "arrows instead.",
                "warn",
            )
        elif skipped:
            self._status(
                f"Added {added}, skipped {len(skipped)} already in the "
                f"step order ({', '.join(skipped)}).",
                "info",
            )
        else:
            self._status("")

    def _move_left(self):
        for i in reversed(self.lb_sel.curselection()):
            self.lb_sel.delete(i)
        self._refresh()

    def _clear_all(self):
        self.lb_sel.delete(0, "end")
        self._refresh()

    def _reorder(self, delta):
        idx = list(self.lb_sel.curselection())
        if not idx:
            return
        items = self._selection()
        order = idx if delta < 0 else list(reversed(idx))
        moved = []
        for i in order:
            j = i + delta
            if 0 <= j < len(items) and j not in moved:
                items[i], items[j] = items[j], items[i]
                moved.append(j)
        self.lb_sel.delete(0, "end")
        for it in items:
            self.lb_sel.insert("end", it)
        for i in moved:
            self.lb_sel.selection_set(i)
        self._refresh()

    def _current_pitch(self):
        try:
            midi = name_to_midi(self.var_note.get())
        except (ValueError, KeyError):
            midi = WT_REGISTERS[self.var_reg.get()][0]
        cycles = WT_REGISTERS[self.var_reg.get()][1]
        try:
            up = max(0, int(self.var_up.get()))
        except (tk.TclError, ValueError):
            up = 0
        return midi, cycles, up

    def _refresh(self):
        midi, cycles, up = self._current_pitch()
        L, f_real, cents = wt_tuning_info(midi, cycles)
        h, h_max = wt_harmonics_for(L, cycles, up)
        warn = (
            ""
            if L <= WT_MAX_SEG_FRAMES
            else f"    too long (max {WT_MAX_SEG_FRAMES} frames/segment)"
        )
        self.lbl_info.config(
            text=(
                f"Segment {L} frames \u00d7 {cycles} cycles    \u00b7    "
                f"{f_real:.3f} Hz ({cents:+.2f} cents)    \u00b7    "
                f"total {WT_SEGMENTS * L / WT_SR:.4f} s    \u00b7    "
                f"step {L / WT_SR * 1000:.3f} ms    \u00b7    "
                f"START 0-{WT_SEGMENTS - 1}\n"
                f"{h} of {h_max} possible harmonics    \u00b7    "
                f"highest at {h * f_real / 1000:.2f} kHz at the root note{warn}"
            )
        )

        sel = self._selection()
        # Families already in use are dimmed in the left column, so the state
        # is visible before anyone clicks the arrow.
        used = set(sel)
        for i in range(self.lb_avail.size()):
            self.lb_avail.itemconfig(
                i, foreground=FG_MUTED if self.lb_avail.get(i) in used else FG_TEXT
            )
        if sel:
            counts = wt_split_steps(len(sel))
            cap = "" if len(sel) < WT_MAX_SELECTED else "   (step order full)"
            self.lbl_alloc.config(
                text=f"{len(sel)} of {WT_MAX_SELECTED} families "
                f"\u2192 " + "   ".join(f"{n}: {c}" for n, c in zip(sel, counts)) + cap
            )
        else:
            self.lbl_alloc.config(
                text=f"Nothing selected \u2013 move at least one family to the "
                f"right (up to {WT_MAX_SELECTED})"
            )
        self._update_preview_label()

    # -- preview -----------------------------------------------------------

    def _pick_preview(self, listbox):
        cur = listbox.curselection()
        if not cur:
            return
        picked = listbox.get(cur[0])
        # Switching families mid-sweep used to leave the old one playing under
        # the new one's curves - what you saw and what you heard came from
        # different families. The sound belongs to the drawing on screen, so
        # picking a different one ends it.
        if self.prev_playing and picked != self.prev_family:
            self._stop_preview()
        self.prev_family = picked
        other = self.lb_sel if listbox is self.lb_avail else self.lb_avail
        other.selection_clear(0, "end")
        self._sync_delete_button()
        self._update_preview_label()
        # Debounced. Rendering the stack costs ~10 ms and building an autoplay
        # sweep ~50 ms, so arrowing through the list at five clicks a second
        # queued a third of a second of work per second and the window stopped
        # responding. Only the family you land on is worth rendering.
        self._schedule_morph_work()

    MORPH_DEBOUNCE_MS = 130

    def _schedule_morph_work(self, autoplay=True):
        if getattr(self, "_morph_job", None):
            try:
                self.after_cancel(self._morph_job)
            except (tk.TclError, ValueError):
                pass
        # A resize that arrives while a click is pending must not cancel the
        # click's intent to play.
        self._morph_autoplay = autoplay or getattr(self, "_morph_autoplay", False)
        self._morph_job = self.after(self.MORPH_DEBOUNCE_MS, self._do_morph_work)

    def _do_morph_work(self):
        self._morph_job = None
        autoplay = getattr(self, "_morph_autoplay", False)
        self._morph_autoplay = False
        try:
            self._draw_morph()
        except tk.TclError:
            return
        # Only when nothing is running: clicking the family that is already
        # playing should not cut it off, and a switch stopped the previous one
        # back in _pick_preview.
        if autoplay and self.var_autoplay.get() and not self.prev_playing and self.prev_family:
            self._toggle_preview()

    def _status(self, text, kind="info"):
        """One place for the line under the dialog.

        Everything used to be muted grey, including the messages that ask you
        to do something - so "the step order is full" read like a footnote
        and got missed. The tone now picks the colour.
        """
        colors = {"info": FG_MUTED, "good": ACCENT_GREEN, "warn": ACCENT_ORANGE, "bad": ACCENT_RED}
        self.lbl_status.config(text=text, fg=colors.get(kind, FG_MUTED))

    def _sync_delete_button(self):
        """Live only for a drawn family highlighted in the left column."""
        if not hasattr(self, "btn_del"):
            return
        cur = self.lb_avail.curselection()
        name = self.lb_avail.get(cur[0]) if cur else None
        self.btn_del.config_state("normal" if name in self.custom else "disabled")

    def _delete_custom(self):
        cur = self.lb_avail.curselection()
        if not cur:
            return
        name = self.lb_avail.get(cur[0])
        entry = self.custom.get(name)
        if not entry:
            return
        in_order = name in self._selection()
        if not dark_askyesno(
            "Delete Waveform",
            f'Remove "{name}" from the saved waveforms?'
            + ("\n\nIt is currently in the step order and will be taken out." if in_order else "")
            + "\n\nWavetables already built with it are not affected.",
            parent=self,
        ):
            return
        self.custom.pop(name, None)
        save_drawn_library(
            {
                n: e
                for n, e in self.custom.items()
                if isinstance(e, dict) and e.get("kind") == "draw"
            }
        )
        for i in reversed(range(self.lb_sel.size())):
            if self.lb_sel.get(i) == name:
                self.lb_sel.delete(i)
        if self.prev_family == name:
            self.prev_family = None
        self._fill_available()
        self._sync_delete_button()
        self._refresh()
        self._status(f"{name} deleted.", "warn")

    def _morph_shapes(self, family, count):
        """Renders the shapes this family steps through, for display only.

        Rendered at the real segment length and harmonic count, not at a
        convenient round number. A coarser display costs accuracy exactly
        where it is least acceptable: families whose morph mainly adds upper
        harmonics - Saw above all - looked far flatter than they sound,
        because at 64 harmonics the ones being added were never there. At the
        true resolution all sixteen families are drawn with no visible loss,
        for about 15 ms per redraw.
        """
        midi, cycles, up = self._current_pitch()
        try:
            L, f_real, _c = wt_tuning_info(midi, cycles)
            h, _hm = wt_harmonics_for(L, cycles, up)
        except Exception:
            L, f_real, h, cycles = 674, 65.41, 337, 1
        Lp = int(min(L, WT_MORPH_MAX_POINTS))
        hp = max(4, min(int(h), Lp // (2 * max(1, cycles))))
        # Cached per family and per pitch setting: going back and forth
        # between two families is the normal way to compare them, and the
        # second visit should not cost another render.
        key = (family, Lp, cycles, hp, count)
        cached = getattr(self, "_morph_shape_cache", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        synth = WTSynth(Lp, cycles, hp)
        _name, fn = wt_family_entry(self._resolve(family))
        out = []
        for j in range(count):
            m = 0.5 if count == 1 else j / (count - 1)
            w, _d = fn(synth, m, f_real)
            w = synth.band_limit(np.asarray(w, dtype=np.float64))
            peak = np.max(np.abs(w))
            out.append(w / peak if peak > 1e-12 else w)
        self._morph_shape_cache = (key, out)
        return out

    def _morph_geometry(self):
        """Layout of the stack, derived from the canvas as it actually is.

        The height was previously taken from WT_MORPH_HEIGHT, the value the
        canvas *asks* for. Tk grants that only when there is room; in a
        squeezed dialog the canvas ends up shorter and the curves at the back
        were drawn above its top edge, so the stack looked like it stopped
        after a few steps. Everything is sized off winfo_height() now, and
        the arithmetic below places the topmost curve exactly on the margin,
        so all of them fit whatever height it gets.
        """
        c = self.morph_canvas
        w = max(2, c.winfo_width())
        h = max(2, c.winfo_height())
        margin = 6
        usable = h - 2 * margin
        if usable < 30 or w < 80:
            return None
        depth_x = w * 0.22
        depth_y = usable * 0.5
        amp = (usable - depth_y) / 2.0
        base_y = h - margin - amp
        return w, h, depth_x, depth_y, amp, base_y, w - depth_x - 4

    def _morph_points(self, vals, idx, shown, geo):
        w, h, depth_x, depth_y, amp, base_y, front_w = geo
        frac = idx / max(1, shown - 1)
        ox, oy = depth_x * frac, -depth_y * frac
        step = max(1, len(vals) // 220)
        pts = []
        for i in range(0, len(vals), step):
            pts += [ox + i / (len(vals) - 1) * front_w, base_y + oy - vals[i] * amp]
        return pts, ox, oy

    def _draw_morph(self):
        c = getattr(self, "morph_canvas", None)
        if c is None:
            return
        c.delete("all")
        geo = self._morph_geometry()
        if geo is None:
            self._morph_cache = None
            return  # too small to show anything meaningful
        w, h = geo[0], geo[1]
        if not self.prev_family:
            c.create_text(
                w / 2,
                h / 2,
                text="Click a family to see its morph",
                fill=FG_MUTED,
                font=(UI_FAMILY, 8),
            )
            self._morph_cache = None
            return

        total = self._preview_steps(self.prev_family)
        shown = max(2, min(WT_MORPH_SHOWN, total))
        try:
            shapes = self._morph_shapes(self.prev_family, shown)
        except Exception as e:
            c.create_text(
                w / 2, h / 2, text=f"Could not render: {e}", fill=FG_MUTED, font=(UI_FAMILY, 8)
            )
            return
        self._morph_cache = (self.prev_family, shapes, total)
        line = readable_on(WAVE_COLOR, WAVE_BG, 7.0)

        # Back to front, each shape filled with the canvas colour before it is
        # stroked: that is what makes a nearer curve hide the one behind it,
        # which is the whole reason the stack reads as depth. The fill runs
        # down to the bottom edge, not just to the curve's own baseline -
        # anything further away lives above this curve, so a short fill would
        # occlude nothing.
        for idx in range(shown - 1, -1, -1):
            pts, ox, oy = self._morph_points(shapes[idx], idx, shown, geo)
            far = idx / max(1, shown - 1)
            col = blend_colors(line, WAVE_BG, 0.62 * far)
            poly = pts + [pts[-2], h, pts[0], h]
            c.create_polygon(*poly, fill=WAVE_BG, outline="")
            c.create_line(*pts, fill=col, width=2 if idx == 0 else 1, tags=f"step{idx}")
        c.create_text(4, h - 10, text="step 1", anchor="w", fill=FG_MUTED, font=(UI_FAMILY, 7))
        c.create_text(
            w - 4, 10, text=f"step {total}", anchor="e", fill=FG_MUTED, font=(UI_FAMILY, 7)
        )
        self._highlight_morph_step(None)

    def _highlight_morph_step(self, frac):
        """Marks the step currently sounding. `frac` runs 0..1, None clears."""
        c = getattr(self, "morph_canvas", None)
        if c is None or not self._morph_cache:
            return
        c.delete("morphmark")
        if frac is None:
            return
        geo = self._morph_geometry()
        if geo is None:
            return
        _fam, shapes, _total = self._morph_cache
        shown = len(shapes)
        idx = int(min(shown - 1, max(0, round(frac * (shown - 1)))))
        # Same helper the stack uses, so the marker can never sit next to the
        # curve it is meant to be on.
        pts, _ox, _oy = self._morph_points(shapes[idx], idx, shown, geo)
        c.create_line(*pts, fill=ACCENT_ORANGE, width=2, tags="morphmark")

    PREVIEW_STEP_CAP = 64

    def _preview_steps(self, family):
        sel = self._selection()
        if family in sel:
            n = wt_split_steps(len(sel))[sel.index(family)]
        else:
            n = wt_split_steps(len(sel) + 1)[-1]
        # With an empty selection this would be all 255 segments, i.e. 255
        # additive syntheses before a single sample is heard. The morph is
        # smooth enough that 64 sounds the same.
        return min(n, self.PREVIEW_STEP_CAP)

    def _update_preview_label(self):
        if not self.prev_family:
            self.btn_prev.text = "\u25b6"
            self.btn_prev.config_state("disabled")
            self.btn_prev._draw()
            self.lbl_prev.config(text="Click a family in either column to preview it")
            return
        self.btn_prev.config_state("normal")
        if not self.prev_playing:
            self.btn_prev.text = "\u25b6"
            self.btn_prev._draw()
        n = self._preview_steps(self.prev_family)
        inlist = self.prev_family in self._selection()
        # The button no longer spells out which family is armed, so the label
        # has to.
        self.lbl_prev.config(
            text=f"{self.prev_family}   \u00b7   {WT_PREVIEW_SECONDS:.0f} s sweep "
            f"across {n} morph steps" + ("" if inlist else "   (count it would get once added)")
        )

    def _stop_preview(self):
        if self.prev_playing:
            try:
                sd.stop()
            except Exception:
                pass
            self.prev_playing = False
        self._cancel_finish_job()
        self._prev_token = getattr(self, "_prev_token", 0) + 1
        try:
            self._highlight_morph_step(None)
        except (tk.TclError, AttributeError):
            pass

    def _toggle_preview(self):
        if self.prev_playing:
            self._stop_preview()
            self._update_preview_label()
            return
        if not self.prev_family:
            return
        midi, cycles, up = self._current_pitch()
        steps = self._preview_steps(self.prev_family)
        try:
            audio = wt_render_sweep(self._resolve(self.prev_family), midi, cycles, up, steps)
            play_audio(audio, WT_SR)
        except Exception as e:
            self._status(f"Preview failed: {e}", "bad")
            return
        self.prev_playing = True
        self.btn_prev.text = "\u25a0"
        self.btn_prev._draw()
        # Wall clock rather than a frame counter: sounddevice reports no
        # position here, and the sweep has a known, fixed length. The token
        # makes a stale tick from a previous run stop by itself.
        self._prev_started = time.time()
        self._prev_token = getattr(self, "_prev_token", 0) + 1
        self._tick_morph_marker(self._prev_token)
        self._cancel_finish_job()
        # Tagged with the token as well. Switching family mid-sweep left the
        # abandoned run's finish timer alive; it fired later and ended the
        # sweep that was playing by then - marker frozen part-way, sound
        # carrying on. Cancelling is the fix, the token is the safety net for
        # a callback already queued when the cancel arrives.
        self._finish_job = self.after(
            int(WT_PREVIEW_SECONDS * 1000) + 250,
            lambda t=self._prev_token: self._preview_finished(t),
        )

    def _tick_morph_marker(self, token):
        if token != getattr(self, "_prev_token", 0) or not self.prev_playing:
            return
        elapsed = time.time() - getattr(self, "_prev_started", time.time())
        frac = min(1.0, elapsed / max(0.001, WT_PREVIEW_SECONDS))
        try:
            self._highlight_morph_step(frac)
        except tk.TclError:
            return
        if frac < 1.0:
            self.after(40, lambda: self._tick_morph_marker(token))

    def _cancel_finish_job(self):
        job = getattr(self, "_finish_job", None)
        if job:
            try:
                self.after_cancel(job)
            except (tk.TclError, ValueError):
                pass
        self._finish_job = None

    def _preview_finished(self, token=None):
        if token is not None and token != getattr(self, "_prev_token", 0):
            return  # belongs to a sweep that was replaced
        self._finish_job = None
        self.prev_playing = False
        self._prev_token = getattr(self, "_prev_token", 0) + 1
        try:
            self._highlight_morph_step(None)
        except tk.TclError:
            pass
        self._update_preview_label()

    # -- apply -------------------------------------------------------------

    def _cancel(self):
        self._stop_preview()  # also cancels the finish timer
        # A pending redraw would fire into a window that no longer exists.
        if getattr(self, "_morph_job", None):
            try:
                self.after_cancel(self._morph_job)
            except (tk.TclError, ValueError):
                pass
            self._morph_job = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

    def _apply(self):
        sel = self._active_selection()
        if not sel:
            dark_showwarning(
                "Nothing selected", "Please choose at least one waveform family.", parent=self
            )
            return
        midi, cycles, up = self._current_pitch()
        self._stop_preview()
        self.btn_apply.config_state("disabled")
        self._status("Building wavetable \u2026", "info")
        self.update_idletasks()
        try:
            pcm, rows, meta = wt_build(self._resolved_selection(), midi, cycles, up)
        except Exception as e:
            self.btn_apply.config_state("normal")
            self._status("")
            dark_showerror("Wavetable", str(e), parent=self)
            return
        self.result = {
            "config": {
                "mode": self.var_mode.get(),
                "register": self.var_reg.get(),
                "note": self.var_note.get(),
                "up": up,
                "families": list(sel),
                # Only the shapes actually used - a preset should not carry
                # drawings the table does not contain.
                "custom": [self.custom[n] for n in sel if n in self.custom],
                "save_map": bool(self.var_save_map.get()),
            },
            "pcm": pcm,
            "rows": rows,
            "meta": meta,
        }
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

"""Custom waveform drawing and loading dialog: WaveformCreatorDialog."""

import os
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
    ACCENT_ORANGE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BTN_BLUE,
    BTN_GREEN,
    BTN_PURPLE,
    BTN_RED,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
    WAVE_COLOR,
)
from pyp6.config import (
    load_last_cycle_dir,
    save_last_cycle_dir,
)
from pyp6.constants import (
    UI_FAMILY,
    WT_DRAW_POINTS,
    WT_PREVIEW_SECONDS,
    WT_SR,
)
from pyp6.log import logger
from pyp6.synth.engine import (
    WTSynth,
    midi_to_hz,
    midi_to_name,
    name_to_midi,
    wt_harmonics_for,
    wt_render_sweep,
    wt_tuning_info,
)
from pyp6.synth.waveforms import (
    apply_morph_curve,
    wt_load_cycle_file,
    wt_points_to_cycle,
)
from pyp6.theme import blend_colors, readable_on
from pyp6.ui.dialogs_common import (
    add_tooltip,
    center_toplevel_on_parent,
    dark_askyesno,
    dark_showerror,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel

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
        from pyp6.ui.dialogs.audio_preview import AudioPreviewDialog

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
            logger.exception(f"wt_load_cycle_file failed for {path!r}")
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
            logger.exception("WaveformCreatorDialog preview failed")
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

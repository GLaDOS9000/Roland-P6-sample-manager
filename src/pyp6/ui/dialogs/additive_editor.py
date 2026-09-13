"""Additive Editor dialog: 32-harmonic waveform builder.

Users adjust per-harmonic amplitude and phase sliders to construct a
single-cycle waveform.  The result is saved to the custom family library and
appears in the SynthDialog step order alongside drawn shapes and the 16
built-in families.
"""

import tkinter as tk

import numpy as np

try:
    import sounddevice as sd  # noqa: F401 – presence check only

    from pyp6.audio.playback import play_audio
except ImportError:
    sd = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


from pyp6._theme_vars import (
    ACCENT_BLUE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BTN_BLUE,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
    WAVE_COLOR,
)
from pyp6.constants import CYCLE_AUDITION_SECONDS, UI_FAMILY, WT_SR
from pyp6.log import logger
from pyp6.synth.additive import synthesize_additive
from pyp6.synth.engine import midi_to_hz, name_to_midi
from pyp6.synth.waveforms import wt_cycle_tone
from pyp6.ui.dialogs_common import (
    add_tooltip,
    center_toplevel_on_parent,
    style_label,
    style_toplevel,
)
from pyp6.ui.waveform import draw_waveform_on_canvas
from pyp6.ui.widgets import RoundedButton, RoundedPanel, RoundedScrollbar

_N = 32  # number of harmonics

_AMP_SLIDER_LEN = 130  # px length of each amplitude Scale
_PHASE_SLIDER_LEN = 90  # px length of each phase Scale
_LABEL_H = 16  # px height of the harmonic-number label below each slider


# ---------------------------------------------------------------------------
# Preset harmonic series
# ---------------------------------------------------------------------------


def _preset_amps_phases(name):
    """Return (amps, phases_deg) for a named harmonic preset.

    Parameters
    ----------
    name : str
        One of ``"Sine"``, ``"Saw"``, ``"Square"``, ``"Triangle"``, ``"Organ"``.

    Returns
    -------
    amps : list of float, length 32
    phases_deg : list of int, length 32  (degrees, 0–360)
    """
    amps = [0.0] * _N
    phases = [0] * _N

    if name == "Sine":
        amps[0] = 1.0

    elif name == "Saw":
        for k in range(1, _N + 1):
            amps[k - 1] = 1.0 / k

    elif name == "Square":
        for k in range(1, _N + 1):
            if k % 2 == 1:
                amps[k - 1] = 1.0 / k

    elif name == "Triangle":
        alt = 0
        for k in range(1, _N + 1):
            if k % 2 == 1:
                amps[k - 1] = 1.0 / (k * k)
                phases[k - 1] = alt * 180
                alt = 1 - alt

    elif name == "Organ":
        for k in (1, 2, 3, 4, 6, 8):
            if k <= _N:
                amps[k - 1] = 1.0

    return amps, phases


# ---------------------------------------------------------------------------
# Scrollable slider bank
# ---------------------------------------------------------------------------


def _build_scrollable_slider_bank(parent, bg, n, var_list, from_, to_, resolution, slider_len):
    """Build a horizontally-scrollable row of *n* vertical tk.Scale widgets.

    The canvas has a **fixed pixel height** so it never expands to fill the
    whole container width (which would make all sliders visible and suppress
    the auto-hide scrollbar).

    **Critical constructor order:** ``scroll_canvas`` is created before
    ``RoundedScrollbar`` so that ``scroll_canvas.xview`` can be passed as
    the ``command`` argument.  ``RoundedScrollbar`` stores ``command`` only
    as an instance attribute; calling ``configure(command=...)`` on it after
    construction has no effect.

    The scrollbar is then *packed before* the canvas so tkinter's pack
    manager reserves its pixel height at the bottom first.

    Parameters
    ----------
    parent : tk.Widget
        Already-created container frame.
    bg : str
        Background colour used for the canvas and inner frame.
    n : int
        Number of sliders.
    var_list : list of tk.Variable
        One variable per slider.
    from_, to_ : float
        Scale range (``from_`` is the visual top / high value).
    resolution : float
        Slider step size.
    slider_len : int
        Pixel ``length`` passed to each tk.Scale.

    Returns
    -------
    sliders : list of tk.Scale
    scrollbar : RoundedScrollbar
    """
    canvas_h = slider_len + _LABEL_H + 10

    # 1. Create the canvas FIRST so its .xview can be passed to RoundedScrollbar
    scroll_canvas = tk.Canvas(parent, bg=bg, highlightthickness=0, height=canvas_h)

    # 2. Create scrollbar with command already set
    scrollbar = RoundedScrollbar(parent, orient="horizontal", command=scroll_canvas.xview)
    scroll_canvas.configure(xscrollcommand=scrollbar.set)

    # 3. Pack scrollbar BEFORE canvas — claims space at bottom first
    scrollbar.pack(side="bottom", fill="x")
    scroll_canvas.pack(side="top", fill="x")

    # Scrollable inner frame
    inner = tk.Frame(scroll_canvas, bg=bg)
    win_id = scroll_canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_event):
        scroll_canvas.configure(
            scrollregion=(0, 0, inner.winfo_reqwidth(), inner.winfo_reqheight())
        )

    def _on_canvas_configure(event):
        # Keep embedded window height in sync with the canvas
        scroll_canvas.itemconfigure(win_id, height=event.height)

    inner.bind("<Configure>", _on_inner_configure)
    scroll_canvas.bind("<Configure>", _on_canvas_configure)

    # Shift+wheel scrolls horizontally
    def _on_shift_wheel(event):
        scroll_canvas.xview_scroll(
            int(-event.delta / 30) or (-1 if event.delta > 0 else 1), "units"
        )

    scroll_canvas.bind("<Shift-MouseWheel>", _on_shift_wheel)

    sliders = []
    for k in range(n):
        col = tk.Frame(inner, bg=bg)
        col.pack(side="left", padx=2, pady=(6, 2))

        sc = tk.Scale(
            col,
            variable=var_list[k],
            orient="vertical",
            from_=from_,
            to=to_,
            resolution=resolution,
            length=slider_len,
            showvalue=False,
            bg=BG_DARK,
            fg=FG_MUTED,
            troughcolor=BG_INPUT,
            activebackground=ACCENT_BLUE,
            highlightthickness=0,
            relief="flat",
            sliderlength=14,
        )
        sc.pack()
        sliders.append(sc)

        lbl = tk.Label(col, text=str(k + 1))
        style_label(lbl, bg=bg, fg=FG_MUTED, font=(UI_FAMILY, 7))
        lbl.pack()

    return sliders, scrollbar


# ---------------------------------------------------------------------------
# Section header helper (title + horizontal rule)
# ---------------------------------------------------------------------------


def _section_header(parent, text):
    """Pack a bold label + separator line into *parent* (a tk.Frame on BG_DARK).

    Returns the label widget so the caller can update its text for collapsible
    sections.
    """
    row = tk.Frame(parent, bg=BG_DARK)
    row.pack(fill="x", padx=10, pady=(4, 2))
    lbl = tk.Label(row, text=text)
    style_label(lbl, fg=FG_MUTED, font=(UI_FAMILY, 9, "bold"))
    lbl.pack(side="left")
    tk.Frame(row, bg=BORDER_COLOR, height=1).pack(side="left", fill="x", expand=True, padx=(8, 0))
    return lbl


# ---------------------------------------------------------------------------
# AdditiveEditorDialog
# ---------------------------------------------------------------------------


class AdditiveEditorDialog(tk.Toplevel):
    """Construct a single-cycle waveform from up to 32 harmonic partials.

    Layout (top to bottom):
    - Preview canvas with amplitude/phase axis labels
    - Harmonics section: scrollable bank of 32 amplitude sliders
    - Phase section: collapsible scrollable bank of 32 phase sliders (0°–360°)
    - Foot: Clear, Audition, Cancel, Save to Library

    Parameters
    ----------
    parent : tk.Widget
        Parent window (usually SynthDialog).
    app : P6ManagerApp
        Application instance; used to read ``_wt_last_config`` for audition
        pitch.
    entry : dict or None
        If provided, pre-loads amplitude and phase values from a previously
        saved additive library entry (for round-trip editing).
    on_apply : callable or None
        Optional callback receiving the result dict when the user clicks
        "Save to Library".

    Result dict schema (``dlg.result``)
    ------------------------------------
    ``kind``    : ``"additive"``
    ``name``    : str
    ``amps``    : list of 32 floats  (0.0–1.0)
    ``phases``  : list of 32 ints   (degrees, 0–360)
    ``a``       : list of floats    (synthesised time-domain cycle)
    ``b``       : list of floats    (identical to ``a``)
    """

    def __init__(self, parent, app, entry=None, on_apply=None):
        super().__init__(parent)
        self.app = app
        self.on_apply = on_apply
        self.result = None
        self._preview_playing = False
        self._update_job = None
        self._last_frame = np.zeros(2048)

        self.amp_vars = [tk.DoubleVar(value=0.0) for _ in range(_N)]
        self.phase_vars = [tk.DoubleVar(value=0.0) for _ in range(_N)]
        self.name_var = tk.StringVar(value="Additive")

        if entry:
            self.name_var.set(entry.get("name") or "Additive")
            for i, v in enumerate((entry.get("amps") or [])[:_N]):
                self.amp_vars[i].set(float(v))
            for i, v in enumerate((entry.get("phases") or [])[:_N]):
                self.phase_vars[i].set(float(v))

        for var in self.amp_vars + self.phase_vars:
            var.trace_add("write", lambda *_: self._schedule_update())

        self.title("Additive Editor")
        style_toplevel(self)
        self.minsize(700, 560)
        self.geometry("900x680")

        self._build()

        center_toplevel_on_parent(self, parent)
        self.transient(parent)
        self.grab_set()

        self.after(60, self._do_update)

    # ---------------------------------------------------------------------- #
    # Layout                                                                   #
    # ---------------------------------------------------------------------- #

    def _build(self):
        # HEAD: name entry + preset buttons
        head = tk.Frame(self, padx=14, pady=8, bg=BG_DARK)
        head.pack(fill="x")
        self._build_head(head)

        # PREVIEW: RoundedPanel expands to fill remaining vertical space.
        # RoundedPanel is used here with grid (its documented usage) inside a
        # container frame that is itself packed with fill=both/expand=True.
        preview_outer = tk.Frame(self, bg=BG_DARK)
        preview_outer.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        preview_outer.grid_rowconfigure(0, weight=1)
        preview_outer.grid_columnconfigure(0, weight=1)
        preview_panel = RoundedPanel(preview_outer, title="Preview")
        preview_panel.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas = tk.Canvas(preview_panel.body, bg=WAVE_BG, highlightthickness=0)
        self.preview_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.preview_canvas.bind("<Configure>", lambda _: self._redraw_preview())

        # HARMONICS: plain styled frame (fixed height, driven by slider content)
        _section_header(self, "Harmonics")
        harm_frame = tk.Frame(self, bg=BG_PANEL)
        harm_frame.pack(fill="x", padx=10, pady=(0, 6))
        self._amp_sliders, _ = _build_scrollable_slider_bank(
            harm_frame,
            BG_PANEL,
            _N,
            self.amp_vars,
            from_=1.0,
            to_=0.0,
            resolution=0.01,
            slider_len=_AMP_SLIDER_LEN,
        )

        # PHASE: collapsible styled frame
        self._lbl_phase_toggle = _section_header(self, "\u25b6 Phase")
        self._lbl_phase_toggle.config(cursor="hand2")
        self._lbl_phase_toggle.bind("<Button-1>", lambda _: self._toggle_phase())
        add_tooltip(
            self._lbl_phase_toggle,
            "Expand to adjust the phase (0°–360°) of each harmonic partial. "
            "Phase shifts are rare in practice — most presets sound best at 0°.",
        )

        self._phase_frame = tk.Frame(self, bg=BG_PANEL)
        # Not packed initially (collapsed)
        self._phase_sliders, _ = _build_scrollable_slider_bank(
            self._phase_frame,
            BG_PANEL,
            _N,
            self.phase_vars,
            from_=360.0,
            to_=0.0,
            resolution=1.0,
            slider_len=_PHASE_SLIDER_LEN,
        )

        # FOOT
        self._foot_frame = tk.Frame(self, padx=14, pady=8, bg=BG_DARK)
        self._foot_frame.pack(fill="x")
        self._build_foot(self._foot_frame)

    def _build_head(self, head):
        lbl = tk.Label(head, text="Name:")
        style_label(lbl, font=(UI_FAMILY, 9))
        lbl.pack(side="left")
        tk.Entry(
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
        ).pack(side="left", padx=(6, 18))

        preset_frame = tk.Frame(head, bg=BG_DARK)
        preset_frame.pack(side="right")
        lbl2 = tk.Label(preset_frame, text="Presets:")
        style_label(lbl2, font=(UI_FAMILY, 9))
        lbl2.pack(side="left", padx=(0, 6))
        for name in ("Sine", "Saw", "Square", "Triangle", "Organ"):
            RoundedButton(
                preset_frame,
                text=name,
                command=lambda n=name: self._load_preset(n),
                bg=BTN_BLUE,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=64,
                height=24,
                font=(UI_FAMILY, 8),
            ).pack(side="left", padx=3)

    def _build_foot(self, foot):
        RoundedButton(
            foot,
            text="Clear",
            command=self._clear,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=70,
            height=28,
            font=(UI_FAMILY, 9),
        ).pack(side="left", padx=(0, 8))
        add_tooltip(
            foot.winfo_children()[-1],
            "Reset all amplitude sliders to 0 and all phase values to 0°.",
        )

        self.btn_audition = RoundedButton(
            foot,
            text="\u25b6 Audition",
            command=self._toggle_audition,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=100,
            height=28,
            font=(UI_FAMILY, 9),
        )
        self.btn_audition.pack(side="left")
        add_tooltip(
            self.btn_audition,
            "Play the current waveform as a sustained tone at the root note "
            "configured in the Synth dialog.",
        )

        RoundedButton(
            foot,
            text="Cancel",
            command=self._cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=80,
            height=28,
            font=(UI_FAMILY, 9),
        ).pack(side="right", padx=(8, 0))

        RoundedButton(
            foot,
            text="Save to Library",
            command=self._apply,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=130,
            height=28,
            font=(UI_FAMILY, 9, "bold"),
        ).pack(side="right")

    # ---------------------------------------------------------------------- #
    # Collapsible phase section                                                #
    # ---------------------------------------------------------------------- #

    def _toggle_phase(self):
        if self._phase_frame.winfo_ismapped():
            self._phase_frame.pack_forget()
            self._lbl_phase_toggle.config(text="\u25b6 Phase", fg=FG_MUTED)
        else:
            self._phase_frame.pack(fill="x", padx=10, pady=(0, 6), before=self._foot_frame)
            self._lbl_phase_toggle.config(text="\u25bc Phase", fg=FG_TEXT)

    # ---------------------------------------------------------------------- #
    # Preset loading                                                           #
    # ---------------------------------------------------------------------- #

    def _load_preset(self, name):
        """Populate amplitude and phase controls from a named harmonic preset."""
        amps, phases = _preset_amps_phases(name)
        for i, (a, p) in enumerate(zip(amps, phases)):
            self.amp_vars[i].set(round(a, 4))
            self.phase_vars[i].set(float(p))
        self._do_update()
        self.name_var.set(name)

    # ---------------------------------------------------------------------- #
    # Clear                                                                    #
    # ---------------------------------------------------------------------- #

    def _clear(self):
        for var in self.amp_vars:
            var.set(0.0)
        for var in self.phase_vars:
            var.set(0.0)
        self._do_update()

    # ---------------------------------------------------------------------- #
    # Synthesis + preview                                                      #
    # ---------------------------------------------------------------------- #

    def _schedule_update(self):
        if self._update_job is not None:
            try:
                self.after_cancel(self._update_job)
            except tk.TclError:
                pass
        try:
            self._update_job = self.after(30, self._do_update)
        except (tk.TclError, ValueError):
            pass

    def _do_update(self):
        self._update_job = None
        amps = [v.get() for v in self.amp_vars]
        phases_rad = [v.get() * np.pi / 180.0 for v in self.phase_vars]
        try:
            self._last_frame = synthesize_additive(amps, phases_rad)
        except Exception:
            logger.exception("AdditiveEditorDialog synthesis failed")
            return
        self._redraw_preview()

    def _redraw_preview(self):
        c = self.preview_canvas
        w = max(2, c.winfo_width())
        h = max(2, c.winfo_height())
        c.delete("all")

        margin_l = 52  # Y-axis title + tick labels
        margin_b = 30  # X-axis tick labels + title
        plot_w = max(2, w - margin_l)
        plot_h = max(2, h - margin_b)
        zero_y = plot_h // 2

        # Zero line (dashed)
        c.create_line(margin_l, zero_y, w, zero_y, fill=FG_MUTED, dash=(2, 4))

        # Waveform
        if self._last_frame is not None and np.any(self._last_frame != 0):
            draw_waveform_on_canvas(
                c,
                self._last_frame,
                0.0,
                1.0,
                plot_w,
                plot_h,
                color=WAVE_COLOR,
                y_offset=0,
                clear=False,
            )
            for item in c.find_withtag("waveform"):
                c.move(item, margin_l, 0)

        _tick = {"fill": FG_MUTED, "font": (UI_FAMILY, 7)}
        _title = {"fill": FG_MUTED, "font": (UI_FAMILY, 7, "bold")}

        # Y-axis title (rotated) and ticks
        c.create_text(8, plot_h // 2, text="Amplitude", angle=90, anchor="center", **_title)
        c.create_text(margin_l - 4, 3, text="+1", anchor="ne", **_tick)
        c.create_text(margin_l - 4, zero_y, text="0", anchor="e", **_tick)
        c.create_text(margin_l - 4, plot_h - 3, text="\u22121", anchor="se", **_tick)

        # X-axis ticks and title
        c.create_text(margin_l, plot_h + 2, text="0", anchor="nw", **_tick)
        c.create_text(margin_l + plot_w // 2, plot_h + 2, text="½", anchor="n", **_tick)
        c.create_text(w - 1, plot_h + 2, text="1", anchor="ne", **_tick)
        c.create_text(margin_l + plot_w // 2, h - 2, text="Time (1 cycle)", anchor="s", **_title)

        # Axis lines
        c.create_line(margin_l, 0, margin_l, plot_h, fill=FG_MUTED)
        c.create_line(margin_l, plot_h, w, plot_h, fill=FG_MUTED)

    # ---------------------------------------------------------------------- #
    # Audition                                                                 #
    # ---------------------------------------------------------------------- #

    def _toggle_audition(self):
        if self._preview_playing:
            self._stop_audition()
            return
        try:
            cfg = getattr(self.app, "_wt_last_config", None) or {}
            try:
                hz = midi_to_hz(name_to_midi(cfg.get("note", "C2")))
            except Exception:
                hz = 65.41
            tone = wt_cycle_tone(self._last_frame, hz=hz)
            play_audio(tone.astype(np.float32), WT_SR)
        except Exception:
            logger.exception("AdditiveEditorDialog audition failed")
            return
        self._preview_playing = True
        self.btn_audition.text = "\u25a0 Stop"
        self.btn_audition._draw()
        self.after(int(CYCLE_AUDITION_SECONDS * 1000) + 100, self._stop_audition)

    def _stop_audition(self):
        if not self._preview_playing:
            return
        self._preview_playing = False
        try:
            import sounddevice as _sd

            _sd.stop()
        except Exception:
            pass
        try:
            self.btn_audition.text = "\u25b6 Audition"
            self.btn_audition._draw()
        except tk.TclError:
            pass

    # ---------------------------------------------------------------------- #
    # Result                                                                   #
    # ---------------------------------------------------------------------- #

    def _entry(self):
        return {
            "kind": "additive",
            "name": self.name_var.get().strip() or "Additive",
            "amps": [round(v.get(), 4) for v in self.amp_vars],
            "phases": [int(round(v.get())) % 360 for v in self.phase_vars],
            "a": list(self._last_frame.round(4).tolist()),
            "b": list(self._last_frame.round(4).tolist()),
        }

    def _apply(self):
        self._stop_audition()
        self.result = self._entry()
        if self.on_apply:
            self.on_apply(self.result)
        self.destroy()

    def _cancel(self):
        self._stop_audition()
        self.result = None
        self.destroy()

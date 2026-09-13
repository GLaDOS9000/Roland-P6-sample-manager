"""Additive Editor dialog: 32-harmonic waveform builder.

Users adjust per-harmonic amplitude sliders and optional phase spinboxes to
construct a single-cycle waveform.  The result is saved to the custom family
library and appears in the SynthDialog step order alongside drawn shapes and
the 16 built-in families.
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
        # Classic sawtooth: sum of 1/k harmonics
        for k in range(1, _N + 1):
            amps[k - 1] = 1.0 / k

    elif name == "Square":
        # Odd harmonics only: 1, 3, 5, ...  with 1/k amplitude
        for k in range(1, _N + 1):
            if k % 2 == 1:
                amps[k - 1] = 1.0 / k

    elif name == "Triangle":
        # Odd harmonics: 1/k² amplitude; sign alternates via phase
        # k=1 → 0°, k=3 → 180°, k=5 → 0°, ...
        alt = 0
        for k in range(1, _N + 1):
            if k % 2 == 1:
                amps[k - 1] = 1.0 / (k * k)
                phases[k - 1] = alt * 180
                alt = 1 - alt

    elif name == "Organ":
        # Hammond drawbar approximation: harmonics 1–4, 6, 8 at full draw
        for k in (1, 2, 3, 4, 6, 8):
            if k <= _N:
                amps[k - 1] = 1.0

    return amps, phases


# ---------------------------------------------------------------------------
# AdditiveEditorDialog
# ---------------------------------------------------------------------------


class AdditiveEditorDialog(tk.Toplevel):
    """Construct a single-cycle waveform from up to 32 harmonic partials.

    The dialog presents a bank of amplitude sliders (one per harmonic) and an
    optional collapsible phase section.  A live preview canvas and audition
    button let the user hear the result before saving.

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

    ``a`` and ``b`` are identical so that ``wt_drawn_family`` (which morphs
    from ``a`` to ``b``) produces a static waveform — the intended behaviour
    for a single additive keyframe.  Users who want morphing simply add two
    additive families to the Step Order, as they would with any two built-in
    families.
    """

    def __init__(self, parent, app, entry=None, on_apply=None):
        super().__init__(parent)
        self.app = app
        self.on_apply = on_apply
        self.result = None
        self._preview_playing = False
        self._update_job = None
        self._last_frame = np.zeros(2048)

        # ------------------------------------------------------------------ #
        # State: 32 amplitude DoubleVars (0.0–1.0) + 32 phase IntVars (0°–360°)
        # ------------------------------------------------------------------ #
        self.amp_vars = [tk.DoubleVar(value=0.0) for _ in range(_N)]
        self.phase_vars = [tk.IntVar(value=0) for _ in range(_N)]
        self.name_var = tk.StringVar(value="Additive")

        if entry:
            self.name_var.set(entry.get("name") or "Additive")
            for i, v in enumerate((entry.get("amps") or [])[:_N]):
                self.amp_vars[i].set(float(v))
            for i, v in enumerate((entry.get("phases") or [])[:_N]):
                self.phase_vars[i].set(int(v))

        # Attach traces — all share one debounced update path
        for var in self.amp_vars + self.phase_vars:
            var.trace_add("write", lambda *_: self._schedule_update())

        # ------------------------------------------------------------------ #
        # Window setup
        # ------------------------------------------------------------------ #
        self.title("Additive Editor")
        style_toplevel(self)
        self.minsize(900, 620)
        self.geometry("980x700")

        self._build()

        center_toplevel_on_parent(self, parent)
        self.transient(parent)
        self.grab_set()

        # Initial render after layout is settled
        self.after(60, self._do_update)

    # ---------------------------------------------------------------------- #
    # Layout                                                                   #
    # ---------------------------------------------------------------------- #

    def _build(self):
        # HEAD: name entry + preset buttons
        head = tk.Frame(self, padx=14, pady=10, bg=BG_DARK)
        head.pack(fill="x")
        self._build_head(head)

        # BODY: sliders (left) + preview (right)
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        body.grid_columnconfigure(0, weight=6)
        body.grid_columnconfigure(1, weight=4)
        body.grid_rowconfigure(0, weight=1)

        self._build_slider_panel(body)
        self._build_preview_panel(body)

        # PHASE SECTION: collapsible
        self._build_phase_section()

        # FOOT: action buttons
        foot = tk.Frame(self, padx=14, pady=10, bg=BG_DARK)
        foot.pack(fill="x")
        self._build_foot(foot)

    def _build_head(self, head):
        # Name entry
        lbl = tk.Label(head, text="Name:")
        style_label(lbl, font=(UI_FAMILY, 9))
        lbl.pack(side="left")
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

        # Preset buttons (right-aligned)
        preset_frame = tk.Frame(head, bg=BG_DARK)
        preset_frame.pack(side="right")
        preset_lbl = tk.Label(preset_frame, text="Presets:")
        style_label(preset_lbl, font=(UI_FAMILY, 9))
        preset_lbl.pack(side="left", padx=(0, 6))
        for name in ("Sine", "Saw", "Square", "Triangle", "Organ"):
            btn = RoundedButton(
                preset_frame,
                text=name,
                command=lambda n=name: self._load_preset(n),
                bg=BTN_BLUE,
                fg="#FFFFFF",
                parent_bg=BG_DARK,
                width=64,
                height=24,
                font=(UI_FAMILY, 8),
            )
            btn.pack(side="left", padx=3)

    def _build_slider_panel(self, body):
        panel = RoundedPanel(body, title="Harmonics")
        panel.grid(row=0, column=0, sticky="nsew", padx=(0, 5))

        # Scrollable container for the 32 sliders
        scroll_host = tk.Frame(panel.body, bg=BG_PANEL)
        scroll_host.pack(fill="both", expand=True, padx=6, pady=6)

        self._slider_canvas = tk.Canvas(scroll_host, bg=BG_PANEL, highlightthickness=0)
        self._slider_canvas.pack(side="left", fill="both", expand=True)

        self._slider_scrollbar = RoundedScrollbar(
            scroll_host, orient="horizontal", command=self._slider_canvas.xview
        )
        self._slider_scrollbar.pack(side="bottom", fill="x")
        self._slider_canvas.configure(xscrollcommand=self._slider_scrollbar.set)

        inner = tk.Frame(self._slider_canvas, bg=BG_PANEL)
        self._slider_canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda e: self._slider_canvas.configure(scrollregion=self._slider_canvas.bbox("all")),
        )

        self._sliders = []
        for k in range(_N):
            col_frame = tk.Frame(inner, bg=BG_PANEL)
            col_frame.pack(side="left", padx=2, pady=(6, 2))

            sc = tk.Scale(
                col_frame,
                variable=self.amp_vars[k],
                orient="vertical",
                from_=1.0,
                to=0.0,
                resolution=0.01,
                length=150,
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
            self._sliders.append(sc)

            lbl = tk.Label(col_frame, text=str(k + 1))
            style_label(lbl, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 7))
            lbl.pack()

    def _build_preview_panel(self, body):
        panel = RoundedPanel(body, title="Preview")
        panel.grid(row=0, column=1, sticky="nsew")

        self.preview_canvas = tk.Canvas(
            panel.body,
            bg=WAVE_BG,
            highlightthickness=0,
        )
        self.preview_canvas.pack(fill="both", expand=True, padx=6, pady=6)
        self.preview_canvas.bind("<Configure>", lambda _: self._redraw_preview())

    def _build_phase_section(self):
        # Collapsible header
        phase_header = tk.Frame(self, bg=BG_DARK, padx=10)
        phase_header.pack(fill="x", pady=(2, 0))

        self._lbl_phase_toggle = tk.Label(
            phase_header,
            text="\u25b6 Phase",
            cursor="hand2",
            font=(UI_FAMILY, 9, "bold"),
            fg=FG_MUTED,
        )
        style_label(self._lbl_phase_toggle, fg=FG_MUTED, font=(UI_FAMILY, 9, "bold"))
        self._lbl_phase_toggle.config(cursor="hand2")
        self._lbl_phase_toggle.pack(side="left")
        self._lbl_phase_toggle.bind("<Button-1>", lambda _: self._toggle_phase())
        add_tooltip(
            self._lbl_phase_toggle,
            "Expand to adjust the phase (in degrees) of each harmonic partial. "
            "Phase shifts are rare in practice — most presets sound best at 0°.",
        )
        tk.Frame(phase_header, bg=BORDER_COLOR, height=1).pack(
            side="left", fill="x", expand=True, padx=(8, 0)
        )

        # Body (collapsed by default)
        self._phase_body = tk.Frame(self, bg=BG_DARK, padx=14, pady=6)
        # Not packed initially — toggled on demand

        self._phase_spinboxes = []
        COLS = 8
        for k in range(_N):
            row, col = divmod(k, COLS)
            cell = tk.Frame(self._phase_body, bg=BG_DARK)
            cell.grid(row=row * 2, column=col, padx=4, pady=(2, 0))

            lbl = tk.Label(cell, text=f"k={k + 1}")
            style_label(lbl, bg=BG_DARK, fg=FG_MUTED, font=(UI_FAMILY, 7))
            lbl.pack()

            cell2 = tk.Frame(self._phase_body, bg=BG_DARK)
            cell2.grid(row=row * 2 + 1, column=col, padx=4, pady=(0, 4))

            sb = tk.Spinbox(
                cell2,
                from_=0,
                to=355,
                increment=5,
                textvariable=self.phase_vars[k],
                width=4,
                bg=BG_INPUT,
                fg=FG_TEXT,
                buttonbackground=BG_INPUT,
                insertbackground=FG_TEXT,
                relief="flat",
                highlightthickness=1,
                highlightbackground=BORDER_COLOR,
                font=(UI_FAMILY, 8),
            )
            sb.pack()
            self._phase_spinboxes.append(sb)

    def _build_foot(self, foot):
        # Left side: Clear
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

        # Audition button
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

        # Right side: Cancel + Save
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
        if self._phase_body.winfo_ismapped():
            self._phase_body.pack_forget()
            self._lbl_phase_toggle.config(text="\u25b6 Phase", fg=FG_MUTED)
        else:
            self._phase_body.pack(fill="x", before=self._foot_anchor())
            self._lbl_phase_toggle.config(text="\u25bc Phase", fg=FG_TEXT)

    def _foot_anchor(self):
        """Return the foot frame so the phase body packs before it."""
        # The foot is the last child packed — walk children to find it
        children = self.pack_slaves()
        return children[-1] if children else None

    # ---------------------------------------------------------------------- #
    # Preset loading                                                           #
    # ---------------------------------------------------------------------- #

    def _load_preset(self, name):
        """Populate amplitude and phase controls from a named harmonic preset.

        Parameters
        ----------
        name : str
            Preset name — one of ``"Sine"``, ``"Saw"``, ``"Square"``,
            ``"Triangle"``, ``"Organ"``.
        """
        amps, phases = _preset_amps_phases(name)
        # Suspend traces to avoid 64 individual redraws; do one at the end
        for i, (a, p) in enumerate(zip(amps, phases)):
            self.amp_vars[i].set(round(a, 4))
            self.phase_vars[i].set(p)
        self._do_update()
        self.name_var.set(name)

    # ---------------------------------------------------------------------- #
    # Clear                                                                    #
    # ---------------------------------------------------------------------- #

    def _clear(self):
        for var in self.amp_vars:
            var.set(0.0)
        for var in self.phase_vars:
            var.set(0)
        self._do_update()

    # ---------------------------------------------------------------------- #
    # Synthesis + preview                                                      #
    # ---------------------------------------------------------------------- #

    def _schedule_update(self):
        """Debounce: coalesce rapid slider events into a single synthesis call."""
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
        """Synthesise the current harmonic state and refresh the preview."""
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
        if self._last_frame is not None and np.any(self._last_frame != 0):
            draw_waveform_on_canvas(
                c,
                self._last_frame,
                0.0,
                1.0,
                w,
                h,
                color=WAVE_COLOR,
            )

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
                hz = 65.41  # C2
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
        """Build and return the result dict representing the current state."""
        return {
            "kind": "additive",
            "name": self.name_var.get().strip() or "Additive",
            "amps": [round(v.get(), 4) for v in self.amp_vars],
            "phases": [v.get() for v in self.phase_vars],
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

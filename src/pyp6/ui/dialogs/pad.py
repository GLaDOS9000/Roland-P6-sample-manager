"""Pad waveform editor dialog: PadWaveformViewDialog."""

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


try:
    import soundfile as sf
except ImportError:
    sf = None

from pyp6._theme_vars import (
    ACCENT_ORANGE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BTN_BLUE,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
)
from pyp6.audio.info import compute_truncate_fraction
from pyp6.audio.processing import (
    apply_fade_envelope,
    apply_fade_to_wav_file,
    apply_micro_fade,
    normalize_wav_file,
    trim_wav_file,
)
from pyp6.config import format_duration
from pyp6.constants import MAIN_MIN_W, UI_FAMILY, ZOOM_BAR_RESERVE
from pyp6.log import logger
from pyp6.ui.dialogs_common import (
    add_tooltip,
    center_toplevel_on_parent,
    dark_showerror,
    dark_showinfo,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.waveform import draw_truncate_overlay
from pyp6.ui.waveform_canvas_mixin import WaveformCanvasMixin
from pyp6.ui.widgets import RoundedButton, RoundedPanel, RoundedScrollbar


class PadWaveformViewDialog(WaveformCanvasMixin, tk.Toplevel):
    """Post-hoc editing view for a pad's already-loaded sample: trim
    markers + zoom, the same interaction as the Load dialog's waveform
    pane, plus Normalize. "Apply to Pad" writes the edited result back
    onto the exact pad this was opened from (with undo), rather than
    "Select"-ing it somewhere else the way the Load dialog does."""

    def __init__(self, parent, app, pad_num, filepath, display_name):
        super().__init__(parent)
        self.app = app
        self.pad_num = pad_num
        self.filepath = filepath
        self.base_display_name = display_name
        # Chop-built multisamples have precise, fixed slice boundaries that
        # the P-6 relies on - trimming or fading them can shift/clip a slice
        # boundary and cause playback problems on the actual hardware, even
        # though it looks fine in this editor. Detected via the filename
        # prefix our own Chop export always uses (chop_<slices>slices_...).
        self.is_chop_sample = os.path.basename(filepath).lower().startswith("chop_")
        self.title(display_name)
        self.geometry(f"{MAIN_MIN_W}x570")
        # + ZOOM_BAR_RESERVE: the horizontal scrollbar only appears once the
        # user zooms in, and there is no list here to take its height from.
        self.minsize(700, 470 + 2 * 32 + ZOOM_BAR_RESERVE)
        style_toplevel(self)

        self.trim_start_frac = 0.0
        self.trim_end_frac = 1.0
        self.drag_target = None
        self.is_playing = False
        self.play_start_time = None
        self.play_duration = 0.0
        self._wave_data = None
        self._wave_data_stereo = None
        self._wave_fs = None
        self.zoom_factor = 1.0
        self.view_start_frac = 0.0
        self.view_span_frac = 1.0
        self.center_frac = 0.5
        self.wave_width = 800
        self.wave_height = 300

        header = tk.Frame(self, padx=16, pady=12, bg=BG_DARK)
        header.pack(fill="x")
        name_label = tk.Label(header, text=display_name, anchor="w")
        style_label(name_label, font=(UI_FAMILY, 11, "bold"))
        name_label.pack(side="left")
        self.info_label = tk.Label(header, text="", anchor="e")
        style_label(self.info_label, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self.info_label.pack(side="right")

        # Logarithmic fade-time steps (fast at the short end, where the ear
        # is most sensitive to small changes; coarser toward 1s) rather than
        # fixed linear increments.
        self.FADE_STEPS = [0.0, 0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5, 0.7, 1.0]
        self.fade_in_seconds = 0.0
        self.fade_out_seconds = 0.0
        edit_panel = RoundedPanel(
            self,
            title="Edit",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        edit_panel.pack(fill="x", padx=16, pady=(0, 4))
        controls_row = tk.Frame(edit_panel.body, bg=BG_PANEL)
        controls_row.pack(fill="x")

        # Zoom pinned to the right - packed first so it claims its space
        # on that side regardless of how wide the left-hand group grows.
        zoom_row = tk.Frame(controls_row, bg=BG_PANEL)
        zoom_row.pack(side="right")
        zoom_out_btn = RoundedButton(
            zoom_row,
            text="\u2212",
            command=self.zoom_out,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        zoom_out_btn.pack(side="left", padx=1)
        self.zoom_label = tk.Label(zoom_row, text="1.0x")
        style_label(self.zoom_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        self.zoom_label.pack(side="left", padx=4)
        zoom_in_btn = RoundedButton(
            zoom_row,
            text="+",
            command=self.zoom_in,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        zoom_in_btn.pack(side="left", padx=1)
        zoom_reset_btn = RoundedButton(
            zoom_row,
            text="Reset",
            command=self.zoom_reset,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=55,
            height=22,
            font=(UI_FAMILY, 8, "bold"),
        )
        zoom_reset_btn.pack(side="left", padx=(6, 0))

        # Normalize + Fade on the left - "shape the level/edges of the
        # selection" controls, grouped together and read as one unit.
        self.normalize_var = tk.BooleanVar(value=False)
        normalize_cb = tk.Checkbutton(
            controls_row,
            text="Normalize",
            variable=self.normalize_var,
            command=self._render_wave_at_current_view,
        )
        style_checkbutton(normalize_cb)
        normalize_cb.pack(side="left")
        add_tooltip(
            normalize_cb,
            "Lifts the sample to its maximum level without clipping. Shown live "
            'in the waveform, written on "Apply to Pad".',
        )

        fade_in_lbl = tk.Label(controls_row, text="Fade In:")
        style_label(fade_in_lbl, font=(UI_FAMILY, 9))
        fade_in_lbl.pack(side="left", padx=(20, 0))
        self.fade_in_minus = RoundedButton(
            controls_row,
            text="\u2212",
            command=lambda: self._adjust_fade("in", -1),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.fade_in_minus.pack(side="left", padx=(6, 1))
        self.fade_in_label = tk.Label(controls_row, text="0.00s", width=6)
        style_label(self.fade_in_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        self.fade_in_label.pack(side="left", padx=4)
        self.fade_in_plus = RoundedButton(
            controls_row,
            text="+",
            command=lambda: self._adjust_fade("in", 1),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.fade_in_plus.pack(side="left", padx=1)

        fade_out_lbl = tk.Label(controls_row, text="Fade Out:")
        style_label(fade_out_lbl, font=(UI_FAMILY, 9))
        fade_out_lbl.pack(side="left", padx=(20, 0))
        self.fade_out_minus = RoundedButton(
            controls_row,
            text="\u2212",
            command=lambda: self._adjust_fade("out", -1),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.fade_out_minus.pack(side="left", padx=(6, 1))
        self.fade_out_label = tk.Label(controls_row, text="0.00s", width=6)
        style_label(self.fade_out_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        self.fade_out_label.pack(side="left", padx=4)
        self.fade_out_plus = RoundedButton(
            controls_row,
            text="+",
            command=lambda: self._adjust_fade("out", 1),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=28,
            height=22,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.fade_out_plus.pack(side="left", padx=1)

        if self.is_chop_sample:
            fade_help = (
                "Disabled for chop multisamples: a fade would shift the fixed "
                "slice boundaries the P-6 relies on."
            )
        else:
            fade_help = (
                "Fades the marked region in/out, 0 to 1.0 s in logarithmic "
                "steps. Useful against clicks at the start or end."
            )
        for _fade_btn in (
            self.fade_in_minus,
            self.fade_in_plus,
            self.fade_out_minus,
            self.fade_out_plus,
        ):
            add_tooltip(_fade_btn, fade_help)

        wave_panel = RoundedPanel(
            self,
            title="Waveform / Trim",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        wave_panel.pack(fill="both", expand=True, padx=16)

        duration_row = tk.Frame(wave_panel.body, bg=BG_PANEL)
        duration_row.pack(fill="x")
        if self.is_chop_sample:
            chop_hint = tk.Label(
                duration_row,
                text="Chop sample: trim and fade are disabled (would risk breaking slice "
                "playback on the P-6). Normalize is still available.",
                anchor="w",
            )
            style_label(chop_hint, fg=ACCENT_ORANGE, font=(UI_FAMILY, 8))
            chop_hint.pack(side="left")
            self.fade_in_minus.config_state("disabled")
            self.fade_in_plus.config_state("disabled")
            self.fade_out_minus.config_state("disabled")
            self.fade_out_plus.config_state("disabled")
        self.duration_label = tk.Label(duration_row, text="", anchor="e")
        style_label(self.duration_label, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.duration_label.pack(side="right")

        wave_frame = tk.Frame(wave_panel.body, bg=BG_PANEL)
        wave_frame.pack(fill="both", expand=True)
        self.wave_canvas = tk.Canvas(
            wave_frame, bg=WAVE_BG, highlightthickness=0, bd=0, cursor="sb_h_double_arrow"
        )
        self.wave_canvas.pack(fill="both", expand=True, pady=(8, 2))
        if self.is_chop_sample:
            add_tooltip(
                self.wave_canvas,
                "Chop multisample: the trim markers are disabled so the slice "
                "boundaries stay intact.",
            )
        else:
            add_tooltip(
                self.wave_canvas,
                "Drag the green (start) and red (end) markers to shorten the "
                "sample. An orange area marks what the P-6 would cut off at the "
                "current rate and pitch.",
            )
        self.wave_canvas.bind("<Configure>", self._on_wave_canvas_resize)
        self.wave_canvas.bind("<ButtonPress-1>", self.on_wave_press)
        self.wave_canvas.bind("<B1-Motion>", self.on_wave_drag)
        self.wave_canvas.bind("<ButtonRelease-1>", self.on_wave_release)
        self.wave_canvas.bind("<MouseWheel>", self.on_wave_mousewheel)
        self.wave_canvas.bind("<Button-4>", self.on_wave_mousewheel)
        self.wave_canvas.bind("<Button-5>", self.on_wave_mousewheel)
        self.wave_scrollbar = RoundedScrollbar(
            wave_frame,
            orient="horizontal",
            command=self.on_wave_scroll,
            parent_bg=BG_PANEL,
            auto_hide=False,
        )
        # Holds the scrollbar's height while it is hidden, so showing it
        # later costs nothing and cannot push the button row out of the
        # window. Same height and padding as the scrollbar itself.
        self._zoom_spacer = tk.Frame(wave_frame, bg=BG_PANEL, height=RoundedScrollbar.THICKNESS)
        self._zoom_spacer.pack_propagate(False)
        # Packed straight away: the window sizes itself from its contents when
        # it opens, so the space has to be accounted for from the start.
        self._zoom_spacer.pack(fill="x", pady=(0, 4))
        # Not packed here on purpose - only shown once zoomed in. Placement is
        # managed by hand below, not by the scrollbar's own auto-hide.

        btn_row = tk.Frame(self, padx=16, pady=12, bg=BG_DARK)
        btn_row.pack(fill="x")
        self.play_btn = RoundedButton(
            btn_row,
            text="\u25b6 Preview",
            command=self.toggle_play,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=110,
        )
        self.play_btn.pack(side="left")
        add_tooltip(
            self.play_btn, "Plays the marked region with the current edits.\nShortcut: Space"
        )
        close_btn = RoundedButton(
            btn_row,
            text="Close",
            command=self.on_close,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        close_btn.pack(side="right")
        add_tooltip(close_btn, "Closes the editor. Unapplied changes are discarded.")
        apply_btn = RoundedButton(
            btn_row,
            text="Apply to Pad",
            command=self.apply_changes,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=130,
        )
        apply_btn.pack(side="right", padx=(0, 8))
        add_tooltip(
            apply_btn,
            "Writes trim, normalize and fade to a new file in the temp folder and "
            "puts it back on this pad. The original file stays untouched; "
            "Ctrl+Z undoes it.",
        )

        self.bind("<space>", lambda e: self.toggle_play())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self._load_wave_data()
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

    def _load_wave_data(self):
        try:
            data, fs = sf.read(self.filepath, dtype="float32")
            self._wave_fs = fs
            rate, force_mono, pitch_cents = self._get_pad_settings()
            # Follow the pad's mono setting, not just the file's channel
            # count. The main window's mini waveform already collapses a
            # stereo file to a single trace when Mono (or the bank's Force
            # Mono) is on; the editor showed two stacked channels for the
            # same pad, which looked like the two views disagreed about the
            # sample. What gets exported is mono, so that's what's drawn.
            if data.ndim > 1 and data.shape[1] >= 2 and not force_mono:
                self._wave_data_stereo = data
                self._wave_data = data.mean(axis=1)
            else:
                if data.ndim > 1:
                    self._wave_data = data.mean(axis=1) if data.shape[1] >= 2 else data.flatten()
                else:
                    self._wave_data = data
                self._wave_data_stereo = None
            self.play_duration = len(self._wave_data) / fs if fs else 0
            # The file's own rate AND the pad's export settings. Showing only
            # "44100 Hz" here read as if the editor ignored the pad's rate
            # dropdown, when in fact the orange length-limit overlay is
            # computed from exactly those pad settings, not from the file.
            channel_word = "mono" if force_mono else "as-is"
            pitch_note = f", {pitch_cents:+d}c" if pitch_cents else ""
            self.info_label.config(
                text=f"{format_duration(self.play_duration)}  \u2022  file {fs} Hz  "
                f"\u2022  pad export: {rate} Hz, {channel_word}{pitch_note}"
            )
            self.render_and_draw_wave()
        except Exception as e:
            # Whatever fails here, it must not prevent __init__ from
            # reaching transient()/center_toplevel_on_parent()/_safe_grab()
            # below - otherwise the window is created but never properly
            # positioned/shown, which looks like an empty black rectangle.
            logger.exception(f"PadWaveformViewDialog init failed for {self.filepath!r}")
            dark_showerror("Could Not Load Sample", str(e), parent=self)

    # ------------------------------------------------------------------ hooks

    def _trim_is_locked(self):
        return self.is_chop_sample

    def _before_redraw_markers(self):
        self._redraw_length_limit_overlay()

    def _on_playhead_done(self):
        self.play_btn.text = "\u25b6 Preview"
        self.play_btn._draw()

    def _display_data_with_edits(self, data):
        """Returns a copy of the FULL (untrimmed) waveform data with
        normalize + fade-in/fade-out applied only within the trim region -
        in the same order apply_changes() actually writes them (normalize
        first, then fade, so fading down the edges doesn't distort what
        normalize would have used as the peak). Everything outside the
        trim markers (already shown dimmed) stays untouched."""
        if data is None or self._wave_fs is None:
            return data
        normalize = self.normalize_var.get()
        has_fade = self.fade_in_seconds > 0 or self.fade_out_seconds > 0
        if not normalize and not has_fade:
            return data
        n = len(data)
        start_i = int(self.trim_start_frac * n)
        end_i = int(self.trim_end_frac * n)
        region = data[start_i:end_i]
        if len(region) == 0:
            return data
        if normalize:
            peak = float(np.max(np.abs(region))) if region.size else 0.0
            if peak > 0:
                region = region * (0.98 / peak)
        if has_fade:
            region = apply_fade_envelope(
                region, self._wave_fs, self.fade_in_seconds, self.fade_out_seconds
            )
        result = data.copy()
        result[start_i:end_i] = region
        return result

    def _get_pad_settings(self):
        """(rate, force_mono, pitch_cents) currently configured for the pad
        this sample lives on - used to compute the same export duration
        limit the app would actually enforce."""
        slot = self.app.pad_widgets.get(self.pad_num) if hasattr(self.app, "pad_widgets") else None
        if slot is None:
            return 44100, False, 0
        return slot.target_rate.get(), slot.effective_mono(), slot.pitch_cents.get()

    def _redraw_length_limit_overlay(self):
        """Shades the portion of the waveform that would exceed the P-6's
        length limit for this pad's current rate/mono/pitch settings -
        same visual language as the main window's truncation overlay, so
        it's clear at a glance how much needs to be trimmed to fit."""
        self.wave_canvas.delete("lenlimit")
        if not self.play_duration:
            return
        rate, force_mono, pitch_cents = self._get_pad_settings()
        limit_frac = compute_truncate_fraction(self.filepath, rate, pitch_cents, force_mono)
        if limit_frac is None:
            return
        x_cut = self.frac_to_x(limit_frac)
        if x_cut < 0 or x_cut > self.wave_width:
            return  # the cut point is outside the currently zoomed-in view
        draw_truncate_overlay(
            self.wave_canvas, x_cut, self.wave_width, self.wave_height, tag="lenlimit"
        )

    def _adjust_fade(self, which, direction):
        """Moves one step along FADE_STEPS (logarithmic: fine-grained near
        0.01s, coarser toward 1s) rather than a fixed linear increment."""
        current = self.fade_in_seconds if which == "in" else self.fade_out_seconds
        idx = min(range(len(self.FADE_STEPS)), key=lambda i: abs(self.FADE_STEPS[i] - current))
        idx = max(0, min(idx + direction, len(self.FADE_STEPS) - 1))
        new_value = self.FADE_STEPS[idx]
        if which == "in":
            self.fade_in_seconds = new_value
            self.fade_in_label.config(text=f"{new_value:.2f}s")
        else:
            self.fade_out_seconds = new_value
            self.fade_out_label.config(text=f"{new_value:.2f}s")
        self._render_wave_at_current_view()

    def toggle_play(self):
        if self.is_playing:
            self.stop_play()
            return
        if self._wave_data is None:
            return
        try:
            sd.stop()
            data, fs = sf.read(self.filepath, dtype="float32")
            n = len(data)
            start_i = int(self.trim_start_frac * n)
            end_i = int(self.trim_end_frac * n)
            segment = data[start_i:end_i]
            self._audible_seconds = None
            segment = apply_micro_fade(segment, fs, fade_ms=2)
            if self.normalize_var.get():
                peak = float(np.max(np.abs(segment))) if segment.size else 0.0
                if peak > 0:
                    segment = segment * (0.98 / peak)
            segment = apply_fade_envelope(segment, fs, self.fade_in_seconds, self.fade_out_seconds)
            play_audio(segment, fs)
            self.is_playing = True
            self.play_btn.text = "\u25a0 Stop"
            self.play_btn._draw()
            self.play_start_time = time.time()
            self.update_playhead()
        except Exception as e:
            logger.exception("PadWaveformViewDialog playback failed")
            dark_showerror("Playback Error", str(e), parent=self)

    def stop_play(self):
        try:
            sd.stop()
        except Exception:
            pass
        self.is_playing = False
        if hasattr(self, "play_btn"):
            self.play_btn.text = "\u25b6 Preview"
            self.play_btn._draw()
        if hasattr(self, "wave_canvas"):
            self.wave_canvas.delete("playhead")

    def apply_changes(self):
        trimmed = self.trim_start_frac > 0.001 or self.trim_end_frac < 0.999
        normalize = self.normalize_var.get()
        has_fade = self.fade_in_seconds > 0.0 or self.fade_out_seconds > 0.0
        if self.is_chop_sample:
            # Defense in depth - the UI already blocks marker dragging and
            # disables the fade buttons, but this makes sure neither can
            # ever be applied to a chop sample regardless of how trim_*_frac
            # or fade_*_seconds ended up set.
            trimmed = False
            has_fade = False
        if not trimmed and not normalize and not has_fade:
            dark_showinfo(
                "Nothing to Apply", "No trim, fade or normalize changes were made.", parent=self
            )
            return
        try:
            result_path = self.filepath
            if trimmed:
                result_path = trim_wav_file(result_path, self.trim_start_frac, self.trim_end_frac)
            if normalize:
                result_path = normalize_wav_file(result_path)
            if has_fade:
                result_path = apply_fade_to_wav_file(
                    result_path, self.fade_in_seconds, self.fade_out_seconds
                )
        except Exception as e:
            logger.exception(f"PadWaveformViewDialog apply_changes failed for {self.filepath!r}")
            dark_showerror("Edit Error", str(e), parent=self)
            return

        suffix = ""
        if trimmed:
            suffix += " (trim)"
        if normalize:
            suffix += " (normalized)"
        if has_fade:
            suffix += " (fade)"
        new_display_name = f"{self.base_display_name}{suffix}"

        slot = self.app.pad_widgets.get(self.pad_num)
        if slot is not None and getattr(slot, "wavetable", None):
            # Belt and braces: open_waveform_view already blocks this, but
            # keep_settings=True below would leave the wavetable flag intact
            # on top of trimmed audio, and the exported .PRM would then state
            # a SIZE the file no longer has.
            dark_showerror(
                "Wavetable",
                "This pad holds a generated wavetable and cannot be "
                "edited here. Use Synth to rebuild it.",
            )
            self.stop_play()
            self.destroy()
            return
        if slot is not None:
            self.app._push_undo()
            # keep_settings: this replaces the pad's sample with an edited
            # version of itself, so the rate/pitch/mono chosen for this pad
            # must survive. Editing used to silently reset all three.
            slot.set_file(result_path, display_name=new_display_name, keep_settings=True)
            self.app.update_storage_display()
            self.app.update_pad_warnings()
            self.app.show_status(f"PAD_{self.pad_num} updated.")
        self.stop_play()
        self.destroy()

    def on_close(self):
        self.stop_play()
        self.destroy()

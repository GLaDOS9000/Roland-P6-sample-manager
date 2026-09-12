"""Reusable mixin for interactive waveform canvas widgets.

WaveformCanvasMixin provides the zoom/pan/trim-marker/playhead interaction
logic shared by AudioPreviewDialog and PadWaveformViewDialog.  Each of those
classes had an identical copy of ~220 lines of canvas code; this mixin is the
single source of truth.

Usage
-----
Inherit from WaveformCanvasMixin *before* tk.Toplevel so that the MRO gives
the mixin methods priority over any accidental Tk collision:

    class MyDialog(WaveformCanvasMixin, tk.Toplevel):
        ...

Required instance attributes (set in __init__ before calling canvas methods):
    wave_canvas       tk.Canvas  — the waveform canvas
    wave_scrollbar    RoundedScrollbar — horizontal scrollbar (starts unmapped)
    _zoom_spacer      tk.Frame   — placeholder that reserves scrollbar height
    _wave_data        np.ndarray | None — mono audio samples
    _wave_data_stereo np.ndarray | None — (N, C) stereo samples, or None
    wave_width        int        — logical drawing width (kept in sync with canvas)
    wave_height       int        — logical drawing height
    zoom_factor       float      — current zoom level (1.0 = full view)
    view_start_frac   float      — left edge of the zoomed view [0, 1)
    view_span_frac    float      — width of the zoomed view as a fraction of 1
    center_frac       float      — target center after zoom recenter
    trim_start_frac   float      — start marker position [0, 1]
    trim_end_frac     float      — end marker position [0, 1]
    drag_target       str | None — "start", "end", or None while dragging
    is_playing        bool       — True while the playhead animation runs
    play_start_time   float      — time.time() at playback start
    play_duration     float      — total clip duration in seconds

Required methods (implemented by the concrete subclass):
    _display_data_with_edits(data) → np.ndarray
        Returns the waveform data with any live preview edits (normalize,
        fade…) baked in for display only.
    update_duration_label()
        Refreshes the duration / selection-length label in the UI.

Override hooks (all have do-nothing defaults):
    _trim_is_locked() → bool
        Return True to prevent the user from dragging trim markers and to
        skip drawing them in redraw_markers().  AudioPreviewDialog returns
        bool(self.cycle_hz); PadWaveformViewDialog returns self.is_chop_sample.
    _before_redraw_markers()
        Called inside _render_wave_at_current_view() just before
        redraw_markers(), so subclasses can draw overlays beneath the
        markers.  PadWaveformViewDialog uses this for the length-limit overlay.
    _on_playhead_done()
        Called when the playhead animation ends (playback finished).  Subclasses
        use this to reset the play-button label.
"""

import time

from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_RED,
    BG_DARK,
    BORDER_COLOR,
    FG_MUTED,
)
from pyp6.ui.waveform import (
    draw_bracket_marker,
    draw_waveform_on_canvas,
    max_zoom_for,
    min_trim_fraction,
)


class WaveformCanvasMixin:
    """Zoom / pan / trim-marker / playhead logic for an interactive waveform canvas.

    See module docstring for the full contract.
    """

    # ------------------------------------------------------------------ hooks

    def _trim_is_locked(self):
        """Return True to suppress trim-marker interaction and rendering."""
        return False

    def _before_redraw_markers(self):
        """Hook called just before redraw_markers() in _render_wave_at_current_view.

        Override to draw canvas overlays that should appear *beneath* the
        trim markers (e.g. a length-limit shade region).
        """

    def _on_playhead_done(self):
        """Hook called when the playhead animation ends.

        Override to reset the play/preview button back to its idle label.
        """

    # --------------------------------------------------------- view math

    def _update_view_window(self):
        self.zoom_factor = max(1.0, self.zoom_factor)
        self.view_span_frac = 1.0 / self.zoom_factor
        start = self.center_frac - self.view_span_frac / 2.0
        start = max(0.0, min(start, 1.0 - self.view_span_frac))
        self.view_start_frac = start

    def frac_to_x(self, frac):
        if self.view_span_frac <= 0:
            return 0
        return (frac - self.view_start_frac) / self.view_span_frac * self.wave_width

    def x_to_frac(self, x):
        return self.view_start_frac + (x / self.wave_width) * self.view_span_frac

    # --------------------------------------------------------- render

    def render_and_draw_wave(self):
        """Re-center the view on the current markers, then render.

        Use this after zoom changes or a marker drag that should recenter
        the view.  For plain scrollbar/mousewheel panning use
        _render_wave_at_current_view() directly.
        """
        self._update_view_window()
        self._render_wave_at_current_view()

    def _on_wave_canvas_resize(self, event=None):
        """Keep wave_width/wave_height in sync with the canvas's actual size.

        The canvas is packed to fill available space and can end up a
        different size than the fixed wave_width/wave_height used for
        drawing/marker/zoom math — keep them in sync so the waveform scales
        with the window instead of leaving empty space or getting clipped.
        """
        new_width = event.width if event else self.wave_canvas.winfo_width()
        new_height = event.height if event else self.wave_canvas.winfo_height()
        changed = False
        if new_width > 10 and new_width != self.wave_width:
            self.wave_width = new_width
            changed = True
        if new_height > 10 and new_height != self.wave_height:
            self.wave_height = new_height
            changed = True
        if changed and self._wave_data is not None:
            self._render_wave_at_current_view()

    def _render_wave_at_current_view(self):
        """Render at the current view_start_frac/view_span_frac without recentering.

        This is the low-level render used by scrollbar and mousewheel panning
        where the view position was already updated before calling here.
        """
        if hasattr(self, "zoom_label"):
            self.zoom_label.config(text=f"{self.zoom_factor:.1f}x")
        self._update_scrollbar_visibility()

        self.wave_canvas.delete("all")
        if self._wave_data is None:
            self.wave_canvas.create_text(
                self.wave_width // 2, self.wave_height // 2, text="(No preview)", fill=FG_MUTED
            )
            return

        end_frac = self.view_start_frac + self.view_span_frac
        if self._wave_data_stereo is not None:
            display_stereo = self._display_data_with_edits(self._wave_data_stereo)
            half_h = self.wave_height / 2.0
            draw_waveform_on_canvas(
                self.wave_canvas,
                display_stereo[:, 0],
                self.view_start_frac,
                end_frac,
                self.wave_width,
                half_h,
                tag="waveform",
                y_offset=0,
                clear=True,
            )
            draw_waveform_on_canvas(
                self.wave_canvas,
                display_stereo[:, 1],
                self.view_start_frac,
                end_frac,
                self.wave_width,
                half_h,
                tag="waveform",
                y_offset=half_h,
                clear=False,
            )
            self.wave_canvas.create_line(
                0, half_h, self.wave_width, half_h, fill=BORDER_COLOR, width=1, tags="waveform"
            )
        else:
            display_mono = self._display_data_with_edits(self._wave_data)
            draw_waveform_on_canvas(
                self.wave_canvas,
                display_mono,
                self.view_start_frac,
                end_frac,
                self.wave_width,
                self.wave_height,
            )
        # Overlays first so that markers render on top — painting the shaded
        # region over the red end marker would hide it precisely where the
        # two most often coincide.
        self._before_redraw_markers()
        self.redraw_markers()

    # --------------------------------------------------------- scrollbar

    def _update_scrollbar_visibility(self):
        if self.zoom_factor > 1.0 and self._wave_data is not None:
            if not self.wave_scrollbar.winfo_ismapped():
                self._zoom_spacer.pack_forget()
                self.wave_scrollbar.pack(fill="x", pady=(0, 4), after=self.wave_canvas)
            first = self.view_start_frac
            last = self.view_start_frac + self.view_span_frac
            self.wave_scrollbar.set(first, last)
        else:
            if self.wave_scrollbar.winfo_ismapped():
                self.wave_scrollbar.pack_forget()
            if not self._zoom_spacer.winfo_ismapped():
                self._zoom_spacer.pack(fill="x", pady=(0, 4), after=self.wave_canvas)

    def _pan_to(self, new_start_frac):
        new_start_frac = max(0.0, min(new_start_frac, 1.0 - self.view_span_frac))
        self.view_start_frac = new_start_frac
        self.center_frac = self.view_start_frac + self.view_span_frac / 2.0
        self._render_wave_at_current_view()

    def on_wave_scroll(self, *args):
        if not args or self.view_span_frac >= 1.0:
            return
        action = args[0]
        if action == "moveto":
            self._pan_to(float(args[1]))
        elif action == "scroll":
            amount = float(args[1])
            unit = args[2] if len(args) > 2 else "units"
            step = self.view_span_frac * (0.1 if unit == "units" else 0.9)
            self._pan_to(self.view_start_frac + amount * step)

    def on_wave_mousewheel(self, event):
        if self.view_span_frac >= 1.0:
            return
        if getattr(event, "num", None) == 4:
            delta = -1
        elif getattr(event, "num", None) == 5:
            delta = 1
        else:
            delta = -1 if event.delta > 0 else 1
        step = self.view_span_frac * 0.1
        self._pan_to(self.view_start_frac + delta * step)

    # --------------------------------------------------------- zoom controls

    def zoom_in(self):
        cap = max_zoom_for(getattr(self, "play_duration", 0))
        self.zoom_factor = min(self.zoom_factor * 1.6, cap)
        self.render_and_draw_wave()

    def zoom_out(self):
        self.zoom_factor = max(self.zoom_factor / 1.6, 1.0)
        self.render_and_draw_wave()

    def zoom_reset(self):
        self.zoom_factor = 1.0
        self.render_and_draw_wave()

    # --------------------------------------------------------- markers

    def redraw_markers(self):
        self.wave_canvas.delete("marker")
        self.wave_canvas.delete("playhead")
        if self._trim_is_locked():
            self.update_duration_label()
            return
        x_start = self.frac_to_x(self.trim_start_frac)
        x_end = self.frac_to_x(self.trim_end_frac)
        if x_start > 0:
            self.wave_canvas.create_rectangle(
                0,
                0,
                x_start,
                self.wave_height,
                fill=BG_DARK,
                stipple="gray50",
                outline="",
                tags="marker",
            )
        if x_end < self.wave_width:
            self.wave_canvas.create_rectangle(
                x_end,
                0,
                self.wave_width,
                self.wave_height,
                fill=BG_DARK,
                stipple="gray50",
                outline="",
                tags="marker",
            )
        draw_bracket_marker(self.wave_canvas, x_start, self.wave_height, ACCENT_GREEN, "start")
        draw_bracket_marker(self.wave_canvas, x_end, self.wave_height, ACCENT_RED, "end")
        self.update_duration_label()

    def update_duration_label(self):
        """Refresh the selection-length label.  Override to add class-specific content."""
        if not hasattr(self, "duration_label"):
            return
        if self.play_duration <= 0:
            self.duration_label.config(text="")
            return
        region_duration = self.play_duration * (self.trim_end_frac - self.trim_start_frac)
        self.duration_label.config(text=f"Selection: {region_duration:.2f}s")

    # --------------------------------------------------------- mouse interaction

    def on_wave_press(self, event):
        if self._trim_is_locked():
            self.drag_target = None
            return
        x_start = self.frac_to_x(self.trim_start_frac)
        x_end = self.frac_to_x(self.trim_end_frac)
        if abs(event.x - x_start) <= 9:
            self.drag_target = "start"
        elif abs(event.x - x_end) <= 9:
            self.drag_target = "end"
        else:
            self.drag_target = None

    def on_wave_drag(self, event):
        if not self.drag_target:
            return
        frac = max(0.0, min(self.x_to_frac(event.x), 1.0))
        if self.drag_target == "start":
            gap = min_trim_fraction(getattr(self, "play_duration", 0))
            self.trim_start_frac = min(frac, self.trim_end_frac - gap)
        elif self.drag_target == "end":
            gap = min_trim_fraction(getattr(self, "play_duration", 0))
            self.trim_end_frac = max(frac, self.trim_start_frac + gap)
        # Cheap during drag; the waveform image itself (which may recenter
        # when zoomed) is only redrawn once the mouse is released.
        self.redraw_markers()

    def on_wave_release(self, event):
        dragged = self.drag_target
        self.drag_target = None
        if dragged and self.zoom_factor > 1.0:
            self.center_frac = self.trim_start_frac if dragged == "start" else self.trim_end_frac
            self.render_and_draw_wave()

    # --------------------------------------------------------- playhead

    def update_playhead(self):
        """Animate the playhead line while audio is playing.

        Subclasses that need to handle special playback modes (e.g. cycle/loop)
        can override this method and call super().update_playhead() for the
        standard linear-progress path.
        """
        if not self.is_playing:
            return
        elapsed = time.time() - self.play_start_time
        override = getattr(self, "_audible_seconds", None)
        region_duration = (
            override
            if override
            else self.play_duration * (self.trim_end_frac - self.trim_start_frac)
        )
        frac_in_region = min(elapsed / region_duration, 1.0) if region_duration > 0 else 1.0
        abs_frac = self.trim_start_frac + frac_in_region * (
            self.trim_end_frac - self.trim_start_frac
        )
        x = self.frac_to_x(abs_frac)
        self.wave_canvas.delete("playhead")
        if 0 <= x <= self.wave_width:
            self.wave_canvas.create_line(
                x, 0, x, self.wave_height, fill=ACCENT_BLUE, width=2, tags="playhead"
            )
        if frac_in_region < 1.0:
            self.after(30, self.update_playhead)
        else:
            self.is_playing = False
            self._on_playhead_done()
            self.wave_canvas.delete("playhead")

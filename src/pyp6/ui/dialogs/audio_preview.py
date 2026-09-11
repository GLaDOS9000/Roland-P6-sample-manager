"""Audio file browser and preview dialog: AudioPreviewDialog."""

import os
import time
import tkinter as tk
from tkinter import ttk

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    from pedalboard.io import AudioFile as _PBAudioFile
except ImportError:
    _PBAudioFile = None

from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BTN_BLUE,
    BTN_GREEN,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
)
from pyp6.audio.info import get_audio_duration_seconds
from pyp6.audio.playback import AUDIO_AVAILABLE, play_audio
from pyp6.audio.processing import (
    apply_micro_fade,
    normalize_wav_file,
    trim_wav_file,
)
from pyp6.config import (
    format_duration,
    format_size,
    load_default_autoplay,
    temp_path,
)
from pyp6.constants import (
    AUDIO_PREVIEW_MIN_H,
    AUDIO_PREVIEW_MIN_W,
    UI_FAMILY,
    WT_DRAW_POINTS,
    WT_SR,
)
from pyp6.log import logger
from pyp6.synth.waveforms import wt_cycle_tone
from pyp6.ui.dialogs_common import (
    add_focus_border,
    add_tooltip,
    center_toplevel_on_parent,
    dark_showerror,
    ensure_dark_treeview_style,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.nav_mixin import FolderNavMixin
from pyp6.ui.waveform import (
    draw_bracket_marker,
    draw_waveform_on_canvas,
    max_zoom_for,
    min_trim_fraction,
)
from pyp6.ui.widgets import RoundedButton, RoundedPanel, RoundedScrollbar


class AudioPreviewDialog(FolderNavMixin, tk.Toplevel):
    def __init__(self, parent, initial_dir=None, cycle_hz=None):
        super().__init__(parent)
        # cycle_hz turns this into a single-cycle browser: files are auditioned
        # as a held note at that pitch instead of being played at their own
        # length, which for a 7 ms cycle is just a tick.
        self.cycle_hz = cycle_hz
        self.title("Select Single-Cycle Waveform" if cycle_hz else "Select Sample (with Preview)")
        self.geometry(f"{AUDIO_PREVIEW_MIN_W}x{AUDIO_PREVIEW_MIN_H}")
        self.minsize(AUDIO_PREVIEW_MIN_W, AUDIO_PREVIEW_MIN_H)
        style_toplevel(self)
        self.selected_path = None  # RESULT - only ever set by on_confirm()
        self.selected_display_name = None
        self.preview_path = None  # what's merely highlighted in the list
        self.current_dir = initial_dir or os.path.expanduser("~")
        self.autoplay_var = tk.BooleanVar(value=load_default_autoplay())
        self._sort_column = None  # None = default (name), else "name"/"length"/"size"
        self._sort_reverse = False

        self._build_nav_bar(container_bg=BG_DARK)

        ensure_dark_treeview_style()
        if cycle_hz:
            note = tk.Label(
                self,
                anchor="w",
                text=f"Previewing as a held note at "
                f"{cycle_hz:.2f} Hz \u00b7 the file's own sample "
                f"rate and length do not affect the pitch",
            )
            style_label(note, fg=ACCENT_BLUE, font=(UI_FAMILY, 8))
            note.pack(fill="x", padx=10, pady=(0, 2))
        list_panel = RoundedPanel(
            self,
            title="Samples",
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
        self.listbox = ttk.Treeview(
            list_frame,
            columns=("length", "size"),
            show="tree headings",
            selectmode="browse",
            yscrollcommand=scrollbar.set,
            style="Dark.Treeview",
        )
        self.listbox.heading("#0", text="Name", anchor="w", command=lambda: self._sort_by("name"))
        self.listbox.heading(
            "length", text="Length", anchor="e", command=lambda: self._sort_by("length")
        )
        self.listbox.heading("size", text="Size", anchor="e", command=lambda: self._sort_by("size"))
        self.listbox.column("#0", anchor="w", width=380, stretch=True)
        self.listbox.column("length", anchor="e", width=80, stretch=False)
        self.listbox.column("size", anchor="e", width=80, stretch=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        add_focus_border(self.listbox, list_frame)
        scrollbar.command = self.listbox.yview
        self.listbox.bind("<<TreeviewSelect>>", self.on_select)
        self.listbox.bind("<Double-Button-1>", self.on_confirm)
        self.listbox.bind("<BackSpace>", lambda e: self.go_up())

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
        # Fixed height, like the Chop dialog: only the list above expands, so
        # the scrollbar that appears when zooming in takes its space from the
        # list rather than pushing the button row off the bottom.
        wave_panel.pack(fill="x", padx=10, pady=(0, 4))
        autoplay_row = tk.Frame(wave_panel.body, bg=BG_PANEL)
        autoplay_row.pack(fill="x")
        autoplay_cb = tk.Checkbutton(
            autoplay_row, text="Autoplay (play sound on click)", variable=self.autoplay_var
        )
        style_checkbutton(autoplay_cb, bg=BG_PANEL)
        autoplay_cb.pack(side="left")
        add_tooltip(
            autoplay_cb,
            "Plays a sample as soon as you select it in the list.\nThe "
            "starting position of this switch is set under "
            "Settings \u2192 Defaults.",
        )

        self.normalize_var = tk.BooleanVar(value=False)
        normalize_cb = tk.Checkbutton(
            autoplay_row,
            text="Normalize",
            variable=self.normalize_var,
            command=self._render_wave_at_current_view,
        )
        style_checkbutton(normalize_cb, bg=BG_PANEL)
        normalize_cb.pack(side="left", padx=(12, 0))
        add_tooltip(
            normalize_cb,
            "Lifts the sample to its maximum level without clipping. Applied when "
            'you press "Select".',
        )

        zoom_row = tk.Frame(autoplay_row, bg=BG_PANEL)
        zoom_row.pack(side="left", padx=(16, 0))
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

        self.duration_label = tk.Label(autoplay_row, text="")
        style_label(self.duration_label, bg=BG_PANEL, fg=ACCENT_BLUE, font=(UI_FAMILY, 9, "bold"))
        self.duration_label.pack(side="right")

        self.wave_width = 480
        self.wave_height = 144
        self.wave_canvas = tk.Canvas(
            wave_panel.body,
            bg=WAVE_BG,
            width=self.wave_width,
            height=self.wave_height,
            highlightthickness=0,
            cursor="sb_h_double_arrow",
        )
        self.wave_canvas.pack(fill="x", pady=(8, 2))
        add_tooltip(
            self.wave_canvas,
            "Drag the green (start) and red (end) markers to load only that "
            'region onto the pad. "Reset" returns the zoom to the full view - '
            "it does not move the markers back.",
        )
        self.wave_canvas.bind("<Configure>", self._on_wave_canvas_resize)
        self.wave_scrollbar = RoundedScrollbar(
            wave_panel.body,
            orient="horizontal",
            command=self.on_wave_scroll,
            parent_bg=BG_PANEL,
            auto_hide=False,
        )
        # Holds the scrollbar's height while it is hidden, so showing it
        # later costs nothing and cannot push the button row out of the
        # window. Same height and padding as the scrollbar itself.
        self._zoom_spacer = tk.Frame(
            wave_panel.body, bg=BG_PANEL, height=RoundedScrollbar.THICKNESS
        )
        self._zoom_spacer.pack_propagate(False)
        # Packed straight away: the window sizes itself from its contents when
        # it opens, so the space has to be accounted for from the start.
        self._zoom_spacer.pack(fill="x", pady=(0, 4))
        # Not packed here on purpose - only shown once zoomed in. Placement is
        # managed by hand below, not by the scrollbar's own auto-hide.
        self.waveform_img = None
        self._wave_data_stereo = None  # (n, channels) raw data when the sample is stereo
        self.trim_start_frac = 0.0
        self.trim_end_frac = 1.0
        self.drag_target = None
        self.is_playing = False
        self.play_start_time = None
        self.play_duration = 0.0
        self.current_audio_path = None
        self._wave_data = None
        self._wave_fs = None
        self.zoom_factor = 1.0
        self.view_start_frac = 0.0
        self.view_span_frac = 1.0
        self.center_frac = 0.5  # what the zoomed view is focused on

        self.wave_canvas.bind("<ButtonPress-1>", self.on_wave_press)
        self.wave_canvas.bind("<B1-Motion>", self.on_wave_drag)
        self.wave_canvas.bind("<ButtonRelease-1>", self.on_wave_release)
        self.wave_canvas.bind("<MouseWheel>", self.on_wave_mousewheel)
        self.wave_canvas.bind("<Button-4>", self.on_wave_mousewheel)
        self.wave_canvas.bind("<Button-5>", self.on_wave_mousewheel)

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        self.preview_btn = RoundedButton(
            btn_row,
            text="\u25b6 Preview",
            command=self.toggle_preview,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=110,
        )
        self.preview_btn.pack(side="left", padx=4)
        add_tooltip(
            self.preview_btn,
            "Plays the marked region, or the whole sample if no markers are set.\nShortcut: Space",
        )
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
        )
        cancel_btn.pack(side="right", padx=4)
        select_btn = RoundedButton(
            btn_row,
            text="Select",
            command=self.on_confirm,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
        )
        select_btn.pack(side="right", padx=4)
        add_tooltip(
            select_btn,
            "Loads the sample onto the pad. Trim and Normalize are written to a "
            "new file in the temp folder - the original stays untouched.",
        )

        self.bind("<space>", self._on_space_key)
        # Without this, closing via the window manager's X skips on_cancel():
        # playback would keep running and the pending playhead tick would
        # fire on an already-destroyed canvas.
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)

        self.refresh_list()
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _on_space_key(self, event):
        """Space plays the current sample - except while typing in a text
        field (address bar etc.), where it should just type a space."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        self.preview_selected()
        return "break"

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

    def _sort_by(self, column):
        if self._sort_column == column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = column
            self._sort_reverse = False
        self.refresh_list()

    def _update_sort_headers(self):
        def label(base, col):
            if self._sort_column == col:
                return base + (" \u25bc" if self._sort_reverse else " \u25b2")
            return base

        self.listbox.heading("#0", text=label("Name", "name"))
        self.listbox.heading("length", text=label("Length", "length"))
        self.listbox.heading("size", text=label("Size", "size"))

    def refresh_list(self):
        for item in self.listbox.get_children():
            self.listbox.delete(item)
        self._update_path_entry()
        try:
            entries = sorted(os.listdir(self.current_dir))
        except Exception as e:
            entries = []
            logger.error(f"Could not read folder: {e}")

        folders, files = [], []
        for entry in entries:
            full = os.path.join(self.current_dir, entry)
            if os.path.isdir(full):
                folders.append(entry)
            elif entry.lower().endswith((".wav", ".mp3")):
                duration = get_audio_duration_seconds(full)
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = None
                files.append((entry, duration, size))

        folders.sort(key=str.lower)
        if self._sort_column == "length":
            files.sort(key=lambda r: (r[1] is None, r[1] or 0), reverse=self._sort_reverse)
        elif self._sort_column == "size":
            files.sort(key=lambda r: (r[2] is None, r[2] or 0), reverse=self._sort_reverse)
        else:
            files.sort(key=lambda r: r[0].lower(), reverse=self._sort_reverse)

        self._entries = [".."]
        self.listbox.insert("", tk.END, iid="0", text="..")
        for entry in folders:
            idx = len(self._entries)
            self._entries.append(f"[Folder] {entry}")
            self.listbox.insert("", tk.END, iid=str(idx), text=f"[Folder] {entry}")
        for entry, duration, size in files:
            idx = len(self._entries)
            self._entries.append(entry)
            self.listbox.insert(
                "",
                tk.END,
                iid=str(idx),
                text=entry,
                values=(format_duration(duration), format_size(size)),
            )
        self._update_sort_headers()

    def get_selected_entry(self):
        sel = self.listbox.selection()
        if not sel:
            return None
        idx = int(sel[0])
        if idx >= len(self._entries):
            return None
        return self._entries[idx]

    def on_select(self, event):
        entry = self.get_selected_entry()
        if entry and not entry.startswith("[Folder]") and entry != "..":
            # NOT self.selected_path: that one is the dialog's RESULT and is
            # only allowed to be set by on_confirm(). Merely clicking a file
            # in the list used to set it, so closing the window with the
            # WM's X button (which never runs on_cancel) left it filled in
            # and the caller loaded that sample onto the pad anyway -
            # untrimmed, un-normalized, and with an undo step pushed.
            self.preview_path = os.path.join(self.current_dir, entry)
            self.show_waveform(self.preview_path)
            if self.autoplay_var.get():
                self.preview_selected()
        else:
            self.preview_path = None
            self.wave_canvas.delete("all")

    def show_waveform(self, path):
        wav_path = path
        if path.lower().endswith(".mp3") and AUDIO_AVAILABLE and _PBAudioFile:
            try:
                with _PBAudioFile(path) as _f:
                    _audio = _f.read(_f.frames)
                    _sr = _f.samplerate
                wav_path = temp_path("waveform_src.wav")
                with _PBAudioFile(
                    wav_path, "w", samplerate=_sr, num_channels=_audio.shape[0], bit_depth=16
                ) as _f:
                    _f.write(_audio)
            except Exception:
                self._wave_data = None
                self.wave_canvas.delete("all")
                self.wave_canvas.create_text(
                    self.wave_width // 2, self.wave_height // 2, text="(No preview)", fill=FG_MUTED
                )
                return

        self.current_audio_path = wav_path
        self.trim_start_frac = 0.0
        self.trim_end_frac = 1.0
        self.zoom_factor = 1.0
        self.center_frac = 0.5

        try:
            data, fs = sf.read(wav_path, dtype="float32")
            if data.ndim > 1 and data.shape[1] >= 2:
                self._wave_data_stereo = data
                self._wave_data = data.mean(axis=1)
            else:
                self._wave_data_stereo = None
                self._wave_data = data.reshape(-1) if data.ndim > 1 else data
            self._wave_fs = fs
            self.play_duration = len(data) / float(fs) if fs else 0.0
        except Exception:
            self._wave_data = None
            self._wave_data_stereo = None
            self._wave_fs = None
            self.play_duration = 0.0

        self.render_and_draw_wave()

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

    def render_and_draw_wave(self):
        """Used after zoom changes or a marker drag: re-centers the view on
        the markers, then renders."""
        self._update_view_window()
        self._render_wave_at_current_view()

    def _on_wave_canvas_resize(self, event=None):
        """The canvas is packed to fill available space and can end up a
        different size than the fixed wave_width/wave_height used for
        drawing/marker/zoom math - keep them in sync so the waveform scales
        with the window instead of leaving empty space or getting clipped."""
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

    def _display_data_with_edits(self, data):
        """Returns a copy of the FULL (untrimmed) waveform data with
        Normalize applied only within the trim region - so the preview
        shows the amplitude you'll actually get if Normalize is checked
        when you confirm the selection."""
        if data is None or not self.normalize_var.get():
            return data
        n = len(data)
        start_i = int(self.trim_start_frac * n)
        end_i = int(self.trim_end_frac * n)
        region = data[start_i:end_i]
        if len(region) == 0:
            return data
        peak = float(np.max(np.abs(region))) if region.size else 0.0
        if peak <= 0:
            return data
        result = data.copy()
        result[start_i:end_i] = region * (0.98 / peak)
        return result

    def _render_wave_at_current_view(self):
        """Renders at whatever view_start_frac/view_span_frac currently are,
        without recentering - used for manual scrollbar/mousewheel panning."""
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
        self.redraw_markers()

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

    def redraw_markers(self):
        self.wave_canvas.delete("marker")
        self.wave_canvas.delete("playhead")
        if self.cycle_hz:
            # Nothing to trim - the whole file is the cycle.
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
        if not hasattr(self, "duration_label"):
            return
        if self.cycle_hz:
            # play_rate does not exist; the loaded samples and their rate are
            # kept as _wave_data / _wave_fs by render_and_draw_wave().
            data = getattr(self, "_wave_data", None)
            frames = int(len(data)) if data is not None else 0
            if not frames:
                self.duration_label.config(text="")
                return
            fs = getattr(self, "_wave_fs", None) or WT_SR
            usable = min(frames // 2, WT_DRAW_POINTS // 2)
            self.duration_label.config(
                text=f"{frames} frames @ {int(fs)} Hz  \u00b7  {usable} harmonics"
            )
            return
        if self.play_duration <= 0:
            self.duration_label.config(text="")
            return
        region_duration = self.play_duration * (self.trim_end_frac - self.trim_start_frac)
        self.duration_label.config(text=f"Selection: {region_duration:.2f}s")

    def on_wave_press(self, event):
        if self.cycle_hz:
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
        # Cheap during drag; the waveform image itself (which may re-center
        # when zoomed) is only redrawn once the mouse is released.
        self.redraw_markers()

    def on_wave_release(self, event):
        dragged = self.drag_target
        self.drag_target = None
        if dragged and self.zoom_factor > 1.0:
            self.center_frac = self.trim_start_frac if dragged == "start" else self.trim_end_frac
            self.render_and_draw_wave()

    def update_playhead(self):
        if not self.is_playing:
            return
        if self.cycle_hz:
            # A held note repeats the same cycle hundreds of times; a marker
            # racing across it would suggest a position that does not exist.
            # The button already shows that something is playing.
            secs = getattr(self, "_audible_seconds", None) or 1.0
            if time.time() - self.play_start_time >= secs:
                self.is_playing = False
                if hasattr(self, "preview_btn"):
                    self.preview_btn.text = "\u25b6 Preview"
                    self.preview_btn._draw()
            else:
                self.after(50, self.update_playhead)
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
            if hasattr(self, "preview_btn"):
                self.preview_btn.text = "\u25b6 Preview"
                self.preview_btn._draw()
            self.wave_canvas.delete("playhead")

    def get_trimmed_export_path(self):
        if self.trim_start_frac <= 0.001 and self.trim_end_frac >= 0.999:
            return None
        if not self.current_audio_path:
            return None
        return trim_wav_file(self.current_audio_path, self.trim_start_frac, self.trim_end_frac)

    def on_confirm(self, event=None):
        entry = self.get_selected_entry()
        if entry is None:
            return
        if entry == "..":
            self.go_up()
            return
        if entry.startswith("[Folder] "):
            folder_name = entry.replace("[Folder] ", "", 1)
            self.navigate_to(os.path.join(self.current_dir, folder_name))
            return

        original_path = os.path.join(self.current_dir, entry)
        try:
            trimmed_path = self.get_trimmed_export_path()
        except Exception as e:
            dark_showerror("Trim Error", f"Could not create the trimmed sample:\n{e}", parent=self)
            return

        result_path = trimmed_path if trimmed_path else original_path
        name_suffix = " (trim)" if trimmed_path else ""

        if self.normalize_var.get():
            try:
                result_path = normalize_wav_file(result_path)
                name_suffix += " (normalized)"
            except Exception as e:
                dark_showerror(
                    "Normalize Error", f"Could not normalize the sample:\n{e}", parent=self
                )
                return

        self.selected_path = result_path
        self.selected_display_name = f"{entry}{name_suffix}"

        self.stop_preview()
        self.destroy()

    def toggle_preview(self):
        if self.is_playing:
            self.stop_preview()
        else:
            self.preview_selected()

    def preview_selected(self):
        entry = self.get_selected_entry()
        if not entry or entry == ".." or entry.startswith("[Folder]"):
            return
        path = os.path.join(self.current_dir, entry)
        try:
            sd.stop()
            play_path = path
            if path.lower().endswith(".mp3"):
                if not AUDIO_AVAILABLE or not _PBAudioFile:
                    dark_showerror(
                        "pedalboard missing",
                        "Previewing MP3 requires pedalboard.",
                        parent=self,
                    )
                    return
                with _PBAudioFile(path) as _f:
                    _audio = _f.read(_f.frames)
                    _sr = _f.samplerate
                tmp_preview = temp_path("preview_tmp.wav")
                with _PBAudioFile(
                    tmp_preview, "w", samplerate=_sr, num_channels=_audio.shape[0], bit_depth=16
                ) as _f:
                    _f.write(_audio)
                play_path = tmp_preview

            data, fs = sf.read(play_path, dtype="float32")
            if self.cycle_hz:
                mono = data.mean(axis=1) if data.ndim > 1 else data
                tone = wt_cycle_tone(mono, self.cycle_hz)
                play_audio(tone, WT_SR)
                # The tone lasts far longer than the file it was built from,
                # so the playhead has to follow the tone.
                self._audible_seconds = len(tone) / float(WT_SR)
                self.is_playing = True
                self.preview_btn.text = "\u25a0 Stop"
                self.preview_btn._draw()
                self.play_start_time = time.time()
                self.update_playhead()
                return
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
            play_audio(segment, fs)

            self.is_playing = True
            self.preview_btn.text = "\u25a0 Stop"
            self.preview_btn._draw()
            self.play_start_time = time.time()
            self.update_playhead()
        except Exception as e:
            dark_showerror("Error During Preview", str(e), parent=self)

    def stop_preview(self):
        try:
            sd.stop()
        except Exception:
            pass
        self.is_playing = False
        if hasattr(self, "preview_btn"):
            self.preview_btn.text = "\u25b6 Preview"
            self.preview_btn._draw()
        self.wave_canvas.delete("playhead")

    def on_cancel(self):
        self.stop_preview()
        self.selected_path = None
        self.destroy()

"""Audio preview and chop dialogs: AudioPreviewDialog, ChopDialog."""

import os
import time
import tkinter as tk
import uuid
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
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None

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
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
)
from pyp6.audio.conversion import build_chop_file
from pyp6.audio.info import get_audio_duration_seconds
from pyp6.audio.playback import PYDUB_AVAILABLE
from pyp6.audio.processing import (
    apply_micro_fade,
    ensure_mono_wav,
    normalize_wav_file,
    trim_wav_file,
)
from pyp6.config import (
    format_duration,
    format_size,
    load_default_autoplay,
    load_default_slices,
    temp_path,
)
from pyp6.constants import (
    AUDIO_PREVIEW_MIN_H,
    AUDIO_PREVIEW_MIN_W,
    CHOP_MIN_H,
    CHOP_MIN_W,
    MAX_SECONDS,
    NORMALIZE_MODE_KEYS,
    NORMALIZE_MODES,
    SLICE_COUNTS,
    TARGET_RATES,
    UI_FAMILY,
    WT_DRAW_POINTS,
    WT_SR,
)
from pyp6.synth.waveforms import wt_cycle_tone
from pyp6.ui.dialogs_common import (
    add_focus_border,
    add_tooltip,
    center_toplevel_on_parent,
    dark_askyesno,
    dark_showerror,
    dark_showinfo,
    dark_showwarning,
    ensure_dark_treeview_style,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.nav_mixin import FolderNavMixin
from pyp6.ui.waveform import (
    draw_bracket_marker,
    draw_truncate_overlay,
    draw_waveform_on_canvas,
    max_zoom_for,
    min_trim_fraction,
)
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel, RoundedScrollbar


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
            print(f"Could not read folder: {e}")

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
        if path.lower().endswith(".mp3") and PYDUB_AVAILABLE:
            try:
                sound = AudioSegment.from_file(path)
                wav_path = temp_path("waveform_src.wav")
                sound.export(wav_path, format="wav")
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
                if not PYDUB_AVAILABLE:
                    dark_showerror(
                        "pydub missing", "Previewing MP3 requires pydub + ffmpeg.", parent=self
                    )
                    return
                sound = AudioSegment.from_file(path)
                tmp_preview = temp_path("preview_tmp.wav")
                sound.export(tmp_preview, format="wav")
                play_path = tmp_preview

            data, fs = sf.read(play_path, dtype="float32")
            if self.cycle_hz:
                mono = data.mean(axis=1) if data.ndim > 1 else data
                tone = wt_cycle_tone(mono, self.cycle_hz)
                sd.play(tone, WT_SR)
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
            sd.play(segment, fs)

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


class ChopDialog(FolderNavMixin, tk.Toplevel):
    """All-in-one Chop window: a Browse pane (left) to find samples, a
    Selected pane (right) showing the chop order, and a shared waveform view
    with drag markers so you can add a trimmed region of a Browse sample
    straight into the selection."""

    def __init__(self, parent, initial_dir=None):
        super().__init__(parent)
        self.title("Chop - Build Multisample")
        self.geometry(f"{CHOP_MIN_W}x{CHOP_MIN_H}")
        self.minsize(CHOP_MIN_W, CHOP_MIN_H)
        style_toplevel(self)
        self.result_path = None
        self.current_dir = initial_dir or os.path.expanduser("~")
        self.selected_files = []
        self.selected_display_names = []
        self._entries = []
        self.autoplay_var = tk.BooleanVar(value=load_default_autoplay())
        self._sort_column = None  # Browse list sort state (Selected list is never sorted -
        self._sort_reverse = False  # only the real chop order matters there)

        # Shared waveform/trim state -----------------------------------
        self.wave_width = 960
        self.wave_height = 162
        self.wave_mode = "browse"  # "browse" (draggable markers) or "selected" (view only)
        self.current_audio_path = None  # decoded-to-wav path backing the waveform/trim/preview
        self.browse_source_path = None  # original file behind the currently loaded BROWSE item
        self.trim_start_frac = 0.0
        self.trim_end_frac = 1.0
        self.drag_target = None
        self.is_playing = False
        self.play_start_time = None
        self.play_duration = 0.0
        self._wave_data = None  # cached mono float32 samples of current_audio_path
        self._wave_data_stereo = None  # (n, channels) raw data when the sample is stereo
        self._wave_fs = None
        self.zoom_factor = 1.0  # 1.0 = whole file visible
        self.view_start_frac = 0.0  # left edge of the visible window (fraction of full duration)
        self.view_span_frac = 1.0  # width of the visible window (fraction of full duration)
        self.center_frac = 0.5  # what the zoomed view is focused on

        self._build_nav_bar(container_bg=BG_DARK)

        # ----- three panes: Browse | transfer arrows | Selected -----
        # Same arrangement as the Synth dialog. Putting the four transfer
        # actions in one narrow column between the lists frees the two button
        # rows underneath them, which is where the vertical space went.
        panes = tk.Frame(self, bg=BG_DARK)
        panes.pack(fill="both", expand=True, padx=10, pady=(0, 4))
        panes.grid_columnconfigure(0, weight=1)
        panes.grid_columnconfigure(1, weight=0)
        panes.grid_columnconfigure(2, weight=1)
        panes.grid_rowconfigure(0, weight=1)

        # --- LEFT: Browse ---
        # The heading lives on the panel now, so the separate title Label is
        # gone. `left` stays pointing at the panel body, which keeps every
        # child below unchanged apart from its background.
        left_panel = RoundedPanel(
            panes,
            title="Browse",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        left_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        left = left_panel.body

        ensure_dark_treeview_style()
        left_list_frame = tk.Frame(left, bg=BG_PANEL)
        left_list_frame.pack(fill="both", expand=True)
        left_scrollbar = RoundedScrollbar(left_list_frame, orient="vertical", parent_bg=BG_PANEL)
        left_scrollbar.pack(side="right", fill="y", padx=(3, 0))
        self.listbox = ttk.Treeview(
            left_list_frame,
            columns=("length", "size"),
            show="tree headings",
            selectmode="extended",
            yscrollcommand=left_scrollbar.set,
            style="Dark.Treeview",
        )
        self.listbox.heading("#0", text="Name", anchor="w", command=lambda: self._sort_by("name"))
        self.listbox.heading(
            "length", text="Length", anchor="e", command=lambda: self._sort_by("length")
        )
        self.listbox.heading("size", text="Size", anchor="e", command=lambda: self._sort_by("size"))
        self.listbox.column("#0", anchor="w", width=180, stretch=True)
        self.listbox.column("length", anchor="e", width=60, stretch=False)
        self.listbox.column("size", anchor="e", width=65, stretch=False)
        self.listbox.pack(side="left", fill="both", expand=True)
        add_focus_border(self.listbox, left_list_frame)
        left_scrollbar.command = self.listbox.yview
        self.listbox.bind("<Double-Button-1>", self.on_double_click)
        self.listbox.bind("<<TreeviewSelect>>", self.on_browse_select)
        self.listbox.bind("<BackSpace>", lambda e: self.go_up())

        # --- MIDDLE: transfer column ---
        mid = tk.Frame(panes, bg=BG_DARK)
        mid.grid(row=0, column=1, padx=4)  # no sticky: centred on the lists
        for txt, cmd, tip in (
            (
                "\u2192",
                self.add_selected,
                "Adds the sample(s) highlighted on the left to the chop order.\n"
                "With trim markers set, only the marked region is added - so you "
                "can pull several regions out of one long file.",
            ),
            (
                "\u2190",
                self.remove_from_selection,
                "Takes the highlighted entries back out of the chop order. The "
                "files themselves are untouched.\nShortcut: Del or Backspace",
            ),
            (
                "\u25b2",
                self.move_up,
                "Moves the highlighted entry one slice earlier. The order in the "
                "right-hand list is the slice order on the P-6.\nShortcut: Alt+Up",
            ),
            (
                "\u25bc",
                self.move_down,
                "Moves the highlighted entry one slice later.\nShortcut: Alt+Down",
            ),
        ):
            b = RoundedButton(
                mid,
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

        # Preview sits with the transfer buttons rather than under one list,
        # since it plays whichever list last fed the waveform view. Glyph only:
        # the word would have set the column's width for all five buttons.
        self.browse_preview_btn = RoundedButton(
            mid,
            text="\u25b6",
            command=self.toggle_preview,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=40,
            height=26,
            font=(UI_FAMILY, 10, "bold"),
        )
        self.browse_preview_btn.pack(pady=(14, 3))
        add_tooltip(
            self.browse_preview_btn,
            "Plays whatever the waveform view below is showing - a browsed "
            "sample, or an entry from the chop order at its target rate and "
            "channel count. With trim markers set, only the marked region is "
            "played.\nShortcut: Space",
        )

        # --- RIGHT: Selected ---
        self.selected_panel = RoundedPanel(
            panes,
            title="Chop Order: 0",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            radius=12,
            title_font=(UI_FAMILY, 9, "bold"),
            body_padx=10,
            body_pady=(24, 8),
        )
        self.selected_panel.grid(row=0, column=2, sticky="nsew", padx=(4, 0))
        right = self.selected_panel.body

        right_list_frame = tk.Frame(right, bg=BG_PANEL)
        right_list_frame.pack(fill="both", expand=True)
        right_scrollbar = RoundedScrollbar(right_list_frame, orient="vertical", parent_bg=BG_PANEL)
        right_scrollbar.pack(side="right", fill="y", padx=(3, 0))
        self.selected_listbox = ttk.Treeview(
            right_list_frame,
            columns=("no", "name", "length", "size"),
            show="headings",
            selectmode="extended",
            yscrollcommand=right_scrollbar.set,
            style="Dark.Treeview",
        )
        self.selected_listbox.heading("no", text="No.", anchor="w")
        self.selected_listbox.heading("name", text="Name", anchor="w")
        self.selected_listbox.heading("length", text="Length", anchor="e")
        self.selected_listbox.heading("size", text="Size", anchor="e")
        self.selected_listbox.column("no", anchor="w", width=32, stretch=False)
        self.selected_listbox.column("name", anchor="w", width=148, stretch=True)
        self.selected_listbox.column("length", anchor="e", width=60, stretch=False)
        self.selected_listbox.column("size", anchor="e", width=65, stretch=False)
        self.selected_listbox.tag_configure("toolong", foreground=ACCENT_ORANGE)
        self.selected_listbox.pack(side="left", fill="both", expand=True)
        add_focus_border(self.selected_listbox, right_list_frame)
        right_scrollbar.command = self.selected_listbox.yview
        self.selected_listbox.bind("<Double-Button-1>", lambda e: self.preview_current())
        self.selected_listbox.bind("<Alt-Left>", lambda e: self.remove_from_selection())

        self.selected_listbox.bind("<<TreeviewSelect>>", self.on_selected_select)
        self.selected_listbox.bind("<Alt-Up>", lambda e: self.move_up())
        self.selected_listbox.bind("<Alt-Down>", lambda e: self.move_down())
        self.selected_listbox.bind("<Delete>", lambda e: self.remove_from_selection())
        self.selected_listbox.bind("<BackSpace>", lambda e: self.remove_from_selection())

        # ----- shared waveform / trim view -----
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
        wave_panel.pack(fill="x", padx=10, pady=(4, 0))
        wave_wrap = wave_panel.body

        wave_header = tk.Frame(wave_wrap, bg=BG_PANEL)
        wave_header.pack(fill="x")
        self.wave_name_label = tk.Label(wave_header, text="No sample loaded")
        style_label(self.wave_name_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self.wave_name_label.pack(side="left")
        autoplay_cb = tk.Checkbutton(
            wave_header, text="Autoplay on click", variable=self.autoplay_var
        )
        style_checkbutton(autoplay_cb, bg=BG_PANEL)
        autoplay_cb.pack(side="left", padx=(16, 0))
        add_tooltip(
            autoplay_cb,
            "Plays a sample as soon as you click it in either list.\nThe "
            "starting position of this switch is set under "
            "Settings \u2192 Defaults.",
        )

        zoom_row = tk.Frame(wave_header, bg=BG_PANEL)
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

        self.duration_label = tk.Label(wave_header, text="")
        style_label(self.duration_label, bg=BG_PANEL, fg=ACCENT_BLUE, font=(UI_FAMILY, 9, "bold"))
        self.duration_label.pack(side="right")

        self.wave_canvas = tk.Canvas(
            wave_wrap,
            bg=WAVE_BG,
            width=self.wave_width,
            height=self.wave_height,
            highlightthickness=0,
            cursor="sb_h_double_arrow",
        )
        self.wave_canvas.pack(fill="x", pady=(4, 2))
        add_tooltip(
            self.wave_canvas,
            "Drag the green (start) and red (end) markers to mark a region. "
            "The scrollbar appears once you are zoomed in. Markers only work on "
            'samples from "Browse".',
        )
        self.wave_canvas.bind("<Configure>", self._on_wave_canvas_resize)
        self.waveform_img = None
        self.wave_canvas.bind("<ButtonPress-1>", self.on_wave_press)
        self.wave_canvas.bind("<B1-Motion>", self.on_wave_drag)
        self.wave_canvas.bind("<ButtonRelease-1>", self.on_wave_release)
        self.wave_canvas.bind("<MouseWheel>", self.on_wave_mousewheel)  # Windows / macOS
        self.wave_canvas.bind("<Button-4>", self.on_wave_mousewheel)  # Linux scroll up
        self.wave_canvas.bind("<Button-5>", self.on_wave_mousewheel)  # Linux scroll down

        self.wave_scrollbar = RoundedScrollbar(
            wave_wrap,
            orient="horizontal",
            command=self.on_wave_scroll,
            parent_bg=BG_PANEL,
            auto_hide=False,
        )
        # Holds the scrollbar's height while it is hidden, so showing it
        # later costs nothing and cannot push the button row out of the
        # window. Same height and padding as the scrollbar itself.
        self._zoom_spacer = tk.Frame(wave_wrap, bg=BG_PANEL, height=RoundedScrollbar.THICKNESS)
        self._zoom_spacer.pack_propagate(False)
        # Packed straight away: the window sizes itself from its contents when
        # it opens, so the space has to be accounted for from the start.
        self._zoom_spacer.pack(fill="x", pady=(0, 4))
        # Not packed here on purpose - only shown once zoomed in (see
        # _update_scrollbar_visibility), which places it by hand instead of
        # leaving it to the scrollbar's own fits-in-view auto-hide.

        hint = tk.Label(
            wave_wrap,
            text='Click a sample in "Browse", drag the green/red markers, then '
            "\u2192 \u2014 adds only the marked region. "
            "Without markers the whole file is added.",
            anchor="w",
            justify="left",
            wraplength=CHOP_MIN_W - 20,
        )
        style_label(hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", pady=(0, 4))

        # ----- chop build options -----
        opts = tk.Frame(self, padx=10, pady=8, bg=BG_DARK)
        opts.pack(fill="x")

        lbl1 = tk.Label(opts, text="Slices:")
        style_label(lbl1)
        lbl1.grid(row=0, column=0, sticky="w")
        self.slices_var = tk.IntVar(value=load_default_slices())
        om1 = RoundedDropdown(
            opts,
            self.slices_var,
            SLICE_COUNTS,
            parent_bg=BG_DARK,
            width=70,
            command=lambda _v: self.on_options_changed(),
        )
        om1.grid(row=0, column=1, padx=6)
        add_tooltip(
            om1,
            "How many equal slices the multisample is divided into. Each selected "
            "sample fills one slice; unused slices stay silent. Fewer slices = "
            "more time per slice.",
        )

        lbl2 = tk.Label(opts, text="Sample Rate:")
        style_label(lbl2)
        lbl2.grid(row=0, column=2, sticky="w", padx=(16, 0))
        self.rate_var = tk.IntVar(value=44100)
        om2 = RoundedDropdown(
            opts,
            self.rate_var,
            TARGET_RATES,
            parent_bg=BG_DARK,
            width=90,
            command=lambda _v: self.on_options_changed(),
        )
        om2.grid(row=0, column=3, padx=6)
        add_tooltip(
            om2,
            "Sample rate of the finished multisample. A lower rate means less "
            "memory and a longer possible slice time, at the cost of high "
            "frequencies.",
        )

        self.stereo_var = tk.BooleanVar(value=False)
        self.stereo_cb = tk.Checkbutton(
            opts, text="Stereo", variable=self.stereo_var, command=self.on_options_changed
        )
        style_checkbutton(self.stereo_cb)
        self.stereo_cb.grid(row=0, column=4, padx=(16, 0))
        add_tooltip(
            self.stereo_cb,
            "Builds the multisample in stereo. Mono halves the size and doubles "
            "the possible slice time. Locks itself as soon as the list on the "
            "right is not empty, so mono and stereo entries can't get mixed - "
            "clear the selection to change it.",
        )

        norm_lbl = tk.Label(opts, text="Normalize:")
        style_label(norm_lbl)
        norm_lbl.grid(row=0, column=5, sticky="w", padx=(16, 0))
        self.normalize_mode_var = tk.StringVar(value=NORMALIZE_MODES[0])
        norm_dd = RoundedDropdown(
            opts,
            self.normalize_mode_var,
            NORMALIZE_MODES,
            parent_bg=BG_DARK,
            width=110,
            command=lambda _v: self._on_normalize_mode_changed(),
        )
        norm_dd.grid(row=0, column=6, padx=6)
        add_tooltip(
            norm_dd,
            "Off: levels stay as they are.\n"
            "Per sample: every slice is lifted to full level on its own - use "
            "this when the samples were recorded at different volumes.\n"
            "Whole file: only the finished multisample is lifted, the balance "
            "between the slices stays as it is.",
        )

        self.limits_label = tk.Label(self, text="", anchor="w")
        style_label(self.limits_label, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        self.limits_label.pack(fill="x", padx=10, pady=(0, 4))

        self.info_label = tk.Label(self, text="", wraplength=CHOP_MIN_W - 20, justify="left")
        style_label(self.info_label, fg=ACCENT_RED)
        self.info_label.pack(fill="x", padx=10)

        btn_row = tk.Frame(self, padx=10, pady=10, bg=BG_DARK)
        btn_row.pack(fill="x")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
        )
        cancel_btn.pack(side="right", padx=4)
        build_btn = RoundedButton(
            btn_row,
            text="Build Multisample",
            command=self.on_build,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=150,
        )
        build_btn.pack(side="right", padx=4)
        add_tooltip(
            build_btn,
            "Renders the chop order into a single WAV and loads it onto the pad "
            "you started from. Samples longer than the slice time are truncated.",
        )
        clear_btn = RoundedButton(
            btn_row,
            text="Clear Selection",
            command=self.clear_selection,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=130,
        )
        clear_btn.pack(side="left", padx=4)
        add_tooltip(clear_btn, "Empties the chop order on the right. Files are not deleted.")

        self.refresh_list()
        self.refresh_selected_list()
        self.update_limits_label()
        self.bind("<space>", self._on_space_key)
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)  # X must stop playback too
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _normalize_mode(self):
        """Internal key ("off"/"per_sample"/"whole") for the Normalize
        dropdown, which itself holds the human-readable label."""
        return NORMALIZE_MODE_KEYS.get(self.normalize_mode_var.get(), "off")

    def _normalize_per_sample(self):
        """Whether the CURRENTLY shown sample is affected by Normalize.

        Only "Per sample" changes an individual sample, so this is what the
        waveform preview and the preview playback follow. In "Whole file"
        mode the individual sample is untouched and only the finished
        multisample gets lifted - showing it scaled here would promise a
        level this sample never actually has."""
        return self._normalize_mode() == "per_sample"

    def _on_normalize_mode_changed(self):
        self._render_wave_at_current_view()

    def _on_space_key(self, event):
        """Space plays the current sample - except while typing in a text
        field (address bar, preset name entry etc.), where it should just
        type a space."""
        if isinstance(self.focus_get(), tk.Entry):
            return
        self.preview_current()
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

    # ----- Browse pane -----

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
            print(f"Could not read folder: {e}")

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

    def _entry_at(self, index):
        if 0 <= index < len(self._entries):
            return self._entries[index]
        return None

    def on_double_click(self, event):
        sel = self.listbox.selection()
        if not sel:
            return
        entry = self._entry_at(int(sel[0]))
        if entry is None:
            return
        if entry == "..":
            self.go_up()
        elif entry.startswith("[Folder] "):
            folder_name = entry.replace("[Folder] ", "", 1)
            self.navigate_to(os.path.join(self.current_dir, folder_name))
        else:
            self.add_selected()

    def on_browse_select(self, event):
        sel = self.listbox.selection()
        if len(sel) != 1:
            return  # multi-select for batch add - don't disturb the waveform
        entry = self._entry_at(int(sel[0]))
        if not entry or entry == ".." or entry.startswith("[Folder]"):
            self.current_audio_path = None
            self.browse_source_path = None
            self.wave_canvas.delete("all")
            self.wave_name_label.config(text="No sample loaded")
            self.duration_label.config(text="")
            return
        full_path = os.path.join(self.current_dir, entry)
        self.browse_source_path = full_path
        self.load_waveform(full_path, mode="browse")
        if self.autoplay_var.get():
            self.preview_current()

    # ----- Selected pane -----

    def compute_slice_limit_seconds(self):
        rate = self.rate_var.get()
        channels = 2 if self.stereo_var.get() else 1
        num_slices = self.slices_var.get()
        limit = MAX_SECONDS.get((rate, channels))
        if not limit or num_slices <= 0:
            return None
        return limit / num_slices

    def update_limits_label(self):
        rate = self.rate_var.get()
        channels = 2 if self.stereo_var.get() else 1
        num_slices = self.slices_var.get()
        limit = MAX_SECONDS.get((rate, channels))
        if limit and num_slices > 0:
            per_slice = limit / num_slices
            ch_label = "Stereo" if channels == 2 else "Mono"
            self.limits_label.config(
                text=f"Max total: {limit:.2f}s @ {rate}Hz/{ch_label}   \u2022   "
                f"Max per slice ({num_slices} slices): {per_slice:.2f}s"
            )
        else:
            self.limits_label.config(text="")

    def on_options_changed(self):
        self.update_limits_label()
        self.refresh_selected_list()
        if self.current_audio_path:
            self._reload_wave_channels()
            self.render_and_draw_wave()

    def refresh_selected_list(self):
        for item in self.selected_listbox.get_children():
            self.selected_listbox.delete(item)
        slice_limit = self.compute_slice_limit_seconds()
        for i, path in enumerate(self.selected_files):
            duration = get_audio_duration_seconds(path)
            try:
                size = os.path.getsize(path)
            except OSError:
                size = None
            too_long = bool(slice_limit and duration and duration > slice_limit)
            display_name = (
                self.selected_display_names[i]
                if i < len(self.selected_display_names)
                else os.path.basename(path)
            )
            self.selected_listbox.insert(
                "",
                tk.END,
                iid=str(i),
                values=(i + 1, display_name, format_duration(duration), format_size(size)),
                tags=("toolong",) if too_long else (),
            )
        self.selected_panel.set_title(f"Chop Order: {len(self.selected_files)}")
        self.update_stereo_lock()

    def update_stereo_lock(self):
        """Locks the Stereo checkbox once samples are selected, so you can't
        end up mixing mono- and stereo-normalized entries in one multisample
        by flipping it mid-selection. Unlocks again once the list is empty."""
        if not hasattr(self, "stereo_cb"):
            return
        if self.selected_files:
            self.stereo_cb.config(state="disabled", text="Stereo (locked)")
        else:
            self.stereo_cb.config(state="normal", text="Stereo")

    def on_selected_select(self, event):
        sel = self.selected_listbox.selection()
        if len(sel) != 1:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.selected_files):
            display_name = (
                self.selected_display_names[idx] if idx < len(self.selected_display_names) else None
            )
            self.load_waveform(self.selected_files[idx], mode="selected", display_name=display_name)
            if self.autoplay_var.get():
                self.preview_current()

    def move_up(self):
        sel = sorted(int(i) for i in self.selected_listbox.selection())
        if not sel or sel[0] == 0:
            return
        for i in sel:
            self.selected_files[i - 1], self.selected_files[i] = (
                self.selected_files[i],
                self.selected_files[i - 1],
            )
            self.selected_display_names[i - 1], self.selected_display_names[i] = (
                self.selected_display_names[i],
                self.selected_display_names[i - 1],
            )
        self.refresh_selected_list()
        self.selected_listbox.selection_set([str(i - 1) for i in sel])
        self.selected_listbox.see(str(sel[0] - 1))

    def move_down(self):
        sel = sorted((int(i) for i in self.selected_listbox.selection()), reverse=True)
        if not sel or sel[0] == len(self.selected_files) - 1:
            return
        for i in sel:
            self.selected_files[i + 1], self.selected_files[i] = (
                self.selected_files[i],
                self.selected_files[i + 1],
            )
            self.selected_display_names[i + 1], self.selected_display_names[i] = (
                self.selected_display_names[i],
                self.selected_display_names[i + 1],
            )
        self.refresh_selected_list()
        self.selected_listbox.selection_set([str(i + 1) for i in sel])
        self.selected_listbox.see(str(sel[0] + 1))

    def remove_from_selection(self):
        sel = [int(i) for i in self.selected_listbox.selection()]
        if not sel:
            return
        for i in sorted(sel, reverse=True):
            if 0 <= i < len(self.selected_files):
                del self.selected_files[i]
                del self.selected_display_names[i]
        self.refresh_selected_list()

    def clear_selection(self):
        self.selected_files = []
        self.selected_display_names = []
        self.refresh_selected_list()

    def add_selected(self):
        sel = [int(i) for i in self.listbox.selection()]
        entries = []
        for i in sel:
            entry = self._entry_at(i)
            if entry and entry != ".." and not entry.startswith("[Folder]"):
                entries.append(entry)
        if not entries:
            return

        single_full_path = os.path.join(self.current_dir, entries[0]) if len(entries) == 1 else None
        region_marked = not (self.trim_start_frac <= 0.001 and self.trim_end_frac >= 0.999)

        if (
            len(entries) == 1
            and single_full_path == self.browse_source_path
            and region_marked
            and self.current_audio_path
        ):
            # Single file with a marked region -> add just that trimmed clip.
            try:
                trimmed_path = trim_wav_file(
                    self.current_audio_path, self.trim_start_frac, self.trim_end_frac
                )
                if not self.stereo_var.get():
                    trimmed_path = ensure_mono_wav(trimmed_path)
                self.selected_files.append(trimmed_path)
                # trim_wav_file()/ensure_mono_wav() write to a randomly-named
                # temp file, so keep the ORIGINAL name around for display -
                # otherwise the list becomes a wall of unrecognizable
                # "mono_a1b2c3d4.wav" entries.
                self.selected_display_names.append(f"{entries[0]} (trim)")
            except Exception as e:
                dark_showerror("Trim Error", str(e), parent=self)
                return
        else:
            # Batch add: one or more full files (no trimming).
            for entry in entries:
                full_path = os.path.join(self.current_dir, entry)
                if not self.stereo_var.get():
                    full_path = ensure_mono_wav(full_path)
                self.selected_files.append(full_path)
                self.selected_display_names.append(entry)

        self.refresh_selected_list()

    # ----- Shared waveform / trim / preview -----

    def _decide_channels(self, data):
        """Decides mono vs stereo display/handling for `data` based on the
        Stereo checkbox: with Stereo off, everything is mixed down to mono
        (waveform, preview, and later what gets added to the selection)."""
        if data.ndim > 1 and data.shape[1] >= 2:
            if self.stereo_var.get():
                return data.mean(axis=1), data
            return data.mean(axis=1), None
        return (data.reshape(-1) if data.ndim > 1 else data), None

    def _reload_wave_channels(self):
        """Re-applies the mono/stereo decision for the currently loaded
        audio (e.g. after the Stereo checkbox is toggled), without touching
        trim markers/zoom."""
        if not self.current_audio_path:
            return
        try:
            data, fs = sf.read(self.current_audio_path, dtype="float32")
            self._wave_data, self._wave_data_stereo = self._decide_channels(data)
        except Exception:
            pass

    def load_waveform(self, path, mode, display_name=None):
        self.wave_mode = mode
        wav_path = path
        if path.lower().endswith(".mp3") and PYDUB_AVAILABLE:
            try:
                sound = AudioSegment.from_file(path)
                wav_path = temp_path("waveform_src.wav")
                sound.export(wav_path, format="wav")
            except Exception:
                self.current_audio_path = None
                self._wave_data = None
                self.wave_canvas.delete("all")
                self.wave_canvas.create_text(
                    self.wave_width // 2, self.wave_height // 2, text="(No preview)", fill=FG_MUTED
                )
                return
        elif not PYDUB_AVAILABLE and path.lower().endswith(".mp3"):
            self.current_audio_path = None
            self._wave_data = None
            self.wave_canvas.delete("all")
            self.wave_canvas.create_text(
                self.wave_width // 2,
                self.wave_height // 2,
                text="(No preview - pydub missing)",
                fill=FG_MUTED,
            )
            return

        self.current_audio_path = wav_path
        self.trim_start_frac = 0.0
        self.trim_end_frac = 1.0
        self.zoom_factor = 1.0
        self.center_frac = 0.5
        self.wave_name_label.config(text=display_name or os.path.basename(path))

        try:
            data, fs = sf.read(wav_path, dtype="float32")
            self._wave_data, self._wave_data_stereo = self._decide_channels(data)
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
        center = self.center_frac if self.wave_mode == "browse" else 0.5
        start = center - self.view_span_frac / 2.0
        start = max(0.0, min(start, 1.0 - self.view_span_frac))
        self.view_start_frac = start

    def frac_to_x(self, frac):
        if self.view_span_frac <= 0:
            return 0
        return (frac - self.view_start_frac) / self.view_span_frac * self.wave_width

    def x_to_frac(self, x):
        return self.view_start_frac + (x / self.wave_width) * self.view_span_frac

    def _on_wave_canvas_resize(self, event=None):
        """The canvas is packed with fill='x' and can end up wider than the
        fixed wave_width used for drawing/marker/zoom math - keep them in
        sync so there's no empty gap on the right, at any window size."""
        new_width = event.width if event else self.wave_canvas.winfo_width()
        if new_width > 10 and new_width != self.wave_width:
            self.wave_width = new_width
            if self._wave_data is not None:
                self._render_wave_at_current_view()

    def render_and_draw_wave(self):
        """Used after zoom changes or a marker drag: re-centers the view on
        the markers (browse mode) or window middle (selected mode), then
        renders."""
        self._update_view_window()
        self._render_wave_at_current_view()

    def _display_data_with_edits(self, data):
        """Returns a copy of the FULL (untrimmed) waveform data with the
        per-sample normalization applied inside the trim region, so the
        preview shows the level this slice will really have in the built
        multisample.

        The old version keyed off a plain Normalize checkbox that, at build
        time, actually normalized the COMBINED file - so the preview showed
        a per-sample result the build never produced. It now follows
        _normalize_per_sample() and stays flat in "Whole file" mode."""
        if data is None or not self._normalize_per_sample():
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
        if self.zoom_label is not None:
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
            return  # not zoomed in - nothing to pan
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
        self.wave_canvas.delete("truncate")
        x_start = self.frac_to_x(self.trim_start_frac)
        x_end = self.frac_to_x(self.trim_end_frac)
        slice_limit = self.compute_slice_limit_seconds()

        if self.wave_mode == "browse":
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

            # Part of the *marked* region that would still get truncated at build time.
            if slice_limit and self.play_duration > 0:
                region_duration = self.play_duration * (self.trim_end_frac - self.trim_start_frac)
                if region_duration > slice_limit > 0:
                    cutoff_within_region = slice_limit / region_duration
                    cut_frac = self.trim_start_frac + cutoff_within_region * (
                        self.trim_end_frac - self.trim_start_frac
                    )
                    self._draw_truncate_overlay(self.frac_to_x(cut_frac), x_end)

            draw_bracket_marker(self.wave_canvas, x_start, self.wave_height, ACCENT_GREEN, "start")
            draw_bracket_marker(self.wave_canvas, x_end, self.wave_height, ACCENT_RED, "end")
        else:
            # "selected" mode: whole-file view, truncation relative to full duration.
            if slice_limit and self.play_duration > slice_limit > 0:
                cut_frac = slice_limit / self.play_duration
                self._draw_truncate_overlay(self.frac_to_x(cut_frac), self.frac_to_x(1.0))

        self.update_duration_label()

    def _draw_truncate_overlay(self, x_cut, x_right):
        """Shows the part of a slice that will be cut off for exceeding the
        per-slice time limit. Thin wrapper over the app-wide helper so the
        Chop view keeps the exact same look as the other waveform views."""
        draw_truncate_overlay(self.wave_canvas, x_cut, x_right, self.wave_height)

    def update_duration_label(self):
        if self.play_duration <= 0:
            self.duration_label.config(text="")
            return
        slice_limit = self.compute_slice_limit_seconds()
        if self.wave_mode == "browse":
            region_duration = self.play_duration * (self.trim_end_frac - self.trim_start_frac)
            text = f"Selection: {region_duration:.2f}s"
            if slice_limit and region_duration > slice_limit:
                text += f"  (truncated to {slice_limit:.2f}s)"
                self.duration_label.config(text=text, fg=ACCENT_ORANGE)
            else:
                self.duration_label.config(text=text, fg=ACCENT_BLUE)
        else:
            rate = self.rate_var.get()
            ch_label = "Stereo" if self.stereo_var.get() else "Mono"
            text = f"Length: {self.play_duration:.2f}s   \u2022   Preview @ {rate}Hz/{ch_label}"
            if slice_limit and self.play_duration > slice_limit:
                text += f"  (truncated to {slice_limit:.2f}s)"
                self.duration_label.config(text=text, fg=ACCENT_ORANGE)
            else:
                self.duration_label.config(text=text, fg=ACCENT_BLUE)

    def on_wave_press(self, event):
        if self.wave_mode != "browse":
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
        if not self.drag_target or self.wave_mode != "browse":
            return
        frac = max(0.0, min(self.x_to_frac(event.x), 1.0))
        if self.drag_target == "start":
            gap = min_trim_fraction(getattr(self, "play_duration", 0))
            self.trim_start_frac = min(frac, self.trim_end_frac - gap)
        elif self.drag_target == "end":
            gap = min_trim_fraction(getattr(self, "play_duration", 0))
            self.trim_end_frac = max(frac, self.trim_start_frac + gap)
        # Cheap: only redraw markers/overlays while dragging. The waveform
        # image itself (which may re-center when zoomed) is redrawn once the
        # mouse is released, so dragging stays smooth even at high zoom.
        self.redraw_markers()

    def on_wave_release(self, event):
        dragged = self.drag_target
        self.drag_target = None
        if dragged and self.wave_mode == "browse" and self.zoom_factor > 1.0:
            self.center_frac = self.trim_start_frac if dragged == "start" else self.trim_end_frac
            self.render_and_draw_wave()

    def update_playhead(self):
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
            if hasattr(self, "browse_preview_btn"):
                self.browse_preview_btn.text = "\u25b6"
                self.browse_preview_btn._draw()
            self.wave_canvas.delete("playhead")

    def toggle_preview(self):
        """The Preview button sits between the two lists, so it follows
        whichever one last fed the waveform view."""
        if self.is_playing:
            self.stop_preview()
        else:
            self.preview_current()

    def preview_current(self):
        if not self.current_audio_path:
            return
        try:
            sd.stop()

            if self.wave_mode == "selected" and PYDUB_AVAILABLE:
                # Preview at the actual target rate/channels (in-memory, no temp
                # file) so you can hear the quality it will have in the chop.
                rate = self.rate_var.get()
                channels = 2 if self.stereo_var.get() else 1
                audio = AudioSegment.from_file(self.current_audio_path)
                audio = audio.set_frame_rate(rate)
                audio = audio.set_channels(channels)
                samples = np.array(audio.get_array_of_samples()).astype(np.float32)
                max_val = float(1 << (8 * audio.sample_width - 1))
                samples /= max_val
                if channels > 1:
                    samples = samples.reshape((-1, channels))
                if self._normalize_per_sample():
                    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
                    if peak > 0:
                        samples = samples * (0.98 / peak)
                sd.play(samples, rate)
            else:
                data, fs = sf.read(self.current_audio_path, dtype="float32")
                if data.ndim > 1 and not self.stereo_var.get():
                    data = data.mean(axis=1)
                n = len(data)
                start_i = int(self.trim_start_frac * n)
                end_i = int(self.trim_end_frac * n)
                segment = data[start_i:end_i]
                self._audible_seconds = None
                segment = apply_micro_fade(segment, fs, fade_ms=2)
                if self._normalize_per_sample():
                    peak = float(np.max(np.abs(segment))) if segment.size else 0.0
                    if peak > 0:
                        segment = segment * (0.98 / peak)
                sd.play(segment, fs)

            self.is_playing = True
            if hasattr(self, "browse_preview_btn"):
                self.browse_preview_btn.text = "\u25a0"
                self.browse_preview_btn._draw()
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
        if hasattr(self, "browse_preview_btn"):
            self.browse_preview_btn.text = "\u25b6"
            self.browse_preview_btn._draw()
        self.wave_canvas.delete("playhead")

    # ----- Build -----

    def on_build(self):
        if not PYDUB_AVAILABLE:
            dark_showerror(
                "pydub missing", "The Chop feature requires pydub + ffmpeg.", parent=self
            )
            return
        if not self.selected_files:
            dark_showwarning("No Files", "Please add at least one sample first.", parent=self)
            return

        num_slices = self.slices_var.get()
        rate = self.rate_var.get()
        channels = 2 if self.stereo_var.get() else 1

        if len(self.selected_files) > num_slices:
            proceed = dark_askyesno(
                "Too Many Files",
                f"You selected {len(self.selected_files)} files but only {num_slices} slices "
                f"fit in one output file. Only the first {num_slices} will be used. Continue?",
                parent=self,
            )
            if not proceed:
                return

        files_to_use = self.selected_files[:num_slices]

        # Building can take a noticeable moment - show a busy cursor so it
        # doesn't look like the app froze.
        try:
            self.config(cursor="watch")
            self.update_idletasks()
        except Exception:
            pass

        try:
            combined = build_chop_file(
                files_to_use, rate, channels, num_slices, normalize_mode=self._normalize_mode()
            )

            unique_id = uuid.uuid4().hex[:8]
            out_name = f"chop_{num_slices}slices_{rate}Hz_{'stereo' if channels == 2 else 'mono'}_{unique_id}.wav"
            out_path = temp_path(out_name)
            combined.export(out_path, format="wav")
        except Exception as e:
            import traceback

            traceback.print_exc()
            dark_showerror(
                "Chop Error", f"An error occurred while building the chop sample:\n{e}", parent=self
            )
            return
        finally:
            try:
                self.config(cursor="")
            except Exception:
                pass

        self.result_path = out_path
        self.lift()
        self.focus_force()
        self.attributes("-topmost", True)
        padded_note = ""
        if len(files_to_use) < num_slices:
            padded_note = (
                f" ({num_slices - len(files_to_use)} remaining slice(s) filled with silence)"
            )
        dark_showinfo(
            "Chop Complete",
            f"Multisample created from {len(files_to_use)} file(s), "
            f"{num_slices} slices at {rate}Hz.{padded_note}",
            parent=self,
        )
        self.attributes("-topmost", False)
        self.destroy()

    def on_cancel(self):
        self.stop_preview()
        self.result_path = None
        self.destroy()

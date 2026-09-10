"""P6ManagerApp: the main application class."""

import contextlib
import copy
import os
import queue
import shutil
import threading
import time
import time as _time
import tkinter as tk
import uuid
import wave

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import soundfile as sf
except ImportError:
    sf = None

from pyp6 import APP_VERSION
from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
    BTN_BLUE,
    BTN_GREEN,
    BTN_ORANGE,
    BTN_RED,
    FG_MUTED,
    FG_TEXT,
    WAVE_BG,
    WAVE_COLOR,
)
from pyp6.audio.conversion import compute_export_ready_path, pitch_speed_factor
from pyp6.audio.info import (
    check_duration_warning,
    get_wav_info,
    get_wav_sample_width,
)
from pyp6.audio.playback import AUDIO_AVAILABLE
from pyp6.config import (
    add_recent_preset,
    is_preset_folder,
    load_last_import_root,
    load_recent_presets,
    read_preset_manifest,
    resource_path,
    save_last_import_root,
    verify_preset_folder,
    write_preset_manifest,
)
from pyp6.constants import (
    APP_NAME,
    APP_SUBTITLE,
    BANKS,
    MAIN_MIN_H,
    MAIN_MIN_W,
    MAX_UNDO_STEPS,
    MAX_UPLOAD_BYTES,
    PADS,
    PRESET_FORMAT_VERSION,
    PRM_TEMPLATES,
    TEMP_DIR,
    UI_FAMILY,
    WAVETABLE_DIR,
)
from pyp6.model.sample_slot import SampleSlot
from pyp6.synth.engine import render_prm
from pyp6.theme import blend_colors, readable_on
from pyp6.ui.dialogs_common import (
    add_tooltip,
    dark_askyesno,
    dark_showerror,
    dark_showwarning,
    ensure_dark_treeview_style,
    style_checkbutton,
    style_label,
)
from pyp6.ui.waveform import draw_truncate_overlay, draw_waveform_on_canvas
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel, RoundedScrollbar

# These are set from __main__.py before the app is constructed.
DEBUG_STARTUP = False


def _log_timing(label):  # replaced by __main__
    pass


DND_AVAILABLE = False
DND_FILES = None
PYP6_LOGO_PNG = ""


class P6ManagerApp:
    def __init__(self, root):
        import pyp6._about_helpers as _ah

        _ah._DND_APP = self  # so dnd_status_text() can report the live registration state
        self.root = root
        self.root.title(f"{APP_NAME} {APP_SUBTITLE} {APP_VERSION}")
        self.root.configure(bg=BG_DARK)
        self.root.resizable(True, True)
        self.root.bind_all("<Control-z>", lambda e: self.undo())
        self.root.bind_all("<Control-Shift-Z>", lambda e: self.redo())
        self.root.bind_all("<Control-y>", lambda e: self.redo())
        self.root.minsize(MAIN_MIN_W, MAIN_MIN_H)
        self.root.geometry(f"{MAIN_MIN_W}x{MAIN_MIN_H}")
        # Use a fast, always-safe placeholder immediately so the window
        # appears right away - the real import_root (which may involve
        # scanning /run/media, /media, etc. and can hang for several
        # seconds on Linux if a stale automount entry is present) is
        # resolved in the background and applied once ready.
        self.import_root = os.path.expanduser("~")
        self.current_bank = tk.StringVar(value=BANKS[0])
        self.slots = {b: {p: None for p in PADS} for b in BANKS}
        self._undo_stack = []
        self._redo_stack = []
        self._active_bank = None  # which bank's state is currently loaded into pad_widgets
        self._currently_playing_pad = None  # which pad's waveform is shown in the main view

        # Status bar - packed FIRST with side="bottom" so it reliably keeps
        # its spot at the very bottom of the window regardless of how the
        # rest of the layout fills/expands.
        self._status_clear_job = None

        top = tk.Frame(root, padx=14, pady=14, bg=BG_DARK)
        top.pack(fill="x")
        bank_lbl = tk.Label(top, text="Bank:")
        style_label(bank_lbl, font=(UI_FAMILY, 11, "bold"))
        bank_lbl.pack(side="left")
        bank_menu = RoundedDropdown(
            top,
            self.current_bank,
            BANKS,
            command=self.switch_bank,
            parent_bg=BG_DARK,
            width=70,
            height=30,
            value_color_fn=self._bank_dropdown_color,
            entry_builder=self._build_bank_menu_entry,
        )
        bank_menu.pack(side="left", padx=8)
        add_tooltip(
            bank_menu,
            "Switches the 6 pads below to another bank (A-H). Each bank keeps its "
            "own pads and settings; banks that already contain samples are shown "
            "in blue. Hover the current bank in the list for Copy To / Move To.",
        )

        # One Force Mono flag PER BANK, not a single global one - a single
        # shared flag can't be expressed correctly once presets can hold a
        # different mono/stereo intent per bank (e.g. bank A always mono,
        # bank C always stereo). The checkbox below always shows/controls
        # whichever bank is currently active, and is re-pointed at the
        # right BooleanVar on every bank switch.
        self.force_mono_vars = {bank: tk.BooleanVar(value=False) for bank in BANKS}
        self.force_mono_cb = tk.Checkbutton(
            top,
            text="Force Mono (this bank)",
            variable=self.force_mono_vars[self.current_bank.get()],
            command=self.on_force_mono_changed,
        )
        style_checkbutton(self.force_mono_cb)
        self.force_mono_cb.pack(side="left", padx=(4, 0))
        add_tooltip(
            self.force_mono_cb,
            "Exports every pad of the CURRENT bank as mono - roughly halves the "
            "size on the device. Stored per bank, so other banks keep their own "
            "setting.",
        )

        self.path_label = tk.Label(top, text=f"IMPORT Path: {self.import_root}")
        style_label(self.path_label, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self.path_label.pack(side="left", padx=20)

        settings_btn = RoundedButton(
            top,
            text="\u2699",
            command=self.open_settings,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=36,
            height=30,
            font=(UI_FAMILY, 13, "bold"),
        )
        settings_btn.pack(side="right", padx=4)
        add_tooltip(
            settings_btn,
            "Settings: IMPORT folder, theme, tooltips, ffmpeg/ffprobe paths, "
            "defaults and temporary files.",
        )

        self._audio_out_lbl = tk.Label(top, text=self._audio_out_text())
        style_label(self._audio_out_lbl, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self._audio_out_lbl.pack(side="right", padx=(0, 8))
        add_tooltip(self._audio_out_lbl, "Active audio output device")

        self.redo_btn = RoundedButton(
            top,
            text="\u21b7",
            command=self.redo,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=36,
            height=30,
            font=(UI_FAMILY, 13, "bold"),
            state="disabled",
        )
        self.redo_btn.pack(side="right", padx=(0, 4))
        add_tooltip(
            self.redo_btn, "Redo the change you just undid.\nShortcut: Ctrl+Shift+Z or Ctrl+Y"
        )
        self.undo_btn = RoundedButton(
            top,
            text="\u21b6",
            command=self.undo,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=36,
            height=30,
            font=(UI_FAMILY, 13, "bold"),
            state="disabled",
        )
        self.undo_btn.pack(side="right", padx=(4, 0))
        add_tooltip(
            self.undo_btn,
            "Undo the last pad change (load, remove, swap, apply edit, clear "
            "bank, load preset ...).\nShortcut: Ctrl+Z",
        )

        preset_btn = RoundedButton(
            top,
            text="Preset \u25be",
            command=self.open_preset_menu,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
            height=30,
            font=(UI_FAMILY, 9, "bold"),
        )
        preset_btn.pack(side="right", padx=4)
        self.preset_btn = preset_btn
        add_tooltip(
            preset_btn,
            "Save or load presets, or reopen a recent one. A preset stores the "
            "selected banks including their samples, so it stays usable even "
            "after the temp folder is cleared.",
        )

        self.pad_container = tk.Frame(root, padx=14, bg=BG_DARK)
        self.pad_container.pack(fill="x", pady=(6, 0))
        self.pad_container.grid_columnconfigure((0, 1, 2), weight=1)
        self.pad_widgets = {}
        _log_timing("  before creating 6 pad widgets")
        for pad in PADS:
            self.pad_widgets[pad] = SampleSlot(self.pad_container, pad, self)
        _log_timing("  after creating 6 pad widgets")

        if DND_AVAILABLE:
            self._last_dnd_hover_pad = None
            self._last_drop_time = 0.0
            self.root.bind("<Map>", self._setup_dnd_targets, add="+")

        storage_outer = tk.Frame(root, padx=14, bg=BG_DARK)
        storage_outer.pack(fill="x", side="top", pady=(6, 14))
        self.storage_panel = RoundedPanel(
            storage_outer,
            title="Storage (loaded samples)",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        self.storage_panel.pack(fill="x")

        storage_row = tk.Frame(self.storage_panel.body, bg=BG_PANEL)
        storage_row.pack(fill="x")

        bank_col = tk.Frame(storage_row, bg=BG_PANEL)
        bank_col.pack(side="left", padx=(0, 40))
        bank_col_title = tk.Label(bank_col, text="Current Bank")
        style_label(bank_col_title, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        bank_col_title.pack(anchor="w")
        self.bank_size_label = tk.Label(bank_col, text="0.00 MB")
        style_label(self.bank_size_label, bg=BG_PANEL, fg=FG_TEXT, font=(UI_FAMILY, 15, "bold"))
        self.bank_size_label.pack(anchor="w")

        total_col = tk.Frame(storage_row, bg=BG_PANEL)
        total_col.pack(side="left")
        total_col_title = tk.Label(total_col, text="All Banks (total)")
        style_label(total_col_title, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8, "bold"))
        total_col_title.pack(anchor="w")
        self.total_size_label = tk.Label(total_col, text="0.00 MB")
        style_label(self.total_size_label, bg=BG_PANEL, fg=FG_TEXT, font=(UI_FAMILY, 15, "bold"))
        self.total_size_label.pack(anchor="w")

        hint_col = tk.Frame(storage_row, bg=BG_PANEL)
        hint_col.pack(side="left", padx=(30, 0), fill="both", expand=True)

        self.status_label = tk.Label(hint_col, text="", anchor="w", justify="left")
        style_label(self.status_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 9, "bold"))
        self.status_label.pack(anchor="w", fill="x")

        ensure_dark_treeview_style()
        warn_frame = tk.Frame(hint_col, bg=BG_PANEL)
        warn_frame.pack(fill="both", expand=True, pady=(4, 0))
        self.warn_scrollbar = RoundedScrollbar(
            warn_frame, orient="vertical", parent_bg=BG_PANEL, auto_hide=False
        )
        self.warn_spacer = tk.Frame(
            warn_frame, bg=BG_PANEL, width=RoundedScrollbar.THICKNESS, height=1
        )
        self.warn_spacer.pack_propagate(False)
        self.warn_spacer.pack(side="right", fill="y", padx=(3, 0))
        self.warnings_text = tk.Text(
            warn_frame,
            height=3,
            wrap="word",
            bg=BG_PANEL,
            fg=FG_TEXT,
            relief="flat",
            bd=0,
            font=(UI_FAMILY, 8),
            highlightthickness=0,
            yscrollcommand=self._autohide_warn_scrollbar,
            state="disabled",
            cursor="arrow",
        )
        self.warnings_text.tag_configure(
            "storage", foreground=ACCENT_RED, font=(UI_FAMILY, 9, "bold")
        )
        self.warnings_text.tag_configure("padwarn", foreground=ACCENT_ORANGE, font=(UI_FAMILY, 8))
        self.warnings_text.pack(side="left", fill="both", expand=True)
        self.warn_scrollbar.command = self.warnings_text.yview
        self._storage_hint_text = ""
        self._pad_warnings_text = ""

        # ----- playback waveform (reacts to Play/Preview on any pad) -----
        wave_header = tk.Frame(self.storage_panel.body, bg=BG_PANEL)
        wave_header.pack(fill="x", pady=(10, 0))
        self.main_wave_name_label = tk.Label(wave_header, text="No sample playing")
        style_label(self.main_wave_name_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self.main_wave_name_label.pack(side="left")
        self.main_wave_duration_label = tk.Label(wave_header, text="")
        style_label(
            self.main_wave_duration_label, bg=BG_PANEL, fg=ACCENT_BLUE, font=(UI_FAMILY, 9, "bold")
        )
        self.main_wave_duration_label.pack(side="right")

        self.main_wave_width = 880
        self.main_wave_height = 99
        self.main_wave_canvas = tk.Canvas(
            self.storage_panel.body,
            bg=WAVE_BG,
            width=self.main_wave_width,
            height=self.main_wave_height,
            highlightthickness=0,
        )
        self.main_wave_canvas.pack(fill="x", pady=(4, 0))
        self.main_wave_canvas.bind("<Configure>", self._render_main_waveform)
        self.main_wave_canvas.bind("<Button-1>", self._on_main_wave_click)
        add_tooltip(
            self.main_wave_canvas,
            "Click to play from that point. On a wavetable the click jumps "
            "to the start of the zone you clicked in.",
        )
        self.main_wave_data = None
        self.main_wave_data_stereo = None
        self.main_wave_fs = None
        self.main_wave_duration = 0.0
        self.main_wave_max_seconds = None
        self.main_wave_is_playing = False
        self.main_wave_zones = None
        self._wave_view_pad = None
        self.main_wave_play_start_time = None
        self._main_wave_play_id = 0

        bottom = tk.Frame(root, padx=14, bg=BG_DARK)
        bottom.pack(fill="x", side="top", pady=(0, 14))
        copy_all_btn = RoundedButton(
            bottom,
            text="Banks \u2192 P6",
            command=self.open_copy_banks_dialog,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=120,
        )
        copy_all_btn.pack(side="left", padx=4)
        add_tooltip(
            copy_all_btn,
            "Writes the banks you pick to the P-6: each pad's sample is converted "
            "to its rate/pitch/mono settings and copied to "
            "IMPORT/BANK_x/PAD_n/ on the device, replacing whatever was there.",
        )
        import_bank_btn = RoundedButton(
            bottom,
            text="P6 \u2192 Bank",
            command=self.open_import_bank_dialog,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=120,
        )
        import_bank_btn.pack(side="left", padx=4)
        add_tooltip(
            import_bank_btn,
            "The other direction: guides you through the P-6's own export "
            "procedure and loads the resulting EXPORT folder onto the currently "
            "active bank. Rate, pitch and mono come in at their defaults.",
        )
        clear_btn = RoundedButton(
            bottom,
            text="Bank Clear",
            command=self.open_clear_banks_dialog,
            bg=BTN_ORANGE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=110,
        )
        clear_btn.pack(side="left", padx=4)
        add_tooltip(
            clear_btn,
            "Pick which banks to empty (the active one is preselected). Only the "
            "pads in the app are cleared - no files on disk or on the device are "
            "touched. Can be undone with Ctrl+Z.",
        )
        wipe_btn = RoundedButton(
            bottom,
            text="Wipe P6 IMPORT Folder",
            command=self.wipe_import_folder,
            bg=BTN_RED,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=180,
        )
        wipe_btn.pack(side="left", padx=(28, 4))
        add_tooltip(
            wipe_btn,
            "CAUTION: permanently deletes every sample file in the P-6 IMPORT "
            "folder, across all banks. Cannot be undone. Your pads in the app "
            "stay as they are - only the device-side copies are removed.",
        )

        self.build_pad_slots(self.current_bank.get())
        self.prune_orphaned_wavetables()
        _log_timing("build_pad_slots done, scheduling async import-root resolution")

        self._load_logo()

        self.root.after(0, self._resolve_import_root_async)

    def _load_logo(self):
        """Shows the logo in the bottom-right corner, floating on top of the
        packed layout via place()."""
        full_img = None
        try:
            logo_path = resource_path("pyp6logo.png")
            if os.path.exists(logo_path):
                full_img = tk.PhotoImage(file=logo_path)
        except Exception as e:
            print(f"Could not load pyp6logo.png, using the built-in logo: {e}")
        if full_img is None:
            try:
                full_img = tk.PhotoImage(data=PYP6_LOGO_PNG)
            except Exception as e:
                print(f"Could not build the logo: {e}")
                return
        try:
            self._logo_img = full_img.subsample(2, 2)  # ~half size
            logo_label = tk.Label(
                self.root, image=self._logo_img, bg=BG_DARK, bd=0, highlightthickness=0
            )
            logo_label.place(relx=1.0, rely=1.0, anchor="se", x=-10, y=-10)
        except Exception as e:
            print(f"Could not place the logo: {e}")

    def _resolve_import_root_async(self):
        result_queue = queue.Queue()

        def worker():
            t0 = _time.perf_counter()
            resolved = load_last_import_root()
            elapsed = _time.perf_counter() - t0
            if DEBUG_STARTUP:
                print(f"[startup]   background import-root resolution took {elapsed:.3f}s")
            result_queue.put(resolved)

        threading.Thread(target=worker, daemon=True).start()

        def poll():
            try:
                resolved = result_queue.get_nowait()
            except queue.Empty:
                self.root.after(50, poll)
                return
            self._apply_resolved_import_root(resolved)

        self.root.after(50, poll)

    def _apply_resolved_import_root(self, resolved):
        self.import_root = resolved
        if hasattr(self, "path_label"):
            self.path_label.config(text=f"IMPORT Path: {self.import_root}")

    def show_playback_waveform(
        self, samples, fs, name, max_seconds=None, source_path=None, zones=None, offset_frac=0.0
    ):
        if not hasattr(self, "main_wave_canvas"):
            return
        if samples is None or fs is None or len(samples) == 0:
            return
        if samples.ndim > 1 and samples.shape[1] >= 2:
            self.main_wave_data_stereo = samples
            self.main_wave_data = samples.mean(axis=1)
        else:
            self.main_wave_data_stereo = None
            self.main_wave_data = samples.reshape(-1) if samples.ndim > 1 else samples
        self.main_wave_fs = fs
        self.main_wave_duration = len(samples) / float(fs)
        self.main_wave_max_seconds = max_seconds
        self.main_wave_source_path = source_path
        self.main_wave_zones = zones
        self.main_wave_name_label.config(text=name)
        if zones:
            count = len(zones["families"])
            self.main_wave_duration_label.config(
                text=f"{count} zone{'' if count == 1 else 's'} \u00b7 "
                f"START 0-{sum(zones['counts']) - 1}"
            )
        self._render_main_waveform()
        self._start_main_playhead(offset_frac)

    def stop_and_refresh_waveform_for(self, filepath, max_seconds, pitch_cents=0):
        self.stop_playback_waveform()
        if (
            filepath
            and getattr(self, "main_wave_source_path", None) == filepath
            and hasattr(self, "main_wave_canvas")
        ):
            try:
                orig_duration, _, _ = get_wav_info(filepath)
                if pitch_cents:
                    orig_duration = orig_duration / pitch_speed_factor(pitch_cents)
                self.main_wave_duration = orig_duration
            except Exception:
                pass
            self.main_wave_max_seconds = max_seconds
            self._redraw_main_truncate()

    def _render_main_waveform(self, event=None):
        self.main_wave_canvas.delete("all")
        width_px = max(self.main_wave_canvas.winfo_width(), self.main_wave_width)
        self.main_wave_render_width = width_px
        if getattr(self, "main_wave_zones", None):
            self._render_wavetable_zones(width_px)
            return
        if getattr(self, "main_wave_data", None) is None:
            return
        if getattr(self, "main_wave_data_stereo", None) is not None:
            half_h = self.main_wave_height / 2.0
            draw_waveform_on_canvas(
                self.main_wave_canvas,
                self.main_wave_data_stereo[:, 0],
                0.0,
                1.0,
                width_px,
                half_h,
                tag="waveform",
                y_offset=0,
                clear=True,
            )
            draw_waveform_on_canvas(
                self.main_wave_canvas,
                self.main_wave_data_stereo[:, 1],
                0.0,
                1.0,
                width_px,
                half_h,
                tag="waveform",
                y_offset=half_h,
                clear=False,
            )
            self.main_wave_canvas.create_line(
                0, half_h, width_px, half_h, fill=BORDER_COLOR, width=1, tags="waveform"
            )
        else:
            draw_waveform_on_canvas(
                self.main_wave_canvas,
                self.main_wave_data,
                0.0,
                1.0,
                width_px,
                self.main_wave_height,
            )
        self._redraw_main_truncate()

    @staticmethod
    def _ellipsize(font, text, avail):
        if font.measure(text) <= avail:
            return text
        for cut in range(len(text) - 1, 0, -1):
            candidate = text[:cut] + "\u2026"
            if font.measure(candidate) <= avail:
                return candidate
        return ""

    def _render_wavetable_zones(self, width_px):
        import tkinter.font as tkfont

        c = self.main_wave_canvas
        zones = self.main_wave_zones
        families, counts = zones["families"], zones["counts"]
        total = float(sum(counts)) or 1.0
        h = self.main_wave_height
        top, bot = 10, h - 8

        text_col = readable_on(WAVE_COLOR, WAVE_BG, 7.0)
        stripe = blend_colors(WAVE_BG, WAVE_COLOR, 0.12)

        name_font = tkfont.Font(family=UI_FAMILY, size=8)

        widths = [cnt / total * width_px for cnt in counts]
        needed = max(name_font.measure(n) for n in families) + 6
        stagger = len(families) > 1 and needed > min(widths)

        x = 0.0
        pos = 0
        for i, (name, cnt) in enumerate(zip(families, counts)):
            x2 = x + widths[i]
            if i % 2 == 0:
                c.create_rectangle(x, top, x2, bot, fill=stripe, outline="", tags="waveform")
            if i:
                c.create_line(x, top, x, bot, fill=BORDER_COLOR, tags="waveform")

            if stagger:
                y_name = top + 14 if i % 2 == 0 else bot - 22
            else:
                y_name = (top + bot) / 2 - 7
            avail = widths[i] * (2.0 if stagger else 1.0) - 6
            cx = (x + x2) / 2
            c.create_text(
                cx,
                y_name,
                text=self._ellipsize(name_font, name, avail),
                anchor="n",
                fill=text_col,
                font=(UI_FAMILY, 8),
                tags="waveform",
            )
            c.create_text(
                cx,
                y_name + 13,
                text=f"{pos}\u2013{pos + cnt - 1}",
                anchor="n",
                fill=text_col,
                font=(UI_FAMILY, 7),
                tags="waveform",
            )
            pos += cnt
            x = x2

        c.create_rectangle(0, top, width_px, bot, outline=BORDER_COLOR, tags="waveform")

    def _redraw_main_truncate(self):
        self.main_wave_canvas.delete("truncate")
        width_px = getattr(self, "main_wave_render_width", self.main_wave_width)
        duration = self.main_wave_duration
        limit = self.main_wave_max_seconds
        if limit and duration > limit > 0:
            x_cut = (limit / duration) * width_px
            draw_truncate_overlay(self.main_wave_canvas, x_cut, width_px, self.main_wave_height)
            self.main_wave_duration_label.config(
                text=f"Length: {duration:.2f}s   (max {limit:.2f}s)", fg=ACCENT_ORANGE
            )
        else:
            self.main_wave_duration_label.config(text=f"Length: {duration:.2f}s", fg=ACCENT_BLUE)

    def _refresh_playing_pad_button(self):
        if not hasattr(self, "pad_widgets"):
            return
        playing_pad = (
            self._currently_playing_pad if getattr(self, "main_wave_is_playing", False) else None
        )
        for pad, slot in self.pad_widgets.items():
            slot.set_play_button_state(pad == playing_pad)

    def _on_main_wave_click(self, event):
        pad = getattr(self, "_wave_view_pad", None)
        slot = self.pad_widgets.get(pad) if pad else None
        if slot is None or not slot.filepath:
            return
        width = max(1, getattr(self, "main_wave_render_width", self.main_wave_width))
        frac = min(max(event.x / float(width), 0.0), 0.999)

        zones = getattr(self, "main_wave_zones", None)
        if zones:
            total = float(sum(zones["counts"])) or 1.0
            acc = 0
            for count in zones["counts"]:
                if frac < (acc + count) / total:
                    frac = acc / total
                    break
                acc += count
        slot.play_from(frac)

    def show_wavetable_zones(self, pad, zones, name):
        if not hasattr(self, "main_wave_canvas"):
            return
        self.stop_playback_waveform()
        self._currently_playing_pad = None
        self.main_wave_data = None
        self.main_wave_data_stereo = None
        self.main_wave_zones = zones
        self.main_wave_duration = 0.0
        self.main_wave_max_seconds = None
        self.main_wave_source_path = None
        self.main_wave_name_label.config(text=name)
        count = len(zones["families"])
        self.main_wave_duration_label.config(
            text=f"{count} zone{'' if count == 1 else 's'} / {sum(zones['counts'])} segments"
        )
        self.set_active_pad(pad)
        self._render_main_waveform()

    def stop_playback_waveform(self):
        try:
            sd.stop()
        except Exception:
            pass
        self.main_wave_is_playing = False
        self._main_wave_play_id += 1
        if hasattr(self, "main_wave_canvas"):
            self.main_wave_canvas.delete("playhead")
        self._refresh_playing_pad_button()

    def clear_playback_waveform(self):
        self.stop_playback_waveform()
        self._currently_playing_pad = None
        self._wave_view_pad = None
        self.main_wave_zones = None
        if hasattr(self, "pad_widgets"):
            self._clear_all_pad_highlights()
        self.main_wave_data = None
        self.main_wave_data_stereo = None
        self.main_wave_source_path = None
        self.main_wave_duration = 0.0
        self.main_wave_max_seconds = None
        if hasattr(self, "main_wave_canvas"):
            self.main_wave_canvas.delete("all")
        if hasattr(self, "main_wave_name_label"):
            self.main_wave_name_label.config(text="No sample playing")
        if hasattr(self, "main_wave_duration_label"):
            self.main_wave_duration_label.config(text="")

    def _start_main_playhead(self, offset_frac=0.0):
        self._main_wave_play_id += 1
        my_id = self._main_wave_play_id
        self.main_wave_is_playing = True
        self.main_wave_play_start_time = time.time() - offset_frac * self.main_wave_duration
        self._refresh_playing_pad_button()
        self._update_main_playhead(my_id)

    def _update_main_playhead(self, play_id):
        if play_id != self._main_wave_play_id or not self.main_wave_is_playing:
            return
        elapsed = time.time() - self.main_wave_play_start_time
        duration = self.main_wave_duration
        frac = min(elapsed / duration, 1.0) if duration > 0 else 1.0
        width_px = getattr(self, "main_wave_render_width", self.main_wave_width)
        x = frac * width_px
        self.main_wave_canvas.delete("playhead")
        if frac < 1.0:
            self.main_wave_canvas.create_line(
                x, 0, x, self.main_wave_height, fill=ACCENT_BLUE, width=2, tags="playhead"
            )
            self.root.after(30, lambda: self._update_main_playhead(play_id))
        else:
            self.main_wave_is_playing = False
            self._refresh_playing_pad_button()

    def _audio_out_text(self):
        """Return a short string describing the active audio output device."""
        try:
            import sounddevice as _sd

            import pyp6.audio.playback as _pb

            idx = _pb.SD_OUTPUT_DEVICE
            if idx is None:
                return "\u266a system default"
            name = _sd.query_devices(idx)["name"]
            return f"\u266a {name}"
        except Exception:
            return ""

    def open_settings(self):
        from pyp6.ui.dialogs.settings import SettingsDialog

        dialog = SettingsDialog(self.root, self)
        self.root.wait_window(dialog)
        self._audio_out_lbl.config(text=self._audio_out_text())

    def open_preset_menu(self):
        menu = tk.Menu(
            self.root,
            tearoff=0,
            bg=BG_PANEL,
            fg=FG_TEXT,
            activebackground=ACCENT_BLUE,
            activeforeground="#FFFFFF",
            font=(UI_FAMILY, 9),
        )
        menu.add_command(label="Save Preset...", command=self.open_save_preset_dialog)
        menu.add_command(label="Load Preset...", command=self.open_load_preset_dialog)

        recents = [p for p in load_recent_presets() if is_preset_folder(p)]
        if recents:
            menu.add_separator()
            recent_menu = tk.Menu(
                menu,
                tearoff=0,
                bg=BG_PANEL,
                fg=FG_TEXT,
                activebackground=ACCENT_BLUE,
                activeforeground="#FFFFFF",
                font=(UI_FAMILY, 9),
            )
            for path in recents:
                name = os.path.basename(path.rstrip(os.sep)) or path
                recent_menu.add_command(
                    label=name, command=lambda p=path: self.open_load_preset_dialog(preselect=p)
                )
            menu.add_cascade(label="Recent", menu=recent_menu)

        x = self.preset_btn.winfo_rootx()
        y = self.preset_btn.winfo_rooty() + self.preset_btn.winfo_height()
        menu.bind("<Escape>", lambda e: menu.unpost())
        menu.tk_popup(x, y)

    def open_save_preset_dialog(self):
        from pyp6.ui.dialogs.preset import PresetSaveDialog

        initial_dir = (
            os.path.dirname(load_recent_presets()[0])
            if load_recent_presets()
            else os.path.expanduser("~")
        )
        dialog = PresetSaveDialog(self.root, self, initial_dir=initial_dir)
        self.root.wait_window(dialog)
        if dialog.result_dir:
            self.show_status(f"Preset saved: {os.path.basename(dialog.result_dir)}")

    def open_load_preset_dialog(self, preselect=None):
        from pyp6.ui.dialogs.preset import PresetLoadDialog

        initial_dir = (
            os.path.dirname(preselect)
            if preselect
            else (
                os.path.dirname(load_recent_presets()[0])
                if load_recent_presets()
                else os.path.expanduser("~")
            )
        )
        dialog = PresetLoadDialog(
            self.root, self, initial_dir=initial_dir, preselect_path=preselect
        )
        self.root.wait_window(dialog)
        if dialog.result_dir and dialog.result_banks:
            self.load_preset_from_folder(
                dialog.result_dir,
                dialog.result_banks,
                target_bank_override=dialog.result_target_override,
            )

    def show_progress(self, message):
        if self._status_clear_job:
            self.root.after_cancel(self._status_clear_job)
            self._status_clear_job = None
        self.status_label.config(text=message, fg=FG_MUTED)
        self.root.update_idletasks()

    def show_status(self, message, kind="success", duration_ms=5000):
        colors = {
            "success": ACCENT_GREEN,
            "info": FG_MUTED,
            "warning": ACCENT_ORANGE,
        }
        self.status_label.config(text=message, fg=colors.get(kind, FG_MUTED))
        if self._status_clear_job:
            self.root.after_cancel(self._status_clear_job)
        self._status_clear_job = self.root.after(duration_ms, self._clear_status)

    def _clear_status(self):
        self.status_label.config(text="")
        self._status_clear_job = None

    def _pad_at_screen_pos(self, x_root, y_root):
        for pad, slot in self.pad_widgets.items():
            panel = slot.panel
            px, py = panel.winfo_rootx(), panel.winfo_rooty()
            pw, ph = panel.winfo_width(), panel.winfo_height()
            if px <= x_root <= px + pw and py <= y_root <= py + ph:
                return pad
        return None

    def _pad_idle_color(self, pad):
        if pad == getattr(self, "_wave_view_pad", None):
            return ACCENT_BLUE, 3
        return BORDER_LIGHT, 1

    def _clear_all_pad_highlights(self):
        for pad, slot in self.pad_widgets.items():
            color, width = self._pad_idle_color(pad)
            slot.panel.set_border_color(color, width=width)

    def set_active_pad(self, pad):
        self._wave_view_pad = pad
        if hasattr(self, "pad_widgets"):
            self._clear_all_pad_highlights()

    def highlight_playing_pad(self, pad):
        self._currently_playing_pad = pad
        self._wave_view_pad = pad
        self._clear_all_pad_highlights()
        self._refresh_playing_pad_button()

    def swap_pads(self, pad_a, pad_b):
        if pad_a == pad_b:
            return
        self._push_undo()
        state_a = self.pad_widgets[pad_a].get_state()
        state_b = self.pad_widgets[pad_b].get_state()
        self.pad_widgets[pad_a].apply_state(state_b)
        self.pad_widgets[pad_b].apply_state(state_a)
        playing = getattr(self, "_currently_playing_pad", None)
        if playing == pad_a:
            self._currently_playing_pad = pad_b
        elif playing == pad_b:
            self._currently_playing_pad = pad_a
        self._clear_all_pad_highlights()
        self._refresh_playing_pad_button()
        self.update_storage_display()
        self.update_pad_warnings()
        self.show_status(f"Swapped PAD_{pad_a} and PAD_{pad_b}.")

    def _setup_dnd_targets(self, event=None):
        if getattr(self, "_dnd_targets_ready", False):
            return
        self._dnd_registered = []

        def register(widget, label):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<DropPosition>>", self._on_pad_drag_position)
                widget.dnd_bind("<<DragLeave>>", self._on_pad_drag_leave)
                widget.dnd_bind("<<Drop>>", self._on_pad_drop)
                self._dnd_registered.append(label)
                _log_timing(f"  drop target registered on {label}")
                return True
            except Exception as e:
                print(f"Drop target registration on {label} failed: {e}")
                return False

        register(self.pad_container, "pad container")
        register(self.root, "main window")

        if self._dnd_registered:
            self._dnd_targets_ready = True
        else:
            print(
                "Drag & drop: no drop target could be registered - "
                "dropping files onto pads will not work this session."
            )

    def _on_pad_drag_position(self, event):
        if not getattr(self, "_dnd_position_seen", False):
            self._dnd_position_seen = True
            _log_timing("  first <<DropPosition>> received - XDND is reaching the app")
        hovered = self._pad_at_screen_pos(event.x_root, event.y_root)
        self._last_dnd_hover_pad = hovered
        for pad, slot in self.pad_widgets.items():
            if pad == hovered:
                slot.panel.set_border_color(ACCENT_GREEN, width=3)
            else:
                color, width = self._pad_idle_color(pad)
                slot.panel.set_border_color(color, width=width)
        return event.action

    def _on_pad_drag_leave(self, event):
        self._clear_all_pad_highlights()
        self._last_dnd_hover_pad = None
        return event.action

    def _on_pad_drop(self, event):
        _log_timing("  <<Drop>> received")
        now = time.time()
        if now - getattr(self, "_last_drop_time", 0.0) < 0.3:
            return "break"
        self._last_drop_time = now
        self._clear_all_pad_highlights()
        pad = self._pad_at_screen_pos(event.x_root, event.y_root)
        if pad is None:
            pad = getattr(self, "_last_dnd_hover_pad", None)
        self._last_dnd_hover_pad = None
        if pad is None:
            dark_showwarning(
                "Drop Not Recognized",
                "Couldn't tell which pad that was dropped on - try dropping "
                "more toward the center of a pad.",
            )
            return "break"
        try:
            paths = self.root.tk.splitlist(event.data)
        except Exception:
            paths = [event.data]
        audio_paths = [p for p in paths if p.lower().endswith((".wav", ".mp3"))]
        if not audio_paths:
            dark_showwarning(
                "No Audio Files", "The dropped item(s) don't look like .wav or .mp3 files."
            )
            return "break"

        self.stop_playback_waveform()
        self._push_undo()
        for offset, path in enumerate(audio_paths):
            target_num = pad + offset
            if target_num > len(PADS):
                break
            self.pad_widgets[target_num].set_file(path)
        return "break"

    def bank_force_mono(self, bank):
        var = self.force_mono_vars.get(bank)
        return bool(var.get()) if var else False

    def _snapshot_state(self):
        self._save_active_bank_state()
        return {
            "slots": copy.deepcopy(self.slots),
            "force_mono": {b: v.get() for b, v in self.force_mono_vars.items()},
        }

    def _push_undo(self):
        snapshot = self._snapshot_state()
        self._undo_stack.append(snapshot)
        if len(self._undo_stack) > MAX_UNDO_STEPS:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_redo_buttons()

    def _restore_snapshot(self, snapshot):
        self.clear_playback_waveform()
        self.slots = copy.deepcopy(snapshot["slots"])
        for bank, value in snapshot["force_mono"].items():
            if bank in self.force_mono_vars:
                self.force_mono_vars[bank].set(value)
        self.build_pad_slots(self.current_bank.get())
        self.update_storage_display()
        self.update_pad_warnings()

    def undo(self):
        if not self._undo_stack:
            return
        self._redo_stack.append(self._snapshot_state())
        if len(self._redo_stack) > MAX_UNDO_STEPS:
            self._redo_stack.pop(0)
        snapshot = self._undo_stack.pop()
        self._restore_snapshot(snapshot)
        self._update_undo_redo_buttons()

    def redo(self):
        if not self._redo_stack:
            return
        self._undo_stack.append(self._snapshot_state())
        if len(self._undo_stack) > MAX_UNDO_STEPS:
            self._undo_stack.pop(0)
        snapshot = self._redo_stack.pop()
        self._restore_snapshot(snapshot)
        self._update_undo_redo_buttons()

    def _update_undo_redo_buttons(self):
        if hasattr(self, "undo_btn"):
            self.undo_btn.config_state("normal" if self._undo_stack else "disabled")
        if hasattr(self, "redo_btn"):
            self.redo_btn.config_state("normal" if self._redo_stack else "disabled")

    def _is_temp_path(self, filepath):
        try:
            abs_fp = os.path.abspath(filepath)
            abs_temp = os.path.abspath(TEMP_DIR)
            return abs_fp == abs_temp or abs_fp.startswith(abs_temp + os.sep)
        except Exception:
            return False

    def prune_orphaned_wavetables(self):
        if self._undo_stack or self._redo_stack:
            return 0
        if not os.path.isdir(WAVETABLE_DIR):
            return 0
        in_use = set()
        for bank in BANKS:
            for pad in PADS:
                state = (self.slots.get(bank) or {}).get(pad)
                if state and state.get("filepath"):
                    in_use.add(os.path.normcase(os.path.abspath(state["filepath"])))
        removed = 0
        try:
            names = os.listdir(WAVETABLE_DIR)
        except Exception as e:
            print(f"Could not read the wavetables folder: {e}")
            return 0
        for name in names:
            if not name.upper().endswith((".WAV", ".PRM")):
                continue
            full = os.path.join(WAVETABLE_DIR, name)
            wav = os.path.splitext(full)[0] + ".WAV"
            if os.path.normcase(os.path.abspath(wav)) in in_use:
                continue
            try:
                os.remove(full)
                removed += 1
            except Exception as e:
                print(f"Could not remove orphaned wavetable {name}: {e}")
        if removed:
            print(f"Removed {removed} orphaned wavetable file(s).")
        return removed

    def clear_pads_referencing_missing_files(self):
        self._save_active_bank_state()
        cleared_count = 0
        for bank in BANKS:
            pad_states = self.slots.get(bank, {})
            for pad in PADS:
                state = pad_states.get(pad)
                if not state or not state.get("filepath"):
                    continue
                filepath = state["filepath"]
                if self._is_temp_path(filepath) and not os.path.exists(filepath):
                    self.slots[bank][pad] = None
                    cleared_count += 1
        self.build_pad_slots(self.current_bank.get())
        self.update_storage_display()
        self.update_pad_warnings()
        return cleared_count

    def bank_has_samples(self, bank):
        for pad in PADS:
            state = self._get_pad_state(bank, pad)
            if state and state.get("filepath"):
                return True
        return False

    def _bank_dropdown_color(self, bank):
        return ACCENT_BLUE if self.bank_has_samples(bank) else None

    def _report_preset_check(self, preset_dir, when):
        try:
            problems, strays = verify_preset_folder(preset_dir)
        except Exception as e:
            print(f"Preset check failed: {e}")
            return True
        if not problems:
            if strays:
                print(f"Preset {preset_dir}: unreferenced files: {', '.join(strays)}")
            return True
        lines = "\n".join(f"\u2022 {p}" for p in problems[:12])
        if len(problems) > 12:
            lines += f"\n\u2022 ...and {len(problems) - 12} more"
        dark_showwarning(
            "Preset Incomplete",
            f"{when}\n\n{lines}\n\nA preset folder is meant to be handed to "
            "someone else, so anything listed here would break it for them.",
        )
        return False

    def save_preset_to_folder(self, target_dir, name, banks_to_save):
        preset_dir = os.path.join(target_dir, name)
        os.makedirs(preset_dir, exist_ok=True)

        existing = read_preset_manifest(preset_dir) or {}
        banks_data = existing.get("banks", {})
        try:
            existing_version = int(existing.get("format_version", 0)) if existing else 0
        except (TypeError, ValueError):
            existing_version = 0

        carried = []
        for bank in sorted(list(banks_data)):
            if bank in banks_to_save:
                continue
            if not os.path.isdir(os.path.join(preset_dir, f"BANK_{bank}")):
                print(f"Preset {name}: dropping BANK_{bank} - its folder is gone.")
                banks_data.pop(bank, None)
            else:
                carried.append(bank)

        self._save_active_bank_state()
        copy_failures = []

        for bank in banks_to_save:
            bank_dir = os.path.join(preset_dir, f"BANK_{bank}")
            staging_dir = os.path.join(preset_dir, f".BANK_{bank}_staging_{uuid.uuid4().hex[:6]}")
            os.makedirs(staging_dir, exist_ok=True)

            pad_entries = {}
            for pad in PADS:
                state = self._get_pad_state(bank, pad)
                if not state or not state.get("filepath") or not os.path.exists(state["filepath"]):
                    pad_entries[str(pad)] = None
                    continue
                src = state["filepath"]
                pad_dir = os.path.join(staging_dir, f"PAD_{pad}")
                os.makedirs(pad_dir, exist_ok=True)
                dest = os.path.join(pad_dir, os.path.basename(src))
                try:
                    shutil.copy2(src, dest)
                    dst_size = os.path.getsize(dest)
                    src_size = os.path.getsize(src)
                    if dst_size != src_size:
                        raise OSError(f"copied {dst_size} of {src_size} bytes")
                    if dest.lower().endswith(".wav"):
                        with contextlib.closing(wave.open(dest, "r")) as _wf:
                            if _wf.getnframes() == 0:
                                raise OSError("copy contains no audio frames")
                except Exception as e:
                    detail = f"{type(e).__name__}: {e or 'file is empty or truncated'}"
                    print(f"Could not copy sample for BANK_{bank}/PAD_{pad}: {detail}  ({src})")
                    copy_failures.append(
                        f"BANK_{bank}/PAD_{pad}: {os.path.basename(src)} - {detail}"
                    )
                    pad_entries[str(pad)] = None
                    continue
                prm_src = self._find_prm_for(src)
                if prm_src:
                    try:
                        shutil.copy2(prm_src, os.path.splitext(dest)[0] + ".PRM")
                    except Exception as e:
                        print(f"Could not copy settings file for BANK_{bank}/PAD_{pad}: {e}")
                rel_path = f"BANK_{bank}/" + os.path.relpath(dest, staging_dir).replace(os.sep, "/")
                pad_entries[str(pad)] = {
                    "filepath": rel_path,
                    "target_rate": state.get("target_rate"),
                    "pitch_cents": state.get("pitch_cents", 0),
                    "mono": state.get("mono", False),
                    "display_name": state.get("display_name") or os.path.basename(src),
                    "wavetable": state.get("wavetable"),
                    "wt_patch": state.get("wt_patch", "Init"),
                    "wt_poly": state.get("wt_poly", False),
                }

            try:
                if os.path.isdir(bank_dir):
                    shutil.rmtree(bank_dir, ignore_errors=True)
                os.rename(staging_dir, bank_dir)
            except Exception as e:
                shutil.rmtree(staging_dir, ignore_errors=True)
                print(f"Could not finalize BANK_{bank} in preset: {e}")
                continue

            banks_data[bank] = {
                "pads": pad_entries,
                "force_mono": self.bank_force_mono(bank),
            }

        manifest = {
            "format_version": PRESET_FORMAT_VERSION,
            "banks": banks_data,
        }
        write_preset_manifest(preset_dir, manifest)
        add_recent_preset(preset_dir)
        if carried and existing_version and existing_version < PRESET_FORMAT_VERSION:
            dark_showwarning(
                "Older Preset Updated",
                f"This preset was written in format version {existing_version}. "
                f"The banks you just saved are now version {PRESET_FORMAT_VERSION}, "
                f"but {', '.join('BANK_' + b for b in carried)} still hold what the "
                "earlier save left behind.\n\nRe-save those banks too if you want "
                "the whole folder consistent.",
            )
        if copy_failures:
            dark_showwarning(
                "Samples Not Saved",
                "These pads could not be copied into the preset and were left "
                "empty:\n\n" + "\n".join(f"\u2022 {f}" for f in copy_failures[:10]),
            )
        self._report_preset_check(preset_dir, "This preset was saved, but:")
        return preset_dir

    def load_preset_from_folder(self, preset_dir, banks_to_load, target_bank_override=None):
        manifest = read_preset_manifest(preset_dir)
        if not manifest:
            dark_showerror("Invalid Preset", "No valid preset.json found in this folder.")
            return False
        try:
            preset_version = int(manifest.get("format_version", 1))
        except (TypeError, ValueError):
            preset_version = 1
        if preset_version > PRESET_FORMAT_VERSION:
            if not dark_askyesno(
                "Newer Preset Format",
                f"This preset was written in format version {preset_version}, "
                f"but this version of {APP_NAME} understands up to "
                f"{PRESET_FORMAT_VERSION}.\n\nAnything it does not recognise "
                "will be ignored. Load it anyway?",
            ):
                return False
        self._report_preset_check(preset_dir, "Loading this preset anyway, but:")
        self._push_undo()

        banks_data = manifest.get("banks", {})
        self._save_active_bank_state()
        self.clear_playback_waveform()
        missing_samples = []

        for bank in banks_to_load:
            bank_entry = banks_data.get(bank)
            if bank_entry is None:
                continue
            pad_entries = bank_entry.get("pads", {})
            target_bank = target_bank_override or bank
            new_slot = {}
            for pad in PADS:
                entry = pad_entries.get(str(pad))
                if not entry:
                    new_slot[pad] = None
                    continue
                rel_path = entry.get("filepath", "")
                abs_path = (
                    os.path.normpath(os.path.join(preset_dir, *rel_path.split("/")))
                    if rel_path
                    else ""
                )
                if not rel_path or not os.path.exists(abs_path):
                    missing_samples.append(f"BANK_{target_bank}/PAD_{pad} (from BANK_{bank})")
                    new_slot[pad] = None
                    continue
                new_slot[pad] = {
                    "filepath": abs_path,
                    "target_rate": entry.get("target_rate") or 44100,
                    "pitch_cents": entry.get("pitch_cents", 0),
                    "mono": entry.get("mono", False),
                    "from_sync": False,
                    "display_name": entry.get("display_name"),
                    "wavetable": entry.get("wavetable"),
                    "wt_patch": entry.get("wt_patch", "Init"),
                    "wt_poly": entry.get("wt_poly", False),
                }
            self.slots[target_bank] = new_slot
            if target_bank in self.force_mono_vars:
                self.force_mono_vars[target_bank].set(bool(bank_entry.get("force_mono", False)))

        self.build_pad_slots(self.current_bank.get())
        self.on_force_mono_changed()
        add_recent_preset(preset_dir)

        if missing_samples:
            dark_showwarning(
                "Some Samples Missing",
                "The following pads reference sample files that could not be found:\n\n"
                + "\n".join(missing_samples),
            )
        return True

    def choose_import_folder(self, parent_window=None):
        from pyp6.ui.dialogs.file import FolderPickerDialog

        parent_window = parent_window or self.root
        initial = self.import_root if os.path.isdir(self.import_root) else os.path.expanduser("~")
        picker = FolderPickerDialog(
            parent_window, initial_dir=initial, title="Select P-6 IMPORT Folder"
        )
        parent_window.wait_window(picker)
        new_path = picker.selected_dir
        if new_path:
            self.import_root = new_path
            self.path_label.config(text=f"IMPORT Path: {self.import_root}")
            save_last_import_root(new_path)

    def build_pad_slots(self, bank):
        for pad in PADS:
            state = self.slots.get(bank, {}).get(pad)
            self.pad_widgets[pad].apply_state(state)
        self._active_bank = bank
        self.update_storage_display()
        self.update_pad_warnings()

    def _get_pad_state(self, bank, pad):
        if bank == self._active_bank:
            return self.pad_widgets[pad].get_state()
        return self.slots.get(bank, {}).get(pad)

    def _save_active_bank_state(self):
        if self._active_bank is None:
            return
        for pad in PADS:
            self.slots[self._active_bank][pad] = self.pad_widgets[pad].get_state()

    def update_pad_warnings(self):
        if not hasattr(self, "warnings_text"):
            return
        bank = self.current_bank.get()
        global_force = self.bank_force_mono(bank)
        messages = []
        for pad in PADS:
            state = self._get_pad_state(bank, pad)
            if not state or not state.get("filepath"):
                continue
            pad_mono = global_force or state.get("mono", False)
            msg = check_duration_warning(
                state["filepath"], state.get("target_rate"), state.get("pitch_cents", 0), pad_mono
            )
            if msg:
                messages.append(f"PAD_{pad}: {msg}")
        self._pad_warnings_text = "\n".join(messages)
        self._refresh_warnings_display()

    def _autohide_warn_scrollbar(self, first, last):
        self.warn_scrollbar.set(first, last)

    def _place_warn_scrollbar(self, needed):
        mapped = self.warn_scrollbar.winfo_ismapped()
        if needed == mapped:
            return
        if needed:
            self.warn_spacer.pack_forget()
            self.warn_scrollbar.pack(side="right", fill="y", padx=(3, 0), before=self.warnings_text)
        else:
            self.warn_scrollbar.pack_forget()
            self.warn_spacer.pack(side="right", fill="y", padx=(3, 0), before=self.warnings_text)

    def _warn_display_lines(self):
        try:
            res = self.warnings_text.count("1.0", "end", "displaylines")
        except tk.TclError:
            return 0
        if isinstance(res, list | tuple):
            res = res[0] if res else 0
        try:
            return int(res or 0)
        except (TypeError, ValueError):
            return 0

    def _update_warn_scrollbar_visibility(self):
        rows = self._warn_display_lines()
        try:
            visible = int(self.warnings_text.cget("height") or 3)
        except (TypeError, ValueError):
            visible = 3
        if rows:
            needed = rows > visible
        else:
            try:
                first, last = self.warnings_text.yview()
                needed = (last - first) < 0.98
            except Exception:
                needed = False
        self._place_warn_scrollbar(needed)

    def _refresh_warnings_display(self):
        self.warnings_text.config(state="normal")
        self.warnings_text.delete("1.0", tk.END)
        if self._storage_hint_text:
            self.warnings_text.insert(tk.END, self._storage_hint_text + "\n", "storage")
        if self._pad_warnings_text:
            self.warnings_text.insert(tk.END, self._pad_warnings_text, "padwarn")
        self.warnings_text.config(state="disabled")
        if getattr(self, "_warn_job", None):
            try:
                self.root.after_cancel(self._warn_job)
            except (tk.TclError, ValueError):
                pass
        self._warn_job = self.root.after_idle(self._run_warn_scrollbar_check)

    def _run_warn_scrollbar_check(self):
        self._warn_job = None
        try:
            self._update_warn_scrollbar_visibility()
        except tk.TclError:
            pass

    def on_force_mono_changed(self):
        self.stop_playback_waveform()
        for pad in PADS:
            self.pad_widgets[pad].update_mono_lock()
            self.pad_widgets[pad].update_mini_waveform()
        self.update_storage_display()
        self.update_pad_warnings()
        pass  # pedalboard handles mono conversion at export time

    def _estimated_export_bytes(self, filepath, target_rate, pitch_cents=0, force_mono=False):
        if not AUDIO_AVAILABLE:
            try:
                return os.path.getsize(filepath)
            except OSError:
                return 0
        try:
            duration, orig_rate, channels = get_wav_info(filepath)
        except Exception:
            try:
                return os.path.getsize(filepath)
            except OSError:
                return 0

        orig_sample_width = get_wav_sample_width(filepath) or 2
        needs_mono = force_mono and channels > 1
        needs_bit_depth_fix = orig_sample_width != 2
        if (
            target_rate == orig_rate
            and not pitch_cents
            and not needs_mono
            and not needs_bit_depth_fix
        ):
            try:
                return os.path.getsize(filepath)
            except OSError:
                return 0

        if pitch_cents:
            duration = duration / pitch_speed_factor(pitch_cents)
        if needs_mono:
            channels = 1
        bytes_per_sample = 2
        return int(duration * target_rate * channels * bytes_per_sample) + 44

    def _bank_size_bytes(self, bank):
        total = 0
        global_force = self.bank_force_mono(bank)
        for pad in PADS:
            state = self._get_pad_state(bank, pad)
            path = state.get("filepath") if state else None
            if path and os.path.exists(path):
                if state.get("wavetable"):
                    try:
                        total += os.path.getsize(path)
                    except OSError:
                        pass
                    continue
                target_rate = state.get("target_rate")
                pitch_cents = state.get("pitch_cents", 0)
                pad_mono = global_force or state.get("mono", False)
                if target_rate:
                    total += self._estimated_export_bytes(path, target_rate, pitch_cents, pad_mono)
                else:
                    try:
                        total += os.path.getsize(path)
                    except OSError:
                        pass
        return total

    def update_storage_display(self):
        if not hasattr(self, "bank_size_label"):
            return

        bank = self.current_bank.get()
        bank_bytes = self._bank_size_bytes(bank)
        total_bytes = sum(self._bank_size_bytes(b) for b in BANKS)
        limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)

        bank_mb = bank_bytes / (1024 * 1024)
        total_mb = total_bytes / (1024 * 1024)
        bank_over = bank_bytes > MAX_UPLOAD_BYTES
        total_over = total_bytes > MAX_UPLOAD_BYTES

        self.bank_size_label.config(
            text=f"{bank_mb:.2f} MB", fg=ACCENT_RED if bank_over else FG_TEXT
        )
        self.total_size_label.config(
            text=f"{total_mb:.2f} MB", fg=ACCENT_RED if total_over else FG_TEXT
        )

        if bank_over or total_over:
            self._storage_hint_text = f"Max. total file size per upload is {limit_mb:.0f} MB"
        else:
            self._storage_hint_text = ""
        self._refresh_warnings_display()

    def switch_bank(self, bank):
        self._save_active_bank_state()
        self.clear_playback_waveform()
        self.force_mono_cb.config(variable=self.force_mono_vars[bank])
        self.build_pad_slots(bank)

    @staticmethod
    def _find_prm_for(filepath):
        base = os.path.splitext(filepath)[0]
        for ext in (".PRM", ".prm"):
            if os.path.isfile(base + ext):
                return base + ext
        return None

    def banks_with_prm_files(self, banks):
        found = []
        for bank in banks:
            for pad in PADS:
                state = self._get_pad_state(bank, pad)
                if not state or not state.get("filepath"):
                    continue
                if state.get("wavetable"):
                    continue
                if self._find_prm_for(state["filepath"]):
                    found.append(bank)
                    break
        return found

    def export_bank(self, bank, include_prm=False):
        if bank == self._active_bank:
            self._save_active_bank_state()
        bank_path = os.path.join(self.import_root, f"BANK_{bank}")
        copied, skipped = 0, 0
        for pad in PADS:
            state = self._get_pad_state(bank, pad)
            pad_path = os.path.join(bank_path, f"PAD_{pad}")

            if not state or not state.get("filepath"):
                skipped += 1
                continue

            filepath = state["filepath"]
            try:
                os.makedirs(pad_path, exist_ok=True)
            except Exception as e:
                dark_showerror("Copy Error", f"PAD_{pad}: could not create folder:\n{e}")
                skipped += 1
                continue

            if state.get("wavetable"):
                export_path = filepath
            else:
                try:
                    pad_mono = self.bank_force_mono(bank) or state.get("mono", False)
                    export_path = compute_export_ready_path(
                        filepath,
                        state.get("target_rate") or 44100,
                        state.get("pitch_cents", 0),
                        pad_mono,
                    )
                except Exception:
                    export_path = filepath

            dest = os.path.join(pad_path, os.path.basename(export_path))
            wt_state = state.get("wavetable")
            prm_text = None
            if wt_state:
                try:
                    wt_meta = wt_state["meta"]
                    prm_text = render_prm(
                        bank,
                        pad,
                        0,
                        wt_meta["L"],
                        wt_meta["total_frames"],
                        template=(
                            state.get("wt_patch")
                            if state.get("wt_patch") in PRM_TEMPLATES
                            else "Init"
                        ),
                        poly=state.get("wt_poly", False),
                    )
                except Exception as e:
                    print(f"PAD_{pad}: could not build wavetable settings: {e}")
            prm_src = self._find_prm_for(filepath) if include_prm and not prm_text else None
            prm_dest = os.path.splitext(dest)[0] + ".PRM" if (prm_src or prm_text) else None

            try:
                keep = {os.path.abspath(export_path)}
                if prm_dest:
                    keep.add(os.path.abspath(prm_dest))
                for existing_file in os.listdir(pad_path):
                    existing_full = os.path.join(pad_path, existing_file)
                    if os.path.abspath(existing_full) not in keep:
                        try:
                            os.remove(existing_full)
                        except Exception as e:
                            print(f"Could not delete old file ({existing_full}): {e}")
            except Exception as e:
                print(f"Could not read pad folder ({pad_path}): {e}")

            if prm_text:
                try:
                    with open(prm_dest, "w", newline="") as f:
                        f.write(prm_text)
                except Exception as e:
                    dark_showerror(
                        "Copy Error",
                        f"PAD_{pad}: the wavetable settings file could not be written:\n{e}",
                    )
            elif prm_src:
                try:
                    if os.path.abspath(prm_src) != os.path.abspath(prm_dest):
                        shutil.copy2(prm_src, prm_dest)
                except Exception as e:
                    print(f"PAD_{pad}: could not copy settings file: {e}")

            if os.path.abspath(export_path) == os.path.abspath(dest):
                copied += 1
                continue

            try:
                shutil.copy2(export_path, dest)
                src_size = os.path.getsize(export_path)
                dst_size = os.path.getsize(dest)
                if dst_size != src_size:
                    raise OSError(
                        f"copied {dst_size} of {src_size} bytes - "
                        f"the target may be full or disconnected"
                    )
                copied += 1
            except Exception as e:
                detail = f"{type(e).__name__}: {e}" if not str(e) else str(e)
                dark_showerror("Copy Error", f"PAD_{pad}: {detail}")
                skipped += 1
                try:
                    if os.path.exists(dest):
                        os.remove(dest)
                except OSError:
                    pass

        return copied, skipped

    def _build_bank_menu_entry(self, menu, bank, kwargs):
        if bank != self.current_bank.get():
            return False

        submenu = tk.Menu(
            menu,
            tearoff=0,
            bg=BG_INPUT,
            fg=FG_TEXT,
            activebackground=ACCENT_BLUE,
            activeforeground="#00131A",
            bd=0,
            relief="flat",
        )
        for action, label in (("copy", "Copy To"), ("move", "Move To")):
            target_menu = tk.Menu(
                submenu,
                tearoff=0,
                bg=BG_INPUT,
                fg=FG_TEXT,
                activebackground=ACCENT_BLUE,
                activeforeground="#00131A",
                bd=0,
                relief="flat",
            )
            for target in BANKS:
                if target == bank:
                    continue
                suffix = "  (has samples)" if self.bank_has_samples(target) else ""
                target_menu.add_command(
                    label=f"Bank {target}{suffix}",
                    command=lambda t=target, a=action: self.transfer_bank(a, t),
                )
            submenu.add_cascade(label=label, menu=target_menu)
        menu.add_cascade(label=f"{bank}  \u2013  current", menu=submenu, **kwargs)
        return True

    def _duplicate_wavetable_for(self, state):
        from pyp6.config import wavetable_path

        src = state.get("filepath")
        if not src or not os.path.isfile(src):
            return state
        try:
            dst = wavetable_path(f"wavetable_{uuid.uuid4().hex[:8]}.WAV")
            shutil.copy2(src, dst)
            state["filepath"] = dst
        except Exception as e:
            print(f"wavetable copy failed, sharing the original: {e}")
        return state

    def transfer_bank(self, action, target):
        source = self.current_bank.get()
        if target == source:
            return
        self._save_active_bank_state()
        if not self.bank_has_samples(source):
            dark_showwarning(
                "Empty Bank", f"Bank {source} has no samples to {action}.", parent=self.root
            )
            return

        if self.bank_has_samples(target):
            if not dark_askyesno(
                f"Overwrite Bank {target}?",
                f"Bank {target} already contains samples. They will be replaced by "
                f"bank {source}.\n\nContinue?",
                parent=self.root,
            ):
                return
        elif action == "move":
            if not dark_askyesno(
                f"Move Bank {source} to {target}?",
                f"Bank {source} will be emptied and its samples moved to bank "
                f"{target}.\n\nContinue?",
                parent=self.root,
            ):
                return

        self._push_undo()
        self.slots[target] = copy.deepcopy(self.slots[source])
        if action == "copy":
            for pad in PADS:
                state = self.slots[target].get(pad)
                if state and state.get("wavetable"):
                    self._duplicate_wavetable_for(state)
        if target in self.force_mono_vars and source in self.force_mono_vars:
            self.force_mono_vars[target].set(self.force_mono_vars[source].get())
        if action == "move":
            self.slots[source] = {p: None for p in PADS}
            if source in self.force_mono_vars:
                self.force_mono_vars[source].set(False)
            self.clear_playback_waveform()

        if action == "move":
            self.current_bank.set(target)
        self.build_pad_slots(self.current_bank.get())
        self.update_storage_display()
        self.update_pad_warnings()
        self.show_status(
            f"Bank {source} {'moved' if action == 'move' else 'copied'} to bank {target}."
        )

    def open_clear_banks_dialog(self):
        from pyp6.ui.dialogs.bank import ClearBanksDialog

        self._save_active_bank_state()
        dialog = ClearBanksDialog(self.root, self)
        self.root.wait_window(dialog)
        if not dialog.confirmed:
            return
        banks = dialog.selected_banks()
        if banks:
            self.clear_banks(banks)

    def clear_banks(self, banks):
        self.clear_playback_waveform()
        self._push_undo()
        active = self.current_bank.get()
        for bank in banks:
            if bank == active:
                for pad in PADS:
                    self.pad_widgets[pad].clear_pad()
            self.slots[bank] = {p: None for p in PADS}
            if bank in self.force_mono_vars:
                self.force_mono_vars[bank].set(False)
        self.update_storage_display()
        self.update_pad_warnings()
        bank_word = "Bank" if len(banks) == 1 else "Banks"
        self.show_status(f"{bank_word} {', '.join(banks)} cleared.")

    def wipe_import_folder(self):
        files_found = []
        for bank in BANKS:
            bank_path = os.path.join(self.import_root, f"BANK_{bank}")
            if not os.path.isdir(bank_path):
                continue
            for pad in PADS:
                pad_path = os.path.join(bank_path, f"PAD_{pad}")
                if os.path.isdir(pad_path):
                    try:
                        for fname in os.listdir(pad_path):
                            if fname.lower().endswith((".wav", ".mp3")):
                                files_found.append(f"BANK_{bank}/PAD_{pad}/{fname}")
                    except Exception as e:
                        print(f"Could not read {pad_path}: {e}")

        if not files_found:
            self.show_status("The IMPORT folder contains no samples in any bank.", kind="info")
            return

        warning_lines = [
            f"Really delete all {len(files_found)} sample file(s) across every bank from:",
            self.import_root,
            "",
            "This permanently removes them from the device and cannot be undone.",
            "",
            "(Your pad assignments in the app itself are not affected - only files "
            'already copied to the device. You can re-export with "Banks \u2192 P6" '
            "afterward if needed.)",
        ]
        if not dark_askyesno("Confirm Wipe IMPORT Folder", chr(10).join(warning_lines)):
            return

        self._set_busy(True)
        deleted_count = 0
        errors = []
        try:
            for bank in BANKS:
                bank_path = os.path.join(self.import_root, f"BANK_{bank}")
                if not os.path.isdir(bank_path):
                    continue
                for pad in PADS:
                    pad_path = os.path.join(bank_path, f"PAD_{pad}")
                    if os.path.isdir(pad_path):
                        try:
                            for fname in os.listdir(pad_path):
                                if fname.lower().endswith((".wav", ".mp3")):
                                    full_path = os.path.join(pad_path, fname)
                                    try:
                                        os.remove(full_path)
                                        deleted_count += 1
                                    except Exception as e:
                                        errors.append(f"BANK_{bank}/{fname}: {e}")
                        except Exception as e:
                            errors.append(f"BANK_{bank}/PAD_{pad}: {e}")
        finally:
            self._set_busy(False)

        if errors:
            dark_showerror(
                "Partial Errors", "Some files could not be deleted:\n" + chr(10).join(errors)
            )
        else:
            self.show_status(
                f"{deleted_count} file(s) permanently removed from the device across all banks."
            )

    def _set_busy(self, busy):
        try:
            self.root.config(cursor="watch" if busy else "")
            self.root.update_idletasks()
        except Exception:
            pass

    def _confirm_if_over_limit(self, banks):
        over = []
        for bank in banks:
            size = self._bank_size_bytes(bank)
            if size > MAX_UPLOAD_BYTES:
                over.append((bank, size / (1024 * 1024)))
        if not over:
            return True
        limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        details = "\n".join(f"  Bank {b}: {mb:.2f} MB" for b, mb in over)
        return dark_askyesno(
            "Storage Limit Exceeded",
            f"The following exceed the {limit_mb:.0f} MB limit:\n\n{details}\n\nCopy anyway?",
        )

    def open_import_bank_dialog(self):
        from pyp6.ui.dialogs.bank import ImportBankDialog

        self._save_active_bank_state()
        ImportBankDialog(self.root, self)

    def open_copy_banks_dialog(self):
        from pyp6.ui.dialogs.bank import CopyBanksDialog

        self._save_active_bank_state()
        dialog = CopyBanksDialog(self.root, self)
        self.root.wait_window(dialog)
        if not dialog.confirmed:
            return
        banks = dialog.selected_banks()
        if not banks:
            return
        if not self._confirm_if_over_limit(banks):
            return

        prm_banks = self.banks_with_prm_files(banks)
        include_prm = False
        if prm_banks:
            include_prm = dark_askyesno(
                "Copy Settings Files?",
                f"Bank(s) {', '.join(prm_banks)} still have the P-6's own .PRM settings "
                "files for some pads.\n\nCopy them to the device along with the samples?\n\n"
                "Yes: the pads keep the settings they had on the P-6.\n"
                "No: only the audio is copied, and the device applies its defaults.",
            )

        total_c, total_s = 0, 0
        self._set_busy(True)
        try:
            for i, bank in enumerate(banks, 1):
                self.show_progress(f"Copying Bank {bank} to P6 \u2026 ({i}/{len(banks)})")
                c, s = self.export_bank(bank, include_prm=include_prm)
                total_c += c
                total_s += s
        finally:
            self._set_busy(False)
        bank_word = "bank" if len(banks) == 1 else "banks"
        self.show_status(
            f"{len(banks)} {bank_word} ({', '.join(banks)}): {total_c} copied, {total_s} empty."
        )

"""Settings and About dialogs: SettingsDialog, AboutDialog."""

import os
import tkinter as tk

import pyp6.audio.playback as _pb
from pyp6._theme_vars import (
    ACCENT_BLUE,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
    BTN_BLUE,
    BTN_GREEN,
    BTN_ORANGE,
    BTN_PURPLE,
    FG_MUTED,
    FG_TEXT,
    THEME,
)
from pyp6.audio.playback import PYDUB_AVAILABLE
from pyp6.config import (
    apply_saved_storage_threshold,
    clear_temp_folder,
    get_temp_folder_size,
    load_default_autoplay,
    load_default_slices,
    load_ffmpeg_override,
    load_ffprobe_override,
    load_storage_warning_mb,
    save_config_value,
)
from pyp6.constants import (
    APP_NAME,
    APP_SUBTITLE,
    APP_URL,
    APP_VERSION,
    SLICE_COUNTS,
    TEMP_DIR,
    UI_FAMILY,
)
from pyp6.ui.dialogs_common import (
    TOOLTIPS_ENABLED,
    add_tooltip,
    center_toplevel_on_parent,
    dark_askyesno,
    dark_showerror,
    dark_showinfo,
    set_tooltips_enabled,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel

try:
    from pydub import AudioSegment
except ImportError:
    AudioSegment = None


class AboutDialog(tk.Toplevel):
    """About box, opened from Settings.

    Kept as its own window rather than a sixth panel inside Settings: that
    dialog has no scrolling and is already 800px tall, so another panel
    would start pushing the Save/Close row off shorter screens."""

    def __init__(self, parent):
        super().__init__(parent)
        self.title(f"About {APP_NAME}")
        self.geometry("560x560")
        self.minsize(560, 560)
        style_toplevel(self)

        outer = tk.Frame(self, bg=BG_DARK, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        name_label = tk.Label(outer, text=APP_NAME, anchor="w")
        style_label(name_label, fg=ACCENT_BLUE, font=(UI_FAMILY, 20, "bold"))
        name_label.pack(fill="x")

        subtitle_label = tk.Label(outer, text=APP_SUBTITLE, anchor="w")
        style_label(subtitle_label, fg=FG_TEXT, font=(UI_FAMILY, 11))
        subtitle_label.pack(fill="x")

        version_label = tk.Label(outer, text=f"Version {APP_VERSION}", anchor="w")
        style_label(version_label, fg=FG_MUTED, font=(UI_FAMILY, 9))
        version_label.pack(fill="x", pady=(2, 10))

        desc_label = tk.Label(
            outer,
            anchor="w",
            justify="left",
            wraplength=500,
            text=(
                "Manages samples for the Roland AIRA P-6: load, trim, chop and "
                "normalize audio, then write complete banks to the device's "
                "IMPORT folder."
            ),
        )
        style_label(desc_label, fg=FG_TEXT, font=(UI_FAMILY, 9))
        desc_label.pack(fill="x", pady=(0, 12))

        # Not a clickable link on purpose: opening a browser from Tk needs
        # webbrowser plus a working desktop handler, and a silently failing
        # click is worse than text you can select and copy. "Copy Info"
        # includes it too.
        link_label = tk.Entry(
            outer,
            bd=0,
            highlightthickness=0,
            readonlybackground=BG_DARK,
            fg=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
            cursor="xterm",
            selectbackground=ACCENT_BLUE,
            selectforeground="#FFFFFF",
        )
        link_label.insert(0, APP_URL)
        link_label.config(state="readonly")  # selectable and copyable, but not editable
        link_label.pack(fill="x", pady=(0, 12))
        add_tooltip(
            link_label,
            "Project page with the latest version, source code and issue "
            "tracker. Select the text to copy it, or use \u201cCopy Info\u201d "
            "for everything at once.",
        )

        info_panel = RoundedPanel(
            outer,
            title="Details",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        info_panel.pack(fill="both", expand=True)
        # A Text widget rather than a grid of Labels: Tk labels can't be
        # selected, so the version numbers and paths here - exactly the
        # things you want to paste into a bug report - couldn't be picked
        # out individually. "Copy Info" copies everything at once; this
        # allows grabbing a single line.
        self.info_text = tk.Text(
            info_panel.body,
            bg=BG_PANEL,
            fg=FG_TEXT,
            font=(UI_FAMILY, 8),
            bd=0,
            highlightthickness=0,
            wrap="word",
            height=14,
            insertwidth=0,
            cursor="xterm",
            selectbackground=ACCENT_BLUE,
            selectforeground="#FFFFFF",
        )
        self.info_text.pack(fill="both", expand=True, pady=(6, 4))
        self.info_text.tag_configure("key", foreground=FG_MUTED)
        # Lazy import: collect_about_info lives in __main__ and is registered
        # at startup so the about dialog does not hard-depend on __main__.
        from pyp6._about_helpers import about_info_as_text, collect_about_info

        self._about_info_as_text = about_info_as_text
        for label, value in collect_about_info():
            self.info_text.insert("end", f"{label}: ", "key")
            self.info_text.insert("end", f"{value}\n")
        self.info_text.delete("end-1c")  # trailing newline
        self._make_read_only(self.info_text)

        # Not legal advice, just plain honesty: this is an independent tool
        # and users shouldn't be left thinking Roland published it.
        disclaimer = tk.Label(
            outer,
            anchor="w",
            justify="left",
            wraplength=500,
            text=(
                "Roland, AIRA and P-6 are trademarks of Roland Corporation. "
                "This is an independent project and is not affiliated with, "
                "endorsed by or supported by Roland."
            ),
        )
        style_label(disclaimer, fg=FG_MUTED, font=(UI_FAMILY, 8))
        disclaimer.pack(fill="x", pady=(12, 0))

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(12, 0))
        close_btn = RoundedButton(
            btn_row,
            text="Close",
            command=self.destroy,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        close_btn.pack(side="right", padx=4)
        self.copy_btn = RoundedButton(
            btn_row,
            text="Copy Info",
            command=self._copy_info,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=110,
        )
        self.copy_btn.pack(side="right", padx=4)
        add_tooltip(
            self.copy_btn,
            "Copies version, component and path details to the clipboard - "
            "handy to paste into a bug report.",
        )

        self.bind("<Escape>", lambda _e: self.destroy())
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    @staticmethod
    def _make_read_only(text_widget):
        """Keeps a Text widget selectable and copyable but not editable.

        state="disabled" would also block the selection this exists for, so
        the widget stays enabled and every key that could change the content
        is swallowed instead - Ctrl+C/Ctrl+A and cursor movement still get
        through. Middle-click is blocked too: on X11 that pastes the primary
        selection straight into the widget."""
        allowed = {"c", "a", "C", "A", "Insert"}

        def on_key(event):
            if event.state & 0x4 and (event.keysym in allowed):  # Control held
                return None
            if event.keysym in (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Prior",
                "Next",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
            ):
                return None
            return "break"

        text_widget.bind("<Key>", on_key)
        text_widget.bind("<<Paste>>", lambda e: "break")
        text_widget.bind("<<Cut>>", lambda e: "break")
        text_widget.bind("<Button-2>", lambda e: "break")

    def _copy_info(self):
        try:
            self.clipboard_clear()
            self.clipboard_append(self._about_info_as_text())
            self.update()  # some X11 setups drop the selection without this
        except tk.TclError:
            return
        self.copy_btn.text = "Copied"
        self.copy_btn._draw()
        self.after(1500, self._reset_copy_button)

    def _reset_copy_button(self):
        try:
            if self.copy_btn.winfo_exists():
                self.copy_btn.text = "Copy Info"
                self.copy_btn._draw()
        except tk.TclError:
            pass

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


class SettingsDialog(tk.Toplevel):
    """Central place for things that used to be scattered top-bar buttons
    (Choose Folder) plus a few sensible defaults/overrides."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Settings")
        # 40px taller than the content used to need - the Appearance panel
        # gained the tooltip row, and this window has no scrolling, so the
        # Save/Close row at the bottom would otherwise be pushed off-screen.
        self.geometry("620x800")
        self.minsize(620, 800)
        style_toplevel(self)

        outer = tk.Frame(self, bg=BG_DARK, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        # ----- IMPORT folder -----
        import_panel = RoundedPanel(
            outer,
            title="IMPORT Folder",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        import_panel.pack(fill="x", pady=(0, 12))
        import_row = tk.Frame(import_panel.body, bg=BG_PANEL)
        import_row.pack(fill="x")
        self.import_path_label = tk.Label(
            import_row, text=self.app.import_root, anchor="w", wraplength=380, justify="left"
        )
        style_label(self.import_path_label, bg=BG_PANEL, fg=FG_TEXT, font=(UI_FAMILY, 9))
        self.import_path_label.pack(side="left", fill="x", expand=True)
        change_folder_btn = RoundedButton(
            import_row,
            text="Change...",
            command=self._change_import_folder,
            bg=BTN_PURPLE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=100,
        )
        change_folder_btn.pack(side="right")
        add_tooltip(
            change_folder_btn,
            'The IMPORT folder on the P-6 drive. "Banks \u2192 P6" writes the '
            "BANK_x/PAD_n folders in here.",
        )

        # ----- Appearance -----
        appearance_panel = RoundedPanel(
            outer,
            title="Appearance",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        appearance_panel.pack(fill="x", pady=(0, 12))

        theme_row = tk.Frame(appearance_panel.body, bg=BG_PANEL)
        theme_row.pack(fill="x")
        theme_lbl = tk.Label(theme_row, text="Theme:")
        style_label(theme_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        theme_lbl.pack(side="left")
        self.theme_var = tk.StringVar(value=THEME)
        theme_dd = RoundedDropdown(
            theme_row,
            self.theme_var,
            ["dark", "tokyo", "dracula", "modern", "latte", "bright"],
            parent_bg=BG_PANEL,
            width=100,
            height=26,
        )
        theme_dd.pack(side="left", padx=6)
        theme_names_hint = tk.Label(
            theme_row, text="(latte = muted Catppuccin Latte, bright = the original)", anchor="w"
        )
        style_label(theme_names_hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        theme_names_hint.pack(side="left", padx=(4, 0))

        theme_hint = tk.Label(
            appearance_panel.body, text="Requires an app restart to take effect.", anchor="w"
        )
        style_label(theme_hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        theme_hint.pack(fill="x", pady=(6, 0))

        tooltip_row = tk.Frame(appearance_panel.body, bg=BG_PANEL)
        tooltip_row.pack(fill="x", pady=(10, 0))
        self.tooltips_var = tk.BooleanVar(value=TOOLTIPS_ENABLED)
        tooltips_cb = tk.Checkbutton(
            tooltip_row,
            text="Show tooltips (hover help)",
            variable=self.tooltips_var,
            command=self._on_tooltips_toggled,
        )
        style_checkbutton(tooltips_cb)
        tooltips_cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
        tooltips_cb.pack(side="left")
        tooltips_hint = tk.Label(tooltip_row, text="(applies immediately)", anchor="w")
        style_label(tooltips_hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        tooltips_hint.pack(side="left", padx=(6, 0))
        add_tooltip(
            tooltips_cb,
            "Short explanations that appear when you hover over a button or "
            "waveform. Turn this off once you know your way around.",
        )

        # ----- Audio components -----
        comp_panel = RoundedPanel(
            outer,
            title="Audio Components (pydub / ffmpeg)",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        comp_panel.pack(fill="x", pady=(0, 12))

        # Lazy import: dnd helpers are registered at startup in __main__.
        from pyp6._about_helpers import dnd_is_working, dnd_status_text

        dnd_row = tk.Frame(comp_panel.body, bg=BG_PANEL)
        dnd_row.pack(fill="x", pady=(0, 8))
        dnd_lbl = tk.Label(dnd_row, text=f"Drag & drop onto pads: {dnd_status_text()}", anchor="w")
        style_label(
            dnd_lbl,
            bg=BG_PANEL,
            fg=(FG_TEXT if dnd_is_working() else FG_MUTED),
            font=(UI_FAMILY, 9),
        )
        dnd_lbl.pack(side="left")

        ffmpeg_row = tk.Frame(comp_panel.body, bg=BG_PANEL)
        ffmpeg_row.pack(fill="x")
        ffmpeg_lbl = tk.Label(ffmpeg_row, text="ffmpeg path:", width=12, anchor="w")
        style_label(ffmpeg_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        ffmpeg_lbl.pack(side="left")
        self.ffmpeg_entry = tk.Entry(
            ffmpeg_row,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
        )
        current_ffmpeg = (
            load_ffmpeg_override() or getattr(AudioSegment, "converter", "")
            if PYDUB_AVAILABLE
            else ""
        )
        self.ffmpeg_entry.insert(0, current_ffmpeg or "")
        self.ffmpeg_entry.pack(side="left", fill="x", expand=True, padx=6)

        ffprobe_row = tk.Frame(comp_panel.body, bg=BG_PANEL)
        ffprobe_row.pack(fill="x", pady=(6, 0))
        ffprobe_lbl = tk.Label(ffprobe_row, text="ffprobe path:", width=12, anchor="w")
        style_label(ffprobe_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        ffprobe_lbl.pack(side="left")
        self.ffprobe_entry = tk.Entry(
            ffprobe_row,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
        )
        current_ffprobe = (
            load_ffprobe_override() or getattr(AudioSegment, "ffprobe", "")
            if PYDUB_AVAILABLE
            else ""
        )
        self.ffprobe_entry.insert(0, current_ffprobe or "")
        self.ffprobe_entry.pack(side="left", fill="x", expand=True, padx=6)

        hint = tk.Label(
            comp_panel.body,
            text="Leave blank for automatic detection. Only fill in if ffmpeg/ffprobe "
            "aren't found automatically.",
            anchor="w",
            justify="left",
            wraplength=560,
        )
        style_label(hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", pady=(6, 0))

        # ----- Audio Output -----
        audio_out_panel = RoundedPanel(
            outer,
            title="Audio Output",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        audio_out_panel.pack(fill="x", pady=(0, 12))

        dev_row = tk.Frame(audio_out_panel.body, bg=BG_PANEL)
        dev_row.pack(fill="x")

        dev_lbl = tk.Label(dev_row, text="Output device:", width=14, anchor="w")
        style_label(dev_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        dev_lbl.pack(side="left")

        self._device_names, self._device_indices = self._list_output_devices()
        current_idx = _pb.SD_OUTPUT_DEVICE
        try:
            current_name = (
                self._device_names[self._device_indices.index(current_idx)]
                if current_idx in self._device_indices
                else self._device_names[0]
            )
        except (ValueError, IndexError):
            current_name = self._device_names[0] if self._device_names else "—"

        self.device_var = tk.StringVar(value=current_name)
        self._device_dd = RoundedDropdown(
            dev_row,
            self.device_var,
            self._device_names,
            parent_bg=BG_PANEL,
            width=320,
            height=26,
        )
        self._device_dd.pack(side="left", padx=6)

        reload_btn = RoundedButton(
            dev_row,
            text="Reload",
            command=self._reload_output_device,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=80,
            height=26,
            font=(UI_FAMILY, 8),
        )
        reload_btn.pack(side="left", padx=4)
        add_tooltip(
            reload_btn,
            "Re-scans audio devices and applies the selected output. "
            "Use this after plugging in or changing your audio interface.",
        )

        self._dev_status_lbl = tk.Label(audio_out_panel.body, text="", anchor="w")
        style_label(self._dev_status_lbl, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self._dev_status_lbl.pack(fill="x", pady=(4, 0))

        # ----- Defaults -----
        defaults_panel = RoundedPanel(
            outer,
            title="Defaults",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        defaults_panel.pack(fill="x", pady=(0, 12))

        autoplay_row = tk.Frame(defaults_panel.body, bg=BG_PANEL)
        autoplay_row.pack(fill="x")
        self.default_autoplay_var = tk.BooleanVar(value=load_default_autoplay())
        autoplay_cb = tk.Checkbutton(
            autoplay_row,
            text="Autoplay on by default (all preview windows)",
            variable=self.default_autoplay_var,
        )
        style_checkbutton(autoplay_cb)
        autoplay_cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
        autoplay_cb.pack(side="left")
        add_tooltip(
            autoplay_cb,
            "Sets how the Autoplay checkbox starts out in the sample "
            "selection window, the Chop window and the wavetable builder. "
            "In the first two it plays the selected sample; in the "
            "wavetable builder it plays the morph sweep of the family you "
            "click.\n\nEach window keeps its own switch, so this only "
            "decides the starting position.",
        )

        slices_row = tk.Frame(defaults_panel.body, bg=BG_PANEL)
        slices_row.pack(fill="x", pady=(8, 0))
        slices_lbl = tk.Label(slices_row, text="Default Slices (Chop):")
        style_label(slices_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        slices_lbl.pack(side="left")
        self.default_slices_var = tk.IntVar(value=load_default_slices())
        slices_dd = RoundedDropdown(
            slices_row,
            self.default_slices_var,
            SLICE_COUNTS,
            parent_bg=BG_PANEL,
            width=70,
            height=26,
        )
        slices_dd.pack(side="left", padx=6)

        storage_row = tk.Frame(defaults_panel.body, bg=BG_PANEL)
        storage_row.pack(fill="x", pady=(8, 0))
        storage_lbl = tk.Label(storage_row, text="Storage Warning Threshold (MB):")
        style_label(storage_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        storage_lbl.pack(side="left")
        self.storage_mb_entry = tk.Entry(
            storage_row,
            width=8,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
            justify="center",
        )
        self.storage_mb_entry.insert(0, str(load_storage_warning_mb()))
        self.storage_mb_entry.pack(side="left", padx=6)
        add_tooltip(
            self.storage_mb_entry,
            "Above this size the storage display turns red (for the current bank "
            "and for the total), and copying to the P-6 asks for confirmation "
            "for every bank that is over.",
        )

        # ----- Temporary files -----
        temp_panel = RoundedPanel(
            outer,
            title="Temporary Files",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        temp_panel.pack(fill="x", pady=(0, 12))
        temp_row = tk.Frame(temp_panel.body, bg=BG_PANEL)
        temp_row.pack(fill="x", pady=(8, 0))
        self.temp_size_label = tk.Label(temp_row, text="", anchor="w")
        style_label(self.temp_size_label, bg=BG_PANEL, font=(UI_FAMILY, 9))
        self.temp_size_label.pack(side="left")
        clear_temp_btn = RoundedButton(
            temp_row,
            text="Clear Now",
            command=self._clear_temp,
            bg=BTN_ORANGE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=100,
            height=26,
            font=(UI_FAMILY, 8),
        )
        clear_temp_btn.pack(side="right")
        add_tooltip(
            clear_temp_btn,
            "Deletes all trimmed, normalized and chopped intermediate files. "
            "Pads still pointing at one of them are cleared - save a preset "
            "first if you want to keep those edits.",
        )
        temp_hint = tk.Label(
            temp_panel.body,
            text="Trimmed, normalized, mono-converted and chopped samples are stored here. "
            "Saved presets are self-contained (their samples are copied into the "
            "preset folder), so they are unaffected - but pads holding an edited "
            "sample you haven't saved to a preset yet will lose it.",
            anchor="w",
            justify="left",
            wraplength=560,
        )
        style_label(temp_hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        temp_hint.pack(fill="x", pady=(6, 0))
        self._refresh_temp_size()

        # ----- buttons -----
        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(4, 0))
        close_btn = RoundedButton(
            btn_row,
            text="Close",
            command=self.destroy,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        close_btn.pack(side="right", padx=4)
        save_btn = RoundedButton(
            btn_row,
            text="Save",
            command=self._save,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=90,
        )
        save_btn.pack(side="right", padx=4)
        about_btn = RoundedButton(
            btn_row,
            text="About",
            command=self._open_about,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        about_btn.pack(side="left", padx=4)
        add_tooltip(
            about_btn,
            "Version, author and the state of the optional components "
            "(pydub, ffmpeg, drag & drop).",
        )

        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    @staticmethod
    def _list_output_devices():
        """Return (names, indices) for all devices with output channels.

        Always queries PortAudio fresh — never cached — so the list reflects
        the current set of connected devices at the moment of the call.
        """
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            names, indices = [], []
            for i, dev in enumerate(devices):
                if dev["max_output_channels"] > 0:
                    names.append(f"{dev['name']} [{dev['hostapi']}]")
                    indices.append(i)
            if not names:
                names, indices = ["(no output devices found)"], [-1]
        except Exception:
            names, indices = ["(sounddevice unavailable)"], [-1]
        return names, indices

    def _reload_output_device(self):
        """Stop playback, re-scan devices, apply the selected one.

        Calling sd.stop() before re-scanning is critical: PortAudio holds an
        internal stream open after each sd.play(), and that stale stream is
        what causes paInvalidDevice (-9986) after a hot-plug event even when
        the correct device is selected.
        """
        try:
            import sounddevice as sd

            sd.stop()  # release any cached PortAudio stream first

            # Rebuild the device list from scratch to pick up hot-plug changes.
            self._device_names, self._device_indices = self._list_output_devices()
            self._device_dd.options = self._device_names
            self._device_dd._draw()

            selected_name = self.device_var.get()
            # If the previously selected device name still exists use it;
            # otherwise fall back to the first valid device.
            if selected_name not in self._device_names:
                selected_name = self._device_names[0]
                self.device_var.set(selected_name)

            try:
                pos = self._device_names.index(selected_name)
                dev_idx = self._device_indices[pos]
            except (ValueError, IndexError):
                dev_idx = None

            if dev_idx is not None and dev_idx >= 0:
                sd.check_output_settings(device=dev_idx)
                _pb.SD_OUTPUT_DEVICE = dev_idx
                name = sd.query_devices(dev_idx)["name"]
            else:
                _pb.SD_OUTPUT_DEVICE = _pb._find_output_device()
                dev_idx = _pb.SD_OUTPUT_DEVICE
                name = (
                    sd.query_devices(dev_idx)["name"] if dev_idx is not None else "system default"
                )

            self._dev_status_lbl.config(text=f"Active: {name}", fg=FG_TEXT)

        except Exception as exc:
            self._dev_status_lbl.config(text=f"Failed: {exc}", fg="#FF6B6B")

    def _open_about(self):
        """Hands the modal grab over to the About window and takes it back
        afterwards - two stacked grab_set() windows otherwise leave Settings
        unresponsive on some window managers once About closes."""
        try:
            self.grab_release()
        except tk.TclError:
            pass
        dlg = AboutDialog(self)
        self.wait_window(dlg)
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

    def _on_tooltips_toggled(self):
        """Applied and persisted right away, unlike the rest of this dialog.

        Toggling this is how you check whether you want it - so it has to be
        visible immediately, and saving it on the spot avoids the state where
        tooltips are visibly off but come back on the next start because
        "Close" was pressed instead of "Save"."""
        enabled = bool(self.tooltips_var.get())
        set_tooltips_enabled(enabled)
        save_config_value("tooltips_enabled", enabled)

    def _refresh_temp_size(self):
        total, count = get_temp_folder_size()
        mb = total / (1024 * 1024)
        if count == 0:
            self.temp_size_label.config(text="Temp folder is empty.", fg=FG_MUTED)
        else:
            file_word = "file" if count == 1 else "files"
            self.temp_size_label.config(text=f"{mb:.2f} MB in {count} {file_word}", fg=FG_TEXT)

    def _clear_temp(self):
        total, count = get_temp_folder_size()
        if count == 0:
            dark_showinfo("Nothing to Clear", "The temp folder is already empty.", parent=self)
            return
        mb = total / (1024 * 1024)
        if not dark_askyesno(
            "Clear Temporary Files?",
            f"Delete {count} file(s) ({mb:.2f} MB) from:\n{TEMP_DIR}\n\n"
            "Saved presets and your settings are not affected. Pads still holding an "
            "edited (trimmed/normalized/chopped) sample that hasn't been saved to a "
            "preset yet will be cleared.\n\nContinue?",
            parent=self,
        ):
            return
        deleted, errors = clear_temp_folder()
        self._refresh_temp_size()
        cleared_pads = 0
        if hasattr(self.app, "clear_pads_referencing_missing_files"):
            cleared_pads = self.app.clear_pads_referencing_missing_files()
        if errors:
            dark_showerror(
                "Partial Errors",
                "Some items could not be deleted:\n" + chr(10).join(errors),
                parent=self,
            )
        else:
            msg = f"{deleted} item(s) deleted."
            if cleared_pads:
                pad_word = "pad" if cleared_pads == 1 else "pads"
                msg += f"\n\n{cleared_pads} {pad_word} referencing a deleted file were cleared."
            dark_showinfo("Temp Cleared", msg, parent=self)

    def _change_import_folder(self):
        self.grab_release()
        self.app.choose_import_folder(parent_window=self)
        self.import_path_label.config(text=self.app.import_root)
        self.grab_set()
        self.lift()
        self.focus_force()

    def _save(self):
        # Theme
        new_theme = self.theme_var.get()
        theme_changed = new_theme != THEME
        save_config_value("theme", new_theme)

        # Tooltips (already applied+saved on toggle - written again so an
        # explicit Save is never a no-op for a setting shown in this dialog)
        set_tooltips_enabled(bool(self.tooltips_var.get()))
        save_config_value("tooltips_enabled", bool(self.tooltips_var.get()))

        # Defaults
        save_config_value("default_autoplay", bool(self.default_autoplay_var.get()))
        save_config_value("default_slices", int(self.default_slices_var.get()))
        try:
            mb = float(self.storage_mb_entry.get())
            if mb <= 0:
                raise ValueError
        except ValueError:
            dark_showerror(
                "Invalid Value", "The storage warning threshold must be a number > 0.", parent=self
            )
            return
        save_config_value("storage_warning_mb", mb)
        apply_saved_storage_threshold()

        # ffmpeg/ffprobe overrides
        ffmpeg_path = self.ffmpeg_entry.get().strip()
        ffprobe_path = self.ffprobe_entry.get().strip()
        save_config_value("ffmpeg_path", ffmpeg_path)
        save_config_value("ffprobe_path", ffprobe_path)
        if PYDUB_AVAILABLE and AudioSegment is not None:
            if ffmpeg_path and os.path.exists(ffmpeg_path):
                AudioSegment.converter = ffmpeg_path
                AudioSegment.ffmpeg = ffmpeg_path
                _pb.FFMPEG_AVAILABLE = True
            if ffprobe_path and os.path.exists(ffprobe_path):
                AudioSegment.ffprobe = ffprobe_path

        if hasattr(self.app, "update_storage_display"):
            self.app.update_storage_display()

        if theme_changed:
            dark_showinfo(
                "Saved", "Settings saved.\n\nRestart the app to apply the new theme.", parent=self
            )
        else:
            dark_showinfo("Saved", "Settings saved.", parent=self)
        self.destroy()

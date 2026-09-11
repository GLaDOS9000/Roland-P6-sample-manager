"""SampleSlot: one pad in the bank grid, with its UI and audio state."""

import os
import tkinter as tk
import uuid

import numpy as np

try:
    import sounddevice as sd
except ImportError:
    sd = None

try:
    import soundfile as sf
except ImportError:
    sf = None

import pyp6.config as _cfg
from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_ORANGE,
    BG_INPUT,
    BG_PANEL,
    BORDER_COLOR,
    BORDER_LIGHT,
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
from pyp6.audio.conversion import convert_to_wav_if_needed
from pyp6.audio.info import compute_truncate_fraction, get_wav_info
from pyp6.audio.playback import AUDIO_AVAILABLE, play_audio
from pyp6.config import save_last_sample_dir, wavetable_path
from pyp6.constants import (
    BANKS,
    MAX_SECONDS,
    PITCH_MAX_CENTS,
    PITCH_MIN_CENTS,
    PITCH_STEP_CENTS,
    PRM_TEMPLATES,
    TARGET_RATES,
    UI_FAMILY,
    WT_SEGMENTS,
)
from pyp6.log import logger
from pyp6.synth.engine import (
    render_prm,
    wavetable_summary,
    write_wavetable_files,
    write_wavetable_map,
)
from pyp6.theme import readable_on
from pyp6.ui.dialogs_common import (
    add_tooltip,
    dark_askyesno,
    dark_showerror,
    style_checkbutton,
    style_label,
)
from pyp6.ui.waveform import draw_truncate_overlay, draw_waveform_on_canvas
from pyp6.ui.widgets import RoundedButton, RoundedDropdown, RoundedPanel


class SampleSlot:
    def __init__(self, parent, pad_num, app):
        self.pad_num = pad_num
        self.app = app
        self.filepath = None
        self.display_name = None
        self.target_rate = tk.IntVar(value=44100)
        self.pitch_cents = tk.IntVar(value=0)
        # Wavetable state. None means this is an ordinary sample pad; a dict
        # means the pad was built by the Synth dialog and its rate/pitch/mono
        # controls are replaced by the init patch and poly switch.
        self.wavetable = None
        self.wt_patch = tk.StringVar(value="Init")
        self.wt_poly = tk.BooleanVar(value=False)

        self.panel = RoundedPanel(
            parent,
            title=f"PAD_{pad_num}",
            parent_bg=parent.cget("bg"),
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        self.panel.grid(
            row=(pad_num - 1) // 3, column=(pad_num - 1) % 3, padx=6, pady=6, sticky="nsew"
        )
        self.frame = self.panel.body

        self.label = tk.Label(self.frame, text="No sample loaded", width=30, anchor="w")
        style_label(self.label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 9))
        self.label.pack(fill="x")
        self._bind_internal_drag(self.label)
        self._bind_internal_drag(self.panel.canvas)
        drag_help = (
            "Drag this name onto another pad to swap the two pads (including "
            "their rate, pitch and mono settings). The target pad is outlined "
            "in orange while you drag."
        )
        # Lazy import to avoid circular dependency
        from pyp6._about_helpers import DND_AVAILABLE

        if DND_AVAILABLE:
            drag_help += (
                "\n\nYou can also drop an audio file from your file manager straight onto a pad."
            )
        add_tooltip(self.label, drag_help)
        add_tooltip(
            self.panel.canvas,
            "Drag the pad frame or the sample name onto another pad to swap the two pads.",
        )

        self.mini_wave_width = 240
        self.mini_wave_height = 50
        self.mini_wave_canvas = tk.Canvas(
            self.frame,
            bg=WAVE_BG,
            width=self.mini_wave_width,
            height=self.mini_wave_height,
            highlightthickness=0,
            cursor="hand2",
        )
        self.mini_wave_canvas.pack(fill="x", pady=(2, 4))
        self.mini_wave_canvas.bind("<Configure>", self._redraw_mini_waveform_at_current_width)
        self.mini_wave_canvas.bind("<Button-1>", self.open_waveform_view)
        add_tooltip(
            self.mini_wave_canvas,
            "Click the waveform to open the editor for this sample: trim markers, "
            'zoom, normalize and fade in/out, then "Apply to Pad". '
            "An orange shaded area marks the part the P-6 would cut off at the "
            "current rate, pitch and mono setting.",
        )
        self._mini_wave_cache = None

        rate_row = tk.Frame(self.frame, bg=BG_PANEL)
        self.rate_row = rate_row
        rate_row.pack(fill="x", pady=4)
        rate_lbl = tk.Label(rate_row, text="Sample Rate:")
        style_label(rate_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        rate_lbl.pack(side="left")
        rate_menu = RoundedDropdown(
            rate_row,
            self.target_rate,
            TARGET_RATES,
            command=self.on_rate_changed,
            parent_bg=BG_PANEL,
            width=90,
            height=26,
            font=(UI_FAMILY, 9),
        )
        rate_menu.pack(side="left", padx=4)

        self.mono_var = tk.BooleanVar(value=False)
        self.mono_cb = tk.Checkbutton(
            rate_row, text="Mono", variable=self.mono_var, command=self.on_mono_changed
        )
        style_checkbutton(self.mono_cb)
        self.mono_cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
        self.mono_cb.pack(side="left", padx=(6, 0))

        pitch_row = tk.Frame(self.frame, bg=BG_PANEL)
        self.pitch_row = pitch_row
        pitch_row.pack(fill="x", pady=(0, 4))
        pitch_lbl = tk.Label(pitch_row, text="Pitch:")
        style_label(pitch_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        pitch_lbl.pack(side="left")
        pitch_minus_btn = RoundedButton(
            pitch_row,
            text="\u2212",
            command=self.pitch_step_down,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=24,
            height=24,
            font=(UI_FAMILY, 9, "bold"),
        )
        pitch_minus_btn.pack(side="left", padx=(4, 2))
        self.pitch_entry = tk.Entry(
            pitch_row,
            width=6,
            justify="center",
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=BORDER_COLOR,
            highlightcolor=ACCENT_BLUE,
            font=(UI_FAMILY, 9),
        )
        self.pitch_entry.insert(0, "0")
        self.pitch_entry.pack(side="left")
        self.pitch_entry.bind("<Return>", self.on_pitch_entry_commit)
        self.pitch_entry.bind("<FocusOut>", self.on_pitch_entry_commit)
        pitch_plus_btn = RoundedButton(
            pitch_row,
            text="+",
            command=self.pitch_step_up,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=24,
            height=24,
            font=(UI_FAMILY, 9, "bold"),
        )
        pitch_plus_btn.pack(side="left", padx=(2, 4))
        cents_lbl = tk.Label(pitch_row, text="cents")
        style_label(cents_lbl, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        cents_lbl.pack(side="left")
        pitch_reset_btn = RoundedButton(
            pitch_row,
            text="Reset",
            command=self.pitch_reset,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=55,
            height=24,
            font=(UI_FAMILY, 8, "bold"),
        )
        pitch_reset_btn.pack(side="left", padx=(6, 0))

        # Replaces rate/pitch/mono once this pad holds a wavetable: those
        # settings would resample the table and break its tuning, whereas the
        # init patch and poly switch are what actually matter for a synth voice.
        self.synth_row = tk.Frame(self.frame, bg=BG_PANEL)
        patch_lbl = tk.Label(self.synth_row, text="Init Patch:")
        style_label(patch_lbl, bg=BG_PANEL, font=(UI_FAMILY, 9))
        patch_lbl.pack(side="left")
        self.wt_patch_menu = RoundedDropdown(
            self.synth_row,
            self.wt_patch,
            list(PRM_TEMPLATES),
            command=self.on_wt_patch_changed,
            parent_bg=BG_PANEL,
            width=92,
            height=26,
            font=(UI_FAMILY, 9),
        )
        self.wt_patch_menu.pack(side="left", padx=4)
        add_tooltip(
            self.wt_patch_menu,
            "Filter and envelope settings written into this pad's .PRM file. "
            "Init is the plain looping voice; the others were captured dry from "
            "the device. Changing this rewrites the .PRM immediately.",
        )
        self.wt_poly_cb = tk.Checkbutton(
            self.synth_row, text="Poly", variable=self.wt_poly, command=self.on_wt_poly_changed
        )
        style_checkbutton(self.wt_poly_cb)
        self.wt_poly_cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
        self.wt_poly_cb.pack(side="left", padx=(8, 0))

        # Filler that stands in for the row a wavetable pad does not have, so
        # the button row keeps the same baseline as the pads next to it. Its
        # height is measured rather than hard-coded: font and theme both move
        # the real row heights around.
        self.wt_spacer = tk.Frame(self.frame, bg=BG_PANEL, height=1)
        self.wt_spacer.pack_propagate(False)
        add_tooltip(
            self.wt_poly_cb,
            "Polyphonic playback (MONO_POLY in the .PRM). Lets you play chords "
            "on this pad instead of one note at a time.",
        )

        btn_row = tk.Frame(self.frame, bg=BG_PANEL, height=28)
        btn_row.pack(fill="x", pady=4)
        # Pinned: a wavetable pad has one row less than a sample pad, and the
        # leftover space in the panel must not end up inflating this row.
        btn_row.pack_propagate(False)
        self.load_btn = load_btn = RoundedButton(
            btn_row,
            text="Load",
            command=self.load_sample,
            bg=BTN_PURPLE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=56,
            height=28,
        )
        load_btn.pack(side="left", padx=2)
        add_tooltip(
            load_btn,
            "Opens the sample browser with preview and waveform. There you can "
            "drag the green/red markers to load only the marked region onto "
            "this pad. WAV and (with ffmpeg) MP3.",
        )
        self.play_btn = RoundedButton(
            btn_row,
            text="\u25b6",
            command=self.toggle_play_pad,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=36,
            height=28,
            state="disabled",
            font=(UI_FAMILY, 11, "bold"),
        )
        self.play_btn.pack(side="left", padx=2)
        add_tooltip(
            self.play_btn,
            "Plays this pad as it will sound on the P-6 (with rate, pitch and "
            "mono applied) and shows it in the large waveform below.",
        )
        self.remove_btn = RoundedButton(
            btn_row,
            text="\u23cf",
            command=self.remove_sample,
            bg=BTN_RED,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=36,
            height=28,
            state="disabled",
            font=(UI_FAMILY, 11, "bold"),
        )
        self.remove_btn.pack(side="left", padx=2)
        add_tooltip(
            self.remove_btn,
            "Clears this pad in the app. The source file itself is not deleted. "
            "Can be undone with Ctrl+Z.",
        )
        self.chop_btn = chop_btn = RoundedButton(
            btn_row,
            text="Chop",
            command=self.open_chop,
            bg=BTN_ORANGE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=56,
            height=28,
        )
        chop_btn.pack(side="left", padx=2)
        add_tooltip(
            chop_btn,
            "Builds a multisample: several samples are lined up in equal slices "
            "into one file that the P-6 plays back per slice. The result lands "
            "on this pad.",
        )
        self.synth_btn = RoundedButton(
            btn_row,
            text="Synth",
            command=self.open_synth,
            bg=BTN_BLUE,
            fg="#FFFFFF",
            parent_bg=BG_PANEL,
            width=56,
            height=28,
        )
        self.synth_btn.pack(side="left", padx=2)
        add_tooltip(
            self.synth_btn,
            "Turns this pad into a wavetable oscillator and makes the P-6 a "
            "synthesizer: 255 single-cycle waveforms in one sample, stepped "
            "through with the START control while SIZE stays at 1. Builds the "
            "WAV and its .PRM settings file in one go.",
        )

    # ---------------------------------------------------------------
    # Wavetable synth
    # ---------------------------------------------------------------

    def _bank_letter(self):
        try:
            return self.app.current_bank.get()
        except Exception:
            return BANKS[0]

    def open_synth(self):
        """Opens the wavetable builder for this pad, pre-filled with whatever
        was used last time so settings can be reviewed and adjusted."""
        from pyp6.ui.dialogs.synth_dialog import SynthDialog

        cfg = (self.wavetable or {}).get("config")
        dlg = SynthDialog(
            self.app.root, self.app, self._bank_letter(), self.pad_num, initial_config=cfg
        )
        self.app.root.wait_window(dlg)
        if not dlg.result:
            return
        self._apply_wavetable(dlg.result)

    def _wavetable_wav_path(self):
        # Unique per build. A fixed wavetable_<bank><pad> name breaks as soon
        # as two wavetable pads are swapped: the next build on one pad would
        # silently overwrite the file the other pad is now pointing at.
        return wavetable_path(
            f"wavetable_{self._bank_letter()}{self.pad_num}_{uuid.uuid4().hex[:8]}.WAV"
        )

    def _apply_wavetable(self, result):
        cfg, pcm, rows, meta = (result["config"], result["pcm"], result["rows"], result["meta"])
        bank = self._bank_letter()
        wav_path = self._wavetable_wav_path()
        prm_text = render_prm(
            bank,
            self.pad_num,
            0,
            meta["L"],
            meta["total_frames"],
            template=self.wt_patch.get(),
            poly=self.wt_poly.get(),
        )
        try:
            write_wavetable_files(pcm, wav_path, prm_text)
        except Exception as e:
            dark_showerror("Wavetable", f"Could not write the wavetable:\n{e}")
            return

        if hasattr(self.app, "_push_undo"):
            self.app._push_undo()

        # `rows` is deliberately NOT kept on the pad: 255 entries would ride
        # along in every undo snapshot and preset manifest for no benefit.
        # keep_settings=True: rate/pitch/mono must not be re-detected, the
        # table is already 44100 Hz mono and resampling would detune it.
        self.set_file(
            wav_path,
            display_name=f"Wavetable {cfg['note']} ({cfg['register']})",
            keep_settings=True,
        )
        if self.filepath != wav_path:
            dark_showerror(
                "Wavetable", "The generated wavetable could not be loaded onto this pad."
            )
            return
        # No absolute path is kept here on purpose: pad state travels into
        # preset.json, which people swap around. self.filepath already
        # points at the right file and follows the preset when it moves.
        self.wavetable = {"config": cfg, "meta": meta}
        self.target_rate.set(44100)
        self.pitch_cents.set(0)
        self.pitch_entry.delete(0, tk.END)
        self.pitch_entry.insert(0, "0")
        self.mono_var.set(False)
        self._sync_wavetable_ui()
        if self.mini_wave_canvas.winfo_exists():
            add_tooltip(
                self.mini_wave_canvas,
                "This pad holds a generated wavetable. Use Synth to review or "
                "rebuild it; the waveform editor is disabled because trimming "
                "would break the 255-segment raster.",
            )

        if cfg.get("save_map"):
            from pyp6.ui.dialogs.file import FileSaveDialog

            dlg = FileSaveDialog(
                self.app.root,
                title="Save waveform overview",
                initial_dir=getattr(self.app, "import_root", None),
                initial_file=f"wavetable_{bank}{self.pad_num}_map.csv",
                extension=".csv",
            )
            self.app.root.wait_window(dlg)
            path = dlg.result_path
            if path:
                try:
                    write_wavetable_map(rows, meta, path)
                except Exception as e:
                    dark_showerror("Waveform overview", f"Could not write the overview:\n{e}")

    def _rewrite_prm(self):
        """Re-writes only the .PRM next to the wavetable WAV. Used when the
        init patch or the poly switch changes - the audio is untouched, so
        there is no need to rebuild the table."""
        if not self.wavetable:
            return
        meta = self.wavetable["meta"]
        # self.filepath, never a remembered path: saving and reloading a
        # preset copies the audio elsewhere, and the .PRM has to sit next to
        # the file the pad really uses or the device never sees it.
        wav_path = self.filepath
        if not wav_path:
            return
        try:
            with open(os.path.splitext(wav_path)[0] + ".PRM", "w", newline="") as f:
                f.write(
                    render_prm(
                        self._bank_letter(),
                        self.pad_num,
                        0,
                        meta["L"],
                        meta["total_frames"],
                        template=self.wt_patch.get(),
                        poly=self.wt_poly.get(),
                    )
                )
        except Exception as e:
            logger.error(f"PAD_{self.pad_num}: could not rewrite .PRM: {e}")

    def on_wt_patch_changed(self, _value=None):
        if self.wt_patch.get() == "Pad":
            # The Pad template is polyphonic by design; reflect that in the UI
            # so the checkbox never contradicts what was actually written.
            self.wt_poly.set(True)
        self._rewrite_prm()

    def on_wt_poly_changed(self):
        self._rewrite_prm()

    def _fit_wavetable_spacer(self):
        """Pads out the synth row to the height of the two rows it replaced.

        rate_row carries pady=4 top and bottom, pitch_row pady=(0, 4), and
        synth_row pady=4 - so the shortfall is the pitch row plus its bottom
        padding, minus whatever the synth row is already taller by.
        """
        try:
            self.frame.update_idletasks()
            have = self.synth_row.winfo_reqheight() + 8
            want = self.rate_row.winfo_reqheight() + 8 + self.pitch_row.winfo_reqheight() + 4
            gap = max(0, want - have)
        except tk.TclError:
            gap = 30  # widget gone mid-teardown; a sensible row height
        if gap <= 0:
            self.wt_spacer.pack_forget()
            return
        self.wt_spacer.configure(height=gap)
        self.wt_spacer.pack(fill="x", after=self.synth_row)

    def _sync_wavetable_ui(self):
        """Switches the pad between sample mode and wavetable mode."""
        if not hasattr(self, "synth_btn"):
            return  # called before __init__ finished building the row
        wt = self.wavetable
        if wt:
            # PHRASE encodes bank and pad, so a bank switch or a pad swap
            # invalidates the file that was written for the previous slot.
            self._rewrite_prm()
            self.rate_row.pack_forget()
            self.pitch_row.pack_forget()
            self.synth_row.pack(fill="x", pady=4, after=self.mini_wave_canvas)
            self._fit_wavetable_spacer()
            # Play stays live: running the table start to finish sweeps every
            # one of the 255 segments in order, which is the fastest way to
            # hear what the pad actually contains.
            self._sync_pad_buttons()
            # Darker fill under a light ring: on the normal blue the ring
            # barely separated from the button. Set after _sync_pad_buttons,
            # which puts every button back to its default look.
            self.synth_btn.bg_color = self.synth_btn._darken(BTN_BLUE, 34)
            self.synth_btn.set_outline(readable_on(FG_TEXT, BTN_BLUE, 3.0))
            self.synth_btn._draw()
            self.panel.set_border_color(ACCENT_BLUE, width=2)
        else:
            self.synth_row.pack_forget()
            self.wt_spacer.pack_forget()
            self.rate_row.pack(fill="x", pady=4, after=self.mini_wave_canvas)
            self.pitch_row.pack(fill="x", pady=(0, 4), after=self.rate_row)
            self._sync_pad_buttons()
            self.synth_btn.bg_color = BTN_BLUE
            self.synth_btn.set_outline(None)
            self.synth_btn._draw()
            self.panel.set_border_color(BORDER_LIGHT, width=1)
        self.update_mini_waveform()
        self._refresh_main_view_if_active()

    def _draw_wavetable_info(self):
        """Replaces the mini waveform with the table's key facts - the trace
        of 255 stacked single cycles is a solid block and says nothing."""
        import tkinter.font as tkfont

        c = self.mini_wave_canvas
        c.delete("all")
        lines = wavetable_summary(self.wavetable["config"], self.wavetable["meta"])
        # 7.0 rather than the usual 4.5: this is small text on a busy dark
        # canvas, and 4.5 still read as washed out here.
        text_col = readable_on(WAVE_COLOR, WAVE_BG, 7.0)

        # The widest line depends on the waveform count and the step range, and
        # the canvas follows the panel width - so pick the largest size that
        # actually fits instead of assuming one. Clipped text is worse than
        # small text.
        avail = max(c.winfo_width(), self.mini_wave_width) - 12
        size = 8
        for candidate in (8, 7, 6):
            f = tkfont.Font(family=UI_FAMILY, size=candidate)
            if max(f.measure(line) for line in lines) <= avail:
                size = candidate
                break
            size = candidate

        c.create_text(
            6, 4, text="WAVETABLE", anchor="nw", fill=text_col, font=(UI_FAMILY, 6, "bold")
        )
        y = 18
        for line in lines:
            c.create_text(6, y, text=line, anchor="nw", fill=text_col, font=(UI_FAMILY, size))
            y += size + 6

    def _set_pitch(self, value):
        value = max(PITCH_MIN_CENTS, min(PITCH_MAX_CENTS, int(value)))
        self.pitch_cents.set(value)
        self.pitch_entry.delete(0, tk.END)
        self.pitch_entry.insert(0, str(value))
        self.update_warning()
        self.app.update_storage_display()

    def pitch_step_down(self):
        self._set_pitch(self.pitch_cents.get() - PITCH_STEP_CENTS)

    def pitch_step_up(self):
        self._set_pitch(self.pitch_cents.get() + PITCH_STEP_CENTS)

    def pitch_reset(self):
        self._set_pitch(0)

    def on_pitch_entry_commit(self, event=None):
        try:
            value = int(self.pitch_entry.get())
        except ValueError:
            value = self.pitch_cents.get()
        self._set_pitch(value)

    def set_file(self, path, from_sync=False, display_name=None, keep_settings=False):
        """Puts a sample on this pad.

        keep_settings=False (the default) treats `path` as a NEW sample:
        the target rate is auto-detected from the file and pitch/mono go
        back to their defaults, which is what you want when loading,
        dropping or importing something.

        keep_settings=True is for replacing this pad's sample with an
        EDITED version of itself (the waveform editor's "Apply to Pad").
        Re-detecting there threw away deliberate choices: a pad set to
        22050 Hz to save space jumped back to 44100 the moment an edit was
        applied, because trimming preserves the source file's own rate -
        and pitch and Mono were reset along with it."""
        try:
            path, converted = convert_to_wav_if_needed(path)
        except Exception as e:
            logger.error(f"Error in set_file for PAD_{self.pad_num}: {e}")
            return
        if not path.lower().endswith(".wav"):
            # Conversion failed (missing pydub/ffmpeg or a broken file). Loading
            # it anyway would end up copying a non-WAV file straight to the
            # device, which the P-6 cannot read - so refuse it here instead.
            dark_showerror(
                "Unsupported File",
                f"'{os.path.basename(path)}' could not be converted to WAV and "
                "cannot be used.\n\nMP3 support requires pedalboard.",
            )
            return
        self.filepath = path
        # Trimmed/chopped samples are written to a randomly-named temp file
        # (trim_XXXXXXXX.wav) - display_name lets callers show the original,
        # recognizable filename instead of that generated one.
        self.display_name = display_name or os.path.basename(path)
        label_text = self.display_name + (" (converted)" if converted else "")
        if from_sync:
            label_text += " [on device]"
        self.label.config(text=label_text, fg=FG_TEXT)
        self._sync_pad_buttons()
        if hasattr(self.app, "set_active_pad"):
            self.app.set_active_pad(self.pad_num)

        if not keep_settings:
            # A genuinely new sample landed here (load, drop, import, chop).
            # Whatever wavetable this pad used to be is gone - clearing it
            # here is what re-enables Load/Play/Chop and restores the
            # rate/pitch/mono rows.
            if self.wavetable is not None:
                self.wavetable = None
                self._sync_wavetable_ui()
            try:
                _, detected_rate, _ = get_wav_info(path)
                closest_rate = min(TARGET_RATES, key=lambda r: abs(r - detected_rate))
                self.target_rate.set(closest_rate)
            except Exception as e:
                logger.error(
                    f"Could not detect sample rate for PAD_{self.pad_num}: "
                    f"{type(e).__name__}: {e or 'file is empty or truncated'} ({path})"
                )

            self.pitch_cents.set(0)
            self.pitch_entry.delete(0, tk.END)
            self.pitch_entry.insert(0, "0")
            self.mono_var.set(False)

        self.update_warning()
        if hasattr(self.app, "update_storage_display"):
            self.app.update_storage_display()

    def update_warning(self):
        self.update_mini_waveform()
        if hasattr(self.app, "update_pad_warnings"):
            self.app.update_pad_warnings()
        if hasattr(self.app, "stop_and_refresh_waveform_for"):
            self.app.stop_and_refresh_waveform_for(
                self.filepath, self._current_max_seconds(), self.pitch_cents.get()
            )

    def get_export_ready_path(self):
        from pyp6.audio.conversion import compute_export_ready_path

        force_mono = self.effective_mono()
        return compute_export_ready_path(
            self.filepath, self.target_rate.get(), self.pitch_cents.get(), force_mono
        )

    def get_state(self):
        """Snapshot of this pad's current settings, used to remember it
        across bank switches (widgets are reused, not recreated)."""
        if not self.filepath:
            return None
        return {
            "filepath": self.filepath,
            "target_rate": self.target_rate.get(),
            "pitch_cents": self.pitch_cents.get(),
            "mono": self.mono_var.get(),
            "from_sync": "[on device]" in self.label.cget("text"),
            "display_name": self.display_name,
            "wavetable": self.wavetable,
            "wt_patch": self.wt_patch.get(),
            "wt_poly": self.wt_poly.get(),
        }

    def apply_state(self, state):
        """Restores a previously saved state (or clears the pad if None) -
        used when switching banks, instead of destroying/recreating widgets."""
        if not state or not state.get("filepath"):
            self.clear_pad()
            return
        if not os.path.exists(state["filepath"]):
            # The file this pad used to point to is gone (deleted outside
            # the app, a stale preset reference, etc.) - clear the pad
            # instead of leaving it in a broken half-loaded state where
            # rate detection etc. would silently fail.
            logger.warning(
                f"PAD_{self.pad_num}: referenced file no longer exists, clearing pad: "
                f"{state['filepath']}"
            )
            self.clear_pad()
            return
        self.set_file(
            state["filepath"],
            from_sync=state.get("from_sync", False),
            display_name=state.get("display_name"),
        )
        # set_file() auto-detects rate and resets pitch to 0 - restore the
        # saved values on top of that:
        rate = state.get("target_rate")
        if rate:
            self.target_rate.set(rate)
        cents = state.get("pitch_cents", 0)
        self.pitch_cents.set(cents)
        self.pitch_entry.delete(0, tk.END)
        self.pitch_entry.insert(0, str(cents))
        self.mono_var.set(state.get("mono", False))
        self.wavetable = state.get("wavetable")
        patch = state.get("wt_patch", "Init")
        self.wt_patch.set(patch if patch in PRM_TEMPLATES else "Init")
        self.wt_poly.set(state.get("wt_poly", False))
        self._sync_wavetable_ui()
        self.update_mono_lock()
        self.update_warning()

    def clear_pad(self):
        """Resets this pad's widgets to the empty state, without destroying
        them (they're reused across bank switches)."""
        self.filepath = None
        self.display_name = None
        self.label.config(text="No sample loaded", fg=FG_MUTED)
        self._sync_pad_buttons()
        self.mini_wave_canvas.delete("all")
        self.target_rate.set(44100)
        self.pitch_cents.set(0)
        self.pitch_entry.delete(0, tk.END)
        self.pitch_entry.insert(0, "0")
        self.mono_var.set(False)
        self.wavetable = None
        self.wt_patch.set("Init")
        self.wt_poly.set(False)
        self._sync_wavetable_ui()  # ends in _sync_pad_buttons()
        self.update_mono_lock()

    def _bind_internal_drag(self, widget):
        """Wires up the drag-to-swap gesture on a passive (non-interactive)
        widget - the sample name label and the panel's border/title area
        are good handles since neither does anything else on click."""
        try:
            widget.config(cursor="fleur")
        except tk.TclError:
            pass  # not every platform has this cursor name; harmless if so
        widget.bind("<ButtonPress-1>", self._on_internal_drag_start)
        widget.bind("<B1-Motion>", self._on_internal_drag_motion)
        widget.bind("<ButtonRelease-1>", self._on_internal_drag_end)

    def _on_internal_drag_start(self, event):
        self._internal_drag_started_at = (event.x_root, event.y_root)

    def _on_internal_drag_motion(self, event):
        start = getattr(self, "_internal_drag_started_at", None)
        if start is None or not hasattr(self.app, "_pad_at_screen_pos"):
            return
        # Small threshold so a plain click doesn't get treated as a drag.
        if not getattr(self, "_internal_drag_active", False):
            dx, dy = event.x_root - start[0], event.y_root - start[1]
            if (dx * dx + dy * dy) < 36:  # ~6px
                return
            self._internal_drag_active = True
        hovered = self.app._pad_at_screen_pos(event.x_root, event.y_root)
        for pad, slot in self.app.pad_widgets.items():
            if pad == hovered and pad != self.pad_num:
                slot.panel.set_border_color(ACCENT_ORANGE, width=3)
            else:
                color, width = self.app._pad_idle_color(pad)
                slot.panel.set_border_color(color, width=width)

    def _on_internal_drag_end(self, event):
        was_active = getattr(self, "_internal_drag_active", False)
        self._internal_drag_active = False
        self._internal_drag_started_at = None
        if hasattr(self.app, "_clear_all_pad_highlights"):
            self.app._clear_all_pad_highlights()
        if not was_active or not hasattr(self.app, "_pad_at_screen_pos"):
            return
        target = self.app._pad_at_screen_pos(event.x_root, event.y_root)
        if target is not None and target != self.pad_num and hasattr(self.app, "swap_pads"):
            self.app.swap_pads(self.pad_num, target)

    def load_sample(self):
        from pyp6.ui.dialogs.audio_preview import AudioPreviewDialog

        if hasattr(self.app, "stop_playback_waveform"):
            self.app.stop_playback_waveform()
        # Prefer the last folder the user actually browsed to (shared across
        # all pads) over this pad's own sample's folder - that's often a
        # temp folder (trim/chop output), which isn't where the user wants
        # to keep browsing. This also matches the common workflow of loading
        # several samples from the same folder onto multiple pads in a row.
        if _cfg.LAST_SAMPLE_DIR:
            initial_dir = _cfg.LAST_SAMPLE_DIR
        elif self.filepath and os.path.dirname(self.filepath):
            initial_dir = os.path.dirname(self.filepath)
        else:
            initial_dir = None
        dialog = AudioPreviewDialog(self.app.root, initial_dir=initial_dir)
        self.app.root.wait_window(dialog)
        if dialog.selected_path:
            if hasattr(self.app, "_push_undo"):
                self.app._push_undo()
            self.set_file(dialog.selected_path, display_name=dialog.selected_display_name)
            # Use the folder the user actually browsed to, not
            # os.path.dirname(selected_path) - if the sample was trimmed,
            # selected_path points into the app temp folder, which
            # would otherwise corrupt LAST_SAMPLE_DIR for every pad after.
            chosen_dir = getattr(dialog, "current_dir", None) or os.path.dirname(
                dialog.selected_path
            )
            _cfg.LAST_SAMPLE_DIR = chosen_dir
            save_last_sample_dir(chosen_dir)

    def open_chop(self):
        from pyp6.ui.dialogs.chop import ChopDialog

        if hasattr(self.app, "stop_playback_waveform"):
            self.app.stop_playback_waveform()
        initial_dir = _cfg.LAST_SAMPLE_DIR if _cfg.LAST_SAMPLE_DIR else None
        dialog = ChopDialog(self.app.root, initial_dir=initial_dir)
        self.app.root.wait_window(dialog)
        if dialog.result_path:
            if hasattr(self.app, "_push_undo"):
                self.app._push_undo()
            self.set_file(dialog.result_path)
            self.target_rate.set(dialog.rate_var.get())
            self.update_warning()
            chosen_dir = dialog.current_dir
            _cfg.LAST_SAMPLE_DIR = chosen_dir
            save_last_sample_dir(chosen_dir)

    def effective_mono(self):
        """Whether this pad should be treated as mono - either because the
        active bank's 'Force Mono (this bank)' switch is on, or because
        this pad's own Mono checkbox is checked."""
        bank = self.app.current_bank.get() if hasattr(self.app, "current_bank") else None
        global_force = (
            self.app.bank_force_mono(bank)
            if bank and hasattr(self.app, "bank_force_mono")
            else False
        )
        return global_force or self.mono_var.get()

    def update_mono_lock(self):
        """Greys out this pad's own Mono checkbox while the active bank's
        Force Mono switch is on (it's already forced, so the individual
        choice doesn't matter until that bank's switch is off again)."""
        bank = self.app.current_bank.get() if hasattr(self.app, "current_bank") else None
        global_force = (
            self.app.bank_force_mono(bank)
            if bank and hasattr(self.app, "bank_force_mono")
            else False
        )
        self.mono_cb.config(state="disabled" if global_force else "normal")

    def on_mono_changed(self):
        self.update_warning()
        if hasattr(self.app, "update_storage_display"):
            self.app.update_storage_display()
        pass  # pedalboard handles mono conversion at export time

    def on_rate_changed(self, _value=None):
        self.update_warning()
        if hasattr(self.app, "update_storage_display"):
            self.app.update_storage_display()

    def _current_max_seconds(self):
        """Max sample length this pad's current target rate allows (based on
        the original file's channel count, unless Force Mono overrides it),
        same rule as check_duration_warning."""
        if not self.filepath:
            return None
        try:
            _, _, channels = get_wav_info(self.filepath)
        except Exception:
            return None
        force_mono = self.effective_mono()
        ch_key = 1 if (force_mono or channels == 1) else 2
        return MAX_SECONDS.get((self.target_rate.get(), ch_key))

    def _refresh_main_view_if_active(self):
        """Keeps the main waveform area in step with this pad's contents.

        Rebuilding a wavetable replaces the pad but leaves whatever the main
        display was already showing - so a table rebuilt with fewer families
        kept the old zone map on screen. Only touches the display when this
        pad is the one it is showing.
        """
        if getattr(self.app, "_wave_view_pad", None) != self.pad_num:
            return
        zones = self._wavetable_zones()
        if zones and hasattr(self.app, "show_wavetable_zones"):
            self.app.show_wavetable_zones(
                self.pad_num, zones, os.path.basename(self.filepath or "") or "Wavetable"
            )
        elif getattr(self.app, "main_wave_zones", None) and hasattr(
            self.app, "clear_playback_waveform"
        ):
            # Was a wavetable pad a moment ago and is not one any more.
            self.app.clear_playback_waveform()

    def _sync_pad_buttons(self):
        """Sets the state of all five pad buttons. Every button always stays
        in the row - greyed out reads as clearly as gone, and the row keeps
        its shape across all four pad states.

        Load and Chop replace the pad's contents, and doing that silently over
        an existing sample is how work gets lost, so a filled pad locks them.
        Ejecting first makes the destructive step explicit.

        Synth is the exception. On a wavetable pad it reopens the generator
        with the current settings and rebuilds in place, so it destroys
        nothing and is the only quick route back to the parameters.
        """
        if not hasattr(self, "synth_btn"):
            return  # called before __init__ finished building the row
        filled = bool(self.filepath)
        is_wt = bool(self.wavetable)

        for btn in (self.load_btn, self.chop_btn):
            btn.config_state("disabled" if filled else "normal")
        self.synth_btn.config_state("normal" if (not filled) or is_wt else "disabled")
        for btn in (self.play_btn, self.remove_btn):
            btn.config_state("normal" if filled else "disabled")

    WT_AUDITION_REPEATS = 2

    def _expand_wavetable_sweep(self, data):
        """Repeats every segment for playback in the app.

        Each segment holds a whole number of cycles, so playing one twice in
        a row is seamless and leaves the pitch untouched - it only gives the
        ear more than 15 ms per waveform. Purely an audition aid: the file on
        disk and on the device is not affected.

        Doing this in the file instead is not an option. Segment length would
        have to double to 1348 frames, and 255 of those is 7.8 s, past the
        P-6's 5.9 s per-sample limit.
        """
        reps = self.WT_AUDITION_REPEATS
        if not self.wavetable or reps < 2:
            return data
        L = (self.wavetable.get("meta") or {}).get("L")
        if not L or len(data) < L * WT_SEGMENTS:
            return data
        tail = data.shape[1:]
        seg = data[: L * WT_SEGMENTS].reshape((WT_SEGMENTS, L) + tail)
        return np.repeat(seg, reps, axis=0).reshape((-1,) + tail)

    def _wavetable_zones(self):
        """Family names plus how many segments each one owns, or None."""
        if not self.wavetable:
            return None
        meta = self.wavetable.get("meta") or {}
        fams, counts = meta.get("families"), meta.get("counts")
        if not fams or not counts or len(fams) != len(counts):
            return None
        return {"families": list(fams), "counts": list(counts)}

    def _mirror_to_main_waveform(self, samples, fs, offset_frac=0.0):
        if not hasattr(self.app, "show_playback_waveform"):
            return
        name = os.path.basename(self.filepath) if self.filepath else ""
        self.app.show_playback_waveform(
            samples,
            fs,
            name,
            self._current_max_seconds(),
            source_path=self.filepath,
            zones=self._wavetable_zones(),
            offset_frac=offset_frac,
        )
        if hasattr(self.app, "highlight_playing_pad"):
            self.app.highlight_playing_pad(self.pad_num)

    def open_waveform_view(self, event=None):
        if self.wavetable:
            # No trim/fade editor for a wavetable - that raster is the whole
            # point. Show the zone map in the main waveform area instead, so
            # the click still answers "what is on this pad".
            zones = self._wavetable_zones()
            if zones and hasattr(self.app, "show_wavetable_zones"):
                self.app.show_wavetable_zones(self.pad_num, zones, self.display_name or "Wavetable")
            return
        if not (self.filepath and os.path.exists(self.filepath)):
            return
        name = self.display_name or os.path.basename(self.filepath)
        if hasattr(self.app, "stop_playback_waveform"):
            self.app.stop_playback_waveform()
        from pyp6.ui.dialogs.pad import PadWaveformViewDialog

        PadWaveformViewDialog(self.app.root, self.app, self.pad_num, self.filepath, name)

    def toggle_play_pad(self):
        currently_playing = getattr(
            self.app, "_currently_playing_pad", None
        ) == self.pad_num and getattr(self.app, "main_wave_is_playing", False)
        if currently_playing:
            self.app.stop_playback_waveform()
        else:
            self.play_sample()

    def set_play_button_state(self, is_playing):
        """Shows a grey Stop square in place of the green Play triangle
        while this pad is the one currently playing."""
        if is_playing:
            self.play_btn.bg_color = BG_INPUT
            self.play_btn.text = "\u25a0"
        else:
            # BTN_GREEN, not ACCENT_GREEN: this reassigns the fill at runtime,
            # so using the raw accent here would undo the readable button
            # color the moment a pad was played and stopped once.
            self.play_btn.bg_color = BTN_GREEN
            self.play_btn.text = "\u25b6"
        self.play_btn._draw()

    def play_sample(self):
        """Plays this pad's sample exactly as it will actually sound once
        exported: target rate, pitch, and mono all applied (if pydub is
        available)."""
        if not (self.filepath and os.path.exists(self.filepath)):
            return
        rate = self.target_rate.get()
        cents = self.pitch_cents.get()
        force_mono = self.effective_mono()

        try:
            _, orig_rate, _ = get_wav_info(self.filepath)
        except Exception:
            orig_rate = None

        needs_conversion = (orig_rate is not None and rate != orig_rate) or cents or force_mono
        if self.wavetable:
            # Written at exactly the rate and length the P-6 expects. Resampling,
            # pitch shifting or mono folding would all move the segment raster
            # the START control steps through.
            needs_conversion = False

        try:
            sd.stop()
            if needs_conversion and AUDIO_AVAILABLE:
                import pedalboard as _pb_mod
                from pedalboard.io import AudioFile

                from pyp6.audio.conversion import apply_pitch_shift as _pitch_shift

                with AudioFile(self.filepath) as f:
                    audio = f.read(f.frames)  # (channels, samples) float32
                    file_sr = f.samplerate

                if cents:
                    audio = _pitch_shift(audio, file_sr, cents)
                if force_mono and audio.shape[0] > 1:
                    audio = audio.mean(axis=0, keepdims=True)
                if rate != file_sr:
                    audio = _pb_mod.Resample(target_sample_rate=rate)(audio, file_sr)

                # sounddevice expects (samples, channels) or (samples,) for mono
                samples = audio.T
                if samples.ndim > 1 and samples.shape[1] == 1:
                    samples = samples[:, 0]
                self._play_buffer(samples, rate)
            else:
                # Nothing to convert (or pydub unavailable) - play as-is,
                # still respecting Force Mono (pure numpy, no pydub needed).
                data, fs = sf.read(self.filepath, dtype="float32")
                if force_mono and data.ndim > 1:
                    data = data.mean(axis=1)
                data = self._expand_wavetable_sweep(data)
                self._play_buffer(data, fs)
        except Exception as e:
            dark_showerror("Playback Error", str(e))

    def _play_buffer(self, samples, fs):
        """Sends a buffer to the device, honouring a pending seek.

        The main waveform view always shows the whole sample, so the buffer
        handed to the view is the full one - only what goes to the sound
        device is trimmed, and the playhead is backdated by the same amount.
        """
        frac = min(max(getattr(self, "_seek_frac", 0.0), 0.0), 0.999)
        self._seek_frac = 0.0
        start = int(len(samples) * frac)
        play_audio(samples[start:] if start else samples, fs)
        self._mirror_to_main_waveform(samples, fs, offset_frac=frac)

    def play_from(self, frac):
        """Plays this pad starting at `frac` through the sample. Used by the
        click-to-seek on the main waveform view."""
        if not self.filepath:
            return
        self._seek_frac = frac
        self.play_sample()  # already begins with sd.stop()

    def update_mini_waveform(self):
        """Small static waveform preview for this pad - no playhead, just a
        quick visual glance at what's loaded. The part that exceeds the
        P-6's length limit for the current rate/pitch/mono settings is
        shaded orange, exactly like the big waveform views; the trace
        itself always stays the normal waveform color. Shows both channels
        stacked when the sample is stereo (unless Force Mono is on)."""
        self._mini_wave_cache = None
        self.mini_wave_canvas.delete("all")
        if self.wavetable:
            self._draw_wavetable_info()
            return
        if not self.filepath or not os.path.exists(self.filepath):
            return
        try:
            data, fs = sf.read(self.filepath, dtype="float32")
            if len(data) == 0:
                return
        except Exception:
            return
        force_mono = self.effective_mono()
        cut_frac = compute_truncate_fraction(
            self.filepath, self.target_rate.get(), self.pitch_cents.get(), force_mono
        )
        self._mini_wave_cache = (data, force_mono, cut_frac)
        self._redraw_mini_waveform_at_current_width()

    def _redraw_mini_waveform_at_current_width(self, event=None):
        """Draws the cached mini-waveform data at whatever width the canvas
        currently reports. Bound to <Configure> instead of calling
        update_idletasks() (which forces an expensive synchronous X11
        round-trip on Linux) - Tk fires <Configure> naturally once the real
        layout size is known, so this just redraws cheaply from cache."""
        if getattr(self, "wavetable", None):
            # Wavetable pads show text, not a trace, and the text has to be
            # re-measured whenever the panel width changes.
            self._draw_wavetable_info()
            return
        if not getattr(self, "_mini_wave_cache", None):
            return
        data, force_mono, cut_frac = self._mini_wave_cache
        width_px = max(self.mini_wave_canvas.winfo_width(), self.mini_wave_width)
        color = WAVE_COLOR
        if data.ndim > 1 and data.shape[1] >= 2 and not force_mono:
            half_h = self.mini_wave_height / 2.0
            draw_waveform_on_canvas(
                self.mini_wave_canvas,
                data[:, 0],
                0.0,
                1.0,
                width_px,
                half_h,
                color=color,
                tag="waveform",
                y_offset=0,
                clear=True,
            )
            draw_waveform_on_canvas(
                self.mini_wave_canvas,
                data[:, 1],
                0.0,
                1.0,
                width_px,
                half_h,
                color=color,
                tag="waveform",
                y_offset=half_h,
                clear=False,
            )
            self.mini_wave_canvas.create_line(
                0, half_h, width_px, half_h, fill=BORDER_COLOR, width=1, tags="waveform"
            )
        else:
            mono = data.mean(axis=1) if data.ndim > 1 else data
            draw_waveform_on_canvas(
                self.mini_wave_canvas, mono, 0.0, 1.0, width_px, self.mini_wave_height, color=color
            )
        # Drawn last so it sits on top of the trace. The mini view is never
        # zoomed, so the fraction maps straight onto the canvas width.
        self.mini_wave_canvas.delete("truncate")
        if cut_frac is not None:
            draw_truncate_overlay(
                self.mini_wave_canvas, cut_frac * width_px, width_px, self.mini_wave_height
            )

    def remove_sample(self):
        if self.filepath:
            if hasattr(self.app, "_push_undo"):
                self.app._push_undo()
            bank = self.app.current_bank.get()
            pad_path = os.path.join(self.app.import_root, f"BANK_{bank}", f"PAD_{self.pad_num}")
            deleted_any = False
            if os.path.isdir(pad_path):
                try:
                    files_in_pad = [
                        f for f in os.listdir(pad_path) if f.lower().endswith((".wav", ".mp3"))
                    ]
                except Exception as e:
                    files_in_pad = []
                    logger.error(f"Could not read pad folder ({pad_path}): {e}")
                if files_in_pad:
                    file_list_str = ", ".join(files_in_pad)
                    msg_line1 = (
                        "The IMPORT folder for Bank "
                        + bank
                        + ", PAD_"
                        + str(self.pad_num)
                        + " already contains a file ("
                        + file_list_str
                        + ")."
                    )
                    msg_line2 = "Should this file also be permanently deleted?"
                    full_msg = msg_line1 + chr(10) + chr(10) + msg_line2
                    answer = dark_askyesno("Delete Sample on Device?", full_msg)
                    if answer:
                        for fname in files_in_pad:
                            full_path = os.path.join(pad_path, fname)
                            try:
                                os.remove(full_path)
                                deleted_any = True
                            except Exception as e:
                                dark_showerror(
                                    "Deletion Error", f"{fname} could not be deleted: {e}"
                                )
            if deleted_any:
                self.app.show_status(f"PAD_{self.pad_num}: removed from the device.")

        self.clear_pad()
        if hasattr(self.app, "clear_playback_waveform"):
            self.app.clear_playback_waveform()
        if hasattr(self.app, "update_storage_display"):
            self.app.update_storage_display()
        if hasattr(self.app, "update_pad_warnings"):
            self.app.update_pad_warnings()

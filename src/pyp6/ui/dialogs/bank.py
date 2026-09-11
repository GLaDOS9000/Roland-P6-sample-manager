"""Bank management dialogs: ClearBanksDialog, CopyBanksDialog, ImportBankDialog."""

import os
import shutil
import tkinter as tk

from pyp6._theme_vars import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_DARK,
    BG_INPUT,
    BG_PANEL,
    BORDER_LIGHT,
    BTN_GREEN,
    BTN_ORANGE,
    FG_MUTED,
    FG_TEXT,
)
from pyp6.config import (
    derived_temp_path,
    load_last_export_dir,
    save_last_export_dir,
)
from pyp6.constants import BANKS, MAX_UPLOAD_BYTES, PADS, UI_FAMILY
from pyp6.log import logger
from pyp6.ui.dialogs.file import FolderPickerDialog
from pyp6.ui.dialogs_common import (
    center_toplevel_on_parent,
    dark_showerror,
    style_checkbutton,
    style_label,
    style_toplevel,
)
from pyp6.ui.widgets import RoundedButton, RoundedPanel


def _log_timing(label):
    """Stub; the real implementation lives in __main__ and is only active
    when DEBUG_STARTUP is set."""
    pass


class ClearBanksDialog(tk.Toplevel):
    """Pick which banks to empty. Mirrors the Copy Banks dialog's layout on
    purpose - same checkbox grid, same All/None buttons - so the two
    bank-selection flows behave identically.

    Only the active bank starts checked: clearing is bulk destruction of
    work, so defaulting to "everything with samples in it" (as the copy
    dialog does, where that's harmless) would be the wrong way round."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Clear Banks")
        self.geometry("420x380")
        self.minsize(420, 380)
        style_toplevel(self)
        self.confirmed = False

        outer = tk.Frame(self, bg=BG_DARK, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        banks_panel = RoundedPanel(
            outer,
            title="Banks to Clear",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        banks_panel.pack(fill="x", pady=(0, 12))

        active = self.app.current_bank.get()
        self.bank_vars = {}
        grid = tk.Frame(banks_panel.body, bg=BG_PANEL)
        grid.pack(fill="x", pady=(8, 6))
        for i, bank in enumerate(BANKS):
            var = tk.BooleanVar(value=(bank == active))
            var.trace_add("write", lambda *a: self._update_summary())
            self.bank_vars[bank] = var
            suffix = "  (active)" if bank == active else ""
            if not self.app.bank_has_samples(bank):
                suffix += "  \u2013 empty"
            cb = tk.Checkbutton(grid, text=f"Bank {bank}{suffix}", variable=var)
            style_checkbutton(cb)
            cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)

        select_row = tk.Frame(banks_panel.body, bg=BG_PANEL)
        select_row.pack(fill="x", pady=(4, 8))
        all_btn = RoundedButton(
            select_row,
            text="All",
            command=lambda: self._set_all(True),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        all_btn.pack(side="left", padx=(0, 4))
        none_btn = RoundedButton(
            select_row,
            text="None",
            command=lambda: self._set_all(False),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        none_btn.pack(side="left")

        info_panel = RoundedPanel(
            outer,
            title="What This Does",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        info_panel.pack(fill="x", pady=(0, 12))
        self.summary_label = tk.Label(
            info_panel.body, anchor="w", justify="left", wraplength=350, text=""
        )
        style_label(self.summary_label, bg=BG_PANEL, font=(UI_FAMILY, 9))
        self.summary_label.pack(fill="x", pady=(8, 4))
        hint = tk.Label(
            info_panel.body,
            anchor="w",
            justify="left",
            wraplength=350,
            text="Only the pads in the app are emptied - no files on disk or on "
            "the P-6 are touched. Undo (Ctrl+Z) restores everything.",
        )
        style_label(hint, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        hint.pack(fill="x", pady=(0, 8))

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", side="bottom")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        cancel_btn.pack(side="right", padx=4)
        self.clear_btn = RoundedButton(
            btn_row,
            text="Clear",
            command=self.on_clear,
            bg=BTN_ORANGE,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=90,
        )
        self.clear_btn.pack(side="right", padx=4)

        self._update_summary()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _set_all(self, value):
        for var in self.bank_vars.values():
            var.set(value)

    def selected_banks(self):
        return [b for b, var in self.bank_vars.items() if var.get()]

    def _update_summary(self):
        banks = self.selected_banks()
        with_samples = [b for b in banks if self.app.bank_has_samples(b)]
        if not banks:
            self.summary_label.config(text="No banks selected.", fg=FG_MUTED)
        elif not with_samples:
            self.summary_label.config(
                text=f"{', '.join(banks)} selected - all of them are already empty.", fg=FG_MUTED
            )
        else:
            pad_word = "bank" if len(with_samples) == 1 else "banks"
            self.summary_label.config(
                text=f"Clears {len(with_samples)} loaded {pad_word}: {', '.join(with_samples)}.",
                fg=ACCENT_ORANGE,
            )
        if hasattr(self, "clear_btn"):
            self.clear_btn.config_state("normal" if banks else "disabled")

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

    def on_clear(self):
        if not self.selected_banks():
            return
        self.confirmed = True
        self.destroy()

    def on_cancel(self):
        self.confirmed = False
        self.destroy()


class CopyBanksDialog(tk.Toplevel):
    """Pick which banks to export, with a live total-size readout that
    updates as banks are checked/unchecked - so you can see up front how
    much you're about to transfer, before committing to it."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Copy Banks to P6")
        self.geometry("420x420")
        self.minsize(420, 420)
        style_toplevel(self)
        self.confirmed = False

        outer = tk.Frame(self, bg=BG_DARK, padx=16, pady=16)
        outer.pack(fill="both", expand=True)

        banks_panel = RoundedPanel(
            outer,
            title="Banks to Copy",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        banks_panel.pack(fill="x", pady=(0, 12))

        self.bank_vars = {}
        grid = tk.Frame(banks_panel.body, bg=BG_PANEL)
        grid.pack(fill="x", pady=(8, 6))
        for i, bank in enumerate(BANKS):
            has_samples = self.app.bank_has_samples(bank)
            var = tk.BooleanVar(value=has_samples)
            var.trace_add("write", lambda *a: self._update_total())
            self.bank_vars[bank] = var
            cb = tk.Checkbutton(grid, text=f"Bank {bank}", variable=var)
            style_checkbutton(cb)
            cb.config(bg=BG_PANEL, activebackground=BG_PANEL)
            cb.grid(row=i // 2, column=i % 2, sticky="w", padx=6, pady=2)

        select_row = tk.Frame(banks_panel.body, bg=BG_PANEL)
        select_row.pack(fill="x", pady=(4, 8))
        all_btn = RoundedButton(
            select_row,
            text="All",
            command=lambda: self._set_all(True),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        all_btn.pack(side="left", padx=(0, 4))
        none_btn = RoundedButton(
            select_row,
            text="None",
            command=lambda: self._set_all(False),
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=70,
            height=24,
            font=(UI_FAMILY, 8),
        )
        none_btn.pack(side="left")

        total_panel = RoundedPanel(
            outer,
            title="Total to Transfer",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        total_panel.pack(fill="x", pady=(0, 12))
        self.total_label = tk.Label(total_panel.body, text="", anchor="w")
        style_label(self.total_label, bg=BG_PANEL, font=(UI_FAMILY, 14, "bold"))
        self.total_label.pack(fill="x", pady=(8, 8))

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", side="bottom")
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        cancel_btn.pack(side="right", padx=4)
        self.copy_btn = RoundedButton(
            btn_row,
            text="Copy",
            command=self.on_copy,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=90,
        )
        self.copy_btn.pack(side="right", padx=4)

        self._update_total()
        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
        self.transient(parent)
        center_toplevel_on_parent(self, parent)
        self._safe_grab()

    def _set_all(self, value):
        for var in self.bank_vars.values():
            var.set(value)

    def selected_banks(self):
        return [b for b, var in self.bank_vars.items() if var.get()]

    def _update_total(self):
        banks = self.selected_banks()
        total_bytes = sum(self.app._bank_size_bytes(b) for b in banks)
        mb = total_bytes / (1024 * 1024)
        limit_mb = MAX_UPLOAD_BYTES / (1024 * 1024)
        over = total_bytes > MAX_UPLOAD_BYTES
        color = ACCENT_RED if over else FG_TEXT
        n = len(banks)
        bank_word = "bank" if n == 1 else "banks"
        self.total_label.config(
            text=f"{mb:.2f} MB across {n} {bank_word}"
            + (f"  (over {limit_mb:.0f} MB!)" if over else ""),
            fg=color,
        )
        if hasattr(self, "copy_btn"):
            self.copy_btn.config_state("normal" if banks else "disabled")

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

    def on_copy(self):
        if not self.selected_banks():
            return
        self.confirmed = True
        self.destroy()

    def on_cancel(self):
        self.confirmed = False
        self.destroy()


class ImportBankDialog(tk.Toplevel):
    """Walks the user through the P-6's own "export to computer" hardware
    procedure, then imports whatever bank ends up in the resulting EXPORT
    folder onto the app's currently active bank.

    Folder layout: confirmed against real hardware, the device writes

        EXPORT/BANK_<letter>/PAD_<n>/<name>.WAV

    i.e. it mirrors the IMPORT side, with a bank level in between. The
    scan below was originally written before that was known and only
    handled a flat "PAD_1.WAV" or a "PAD_n/*.wav" directly under the
    selected folder - so picking the drive, or even the EXPORT folder
    itself, found nothing and left Import greyed out. It now walks down
    through the EXPORT and BANK_x levels on its own, and still accepts
    being pointed straight at the folder that holds the pads.

    PRM files aren't parsed (undocumented, proprietary format) - only the
    audio itself is imported; rate/pitch/mono come in at their defaults."""

    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("Bank from P6")
        self.geometry("560x520")
        self.minsize(560, 520)
        style_toplevel(self)
        self.selected_folder = None

        outer = tk.Frame(self, bg=BG_DARK, padx=18, pady=16)
        outer.pack(fill="both", expand=True)

        steps_panel = RoundedPanel(
            outer,
            title="On the P-6 itself",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        steps_panel.pack(fill="x", pady=(0, 12))
        current_bank = self.app.current_bank.get()
        steps_text = (
            f"1. Connect the P-6 to this computer via USB.\n"
            f"2. Power it OFF first if it's already on.\n"
            f"3. Turn the power ON while holding the bank button "
            f"([A/E]-[D/H]) for the bank you want to bring in - here, "
            f"that's the button for Bank {current_bank}. For banks E-H, "
            f"also hold the SAMPLING button at the same time.\n"
            f"4. Wait about a minute - the step buttons light up on the "
            f"device to show it's getting the drive ready.\n"
            f"5. A \u201cP-6\u201d drive appears on this computer, containing "
            f"an \u201cEXPORT\u201d folder with that bank's samples."
        )
        steps_label = tk.Label(
            steps_panel.body, text=steps_text, anchor="w", justify="left", wraplength=500
        )
        style_label(steps_label, bg=BG_PANEL, font=(UI_FAMILY, 9))
        steps_label.pack(fill="x", pady=(6, 0))

        warning_label = tk.Label(
            outer,
            text=f"Importing will overwrite Bank {current_bank} in the app (undo covers this "
            f"afterward). Per-pad rate/pitch/mono settings aren't stored in the export, so "
            f"they come in at their defaults - only the audio itself is brought over.",
            anchor="w",
            justify="left",
            wraplength=520,
        )
        style_label(warning_label, fg=ACCENT_ORANGE, font=(UI_FAMILY, 8))
        warning_label.pack(fill="x", pady=(0, 12))

        folder_panel = RoundedPanel(
            outer,
            title="EXPORT Folder",
            parent_bg=BG_DARK,
            panel_bg=BG_PANEL,
            border=BORDER_LIGHT,
            radius=14,
            title_fg=ACCENT_BLUE,
        )
        folder_panel.pack(fill="x", pady=(0, 12))
        folder_row = tk.Frame(folder_panel.body, bg=BG_PANEL)
        folder_row.pack(fill="x", pady=(6, 0))
        self.folder_label = tk.Label(
            folder_row,
            text="No folder selected yet. Pick the P-6 drive or its \u201cEXPORT\u201d folder.",
            anchor="w",
        )
        style_label(self.folder_label, bg=BG_PANEL, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.folder_label.pack(side="left", fill="x", expand=True)
        choose_btn = RoundedButton(
            folder_row,
            text="Choose Folder...",
            command=self.choose_folder,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_PANEL,
            width=130,
            height=26,
            font=(UI_FAMILY, 8),
        )
        choose_btn.pack(side="right")

        self.found_label = tk.Label(outer, text="", anchor="w", justify="left", wraplength=520)
        style_label(self.found_label, fg=FG_MUTED, font=(UI_FAMILY, 8))
        self.found_label.pack(fill="x")

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", side="bottom", pady=(12, 0))
        cancel_btn = RoundedButton(
            btn_row,
            text="Cancel",
            command=self.on_cancel,
            bg=BG_INPUT,
            fg=FG_TEXT,
            parent_bg=BG_DARK,
            width=90,
        )
        cancel_btn.pack(side="right", padx=4)
        self.import_btn = RoundedButton(
            btn_row,
            text="Import",
            command=self.on_import,
            bg=BTN_GREEN,
            fg="#FFFFFF",
            parent_bg=BG_DARK,
            width=100,
            state="disabled",
        )
        self.import_btn.pack(side="right", padx=4)

        # Re-use last session's folder if the drive is still mounted and the
        # export is still there, so a repeat import needs no browsing at all.
        # Silent when it doesn't apply - the label already explains what to
        # pick, and an error about a drive that simply isn't plugged in
        # would be noise.
        remembered = load_last_export_dir()
        if (
            remembered
            and self._resolve_export_folder(remembered, preferred_bank=self.app.current_bank.get())[
                0
            ]
        ):
            self._apply_chosen_folder(remembered)

        self.protocol("WM_DELETE_WINDOW", self.on_cancel)
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

    @staticmethod
    def _find_pad_file(folder, pad_num):
        """Looks for one pad's sample, tolerating either a flat
        PAD_1.WAV file or a PAD_1/*.wav subfolder."""
        for ext in (".wav", ".WAV", ".Wav"):
            direct = os.path.join(folder, f"PAD_{pad_num}{ext}")
            if os.path.isfile(direct):
                return direct
        subfolder = os.path.join(folder, f"PAD_{pad_num}")
        if os.path.isdir(subfolder):
            try:
                for fname in sorted(os.listdir(subfolder)):
                    if fname.lower().endswith(".wav"):
                        return os.path.join(subfolder, fname)
            except Exception:
                pass
        return None

    @staticmethod
    def _folder_has_pads(folder):
        return any(ImportBankDialog._find_pad_file(folder, p) for p in PADS)

    @staticmethod
    def _subdirs(folder, name_test):
        try:
            entries = sorted(os.listdir(folder))
        except Exception as e:
            logger.error(f"Could not scan {folder}: {e}")
            return []
        out = []
        for entry in entries:
            full = os.path.join(folder, entry)
            if os.path.isdir(full) and name_test(entry):
                out.append((entry, full))
        return out

    @staticmethod
    def _resolve_export_folder(folder, preferred_bank=None):
        """Finds the folder the pad samples actually live in, walking down
        through the EXPORT and BANK_x levels as needed.

        Returns (folder_or_None, note). Deliberately tolerant about where
        the user points it - the drive, the EXPORT folder and a single
        BANK_x folder are all reasonable things to click, and only one of
        them used to work. Never guesses silently: whenever it descends,
        the note says so, and with several banks present it names the one
        it took."""
        if ImportBankDialog._folder_has_pads(folder):
            return folder, ""
        _log_timing(f"  EXPORT scan: no pads directly in {folder}")

        # One level down into EXPORT, if that's what was selected around.
        base, note = folder, ""
        export_dirs = ImportBankDialog._subdirs(folder, lambda e: e.upper() == "EXPORT")
        if export_dirs:
            base = export_dirs[0][1]
            note = " (found via the EXPORT folder)"
            if ImportBankDialog._folder_has_pads(base):
                return base, note

        # Then the bank level: EXPORT/BANK_<letter>/PAD_<n>/...
        banks = [
            (name, path)
            for name, path in ImportBankDialog._subdirs(
                base, lambda e: e.upper().startswith("BANK_")
            )
            if ImportBankDialog._folder_has_pads(path)
        ]
        _log_timing(f"  EXPORT scan: base={base} usable banks={[n for n, _ in banks]}")
        if not banks:
            return None, ""
        if len(banks) == 1:
            return banks[0][1], f"{note} (from {banks[0][0]})".strip()

        # More than one bank exported: prefer the one whose letter matches
        # the bank we'd import into, otherwise take the first and say which.
        if preferred_bank:
            for name, path in banks:
                if name.upper() == f"BANK_{preferred_bank.upper()}":
                    return path, f"{note} (from {name}, of {len(banks)} banks present)".strip()
        name, path = banks[0]
        others = ", ".join(n for n, _ in banks)
        return path, f"{note} (using {name}; folder contains {others})".strip()

    def choose_folder(self):
        picker = FolderPickerDialog(
            self,
            initial_dir=(load_last_export_dir() or self.app.import_root),
            title="Select the P-6 EXPORT Folder",
        )
        self.wait_window(picker)
        if not picker.selected_dir:
            return
        self._apply_chosen_folder(picker.selected_dir, remember=True)

    def _apply_chosen_folder(self, chosen_dir, remember=False):
        """Resolves `chosen_dir` down to the folder holding the pads and
        updates the dialog. Shared by the Choose Folder button and the
        auto-fill from the last session, so both behave identically."""
        resolved, note = self._resolve_export_folder(
            chosen_dir, preferred_bank=self.app.current_bank.get()
        )
        if resolved is None:
            self.selected_folder = None
            self.folder_label.config(text=chosen_dir, fg=FG_TEXT)
            self.found_label.config(
                text="No pad samples found there. Expected "
                "EXPORT/BANK_x/PAD_n/<name>.WAV - select the P-6 drive, the "
                "\u201cEXPORT\u201d folder, or one BANK folder inside it. If the path "
                "looks right, the device may not have finished writing its export yet.",
                fg=ACCENT_ORANGE,
            )
            self.import_btn.config_state("disabled")
            return False

        self.selected_folder = resolved
        self.folder_label.config(text=self.selected_folder, fg=FG_TEXT)
        found = [p for p in PADS if self._find_pad_file(self.selected_folder, p)]
        pads_str = ", ".join(str(p) for p in found)
        self.found_label.config(text=f"Found samples for pad(s): {pads_str}{note}", fg=ACCENT_GREEN)
        self.import_btn.config_state("normal")
        if remember:
            # Remember what was PICKED, not what it resolved to - see
            # load_last_export_dir() for why.
            save_last_export_dir(chosen_dir)
        return True

    @staticmethod
    def _copy_into_temp(src, bank, pad):
        """Copies a sample off the device into the app's temp folder.

        The device is removable, so anything imported from it has to be
        taken along rather than referenced in place. The name keeps the
        bank/pad it came from so the temp folder stays readable, plus a
        short random part so importing the same bank twice, or two banks
        with identically named samples, can't collide.

        The P-6 stores each pad's settings in a .PRM file sharing the
        sample's base name. Its format is undocumented, so the app can't
        read it - but it copies it along under the copy's new base name, so
        the settings can be carried back to the device on export instead of
        being lost the moment a sample passes through here."""
        base, ext = os.path.splitext(src)
        dest = derived_temp_path(src, f"imp_{bank}{pad}", ext or ".wav")
        shutil.copy2(src, dest)
        for prm_ext in (".PRM", ".prm"):
            prm_src = base + prm_ext
            if os.path.isfile(prm_src):
                try:
                    shutil.copy2(prm_src, os.path.splitext(dest)[0] + ".PRM")
                except Exception as e:
                    logger.error(f"Could not copy settings file {prm_src}: {e}")
                break
        return dest

    def on_import(self):
        if not self.selected_folder:
            return
        bank = self.app.current_bank.get()
        self.app._push_undo()
        self.app.stop_playback_waveform()

        imported, missing, failed = 0, [], []
        for i, pad in enumerate(PADS, 1):
            self.app.show_progress(f"Importing Bank {bank} from P6 \u2026 (Pad {i}/{len(PADS)})")
            src = self._find_pad_file(self.selected_folder, pad)
            if not src:
                missing.append(pad)
                self.app.pad_widgets[pad].clear_pad()
                continue
            try:
                # Copy into the temp folder instead of pointing the pad at
                # the file on the P-6 drive. Referencing the device directly
                # meant the pad emptied itself the moment the drive was
                # unmounted or the device rewrote its EXPORT folder - and a
                # preset saved after that silently stored those banks empty.
                self.app.pad_widgets[pad].set_file(
                    self._copy_into_temp(src, bank, pad), display_name=os.path.basename(src)
                )
                imported += 1
            except Exception as e:
                # One unreadable/corrupt file on the device must not abort
                # the whole import and leave the remaining pads untouched
                # with self.app.slots never re-synced below.
                logger.error(f"Could not import PAD_{pad} from {src}: {e}")
                failed.append(pad)
                self.app.pad_widgets[pad].clear_pad()

        self.app.slots[bank] = {p: self.app.pad_widgets[p].get_state() for p in PADS}
        self.app.update_storage_display()
        self.app.update_pad_warnings()

        if failed:
            dark_showerror(
                "Some Pads Could Not Be Imported",
                "These pads' files could not be read:\n" + "\n".join(f"PAD_{p}" for p in failed),
                parent=self,
            )
        if missing:
            missing_str = ", ".join(str(p) for p in missing)
            self.app.show_status(
                f"Bank {bank}: {imported} pad(s) imported, no sample found for pad(s) {missing_str}.",
                kind="warning",
            )
        else:
            self.app.show_status(f"Bank {bank}: {imported} pad(s) imported from the P-6.")
        self.destroy()

    def on_cancel(self):
        self.destroy()

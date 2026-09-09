"""Entry point for ``python -m pyp6`` and the ``pyp6`` console script.

Startup profiling. This was added to track down the slow window layout on
Wayland/XWayland and is kept around in case that needs revisiting, but it
is off by default so normal runs don't print diagnostics or pay for the
per-draw timing calls. Enable with:  PYP6_DEBUG=1 python3 -m pyp6
"""

import time as _time
import os as _os

_t_start = _time.perf_counter()

DEBUG_STARTUP = bool(_os.environ.get("PYP6_DEBUG"))

_PERF = {
    "panel_redraws": 0, "panel_redraw_time": 0.0,
    "button_draws": 0, "button_draw_time": 0.0,
    "dropdown_draws": 0, "dropdown_draw_time": 0.0,
}


def _log_timing(label):
    if DEBUG_STARTUP:
        print(f"[startup] {label}: {_time.perf_counter() - _t_start:6.3f}s elapsed")


def _log_perf_counters():
    if not DEBUG_STARTUP:
        return
    print("[startup] --- drawing breakdown ---")
    print(f"[startup]   RoundedPanel._redraw : {_PERF['panel_redraws']:5d} calls, "
          f"{_PERF['panel_redraw_time']:6.3f}s total")
    print(f"[startup]   RoundedButton._draw  : {_PERF['button_draws']:5d} calls, "
          f"{_PERF['button_draw_time']:6.3f}s total")
    print(f"[startup]   RoundedDropdown._draw: {_PERF['dropdown_draws']:5d} calls, "
          f"{_PERF['dropdown_draw_time']:6.3f}s total")


import os
import sys
import subprocess
_log_timing("stdlib imports (batch 1)")

if sys.platform.startswith("win"):
    # Every subprocess call (our own ffprobe lookups, and pydub's internal
    # ffmpeg calls for anything beyond plain WAV) launches a console
    # sub-process. A normal python.exe run has a console to attach to, so
    # this is invisible - but a PyInstaller --windowed/--noconsole build has
    # none, and Windows then briefly pops up a NEW console window for each
    # one before it closes. With MP3 folders that's one flash per file (the
    # "Haufen von Fenstern" behavior), and in some cases the console
    # allocation itself can make the child process fail to run correctly at
    # all, which lines up with MP3s not playing/showing a waveform. Patching
    # subprocess.Popen once, globally, fixes this for every caller
    # (including inside pydub, which we don't otherwise control) without
    # having to fix each individual call site.
    _original_popen_init = subprocess.Popen.__init__

    def _no_console_popen_init(self, *args, **kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
        _original_popen_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _no_console_popen_init

import tkinter as tk
_log_timing("tkinter imported")

# Optional: enables dragging sample files from the OS file manager
# straight onto a pad. Not a hard requirement - without it the app runs
# exactly as before, just without that one feature.
#   pip install tkinterdnd2
# PyInstaller note: this package ships native Tcl extension files, not
# just .py - PyInstaller won't find them automatically. Build with:
#   pyinstaller --collect-data tkinterdnd2 ...
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    DND_AVAILABLE = True
    DND_IMPORT_ERROR = None
except ImportError as e:
    # Keep the reason. Swallowing it entirely meant a missing (or broken)
    # tkinterdnd2 looked exactly like drag & drop being switched off: no
    # message anywhere, no registration, no drag highlight, nothing in the
    # debug log either - just a feature that silently wasn't there.
    DND_AVAILABLE = False
    DND_IMPORT_ERROR = str(e)
    DND_FILES = None
    TkinterDnD = None
_log_timing("tkinterdnd2 import attempted"
            + ("" if DND_AVAILABLE else f" - NOT AVAILABLE: {DND_IMPORT_ERROR}"))

# The logo, embedded so the app needs no companion file - a lone .png next
# to the script goes missing the moment someone moves just the .py, and the
# PyInstaller build no longer has to bundle it either. 128x92, reduced to a
# 32-colour palette: visually identical here, a fifth of the size.
PYP6_LOGO_PNG = (
    "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"
)


def _verify_ui_font(root):
    """Warns (to the console only) if the chosen UI font family isn't
    actually installed. A missing family is resolved by a substitution
    search on every distinct size/weight combination, which on X11 is slow
    enough to visibly delay window construction."""
    from pyp6.constants import UI_FAMILY
    try:
        import tkinter.font as tkfont
        available = set(tkfont.families(root))
        if UI_FAMILY not in available:
            print(f"[startup] WARNING: UI font '{UI_FAMILY}' is not installed - "
                  f"falling back (this can noticeably slow down window drawing).")
            for candidate in ("DejaVu Sans", "Liberation Sans", "Noto Sans",
                              "FreeSans", "Helvetica", "Arial"):
                if candidate in available:
                    print(f"[startup] Suggestion: '{candidate}' is available on this system.")
                    break
    except Exception:
        pass


def check_startup_dependencies(root):
    """One clear, consolidated notice at launch instead of the user only
    finding out piecemeal via different error messages the first time each
    affected feature is touched."""
    from pyp6.audio.playback import PYDUB_AVAILABLE, FFMPEG_AVAILABLE
    import pyp6.audio.playback as _pb
    from pyp6.ui.dialogs_common import dark_showwarning
    if not PYDUB_AVAILABLE:
        dark_showwarning(
            "pydub not found",
            "The Python package 'pydub' was not found.\n\n"
            "The following will not work:\n"
            "- Sample rate, pitch and mono conversion on export\n"
            "- The Chop feature (building multisamples)\n"
            "- MP3 files (loading, previewing, length display)\n\n"
            "WAV files can still be loaded and exported unchanged.\n"
            "Install with: pip install pydub",
            parent=root
        )
        _pb._pydub_warning_shown = True  # already told them - don't nag again per-feature
    elif not FFMPEG_AVAILABLE:
        dark_showwarning(
            "ffmpeg not found",
            "pydub is installed, but ffmpeg was not found (neither on PATH "
            "nor at /usr/bin/ffmpeg).\n\n"
            "The following will not work:\n"
            "- MP3 files (loading, previewing, length display)\n"
            "- Some internal format checks\n\n"
            "WAV files including rate/pitch/mono conversion and Chop usually still "
            "work, since those don't require ffmpeg.\n"
            "Install with e.g.: apt install ffmpeg / brew install ffmpeg",
            parent=root
        )


def main():
    _log_timing("module fully loaded (all imports + class/function defs)")

    import pyp6.config as _cfg
    _cfg.LAST_SAMPLE_DIR = _cfg.load_last_sample_dir()
    _cfg.apply_saved_ffmpeg_overrides()
    _cfg.apply_saved_storage_threshold()

    # Wire performance counters into widget module so draws are tracked.
    from pyp6.ui import widgets as _widgets
    _widgets._PERF = _PERF

    # Wire module-level variables into model.app before constructing the app.
    import pyp6.model.app as _app_mod
    _app_mod.DEBUG_STARTUP = DEBUG_STARTUP
    _app_mod._log_timing = _log_timing
    _app_mod.DND_AVAILABLE = DND_AVAILABLE
    _app_mod.DND_FILES = DND_FILES
    _app_mod.PYP6_LOGO_PNG = PYP6_LOGO_PNG

    # Wire DND state into the about helpers bridge.
    import pyp6._about_helpers as _ah
    _ah.DND_AVAILABLE = DND_AVAILABLE
    _ah.DND_IMPORT_ERROR = DND_IMPORT_ERROR

    root = None
    if DND_AVAILABLE:
        try:
            root = TkinterDnD.Tk()
        except Exception as e:
            print(f"tkinterdnd2 failed to initialize ({e}), continuing without drag & drop")
            _app_mod.DND_AVAILABLE = False
            _ah.DND_AVAILABLE = False
    if root is None:
        root = tk.Tk()
    _log_timing("tk.Tk() root window created")
    _verify_ui_font(root)
    check_startup_dependencies(root)
    _log_timing("dependency check done")

    from pyp6.model.app import P6ManagerApp
    app = P6ManagerApp(root)
    _log_timing("P6ManagerApp constructed (full UI built)")

    if DEBUG_STARTUP:
        def _count_widgets(w):
            n = 1
            for child in w.winfo_children():
                n += _count_widgets(child)
            return n

        def _count_canvases(w):
            n = 1 if isinstance(w, tk.Canvas) else 0
            for child in w.winfo_children():
                n += _count_canvases(child)
            return n

        print(f"[startup]   widget tree: {_count_widgets(root)} widgets total, "
              f"{_count_canvases(root)} of them Canvas")
    root.update_idletasks()
    _log_timing("root.update_idletasks() done (geometry/layout settled)")
    _log_perf_counters()
    root.update()
    _log_timing("root.update() done (all pending draw commands flushed to the display server)")
    root.mainloop()


if __name__ == "__main__":
    main()

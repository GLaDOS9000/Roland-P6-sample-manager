"""Bridge module for About / Settings dialogs.

The functions here gather runtime info about optional dependencies and
drag-and-drop state.  They are called lazily from SettingsDialog and
AboutDialog.  ``__main__.py`` sets the module-level ``_DND_APP``,
``DND_AVAILABLE`` and ``DND_IMPORT_ERROR`` variables once the Tk root
is up.
"""

import sys
import tkinter as tk

import numpy as np

try:
    import soundfile as sf
except ImportError:
    sf = None

try:
    import sounddevice as sd
except ImportError:
    sd = None

from pyp6 import APP_VERSION
from pyp6.constants import (
    APP_AUTHOR,
    APP_NAME,
    APP_SUBTITLE,
    APP_URL,
    APP_YEAR,
    CONFIG_FILE,
    TEMP_DIR,
)
from pyp6.log import LOG_FILE

# These are set at startup from __main__.py.
DND_AVAILABLE = False
DND_IMPORT_ERROR = None
_DND_APP = None


# -----------------------------------------------------------------------
# helpers
# -----------------------------------------------------------------------


def _module_version(module, dist_name=None):
    """Best-effort version string for an optional dependency.

    Tries __version__ first, then the installed package metadata (pydub,
    for one, ships no __version__ attribute). Never raises - a missing
    version in an About box is cosmetic and must not break the dialog."""
    try:
        v = getattr(module, "__version__", None)
        if v:
            return str(v)
    except Exception:
        pass
    if dist_name:
        try:
            from importlib.metadata import version as _dist_version

            return str(_dist_version(dist_name))
        except Exception:
            pass
    return "installed (version unknown)"


def dnd_is_working():
    return bool(DND_AVAILABLE and getattr(_DND_APP, "_dnd_registered", None))


def dnd_status_text():
    """Reports what drag & drop is ACTUALLY doing, not just whether the
    module imported. Those are different failures with different fixes:
    a missing package is a pip install, a failed registration is a tkdnd
    or compositor problem - and the old text said "active" for both."""
    if not DND_AVAILABLE:
        reason = f" - {DND_IMPORT_ERROR}" if DND_IMPORT_ERROR else ""
        return f"tkinterdnd2 not available (pip install tkinterdnd2){reason}"
    registered = getattr(_DND_APP, "_dnd_registered", None)
    if registered is None:
        return "tkinterdnd2 loaded, drop targets not registered yet"
    if not registered:
        return "tkinterdnd2 loaded, but NO drop target could be registered"
    return "active (" + ", ".join(registered) + ")"


def collect_about_info():
    """(label, value) pairs describing this install, for the About box.

    Also what the About box's Copy button puts on the clipboard, so a bug
    report can be pasted with the exact versions and paths involved -
    which is the whole reason the optional-dependency state is in here."""
    rows = []
    rows.append(("Version", APP_VERSION))
    rows.append(("Author", APP_AUTHOR))
    rows.append(("Copyright", f"\u00a9 {APP_YEAR} {APP_AUTHOR}"))
    rows.append(("Project", APP_URL))
    try:
        rows.append(("Python", f"{sys.version.split()[0]} on {sys.platform}"))
    except Exception:
        pass
    try:
        rows.append(("Tk", str(tk.TkVersion)))
    except Exception:
        pass
    rows.append(("NumPy", _module_version(np, "numpy")))
    rows.append(("soundfile", _module_version(sf, "soundfile")))
    rows.append(("sounddevice", _module_version(sd, "sounddevice")))
    try:
        import pedalboard as _pb_mod

        pb_ver = getattr(_pb_mod, "__version__", "installed")
        rows.append(("pedalboard", pb_ver))
    except Exception:
        rows.append(("pedalboard", "not installed --- Chop/MP3/conversion disabled"))
    rows.append(("Drag & drop", dnd_status_text()))
    rows.append(("Settings file", CONFIG_FILE))
    rows.append(("Temp folder", TEMP_DIR))
    rows.append(("Log file", LOG_FILE))
    return rows


def about_info_as_text():
    lines = [f"{APP_NAME} - {APP_SUBTITLE}"]
    lines += [f"{label}: {value}" for label, value in collect_about_info()]
    return "\n".join(lines)

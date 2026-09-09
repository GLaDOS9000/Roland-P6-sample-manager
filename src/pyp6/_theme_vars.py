"""Active-theme color variables, resolved once at import time.

The original monolith sets BG_DARK, FG_TEXT, ACCENT_BLUE etc. as bare
module-level names via an if/elif chain on the theme preference.  Every UI
module in the package imports them from here, so the rest of the code can
keep using the same bare names without change.

Derived values (BTN_BLUE, WAVE_TEXT_COLOR, TRUNCATE_TINT_STIPPLE) that the
original computed from the theme are also exported here.
"""

import json
import os

from pyp6.constants import CONFIG_FILE, BUTTON_SATURATION
from pyp6.theme import THEMES, fill_for_white_text, readable_on, _relative_luminance


def _load_theme_preference():
    """Reads just the theme preference from config (before the full config
    module is available - colors must be resolved before any widget class
    is imported)."""
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f).get("theme", "dark")
    except Exception:
        return "dark"


THEME = _load_theme_preference()
_palette = THEMES.get(THEME, THEMES["dark"])

# Export every palette key as a module-level variable
BG_DARK = _palette["BG_DARK"]
BG_PANEL = _palette["BG_PANEL"]
BG_INPUT = _palette["BG_INPUT"]
FG_TEXT = _palette["FG_TEXT"]
FG_MUTED = _palette["FG_MUTED"]
ACCENT_BLUE = _palette["ACCENT_BLUE"]
ACCENT_GREEN = _palette["ACCENT_GREEN"]
ACCENT_RED = _palette["ACCENT_RED"]
ACCENT_ORANGE = _palette["ACCENT_ORANGE"]
ACCENT_PURPLE = _palette["ACCENT_PURPLE"]
SELECT_GREEN = _palette["SELECT_GREEN"]
BORDER_COLOR = _palette["BORDER_COLOR"]
BORDER_LIGHT = _palette["BORDER_LIGHT"]
WAVE_BG = _palette["WAVE_BG"]
HOVER_BG = _palette["HOVER_BG"]

# Theme-independent waveform color
WAVE_COLOR = "#1D7A9C"

# Readable version of WAVE_COLOR for small text on WAVE_BG
WAVE_TEXT_COLOR = readable_on(WAVE_COLOR, WAVE_BG, 7.0)

# Density of the orange tint in the truncation overlay. On a dark background
# the same stipple reads far more strongly than on a light one, enough to
# swallow the red end marker where the two overlap - so dark themes get the
# next step down. Decided from BG_DARK's luminance rather than the theme
# name, so a future theme is classified correctly without touching this.
TRUNCATE_TINT_STIPPLE = "gray12" if _relative_luminance(BG_DARK) < 0.2 else "gray25"

# Button fill colors - derived from accents, readable with white text on top.
BTN_BLUE = fill_for_white_text(ACCENT_BLUE)
BTN_GREEN = fill_for_white_text(ACCENT_GREEN)
BTN_RED = fill_for_white_text(ACCENT_RED)
BTN_ORANGE = fill_for_white_text(ACCENT_ORANGE)
BTN_PURPLE = fill_for_white_text(ACCENT_PURPLE)

"""Module-level constants for PyP6."""

import os
import sys

APP_NAME = "PyP6"
APP_SUBTITLE = "Roland AIRA P-6 Sample Manager"
APP_VERSION = "3.0.0"
APP_AUTHOR = "Brian Siemund"
APP_YEAR = "2026"
APP_URL = "https://github.com/j0kerpack/Roland-P6-sample-manager"
# Single source of truth for the version: the window title and the About
# box both read these, so a release bump can't leave one of them stale.

APP_DIR = os.path.expanduser("~/.pyp6")
TEMP_DIR = os.path.join(APP_DIR, "temp")
CONFIG_FILE = os.path.join(APP_DIR, "config.json")

WAVETABLE_DIR = os.path.join(APP_DIR, "wavetables")
# Hand-drawn shapes live here rather than in config.json: each one is a 512
# point array, and a dozen of them would bloat a file that gets read on every
# start. Outside temp/ for the same reason config.json is - clearing temp
# must never destroy something the user cannot redraw.
WAVEFORM_LIB_FILE = os.path.join(APP_DIR, "waveforms.json")

BANKS = [chr(c) for c in range(ord("A"), ord("H") + 1)]
PADS = list(range(1, 7))
MAX_UNDO_STEPS = 5
TARGET_RATES = [44100, 22050, 14700, 11025]
SLICE_COUNTS = [1, 2, 4, 8, 16, 24, 32, 48, 64]
# Chop normalize choices. "Per sample" evens out slices recorded at
# different levels; "Whole file" only lifts the overall level and keeps the
# balance between slices. Mutually exclusive - see build_chop_file().
NORMALIZE_MODES = ["Off", "Per sample", "Whole file"]
NORMALIZE_MODE_KEYS = {"Off": "off", "Per sample": "per_sample", "Whole file": "whole"}
PITCH_MIN_CENTS = -1200
PITCH_MAX_CENTS = 1200
PITCH_STEP_CENTS = 100

MAX_SECONDS = {
    (44100, 1): 5.9, (44100, 2): 2.95,
    (22050, 1): 11.8, (22050, 2): 5.9,
    (14700, 1): 17.8, (14700, 2): 8.9,
    (11025, 1): 23.7, (11025, 2): 11.85,
}

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB soft limit per upload

SAMPLE_RATE = 44100  # Default sample rate

PRESET_MANIFEST_NAME = "preset.json"
PRESET_FORMAT_VERSION = 3  # v3: pads can carry wavetable synth state
#     v2: force_mono moved from one global flag to per-bank

# "Segoe UI" only exists on Windows. Asking for it on Linux/macOS makes the
# font system search its whole database for a family that isn't there and
# then resolve a substitute - and that happens during the layout pass, for
# every distinct size/weight combination. On X11 this is slow enough to add
# many seconds to startup, so pick a family that actually exists instead.
if sys.platform.startswith("win"):
    UI_FAMILY = "Segoe UI"
elif sys.platform == "darwin":
    UI_FAMILY = "Helvetica Neue"
else:
    UI_FAMILY = "DejaVu Sans"  # present on virtually every Linux distribution

MAIN_MIN_W = 1000
# Windows needs more headroom than Linux for the same content: its title
# bar and window borders are taller, and the default UI font renders a few
# pixels larger. 860 was arrived at by testing on an actual Windows box -
# at 835 the bottom row sat too tight.
MAIN_MIN_H = 860 if sys.platform.startswith("win") else 825
# The +N below is the height the RoundedPanel frames add: 32 px each (24
# above the body, 8 below). Without it the button row at the bottom is pushed
# out of the window - pack satisfies the earlier widgets first, and whatever
# is packed last gets what is left over, which can be nothing.
CHOP_MIN_W, CHOP_MIN_H = 1000, 815 + 3 * 32
PREVIEW_MIN_W, PREVIEW_MIN_H = 560, 480 + 32
AUDIO_PREVIEW_MIN_W, AUDIO_PREVIEW_MIN_H = 660, 580 + 2 * 32

# Wavetable synth constants
WT_SR = 44100
WT_SEGMENTS = 255
WT_MAX_SECONDS = 5.9
WT_MAX_SEG_FRAMES = int(WT_MAX_SECONDS * WT_SR) // WT_SEGMENTS   # 1020
WT_PEAK = 0.9
WT_PREVIEW_SECONDS = 5.0
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# name: (base MIDI note, cycles per segment, default upward range)
WT_REGISTERS = {
    "Bass": (36, 1, 0),     # C2
    "Mid":  (48, 2, 12),    # C3
    "Lead": (48, 2, 24),    # C3
}

WT_DRAW_POINTS = 512    # stored resolution of a hand-drawn cycle
# Upper limit for the step order. 255 segments over 16 families is already
# only 15-16 steps each; past that the morph inside a family gets too coarse
# to hear as a sweep, and the table turns into a list of jumps.
# Height a horizontal zoom scrollbar needs, including its padding. Windows
# where the waveform is the growing element must budget for it up front.
ZOOM_BAR_RESERVE = 24

WT_MAX_SELECTED = 16
WT_MORPH_HEIGHT = 150   # isometric morph display in the wavetable dialog
WT_MORPH_SHOWN = 12     # curves drawn; the family itself may have more steps
# The morph display renders at the real segment length so nothing is
# understated; this only stops an unusually long segment from getting slow.
WT_MORPH_MAX_POINTS = 1024

# A single cycle much longer than this is almost certainly not one cycle.
WT_CYCLE_SANE_MAX = 8192

CYCLE_AUDITION_SECONDS = 3.0

TOOLTIP_DELAY_MS = 550       # long enough that they don't fire while just passing over
TOOLTIP_WRAPLENGTH = 320

MIN_VISIBLE_SECONDS = 0.08   # narrowest useful view - roughly one drum hit
MIN_TRIM_SECONDS = 0.01   # 10 ms - short enough for a single drum transient

BUTTON_SATURATION = 0.75  # button fills sit at 75% of the accent's saturation

# .PRM sidecar defaults and templates
PRM_DEFAULTS = [
    ("PHRASE", 0), ("GATE", 1), ("LOOP", 1), ("REVERSE", 0),
    ("START_POS", 0), ("SIZE", 0), ("LOOP_SIZE", 0),
    ("C.TUNE", 0), ("F.TUNE", 0), ("DETUNE", 0),
    ("LO-FI_SW", 0), ("LO-FI", 70),
    ("ENV_MODE", 4),
    ("PENV_MODE", 1), ("PENV_ATTACK", 0), ("PENV_DECAY", 20),
    ("PENV_SUSTAIN", 255), ("PENV_RELEASE", 25), ("PENV_TIME_KEYF", 255),
    ("PENV_VELO_SENS", 0), ("PENV_DEPTH", 0),
    ("TENV_MODE", 1), ("TENV_ATTACK", 3), ("TENV_DECAY", 0),
    ("TENV_SUSTAIN", 255), ("TENV_RELEASE", 3), ("TENV_TIME_KEYF", 255),
    ("TVF_TYPE", 0), ("TVF_CUTOFF", 255), ("TVF_RESO", 0), ("TVF_KEYF", 255),
    ("TVF_VELO_SENS", 0), ("TVF_ENV_DEPTH", 0),
    ("TVA_SW", 1), ("LEVEL", 100),
    ("PAN_MODE", 0), ("PAN", 64), ("OUTPUT_SEL", 2),
    ("SEND_DELAY", 0), ("SEND_REVERB", 0),
    ("TM_STR_MODE", 0), ("TM_STR_WINDOW", 30), ("TM_STR_SPEED", 100),
    ("MONO_POLY", 0), ("CHOP", 1), ("MUTE_GROUP", 0),
] + [(f"PRM{i}", 0) for i in range(1, 17)]

PRM_TEMPLATES = {
    "Init": {
        "GATE": 1, "LOOP": 1, "TENV_SUSTAIN": 255, "LEVEL": 110,
    },
    "Acid": {
        "GATE": 1, "LOOP": 1, "TENV_ATTACK": 23,
        "TENV_DECAY": 26, "TENV_SUSTAIN": 45, "TENV_RELEASE": 108,
        "TVF_TYPE": 1, "TVF_CUTOFF": 137, "TVF_RESO": 218,
        "TVF_ENV_DEPTH": 27, "LEVEL": 110,
    },
    "Bass 1": {
        "GATE": 1, "LOOP": 1, "TENV_ATTACK": 0,
        "TENV_DECAY": 52, "TENV_SUSTAIN": 18, "TENV_RELEASE": 71,
        "TVF_TYPE": 1, "TVF_CUTOFF": 3, "TVF_RESO": 23,
        "TVF_ENV_DEPTH": 43, "LEVEL": 110,
    },
    "Bass 2": {
        "GATE": 1, "LOOP": 1, "TENV_ATTACK": 0,
        "TENV_DECAY": 85, "TENV_SUSTAIN": 82, "TENV_RELEASE": 109,
        "TVF_TYPE": 1, "TVF_CUTOFF": 0, "TVF_RESO": 75,
        "TVF_ENV_DEPTH": 19, "LEVEL": 110,
    },
    # PENV is spelled out in full here, including values that match the
    # baseline: the small ones shape the attack audibly and should not
    # silently follow a future change to PRM_DEFAULTS. PENV_DEPTH is 0, so
    # the pitch envelope is currently inactive.
    "Pad": {
        "GATE": 1, "LOOP": 1, "DETUNE": 10,
        "PENV_MODE": 1, "PENV_ATTACK": 1, "PENV_DECAY": 225,
        "PENV_SUSTAIN": 255, "PENV_RELEASE": 25, "PENV_TIME_KEYF": 255,
        "PENV_VELO_SENS": 0, "PENV_DEPTH": 0,
        "TENV_ATTACK": 255, "TENV_DECAY": 125, "TENV_RELEASE": 255,
        "TVF_TYPE": 1, "TVF_CUTOFF": 112, "TVF_ENV_DEPTH": 122,
        "LEVEL": 110, "MONO_POLY": 1,
    },
    "Reso": {
        "GATE": 1, "LOOP": 1, "TENV_SUSTAIN": 73,
        "TENV_RELEASE": 181, "TVF_TYPE": 2, "TVF_CUTOFF": 46,
        "TVF_RESO": 158, "TVF_ENV_DEPTH": 66, "LEVEL": 110,
    },
    "Reso 2": {
        "GATE": 1, "LOOP": 1, "TENV_DECAY": 17,
        "TENV_SUSTAIN": 86, "TENV_RELEASE": 74, "TVF_TYPE": 2,
        "TVF_CUTOFF": 102, "TVF_RESO": 133, "TVF_ENV_DEPTH": 22,
        "LEVEL": 110,
    },
}

for _wt_name, _wt_ov in PRM_TEMPLATES.items():
    if _wt_ov.get("GATE") != 1 or _wt_ov.get("LOOP") != 1:
        raise ValueError(f"PRM template {_wt_name!r} must set GATE = 1 and LOOP = 1")

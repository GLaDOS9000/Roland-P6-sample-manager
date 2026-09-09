"""Config/persistence functions and app directory helpers."""

import json
import os
import re
import shutil
import sys
import unicodedata
import uuid
import wave

from pyp6.constants import (
    APP_DIR,
    CONFIG_FILE,
    PRESET_FORMAT_VERSION,
    PRESET_MANIFEST_NAME,
    SLICE_COUNTS,
    TEMP_DIR,
    WAVEFORM_LIB_FILE,
    WAVETABLE_DIR,
    WT_SR,
)


def resource_path(relative_path):
    """Resolves a path next to the script - and also works after bundling
    with PyInstaller (onefile or onedir), which extracts bundled data files
    into a temp folder at runtime and exposes it via sys._MEIPASS."""
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def ensure_app_dirs():
    """Creates the app's folders on demand. Everything the app writes lives
    under ~/.pyp6: config.json at the top, and all generated audio (trims,
    mono downmixes, normalized copies, chops, preview conversions) under
    temp/. Keeping config OUTSIDE temp/ matters - it means clearing temp
    can never wipe the user's settings."""
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
    except Exception as e:
        print(f"Could not create app folders: {e}")
    return TEMP_DIR


def temp_path(filename):
    """Absolute path for a generated file inside the temp folder."""
    ensure_app_dirs()
    return os.path.join(TEMP_DIR, filename)


def wavetable_path(filename):
    """Generated wavetables live outside temp/ on purpose: they are the pad's
    only copy of the sample, and Settings > Clear temp folder would otherwise
    delete a pad's audio out from under it."""
    os.makedirs(WAVETABLE_DIR, exist_ok=True)
    return os.path.join(WAVETABLE_DIR, filename)


def get_temp_folder_size():
    """(total_bytes, file_count) of the temp folder."""
    total, count = 0, 0
    for root, _dirs, files in os.walk(TEMP_DIR):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
                count += 1
            except OSError:
                pass
    return total, count


def clear_temp_folder():
    """Deletes everything inside temp/ (but keeps the folder itself).
    Returns (deleted_count, errors)."""
    deleted, errors = 0, []
    if not os.path.isdir(TEMP_DIR):
        return deleted, errors
    try:
        names = os.listdir(TEMP_DIR)
    except Exception as e:
        # e.g. permission denied, or the folder vanished between the
        # isdir() check above and here.
        return deleted, [f"Could not read temp folder: {e}"]
    for name in names:
        full = os.path.join(TEMP_DIR, name)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            deleted += 1
        except Exception as e:
            errors.append(f"{name}: {e}")
    return deleted, errors


LAST_SAMPLE_DIR = None


def guess_default_import_root():
    """Try to auto-detect a mounted Roland P-6 IMPORT folder across platforms.
    Falls back to the user's home directory if nothing is found, rather than
    a hardcoded, user- or OS-specific path that would break on other machines."""
    import glob

    candidates = []
    if os.name == "nt":
        import string

        for letter in string.ascii_uppercase:
            candidates.append(f"{letter}:\\IMPORT")
            candidates.append(f"{letter}:\\P-6\\IMPORT")
    elif sys.platform == "darwin":
        candidates += glob.glob("/Volumes/*/IMPORT")
        candidates += glob.glob("/Volumes/*/P-6/IMPORT")
    else:
        # Linux: typical auto-mount locations, independent of username
        candidates += glob.glob("/run/media/*/*/IMPORT")
        candidates += glob.glob("/run/media/*/P-6/IMPORT")
        candidates += glob.glob("/media/*/*/IMPORT")
        candidates += glob.glob("/media/*/P-6/IMPORT")

    for path in candidates:
        if os.path.isdir(path):
            return path

    return os.path.expanduser("~")


def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config_value(key, value):
    data = load_config()
    data[key] = value
    try:
        # On a fresh install ~/.pyp6 doesn't exist yet - without this the
        # write fails and (because of the except below) settings would
        # silently never be saved.
        os.makedirs(APP_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(data, f)
    except Exception as e:
        print(f"Could not save configuration: {e}")


def load_last_import_root():
    data = load_config()
    path = data.get("import_root")
    if path and os.path.isdir(path):
        return path
    return guess_default_import_root()


def load_last_sample_dir():
    data = load_config()
    path = data.get("last_sample_dir")
    if path and os.path.isdir(path):
        return path
    return None


def load_last_export_dir():
    """Where the user last pointed the "P6 -> Bank" import.

    Deliberately the folder they PICKED (usually the P-6 drive), not the
    BANK_x folder it resolved to - the device exports a different bank next
    time, so re-resolving from the picked folder finds whichever bank is
    actually there now."""
    data = load_config()
    path = data.get("last_export_dir")
    if path and os.path.isdir(path):
        return path
    return None


def save_last_import_root(path):
    save_config_value("import_root", path)


def save_last_sample_dir(path):
    save_config_value("last_sample_dir", path)


def save_last_export_dir(path):
    save_config_value("last_export_dir", path)


def load_last_cycle_dir():
    """Folder the single-cycle browser last opened.

    Kept apart from last_sample_dir on purpose: a waveform library lives
    somewhere quite different from the samples that go on pads, and letting
    the two overwrite each other would send you back to the wrong place
    every time.
    """
    path = load_config().get("last_cycle_dir")
    return path if path and os.path.isdir(path) else None


def save_last_cycle_dir(path):
    save_config_value("last_cycle_dir", path)


def load_default_autoplay():
    return bool(load_config().get("default_autoplay", False))


def load_default_slices():
    val = load_config().get("default_slices", 8)
    return val if val in SLICE_COUNTS else 8


def load_storage_warning_mb():
    val = load_config().get("storage_warning_mb", 10)
    try:
        val = float(val)
        return val if val > 0 else 10.0
    except (TypeError, ValueError):
        return 10.0


def load_ffmpeg_override():
    return load_config().get("ffmpeg_path") or ""


def load_ffprobe_override():
    return load_config().get("ffprobe_path") or ""


def load_tooltips_enabled():
    return bool(load_config().get("tooltips_enabled", True))


def is_preset_folder(path):
    """A folder counts as a preset if it directly contains preset.json."""
    return os.path.isfile(os.path.join(path, PRESET_MANIFEST_NAME))


def read_preset_manifest(preset_dir):
    """Returns the parsed preset.json, or None if missing/unreadable."""
    manifest_path = os.path.join(preset_dir, PRESET_MANIFEST_NAME)
    try:
        with open(manifest_path) as f:
            data = json.load(f)
        if not isinstance(data, dict) or "banks" not in data:
            return None
        return data
    except Exception:
        return None


def write_preset_manifest(preset_dir, data):
    manifest_path = os.path.join(preset_dir, PRESET_MANIFEST_NAME)
    with open(manifest_path, "w") as f:
        json.dump(data, f, indent=2)


def load_recent_presets():
    return load_config().get("recent_presets", [])


def add_recent_preset(path):
    recents = load_recent_presets()
    recents = [p for p in recents if p != path]  # de-dupe, most-recent-first
    recents.insert(0, path)
    recents = recents[:5]
    save_config_value("recent_presets", recents)


def load_drawn_library():
    """All shapes the user has drawn so far, keyed by name.

    A drawing is not a setting you can retype - if it is gone, it is gone.
    So it is kept for good, and every wavetable dialog starts with the full
    palette rather than a blank slate.
    """
    try:
        with open(WAVEFORM_LIB_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out = {}
    if isinstance(data, dict):
        for name, entry in data.items():
            if isinstance(entry, dict) and entry.get("a"):
                entry["name"] = name
                out[name] = entry
    return out


def save_drawn_library(library):
    try:
        os.makedirs(APP_DIR, exist_ok=True)
        with open(WAVEFORM_LIB_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {
                    n: {"kind": "draw", "name": n, "a": e.get("a") or [], "b": e.get("b") or []}
                    for n, e in library.items()
                },
                f,
            )
        return True
    except Exception as e:
        print(f"Could not save the waveform library: {e}")
        return False


def verify_preset_folder(preset_dir):
    """Checks that a preset folder is complete and portable.

    A preset is meant to be handed to someone else, so anything that only
    works on the machine that wrote it counts as a fault: absolute paths,
    paths escaping the folder, a manifest entry with no file behind it, or a
    wavetable pad whose .PRM never made it across.

    Returns (problems, stray_files) - both lists of plain strings, empty when
    the folder is sound.
    """
    # Import here to avoid circular dependency
    from pyp6.synth.waveforms import WT_FAMILY_MAP

    problems, referenced = [], set()
    manifest = read_preset_manifest(preset_dir)
    if not manifest:
        return ([f"{PRESET_MANIFEST_NAME} is missing or unreadable."], [])
    referenced.add(os.path.normcase(os.path.join(preset_dir, PRESET_MANIFEST_NAME)))

    try:
        version = int(manifest.get("format_version", 1))
    except (TypeError, ValueError):
        problems.append("format_version is not a number.")
        version = 1
    if version > PRESET_FORMAT_VERSION:
        problems.append(
            f"Written in format version {version}; this build "
            f"understands up to {PRESET_FORMAT_VERSION}."
        )

    for bank, bank_entry in sorted((manifest.get("banks") or {}).items()):
        if not isinstance(bank_entry, dict):
            problems.append(f"BANK_{bank}: malformed entry.")
            continue
        for pad_key, entry in sorted((bank_entry.get("pads") or {}).items()):
            if not entry:
                continue
            where = f"BANK_{bank}/PAD_{pad_key}"
            rel = entry.get("filepath") or ""
            if not rel:
                problems.append(f"{where}: no file recorded.")
                continue
            # Portability first: an absolute path or a .. escape means the
            # preset only works on the machine that wrote it.
            if os.path.isabs(rel) or rel[1:3] == ":\\" or ".." in rel.split("/"):
                problems.append(f"{where}: path is not relative to the preset folder ({rel}).")
                continue
            wav = os.path.normpath(os.path.join(preset_dir, *rel.split("/")))
            if not os.path.isfile(wav):
                problems.append(f"{where}: {rel} is missing.")
                continue
            referenced.add(os.path.normcase(wav))
            if os.path.getsize(wav) == 0:
                problems.append(f"{where}: {rel} is empty (0 bytes).")
                continue
            try:
                with wave.open(wav, "rb") as wf:
                    frames, rate = wf.getnframes(), wf.getframerate()
                if frames == 0:
                    problems.append(f"{where}: {rel} contains no audio frames.")
            except Exception as e:
                problems.append(f"{where}: {rel} is not a readable WAV ({e}).")
                continue

            wt = entry.get("wavetable")
            if wt:
                cfg = (wt or {}).get("config") or {}
                drawn = {e.get("name") for e in (cfg.get("custom") or []) if isinstance(e, dict)}
                for fam in cfg.get("families") or []:
                    if fam not in WT_FAMILY_MAP and fam not in drawn:
                        problems.append(
                            f'{where}: step order uses "{fam}", but no '
                            f"such waveform is stored in the preset."
                        )
                for e in cfg.get("custom") or []:
                    if not isinstance(e, dict) or not e.get("a"):
                        problems.append(f"{where}: a drawn waveform entry has no shape data.")
                    elif len(e.get("a") or []) < 4:
                        problems.append(
                            f'{where}: drawn waveform "{e.get("name")}" is too short to use.'
                        )
            prm = os.path.splitext(wav)[0] + ".PRM"
            referenced.add(os.path.normcase(prm))
            if wt:
                meta = (wt or {}).get("meta") or {}
                if not os.path.isfile(prm):
                    problems.append(
                        f"{where}: wavetable pad without its .PRM - "
                        f"the P-6 cannot loop a segment without it."
                    )
                else:
                    try:
                        text = open(prm).read()
                        got = {
                            k: int(v)
                            for k, v in re.findall(r"^(\w+)\s*=\s*(-?\d+)\s*$", text, re.M)
                        }
                    except Exception as e:
                        got = {}
                        problems.append(f"{where}: .PRM unreadable ({e}).")
                    want_size = meta.get("L")
                    if want_size and got.get("SIZE") not in (None, want_size):
                        problems.append(
                            f"{where}: .PRM SIZE is {got.get('SIZE')}, expected {want_size}."
                        )
                    if got and got.get("LOOP") != 1:
                        problems.append(f"{where}: .PRM does not have LOOP enabled.")
                total = meta.get("total_frames")
                if total and frames and frames != total:
                    problems.append(
                        f"{where}: WAV has {frames} frames, the wavetable was built with {total}."
                    )
                if rate and rate != WT_SR:
                    problems.append(f"{where}: wavetable is {rate} Hz, expected {WT_SR}.")

    strays = []
    for root, dirs, files in os.walk(preset_dir):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            full = os.path.join(root, name)
            if os.path.normcase(full) not in referenced:
                strays.append(os.path.relpath(full, preset_dir).replace(os.sep, "/"))
    return problems, sorted(strays)


def apply_saved_ffmpeg_overrides():
    """Applies any manually-configured ffmpeg/ffprobe paths from Settings on
    top of the auto-detected ones from startup. Called once at launch,
    before the pydub/ffmpeg dependency check, so a working manual override
    from a previous session doesn't get flagged as missing."""
    from pyp6.audio import playback as _pb

    if not _pb.PYDUB_AVAILABLE:
        return
    from pydub import AudioSegment

    ffmpeg_override = load_ffmpeg_override()
    ffprobe_override = load_ffprobe_override()
    if ffmpeg_override and os.path.exists(ffmpeg_override):
        AudioSegment.converter = ffmpeg_override
        AudioSegment.ffmpeg = ffmpeg_override
        _pb.FFMPEG_AVAILABLE = True
    if ffprobe_override and os.path.exists(ffprobe_override):
        AudioSegment.ffprobe = ffprobe_override


def apply_saved_storage_threshold():
    import pyp6.constants as _c

    _c.MAX_UPLOAD_BYTES = int(load_storage_warning_mb() * 1024 * 1024)


_TEMP_TAG_RE = re.compile(
    r"_(?:trim|norm|fade|mono|imp|chop|conv)(?:_[A-H][1-6])?_[0-9a-f]{6,8}$", re.IGNORECASE
)


# NFKD splits accented letters into base + combining mark, which the ASCII
# step then drops cleanly. Letters with no decomposition would simply vanish,
# so the common ones get a spelling instead: "Strasse", not "Strae".
_TRANSLITERATE = str.maketrans(
    {
        "\u00df": "ss",
        "\u00e6": "ae",
        "\u00c6": "AE",
        "\u00f8": "oe",
        "\u00d8": "OE",
        "\u0142": "l",
        "\u0141": "L",
        "\u0111": "d",
        "\u0110": "D",
        "\u00fe": "th",
        "\u00de": "TH",
        "\u00f0": "d",
        "\u00d0": "D",
        "\u0153": "oe",
        "\u0152": "OE",
        "\u00e5": "aa",
        "\u00c5": "AA",
    }
)

_RESERVED_DEVICE_NAMES = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)


def safe_base_name(path, max_len=48, strip_tags=False, fallback="sample"):
    """A filesystem-safe, length-capped base name derived from `path`.

    Every temp file this app writes can end up copied to the P-6, whose
    drive is FAT-formatted - so a name that Linux accepts happily can still
    make the copy fail there. Characters FAT/Windows reject are replaced,
    leading dots (which would make a hidden file on Unix) are dropped, and
    trailing dots/spaces are trimmed because FAT silently mangles those.
    The length cap keeps names readable on the device's small display and
    well clear of any path-length limit.

    With strip_tags, a marker this app appended earlier is removed first,
    so repeated edits don't accumulate a chain of suffixes."""
    base = os.path.splitext(os.path.basename(path or ""))[0]
    base = base.translate(_TRANSLITERATE)
    base = unicodedata.normalize("NFKD", base)
    base = base.encode("ascii", "ignore").decode("ascii")
    base = re.sub(r"[^\w \-.]", "_", base)
    base = base.strip().lstrip(".")
    if strip_tags:
        while True:
            stripped = _TEMP_TAG_RE.sub("", base)
            if stripped == base:
                break
            base = stripped
    base = base[:max_len].strip(" .")
    if base.upper() in _RESERVED_DEVICE_NAMES:
        base += "_"
    return base or fallback


def derived_temp_path(source_path, tag, ext=".wav"):
    """Temp filename that keeps the source sample's name recognizable."""
    return temp_path(
        f"{safe_base_name(source_path, strip_tags=True)}_{tag}_{uuid.uuid4().hex[:8]}{ext}"
    )


def format_duration(seconds):
    if seconds is None:
        return "--:--"
    minutes = int(seconds // 60)
    secs = seconds - minutes * 60
    return f"{minutes}:{secs:04.1f}"


def format_size(num_bytes):
    if num_bytes is None:
        return "--"
    mb = num_bytes / (1024 * 1024)
    if mb >= 0.1:
        return f"{mb:.2f}MB"
    return f"{num_bytes / 1024:.1f}KB"

"""Audio processing: trim, normalize, fade, mono, zero-crossing."""

import numpy as np
import soundfile as sf

from pyp6.config import derived_temp_path
from pyp6.log import logger


def find_zero_crossing(data, target_idx, search_radius):
    """Finds the sample index closest to target_idx (within +/- search_radius)
    where the (mono-mixed) signal crosses zero. Falls back to target_idx
    unchanged if no crossing is found in range."""
    n = len(data)
    if n < 2:
        return target_idx
    mono = data.mean(axis=1) if data.ndim > 1 else data
    target_idx = max(0, min(target_idx, n - 1))
    lo = max(0, target_idx - search_radius)
    hi = min(n - 2, target_idx + search_radius)
    if lo >= hi:
        return target_idx

    best_idx, best_dist = None, None
    for i in range(lo, hi + 1):
        if mono[i] == 0 or (mono[i] < 0) != (mono[i + 1] < 0):
            idx = i if abs(mono[i]) <= abs(mono[i + 1]) else i + 1
            dist = abs(idx - target_idx)
            if best_dist is None or dist < best_dist:
                best_idx, best_dist = idx, dist
    return best_idx if best_idx is not None else target_idx


def trim_wav_file(src_path, start_frac, end_frac, fade_ms=0.5, snap_ms=5):
    data, fs = sf.read(src_path, dtype="float32")
    n = len(data)
    start_i = max(0, min(int(start_frac * n), n - 1))
    end_i = max(start_i + 1, min(int(end_frac * n), n))

    radius = int(fs * snap_ms / 1000)
    start_i = find_zero_crossing(data, start_i, radius)
    end_i = find_zero_crossing(data, end_i, radius)
    if end_i <= start_i:
        end_i = min(n, start_i + 1)

    trimmed = data[start_i:end_i]
    trimmed = apply_micro_fade(trimmed, fs, fade_ms=fade_ms)
    out_path = derived_temp_path(src_path, "trim")
    sf.write(out_path, trimmed, fs, subtype="PCM_16")  # P-6 requires 16-bit PCM
    return out_path


def normalize_wav_file(src_path, target_peak=0.98):
    """Peak-normalizes a wav file."""
    data, fs = sf.read(src_path, dtype="float32")
    peak = float(np.max(np.abs(data))) if data.size else 0.0
    if peak > 0:
        data = data * (target_peak / peak)
    out_path = derived_temp_path(src_path, "norm")
    sf.write(out_path, data, fs, subtype="PCM_16")
    return out_path


def apply_fade_envelope(data, fs, fade_in_s=0.0, fade_out_s=0.0):
    """Applies a linear fade-in/fade-out directly to an in-memory numpy
    array (mono or multi-channel), in place on a copy."""
    n = len(data)
    if n == 0 or (fade_in_s <= 0 and fade_out_s <= 0):
        return data
    data = data.copy()
    fade_in_n = min(int(fade_in_s * fs), n)
    fade_out_n = min(int(fade_out_s * fs), n)
    if fade_in_n > 0:
        ramp = np.linspace(0.0, 1.0, fade_in_n)
        if data.ndim > 1:
            ramp = ramp[:, None]
        data[:fade_in_n] = data[:fade_in_n] * ramp
    if fade_out_n > 0:
        ramp = np.linspace(1.0, 0.0, fade_out_n)
        if data.ndim > 1:
            ramp = ramp[:, None]
        data[-fade_out_n:] = data[-fade_out_n:] * ramp
    return data


def apply_fade_to_wav_file(src_path, fade_in_s, fade_out_s):
    """File-level wrapper around apply_fade_envelope."""
    data, fs = sf.read(src_path, dtype="float32")
    data = apply_fade_envelope(data, fs, fade_in_s, fade_out_s)
    out_path = derived_temp_path(src_path, "fade")
    sf.write(out_path, data, fs, subtype="PCM_16")
    return out_path


def ensure_mono_wav(path):
    """Returns a mono version of the given wav file."""
    try:
        data, fs = sf.read(path, dtype="float32")
    except Exception:
        logger.warning(f"ensure_mono_wav: could not read {path!r}")
        return path
    if data.ndim == 1:
        return path
    mono = data.mean(axis=1)
    out_path = derived_temp_path(path, "mono")
    try:
        sf.write(out_path, mono, fs, subtype="PCM_16")
    except Exception:
        logger.warning(f"ensure_mono_wav: could not write mono version of {path!r}")
        return path
    return out_path


def apply_micro_fade(data, fs, fade_ms=2):
    """Wendet einen linearen Fade-In/Fade-Out von fade_ms Millisekunden an,
    um Klick-Artefakte an harten Schnittkanten zu vermeiden."""
    fade_len = int(fs * fade_ms / 1000)
    fade_len = min(fade_len, len(data) // 2)
    if fade_len <= 0:
        return data
    fade_in = np.linspace(0.0, 1.0, fade_len)
    fade_out = np.linspace(1.0, 0.0, fade_len)
    out = data.copy()
    if out.ndim == 1:
        out[:fade_len] *= fade_in
        out[-fade_len:] *= fade_out
    else:
        out[:fade_len] *= fade_in[:, None]
        out[-fade_len:] *= fade_out[:, None]
    return out


def snap_ms_backward_to_zero(audio_np, sr, target_ms, search_ms=5):
    """Find a zero-crossing at or before target_ms in a (channels, samples) float32 array.
    Returns the adjusted position in milliseconds."""
    target_idx = int(target_ms * sr / 1000)
    if target_idx <= 1:
        return target_ms
    n = audio_np.shape[1]
    target_idx = min(target_idx, n - 1)
    mono = audio_np.mean(axis=0)
    radius = int(sr * search_ms / 1000)
    lo = max(0, target_idx - radius)
    for i in range(target_idx - 1, lo - 1, -1):
        if mono[i] == 0 or (mono[i] < 0) != (mono[i + 1] < 0):
            idx = i if abs(mono[i]) <= abs(mono[i + 1]) else i + 1
            return int(idx * 1000 / sr)
    return target_ms

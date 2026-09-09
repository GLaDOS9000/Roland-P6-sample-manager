"""Audio format conversion: pitch shift, rate/mono/bit-depth, chop builder."""

import os
import uuid

import numpy as np

from pyp6.constants import MAX_SECONDS
from pyp6.config import safe_base_name, temp_path
from pyp6.audio.info import get_wav_info, get_wav_sample_width
from pyp6.audio.playback import PYDUB_AVAILABLE
from pyp6.audio.processing import snap_ms_backward_to_zero


def pitch_speed_factor(cents):
    """Duration/speed multiplier for a "vari-speed" pitch shift of `cents`
    cents. >1 means faster playback / shorter duration (pitch up)."""
    return 2.0 ** (cents / 1200.0)


def apply_pitch_shift(audio_segment, cents):
    """Pitch-shifts a pydub AudioSegment by `cents` using the classic
    vari-speed trick."""
    if not cents:
        return audio_segment
    factor = pitch_speed_factor(cents)
    new_rate = int(audio_segment.frame_rate * factor)
    if new_rate <= 0:
        return audio_segment
    shifted = audio_segment._spawn(audio_segment.raw_data, overrides={"frame_rate": new_rate})
    return shifted.set_frame_rate(audio_segment.frame_rate)


def compute_export_ready_path(filepath, target_rate, pitch_cents=0, force_mono=False):
    """Converts a sample to the target rate/pitch/mono, returning the path."""
    if not filepath or not PYDUB_AVAILABLE:
        return filepath
    from pydub import AudioSegment
    try:
        _, orig_rate, orig_channels = get_wav_info(filepath)
    except Exception:
        return filepath
    orig_sample_width = get_wav_sample_width(filepath) or 2
    needs_mono = force_mono and orig_channels > 1
    needs_bit_depth_fix = orig_sample_width != 2  # P-6 requires 16-bit PCM
    if target_rate == orig_rate and not pitch_cents and not needs_mono and not needs_bit_depth_fix:
        return filepath
    audio = AudioSegment.from_wav(filepath)
    if pitch_cents:
        audio = apply_pitch_shift(audio, pitch_cents)
    if needs_mono:
        audio = audio.set_channels(1)
    audio = audio.set_frame_rate(target_rate)
    audio = audio.set_sample_width(2)  # always force 16-bit for the P-6
    suffix = f"_{target_rate}Hz"
    if pitch_cents:
        suffix += f"_{pitch_cents:+d}c"
    if needs_mono:
        suffix += "_mono"
    if needs_bit_depth_fix:
        suffix += "_16bit"
    out_path = temp_path(f"{safe_base_name(filepath)}{suffix}.wav")
    audio.export(out_path, format="wav")
    return out_path


def convert_to_wav_if_needed(path):
    if path.lower().endswith(".wav"):
        return path, False
    if not PYDUB_AVAILABLE:
        from pyp6.ui.dialogs_common import dark_showerror
        dark_showerror("pydub missing", "MP3 conversion requires pydub + ffmpeg.")
        return path, False
    try:
        from pydub import AudioSegment
        sound = AudioSegment.from_file(path)
        wav_path = temp_path(f"{safe_base_name(path)}_conv_{uuid.uuid4().hex[:6]}.wav")
        sound.export(wav_path, format="wav")
        return wav_path, True
    except Exception as e:
        from pyp6.ui.dialogs_common import dark_showerror
        dark_showerror("Conversion Error", f"Details: {e}")
        return path, False


def build_chop_file(file_paths, rate, channels, num_slices, normalize_mode="off"):
    """Renders `file_paths` into one multisample."""
    if not PYDUB_AVAILABLE:
        raise RuntimeError("pydub is required for the Chop feature.")
    from pydub import AudioSegment
    from pydub.silence import detect_leading_silence
    from pydub.effects import normalize as pydub_normalize

    limit = MAX_SECONDS.get((rate, channels))
    if not limit:
        raise ValueError(f"No duration limit defined for {rate}Hz/{channels}ch.")

    total_ms = int(round(limit * 1000))
    boundaries = [int(round(i * total_ms / num_slices)) for i in range(num_slices + 1)]

    combined = AudioSegment.silent(duration=0, frame_rate=rate)
    if channels == 2:
        combined = combined.set_channels(2)
    else:
        combined = combined.set_channels(1)
    combined = combined.set_sample_width(2)

    for idx, path in enumerate(file_paths):
        slice_ms = boundaries[idx + 1] - boundaries[idx]
        audio = AudioSegment.from_file(path)
        audio = audio.set_frame_rate(rate)
        audio = audio.set_channels(channels)
        audio = audio.set_sample_width(2)

        trimmed_start = detect_leading_silence(audio)
        audio = audio[trimmed_start:]

        if len(audio) > slice_ms:
            cut_ms = snap_ms_backward_to_zero(audio, slice_ms)
            audio = audio[:cut_ms]

        if normalize_mode == "per_sample":
            audio = pydub_normalize(audio)

        if len(audio) < slice_ms:
            tail_ms = snap_ms_backward_to_zero(audio, len(audio))
            audio = audio[:tail_ms]
            pad = AudioSegment.silent(duration=slice_ms - len(audio), frame_rate=rate)
            pad = pad.set_channels(channels)
            pad = pad.set_sample_width(2)
            audio = audio + pad

        combined += audio

    if len(file_paths) < num_slices:
        remaining_ms = total_ms - boundaries[len(file_paths)]
        if remaining_ms > 0:
            silence = AudioSegment.silent(duration=remaining_ms, frame_rate=rate)
            silence = silence.set_channels(channels)
            silence = silence.set_sample_width(2)
            combined += silence

    if normalize_mode == "whole":
        combined = pydub_normalize(combined)

    return combined

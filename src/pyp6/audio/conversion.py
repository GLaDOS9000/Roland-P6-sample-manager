"""Audio format conversion: pitch shift, rate/mono/bit-depth, chop builder."""

import os
import uuid

import numpy as np

from pyp6.audio.info import get_wav_info, get_wav_sample_width
from pyp6.audio.playback import AUDIO_AVAILABLE
from pyp6.config import temp_path
from pyp6.constants import MAX_SECONDS
from pyp6.log import logger


def pitch_speed_factor(cents):
    """Duration/speed multiplier for a "vari-speed" pitch shift of `cents`
    cents. >1 means faster playback / shorter duration (pitch up)."""
    return 2.0 ** (cents / 1200.0)


def _detect_leading_silence_samples(audio_np, threshold_db=-50):
    """Return sample index of first non-silent frame in a (channels, samples) array."""
    threshold = 10 ** (threshold_db / 20)
    per_sample_peak = np.abs(audio_np).max(axis=0)
    nonsilent = np.where(per_sample_peak > threshold)[0]
    return int(nonsilent[0]) if len(nonsilent) > 0 else 0


def _normalize_audio(audio_np):
    """Peak-normalize a (channels, samples) float32 array to [-1, 1]."""
    peak = np.max(np.abs(audio_np))
    return audio_np / peak if peak > 0 else audio_np


def apply_pitch_shift(audio_np, sr, cents):
    """Vari-speed pitch shift. Returns (channels, samples) float32 array
    resampled so that when written at sr it plays pitch-shifted by cents."""
    if not cents:
        return audio_np
    import pedalboard  # lazy: avoids a module-level import that crashes on no-AVX CPUs

    factor = pitch_speed_factor(cents)
    new_sr = int(round(sr * factor))
    if new_sr <= 0:
        return audio_np
    return pedalboard.Resample(target_sample_rate=new_sr)(audio_np, sr)


def compute_export_ready_path(filepath, target_rate, pitch_cents=0, force_mono=False):
    """Return a path to a converted WAV ready for export to the P-6.
    If no conversion is needed, returns filepath unchanged."""
    if not filepath or not AUDIO_AVAILABLE:
        return filepath
    try:
        _, orig_rate, orig_channels = get_wav_info(filepath)
    except Exception:
        return filepath
    orig_sample_width = get_wav_sample_width(filepath) or 2
    needs_mono = force_mono and orig_channels > 1
    needs_bit_depth_fix = orig_sample_width != 2
    if target_rate == orig_rate and not pitch_cents and not needs_mono and not needs_bit_depth_fix:
        return filepath
    try:
        import pedalboard  # lazy
        from pedalboard.io import AudioFile  # lazy

        with AudioFile(filepath) as f:
            audio = f.read(f.frames)  # (channels, samples) float32
            sr = f.samplerate

        if pitch_cents:
            audio = apply_pitch_shift(audio, sr, pitch_cents)
            # After vari-speed resample: write at orig sr to bake in pitch shift

        if needs_mono:
            audio = audio.mean(axis=0, keepdims=True)

        if target_rate != sr:
            audio = pedalboard.Resample(target_sample_rate=target_rate)(audio, sr)

        suffix = f"_{target_rate}Hz"
        if pitch_cents:
            suffix += f"_{pitch_cents:+d}c"
        if needs_mono:
            suffix += "_mono"
        if needs_bit_depth_fix:
            suffix += "_16bit"

        safe_name = os.path.splitext(os.path.basename(filepath))[0]
        out_path = temp_path(f"{safe_name}{suffix}.wav")
        with AudioFile(
            out_path, "w", samplerate=target_rate, num_channels=audio.shape[0], bit_depth=16
        ) as f:
            f.write(audio)
        return out_path
    except Exception:
        logger.exception(
            f"compute_export_ready_path failed for {filepath!r} "
            f"(target_rate={target_rate}, pitch_cents={pitch_cents}, force_mono={force_mono})"
        )
        return filepath


def convert_to_wav_if_needed(path):
    """Convert non-WAV to a temp WAV. Returns (path, was_converted)."""
    if path.lower().endswith(".wav"):
        return path, False
    if not AUDIO_AVAILABLE:
        from pyp6.ui.dialogs_common import dark_showerror

        dark_showerror(
            "pedalboard missing",
            "MP3/format conversion requires pedalboard.\nInstall with: pip install pedalboard",
        )
        return path, False
    try:
        from pedalboard.io import AudioFile  # lazy

        with AudioFile(path) as f:
            audio = f.read(f.frames)
            sr = f.samplerate
        safe_name = os.path.splitext(os.path.basename(path))[0]
        wav_path = temp_path(f"{safe_name}_conv_{uuid.uuid4().hex[:6]}.wav")
        with AudioFile(
            wav_path, "w", samplerate=sr, num_channels=audio.shape[0], bit_depth=16
        ) as f:
            f.write(audio)
        return wav_path, True
    except Exception as e:
        from pyp6.ui.dialogs_common import dark_showerror

        dark_showerror("Conversion Error", f"Could not convert file:\n{e}")
        return path, False


def build_chop_file(file_paths, rate, channels, num_slices, normalize_mode="off"):
    """Render file_paths into one multisample WAV buffer for the P-6.

    Returns (audio_np, rate) where audio_np is (channels, total_samples) float32.
    The caller is responsible for writing the WAV file.
    """
    if not AUDIO_AVAILABLE:
        raise RuntimeError("pedalboard is required for the Chop feature.")

    import pedalboard  # lazy
    from pedalboard.io import AudioFile  # lazy

    from pyp6.audio.processing import snap_ms_backward_to_zero

    limit = MAX_SECONDS.get((rate, channels))
    if not limit:
        raise ValueError(f"No duration limit defined for {rate}Hz/{channels}ch.")

    total_samples = int(round(limit * rate))
    boundaries = [int(round(i * total_samples / num_slices)) for i in range(num_slices + 1)]
    combined_parts = []

    for idx, path in enumerate(file_paths):
        slice_samples = boundaries[idx + 1] - boundaries[idx]

        with AudioFile(path) as f:
            audio = f.read(f.frames)  # (src_channels, src_samples) float32
            src_sr = f.samplerate

        # Resample to target rate
        if src_sr != rate:
            audio = pedalboard.Resample(target_sample_rate=rate)(audio, src_sr)

        # Channel conversion
        if audio.shape[0] != channels:
            if channels == 1:
                audio = audio.mean(axis=0, keepdims=True)
            else:
                audio = np.repeat(audio[:1], 2, axis=0)  # mono -> stereo

        # Trim leading silence
        trim_start = _detect_leading_silence_samples(audio)
        if trim_start > 0:
            audio = audio[:, trim_start:]

        # Per-sample normalization before truncation
        if normalize_mode == "per_sample":
            audio = _normalize_audio(audio)

        # Truncate to slice boundary (zero-crossing aware)
        if audio.shape[1] > slice_samples:
            cut_ms = snap_ms_backward_to_zero(audio, rate, int(slice_samples * 1000 / rate))
            cut_samples = int(cut_ms * rate / 1000)
            audio = audio[:, :cut_samples]

        # Pad with silence to exact slice length
        if audio.shape[1] < slice_samples:
            tail_ms = snap_ms_backward_to_zero(audio, rate, int(audio.shape[1] * 1000 / rate))
            tail_samples = int(tail_ms * rate / 1000)
            audio = audio[:, :tail_samples]
            pad = np.zeros((channels, slice_samples - audio.shape[1]), dtype=np.float32)
            audio = np.concatenate([audio, pad], axis=1)

        combined_parts.append(audio)

    # Fill remaining slices with silence if fewer files than slices
    if len(file_paths) < num_slices:
        remaining_samples = total_samples - boundaries[len(file_paths)]
        if remaining_samples > 0:
            combined_parts.append(np.zeros((channels, remaining_samples), dtype=np.float32))

    if combined_parts:
        combined = np.concatenate(combined_parts, axis=1)
    else:
        combined = np.zeros((channels, total_samples), dtype=np.float32)

    if normalize_mode == "whole":
        combined = _normalize_audio(combined)

    return combined, rate

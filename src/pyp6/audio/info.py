"""Audio file metadata: duration, sample rate, channel count, warnings."""

import contextlib
import os
import shutil
import subprocess
import wave

from pyp6.audio.playback import PYDUB_AVAILABLE
from pyp6.constants import MAX_SECONDS


def get_wav_info(path):
    with contextlib.closing(wave.open(path, "r")) as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        channels = wf.getnchannels()
        duration = frames / float(rate)
        return duration, rate, channels


def get_wav_sample_width(path):
    """Bit depth in bytes (2 = 16-bit, 3 = 24-bit, 4 = 32-bit) of a wav file,
    or None if it can't be read. The P-6 requires 16-bit PCM."""
    try:
        with contextlib.closing(wave.open(path, "r")) as wf:
            return wf.getsampwidth()
    except Exception:
        return None


def check_duration_warning(path, target_rate=None, pitch_cents=0, force_mono=False):
    from pyp6.audio.conversion import pitch_speed_factor

    try:
        duration, rate, channels = get_wav_info(path)
    except Exception:
        return None
    if pitch_cents:
        duration = duration / pitch_speed_factor(pitch_cents)
    rate = target_rate or rate
    ch_key = 1 if (force_mono or channels == 1) else 2
    limit = MAX_SECONDS.get((rate, ch_key))
    if limit and duration > limit:
        pitch_note = f" (with pitch {pitch_cents:+d}c)" if pitch_cents else ""
        return (
            f"Sample is {duration:.1f}s long{pitch_note}, but at {rate}Hz/"
            f"{'Mono' if ch_key == 1 else 'Stereo'} only {limit}s are possible."
        )
    return None


def compute_truncate_fraction(path, target_rate=None, pitch_cents=0, force_mono=False):
    """Where the P-6's length limit falls inside `path`, as a fraction of the
    file's ORIGINAL (un-pitch-shifted) timeline - or None if the sample fits."""
    from pyp6.audio.conversion import pitch_speed_factor

    try:
        duration, _, channels = get_wav_info(path)
    except Exception:
        return None
    if not duration:
        return None
    ch_key = 1 if (force_mono or channels == 1) else 2
    limit = MAX_SECONDS.get((target_rate, ch_key))
    if not limit:
        return None
    speed_factor = pitch_speed_factor(pitch_cents) if pitch_cents else 1.0
    limit_original_seconds = limit * speed_factor
    if limit_original_seconds >= duration:
        return None  # fits, nothing to shade
    return limit_original_seconds / duration


def _mp3_duration_via_ffprobe(path):
    """Reads just the duration from an mp3's container metadata via ffprobe."""
    if PYDUB_AVAILABLE:
        try:
            from pydub import AudioSegment

            ffprobe = getattr(AudioSegment, "ffprobe", None)
        except Exception:
            ffprobe = None
    else:
        ffprobe = None
    ffprobe = ffprobe or shutil.which("ffprobe")
    if not ffprobe:
        return None
    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                path,
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return float(result.stdout.strip())
    except Exception:
        return None


_duration_cache = {}  # path -> (mtime, duration)


def get_audio_duration_seconds(path):
    """Duration in seconds for a .wav or .mp3 file, or None if it can't be read."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    cached = _duration_cache.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]

    duration = None
    try:
        if path.lower().endswith(".wav"):
            duration, _, _ = get_wav_info(path)
        elif path.lower().endswith(".mp3"):
            duration = _mp3_duration_via_ffprobe(path)
            if duration is None and PYDUB_AVAILABLE:
                from pydub import AudioSegment

                audio = AudioSegment.from_file(path)
                duration = len(audio) / 1000.0
    except Exception:
        duration = None

    _duration_cache[path] = (mtime, duration)
    return duration

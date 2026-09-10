"""Pydub/ffmpeg availability and playback helpers."""

import os
import shutil
import sys

from pyp6.config import resource_path

# ---------------------------------------------------------------------------
# pydub / ffmpeg discovery
# ---------------------------------------------------------------------------

try:
    from pydub import AudioSegment

    _bundle_ffmpeg_name = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    _bundle_ffprobe_name = "ffprobe.exe" if sys.platform.startswith("win") else "ffprobe"
    _bundled_ffmpeg = resource_path(_bundle_ffmpeg_name)
    _bundled_ffprobe = resource_path(_bundle_ffprobe_name)

    if os.path.exists(_bundled_ffmpeg):
        _ffmpeg_path = _bundled_ffmpeg
    else:
        _ffmpeg_path = shutil.which("ffmpeg") or "/usr/bin/ffmpeg"
    if os.path.exists(_bundled_ffprobe):
        _ffprobe_path = _bundled_ffprobe
    else:
        _ffprobe_path = shutil.which("ffprobe") or "/usr/bin/ffprobe"

    if os.path.exists(_ffmpeg_path):
        AudioSegment.converter = _ffmpeg_path
        AudioSegment.ffmpeg = _ffmpeg_path
    if os.path.exists(_ffprobe_path):
        AudioSegment.ffprobe = _ffprobe_path
    PYDUB_AVAILABLE = True
    FFMPEG_AVAILABLE = os.path.exists(_ffmpeg_path)
except ImportError:
    PYDUB_AVAILABLE = False
    FFMPEG_AVAILABLE = False

# ---------------------------------------------------------------------------
# sounddevice output device
# ---------------------------------------------------------------------------

try:
    import sounddevice as sd

    def _find_output_device():
        """Return a device index that PortAudio can actually open, or None.

        Strategy: prefer the Core Audio host API default; fall back to the first
        device that has output channels and passes check_output_settings().
        Returns None to let sounddevice use its own default as a last resort.
        """
        try:
            host_apis = sd.query_hostapis()
            for api in host_apis:
                if "Core Audio" in api["name"] and api["default_output_device"] >= 0:
                    idx = api["default_output_device"]
                    try:
                        sd.check_output_settings(device=idx)
                        return idx
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_output_channels"] > 0:
                    try:
                        sd.check_output_settings(device=i)
                        return i
                    except Exception:
                        continue
        except Exception:
            pass

        return None

    SD_OUTPUT_DEVICE = _find_output_device()

    def play_audio(data, samplerate):
        """Play *data* through the current output device.

        Always calls sd.stop() first to release any cached PortAudio stream —
        this is essential on macOS where a stale stream from a disconnected
        device causes paInvalidDevice (-9986) even after the device is
        reconnected.  If the stored device index is no longer valid (hot-plug
        event), it re-runs _find_output_device() and retries once before giving
        up.
        """
        global SD_OUTPUT_DEVICE
        sd.stop()
        try:
            sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)
        except Exception:
            # Device index went stale — re-scan and try once more.
            SD_OUTPUT_DEVICE = _find_output_device()
            sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)

except ImportError:
    sd = None
    SD_OUTPUT_DEVICE = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


_pydub_warning_shown = False  # only nag once per session if pydub is missing


def warn_pydub_missing_once():
    """Shows a one-time notice if the user changes a setting (rate, pitch,
    mono) that requires pydub/ffmpeg to actually take effect at export time."""
    global _pydub_warning_shown
    if PYDUB_AVAILABLE or _pydub_warning_shown:
        return
    _pydub_warning_shown = True
    from pyp6.ui.dialogs_common import dark_showwarning

    dark_showwarning(
        "pydub/ffmpeg missing",
        "Sample rate, pitch and forced mono require pydub + ffmpeg.\n"
        "These settings are saved, but currently have no effect on "
        "Play/Preview/Export while pydub/ffmpeg is missing.",
    )

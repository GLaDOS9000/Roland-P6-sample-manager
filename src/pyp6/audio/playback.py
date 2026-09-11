"""Audio availability and playback helpers."""

import contextlib
import os as _os

from pyp6.log import logger

try:
    import pedalboard  # noqa: F401

    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False

PYDUB_AVAILABLE = AUDIO_AVAILABLE  # backward-compat alias
FFMPEG_AVAILABLE = False  # ffmpeg no longer required; kept for diagnostics

# ---------------------------------------------------------------------------
# sounddevice output device
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _suppress_pa_stderr():
    """Redirect fd-level stderr to /dev/null for the duration of the block.

    PortAudio's AUHAL backend always writes its diagnostic lines straight to
    file descriptor 2 before raising a Python exception, so the usual
    sys.stderr redirect is not enough.  This context manager dups fd 2 away,
    points it at /dev/null, runs the block, then restores fd 2 — even if the
    block raises.  Python's own error messages still land on the *original*
    stderr because we restore before any except clause runs.
    """
    try:
        saved_fd = _os.dup(2)
        devnull = _os.open(_os.devnull, _os.O_WRONLY)
        _os.dup2(devnull, 2)
        _os.close(devnull)
    except OSError:
        yield  # fd operations failed; just run without suppression
        return
    try:
        yield
    finally:
        _os.dup2(saved_fd, 2)
        _os.close(saved_fd)


try:
    import sounddevice as sd

    def _find_output_device(samplerate=None):
        """Return a device index that PortAudio can actually open, or None.

        Strategy: prefer the Core Audio host API default; fall back to the first
        device that has output channels and passes check_output_settings().
        Returns None to let sounddevice use its own default as a last resort.

        When *samplerate* is given the compatibility check includes that rate,
        so the returned device is guaranteed to accept it without resampling.
        """
        try:
            host_apis = sd.query_hostapis()
            for api in host_apis:
                if "Core Audio" in api["name"] and api["default_output_device"] >= 0:
                    idx = api["default_output_device"]
                    try:
                        sd.check_output_settings(device=idx, samplerate=samplerate)
                        logger.debug(f"Audio output: Core Audio default device index {idx}")
                        return idx
                    except Exception as e:
                        logger.debug(f"Audio output: Core Audio default device {idx} rejected: {e}")
        except Exception as e:
            logger.debug(f"Audio output: could not query host APIs: {e}")

        try:
            devices = sd.query_devices()
            for i, dev in enumerate(devices):
                if dev["max_output_channels"] > 0:
                    try:
                        sd.check_output_settings(device=i, samplerate=samplerate)
                        logger.debug(f"Audio output: fallback to device {i} ({dev['name']!r})")
                        return i
                    except Exception:
                        continue
        except Exception as e:
            logger.debug(f"Audio output: device enumeration failed: {e}")

        logger.warning("Audio output: no usable output device found; using sounddevice default")
        return None

    SD_OUTPUT_DEVICE = _find_output_device()

    def play_audio(data, samplerate):
        """Play *data* through the current output device.

        On the first call after a hot-plug event (headphones unplugged then
        replugged) PortAudio's AUHAL backend has a stale device state and will
        fail with -9986.  The recovery sequence:

        1. Try normally — stderr suppressed at the fd level so PortAudio's
           C-level AUHAL diagnostic lines don't pollute the terminal.
        2. On failure: terminate + re-initialize PortAudio so it re-enumerates
           CoreAudio, then pick a new output device that is verified to accept
           *samplerate* before committing to it.
        3. Retry.  If this also fails the exception propagates to the caller.
        """
        global SD_OUTPUT_DEVICE
        sd.stop()

        # First attempt — suppress C-level PortAudio stderr noise because an
        # expected hot-plug failure always prints AUHAL lines before raising.
        first_exc = None
        with _suppress_pa_stderr():
            try:
                sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)
                return
            except Exception as e:
                first_exc = e

        # Hot-plug recovery: force PortAudio to re-enumerate CoreAudio devices.
        logger.warning(f"Audio playback failed ({first_exc}); forcing PortAudio re-enumerate")
        try:
            sd._terminate()
            sd._initialize()
        except Exception as reinit_err:
            logger.debug(f"PortAudio reinit error: {reinit_err}")

        # Re-probe with the actual samplerate so we only pick a device that
        # can accept it — this is the root cause of the double failure.
        SD_OUTPUT_DEVICE = _find_output_device(samplerate)
        sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)

except ImportError:
    sd = None
    SD_OUTPUT_DEVICE = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


_audio_warning_shown = False  # only nag once per session if pedalboard is missing

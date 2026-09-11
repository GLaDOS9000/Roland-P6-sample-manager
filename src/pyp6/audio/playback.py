"""Audio availability and playback helpers."""

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
                        sd.check_output_settings(device=i)
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

        Always calls sd.stop() first to release any cached PortAudio stream.
        On failure (e.g. headphones unplugged/replugged), PortAudio's internal
        device list is stale — a full terminate+initialize cycle forces it to
        re-enumerate CoreAudio devices before retrying once.
        """
        global SD_OUTPUT_DEVICE
        sd.stop()
        try:
            sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)
        except Exception as e:
            # Force PortAudio to re-enumerate devices (handles hot-plug).
            logger.warning(f"Audio playback failed ({e}); forcing PortAudio re-enumerate")
            try:
                sd._terminate()
                sd._initialize()
            except Exception as reinit_err:
                logger.debug(f"PortAudio reinit error: {reinit_err}")
            SD_OUTPUT_DEVICE = _find_output_device()
            sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)

except ImportError:
    sd = None
    SD_OUTPUT_DEVICE = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


_audio_warning_shown = False  # only nag once per session if pedalboard is missing

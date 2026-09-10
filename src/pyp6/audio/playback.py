"""Audio availability and playback helpers."""

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

        Always calls sd.stop() first to release any cached PortAudio stream ---
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
            # Device index went stale --- re-scan and try once more.
            SD_OUTPUT_DEVICE = _find_output_device()
            sd.play(data, samplerate, device=SD_OUTPUT_DEVICE)

except ImportError:
    sd = None
    SD_OUTPUT_DEVICE = None

    def play_audio(data, samplerate):  # noqa: F811
        pass


_audio_warning_shown = False  # only nag once per session if pedalboard is missing

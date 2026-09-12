"""Tests for pyp6.audio.conversion with pedalboard."""

import numpy as np
import pytest


def test_apply_pitch_shift_no_op():
    from pyp6.audio.conversion import apply_pitch_shift

    audio = np.ones((1, 44100), dtype=np.float32)
    result = apply_pitch_shift(audio, 44100, 0)
    assert result is audio


@pytest.mark.requires_pedalboard
def test_apply_pitch_shift_returns_array():
    from pyp6.audio.conversion import apply_pitch_shift

    t = np.linspace(0, 1, 44100, endpoint=False, dtype=np.float32)
    audio = np.sin(2 * np.pi * 440 * t).reshape(1, -1)
    result = apply_pitch_shift(audio, 44100, 100)  # +100 cents
    assert isinstance(result, np.ndarray)
    assert result.shape[0] == 1
    assert result.shape[1] > 0


def test_detect_leading_silence_samples():
    from pyp6.audio.conversion import _detect_leading_silence_samples

    audio = np.zeros((1, 44100), dtype=np.float32)
    audio[0, 500:] = 0.5
    idx = _detect_leading_silence_samples(audio)
    assert idx == 500


def test_normalize_audio():
    from pyp6.audio.conversion import _normalize_audio

    audio = np.array([[0.0, 0.5, -0.25]], dtype=np.float32)
    result = _normalize_audio(audio)
    assert abs(np.max(np.abs(result)) - 1.0) < 1e-6


@pytest.mark.requires_pedalboard
def test_build_chop_file_returns_array(tmp_path):
    import soundfile as sf

    from pyp6.audio.conversion import build_chop_file

    sr = 44100
    fixture = str(tmp_path / "test.wav")
    sf.write(fixture, np.zeros(sr, dtype=np.float32), sr, subtype="PCM_16")

    combined, out_rate = build_chop_file(
        file_paths=[fixture],
        rate=sr,
        channels=1,
        num_slices=2,
        normalize_mode="off",
    )
    assert isinstance(combined, np.ndarray)
    assert combined.shape[0] == 1
    assert out_rate == sr

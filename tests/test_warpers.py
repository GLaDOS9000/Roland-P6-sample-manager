"""Tests for synth/warpers.py."""

import numpy as np
import pytest

from pyp6.synth.warpers import warp_frame


def _sine(n, freq=1, phase=0.0):
    return np.sin(2 * np.pi * freq * np.arange(n) / n + phase)


# ---------------------------------------------------------------------------
# Unit tests — dispatcher
# ---------------------------------------------------------------------------


def test_none_warp_type_is_noop():
    frame = _sine(128)
    result = warp_frame(frame, None, 0.5)
    assert np.array_equal(result, frame)


def test_invalid_warp_type_raises_valueerror():
    with pytest.raises(ValueError, match="Unknown warp_type"):
        warp_frame(_sine(128), "invalid", 0.5)


def test_output_is_float64():
    frame = _sine(128).astype(np.float32)
    for wt in ("pwm", "sync", "fold"):
        result = warp_frame(frame, wt, 0.5)
        assert result.dtype == np.float64, f"{wt}: expected float64"


@pytest.mark.parametrize("n", [128, 127])
@pytest.mark.parametrize("warp_type", ["pwm", "sync", "fold"])
def test_output_length_preserved(n, warp_type):
    frame = _sine(n)
    result = warp_frame(frame, warp_type, 0.5)
    assert len(result) == n


# ---------------------------------------------------------------------------
# Unit tests — PWM bend
# ---------------------------------------------------------------------------


def test_pwm_identity_at_zero_amount():
    frame = _sine(512)
    result = warp_frame(frame, "pwm", 0.0)
    # Both are peak-normalized; compare normalized forms
    peak_in = np.max(np.abs(frame))
    peak_out = np.max(np.abs(result))
    assert np.allclose(result / peak_out, frame / peak_in, atol=1e-9)


@pytest.mark.parametrize("amount", [0.0, 0.3, 0.7, 1.0])
def test_pwm_output_peak_normalized(amount):
    result = warp_frame(_sine(256), "pwm", amount)
    assert np.max(np.abs(result)) <= 1.0 + 1e-9


def test_pwm_silent_frame_safety():
    result = warp_frame(np.zeros(128), "pwm", 0.5)
    assert np.all(result == 0.0)


def test_pwm_breaks_symmetry():
    frame = _sine(512)
    result = warp_frame(frame, "pwm", 0.8)
    peak_in = np.max(np.abs(frame))
    peak_out = np.max(np.abs(result))
    assert not np.allclose(result / peak_out, frame / peak_in, atol=1e-3)


# ---------------------------------------------------------------------------
# Unit tests — Hard sync
# ---------------------------------------------------------------------------


def test_sync_identity_at_zero_amount():
    frame = _sine(512)
    result = warp_frame(frame, "sync", 0.0)
    peak_in = np.max(np.abs(frame))
    peak_out = np.max(np.abs(result))
    assert np.allclose(result / peak_out, frame / peak_in, atol=1e-9)


@pytest.mark.parametrize("amount", [0.0, 0.5, 1.0])
def test_sync_output_peak_normalized(amount):
    result = warp_frame(_sine(256), "sync", amount)
    assert np.max(np.abs(result)) <= 1.0 + 1e-9


def test_sync_silent_frame_safety():
    result = warp_frame(np.zeros(128), "sync", 0.5)
    assert np.all(result == 0.0)


def test_sync_adds_harmonics():
    frame = _sine(2048)
    low_energy = float(np.sum(np.abs(np.fft.rfft(frame)[2:10]) ** 2))
    result = warp_frame(frame, "sync", 0.7)
    high_energy = float(np.sum(np.abs(np.fft.rfft(result)[2:10]) ** 2))
    assert high_energy > low_energy


# ---------------------------------------------------------------------------
# Unit tests — Wavefolding
# ---------------------------------------------------------------------------


def test_fold_identity_at_zero_amount():
    frame = _sine(256)
    result = warp_frame(frame, "fold", 0.0)
    assert np.array_equal(result, frame)


@pytest.mark.parametrize("amount", [0.0, 0.3, 0.7, 1.0])
def test_fold_output_peak_normalized(amount):
    result = warp_frame(_sine(256), "fold", amount)
    assert np.max(np.abs(result)) <= 1.0 + 1e-9


def test_fold_silent_frame_safety():
    result = warp_frame(np.zeros(128), "fold", 0.5)
    assert np.all(result == 0.0)


def test_fold_adds_harmonics():
    # Heavy folding should produce more total harmonic energy (bins > 1)
    # relative to the fundamental than light folding.
    frame = _sine(2048)

    def thd_ratio(result):
        spec = np.abs(np.fft.rfft(result))
        return np.sum(spec[2:] ** 2) / (spec[1] ** 2 + 1e-30)

    assert thd_ratio(warp_frame(frame, "fold", 0.9)) > thd_ratio(warp_frame(frame, "fold", 0.2))


def test_fold_output_bounded_analytically():
    # arcsin(sin(x)) ∈ [-1, 1] by construction; normalization keeps peak = 1
    frame = _sine(512, freq=3, phase=0.3)
    for amount in (0.2, 0.5, 0.9):
        result = warp_frame(frame, "fold", amount)
        assert np.all(np.abs(result) <= 1.0 + 1e-9)


# ---------------------------------------------------------------------------
# Integration tests — wt_build with warp parameters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("warp_type", ["pwm", "sync", "fold"])
def test_wt_build_with_warp_returns_255_segments(warp_type):
    from pyp6.constants import WT_SEGMENTS
    from pyp6.synth.engine import wt_build

    _pcm, rows, _meta = wt_build(
        ["Saw"], midi=60, cycles=2, up_semitones=0, warp_type=warp_type, warp_amount=0.5
    )
    assert len(rows) == WT_SEGMENTS


def test_wt_build_with_warp_pcm_peak_in_range():
    from pyp6.constants import WT_PEAK, WT_SEGMENTS
    from pyp6.synth.engine import wt_build

    pcm, rows, _meta = wt_build(
        ["Saw"], midi=60, cycles=2, up_semitones=0, warp_type="sync", warp_amount=0.6
    )
    assert len(rows) == WT_SEGMENTS
    peak = np.max(np.abs(pcm.astype(np.float32)))
    assert peak >= WT_PEAK * 32767 * 0.5
    assert peak <= 32767


def test_wt_build_warp_none_matches_no_warp_args():
    from pyp6.synth.engine import wt_build

    pcm_default, _rows, _meta = wt_build(["Sine"], midi=60, cycles=2, up_semitones=0)
    pcm_none, _rows2, _meta2 = wt_build(
        ["Sine"], midi=60, cycles=2, up_semitones=0, warp_type=None, warp_amount=0.0
    )
    assert np.array_equal(pcm_default, pcm_none)

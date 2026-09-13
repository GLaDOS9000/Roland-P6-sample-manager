"""Tests for synth/additive.py."""

import numpy as np
import pytest

from pyp6.synth.additive import synthesize_additive

_N_HARMONICS = 32


def _amps(*nonzero):
    """Return a 32-element amp array with the given (index, value) pairs set."""
    a = [0.0] * _N_HARMONICS
    for i, v in nonzero:
        a[i] = v
    return a


def _phases(value=0.0):
    return [value] * _N_HARMONICS


# ---------------------------------------------------------------------------
# Shape and type
# ---------------------------------------------------------------------------


def test_output_shape_default():
    result = synthesize_additive(_amps((0, 1.0)), _phases())
    assert result.shape == (2048,)


def test_output_shape_custom_frame_size():
    for size in (512, 4096):
        result = synthesize_additive(_amps((0, 1.0)), _phases(), frame_size=size)
        assert result.shape == (size,), f"Expected shape ({size},)"


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def test_output_peak_normalized():
    result = synthesize_additive(_amps((0, 1.0)), _phases())
    assert abs(np.max(np.abs(result)) - 1.0) < 1e-10


def test_output_peak_normalized_multi_harmonic():
    # Saw-like: 1/k amplitudes will sum to something > 1 before normalisation
    amps = [1.0 / (k + 1) for k in range(_N_HARMONICS)]
    result = synthesize_additive(amps, _phases())
    assert abs(np.max(np.abs(result)) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Silence / zero-amplitude guard
# ---------------------------------------------------------------------------


def test_all_zero_amps_returns_zeros():
    result = synthesize_additive(_amps(), _phases())
    assert np.all(result == 0.0)
    assert result.shape == (2048,)


# ---------------------------------------------------------------------------
# Harmonic content
# ---------------------------------------------------------------------------


def test_single_harmonic_is_cosine():
    """Fundamental only (k=1, phase=0) must match cos(2π·t) within tolerance.

    irfft of a real-valued bin F[k] reconstructs a cosine at that frequency,
    so zero phase → cosine (starting at peak +1).
    """
    frame_size = 2048
    result = synthesize_additive(_amps((0, 1.0)), _phases(0.0), frame_size=frame_size)
    t = np.arange(frame_size) / frame_size
    ref = np.cos(2 * np.pi * t)
    ref /= np.max(np.abs(ref))
    assert np.allclose(result, ref, atol=1e-9)


def test_phase_shift_rotates_waveform():
    """A π/2 phase shift must rotate the fundamental by a quarter cycle.

    phase=0  → cos(θ)       (starts at +1)
    phase=π/2 → cos(θ+π/2) = -sin(θ)  (starts at 0, first slope negative)
    """
    frame_size = 2048
    result = synthesize_additive(_amps((0, 1.0)), _phases(np.pi / 2), frame_size=frame_size)
    t = np.arange(frame_size) / frame_size
    ref = -np.sin(2 * np.pi * t)
    ref /= np.max(np.abs(ref))
    assert np.allclose(result, ref, atol=1e-9)


def test_harmonic_spectrum_isolation():
    """With amps at k=1 and k=2 only, no other bin should have significant energy."""
    frame_size = 2048
    amps = _amps((0, 1.0), (1, 0.5))
    result = synthesize_additive(amps, _phases(), frame_size=frame_size)
    spectrum = np.abs(np.fft.rfft(result))
    # bins 1 and 2 carry energy; all others should be near zero
    mask = np.ones(len(spectrum), dtype=bool)
    mask[1] = False
    mask[2] = False
    assert spectrum[1] > 0.1
    assert spectrum[2] > 0.1
    assert np.max(spectrum[mask]) < 1e-9


# ---------------------------------------------------------------------------
# Amplitude clipping
# ---------------------------------------------------------------------------


def test_amp_clipping():
    """Amplitudes above 1.0 must be clipped, not passed through."""
    result_clipped = synthesize_additive(_amps((0, 2.0)), _phases())
    result_normal = synthesize_additive(_amps((0, 1.0)), _phases())
    # Both should be the same sine wave (clipping → 1.0, same as explicit 1.0)
    assert np.allclose(result_clipped, result_normal, atol=1e-10)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def test_odd_frame_size_raises():
    with pytest.raises(ValueError, match="even"):
        synthesize_additive(_amps((0, 1.0)), _phases(), frame_size=2047)

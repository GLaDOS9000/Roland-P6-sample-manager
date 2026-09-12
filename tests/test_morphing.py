"""Tests for synth/morphing.py and its integration points in engine.py."""

import numpy as np

from pyp6.synth.morphing import morph_frames


def _sine(n, freq=1, phase=0.0):
    return np.sin(2 * np.pi * freq * np.arange(n) / n + phase)


# ---------------------------------------------------------------------------
# morph_frames unit tests
# ---------------------------------------------------------------------------


def test_identity_at_zero():
    """morph_frames(a, b, 0.0) must reconstruct a."""
    a, b = _sine(128, 1), _sine(128, 3)
    assert np.allclose(morph_frames(a, b, 0.0), a, atol=1e-10)


def test_identity_at_one():
    """morph_frames(a, b, 1.0) must reconstruct b."""
    a, b = _sine(128, 1), _sine(128, 3)
    assert np.allclose(morph_frames(a, b, 1.0), b, atol=1e-10)


def test_output_length_preserved():
    """Output must have the same number of samples as the inputs."""
    a, b = _sine(256, 2), _sine(256, 5)
    assert len(morph_frames(a, b, 0.5)) == 256


def test_output_length_preserved_odd():
    """Odd-length frames must round-trip correctly via irfft(n=…)."""
    a, b = _sine(127, 2), _sine(127, 5)
    assert len(morph_frames(a, b, 0.5)) == 127


def test_preserves_amplitude_on_phase_shifted_frames():
    """Core regression guard: spectral morph must not attenuate a phase-shifted frame.

    Time-domain linear blend of two equal-amplitude sine waves with a 90-degree
    phase offset produces ~0.707 peak amplitude (destructive interference).
    Spectral morphing interpolates magnitude directly, so the output should
    remain near 1.0.
    """
    a = _sine(128, 1, phase=0.0)
    b = _sine(128, 1, phase=np.pi / 2)
    result = morph_frames(a, b, 0.5)
    assert np.max(np.abs(result)) > 0.9


def test_magnitude_linearity():
    """Magnitude at a given bin must interpolate linearly between the two inputs."""
    N = 256
    a = _sine(N, 3)
    b = 0.5 * _sine(N, 3, phase=0.3)
    result = morph_frames(a, b, 0.5)
    mag_expected = (np.abs(np.fft.rfft(a)[3]) + np.abs(np.fft.rfft(b)[3])) / 2
    assert abs(np.abs(np.fft.rfft(result)[3]) - mag_expected) < 1e-9


# ---------------------------------------------------------------------------
# Integration smoke tests
# ---------------------------------------------------------------------------


def test_wt_build_segment_count_invariant():
    """wt_build must always return exactly 255 rows regardless of family count."""
    from pyp6.constants import WT_SEGMENTS
    from pyp6.synth.engine import wt_build

    for families in [["Saw"], ["Saw", "Sine"], ["Saw", "FM", "Bell / Metal"]]:
        _, rows, _ = wt_build(families, midi=60, cycles=2, up_semitones=0)
        assert len(rows) == WT_SEGMENTS, f"Expected {WT_SEGMENTS} rows for {families}"


def test_wt_render_sweep_shape_and_dtype():
    """wt_render_sweep must return a float32 array of the expected length."""
    from pyp6.constants import WT_PREVIEW_SECONDS, WT_SR
    from pyp6.synth.engine import wt_render_sweep

    audio = wt_render_sweep("Saw", midi=60, cycles=2, up_semitones=0, steps=4)
    assert audio.dtype == np.float32
    assert len(audio) == int(WT_PREVIEW_SECONDS * WT_SR)

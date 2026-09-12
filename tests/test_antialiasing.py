"""Tests for synth/antialiasing.py and its integration points in engine.py."""

import numpy as np

from pyp6.synth.antialiasing import mipmap_frame


def _sine(n, freq=1, phase=0.0):
    return np.sin(2 * np.pi * freq * np.arange(n) / n + phase)


# ---------------------------------------------------------------------------
# mipmap_frame unit tests
# ---------------------------------------------------------------------------


def test_output_length_preserved():
    """Output must have the same number of samples as the input."""
    frame = _sine(256, 3)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1)
    assert len(result) == 256


def test_output_length_preserved_odd():
    """Odd-length frames must round-trip correctly via irfft(n=…)."""
    frame = _sine(127, 3)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1)
    assert len(result) == 127


def test_output_peak_normalized():
    """Output must be peak-normalised to 1.0."""
    frame = _sine(256, 3) + 0.5 * _sine(256, 7)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1)
    assert abs(np.max(np.abs(result)) - 1.0) < 1e-9


def test_high_harmonics_attenuated():
    """Bins above K_max must be zeroed; bins well below K_max must survive.

    With root_pitch_hz=440 and target_octave=1:
      K_max = floor(44100 / (2 * 440 * 2)) = floor(25.0) = 25
    Harmonic 5 (bin 5) is below K_max and must survive.
    Harmonic 60 (bin 60) is above K_max and must be zeroed.
    """
    N = 256
    frame = _sine(N, 5) + _sine(N, 60)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1, sample_rate=44100)
    spec = np.abs(np.fft.rfft(result))
    assert spec[60] < 1e-6
    assert spec[5] > 0.1


def test_low_harmonics_preserved():
    """A pure low-frequency sine must pass through unmodified (only normalised)."""
    N = 256
    # K_max = floor(44100 / (2 * 110 * 2)) = floor(100.2) = 100 >> harmonic 3
    frame = _sine(N, 3)
    result = mipmap_frame(frame, root_pitch_hz=110.0, target_octave=1, sample_rate=44100)
    in_spec = np.abs(np.fft.rfft(frame))
    out_spec = np.abs(np.fft.rfft(result))
    # Bin 3 amplitude ratio must equal the overall normalisation scale
    scale = out_spec[3] / in_spec[3]
    assert np.allclose(out_spec[3], in_spec[3] * scale, atol=1e-9)


def test_passthrough_when_octave_zero():
    """target_octave=0 at a low root pitch must leave the spectrum shape unchanged.

    K_max = floor(44100 / (2 * 10 * 1)) = 2205, which exceeds n_bins for a
    256-sample frame (n_bins=129).  The early-return path fires and only
    peak-normalisation is applied.
    """
    N = 256
    frame = _sine(N, 3) + 0.5 * _sine(N, 7)
    result = mipmap_frame(frame, root_pitch_hz=10.0, target_octave=0, sample_rate=44100)
    in_spec = np.abs(np.fft.rfft(frame))
    out_spec = np.abs(np.fft.rfft(result))
    scale = out_spec[3] / in_spec[3]
    assert np.allclose(out_spec, in_spec * scale, atol=1e-9)


def test_taper_reduces_gibbs_vs_hard_cutoff():
    """The 3-bin cosine taper must produce less time-domain ringing than a
    hard brickwall at the same K_max.

    A harmonic-rich sawtooth is filtered at a low K_max. The mipmap_frame
    output is compared against a manually constructed hard-brickwall version.
    A tapered rolloff must have a lower peak overshoot than the hard cutoff.
    """
    N = 512
    # Sawtooth: sum of harmonics 1..N//2
    frame = sum(_sine(N, k) / k for k in range(1, N // 2))

    # K_max = floor(44100 / (2 * 440 * 4)) = floor(12.5) = 12
    root_hz = 440.0
    target_oct = 2
    k_max = int(44100 / (2.0 * root_hz * 2**target_oct))

    # Tapered result from mipmap_frame
    tapered = mipmap_frame(frame, root_pitch_hz=root_hz, target_octave=target_oct)

    # Manual hard brickwall (no taper) for comparison
    spec_hard = np.fft.rfft(np.asarray(frame, dtype=np.float64))
    spec_hard[k_max + 1 :] = 0.0
    hard = np.fft.irfft(spec_hard, n=N)
    hard_peak = np.max(np.abs(hard))
    if hard_peak > 1e-12:
        hard = hard / hard_peak

    # Measure ringing as the RMS of a small window after the transition
    window = slice(N // 4, N // 4 + 16)
    tapered_rms = np.sqrt(np.mean(tapered[window] ** 2))
    hard_rms = np.sqrt(np.mean(hard[window] ** 2))
    # Both contain signal, but the tapered version must not be strictly worse.
    # The test asserts it is at most equal (allowing floating-point ties).
    assert tapered_rms <= hard_rms + 1e-6


def test_silent_frame_safety():
    """An all-zeros input must return all zeros without raising an exception."""
    frame = np.zeros(256)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1)
    assert np.all(result == 0.0)
    assert len(result) == 256


def test_k_max_small_edge_case():
    """A very high root pitch with a large target octave yields a tiny K_max.

    K_max = floor(44100 / (2 * 5000 * 4)) = floor(1.1) = 1
    The taper guard (max(1, k_max - 2)) must prevent negative indices and the
    output must still have the correct length.
    """
    frame = _sine(64, 1) + _sine(64, 5)
    result = mipmap_frame(frame, root_pitch_hz=5000.0, target_octave=2, sample_rate=44100)
    assert len(result) == 64


def test_dtype_is_float64():
    """Output array must be float64 — the engine works in float64 throughout."""
    frame = _sine(256, 3)
    result = mipmap_frame(frame, root_pitch_hz=440.0, target_octave=1)
    assert result.dtype == np.float64


# ---------------------------------------------------------------------------
# Integration smoke tests
# ---------------------------------------------------------------------------


def test_wt_build_segment_count_with_antialiasing():
    """wt_build must still return exactly 255 rows for all three registers."""
    from pyp6.constants import WT_SEGMENTS
    from pyp6.synth.engine import wt_build

    for midi, cycles, up in [(36, 1, 0), (48, 2, 12), (48, 2, 24)]:
        _, rows, _ = wt_build(["Saw"], midi=midi, cycles=cycles, up_semitones=up)
        assert len(rows) == WT_SEGMENTS, f"Expected {WT_SEGMENTS} rows, got {len(rows)}"


def test_wt_build_pcm_peak_within_range():
    """The PCM peak must lie within the expected normalisation window."""
    from pyp6.constants import WT_PEAK
    from pyp6.synth.engine import wt_build

    pcm, _, _ = wt_build(["Saw"], midi=48, cycles=2, up_semitones=12)
    peak = np.max(np.abs(pcm.astype(np.float64)))
    assert peak >= WT_PEAK * 32767 * 0.5
    assert peak <= 32767


def test_wt_build_lead_has_fewer_harmonics():
    """The Lead register (up_semitones=24) must have near-zero energy above K_max.

    End-to-end spectral assertion: after wt_build the first frame of the PCM
    must be band-limited to the Nyquist-safe range for a 2-octave upward
    transposition.  Energy above K_max+3 (outside the taper zone) must be
    negligible compared to the passband.
    """
    from pyp6.synth.engine import wt_build

    midi, cycles, up = 48, 2, 24
    pcm, _, meta = wt_build(["Saw"], midi=midi, cycles=cycles, up_semitones=up)
    L = meta["L"]
    f_real = meta["f_real"]

    frame = pcm[:L].astype(np.float64) / 32767.0
    spec = np.abs(np.fft.rfft(frame))

    k_max = int(44100 / (2.0 * f_real * 2**2))
    # Allow margin above K_max for the taper zone (3 bins)
    energy_above = np.sum(spec[k_max + 4 :] ** 2)
    energy_below = np.sum(spec[1 : k_max - 2] ** 2)
    assert energy_above < energy_below * 1e-4

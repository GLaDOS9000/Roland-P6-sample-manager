"""Multi-octave mipmapping (anti-aliasing) for wavetable frames."""

import numpy as np


def mipmap_frame(frame_data, root_pitch_hz, target_octave, sample_rate=44100):
    """Return an anti-aliased copy of frame_data safe for upward transposition.

    Computes the maximum safe harmonic index K_max for the given root pitch
    transposed up by target_octave octaves, zeros all FFT bins above K_max,
    applies a 3-bin raised-cosine taper at the cutoff to suppress Gibbs
    ringing, then reconstructs via irfft and peak-normalises to 1.0.

    When K_max covers the full spectrum (e.g. target_octave=0 at low root
    pitches), no filtering is applied and the function acts as a pure peak
    normaliser.
    """
    n = len(frame_data)
    spec = np.fft.rfft(np.asarray(frame_data, dtype=np.float64))
    n_bins = len(spec)
    k_max = int(sample_rate / (2.0 * root_pitch_hz * 2**target_octave))

    if k_max + 1 >= n_bins:
        # K_max covers the full spectrum — passthrough + normalize
        w = np.fft.irfft(spec, n=n)
        peak = np.max(np.abs(w))
        return w / peak if peak > 1e-12 else w

    # Step 1: zero all bins above K_max
    spec[k_max + 1 :] = 0.0

    # Step 2: 3-bin raised-cosine taper at [K_max-2, K_max-1, K_max]
    # weights: 1.0, 0.5, 0.0 — smooth rolloff to suppress Gibbs ringing
    taper_start = max(1, k_max - 2)
    taper_len = k_max - taper_start + 1
    offsets = np.arange(3 - taper_len, 3)
    spec[taper_start : k_max + 1] *= 0.5 * (1.0 + np.cos(offsets * np.pi / 2))

    w = np.fft.irfft(spec, n=n)
    peak = np.max(np.abs(w))
    return w / peak if peak > 1e-12 else w

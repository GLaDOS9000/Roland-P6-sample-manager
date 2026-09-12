"""Phase-aligned spectral morphing for wavetable frames."""

import numpy as np

SWEEP_MORPH_DENSITY = 64  # Dense intermediate frames for preview sweep
BLEND_STEPS = 2  # Frames replaced per side at cross-family boundaries


def morph_frames(frame_a, frame_b, t):
    """Return a spectrally-morphed frame at position t in [0.0, 1.0].

    Both frames must be the same length and already band-limited.
    Interpolates magnitude and unwrapped phase linearly in the frequency
    domain, then reconstructs via irfft.  No normalization is applied;
    callers are responsible for peak-normalizing the output.
    """
    n = len(frame_a)
    FA = np.fft.rfft(frame_a)
    FB = np.fft.rfft(frame_b)
    mag_t = (1.0 - t) * np.abs(FA) + t * np.abs(FB)
    phi_t = (1.0 - t) * np.unwrap(np.angle(FA)) + t * np.unwrap(np.angle(FB))
    return np.fft.irfft(mag_t * np.exp(1j * phi_t), n=n)

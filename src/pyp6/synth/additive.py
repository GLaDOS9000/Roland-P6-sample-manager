"""Additive synthesis DSP module.

Constructs single-cycle waveframes from a harmonic amplitude and phase
spectrum, following the spec for the Interactive 32-Harmonic Additive Editor.
"""

import numpy as np


def synthesize_additive(amps, phases, frame_size=2048):
    """Build a single-cycle waveform from up to 32 harmonic partials.

    Constructs a complex spectrum by placing each harmonic at its bin with the
    given amplitude and phase, then reconstructs via inverse real FFT and
    peak-normalizes the result.

    Parameters
    ----------
    amps : array-like of float
        Harmonic amplitudes, length ≤ 32.  Values are clipped to [0.0, 1.0].
        Index 0 → fundamental (k=1), index 1 → 2nd harmonic (k=2), etc.
    phases : array-like of float
        Harmonic phases in **radians**, same length as *amps*.  Values are
        wrapped to [0, 2π).
    frame_size : int, optional
        Number of output samples.  Must be even.  Default 2048.

    Returns
    -------
    numpy.ndarray, shape (frame_size,), dtype float64
        Peak-normalised waveform in [-1.0, 1.0].  Returns an all-zero array
        when all amplitudes are zero or the synthesised signal is silent.

    Raises
    ------
    ValueError
        If *frame_size* is odd (``np.fft.irfft`` requires an even *n* to
        round-trip correctly when the spectrum was built from ``frame_size //
        2 + 1`` bins).

    Notes
    -----
    The spectrum is populated as::

        F[k] = amps[k-1] * (frame_size / 2) * exp(i * phases[k-1])

    which ensures that after ``irfft`` the peak amplitude of the fundamental
    at full gain is 1.0 before normalisation.  The final peak-normalisation
    step scales the mixture to fill [-1, 1] regardless of harmonic
    interactions.
    """
    if frame_size % 2 != 0:
        raise ValueError(
            f"frame_size must be even, got {frame_size}. "
            "np.fft.irfft requires an even n to reconstruct correctly."
        )

    amps = np.clip(np.asarray(amps, dtype=float), 0.0, 1.0)
    phases = np.asarray(phases, dtype=float) % (2 * np.pi)

    n_harmonics = len(amps)

    F = np.zeros(frame_size // 2 + 1, dtype=complex)
    scale = frame_size / 2
    for k in range(1, n_harmonics + 1):
        F[k] = amps[k - 1] * scale * np.exp(1j * phases[k - 1])

    raw = np.fft.irfft(F, n=frame_size)

    peak = np.max(np.abs(raw))
    if peak < 1e-12:
        return np.zeros(frame_size, dtype=float)

    return raw / peak

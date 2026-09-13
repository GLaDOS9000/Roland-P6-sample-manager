"""Post-oscillator phase-bend and waveshaping for wavetable frames."""

import numpy as np

_EPS = 1e-6  # Guard against degenerate duty cycle (w→0 or w→1)
_SYNC_MAX = 8.0  # Maximum sync ratio
_FOLD_T_MIN = 0.1  # Minimum fold threshold


def _interp(frame_data, p_prime):
    """Linear interpolation of frame_data at fractional positions p_prime ∈ [0, 1)."""
    n = len(frame_data)
    src = p_prime * n
    i0 = np.floor(src).astype(int) % n
    i1 = (i0 + 1) % n
    frac = src - np.floor(src)
    return frame_data[i0] * (1.0 - frac) + frame_data[i1] * frac


def _normalize(x):
    """Peak-normalize to [-1, 1]; return as-is if silent."""
    peak = np.max(np.abs(x))
    return x / peak if peak > 1e-12 else x


def _pwm_bend(frame_data, warp_amount):
    """Asymmetric phase bend (PWM emulation).

    Maps output position p through a piecewise-linear duty-cycle remap, then
    samples the original frame via linear interpolation.  At warp_amount=0.0
    the duty-cycle midpoint w=0.5, giving the identity transform.
    """
    peak = np.max(np.abs(frame_data))
    if peak < 1e-12:
        return frame_data.copy()

    # warp_amount 0.0 → w=0.5 (identity), 1.0 → w≈1.0 (extreme skew)
    w = 0.5 + warp_amount * (0.5 - _EPS)

    p = np.arange(len(frame_data)) / len(frame_data)
    p_prime = np.where(
        p < w,
        0.5 / w * p,
        0.5 + 0.5 / (1.0 - w) * (p - w),
    )
    return _normalize(_interp(frame_data, p_prime))


def _hard_sync(frame_data, warp_amount):
    """Hard sync: phase compression by factor s.

    Compresses the phase read-index by s, wrapping modulo 1.0, which re-starts
    the waveform s times per cycle.  At warp_amount=0.0, s=1.0 gives the
    identity transform.
    """
    peak = np.max(np.abs(frame_data))
    if peak < 1e-12:
        return frame_data.copy()

    # warp_amount 0.0 → s=1.0 (identity), 1.0 → s=8.0
    s = 1.0 + warp_amount * (_SYNC_MAX - 1.0)

    p = np.arange(len(frame_data)) / len(frame_data)
    p_prime = (p * s) % 1.0
    return _normalize(_interp(frame_data, p_prime))


def _wavefold(frame_data, warp_amount):
    """Wavefolding via arcsin(sin(π/T·x)) / (π/2).

    Applies a smooth triangle-wave transfer function to the signal amplitude.
    Lower threshold T produces more aggressive folding.  At warp_amount=0.0
    an early-return guard ensures a strict identity (no processing applied).
    """
    if warp_amount == 0.0:
        return frame_data.copy()

    peak = np.max(np.abs(frame_data))
    if peak < 1e-12:
        return frame_data.copy()

    # warp_amount 0.0 → T=1.0 (softest), 1.0 → T=0.1 (most aggressive)
    T = 1.0 - warp_amount * (1.0 - _FOLD_T_MIN)

    result = np.arcsin(np.sin(np.pi / T * frame_data)) / (np.pi / 2.0)
    return _normalize(result)


_WARPERS = {
    "pwm": _pwm_bend,
    "sync": _hard_sync,
    "fold": _wavefold,
}


def warp_frame(frame_data, warp_type, warp_amount):
    """Apply a post-oscillator warp to one wavetable frame.

    Parameters
    ----------
    frame_data : array-like
        One cycle of audio, any length. Coerced to float64.
    warp_type : str or None
        One of ``"pwm"``, ``"sync"``, ``"fold"``, or ``None``.
        ``None`` is a no-op and returns the input unchanged.
    warp_amount : float
        Warp intensity in ``[0.0, 1.0]``.  ``0.0`` is always the identity
        transform regardless of warp_type.

    Returns
    -------
    numpy.ndarray
        float64, same length as *frame_data*, peak-normalized to [-1, 1].

    Raises
    ------
    ValueError
        If *warp_type* is not ``None`` and not a recognized warp name.
    """
    x = np.asarray(frame_data, dtype=np.float64)
    if warp_type is None:
        return x
    try:
        fn = _WARPERS[warp_type]
    except KeyError:
        raise ValueError(f"Unknown warp_type {warp_type!r}. Valid options are: {sorted(_WARPERS)}")
    return fn(x, float(warp_amount))

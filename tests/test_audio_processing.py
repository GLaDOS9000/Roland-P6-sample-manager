"""Tests for pyp6.audio.processing."""

import numpy as np

from pyp6.audio.processing import find_zero_crossing


def test_find_zero_crossing_at_boundary():
    """find_zero_crossing should return a frame index near the target."""
    # Simple sine wave crossing zero at the midpoint.
    sr = 44100
    t = np.linspace(0, 1, sr, endpoint=False)
    data = np.sin(2 * np.pi * 1 * t)  # 1 Hz sine
    target = sr // 2  # roughly at the zero crossing
    idx = find_zero_crossing(data, target, search_radius=1000)
    # The returned index should be close to the target.
    assert abs(idx - target) < 100

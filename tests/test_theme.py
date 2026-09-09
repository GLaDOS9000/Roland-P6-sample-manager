"""Tests for pyp6.theme."""

from pyp6.theme import THEMES, blend_colors, readable_on


def test_themes_dict_not_empty():
    """At least the default 'dark' theme should exist."""
    assert "dark" in THEMES


def test_blend_colors_midpoint():
    """Blending black and white at 0.5 should give a mid-grey."""
    result = blend_colors("#000000", "#ffffff", 0.5)
    # Accept anything near #808080.
    r = int(result[1:3], 16)
    g = int(result[3:5], 16)
    b = int(result[5:7], 16)
    assert 120 <= r <= 136
    assert 120 <= g <= 136
    assert 120 <= b <= 136


def test_readable_on_returns_string():
    """readable_on should return a hex colour string."""
    colour = readable_on("#ffffff", "#1a1a2e")
    assert colour.startswith("#")
    assert len(colour) == 7

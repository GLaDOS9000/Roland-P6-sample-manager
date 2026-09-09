"""Tests for pyp6.synth.engine."""

from pyp6.synth.engine import midi_to_hz, midi_to_name


def test_midi_to_hz_a4():
    """MIDI note 69 is A4 = 440 Hz."""
    assert abs(midi_to_hz(69) - 440.0) < 0.01


def test_midi_to_name_middle_c():
    """MIDI note 60 should map to C4."""
    assert midi_to_name(60) == "C4"

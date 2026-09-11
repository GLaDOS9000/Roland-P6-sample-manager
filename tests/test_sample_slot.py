"""Tests for SampleSlot data-layer logic.

SampleSlot.__init__ creates Tkinter widgets, which requires a display.
We bypass __init__ with object.__new__ and supply lightweight stand-ins
for every Tk attribute the methods under test actually read or write.
This lets the core logic run on headless CI without mocking the entire
Tkinter module.
"""

import pytest

from pyp6.constants import PITCH_MAX_CENTS, PITCH_MIN_CENTS

# ---------------------------------------------------------------------------
# Stand-ins for Tk vars / widgets
# ---------------------------------------------------------------------------


class _Var:
    """Stand-in for tk.IntVar / tk.BooleanVar / tk.StringVar."""

    def __init__(self, value=None):
        self._value = value

    def get(self):
        return self._value

    def set(self, value):
        self._value = value


class _Entry:
    """Stand-in for tk.Entry."""

    def __init__(self, value="0"):
        self._value = value

    def get(self):
        return self._value

    def delete(self, *_args):
        self._value = ""

    def insert(self, _idx, text):
        self._value = str(text)


class _Label:
    """Stand-in for tk.Label."""

    def __init__(self, text=""):
        self._attrs = {"text": text, "fg": ""}

    def cget(self, key):
        return self._attrs.get(key, "")

    def config(self, **kwargs):
        self._attrs.update(kwargs)


class _App:
    """Minimal app stub — only the attributes sample_slot methods touch."""

    class current_bank:
        @staticmethod
        def get():
            return "A"

    def update_pad_warnings(self):
        pass

    def update_storage_display(self):
        pass

    def stop_and_refresh_waveform_for(self, *_args):
        pass


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def slot():
    """A SampleSlot that skipped __init__, populated with fake attributes.

    Only the attributes that the methods under test actually access are
    set — anything else remains unset, so an accidental call into an
    untested code path will raise AttributeError rather than silently
    passing.
    """
    from pyp6.model.sample_slot import SampleSlot

    s = object.__new__(SampleSlot)
    s.pad_num = 1
    s.app = _App()
    s.filepath = None
    s.display_name = None
    s.target_rate = _Var(44100)
    s.pitch_cents = _Var(0)
    s.mono_var = _Var(False)
    s.wavetable = None
    s.wt_patch = _Var("Init")
    s.wt_poly = _Var(False)
    s.label = _Label()
    s.pitch_entry = _Entry("0")
    # Stub out side-effectful methods that touch widgets not set up here.
    s.update_warning = lambda: None
    s.update_mini_waveform = lambda: None
    return s


# ---------------------------------------------------------------------------
# _bank_letter
# ---------------------------------------------------------------------------


def test_bank_letter_reads_from_app(slot):
    assert slot._bank_letter() == "A"


def test_bank_letter_falls_back_on_error(slot):
    # Simulate an app whose StringVar raises (e.g. not yet initialised).
    class _BrokenBank:
        def get(self):
            raise RuntimeError("not ready")

    slot.app.current_bank = _BrokenBank()
    # Should not raise; returns the first bank letter.
    result = slot._bank_letter()
    assert isinstance(result, str)
    assert len(result) == 1


# ---------------------------------------------------------------------------
# get_state
# ---------------------------------------------------------------------------


def test_get_state_returns_none_when_no_file(slot):
    assert slot.get_state() is None


def test_get_state_returns_full_dict(slot, tmp_path):
    wav = tmp_path / "kick.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "kick.wav"

    state = slot.get_state()

    assert state["filepath"] == str(wav)
    assert state["target_rate"] == 44100
    assert state["pitch_cents"] == 0
    assert state["mono"] is False
    assert state["display_name"] == "kick.wav"
    assert state["wavetable"] is None
    assert state["wt_patch"] == "Init"
    assert state["wt_poly"] is False


def test_get_state_preserves_non_default_pitch(slot, tmp_path):
    wav = tmp_path / "snare.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "snare.wav"
    slot.pitch_cents.set(300)
    slot.target_rate.set(22050)
    slot.mono_var.set(True)

    state = slot.get_state()

    assert state["pitch_cents"] == 300
    assert state["target_rate"] == 22050
    assert state["mono"] is True


def test_get_state_includes_wavetable(slot, tmp_path):
    wav = tmp_path / "wt.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "Wavetable C2 (Bass)"
    slot.wavetable = {"config": {"mode": "Simple", "note": "C2"}, "meta": {"L": 674}}

    state = slot.get_state()

    assert state["wavetable"] == slot.wavetable


def test_get_state_detects_from_sync_flag(slot, tmp_path):
    wav = tmp_path / "sync.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "sync.wav"
    # Simulate a pad that came in via "P6 → Bank" — the label carries a tag.
    slot.label.config(text="sync.wav [on device]")

    state = slot.get_state()

    assert state["from_sync"] is True


def test_get_state_from_sync_false_without_tag(slot, tmp_path):
    wav = tmp_path / "local.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "local.wav"
    slot.label.config(text="local.wav")

    state = slot.get_state()

    assert state["from_sync"] is False


# ---------------------------------------------------------------------------
# _set_pitch — clamping and entry sync
# ---------------------------------------------------------------------------


def test_set_pitch_normal_value(slot):
    slot._set_pitch(100)
    assert slot.pitch_cents.get() == 100
    assert slot.pitch_entry.get() == "100"


def test_set_pitch_clamps_to_minimum(slot):
    slot._set_pitch(PITCH_MIN_CENTS - 500)
    assert slot.pitch_cents.get() == PITCH_MIN_CENTS


def test_set_pitch_clamps_to_maximum(slot):
    slot._set_pitch(PITCH_MAX_CENTS + 500)
    assert slot.pitch_cents.get() == PITCH_MAX_CENTS


def test_set_pitch_at_exact_boundary_min(slot):
    slot._set_pitch(PITCH_MIN_CENTS)
    assert slot.pitch_cents.get() == PITCH_MIN_CENTS


def test_set_pitch_at_exact_boundary_max(slot):
    slot._set_pitch(PITCH_MAX_CENTS)
    assert slot.pitch_cents.get() == PITCH_MAX_CENTS


def test_set_pitch_syncs_entry_widget(slot):
    slot._set_pitch(-300)
    assert slot.pitch_entry.get() == "-300"


def test_set_pitch_zero(slot):
    slot.pitch_cents.set(200)
    slot._set_pitch(0)
    assert slot.pitch_cents.get() == 0
    assert slot.pitch_entry.get() == "0"


# ---------------------------------------------------------------------------
# apply_state — early-return branches (no widget creation needed)
# ---------------------------------------------------------------------------


def test_apply_state_none_clears_pad(slot):
    cleared = []
    slot.clear_pad = lambda: cleared.append(True)

    slot.apply_state(None)

    assert cleared, "clear_pad should have been called for a None state"


def test_apply_state_empty_dict_clears_pad(slot):
    cleared = []
    slot.clear_pad = lambda: cleared.append(True)

    slot.apply_state({})

    assert cleared


def test_apply_state_missing_file_clears_pad(slot, tmp_path):
    cleared = []
    slot.clear_pad = lambda: cleared.append(True)

    state = {
        "filepath": str(tmp_path / "nonexistent.wav"),
        "target_rate": 44100,
        "pitch_cents": 0,
        "mono": False,
        "display_name": "ghost.wav",
        "wavetable": None,
        "wt_patch": "Init",
        "wt_poly": False,
        "from_sync": False,
    }
    slot.apply_state(state)

    assert cleared, "clear_pad should be called when the referenced file is gone"


def test_apply_state_no_filepath_key_clears_pad(slot):
    cleared = []
    slot.clear_pad = lambda: cleared.append(True)

    slot.apply_state({"target_rate": 44100, "pitch_cents": 0})

    assert cleared


# ---------------------------------------------------------------------------
# get_state / apply_state round-trip (state dict shape)
# ---------------------------------------------------------------------------


def test_state_keys_are_complete(slot, tmp_path):
    """get_state must return all keys that apply_state reads."""
    wav = tmp_path / "sample.wav"
    wav.touch()
    slot.filepath = str(wav)
    slot.display_name = "sample.wav"

    state = slot.get_state()

    required = {
        "filepath",
        "target_rate",
        "pitch_cents",
        "mono",
        "from_sync",
        "display_name",
        "wavetable",
        "wt_patch",
        "wt_poly",
    }
    assert required <= state.keys()

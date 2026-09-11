"""Integration tests for pyp6.config.verify_preset_folder.

Each test builds a preset directory on disk (via tmp_path) so the check
exercises the real filesystem logic, not a mock.
"""

import wave

from pyp6.config import verify_preset_folder, write_preset_manifest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_wav(path, num_frames=100, sample_rate=44100, channels=1):
    """Write a minimal but valid WAV file at *path*."""
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * num_frames * channels)


def _simple_manifest(rel_path):
    """A manifest with one bank-A pad-1 entry pointing at *rel_path*."""
    return {
        "format_version": 3,
        "banks": {"A": {"pads": {"1": {"filepath": rel_path}}}},
    }


# ---------------------------------------------------------------------------
# Missing / malformed manifest
# ---------------------------------------------------------------------------


def test_missing_manifest(tmp_path):
    problems, strays = verify_preset_folder(str(tmp_path))
    assert any("missing" in p.lower() or "unreadable" in p.lower() for p in problems)
    assert strays == []


def test_valid_empty_banks(tmp_path):
    write_preset_manifest(str(tmp_path), {"format_version": 3, "banks": {}})
    problems, strays = verify_preset_folder(str(tmp_path))
    assert problems == []
    assert strays == []


# ---------------------------------------------------------------------------
# Clean preset
# ---------------------------------------------------------------------------


def test_valid_preset_no_problems(tmp_path):
    pad_dir = tmp_path / "BANK_A" / "PAD_1"
    pad_dir.mkdir(parents=True)
    wav = pad_dir / "kick.wav"
    _write_wav(wav)

    write_preset_manifest(str(tmp_path), _simple_manifest("BANK_A/PAD_1/kick.wav"))

    problems, strays = verify_preset_folder(str(tmp_path))
    assert problems == []


def test_valid_preset_stray_file_detected(tmp_path):
    """A file in the folder but not referenced in the manifest is a stray."""
    pad_dir = tmp_path / "BANK_A" / "PAD_1"
    pad_dir.mkdir(parents=True)
    wav = pad_dir / "kick.wav"
    _write_wav(wav)
    stray = tmp_path / "leftover.wav"
    _write_wav(stray)

    write_preset_manifest(str(tmp_path), _simple_manifest("BANK_A/PAD_1/kick.wav"))

    problems, strays = verify_preset_folder(str(tmp_path))
    assert problems == []
    assert "leftover.wav" in strays


# ---------------------------------------------------------------------------
# Path portability checks
# ---------------------------------------------------------------------------


def test_absolute_filepath_is_rejected(tmp_path):
    manifest = _simple_manifest("/absolute/path/sample.wav")
    write_preset_manifest(str(tmp_path), manifest)

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("not relative" in p for p in problems)


def test_dotdot_escape_is_rejected(tmp_path):
    manifest = _simple_manifest("../outside/sample.wav")
    write_preset_manifest(str(tmp_path), manifest)

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("not relative" in p for p in problems)


# ---------------------------------------------------------------------------
# Missing / empty / unreadable sample files
# ---------------------------------------------------------------------------


def test_missing_sample_file(tmp_path):
    write_preset_manifest(str(tmp_path), _simple_manifest("BANK_A/PAD_1/ghost.wav"))

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("missing" in p for p in problems)


def test_empty_sample_file(tmp_path):
    pad_dir = tmp_path / "BANK_A" / "PAD_1"
    pad_dir.mkdir(parents=True)
    (pad_dir / "empty.wav").write_bytes(b"")

    write_preset_manifest(str(tmp_path), _simple_manifest("BANK_A/PAD_1/empty.wav"))

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("empty" in p or "0 bytes" in p for p in problems)


def test_unreadable_wav(tmp_path):
    pad_dir = tmp_path / "BANK_A" / "PAD_1"
    pad_dir.mkdir(parents=True)
    bad = pad_dir / "bad.wav"
    bad.write_bytes(b"this is not a WAV file at all")

    write_preset_manifest(str(tmp_path), _simple_manifest("BANK_A/PAD_1/bad.wav"))

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("not a readable WAV" in p or "readable" in p.lower() for p in problems)


def test_no_filepath_key(tmp_path):
    manifest = {
        "format_version": 3,
        "banks": {"A": {"pads": {"1": {"filepath": ""}}}},
    }
    write_preset_manifest(str(tmp_path), manifest)

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("no file" in p.lower() for p in problems)


# ---------------------------------------------------------------------------
# Multiple pads — partial problems
# ---------------------------------------------------------------------------


def test_two_pads_one_missing(tmp_path):
    pad1_dir = tmp_path / "BANK_A" / "PAD_1"
    pad1_dir.mkdir(parents=True)
    _write_wav(pad1_dir / "kick.wav")

    manifest = {
        "format_version": 3,
        "banks": {
            "A": {
                "pads": {
                    "1": {"filepath": "BANK_A/PAD_1/kick.wav"},
                    "2": {"filepath": "BANK_A/PAD_2/snare.wav"},  # missing
                }
            }
        },
    }
    write_preset_manifest(str(tmp_path), manifest)

    problems, _ = verify_preset_folder(str(tmp_path))
    # Exactly one problem — the missing snare, not the valid kick
    assert len(problems) == 1
    assert "snare.wav" in problems[0]


# ---------------------------------------------------------------------------
# Format version check
# ---------------------------------------------------------------------------


def test_future_format_version_flagged(tmp_path):
    manifest = {"format_version": 9999, "banks": {}}
    write_preset_manifest(str(tmp_path), manifest)

    problems, _ = verify_preset_folder(str(tmp_path))
    assert any("format version" in p for p in problems)

"""Tests for pyp6.config."""

import os

from pyp6.config import ensure_app_dirs


def test_ensure_app_dirs_creates_temp(tmp_path, monkeypatch):
    """ensure_app_dirs should create the temp directory if missing."""
    fake_temp = str(tmp_path / "pyp6_temp")
    monkeypatch.setattr("pyp6.config.TEMP_DIR", fake_temp)
    monkeypatch.setattr("pyp6.constants.TEMP_DIR", fake_temp)
    ensure_app_dirs()
    assert os.path.isdir(fake_temp)

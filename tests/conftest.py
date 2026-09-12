"""Shared pytest fixtures for pyp6 tests."""

import subprocess
import sys

import pytest
from loguru import logger

# ---------------------------------------------------------------------------
# Pedalboard availability probe
#
# pedalboard ships a compiled C extension that requires AVX CPU instructions.
# On some CI runners (ubuntu-latest) importing it causes a fatal SIGILL that
# kills the entire Python process — no Python-level try/except can catch it.
#
# We probe importability once at session start by running a subprocess.  Tests
# that actually call into pedalboard (not just our wrapper's early-return paths)
# are decorated with @pytest.mark.requires_pedalboard; the hook below skips
# them automatically when the probe returns non-zero.
# ---------------------------------------------------------------------------


def _pedalboard_importable() -> bool:
    """Return True if pedalboard can be imported without crashing."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import pedalboard"],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


PEDALBOARD_AVAILABLE = _pedalboard_importable()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_pedalboard: skip when pedalboard cannot be imported (e.g. no AVX on CI)",
    )


def pytest_collection_modifyitems(config, items):
    if not PEDALBOARD_AVAILABLE:
        skip = pytest.mark.skip(reason="pedalboard not importable on this CPU (AVX required)")
        for item in items:
            if item.get_closest_marker("requires_pedalboard"):
                item.add_marker(skip)


@pytest.fixture
def log_records(capsys):
    """Capture loguru log records emitted during a test.

    Yields a list that is populated in real time as the test runs.
    Each element is a loguru record dict with keys: level, message, name, etc.

    Usage::

        def test_something(log_records):
            do_thing()
            assert any(r["level"].name == "WARNING" for r in log_records)
            assert any("expected text" in r["message"] for r in log_records)
    """
    records = []
    handler_id = logger.add(
        lambda msg: records.append(msg.record),
        level="DEBUG",
        format="{message}",
    )
    try:
        yield records
    finally:
        logger.remove(handler_id)

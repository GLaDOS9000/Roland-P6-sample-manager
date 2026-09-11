"""Shared pytest fixtures for pyp6 tests."""

import pytest
from loguru import logger


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

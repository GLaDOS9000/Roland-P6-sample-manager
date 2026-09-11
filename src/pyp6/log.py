"""Central logger for pyp6.

Import and use everywhere:
    from pyp6.log import logger
    logger.debug("…")
    logger.info("…")
    logger.warning("…")
    logger.error("…")

The sink (stderr) and level are configured once in __main__.py via
configure_logging(). Before that call the loguru default sink is active,
so early import-time messages are not lost.

A rotating file sink is always added alongside stderr so that DEBUG output
is persisted regardless of the active console level. The path is
platform-specific and exported as LOG_FILE for the About/Settings dialogs.
"""

import os
import sys

from loguru import logger

# Remove the default loguru sink so __main__.py can add its own
# with the user-chosen level and format.  This is a no-op if called
# before the first message is emitted.
logger.remove()

# Fallback sink at WARNING so anything logged before __main__.py calls
# configure_logging() (e.g. during a test run) is still visible.
logger.add(sys.stderr, level="WARNING", colorize=True)


def _log_file_path() -> str:
    home = os.path.expanduser("~")
    if sys.platform == "darwin":
        return os.path.join(home, "Library", "Logs", "pyp6", "pyp6.log")
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA", home)
        return os.path.join(appdata, "pyp6", "Logs", "pyp6.log")
    else:
        xdg = os.environ.get("XDG_STATE_HOME", os.path.join(home, ".local", "state"))
        return os.path.join(xdg, "pyp6", "pyp6.log")


LOG_FILE: str = _log_file_path()


def configure_logging(level: str = "INFO") -> None:
    """Replace the fallback sink with the configured one.

    Called once from __main__.main() after CLI args are parsed.
    Adds a rotating file sink (always at DEBUG) alongside the stderr sink.
    """
    logger.remove()
    fmt = (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
    )
    logger.add(sys.stderr, level=level.upper(), colorize=True, format=fmt)

    # File sink: always DEBUG, rotates at 5 MB, keeps 3 compressed archives.
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        file_fmt = "{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} — {message}"
        logger.add(
            LOG_FILE,
            level="DEBUG",
            format=file_fmt,
            rotation="5 MB",
            retention=3,
            compression="zip",
            encoding="utf-8",
        )
    except Exception as exc:
        logger.warning(f"Could not open log file {LOG_FILE!r}: {exc}")

    logger.debug(f"Log level set to {level.upper()}")

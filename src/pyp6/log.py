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
"""

import sys

from loguru import logger

# Remove the default loguru sink so __main__.py can add its own
# with the user-chosen level and format.  This is a no-op if called
# before the first message is emitted.
logger.remove()

# Fallback sink at WARNING so anything logged before __main__.py calls
# configure_logging() (e.g. during a test run) is still visible.
logger.add(sys.stderr, level="WARNING", colorize=True)


def configure_logging(level: str = "INFO") -> None:
    """Replace the fallback sink with the configured one.

    Called once from __main__.main() after CLI args are parsed.
    """
    logger.remove()
    fmt = (
        "<green>{time:HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — <level>{message}</level>"
    )
    logger.add(sys.stderr, level=level.upper(), colorize=True, format=fmt)
    logger.debug(f"Log level set to {level.upper()}")

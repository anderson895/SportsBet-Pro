"""File logging — para may maisusubmit na error report ang user.

Lahat ng logs (kasama ang full tracebacks ng errors at uncaught
exceptions) ay napupunta sa data/app.log (rotating, max 3 files x 1MB).
Kapag may nag-error sa ibang machine, ipadala lang ang app.log file.
"""
from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from src.core.paths import DATA_DIR

LOG_DIR = DATA_DIR
LOG_PATH = LOG_DIR / "app.log"

logger = logging.getLogger("sportsbet")


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        LOG_PATH, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Bawasan ang ingay — status checks kada 15s ay lulunod sa errors
    for noisy in ("httpx", "httpcore", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Uncaught exceptions sa main thread -> app.log na may full traceback
    def _excepthook(exc_type, exc, tb) -> None:
        logger.critical("UNCAUGHT EXCEPTION", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    logger.info("=== Application started | Python %s ===", sys.version)


def asyncio_exception_handler(loop, context: dict) -> None:
    """Unhandled exceptions sa asyncio tasks -> app.log."""
    exc = context.get("exception")
    if exc is not None:
        logger.error(
            "UNHANDLED ASYNC EXCEPTION: %s", context.get("message", ""),
            exc_info=exc,
        )
    else:
        logger.error("ASYNC ERROR: %s", context)

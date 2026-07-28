"""File logging — para may maisusubmit na error report ang user.

Lahat ng logs (kasama ang full tracebacks ng errors at uncaught
exceptions) ay napupunta sa data/app.log (rotating, max 3 files x 1MB).
Kapag may nag-error sa ibang machine, ipadala lang ang app.log file.
"""
from __future__ import annotations

import logging
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Optional

from src.core.paths import DATA_DIR

LOG_DIR = DATA_DIR
LOG_PATH = LOG_DIR / "app.log"

logger = logging.getLogger("sportsbet")


def err_text(exc: BaseException) -> str:
    """One-line description of an exception, never empty.

    httpx's timeout and connect errors often carry no message, so `f"{e}"`
    produced log lines that just stopped after the colon — half a DNS outage
    was unreadable. Fall back to the class name, and reach for the underlying
    cause when the wrapper itself is silent.
    """
    msg = str(exc).strip()
    name = type(exc).__name__
    if not msg:
        cause = exc.__cause__ or exc.__context__
        if cause is not None and str(cause).strip():
            return f"{name}: {str(cause).strip()}"
        return name
    return msg if name in msg else f"{name}: {msg}"


class Outage:
    """Collapses a run of failures into one log line and slows the retries.

    A 15-hour DNS outage previously wrote ~2,300 near-identical warnings at a
    fixed 30s cadence, burying everything else in the log. Report the start
    once, the recovery once, and widen the gap in between.
    """

    MAX_MULTIPLIER = 8

    def __init__(self) -> None:
        self.failures = 0
        self._since: Optional[float] = None

    def fail(self, reason: str) -> Optional[str]:
        """Record a failure; returns a message to log, or None to stay quiet."""
        self.failures += 1
        if self.failures == 1:
            self._since = time.time()
            return f"{reason} — backing off, will report when it recovers"
        return None

    def recover(self) -> Optional[str]:
        """Record a success; returns a recovery message if we were down."""
        if not self.failures:
            return None
        mins = (time.time() - (self._since or time.time())) / 60
        n = self.failures
        self.failures = 0
        self._since = None
        return f"Back online after {mins:.0f}min ({n} failed attempts)"

    def delay(self, base_secs: float) -> float:
        """Retry interval — `base_secs` normally, longer while failing."""
        if not self.failures:
            return base_secs
        return base_secs * min(2 ** self.failures, self.MAX_MULTIPLIER)


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
        # Ctrl+C / pagsara ng window = normal na paglabas, hindi crash —
        # huwag itong itala bilang CRITICAL para hindi nakakatakot ang log
        if issubclass(exc_type, KeyboardInterrupt):
            logger.info("Shutdown requested (Ctrl+C)")
            return
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

"""Application logging: rotating file plus optional console output."""

from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from services.config import log_dir

LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3
_configured = False


def setup_logging(level: str = "INFO", *, portable: bool = False,
                  console: bool | None = None) -> Path | None:
    """Configure the root logger and return the active log file path."""
    global _configured
    root = logging.getLogger()
    root.setLevel(getattr(logging, str(level).upper(), logging.INFO))
    if _configured:
        return getattr(root, "_kicad_log_path", None)

    formatter = logging.Formatter(LOG_FORMAT)

    if console is None:
        console = not getattr(sys, "frozen", False) and sys.stderr is not None
    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        root.addHandler(stream)

    destination: Path | None = None
    try:
        directory = log_dir(portable)
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / "app.log"
        file_handler = logging.handlers.RotatingFileHandler(
            destination, maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        destination = None

    # Keep third-party libraries quieter than the app by default.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
    root._kicad_log_path = destination  # type: ignore[attr-defined]
    _configured = True
    return destination


def reset_logging_for_tests() -> None:
    """Remove handlers added by :func:`setup_logging` (used by the tests)."""
    global _configured
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass
    _configured = False

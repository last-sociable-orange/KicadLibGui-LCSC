"""Small OS-integration helpers for the GUI."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def is_safe_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def open_url(url: str) -> bool:
    """Open an http(s) URL in the system browser; reject other schemes."""
    if not is_safe_url(url):
        logger.warning("Refusing to open non-http(s) URL: %r", url)
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception as exc:  # pragma: no cover - browser integration
        logger.warning("Could not open the browser: %s", exc)
        return False


def open_path(path: str | Path) -> bool:
    """Open a file or folder with the OS default handler."""
    target = Path(path)
    if not target.exists():
        logger.warning("Cannot open missing path: %s", target)
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":  # pragma: no cover
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
        return True
    except Exception as exc:  # pragma: no cover - desktop integration
        logger.warning("Could not open %s: %s", target, exc)
        return False


def reveal_folder(path: str | Path) -> bool:
    return open_path(Path(path))

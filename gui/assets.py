"""Bundled asset lookup (works in source runs and PyInstaller one-file)."""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path

_cache: dict[tuple[int, str, int], tk.PhotoImage] = {}


def asset_dir() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    if bundled:
        return Path(bundled) / "assets"
    return Path(__file__).resolve().parent.parent / "assets"


def asset_path(name: str) -> Path:
    return asset_dir() / name


def load_icon(name: str, master: tk.Misc | None = None, size: int = 16) -> tk.PhotoImage | None:
    """Load ``assets/icons/<name>-<size>.png`` if present."""
    key = (id(master), name, size)
    if key in _cache:
        return _cache[key]
    path = asset_path(f"icons/{name}-{size}.png")
    if not path.exists():
        return None
    try:
        image = tk.PhotoImage(master=master, file=str(path))
    except tk.TclError:  # pragma: no cover - broken asset
        return None
    _cache[key] = image
    return image


def load_app_icon(master: tk.Misc) -> tk.PhotoImage | None:
    path = asset_path("app.png")
    if not path.exists():
        return None
    try:
        return tk.PhotoImage(master=master, file=str(path))
    except tk.TclError:  # pragma: no cover
        return None

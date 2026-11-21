"""Tk theme: colours, fonts, DPI awareness and ttk styles.

Light theme only (v1).  The accent is KiCad-ish blue; cards are white on a
soft grey background.  Windows uses per-monitor DPI awareness when
available and the ``vista`` ttk theme; Linux falls back to ``clam``.
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

# -- palette ---------------------------------------------------------------

BG = "#f5f7fb"
CARD = "#ffffff"
BORDER = "#dee5ef"
BORDER_STRONG = "#c9d4e3"
TEXT = "#1f2937"
TEXT_SOFT = "#4b5563"
MUTED = "#6b7280"
FAINT = "#9aa5b4"
ACCENT = "#1668b3"
ACCENT_HOVER = "#125592"
ACCENT_SOFT = "#e8f1fb"
ACCENT_LINE = "#bcd6ef"
SUCCESS = "#15803d"
SUCCESS_BG = "#e7f6ec"
WARNING = "#b45309"
WARNING_BG = "#fdf3e2"
DANGER = "#b91c1c"
DANGER_BG = "#fdecec"
SELECTED = "#eef4fb"
HEADER_BG = "#f2f5fa"
PILL_BG = "#eef2f7"
WHITE = "#ffffff"

FONT_CANDIDATES = ("Segoe UI", "DejaVu Sans", "Noto Sans", "Liberation Sans", "Arial")
MONO_CANDIDATES = ("Consolas", "Cascadia Mono", "DejaVu Sans Mono", "Liberation Mono", "Courier New")


@dataclass
class Theme:
    family: str
    mono_family: str
    base: tuple
    small: tuple
    tiny: tuple
    heading: tuple
    title: tuple
    subtitle: tuple
    mono: tuple
    button: tuple


_CURRENT: Theme | None = None


def current() -> Theme:
    """Return the active theme (or safe defaults before :func:`apply`)."""
    if _CURRENT is not None:
        return _CURRENT
    return Theme(
        family="Segoe UI",
        mono_family="Consolas",
        base=("Segoe UI", 10),
        small=("Segoe UI", 9),
        tiny=("Segoe UI", 8),
        heading=("Segoe UI", 10, "bold"),
        title=("Segoe UI", 16, "bold"),
        subtitle=("Segoe UI", 10),
        mono=("Consolas", 9),
        button=("Segoe UI", 10, "bold"),
    )


def enable_dpi_awareness() -> None:
    """Opt into per-monitor DPI awareness before creating the Tk root."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        import ctypes

        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def _pick_family(root: tk.Misc, candidates: tuple[str, ...]) -> str:
    try:
        available = {name.lower(): name for name in tkfont.families(root)}
    except tk.TclError:  # pragma: no cover
        available = {}
    for candidate in candidates:
        if candidate.lower() in available:
            return available[candidate.lower()]
    return candidates[-1]


def apply(root: tk.Tk) -> Theme:
    """Install fonts/styles on *root* and return the :class:`Theme`."""
    global _CURRENT
    try:
        dpi = float(root.winfo_fpixels("1i"))
        if dpi > 0:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except (tk.TclError, ValueError):  # pragma: no cover
        pass

    family = _pick_family(root, FONT_CANDIDATES)
    mono = _pick_family(root, MONO_CANDIDATES)
    theme = Theme(
        family=family,
        mono_family=mono,
        base=(family, 10),
        small=(family, 9),
        tiny=(family, 8),
        heading=(family, 10, "bold"),
        title=(family, 16, "bold"),
        subtitle=(family, 10),
        mono=(mono, 9),
        button=(family, 10, "bold"),
    )

    for name, size in (("TkDefaultFont", 10), ("TkTextFont", 10), ("TkMenuFont", 10),
                       ("TkHeadingFont", 10), ("TkCaptionFont", 10),
                       ("TkSmallCaptionFont", 9), ("TkIconFont", 10),
                       ("TkTooltipFont", 9)):
        try:
            tkfont.nametofont(name).configure(family=family, size=size)
        except tk.TclError:
            pass

    style = ttk.Style(root)
    preferred = "vista" if sys.platform == "win32" else "clam"
    available = style.theme_names()
    style.theme_use(preferred if preferred in available else "clam")

    root.configure(background=BG)

    # Frames / labels -----------------------------------------------------
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("Toolbar.TFrame", background=BG)
    style.configure("Status.TFrame", background=CARD)

    style.configure("TLabel", background=BG, foreground=TEXT, font=theme.base)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=theme.base)
    style.configure("Muted.TLabel", background=CARD, foreground=MUTED, font=theme.small)
    style.configure("MutedBg.TLabel", background=BG, foreground=MUTED, font=theme.small)
    style.configure("Tiny.TLabel", background=CARD, foreground=FAINT, font=theme.tiny)
    style.configure("Section.TLabel", background=CARD, foreground=MUTED, font=theme.tiny)
    style.configure("Heading.TLabel", background=CARD, foreground=TEXT, font=theme.heading)
    style.configure("Title.TLabel", background=CARD, foreground=TEXT, font=theme.title)
    style.configure("Status.TLabel", background=CARD, foreground=MUTED, font=theme.small)

    # Entries / comboboxes ------------------------------------------------
    style.configure(
        "TEntry",
        fieldbackground=WHITE,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure(
        "TCombobox",
        fieldbackground=WHITE,
        background=WHITE,
        foreground=TEXT,
        arrowcolor=ACCENT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        padding=5,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", WHITE)],
        bordercolor=[("focus", ACCENT)],
        selectbackground=[("readonly", WHITE)],
        selectforeground=[("readonly", TEXT)],
    )
    style.configure("TSpinbox", fieldbackground=WHITE, foreground=TEXT, padding=5)
    style.configure(
        "Compact.TCombobox",
        fieldbackground=WHITE,
        background=WHITE,
        foreground=TEXT,
        arrowcolor=ACCENT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        padding=2,
        arrowsize=12,
    )
    style.map(
        "Compact.TCombobox",
        fieldbackground=[("readonly", WHITE)],
        bordercolor=[("focus", ACCENT)],
    )

    # Treeview ------------------------------------------------------------
    style.configure(
        "Treeview",
        background=CARD,
        fieldbackground=CARD,
        foreground=TEXT,
        rowheight=25,
        borderwidth=0,
        font=theme.base,
    )
    style.configure(
        "Treeview.Heading",
        background=HEADER_BG,
        foreground=MUTED,
        font=theme.tiny,
        relief="flat",
        padding=(8, 3),
        borderwidth=0,
    )
    style.map(
        "Treeview",
        background=[("selected", SELECTED)],
        foreground=[("selected", TEXT)],
    )
    style.map("Treeview.Heading", background=[("active", HEADER_BG)])
    style.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    # Notebook / scrollbars / progress -----------------------------------
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure(
        "TNotebook.Tab",
        background=BG,
        foreground=MUTED,
        padding=(14, 8),
        font=theme.heading,
    )
    style.map("TNotebook.Tab", background=[("selected", CARD)],
              foreground=[("selected", ACCENT)])
    style.configure("TScrollbar", background="#e5eaf2", troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED)
    style.configure(
        "Accent.Horizontal.TProgressbar",
        background=ACCENT,
        troughcolor="#e7edf5",
        bordercolor="#e7edf5",
        lightcolor=ACCENT,
        darkcolor=ACCENT,
        thickness=8,
    )
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=8, background=BG)
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=theme.base)
    style.map("TCheckbutton", background=[("active", CARD)])

    # Default ttk buttons (secondary style); primary actions use tk.Button.
    style.configure(
        "TButton",
        background=CARD,
        foreground=TEXT,
        bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG,
        padding=(12, 6),
        font=theme.base,
    )
    style.map(
        "TButton",
        background=[("active", "#f0f4fa"), ("disabled", CARD)],
        foreground=[("disabled", FAINT)],
    )

    _CURRENT = theme
    return theme

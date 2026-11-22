"""Tk theme: colours, named fonts, DPI awareness and ttk styles.

Light theme only.  The accent is a KiCad-ish blue; cards are white on a soft grey
background.

**Fonts are named Tk fonts**, not tuples: ``LCSC.Base``, ``LCSC.Small`` and
friends.  Widgets pass the *name* (``font="LCSC.Base"``), so changing the user's
interface font size is one ``font configure`` per role and every existing widget
re-flows on its own — no window rebuild, no lost selection.  The user picks the
base size in Settings; :func:`apply` and :func:`resize` derive the rest.
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import font as tkfont
from tkinter import ttk

from services.config import (
    DEFAULT_FONT_SIZE,
    FONT_SIZES,  # noqa: F401  (re-exported for the Settings dialog)
    MAX_FONT_SIZE,
    MIN_FONT_SIZE,
)

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

#: Named-font roles.  ``size`` is relative to the user's base size.
_ROLE_OFFSETS: dict[str, tuple[int, str]] = {
    "base": (0, "normal"),
    "small": (-1, "normal"),
    "tiny": (-2, "normal"),
    "mono": (-1, "normal"),
    "entry": (0, "normal"),
    "heading": (0, "bold"),
    "button": (0, "bold"),
    "section": (-2, "bold"),
    "card_title": (2, "bold"),
    "panel_title": (3, "bold"),
    "title": (5, "bold"),
}
_MONO_ROLES = frozenset({"mono"})


def _font_name(role: str) -> str:
    """``card_title`` -> ``LCSC.CardTitle``."""
    return "LCSC." + "".join(part[:1].upper() + part[1:] for part in role.split("_"))


@dataclass
class Theme:
    """The active theme.

    Every font field holds a *named font* (``"LCSC.Base"``) so the size can change
    at runtime; ``family``/``mono_family`` keep the resolved face names for the
    few places that need to build a font on the fly.
    """

    family: str
    mono_family: str
    base: str
    small: str
    tiny: str
    mono: str
    entry: str
    heading: str
    button: str
    section: str
    card_title: str
    panel_title: str
    title: str
    font_size: int


_CURRENT: Theme | None = None


def _role_sizes(font_size: int) -> dict[str, tuple[int, str]]:
    base = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, int(font_size)))
    return {
        role: (max(MIN_FONT_SIZE, base + offset), weight)
        for role, (offset, weight) in _ROLE_OFFSETS.items()
    }


def _fallback_theme() -> Theme:
    """Safe defaults for the window before :func:`apply` runs."""
    return Theme(
        family="Segoe UI",
        mono_family="Consolas",
        base="TkDefaultFont",
        small="TkSmallCaptionFont",
        tiny="TkTooltipFont",
        mono="TkFixedFont",
        entry="TkTextFont",
        heading="TkHeadingFont",
        button="TkDefaultFont",
        section="TkSmallCaptionFont",
        card_title="TkHeadingFont",
        panel_title="TkHeadingFont",
        title="TkCaptionFont",
        font_size=DEFAULT_FONT_SIZE,
    )


def current() -> Theme:
    """Return the active theme (or safe defaults before :func:`apply`)."""
    return _CURRENT if _CURRENT is not None else _fallback_theme()


def font_size() -> int:
    return current().font_size


def scale() -> float:
    """How much bigger or smaller the current font size is than the default.

    Pixel geometry (tree row heights, column widths, dialog padding) is
    multiplied by this so the layout keeps pace with the text.
    """
    return font_size() / DEFAULT_FONT_SIZE


# -- fonts -----------------------------------------------------------------

#: Named fonts must outlive the call that creates them: tkinter's ``Font`` object
#: deletes its named font from Tk when it is garbage collected, so every created
#: font is kept here, keyed by interpreter and name.
_FONTS: dict[tuple[int, str], tkfont.Font] = {}


def _install_fonts(root: tk.Misc, family: str, mono_family: str, font_size: int) -> dict[str, str]:
    """Create or reconfigure the named fonts and return role -> font name."""
    names: dict[str, str] = {}
    for role, (size, weight) in _role_sizes(font_size).items():
        name = _font_name(role)
        face = mono_family if role in _MONO_ROLES else family
        key = (id(root), name)
        font = _FONTS.get(key)
        try:
            if font is None:
                raise tk.TclError("not created yet")
            font.configure(family=face, size=size, weight=weight)
        except tk.TclError:
            font = tkfont.Font(root=root, name=name, exists=False, family=face,
                               size=size, weight=weight)
            _FONTS[key] = font
        names[role] = name
    return names


def _configure_named_defaults(root: tk.Misc, family: str, font_size: int) -> None:
    """Keep the stock Tk fonts in step, so unstyled widgets scale too."""
    small = max(MIN_FONT_SIZE, font_size - 1)
    tiny = max(MIN_FONT_SIZE, font_size - 2)
    for name, size in (
        ("TkDefaultFont", font_size),
        ("TkTextFont", font_size),
        ("TkMenuFont", font_size),
        ("TkHeadingFont", font_size),
        ("TkCaptionFont", font_size + 3),
        ("TkSmallCaptionFont", small),
        ("TkIconFont", font_size),
        ("TkTooltipFont", tiny),
    ):
        try:
            tkfont.nametofont(name, root=root).configure(family=family, size=size)
        except tk.TclError:  # pragma: no cover - unusual Tk builds
            pass


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


def _row_height(font_size: int) -> int:
    return round(font_size * 2.6)


def _configure_styles(root: tk.Misc, theme: Theme) -> None:
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
    style.configure("Section.TLabel", background=CARD, foreground=MUTED, font=theme.section)
    style.configure("Heading.TLabel", background=CARD, foreground=TEXT, font=theme.heading)
    style.configure("Title.TLabel", background=CARD, foreground=TEXT, font=theme.title)
    style.configure("Status.TLabel", background=CARD, foreground=MUTED, font=theme.small)

    # Entries / comboboxes ------------------------------------------------
    style.configure(
        "TEntry", fieldbackground=WHITE, foreground=TEXT, bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG, darkcolor=BORDER_STRONG, padding=6,
    )
    style.map("TEntry", bordercolor=[("focus", ACCENT)])
    style.configure(
        "TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT,
        arrowcolor=ACCENT, bordercolor=BORDER_STRONG, lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG, padding=5,
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
        "Compact.TCombobox", fieldbackground=WHITE, background=WHITE, foreground=TEXT,
        arrowcolor=ACCENT, bordercolor=BORDER_STRONG, lightcolor=BORDER_STRONG,
        darkcolor=BORDER_STRONG, padding=2, arrowsize=12,
    )
    style.map(
        "Compact.TCombobox",
        fieldbackground=[("readonly", WHITE)],
        bordercolor=[("focus", ACCENT)],
    )

    # Treeview ------------------------------------------------------------
    style.configure(
        "Treeview", background=CARD, fieldbackground=CARD, foreground=TEXT,
        rowheight=_row_height(theme.font_size), borderwidth=0, font=theme.base,
    )
    style.configure(
        "Treeview.Heading", background=HEADER_BG, foreground=MUTED, font=theme.tiny,
        relief="flat", padding=(8, 3), borderwidth=0,
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
    style.configure("TNotebook.Tab", background=BG, foreground=MUTED, padding=(14, 8),
                    font=theme.heading)
    style.map("TNotebook.Tab", background=[("selected", CARD)],
              foreground=[("selected", ACCENT)])
    style.configure("TScrollbar", background="#e5eaf2", troughcolor=BG, bordercolor=BG,
                    arrowcolor=MUTED)
    style.configure(
        "Accent.Horizontal.TProgressbar", background=ACCENT, troughcolor="#e7edf5",
        bordercolor="#e7edf5", lightcolor=ACCENT, darkcolor=ACCENT, thickness=8,
    )
    style.configure("TPanedwindow", background=BG)
    style.configure("Sash", sashthickness=8, background=BG)
    style.configure("TCheckbutton", background=CARD, foreground=TEXT, font=theme.base)
    style.map("TCheckbutton", background=[("active", CARD)])

    # Default ttk buttons (secondary style); primary actions use tk.Button.
    style.configure(
        "TButton", background=CARD, foreground=TEXT, bordercolor=BORDER_STRONG,
        lightcolor=BORDER_STRONG, darkcolor=BORDER_STRONG, padding=(12, 6),
        font=theme.base,
    )
    style.map(
        "TButton",
        background=[("active", "#f0f4fa"), ("disabled", CARD)],
        foreground=[("disabled", FAINT)],
    )


def apply(root: tk.Tk, *, font_size: int | None = None) -> Theme:
    """Install fonts/styles on *root* and return the :class:`Theme`."""
    global _CURRENT

    try:
        dpi = float(root.winfo_fpixels("1i"))
        if dpi > 0:
            root.tk.call("tk", "scaling", dpi / 72.0)
    except (tk.TclError, ValueError):  # pragma: no cover
        pass

    size = DEFAULT_FONT_SIZE if font_size is None else int(font_size)
    size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, size))
    family = _pick_family(root, FONT_CANDIDATES)
    mono = _pick_family(root, MONO_CANDIDATES)

    names = _install_fonts(root, family, mono, size)
    _configure_named_defaults(root, family, size)

    theme = Theme(family=family, mono_family=mono, font_size=size, **names)
    _configure_styles(root, theme)
    _CURRENT = theme
    return theme


def resize(root: tk.Tk, font_size: int) -> Theme:
    """Change the interface font size in place and restyle the ttk widgets."""
    global _CURRENT

    size = max(MIN_FONT_SIZE, min(MAX_FONT_SIZE, font_size))
    family = _CURRENT.family if _CURRENT is not None else _pick_family(root, FONT_CANDIDATES)
    mono = _CURRENT.mono_family if _CURRENT is not None else _pick_family(root, MONO_CANDIDATES)

    names = _install_fonts(root, family, mono, size)
    _configure_named_defaults(root, family, size)

    theme = Theme(family=family, mono_family=mono, font_size=size, **names)
    _configure_styles(root, theme)
    _CURRENT = theme
    root.event_generate("<<ThemeFontSize>>")
    return theme

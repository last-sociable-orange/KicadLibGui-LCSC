"""Small Tk building blocks shared by the window and dialogs."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from gui import assets, theme


def card(parent: tk.Misc, **kwargs) -> tk.Frame:
    options = {
        "bg": theme.CARD,
        "highlightbackground": theme.BORDER,
        "highlightthickness": 1,
        "bd": 0,
    }
    options.update(kwargs)
    return tk.Frame(parent, **options)


def separator(parent: tk.Misc, *, bg: str = theme.BORDER, padx: int = 0,
              pady: int = 0) -> tk.Frame:
    frame = tk.Frame(parent, bg=bg, height=1, bd=0, highlightthickness=0)
    frame.pack(fill="x", padx=padx, pady=pady)
    return frame


def label(parent: tk.Misc, text: str = "", *, bg: str = theme.CARD,
          fg: str = theme.TEXT, font: tuple | None = None, **kwargs) -> tk.Label:
    return tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=font or theme.current().base,
        bd=0,
        highlightthickness=0,
        anchor="w",
        justify="left",
        **kwargs,
    )


def primary_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    icon: str | None = None,
    font: tuple | None = None,
    padx: int = 18,
    pady: int = 7,
) -> tk.Button:
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=theme.ACCENT,
        fg=theme.WHITE,
        activebackground=theme.ACCENT_HOVER,
        activeforeground=theme.WHITE,
        disabledforeground="#c7d7e8",
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=padx,
        pady=pady,
        cursor="hand2",
        font=font or theme.current().button,
    )
    if icon:
        image = assets.load_icon(icon, parent)
        if image is not None:
            button.configure(image=image, compound="left", padx=max(10, padx - 6))
            button.image = image  # type: ignore[attr-defined]

    def on_enter(_event=None):
        if str(button.cget("state")) != "disabled":
            button.configure(bg=theme.ACCENT_HOVER)

    def on_leave(_event=None):
        if str(button.cget("state")) != "disabled":
            button.configure(bg=theme.ACCENT)

    button.bind("<Enter>", on_enter)
    button.bind("<Leave>", on_leave)
    return button


def secondary_button(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    icon: str | None = None,
    bg: str = theme.CARD,
    font: tuple | None = None,
    padx: int = 14,
    pady: int = 6,
) -> tk.Button:
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=theme.TEXT,
        activebackground="#f0f4fa",
        activeforeground=theme.TEXT,
        disabledforeground=theme.FAINT,
        relief="flat",
        bd=0,
        highlightbackground=theme.BORDER_STRONG,
        highlightthickness=1,
        padx=padx,
        pady=pady,
        cursor="hand2",
        font=font or theme.current().base,
    )
    if icon:
        image = assets.load_icon(icon, parent)
        if image is not None:
            button.configure(image=image, compound="left", padx=max(8, padx - 4))
            button.image = image  # type: ignore[attr-defined]
    return button


def icon_button(
    parent: tk.Misc,
    icon: str,
    command: Callable[[], None],
    *,
    bg: str = theme.BG,
    tooltip: str = "",
) -> tk.Button:
    button = tk.Button(
        parent,
        command=command,
        bg=bg,
        activebackground="#eaf0f7",
        relief="flat",
        bd=0,
        highlightthickness=0,
        padx=6,
        pady=4,
        cursor="hand2",
    )
    image = assets.load_icon(icon, parent)
    if image is not None:
        button.configure(image=image)
        button.image = image  # type: ignore[attr-defined]
    else:
        button.configure(text="⚙", fg=theme.MUTED)
    if tooltip:
        _attach_tooltip(button, tooltip)
    return button


def link_label(
    parent: tk.Misc,
    text: str,
    command: Callable[[], None],
    *,
    bg: str = theme.CARD,
    fg: str = theme.ACCENT,
    font: tuple | None = None,
) -> tk.Label:
    widget = tk.Label(
        parent,
        text=text,
        bg=bg,
        fg=fg,
        font=font or theme.current().small,
        cursor="hand2",
        bd=0,
        highlightthickness=0,
    )
    widget.bind("<Button-1>", lambda _event: command())
    widget.bind("<Enter>", lambda _event: widget.configure(fg=theme.ACCENT_HOVER))
    widget.bind("<Leave>", lambda _event: widget.configure(fg=fg))
    return widget


def set_enabled(widget: tk.Widget, enabled: bool, *, bg: str | None = None) -> None:
    try:
        widget.configure(state="normal" if enabled else "disabled")
        if bg is not None and isinstance(widget, tk.Button):
            widget.configure(bg=bg if enabled else "#c7d7e8")
    except tk.TclError:
        pass


class Pill(tk.Label):
    """A compact coloured count/badge label."""

    def __init__(
        self,
        parent: tk.Misc,
        text: str = "",
        *,
        fg: str = theme.TEXT_SOFT,
        bg: str = theme.PILL_BG,
        font: tuple | None = None,
    ):
        super().__init__(
            parent,
            text=text,
            bg=bg,
            fg=fg,
            font=font or theme.current().tiny,
            padx=8,
            pady=2,
            bd=0,
            highlightthickness=0,
        )

    def set(self, text: str, *, fg: str | None = None, bg: str | None = None) -> None:
        self.configure(text=text)
        if fg:
            self.configure(fg=fg)
        if bg:
            self.configure(bg=bg)


class Tooltip:
    """A minimal hover tooltip (used by icon buttons)."""

    def __init__(self, widget: tk.Widget, text: str, delay: int = 500):
        self.widget = widget
        self.text = text
        self.delay = delay
        self._after: str | None = None
        self._window: tk.Toplevel | None = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._after = self.widget.after(self.delay, self._show)

    def _show(self):
        if self._window is not None:
            return
        x = self.widget.winfo_rootx() + 8
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        window = tk.Toplevel(self.widget)
        window.wm_overrideredirect(True)
        window.attributes("-topmost", True)
        frame = tk.Frame(window, bg="#1f2937", padx=8, pady=4)
        frame.pack()
        tk.Label(frame, text=self.text, bg="#1f2937", fg="white",
                 font=("Segoe UI", 9)).pack()
        window.wm_geometry(f"+{x}+{y}")
        self._window = window

    def _hide(self, _event=None):
        if self._after:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None
        if self._window is not None:
            self._window.destroy()
            self._window = None


def _attach_tooltip(widget: tk.Widget, text: str) -> None:
    Tooltip(widget, text)

"""Inline, non-modal error/info banner with a Details view."""

from __future__ import annotations

import logging
import tkinter as tk
from tkinter import ttk

from gui import theme
from gui.widgets import link_label

logger = logging.getLogger(__name__)

_KIND_COLOURS = {
    "error": (theme.DANGER_BG, theme.DANGER, "✕"),
    "warning": (theme.WARNING_BG, theme.WARNING, "⚠"),
    "info": (theme.ACCENT_SOFT, theme.ACCENT, "ℹ"),
    "success": (theme.SUCCESS_BG, theme.SUCCESS, "✓"),
}


class Banner(tk.Frame):
    def __init__(self, parent: tk.Misc, *, before: tk.Misc | None = None):
        super().__init__(parent, bg=theme.DANGER_BG, bd=0, highlightthickness=0)
        self._before = before
        self._details = ""
        self._message_text = ""

        self.icon = tk.Label(self, text="✕", bg=theme.DANGER_BG, fg=theme.DANGER,
                             font=(theme.current().family, 10, "bold"))
        self.icon.pack(side="left", padx=(10, 6), pady=7)

        self.message = tk.Label(
            self, text="", bg=theme.DANGER_BG, fg=theme.DANGER,
            font=theme.current().small, anchor="w", justify="left", wraplength=760,
        )
        self.message.pack(side="left", fill="x", expand=True, pady=7)

        self.details_link = link_label(
            self, "Details", self._show_details, bg=theme.DANGER_BG,
            fg=theme.DANGER, font=theme.current().small,
        )
        self.details_link.pack(side="left", padx=(8, 4))

        self.close_button = tk.Label(
            self, text="✕", bg=theme.DANGER_BG, fg=theme.DANGER,
            font=theme.current().small, cursor="hand2", padx=8,
        )
        self.close_button.pack(side="right", padx=(0, 4))
        self.close_button.bind("<Button-1>", lambda _event: self.hide())

        self.bind("<Configure>", self._on_resize)
        self._visible = False

    # -- API -------------------------------------------------------------

    def show(self, message: str, details: str = "", kind: str = "error") -> None:
        background, foreground, icon = _KIND_COLOURS.get(kind, _KIND_COLOURS["error"])
        self.configure(bg=background)
        self.icon.configure(text=icon, bg=background, fg=foreground)
        self.message.configure(text=message, bg=background, fg=foreground)
        self.close_button.configure(bg=background, fg=foreground)
        self.details_link.configure(bg=background, fg=foreground)
        self.details_link._link_fg = foreground  # type: ignore[attr-defined]
        self._details = details or ""
        self._message_text = message
        if self._details:
            self.details_link.pack(side="left", padx=(8, 4))
        else:
            self.details_link.pack_forget()
        if not self._visible:
            options = {"fill": "x", "padx": 14, "pady": (0, 8)}
            if self._before is not None:
                options["before"] = self._before
            self.pack(**options)
            self._visible = True
        logger.info("Banner (%s): %s", kind, message)

    def hide(self) -> None:
        if self._visible:
            self.pack_forget()
            self._visible = False

    @property
    def visible(self) -> bool:
        return self._visible

    # -- internals -------------------------------------------------------

    def _on_resize(self, event) -> None:
        width = max(320, event.width - 220)
        self.message.configure(wraplength=width)

    def _show_details(self) -> None:
        if not self._details:
            return
        window = tk.Toplevel(self)
        window.title("Error details")
        window.configure(bg=theme.BG)
        window.transient(self.winfo_toplevel())
        window.geometry("720x360")
        window.minsize(480, 240)

        frame = ttk.Frame(window, padding=12)
        frame.pack(fill="both", expand=True)
        text = tk.Text(
            frame, wrap="word", font=theme.current().mono, bg=theme.CARD,
            fg=theme.TEXT, relief="flat", highlightthickness=1,
            highlightbackground=theme.BORDER, padx=10, pady=10,
        )
        scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", self._details)
        text.configure(state="disabled")

        buttons = ttk.Frame(window, padding=(12, 0, 12, 12))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Close", command=window.destroy).pack(side="right")
        window.bind("<Escape>", lambda _event: window.destroy())

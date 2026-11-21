"""About dialog: what this program is, and what it is not."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import version
from gui import theme
from lcsc_core.texts import t


class AboutDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, *, site: str = "", database: str = ""):
        super().__init__(parent)
        self.title(t("about.title"))
        self.configure(bg=theme.CARD)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.bind("<Escape>", lambda _event: self.destroy())

        outer = tk.Frame(self, bg=theme.CARD, padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text=version.APP_NAME, bg=theme.CARD, fg=theme.TEXT,
                 font=(theme.current().family, 16, "bold")).pack(anchor="w")
        tk.Label(outer, text=t("about.version", version=version.__version__), bg=theme.CARD,
                 fg=theme.MUTED, font=theme.current().small).pack(anchor="w", pady=(2, 12))

        tk.Label(outer, text=t("about.what"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().base, wraplength=420, justify="left").pack(anchor="w")

        details = [
            ("Storefront", site or "-"),
            (t("settings.database"), database or "-"),
            ("Schema", "KiCad components (80 columns)"),
            ("Licence", "MIT"),
        ]
        grid = tk.Frame(outer, bg=theme.CARD)
        grid.pack(fill="x", pady=(14, 0))
        for row, (label, value) in enumerate(details):
            tk.Label(grid, text=label, bg=theme.CARD, fg=theme.MUTED,
                     font=theme.current().tiny, width=12, anchor="w").grid(
                row=row, column=0, sticky="w")
            tk.Label(grid, text=value, bg=theme.CARD, fg=theme.TEXT,
                     font=theme.current().small, anchor="w", wraplength=330,
                     justify="left").grid(row=row, column=1, sticky="w")

        tk.Label(outer, text=t("about.prices"), bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny, wraplength=420,
                 justify="left").pack(anchor="w", pady=(14, 0))
        tk.Label(outer, text=t("app.unofficial"), bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny, wraplength=420,
                 justify="left").pack(anchor="w", pady=(4, 0))

        buttons = tk.Frame(outer, bg=theme.CARD)
        buttons.pack(fill="x", pady=(18, 0))
        ttk.Button(buttons, text=t("common.close"), command=self.destroy).pack(side="right")

        self.focus_set()

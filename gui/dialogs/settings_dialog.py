"""Settings dialog: paths, storefront language, pacing, cache and logging."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui import theme, utils
from gui.widgets import primary_button, secondary_button
from lcsc_core.routing import LANGUAGES
from lcsc_core.texts import t
from services import config

logger = logging.getLogger(__name__)

_CACHE_LABELS = {
    0: "settings.cache_off",
    3600: "settings.cache_hour",
    21600: "settings.cache_6h",
    86400: "settings.cache_day",
    604800: "settings.cache_week",
}


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app, *, on_language_change=None):
        super().__init__(parent)
        self.app = app
        self._on_language_change = on_language_change
        self._original_language = app.settings.language
        self.title(t("settings.title"))
        self.configure(bg=theme.CARD)
        self.transient(parent.winfo_toplevel())
        self.geometry("720x600")
        self.minsize(640, 560)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        self._build()
        self._load()
        try:
            self.grab_set()
        except tk.TclError:  # pragma: no cover
            pass

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        outer = tk.Frame(self, bg=theme.CARD, padx=24, pady=20)
        outer.pack(fill="both", expand=True)

        tk.Label(outer, text=t("settings.title"), bg=theme.CARD, fg=theme.TEXT,
                 font=(theme.current().family, 15, "bold")).pack(anchor="w")
        tk.Label(outer, text=t("settings.config_folder",
                               path=self.app.settings.config_folder),
                 bg=theme.CARD, fg=theme.MUTED, font=theme.current().small,
                 wraplength=620, justify="left", anchor="w").pack(anchor="w", pady=(3, 14))

        # Database --------------------------------------------------------
        tk.Label(outer, text=t("settings.database"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        db_row = tk.Frame(outer, bg=theme.CARD)
        db_row.pack(fill="x", pady=(3, 4))
        self.db_var = tk.StringVar()
        self.db_entry = ttk.Entry(db_row, textvariable=self.db_var, font=theme.current().base)
        self.db_entry.pack(side="left", fill="x", expand=True)
        secondary_button(db_row, t("common.browse"), self._browse_db).pack(side="left", padx=(8, 0))
        self.db_hint = tk.Label(outer, text="", bg=theme.CARD, fg=theme.WARNING,
                                font=theme.current().tiny, anchor="w",
                                wraplength=620, justify="left")
        self.db_hint.pack(fill="x")

        # Language --------------------------------------------------------
        tk.Label(outer, text=t("settings.language"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w", pady=(14, 0))
        self.language_var = tk.StringVar()
        self.language_combo = ttk.Combobox(
            outer, textvariable=self.language_var, state="readonly",
            values=[label for _code, label in LANGUAGES], width=26,
            font=theme.current().base)
        self.language_combo.pack(anchor="w", pady=(3, 2))
        tk.Label(outer, text=t("settings.language_note"), bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny, wraplength=620, justify="left",
                 anchor="w").pack(anchor="w")

        # Numbers ---------------------------------------------------------
        limits = tk.Frame(outer, bg=theme.CARD)
        limits.pack(fill="x", pady=(14, 0))
        limits.grid_columnconfigure(0, weight=1)
        limits.grid_columnconfigure(1, weight=1)

        left = tk.Frame(limits, bg=theme.CARD)
        left.grid(row=0, column=0, sticky="nw", padx=(0, 18))
        tk.Label(left, text=t("settings.page_size"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.page_size_var = tk.StringVar()
        self.page_size_combo = ttk.Combobox(
            left, textvariable=self.page_size_var, state="readonly", width=8,
            values=[str(value) for value in config.PAGE_SIZES],
            font=theme.current().base)
        self.page_size_combo.pack(anchor="w", pady=(3, 12))

        tk.Label(left, text=t("settings.timeout"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.timeout_var = tk.StringVar()
        self.timeout_spin = tk.Spinbox(
            left, from_=5, to=120, increment=5, width=8, textvariable=self.timeout_var,
            font=theme.current().small, relief="flat", bg=theme.WHITE,
            highlightbackground=theme.BORDER_STRONG, highlightthickness=1)
        self.timeout_spin.pack(anchor="w", pady=(3, 12))

        tk.Label(left, text=t("settings.log_level"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.log_var = tk.StringVar()
        self.log_combo = ttk.Combobox(left, textvariable=self.log_var, state="readonly",
                                      values=list(config.LOG_LEVELS), width=10,
                                      font=theme.current().base)
        self.log_combo.pack(anchor="w", pady=(3, 0))

        right = tk.Frame(limits, bg=theme.CARD)
        right.grid(row=0, column=1, sticky="nw")
        tk.Label(right, text=t("settings.interval"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.interval_var = tk.StringVar()
        self.interval_spin = tk.Spinbox(
            right, from_=0, to=5000, increment=50, width=8, textvariable=self.interval_var,
            font=theme.current().small, relief="flat", bg=theme.WHITE,
            highlightbackground=theme.BORDER_STRONG, highlightthickness=1)
        self.interval_spin.pack(anchor="w", pady=(3, 12))

        tk.Label(right, text=t("settings.batch_delay"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.delay_var = tk.StringVar()
        self.delay_spin = tk.Spinbox(
            right, from_=0, to=10000, increment=50, width=8, textvariable=self.delay_var,
            font=theme.current().small, relief="flat", bg=theme.WHITE,
            highlightbackground=theme.BORDER_STRONG, highlightthickness=1)
        self.delay_spin.pack(anchor="w", pady=(3, 12))

        tk.Label(right, text=t("settings.cache"), bg=theme.CARD, fg=theme.TEXT_SOFT,
                 font=theme.current().small).pack(anchor="w")
        self.cache_var = tk.StringVar()
        self.cache_combo = ttk.Combobox(
            right, textvariable=self.cache_var, state="readonly",
            values=[t(key) for key in _CACHE_LABELS.values()], width=14,
            font=theme.current().base)
        self.cache_combo.pack(anchor="w", pady=(3, 0))

        tk.Label(outer, text=t("settings.politeness"), bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny, wraplength=620, justify="left",
                 anchor="w").pack(anchor="w", pady=(12, 0))

        # Maintenance -----------------------------------------------------
        maintenance = tk.Frame(outer, bg=theme.CARD)
        maintenance.pack(fill="x", pady=(14, 0))
        self.reveal_button = secondary_button(maintenance, t("settings.reveal"),
                                              self._reveal_config)
        self.reveal_button.pack(side="left")
        self.clear_cache_button = secondary_button(maintenance, t("settings.clear_cache"),
                                                   self._clear_cache)
        self.clear_cache_button.pack(side="left", padx=(8, 0))

        buttons = tk.Frame(outer, bg=theme.CARD)
        buttons.pack(fill="x", side="bottom", pady=(18, 0))
        self.cancel_button = secondary_button(buttons, t("common.cancel"), self._close)
        self.cancel_button.pack(side="right")
        self.save_button = primary_button(buttons, t("common.save"), self._save, padx=24)
        self.save_button.pack(side="right", padx=(0, 8))

    # -- data ------------------------------------------------------------

    def _load(self) -> None:
        settings = self.app.settings
        self.db_var.set(settings.database_path)
        self.language_var.set(dict(LANGUAGES).get(settings.language, ""))
        self.page_size_var.set(str(settings.page_size))
        self.timeout_var.set(str(settings.http_timeout))
        self.interval_var.set(str(settings.request_interval_ms))
        self.delay_var.set(str(settings.batch_delay_ms))
        self.cache_var.set(t(_CACHE_LABELS.get(settings.cache_ttl, "settings.cache_6h")))
        self.log_var.set(settings.log_level)
        self._update_hints()
        self.db_var.trace_add("write", lambda *_args: self._update_hints())

    def _update_hints(self) -> None:
        path = self.db_var.get()
        sync = config.sync_folder_name(path) if path else None
        self.db_hint.configure(text=(
            f"⚠ This path is inside {sync}. Sync clients can lock or corrupt SQLite "
            "files; a local folder such as ~/KiCadLibGenLCSC is safer." if sync else ""))

    def _browse_db(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title="Choose a components database",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")])
        if path:
            self.db_var.set(path)

    # -- actions ---------------------------------------------------------

    def _reveal_config(self) -> None:
        utils.reveal_folder(self.app.settings.config_folder)

    def _clear_cache(self) -> None:
        removed = self.app.search_service.clear_cache()
        # Older entries written by another run may not be reachable through the
        # live cache object, so sweep the folder as well.
        directory = config.cache_dir(self.app.settings.portable)
        if directory.exists():
            for item in directory.glob("*.json"):
                try:
                    item.unlink()
                    removed += 1
                except OSError:
                    pass
        logger.info("Cleared %s cached responses", removed)
        self.app.toast(t("settings.cache_cleared"))

    def _save(self) -> None:
        try:
            timeout = max(5, min(120, int(float(self.timeout_var.get()))))
            interval = max(0, min(5000, int(float(self.interval_var.get()))))
            delay = max(0, min(10000, int(float(self.delay_var.get()))))
            page_size = int(self.page_size_var.get())
        except (TypeError, ValueError):
            messagebox.showerror(t("settings.title"), t("settings.invalid"), parent=self)
            return
        database = self.db_var.get().strip()
        if not database:
            messagebox.showerror(t("settings.title"), t("settings.invalid"), parent=self)
            return

        settings = self.app.settings
        settings.database_path = database
        settings.page_size = page_size
        settings.http_timeout = timeout
        settings.request_interval_ms = interval
        settings.batch_delay_ms = delay
        settings.log_level = self.log_var.get()
        language_label = self.language_var.get()
        settings.language = next((code for code, label in LANGUAGES if label == language_label),
                                 settings.language)
        ttl = next((value for value, key in _CACHE_LABELS.items()
                    if t(key) == self.cache_var.get()), settings.cache_ttl)
        settings.cache_ttl = ttl

        try:
            settings.save()
        except OSError as exc:
            messagebox.showerror(t("settings.title"), str(exc), parent=self)
            return

        previous = self._original_language
        self.app.apply_settings(previous_language=previous)
        if self._on_language_change is not None:
            self._on_language_change()
        Path(settings.database_path).expanduser()
        self._close()

    def _close(self) -> None:
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

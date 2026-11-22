"""Database tab: browse/filter records, edit the KiCad mapping, delete, duplicates."""

from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from gui import theme
from gui.widgets import Pill, link_label, primary_button, secondary_button
from kicad_core.errors import AppError
from kicad_core.models import ProductInfo
from lcsc_core.texts import t, tn
from services.database_service import RecordSummary

logger = logging.getLogger(__name__)

_COLUMNS = (
    ("part", 92, "w", False),
    ("mpn", 180, "w", False),
    ("manufacturer", 130, "w", False),
    ("description", 260, "w", True),
    ("symbol", 190, "w", False),
    ("footprint", 190, "w", False),
    ("status", 90, "w", False),
)


class DatabaseTab(tk.Frame):
    def __init__(self, parent: tk.Misc, app, *, on_open_db: Callable[[], None],
                 on_new_db: Callable[[], None],
                 on_show_params: Callable[[ProductInfo], None] | None = None):
        super().__init__(parent, bg=theme.BG)
        self.app = app
        self._on_open_db = on_open_db
        self._on_new_db = on_new_db
        self._on_show_params = on_show_params
        self.records: list[RecordSummary] = []
        self.current: RecordSummary | None = None
        self.current_product: ProductInfo | None = None
        self._duplicates: list[tuple[str, int]] = []

        self._build()
        self.show_empty_state(t("db.empty"))

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = tk.Frame(self, bg=theme.CARD, padx=16, pady=12,
                          highlightbackground=theme.BORDER, highlightthickness=1)
        header.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))

        title_row = tk.Frame(header, bg=theme.CARD)
        title_row.pack(fill="x")
        self.title_label = tk.Label(title_row, text=t("db.title"), bg=theme.CARD,
                                    fg=theme.TEXT, font=theme.current().card_title)
        self.title_label.pack(side="left")
        self.count_pill = Pill(title_row, tn("db.count", 0), fg=theme.TEXT_SOFT)
        self.count_pill.pack(side="left", padx=(10, 0))
        self.duplicate_link = link_label(title_row, "", self._show_duplicates, fg=theme.WARNING)
        self.duplicate_link.pack(side="left", padx=(10, 0))
        self.duplicate_link.pack_forget()

        filter_row = tk.Frame(header, bg=theme.CARD)
        filter_row.pack(fill="x", pady=(10, 0))
        self.filter_var = tk.StringVar()
        self.filter_entry = ttk.Entry(filter_row, textvariable=self.filter_var,
                                      font=theme.current().base)
        self.filter_entry.pack(side="left", fill="x", expand=True)
        self.filter_entry.bind("<Return>", lambda _event: self.refresh())
        self.search_button = secondary_button(filter_row, t("common.search"), self.refresh,
                                              icon="search")
        self.search_button.pack(side="left", padx=(8, 0))
        self.refresh_button = secondary_button(filter_row, t("common.refresh"), self.refresh,
                                               icon="refresh")
        self.refresh_button.pack(side="left", padx=(8, 0))

        table_card = tk.Frame(self, bg=theme.CARD, highlightbackground=theme.BORDER,
                              highlightthickness=1)
        table_card.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 8))

        self.tree = ttk.Treeview(table_card, columns=[name for name, *_ in _COLUMNS],
                                 show="headings", selectmode="browse")
        self._retitle_columns()
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        xscroll = ttk.Scrollbar(table_card, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=xscroll.set)
        xscroll.pack(side="bottom", fill="x")
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", lambda _event: self._focus_symbol())

        self.empty = tk.Frame(table_card, bg=theme.CARD)
        self.empty_label = tk.Label(self.empty, text="", bg=theme.CARD, fg=theme.MUTED,
                                    font=theme.current().base, justify="center")
        self.empty_label.pack(pady=(0, 10))
        button_row = tk.Frame(self.empty, bg=theme.CARD)
        button_row.pack()
        self.empty_open = secondary_button(button_row, t("db.open"), self._on_open_db)
        self.empty_open.pack(side="left")
        self.empty_create = secondary_button(button_row, t("db.create"), self._on_new_db)
        self.empty_create.pack(side="left", padx=(8, 0))

        self.editor = tk.Frame(self, bg=theme.CARD, padx=16, pady=12,
                               highlightbackground=theme.BORDER, highlightthickness=1)
        self.editor.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        self.editor.grid_remove()

        top = tk.Frame(self.editor, bg=theme.CARD)
        top.pack(fill="x")
        self.editor_title = tk.Label(top, text="", bg=theme.CARD, fg=theme.TEXT,
                                     font=theme.current().panel_title)
        self.editor_title.pack(side="left")
        self.editor_subtitle = tk.Label(top, text="", bg=theme.CARD, fg=theme.MUTED,
                                        font=theme.current().tiny)
        self.editor_subtitle.pack(side="left", padx=(10, 0))
        self.params_link = link_label(top, t("detail.view_all"), self._show_params,
                                      fg=theme.ACCENT, font=theme.current().tiny)
        self.params_link.pack(side="right")

        mapping = tk.Frame(self.editor, bg=theme.CARD)
        mapping.pack(fill="x", pady=(8, 0))
        mapping.grid_columnconfigure(1, weight=1)
        mapping.grid_columnconfigure(3, weight=1)
        self.symbol_caption = tk.Label(mapping, text=t("detail.symbol"), bg=theme.CARD,
                                       fg=theme.TEXT_SOFT, font=theme.current().tiny,
                                       width=7, anchor="w")
        self.symbol_caption.grid(row=0, column=0, sticky="w")
        self.symbol_var = tk.StringVar()
        self.symbol_combo = ttk.Combobox(mapping, textvariable=self.symbol_var,
                                         font=theme.current().small,
                                         style="Compact.TCombobox")
        self.symbol_combo.grid(row=0, column=1, sticky="ew", padx=(0, 12))
        self.footprint_caption = tk.Label(mapping, text=t("detail.footprint"), bg=theme.CARD,
                                          fg=theme.TEXT_SOFT, font=theme.current().tiny,
                                          width=7, anchor="w")
        self.footprint_caption.grid(row=0, column=2, sticky="w")
        self.footprint_var = tk.StringVar()
        self.footprint_combo = ttk.Combobox(mapping, textvariable=self.footprint_var,
                                            font=theme.current().small,
                                            style="Compact.TCombobox")
        self.footprint_combo.grid(row=0, column=3, sticky="ew")

        actions = tk.Frame(self.editor, bg=theme.CARD)
        actions.pack(fill="x", pady=(10, 0))
        self.delete_button = secondary_button(actions, t("db.delete"), self._delete_record)
        self.delete_button.pack(side="left")
        self.save_button = primary_button(actions, t("db.update_mapping"), self._save_mapping)
        self.save_button.pack(side="right")

    # -- language / scale --------------------------------------------------

    def _retitle_columns(self) -> None:
        factor = theme.scale()
        for key, width, anchor, stretch in _COLUMNS:
            self.tree.heading(key, text=t(f"col.{key}").upper(), anchor=anchor)
            self.tree.column(key, width=int(width * factor), minwidth=60, anchor=anchor,
                             stretch=stretch)

    def apply_scale(self) -> None:
        """Re-apply the column widths after the interface font size changed."""
        self._retitle_columns()

    def apply_language(self) -> None:
        self.title_label.configure(text=t("db.title"))
        self.search_button.configure(text=t("common.search"))
        self.refresh_button.configure(text=t("common.refresh"))
        self.empty_open.configure(text=t("db.open"))
        self.empty_create.configure(text=t("db.create"))
        self.symbol_caption.configure(text=t("detail.symbol"))
        self.footprint_caption.configure(text=t("detail.footprint"))
        self.save_button.configure(text=t("db.update_mapping"))
        self.delete_button.configure(text=t("db.delete"))
        self.params_link.configure(text=t("detail.view_all"))
        self._retitle_columns()
        if self.app.db_info is None:
            self.empty_label.configure(text=t("db.empty"))
            self.count_pill.set(tn("db.count", 0))
        else:
            self.refresh()
        if self.current is not None:
            self.editor_title.configure(text=self.current.mpn)

    # -- state -----------------------------------------------------------

    def show_empty_state(self, message: str) -> None:
        self.records = []
        self.current = None
        self.current_product = None
        self.tree.delete(*self.tree.get_children())
        self.editor.grid_remove()
        self.empty_label.configure(text=message)
        self.empty.place(relx=0.5, rely=0.45, anchor="center")
        self.count_pill.set(tn("db.count", 0))
        self.duplicate_link.pack_forget()

    def refresh(self) -> None:
        if self.app.database is None:
            self.show_empty_state(t("db.empty"))
            return
        self.empty.place_forget()
        try:
            self.records = self.app.database.list_records(self.filter_var.get(), limit=1000)
            self._duplicates = self.app.database.duplicate_mpns()
        except AppError as exc:
            self.app.show_banner(str(exc), exc.details, "error")
            return
        self.tree.delete(*self.tree.get_children())
        for index, record in enumerate(self.records):
            self.tree.insert("", "end", iid=str(index), values=(
                record.part or "-",
                record.mpn or "-",
                record.manufacturer or "-",
                record.description or "-",
                record.symbol or "-",
                record.footprint or "-",
                record.status or "-",
            ))
        total = len(self.records)
        self.count_pill.set(tn("db.count", total))
        if self._duplicates:
            self.duplicate_link.configure(text=t("db.duplicates", count=len(self._duplicates)))
            self.duplicate_link.pack(side="left", padx=(10, 0))
        else:
            self.duplicate_link.pack_forget()
        if not self.records:
            self.empty_label.configure(text=t("db.empty"))
            self.empty.place(relx=0.5, rely=0.45, anchor="center")
            self.editor.grid_remove()

    # -- events ----------------------------------------------------------

    def _on_select(self, _event=None) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        try:
            self.current = self.records[int(selection[0])]
        except (ValueError, IndexError):
            return
        try:
            self.current_product = self.app.database.full_record(self.current.mpn) \
                if self.app.database else None
        except AppError:
            self.current_product = None
        self.editor_title.configure(text=self.current.mpn)
        self.editor_subtitle.configure(text=self.current.description or "")
        self.symbol_var.set(self.current.symbol)
        self.footprint_var.set(self.current.footprint)
        self.editor.grid()

    def _focus_symbol(self) -> None:
        if self.current is not None:
            self.symbol_combo.focus_set()
            self.symbol_combo.selection_range(0, "end")

    def _save_mapping(self) -> None:
        if self.current is None or self.app.database is None:
            self.app.show_banner(t("db.no_selection"), "", "info")
            return
        try:
            self.app.database.update_mapping(self.current.mpn, self.symbol_var.get(),
                                             self.footprint_var.get())
        except AppError as exc:
            self.app.show_banner(str(exc), exc.details, "error")
            return
        self.app.toast(t("db.mapping_saved", mpn=self.current.mpn))
        self.refresh()

    def _delete_record(self) -> None:
        if self.current is None or self.app.database is None:
            self.app.show_banner(t("db.no_selection"), "", "info")
            return
        if not messagebox.askyesno(t("db.delete"), t("db.delete_confirm", mpn=self.current.mpn),
                                   parent=self):
            return
        try:
            self.app.database.delete(self.current.mpn)
        except AppError as exc:
            self.app.show_banner(str(exc), exc.details, "error")
            return
        self.app.toast(t("db.deleted", mpn=self.current.mpn))
        self.current = None
        self.current_product = None
        self.editor.grid_remove()
        info = self.app.refresh_db_info()
        if info is not None:
            self.app.window.update_db_info(info)

    def _show_params(self) -> None:
        if self.current_product is not None and self._on_show_params is not None:
            self._on_show_params(self.current_product)

    def _show_duplicates(self) -> None:
        if not self._duplicates:
            return
        rows = "\n".join(f"{mpn}  ×{count}" for mpn, count in self._duplicates[:40])
        if len(self._duplicates) > 40:
            rows += f"\n… (+{len(self._duplicates) - 40})"
        messagebox.showinfo(t("about.title"), t("db.duplicates_body", rows=rows), parent=self)

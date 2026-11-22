"""Results treeview with the LCSC columns, status colouring and an empty state."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from gui import theme
from kicad_core.models import ProductInfo
from lcsc_core import texts
from lcsc_core.texts import t


def _format_qty(value: str) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return value or "-"


def _format_price(value: str) -> str:
    """Headline price for the table; the full ladder lives in the detail panel."""
    tiers = [tier for tier in (value or "").split("/") if tier]
    if not tiers:
        return "-"
    return tiers[0] if len(tiers) == 1 else tiers[0] + " …"


def _status_tag(status: str) -> str:
    upper = (status or "").upper()
    if upper == "ACTIVE":
        return "status-active"
    if upper in ("OBSOLETE", "DISCONTINUED", "NOT RECOMMENDED", "NO STOCK"):
        return "status-obsolete"
    return "status-other"


class ResultsTable(tk.Frame):
    """The search results. Column headings follow the active language."""

    COLUMN_KEYS = (
        ("part", 92, "w", False),
        ("mpn", 168, "w", False),
        ("manufacturer", 132, "w", False),
        ("package", 96, "w", False),
        ("stock", 78, "e", False),
        ("price", 128, "e", False),
        ("description", 300, "w", True),
    )

    def __init__(self, parent: tk.Misc, *,
                 on_select: Callable[[ProductInfo | None], None] | None = None):
        super().__init__(parent, bg=theme.CARD)
        self.on_select = on_select
        self.products: list[ProductInfo] = []

        columns = [name for name, *_rest in self.COLUMN_KEYS]
        self.tree = ttk.Treeview(self, columns=columns, show="headings", selectmode="browse",
                                 height=6)
        self._retitle()
        self.tree.tag_configure("status-active", foreground=theme.TEXT)
        self.tree.tag_configure("status-obsolete", foreground=theme.DANGER)
        self.tree.tag_configure("status-other", foreground=theme.WARNING)

        self.scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=self.scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")

        self.empty = tk.Label(self, text=t("results.empty"), bg=theme.CARD,
                              fg=theme.MUTED, font=theme.current().base, justify="center")
        self.empty.place(relx=0.5, rely=0.55, anchor="center")

        self.tree.bind("<<TreeviewSelect>>", self._handle_select)
        self.tree.bind("<Double-1>", lambda _event: self._handle_select())

    # -- language / scale ------------------------------------------------

    def _retitle(self) -> None:
        factor = theme.scale()
        for key, width, anchor, stretch in self.COLUMN_KEYS:
            self.tree.heading(key, text=t(f"col.{key}").upper(), anchor=anchor)
            self.tree.column(key, width=int(width * factor), minwidth=60, anchor=anchor,
                             stretch=stretch)

    def apply_language(self) -> None:
        self._retitle()
        if not self.products:
            self.empty.configure(text=t("results.empty"))

    def apply_scale(self) -> None:
        """Re-apply the column widths after the interface font size changed."""
        self._retitle()

    # -- data ------------------------------------------------------------

    def set_products(self, products: list[ProductInfo], *, append: bool = False) -> None:
        if not append:
            self.products = []
            self.tree.delete(*self.tree.get_children())
        self.products.extend(products)
        for product in products:
            self.tree.insert("", "end", iid=str(len(self.tree.get_children())),
                             values=self._values(product),
                             tags=(_status_tag(product.base.part_status),))
        if self.products:
            self.empty.place_forget()
            if not append:
                self.tree.selection_set("0")
                self.tree.focus("0")
                self.tree.see("0")
        else:
            self.empty.configure(text=t("results.empty_none"))
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

    @staticmethod
    def _values(product: ProductInfo) -> tuple[str, ...]:
        base = product.base
        return (
            base.distributor_product_number or "-",
            base.manufacturer_product_number or "-",
            base.manufacturer or "-",
            base.package or "-",
            _format_qty(base.qty_available),
            _format_price(base.unit_price),
            base.description or "-",
        )

    def clear(self, message: str | None = None) -> None:
        self.products = []
        self.tree.delete(*self.tree.get_children())
        self.empty.configure(text=message or t("results.empty"))
        self.empty.place(relx=0.5, rely=0.55, anchor="center")
        if self.on_select:
            self.on_select(None)

    def selected_product(self) -> ProductInfo | None:
        selection = self.tree.selection()
        if not selection:
            return None
        try:
            return self.products[int(selection[0])]
        except (ValueError, IndexError):
            return None

    def selected_index(self) -> int:
        selection = self.tree.selection()
        if not selection:
            return -1
        try:
            return int(selection[0])
        except ValueError:
            return -1

    def select_index(self, index: int) -> None:
        if 0 <= index < len(self.products):
            self.tree.selection_set(str(index))
            self.tree.focus(str(index))
            self.tree.see(str(index))

    def replace_product(self, index: int, product: ProductInfo) -> None:
        """Redraw one row after a detail enrichment, keeping the selection."""
        if not 0 <= index < len(self.products):
            return
        self.products[index] = product
        self.tree.item(str(index), values=self._values(product),
                       tags=(_status_tag(product.base.part_status),))

    # -- events ----------------------------------------------------------

    def _handle_select(self, _event=None) -> None:
        if self.on_select:
            self.on_select(self.selected_product())

    def language_note(self) -> str:
        return texts.t("results.sort_note")

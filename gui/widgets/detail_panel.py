"""Selected-part detail panel: overview, links, KiCad mapping and the save action."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from gui import theme
from gui.widgets import Pill, link_label, primary_button, secondary_button, separator
from kicad_core.models import ProductInfo
from lcsc_core.texts import t

#: ``(field, label key)`` in display order, two per row.
_OVERVIEW_ROWS: tuple[tuple[tuple[str, str], ...], ...] = (
    (("manufacturer", "field.manufacturer"), ("part_number", "field.part_number")),
    (("package", "field.package"), ("category", "field.category")),
    (("stock", "field.stock"), ("price", "field.price")),
    (("status", "field.status"),),
)


class DetailPanel(tk.Frame):
    def __init__(
        self,
        parent: tk.Misc,
        *,
        on_save: Callable[[], None],
        on_clear: Callable[[], None],
        on_open_url: Callable[[str], None],
        on_show_params: Callable[[ProductInfo], None],
        site: str = "",
    ):
        super().__init__(parent, bg=theme.CARD, padx=14, pady=4)
        self._on_save = on_save
        self._on_clear = on_clear
        self._on_open_url = on_open_url
        self._on_show_params = on_show_params
        self.site = site
        self.product: ProductInfo | None = None
        self.in_database = False

        self.empty = tk.Label(
            self, text=t("detail.empty"), bg=theme.CARD, fg=theme.MUTED,
            font=theme.current().base, justify="center",
        )
        self.empty.pack(fill="both", expand=True, pady=60)

        self.content = tk.Frame(self, bg=theme.CARD)
        self.content.pack(fill="both", expand=True)

        self._build_header()
        separator(self.content, bg=theme.BORDER, pady=(4, 0))
        self._build_body()

        self.clear()

    # -- construction ----------------------------------------------------

    def _build_header(self) -> None:
        header = tk.Frame(self.content, bg=theme.CARD)
        header.pack(fill="x")
        header.grid_columnconfigure(0, weight=1)

        left = tk.Frame(header, bg=theme.CARD)
        left.grid(row=0, column=0, sticky="w")

        title_row = tk.Frame(left, bg=theme.CARD)
        title_row.pack(anchor="w")
        self.mpn_label = tk.Label(title_row, text="", bg=theme.CARD, fg=theme.TEXT,
                                  font=(theme.current().family, 13, "bold"))
        self.mpn_label.pack(side="left")
        self.manufacturer_label = tk.Label(title_row, text="", bg=theme.CARD,
                                           fg=theme.MUTED, font=theme.current().small)
        self.manufacturer_label.pack(side="left", padx=(10, 0), pady=(3, 0))
        self.badge = Pill(title_row, t("detail.badge_new"), fg=theme.WARNING, bg=theme.WARNING_BG)
        self.badge.pack(side="left", padx=(12, 0), pady=(3, 0))

        self.state_label = tk.Label(left, text="", bg=theme.CARD, fg=theme.FAINT,
                                    font=theme.current().tiny, anchor="w")
        self.state_label.pack(anchor="w")

        links = tk.Frame(header, bg=theme.CARD)
        links.grid(row=0, column=1, sticky="ne")
        self.datasheet_link = link_label(
            links, t("detail.datasheet"), lambda: self._open_link(self._url("datasheet")))
        self.datasheet_link.pack(side="left", padx=(0, 14))
        self.product_link = link_label(
            links, t("detail.product_page"), lambda: self._open_link(self._url("product")))
        self.product_link.pack(side="left")

    def _build_body(self) -> None:
        actions = tk.Frame(self.content, bg=theme.CARD)
        actions.pack(side="bottom", fill="x", pady=(8, 2))
        self.clear_button = secondary_button(actions, t("common.clear"), self._clear_clicked,
                                             pady=2, font=theme.current().small)
        self.clear_button.pack(side="left")
        self.save_button = primary_button(actions, t("detail.add"), self._on_save,
                                          padx=16, pady=3,
                                          font=(theme.current().family, 9, "bold"))
        self.save_button.pack(side="right")

        body = tk.Frame(self.content, bg=theme.CARD)
        body.pack(fill="both", expand=True, pady=(4, 0))
        body.grid_columnconfigure(0, weight=1, uniform="detail")
        body.grid_columnconfigure(1, weight=1, uniform="detail")
        body.grid_rowconfigure(0, weight=1)

        overview = tk.Frame(body, bg=theme.CARD)
        overview.grid(row=0, column=0, sticky="nsew", padx=(0, 18))
        mapping = tk.Frame(body, bg=theme.CARD)
        mapping.grid(row=0, column=1, sticky="nsew", padx=(18, 0))

        self._build_overview(overview)
        self._build_mapping(mapping)

    def _build_overview(self, parent: tk.Frame) -> None:
        header = tk.Frame(parent, bg=theme.CARD)
        header.pack(fill="x", pady=(0, 3))
        self.overview_title = tk.Label(header, text=t("detail.overview"), bg=theme.CARD,
                                       fg=theme.MUTED,
                                       font=(theme.current().family, 8, "bold"))
        self.overview_title.pack(side="left")
        self.params_link = link_label(header, t("detail.view_all"), self._show_params,
                                      fg=theme.ACCENT, font=theme.current().tiny)
        self.params_link.pack(side="right")
        self.params_label = tk.Label(header, text="", bg=theme.CARD, fg=theme.MUTED,
                                     font=theme.current().tiny)
        self.params_label.pack(side="right", padx=(0, 6))

        self.grid_frame = tk.Frame(parent, bg=theme.CARD)
        self.grid_frame.pack(fill="x", anchor="nw")
        self.grid_frame.grid_columnconfigure(0, weight=1, uniform="ov")
        self.grid_frame.grid_columnconfigure(1, weight=1, uniform="ov")

        self.value_labels: dict[str, tk.Label] = {}
        self.caption_labels: dict[str, tk.Label] = {}
        self._build_overview_grid()

    def _build_overview_grid(self) -> None:
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.value_labels.clear()
        self.caption_labels.clear()
        for row_index, pair in enumerate(_OVERVIEW_ROWS):
            for col_index, (field, key) in enumerate(pair):
                cell = tk.Frame(self.grid_frame, bg=theme.CARD)
                cell.grid(row=row_index, column=col_index, sticky="nw",
                          padx=(0, 10) if col_index == 0 else 0)
                caption = tk.Label(cell, text=t(key), bg=theme.CARD, fg=theme.MUTED,
                                   font=theme.current().tiny, width=11, anchor="w")
                caption.pack(side="left", anchor="n")
                self.caption_labels[field] = caption
                value = tk.Label(cell, text="-", bg=theme.CARD, fg=theme.TEXT,
                                 font=theme.current().small, anchor="w", justify="left",
                                 wraplength=190)
                value.pack(side="left", fill="x", expand=True, anchor="n")
                self.value_labels[field] = value

    def _build_mapping(self, parent: tk.Frame) -> None:
        self.mapping_title = tk.Label(parent, text=t("detail.mapping"), bg=theme.CARD,
                                      fg=theme.MUTED,
                                      font=(theme.current().family, 8, "bold"))
        self.mapping_title.pack(anchor="w", pady=(0, 3))

        symbol_row = tk.Frame(parent, bg=theme.CARD)
        symbol_row.pack(fill="x", pady=(0, 3))
        self.symbol_caption = tk.Label(symbol_row, text=t("detail.symbol"), bg=theme.CARD,
                                       fg=theme.TEXT_SOFT, font=theme.current().tiny,
                                       width=7, anchor="w")
        self.symbol_caption.pack(side="left", anchor="n", pady=(7, 0))
        self.symbol_var = tk.StringVar()
        self.symbol_combo = ttk.Combobox(symbol_row, textvariable=self.symbol_var, width=36,
                                         font=theme.current().small, style="Compact.TCombobox")
        self.symbol_combo.pack(side="left", fill="x", expand=True)

        footprint_row = tk.Frame(parent, bg=theme.CARD)
        footprint_row.pack(fill="x", pady=(0, 2))
        self.footprint_caption = tk.Label(footprint_row, text=t("detail.footprint"),
                                          bg=theme.CARD, fg=theme.TEXT_SOFT,
                                          font=theme.current().tiny, width=7, anchor="w")
        self.footprint_caption.pack(side="left", anchor="n", pady=(7, 0))
        self.footprint_var = tk.StringVar()
        self.footprint_combo = ttk.Combobox(footprint_row, textvariable=self.footprint_var,
                                            width=36, font=theme.current().small,
                                            style="Compact.TCombobox")
        self.footprint_combo.pack(side="left", fill="x", expand=True)

        hint = tk.Frame(parent, bg=theme.CARD)
        hint.pack(fill="x", pady=(0, 4))
        tk.Label(hint, text="ⓘ", bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny).pack(side="left")
        self.hint_label = tk.Label(hint, text=t("detail.mapping_hint"), bg=theme.CARD,
                                   fg=theme.MUTED, font=theme.current().tiny,
                                   wraplength=250, justify="left")
        self.hint_label.pack(side="left", padx=(5, 0))

    # -- language --------------------------------------------------------

    def apply_language(self, *, site: str = "") -> None:
        self.site = site or self.site
        self.empty.configure(text=t("detail.empty"))
        self.datasheet_link.configure(text=t("detail.datasheet"))
        self.product_link.configure(text=t("detail.product_page"))
        self.overview_title.configure(text=t("detail.overview"))
        self.params_link.configure(text=t("detail.view_all"))
        self.mapping_title.configure(text=t("detail.mapping"))
        self.symbol_caption.configure(text=t("detail.symbol"))
        self.footprint_caption.configure(text=t("detail.footprint"))
        self.hint_label.configure(text=t("detail.mapping_hint"))
        self.clear_button.configure(text=t("common.clear"))
        self._build_overview_grid()
        if self.product is not None:
            self.set_product(self.product, in_database=self.in_database)
        else:
            self.save_button.configure(text=t("detail.add"))

    # -- data ------------------------------------------------------------

    def set_suggestions(self, symbols: list[str], footprints: list[str]) -> None:
        def uniq(values: list[str]) -> list[str]:
            seen: list[str] = []
            for value in values:
                if value and value not in seen:
                    seen.append(value)
            return seen

        self.symbol_combo.configure(values=uniq(["Symbol:?", *symbols, "Standard:"]))
        self.footprint_combo.configure(
            values=uniq(["Footprint:?", *footprints, "Standard:"]))

    def set_product(self, product: ProductInfo, *, in_database: bool,
                    existing: ProductInfo | None = None) -> None:
        self.product = product
        self.in_database = in_database
        self.empty.pack_forget()
        self.content.pack(fill="both", expand=True)

        base = product.base
        self.mpn_label.configure(text=base.manufacturer_product_number or "(unnamed)")
        self.manufacturer_label.configure(text=base.manufacturer or "")
        if in_database:
            self.badge.set(t("detail.badge_saved"), fg=theme.SUCCESS, bg=theme.SUCCESS_BG)
            self.save_button.configure(text=t("detail.update"), bg=theme.ACCENT)
        else:
            self.badge.set(t("detail.badge_new"), fg=theme.WARNING, bg=theme.WARNING_BG)
            self.save_button.configure(text=t("detail.add"), bg=theme.ACCENT)

        self.value_labels["manufacturer"].configure(text=base.manufacturer or "-")
        self.value_labels["part_number"].configure(
            text=base.distributor_product_number or "-")
        self.value_labels["package"].configure(text=base.package or "-")
        self.value_labels["category"].configure(
            text=(base.id.split("/", 1)[0] if base.id else "-"))
        self.value_labels["stock"].configure(text=base.qty_available or "-")
        self.value_labels["price"].configure(text=base.unit_price or "-")
        self.value_labels["status"].configure(
            text=base.part_status or "-", fg=self._status_colour(base.part_status))

        source = existing if existing is not None else product
        self.symbol_var.set(source.base.kicad_symbol_library or "")
        self.footprint_var.set(source.base.kicad_footprint_library or "")

        count = len(list(product.reported_parameter_pairs()))
        self.params_label.configure(text=t("detail.param_count", count=count))
        self._set_links(base.datasheet_url, base.product_url)
        self._set_state(product.detail_state)

    def set_state(self, state: str) -> None:
        self._set_state(state)

    def _set_state(self, state: str) -> None:
        if state == "enriching":
            self.state_label.configure(text=t("detail.enriching"), fg=theme.ACCENT)
        elif state == "enriched":
            self.state_label.configure(text=t("detail.enriched"), fg=theme.SUCCESS)
        elif state == "failed":
            self.state_label.configure(text=t("detail.enrich_failed"), fg=theme.WARNING)
        else:
            self.state_label.configure(text="")

    def clear(self) -> None:
        self.product = None
        self.in_database = False
        self.content.pack_forget()
        self.empty.pack(fill="both", expand=True, pady=60)
        self.symbol_var.set("")
        self.footprint_var.set("")

    def current_mapping(self) -> tuple[str, str]:
        return self.symbol_var.get().strip(), self.footprint_var.get().strip()

    def set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        for widget in (self.symbol_combo, self.footprint_combo):
            widget.configure(state=state)
        self.save_button.configure(state=state)
        self.clear_button.configure(state=state)
        if busy:
            self.save_button.configure(bg="#7ba7cf")

    def focus_mapping(self) -> None:
        self.symbol_combo.focus_set()

    def show_error(self, message: str) -> None:
        self.save_button.configure(bg=theme.DANGER)
        self.after(1200, lambda: self.save_button.configure(bg=theme.ACCENT))

    # -- helpers ---------------------------------------------------------

    def _clear_clicked(self) -> None:
        self._on_clear()

    def _show_params(self) -> None:
        if self.product is not None:
            self._on_show_params(self.product)

    def _url(self, kind: str) -> str:
        if self.product is None:
            return ""
        base = self.product.base
        return base.datasheet_url if kind == "datasheet" else base.product_url

    def _open_link(self, url: str) -> None:
        if url:
            self._on_open_url(url)

    def _set_links(self, datasheet: str, product: str) -> None:
        for widget, url in ((self.datasheet_link, datasheet), (self.product_link, product)):
            colour = theme.ACCENT if url else theme.FAINT
            widget.configure(fg=colour, cursor="hand2" if url else "")
            widget._link_fg = colour  # type: ignore[attr-defined]

    @staticmethod
    def _status_colour(status: str) -> str:
        upper = (status or "").upper()
        if upper == "ACTIVE":
            return theme.SUCCESS
        if upper in ("OBSOLETE", "DISCONTINUED", "NO STOCK", "NOT RECOMMENDED"):
            return theme.DANGER
        return theme.WARNING

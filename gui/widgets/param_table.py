"""Read-only dialog listing every parameter the storefront reported."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from gui import theme
from kicad_core.models import ProductInfo
from lcsc_core.texts import t


def show_parameters_dialog(parent: tk.Misc, product: ProductInfo, *, site: str = "") -> tk.Toplevel:
    pairs = list(product.reported_parameter_pairs())
    part = product.base.distributor_product_number or product.mpn

    window = tk.Toplevel(parent)
    window.title(t("params.title", part=part))
    window.configure(bg=theme.BG)
    window.transient(parent.winfo_toplevel())
    window.geometry("660x480")
    window.minsize(440, 300)

    header = tk.Frame(window, bg=theme.CARD, padx=16, pady=12,
                      highlightbackground=theme.BORDER, highlightthickness=1)
    header.pack(fill="x", padx=14, pady=(14, 8))
    tk.Label(header, text=part, bg=theme.CARD, fg=theme.TEXT,
             font=theme.current().panel_title).pack(anchor="w")
    tk.Label(header, text=t("params.subtitle", count=len(pairs), site=site or "LCSC"),
             bg=theme.CARD, fg=theme.MUTED, font=theme.current().small).pack(anchor="w", pady=(2, 0))

    body = tk.Frame(window, bg=theme.CARD, highlightbackground=theme.BORDER,
                    highlightthickness=1)
    body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

    tree = ttk.Treeview(body, columns=("name", "value"), show="headings", selectmode="browse")
    tree.heading("name", text=t("params.column_name"), anchor="w")
    tree.heading("value", text=t("params.column_value"), anchor="w")
    tree.column("name", width=230, minwidth=120, anchor="w")
    tree.column("value", width=370, minwidth=160, anchor="w", stretch=True)
    scroll = ttk.Scrollbar(body, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
    scroll.pack(side="right", fill="y", pady=8, padx=(0, 4))

    for index, (name, value) in enumerate(pairs):
        tree.insert("", "end", iid=str(index), values=(name or "-", value or "-"))
    if not pairs:
        tree.insert("", "end", values=(t("params.none"), ""))

    footer = tk.Frame(window, bg=theme.BG)
    footer.pack(fill="x", padx=14, pady=(0, 14))
    ttk.Button(footer, text=t("common.close"), command=window.destroy).pack(side="right")

    window.bind("<Escape>", lambda _event: window.destroy())
    window.focus_set()
    return window

"""Main window: toolbar, tabs, search card, results/detail panes, status bar."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

import version
from gui import theme, utils
from gui.database_tab import DatabaseTab
from gui.dialogs.about_dialog import AboutDialog
from gui.dialogs.batch_dialog import BatchDialog
from gui.dialogs.settings_dialog import SettingsDialog
from gui.widgets import Pill, icon_button, primary_button, secondary_button
from gui.widgets.banner import Banner
from gui.widgets.detail_panel import DetailPanel
from gui.widgets.param_table import show_parameters_dialog
from gui.widgets.results_table import ResultsTable
from kicad_core.errors import AppError, RateLimitError
from kicad_core.models import ProductInfo
from lcsc_core.base import SearchPage
from lcsc_core.routing import LANGUAGES, site_for
from lcsc_core.texts import t, tn
from services.config import sync_folder_name
from services.database_service import DatabaseInfo

logger = logging.getLogger(__name__)


def _shorten(path: str, limit: int = 46) -> str:
    text = str(path)
    if len(text) <= limit:
        return text
    return "…" + text[-(limit - 1):]


class MainWindow:
    def __init__(self, root: tk.Tk, app):
        self.root = root
        self.app = app
        self.page: SearchPage | None = None
        self.query = ""
        self.category_id = ""
        self.selected_product: ProductInfo | None = None
        self.existing_product: ProductInfo | None = None
        self.db_info: DatabaseInfo | None = None
        self._toast_job: str | None = None
        self._enrich_token = 0
        self._language_guard = False
        self._category_ids: list[str] = []

        self.container = tk.Frame(root, bg=theme.BG)
        self.container.pack(fill="both", expand=True)

        self._build_menu()
        self._build_toolbar()
        self._build_tabs()
        self.banner = Banner(self.container, before=self.tabs_bar)
        self._build_status_bar()
        self._build_pages()
        self._bind_shortcuts()
        self._select_tab("search")
        self.update_db_info(app.db_info)

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    @property
    def site(self) -> str:
        return site_for(self.app.settings.language)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label=t("toolbar.open"), accelerator="Ctrl+O",
                              command=self.open_database_dialog)
        file_menu.add_command(label=t("toolbar.new"), accelerator="Ctrl+N",
                              command=self.new_database_dialog)
        self.recent_menu = tk.Menu(file_menu, tearoff=0)
        file_menu.add_cascade(label="Recent databases", menu=self.recent_menu)
        file_menu.add_separator()
        file_menu.add_command(label=t("toolbar.batch"), accelerator="Ctrl+B",
                              command=self.open_batch_dialog)
        file_menu.add_separator()
        file_menu.add_command(label=t("common.close"), command=self.app.close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.file_menu = file_menu

        tools_menu = tk.Menu(menubar, tearoff=0)
        tools_menu.add_command(label=t("toolbar.settings"), command=self.open_settings_dialog)
        tools_menu.add_separator()
        tools_menu.add_command(label=t("common.refresh"), accelerator="F5",
                               command=self.refresh_database)
        menubar.add_cascade(label="Tools", menu=tools_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label=t("about.title"), command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.configure(menu=menubar)
        self.menubar = menubar
        self._refresh_recent_menu()

    def _build_toolbar(self) -> None:
        toolbar = tk.Frame(self.container, bg=theme.BG, padx=14, pady=8)
        toolbar.pack(fill="x")

        chip = tk.Frame(toolbar, bg=theme.CARD, highlightbackground=theme.BORDER,
                        highlightthickness=1, padx=10, pady=5)
        chip.pack(side="left")
        icon = tk.Label(chip, bg=theme.CARD)
        icon.pack(side="left", padx=(0, 8))
        from gui import assets

        db_icon = assets.load_icon("database", self.root)
        if db_icon is not None:
            icon.configure(image=db_icon)
            icon.image = db_icon  # type: ignore[attr-defined]

        text = tk.Frame(chip, bg=theme.CARD)
        text.pack(side="left")
        self.db_name_label = tk.Label(text, text=t("toolbar.no_database"), bg=theme.CARD,
                                      fg=theme.TEXT, font=theme.current().heading)
        self.db_name_label.pack(anchor="w")
        self.db_path_label = tk.Label(text, text=t("toolbar.open_or_create"), bg=theme.CARD,
                                      fg=theme.MUTED, font=theme.current().tiny)
        self.db_path_label.pack(anchor="w")
        self.db_count_pill = Pill(chip, tn("toolbar.parts", 0), fg=theme.TEXT_SOFT)
        self.db_count_pill.pack(side="left", padx=(12, 2))

        self.open_button = secondary_button(toolbar, t("toolbar.open"),
                                            self.open_database_dialog, icon="open")
        self.open_button.pack(side="left", padx=(10, 0))
        self.new_button = secondary_button(toolbar, t("toolbar.new"),
                                           self.new_database_dialog, icon="new")
        self.new_button.pack(side="left", padx=(6, 0))

        self.settings_button = icon_button(toolbar, "gear", self.open_settings_dialog,
                                           tooltip=t("toolbar.settings"))
        self.settings_button.pack(side="right", padx=(6, 0))

        language_frame = tk.Frame(toolbar, bg=theme.BG)
        language_frame.pack(side="right", padx=(6, 0))
        self.language_label = tk.Label(language_frame, text=t("toolbar.language"), bg=theme.BG,
                                       fg=theme.MUTED, font=theme.current().tiny)
        self.language_label.pack(side="left", padx=(0, 5))
        self.language_var = tk.StringVar()
        self.language_combo = ttk.Combobox(
            language_frame, textvariable=self.language_var, state="readonly", width=18,
            values=[label for _code, label in LANGUAGES], font=theme.current().small,
        )
        self.language_combo.pack(side="left")
        self.language_combo.bind("<<ComboboxSelected>>", self._on_language_changed)
        self._sync_language_combo()

        self.batch_button = secondary_button(toolbar, t("toolbar.batch"),
                                             self.open_batch_dialog, icon="batch")
        self.batch_button.pack(side="right")

    def _build_tabs(self) -> None:
        self.tabs_bar = tk.Frame(self.container, bg=theme.BG, padx=14)
        self.tabs_bar.pack(fill="x")

        self.tab_buttons: dict[str, dict[str, Any]] = {}
        search_tab = self._make_tab("search", t("tab.search", site=self.site))
        search_tab["frame"].pack(side="left")
        database_tab = self._make_tab("database", t("tab.database"))
        database_tab["frame"].pack(side="left", padx=(6, 0))
        self.db_tab_badge = Pill(database_tab["body"], "0", fg=theme.TEXT_SOFT)
        self.db_tab_badge.pack(side="left", padx=(4, 0))
        self.db_tab_badge.bind("<Button-1>", lambda _event: self._select_tab("database"))

        site_frame = tk.Frame(self.tabs_bar, bg=theme.BG)
        site_frame.pack(side="right")
        self.site_dot = tk.Label(site_frame, text="●", bg=theme.BG, fg=theme.SUCCESS,
                                 font=theme.current().small)
        self.site_dot.pack(side="left")
        self.site_label = tk.Label(site_frame, text=self.site, bg=theme.BG, fg=theme.MUTED,
                                   font=theme.current().small)
        self.site_label.pack(side="left", padx=(5, 0))

        tk.Frame(self.container, bg=theme.BORDER, height=1).pack(fill="x")

    def _make_tab(self, key: str, text: str) -> dict[str, Any]:
        frame = tk.Frame(self.tabs_bar, bg=theme.BG, cursor="hand2")
        body = tk.Frame(frame, bg=theme.BG)
        body.pack(fill="x")
        label = tk.Label(body, text=text, bg=theme.BG, fg=theme.MUTED,
                         font=theme.current().heading, padx=6, pady=5, cursor="hand2")
        label.pack(side="left")
        underline = tk.Frame(frame, bg=theme.BG, height=2)
        underline.pack(fill="x")
        info = {"frame": frame, "body": body, "label": label, "underline": underline}
        for widget in (frame, body, label):
            widget.bind("<Button-1>", lambda _event, tab=key: self._select_tab(tab))
        self.tab_buttons[key] = info
        return info

    def _select_tab(self, key: str) -> None:
        self.active_tab = key
        for name, info in self.tab_buttons.items():
            active = name == key
            info["label"].configure(fg=theme.ACCENT if active else theme.MUTED)
            info["underline"].configure(bg=theme.ACCENT if active else theme.BG)
        if key == "database":
            self.database_tab.refresh()
        self.pages[key].tkraise()

    def _build_pages(self) -> None:
        self.content = tk.Frame(self.container, bg=theme.BG)
        self.content.pack(fill="both", expand=True)
        self.content.grid_rowconfigure(0, weight=1)
        self.content.grid_columnconfigure(0, weight=1)

        self.pages: dict[str, tk.Widget] = {}
        self.pages["search"] = self._build_search_page()
        self.database_tab = DatabaseTab(
            self.content,
            self.app,
            on_open_db=self.open_database_dialog,
            on_new_db=self.new_database_dialog,
            on_show_params=self._show_parameters,
        )
        self.pages["database"] = self.database_tab
        for page in self.pages.values():
            page.grid(row=0, column=0, sticky="nsew")

    def _build_search_page(self) -> tk.Frame:
        page = tk.Frame(self.content, bg=theme.BG)

        search_card = tk.Frame(page, bg=theme.CARD, highlightbackground=theme.BORDER,
                               highlightthickness=1, padx=16, pady=8)
        search_card.pack(fill="x", padx=14, pady=(8, 6))
        self.search_section_label = tk.Label(
            search_card, text=t("search.section", site=self.site).upper(), bg=theme.CARD,
            fg=theme.MUTED, font=theme.current().section)
        self.search_section_label.pack(anchor="w")
        row = tk.Frame(search_card, bg=theme.CARD)
        row.pack(fill="x", pady=(3, 0))
        self.search_var = tk.StringVar()
        self.search_entry = ttk.Entry(row, textvariable=self.search_var,
                                      font=theme.current().entry)
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<Return>", lambda _event: self.perform_search())
        self.search_button = primary_button(row, t("search.button"), self.perform_search,
                                            icon="search", padx=24, pady=5)
        self.search_button.pack(side="left", padx=(8, 0))
        self.search_tip = tk.Label(search_card, text=t("search.tip"), bg=theme.CARD,
                                   fg=theme.MUTED, font=theme.current().tiny)
        self.search_tip.pack(anchor="w", pady=(4, 0))

        self.paned = ttk.PanedWindow(page, orient="vertical")
        self.paned.pack(fill="both", expand=True, padx=14, pady=(0, 6))

        results_card = tk.Frame(self.paned, bg=theme.CARD, highlightbackground=theme.BORDER,
                                highlightthickness=1)
        results_header = tk.Frame(results_card, bg=theme.CARD, padx=16, pady=6)
        results_header.pack(fill="x")
        self.results_title_label = tk.Label(results_header, text=t("results.title"),
                                            bg=theme.CARD, fg=theme.TEXT,
                                            font=theme.current().card_title)
        self.results_title_label.pack(side="left")
        self.results_pill = Pill(results_header, t("results.count", count=0), fg=theme.MUTED)
        self.results_pill.pack(side="left", padx=(10, 0))
        self.note_label = tk.Label(results_header, text="", bg=theme.CARD, fg=theme.WARNING,
                                   font=theme.current().tiny, justify="right", anchor="e")
        self.note_label.pack(side="right")
        tk.Frame(results_card, bg=theme.BORDER, height=1).pack(fill="x")

        pager = tk.Frame(results_card, bg=theme.CARD, padx=12, pady=6)
        pager.pack(side="bottom", fill="x")
        self.category_label = tk.Label(pager, text=t("results.category_label"), bg=theme.CARD,
                                       fg=theme.MUTED, font=theme.current().tiny)
        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(pager, textvariable=self.category_var,
                                           state="readonly", width=30,
                                           font=theme.current().small)
        self.category_combo.bind("<<ComboboxSelected>>", self._on_category_changed)
        self.prev_button = secondary_button(pager, t("results.prev"), self._go_previous,
                                            padx=10, pady=3, font=theme.current().small)
        self.next_button = secondary_button(pager, t("results.next"), self._go_next,
                                            padx=10, pady=3, font=theme.current().small)
        self.more_button = secondary_button(pager, t("results.load_more", count=30),
                                            self._load_more, padx=10, pady=3,
                                            font=theme.current().small)
        self.page_label = tk.Label(pager, text="", bg=theme.CARD, fg=theme.MUTED,
                                   font=theme.current().small)
        self.more_button.pack(side="right")
        self.next_button.pack(side="right", padx=(0, 6))
        self.page_label.pack(side="right", padx=(0, 8))
        self.prev_button.pack(side="right", padx=(0, 6))
        self._update_pager()

        self.results_table = ResultsTable(results_card, on_select=self.on_result_selected)
        self.results_table.pack(fill="both", expand=True, padx=4, pady=(0, 2))

        self.paned.add(results_card, weight=3)

        detail_card = tk.Frame(self.paned, bg=theme.CARD, highlightbackground=theme.BORDER,
                               highlightthickness=1)
        self.detail = DetailPanel(
            detail_card,
            on_save=self.save_detail,
            on_clear=self.clear_detail,
            on_open_url=self.open_url,
            on_show_params=self._show_parameters,
            site=self.site,
        )
        self.detail.pack(fill="both", expand=True)
        self.paned.add(detail_card, weight=2)

        self.root.after(120, self._fit_detail_pane)
        return page

    def _fit_detail_pane(self) -> None:
        """Give the detail pane exactly the height its content asks for.

        The requirement is measured rather than hard-coded so a larger interface
        font (which makes the overview grid taller) does not clip it.
        """
        try:
            self.root.update_idletasks()
            height = self.paned.winfo_height()
            if height <= 200:
                return
            needed = max(150, self.detail.winfo_reqheight() + 8)
            self.paned.sashpos(0, max(120, height - min(needed, height - 120)))
        except (tk.TclError, IndexError):  # pragma: no cover
            pass

    def _build_status_bar(self) -> None:
        bar = tk.Frame(self.container, bg=theme.CARD, highlightbackground=theme.BORDER,
                       highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        inner = tk.Frame(bar, bg=theme.CARD, padx=14, pady=6)
        inner.pack(fill="x")

        self.status_dot = tk.Label(inner, text="●", bg=theme.CARD, fg=theme.FAINT,
                                   font=theme.current().small)
        self.status_dot.pack(side="left")
        self.status_text = tk.Label(inner, text=t("status.no_db"), bg=theme.CARD,
                                    fg=theme.MUTED, font=theme.current().small)
        self.status_text.pack(side="left", padx=(5, 16))
        self.status_file = tk.Label(inner, text="", bg=theme.CARD, fg=theme.MUTED,
                                    font=theme.current().small)
        self.status_file.pack(side="left", padx=(0, 16))
        self.status_count = tk.Label(inner, text="", bg=theme.CARD, fg=theme.MUTED,
                                     font=theme.current().small)
        self.status_count.pack(side="left", padx=(0, 16))
        self.status_params = tk.Label(inner, text="", bg=theme.CARD, fg=theme.MUTED,
                                      font=theme.current().small)
        self.status_params.pack(side="left")

        self.status_site = tk.Label(inner, text=self.site, bg=theme.CARD, fg=theme.MUTED,
                                    font=theme.current().small)
        self.status_site.pack(side="right", padx=(12, 0))
        self.status_version = tk.Label(inner, text=f"v{version.__version__}", bg=theme.CARD,
                                       fg=theme.FAINT, font=theme.current().tiny)
        self.status_version.pack(side="right")

    def _bind_shortcuts(self) -> None:
        self.root.bind("<<ThemeFontSize>>", lambda _event: self._after_font_change())
        for sequence, handler in (
            ("<Control-o>", lambda: self.open_database_dialog()),
            ("<Control-O>", lambda: self.open_database_dialog()),
            ("<Control-n>", lambda: self.new_database_dialog()),
            ("<Control-N>", lambda: self.new_database_dialog()),
            ("<Control-b>", lambda: self.open_batch_dialog()),
            ("<Control-B>", lambda: self.open_batch_dialog()),
            ("<Control-f>", self.focus_search),
            ("<Control-F>", self.focus_search),
            ("<Control-l>", self.focus_search),
            ("<Control-L>", self.focus_search),
            ("<Control-s>", self.save_detail),
            ("<Control-S>", self.save_detail),
            ("<F5>", self.refresh_database),
        ):
            self.root.bind(sequence, lambda _event, fn=handler: fn())
        self.root.bind("<Escape>", self._on_escape)

    def _on_escape(self, _event=None) -> None:
        if self.banner.visible:
            self.banner.hide()

    # ------------------------------------------------------------------
    # Font size
    # ------------------------------------------------------------------

    def _after_font_change(self) -> None:
        """Re-fit pixel geometry after the named fonts changed size."""
        try:
            self.root.update_idletasks()
        except tk.TclError:  # pragma: no cover - shutting down
            return
        self.results_table.apply_scale()
        self.database_tab.apply_scale()
        self._fit_detail_pane()

    def refresh_layout(self) -> None:
        """Public hook for the app after a theme change."""
        self._after_font_change()

    # ------------------------------------------------------------------
    # Language
    # ------------------------------------------------------------------

    def _sync_language_combo(self) -> None:
        labels = [label for _code, label in LANGUAGES]
        self.language_var.set(dict(LANGUAGES).get(self.app.settings.language, labels[0]))

    def _on_language_changed(self, _event=None) -> None:
        if self._language_guard:
            return
        chosen = self.language_var.get()
        code = next((code for code, label in LANGUAGES if label == chosen), None)
        if code is None or code == self.app.settings.language:
            self._sync_language_combo()
            return
        previous = self.app.settings.language
        self.app.settings.language = code
        self._language_guard = True
        try:
            self.app.apply_settings(previous_language=previous)
        finally:
            self._language_guard = False
        self._sync_language_combo()

    def apply_language(self) -> None:
        """Re-label everything after the language setting changed."""
        self._build_menu()
        self.tab_buttons["search"]["label"].configure(text=t("tab.search", site=self.site))
        self.tab_buttons["database"]["label"].configure(text=t("tab.database"))
        self.site_label.configure(text=self.site)
        self.status_site.configure(text=self.site)
        self.language_label.configure(text=t("toolbar.language"))
        self.open_button.configure(text=t("toolbar.open"))
        self.new_button.configure(text=t("toolbar.new"))
        self.batch_button.configure(text=t("toolbar.batch"))
        self.search_section_label.configure(text=t("search.section", site=self.site).upper())
        self.search_button.configure(
            text=t("search.busy") if self.app.runner.busy else t("search.button"))
        self.search_tip.configure(text=t("search.tip"))
        self.results_title_label.configure(text=t("results.title"))
        self.category_label.configure(text=t("results.category_label"))
        self.prev_button.configure(text=t("results.prev"))
        self.next_button.configure(text=t("results.next"))
        self.more_button.configure(
            text=t("results.load_more", count=self.app.settings.page_size))
        self.results_table.apply_language()
        self.detail.apply_language(site=self.site)
        if hasattr(self, "database_tab"):
            self.database_tab.apply_language()

        # The results on screen came from the other storefront: drop them rather
        # than show foreign-language rows under new headings.
        self._enrich_token += 1
        self.page = None
        self.selected_product = None
        self.existing_product = None
        self.results_table.clear(t("results.empty"))
        self.detail.clear()
        self._reset_category_combo()
        self.results_pill.set(tn("results.count", 0), fg=theme.MUTED)
        self.note_label.configure(text="")
        self._update_pager()
        self.update_db_info(self.db_info)
        self.root.title(f"{version.APP_NAME} - {t('app.subtitle')}" if self.db_info is None
                        else f"{version.APP_NAME} - {Path(self.db_info.path).name}")

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def open_database_dialog(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root, title="Open a KiCad components database",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.app.open_database(path, create=False)
        except AppError as exc:
            self.show_banner(str(exc), exc.details, "error")
            return
        self._after_database_opened()

    def new_database_dialog(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root, title="Create a KiCad components database",
            defaultextension=".db",
            initialdir=str(Path(self.app.settings.database_path).parent),
            initialfile="components.db",
            filetypes=[("SQLite database", "*.db"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            self.app.open_database(path, create=True)
        except AppError as exc:
            self.show_banner(str(exc), exc.details, "error")
            return
        self._after_database_opened()

    def _after_database_opened(self) -> None:
        info = self.app.db_info
        if info is None:
            return
        sync = sync_folder_name(info.path)
        if sync:
            self.show_banner(
                f"This database is inside {sync}. Sync clients can lock or corrupt "
                "SQLite files; consider moving it to a local folder such as "
                "~/KiCadLibGenLCSC.", "", "warning")
        else:
            self.clear_banner()
        self.toast(t("status.opened", name=Path(info.path).name, count=info.count))
        self._refresh_recent_menu()

    def refresh_database(self) -> None:
        info = self.app.refresh_db_info()
        if info is not None:
            self.update_db_info(info)
        self.toast(t("status.refreshed"))

    def update_db_info(self, info: DatabaseInfo | None) -> None:
        self.db_info = info
        if info is None:
            self.db_name_label.configure(text=t("toolbar.no_database"))
            self.db_path_label.configure(text=t("toolbar.open_or_create"))
            self.db_count_pill.set(tn("toolbar.parts", 0))
            self.db_tab_badge.set("0")
            self.status_dot.configure(fg=theme.FAINT)
            self.status_text.configure(text=t("status.no_db"), fg=theme.MUTED)
            self.status_file.configure(text="")
            self.status_count.configure(text="")
            self.status_params.configure(text="")
            self.database_tab.show_empty_state(t("db.empty"))
            self.detail.set_suggestions([], [])
            self.root.title(f"{version.APP_NAME} - {t('app.subtitle')}")
            return

        name = Path(info.path).name
        folder = str(Path(info.path).parent)
        self.db_name_label.configure(text=name)
        self.db_path_label.configure(text=_shorten(folder))
        self.db_count_pill.set(tn("toolbar.parts", info.count))
        self.db_tab_badge.set(str(info.count))
        self.status_dot.configure(fg=theme.SUCCESS)
        self.status_text.configure(text=t("status.ready"), fg=theme.SUCCESS)
        self.status_file.configure(text=name)
        self.status_count.configure(text=tn("toolbar.parts", info.count))
        self.status_params.configure(text=tn("status.param_rows", info.parameter_count))
        self.root.title(f"{version.APP_NAME} - {name}")
        try:
            symbols = self.app.database.distinct_symbols() if self.app.database else []
            footprints = self.app.database.distinct_footprints() if self.app.database else []
        except AppError:
            symbols, footprints = [], []
        self.detail.set_suggestions(symbols, footprints)
        self.database_tab.refresh()

    def _refresh_recent_menu(self) -> None:
        self.recent_menu.delete(0, "end")
        recent = self.app.settings.recent_databases
        if not recent:
            self.recent_menu.add_command(label=t("common.none"), state="disabled")
            return
        for path in recent:
            self.recent_menu.add_command(
                label=f"{Path(path).name}  —  {_shorten(path, 60)}",
                command=lambda item=path: self._open_recent(item),
            )

    def _open_recent(self, path: str) -> None:
        if not Path(path).exists():
            self.show_banner(f"Database not found: {path}", "", "warning")
            return
        try:
            self.app.open_database(path, create=False)
        except AppError as exc:
            self.show_banner(str(exc), exc.details, "error")
            return
        self._after_database_opened()

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def focus_search(self) -> None:
        self._select_tab("search")
        self.search_entry.focus_set()
        self.search_entry.selection_range(0, "end")

    def perform_search(self, *, page: int = 1, append: bool = False) -> None:
        query = self.search_var.get().strip()
        if not query:
            self._select_tab("search")
            self.search_entry.focus_set()
            self.show_banner(t("search.empty_query"), "", "info")
            return
        if self.app.runner.busy:
            self.toast(t("status.wait"))
            return
        self._select_tab("search")
        self.clear_banner()
        if not append:
            self.query = query
            self.category_id = ""
            self._reset_category_combo()
        self._set_search_busy(True)
        self.status_text.configure(text=t("status.searching", site=self.site), fg=theme.ACCENT)
        self.results_pill.set(t("results.searching"), fg=theme.ACCENT)
        submitted = self.app.runner.submit(
            lambda: self.app.search_service.search(self.query, page,
                                                   category_id=self.category_id),
            lambda result: self._search_succeeded(result, append=append),
            self._search_failed,
            name="search",
        )
        if not submitted:
            self._set_search_busy(False)

    def _search_succeeded(self, page: SearchPage, *, append: bool) -> None:
        self._set_search_busy(False)
        self.page = page
        self.results_table.set_products(page.items, append=append)
        shown = len(self.results_table.products)
        self.results_pill.set(t("results.count", count=shown),
                              fg=theme.SUCCESS if shown else theme.MUTED)
        self.note_label.configure(text=page.note or "")
        self._update_categories(page)
        self._update_pager()
        self.status_text.configure(
            text=t("status.ready") if self.db_info is not None else t("status.no_db"),
            fg=theme.SUCCESS if self.db_info is not None else theme.MUTED,
        )
        if not page.items and not append:
            self.detail.clear()
            self.selected_product = None
            self.existing_product = None
            self.show_banner(t("results.empty_none"), "", "info")
        elif append and self.results_table.products:
            last = len(self.results_table.products) - 1
            self.results_table.select_index(last)
            self.results_table.tree.see(str(last))

    def _search_failed(self, exc: BaseException) -> None:
        self._set_search_busy(False)
        self.results_pill.set(t("results.count", count=0), fg=theme.MUTED)
        self.status_text.configure(text=t("status.failed"), fg=theme.DANGER)
        if isinstance(exc, RateLimitError):
            self.show_banner(
                t("search.rate_limited", seconds=getattr(exc, "retry_after", None) or 60),
                exc.details, "warning")
            return
        if isinstance(exc, AppError):
            self.show_banner(str(exc), exc.details, "error")
        else:
            logger.exception("Unexpected search failure",
                             exc_info=(type(exc), exc, exc.__traceback__))
            self.show_banner(f"Search failed: {exc}", "", "error")

    def _set_search_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.search_button.configure(state=state,
                                     text=t("search.busy") if busy else t("search.button"))
        self.batch_button.configure(state=state)
        self.open_button.configure(state=state)
        self.new_button.configure(state=state)

    # -- paging ----------------------------------------------------------

    def _update_pager(self) -> None:
        page = self.page
        if page is None or page.total == 0:
            self.page_label.configure(text="")
            for button in (self.prev_button, self.next_button, self.more_button):
                button.configure(state="disabled")
            return
        self.page_label.configure(text=t("results.page", page=page.page, pages=page.pages))
        self.prev_button.configure(state="normal" if page.page > 1 else "disabled")
        self.next_button.configure(state="normal" if page.page < page.pages else "disabled")
        self.more_button.configure(
            state="normal" if page.page < page.pages else "disabled",
            text=t("results.load_more", count=page.page_size),
        )

    def _go_previous(self) -> None:
        if self.page and self.page.page > 1:
            self.perform_search(page=self.page.page - 1)

    def _go_next(self) -> None:
        if self.page and self.page.page < self.page.pages:
            self.perform_search(page=self.page.page + 1)

    def _load_more(self) -> None:
        if self.page and self.page.page < self.page.pages:
            self.perform_search(page=self.page.page + 1, append=True)

    def _update_categories(self, page: SearchPage) -> None:
        if not page.categories:
            self.category_combo.pack_forget()
            self.category_label.pack_forget()
            self._category_ids = []
            return
        self._category_ids = [""] + [item.id for item in page.categories]
        values = [t("results.category_all")] + [
            f"{item.name} ({item.count})" for item in page.categories]
        self.category_combo.configure(values=values)
        current = self._category_ids.index(page.category_id) if page.category_id in (
            self._category_ids) else 0
        self.category_combo.current(current)
        self.category_label.pack(side="left", padx=(0, 4))
        self.category_combo.pack(side="left")

    def _reset_category_combo(self) -> None:
        self._category_ids = []
        self.category_combo.set("")
        self.category_combo.pack_forget()
        self.category_label.pack_forget()

    def _on_category_changed(self, _event=None) -> None:
        index = self.category_combo.current()
        if not 0 <= index < len(self._category_ids):
            return
        self.category_id = self._category_ids[index]
        self.perform_search(page=1)

    # -- selection -------------------------------------------------------

    def on_result_selected(self, product: ProductInfo | None) -> None:
        if product is None:
            self.selected_product = None
            self.existing_product = None
            self.detail.clear()
            return
        self.selected_product = product
        existing = None
        if self.app.database is not None:
            try:
                existing = self.app.database.find_by_mpn(product.mpn)
            except AppError as exc:
                self.show_banner(str(exc), exc.details, "error")
        self.existing_product = existing
        self.detail.set_product(product, in_database=existing is not None, existing=existing)
        self._fit_detail_pane()
        self._start_enrichment(product)

    def _start_enrichment(self, product: ProductInfo) -> None:
        if product.detail_state in ("enriched", "enriching"):
            return
        service = self.app.search_service
        if not service.supports_detail():
            return
        part = product.base.distributor_product_number
        self._enrich_token += 1
        token = self._enrich_token
        product.detail_state = "enriching"
        self.detail.set_state("enriching")

        def work():
            return service.enrich_safely(product)

        def done(result: Any) -> None:
            enriched, warning = result
            if token != self._enrich_token:
                return
            current = self.selected_product
            if current is None or current.base.distributor_product_number != part:
                return
            self.selected_product = enriched
            index = self.results_table.selected_index()
            if index >= 0:
                self.results_table.replace_product(index, enriched)
            self.detail.set_product(enriched, in_database=self.existing_product is not None,
                                    existing=self.existing_product)
            if warning:
                self.detail.set_state("failed")
                self.show_banner(t("detail.enrich_failed"), warning, "warning")

        def failed(exc: BaseException) -> None:
            if token != self._enrich_token:
                return
            self.detail.set_state("failed")
            logger.info("Detail enrichment failed: %s", exc)

        if not self.app.runner.submit_background(work, done, failed, name="detail"):
            self.detail.set_state("")

    def clear_detail(self) -> None:
        self._enrich_token += 1
        self.selected_product = None
        self.existing_product = None
        self.detail.clear()
        selection = self.results_table.tree.selection()
        if selection:
            self.results_table.tree.selection_remove(*selection)

    # -- save ------------------------------------------------------------

    def save_detail(self) -> None:
        product = self.detail.product
        if product is None:
            return
        if self.app.database is None:
            if messagebox.askyesno(
                "No database open",
                "A database is required to save parts. Create one now?",
                parent=self.root,
            ):
                self.new_database_dialog()
            return

        symbol, footprint = self.detail.current_mapping()
        candidate = product.copy().with_mapping(symbol, footprint)
        try:
            existing = self.app.database.find_by_mpn(candidate.mpn)
        except AppError as exc:
            self.show_banner(str(exc), exc.details, "error")
            return
        if existing is not None:
            if not messagebox.askyesno(
                "Update existing part?",
                f"{candidate.mpn} already exists in the database.\n\n"
                "Overwrite its record and KiCad mapping?",
                parent=self.root,
            ):
                return
        self.detail.set_busy(True)
        try:
            outcome = self.app.database.upsert(candidate)
        except AppError as exc:
            self.show_banner(str(exc), exc.details, "error")
            self.detail.show_error(str(exc))
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Unexpected save failure")
            self.show_banner(f"Could not save the part: {exc}", "", "error")
            return
        finally:
            self.detail.set_busy(False)

        verb = "Added" if outcome.action == "inserted" else "Updated"
        message = t("status.saved", part=candidate.mpn)
        if outcome.rows_updated > 1:
            message += f" ({verb.lower()} {outcome.rows_updated} legacy duplicate rows)"
        self.toast(message)
        info = self.app.refresh_db_info()
        if info is not None:
            self.update_db_info(info)
        stored = self.app.database.find_by_mpn(candidate.mpn) if self.app.database else None
        self.detail.set_product(candidate, in_database=True, existing=stored or candidate)
        self.existing_product = stored

    def _show_parameters(self, product: ProductInfo) -> None:
        show_parameters_dialog(self.root, product, site=self.site)

    def open_url(self, url: str) -> None:
        if not utils.open_url(url):
            self.show_banner(f"Could not open {url}", "", "warning")

    # ------------------------------------------------------------------
    # Dialog actions
    # ------------------------------------------------------------------

    def open_batch_dialog(self) -> None:
        if self.app.database is None:
            self.show_banner("Open or create a database before importing a batch.", "", "info")
            return
        BatchDialog(self.root, self.app, on_finished=self._batch_finished)

    def _batch_finished(self, summary) -> None:
        info = self.app.refresh_db_info()
        if info is not None:
            self.update_db_info(info)
        if getattr(summary, "log_path", None):
            self.toast(t("batch.log_written", path=Path(summary.log_path).name))

    def open_settings_dialog(self) -> None:
        SettingsDialog(self.root, self.app, on_language_change=self._sync_language_combo)

    def show_about(self) -> None:
        AboutDialog(self.root, site=self.site,
                    database=self.db_info.path if self.db_info else "")

    # ------------------------------------------------------------------
    # Status / banner / toast
    # ------------------------------------------------------------------

    def show_banner(self, message: str, details: str = "", kind: str = "error") -> None:
        self.banner.show(message, details or "", kind)

    def clear_banner(self) -> None:
        self.banner.hide()

    def toast(self, message: str) -> None:
        self.status_text.configure(text=message, fg=theme.TEXT_SOFT)
        if self._toast_job is not None:
            try:
                self.root.after_cancel(self._toast_job)
            except tk.TclError:
                pass
        self._toast_job = self.root.after(4500, self._restore_status)

    def _restore_status(self) -> None:
        self._toast_job = None
        if self.db_info is not None:
            self.status_text.configure(text=t("status.ready"), fg=theme.SUCCESS)
        else:
            self.status_text.configure(text=t("status.no_db"), fg=theme.MUTED)

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def on_close(self) -> None:
        if self._toast_job is not None:
            try:
                self.root.after_cancel(self._toast_job)
            except tk.TclError:
                pass

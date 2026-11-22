"""GUI smoke test: build the real window, search through a fake backend, close.

Skipped automatically when Tk cannot open a display (headless CI).
"""

from __future__ import annotations

import time

import pytest
from conftest import load_fixture

from lcsc_core import parsers
from lcsc_core.base import SearchPage


def _tk_available() -> bool:
    try:
        import tkinter

        root = tkinter.Tk()
        root.destroy()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _tk_available(), reason="no Tk display available")


@pytest.fixture()
def app(monkeypatch, workdir):
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_CONFIG_DIR", str(workdir / "cfg"))
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_LOG_DIR", str(workdir / "logs"))
    monkeypatch.setenv("KICAD_LIBGEN_LCSC_CACHE_DIR", str(workdir / "cache"))
    from gui.app import App

    instance = App(portable=False, language="zh_CN")
    instance.window.update_db_info(None)
    yield instance
    instance.close()


class FakeService:
    """A backend-shaped stub so the window can be exercised without a network."""

    def __init__(self) -> None:
        self.language = "zh_CN"
        self.site = "szlcsc.com"
        self.currency = "¥"
        self.calls: list[str] = []

    def _products(self):
        row = load_fixture("domestic_search")["result"]["searchResult"]["productRecordList"][0]
        return [parsers.domestic_product(row)]

    def search(self, query, page=1, *, category_id=""):
        self.calls.append(query)
        products = self._products()
        return SearchPage(items=products, total=len(products), page=page, page_size=30, pages=1)

    def supports_detail(self) -> bool:
        return True

    def detail(self, product):
        enriched = product.copy()
        enriched.detail_state = "enriched"
        enriched.base.datasheet_url = "https://example.invalid/d.pdf"
        return enriched

    def enrich_safely(self, product):
        return self.detail(product), ""

    def set_language(self, language: str) -> bool:
        return False

    def configure(self, **kwargs) -> None:
        return None

    def clear_cache(self) -> int:
        return 0

    def close(self) -> None:
        return None


def pump(root, seconds: float, until=None) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        root.update()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until() if until is not None else True


def test_window_builds_with_all_tabs(app):
    window = app.window
    assert window.pages["search"] is not None
    assert window.pages["database"] is not None
    assert window.db_name_label.cget("text")
    window._select_tab("database")
    pump(app.root, 0.3)
    window._select_tab("search")
    assert window.active_tab == "search"


def test_search_populates_the_table_and_enriches_the_selection(app):
    window = app.window
    fake = FakeService()
    app.search_service = fake
    window.search_var.set("C25804")
    window.perform_search()

    assert pump(app.root, 5.0, until=lambda: bool(window.results_table.products))
    assert fake.calls == ["C25804"]
    assert window.results_table.products[0].base.distributor_product_number == "C25804"
    assert "1" in window.results_pill.cget("text")

    # selection triggers the background enrichment
    assert pump(app.root, 5.0, until=lambda: window.detail.product is not None)
    assert window.detail.product.base.datasheet_url


def test_saving_writes_a_row_and_marks_the_detail_panel(app, workdir):
    from services.database_service import DatabaseService

    path = workdir / "gui.db"
    app.open_database(path, create=True)
    window = app.window
    app.search_service = FakeService()
    window.search_var.set("C25804")
    window.perform_search()
    assert pump(app.root, 5.0, until=lambda: bool(window.results_table.products))
    assert pump(app.root, 5.0, until=lambda: window.detail.product is not None)

    window.detail.symbol_var.set("Symbol:?")
    window.detail.footprint_var.set("Footprint:?")
    window.save_detail()

    database = DatabaseService(path)
    assert database.count() == 1
    stored = database.find_by_mpn("0603WAF1002T5E")
    assert stored.base.kicad_symbol_library == "Symbol:0603WAF1002T5E"
    assert stored.base.distributor_product_number == "C25804"


def test_language_switch_relabels_and_clears_foreign_results(app):
    window = app.window
    app.search_service = FakeService()
    window.search_var.set("C25804")
    window.perform_search()
    assert pump(app.root, 5.0, until=lambda: bool(window.results_table.products))

    from lcsc_core import texts
    from lcsc_core.routing import LANGUAGES

    app.settings.language = "en_US"
    app.apply_settings(previous_language="zh_CN")
    assert texts.language() == "en_US"
    assert window.site_label.cget("text") == "lcsc.com"
    # Rows from the other storefront must not survive the switch.
    assert window.results_table.products == []
    assert window.search_button.cget("text") == "Search"
    app.settings.language = "zh_CN"
    app.apply_settings(previous_language="en_US")
    assert window.search_button.cget("text") == "搜索"
    assert dict(LANGUAGES)["zh_CN"]


class TestFontSize:
    def test_default_size_is_installed(self, app):
        from gui import theme

        assert theme.font_size() == app.settings.font_size

    def test_named_fonts_exist_and_are_not_deleted(self, app):
        from tkinter import font as tkfont

        from gui import theme

        for role in ("Base", "Small", "Tiny", "Section", "CardTitle", "PanelTitle", "Title"):
            font = tkfont.nametofont(f"LCSC.{role}", root=app.root)
            assert font.cget("family")
            assert int(font.cget("size")) > 0
        # The base role is what the window actually uses.
        assert theme.current().base == "LCSC.Base"

    def test_increasing_the_size_scales_fonts_rows_and_columns(self, app):
        from tkinter import font as tkfont

        from gui import theme
        from services import config

        window = app.window
        app.search_service = FakeService()
        window.search_var.set("C25804")
        window.perform_search()
        assert pump(app.root, 5.0, until=lambda: bool(window.results_table.products))
        before = window.results_table.tree.column("mpn", "width")

        app.settings.font_size = 16
        app.apply_settings()

        assert theme.font_size() == 16
        base = tkfont.nametofont(theme.current().base, root=app.root)
        small = tkfont.nametofont(theme.current().small, root=app.root)
        assert int(base.cget("size")) == 16
        assert int(small.cget("size")) == 15
        assert window.results_table.tree.column("mpn", "width") > before
        # The content-driven sash must still leave the results visible.
        assert window.paned.sashpos(0) > 100

        app.settings.font_size = config.DEFAULT_FONT_SIZE
        app.apply_settings()
        assert theme.font_size() == config.DEFAULT_FONT_SIZE
        assert window.results_table.tree.column("mpn", "width") == before

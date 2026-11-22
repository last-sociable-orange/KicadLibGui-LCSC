"""The KiCad database-library files must match the table they describe.

``db_setup/*.kicad_dbl`` is what makes KiCad able to browse the database, so a
drift between it and :data:`kicad_core.models.ALL_COLUMNS` would quietly break
the symbol chooser.  These tests read the shipped files and check them against the
schema definition.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_core.models import ALL_COLUMNS, PARAM_COUNT

DB_SETUP = Path(__file__).resolve().parent.parent / "db_setup"
PLATFORMS = ("windows", "linux")


def load(platform: str) -> dict:
    return json.loads((DB_SETUP / f"components_db_{platform}.kicad_dbl").read_text(encoding="utf-8"))


@pytest.fixture(params=PLATFORMS)
def document(request) -> dict:
    return load(request.param)


class TestShape:
    def test_meta_and_identity(self, document):
        assert document["meta"] == {"version": 0}
        assert document["name"]
        assert document["description"]
        assert "LCSC" in document["description"]

    def test_source_is_a_sqlite_odbc_database(self, document):
        source = document["source"]
        assert source["type"] == "odbc"
        assert source["timeout_seconds"] >= 1
        assert "components.db" in source["connection_string"]

    def test_one_library_reading_the_components_table(self, document):
        libraries = document["libraries"]
        assert len(libraries) == 1
        library = libraries[0]
        assert library["table"] == "components"
        assert library["key"] == "ID"
        assert library["symbols"] == "KicadSymbolLibrary"
        assert library["footprints"] == "KicadFootprintLibrary"

    def test_the_key_and_library_columns_are_mapped(self, document):
        columns = [field["column"] for field in document["libraries"][0]["fields"]]
        for required in ("ID", "KicadSymbolLibrary", "KicadFootprintLibrary", "Value"):
            assert required in columns


class TestFields:
    def test_every_column_is_mapped_exactly_once(self, document):
        columns = [field["column"] for field in document["libraries"][0]["fields"]]
        assert len(columns) == 80
        assert len(set(columns)) == 80
        assert set(columns) == set(ALL_COLUMNS)

    def test_field_order_is_the_one_the_previous_files_used(self, document):
        """The chooser columns must not jump around for an existing setup."""
        columns = [field["column"] for field in document["libraries"][0]["fields"]]
        assert columns[:16] == [
            "ID", "Description", "Keywords", "Value", "Manufacturer",
            "ManufacturerProductNumber", "KicadSymbolLibrary", "KicadFootprintLibrary",
            "Package", "PartStatus", "QtyAvailable", "Distributor",
            "DistributorProductNumber", "UnitPrice", "ProductUrl", "DatasheetUrl",
        ]
        assert columns[16:] == [name for index in range(1, PARAM_COUNT + 1)
                                for name in (f"Param{index:02d}", f"Value{index:02d}")]

    def test_only_value_is_written_when_a_symbol_is_placed(self, document):
        visible = [field["column"] for field in document["libraries"][0]["fields"]
                   if field["visible_on_add"]]
        assert visible == ["Value"]

    def test_keywords_is_hidden_from_the_chooser(self, document):
        fields = {field["column"]: field for field in document["libraries"][0]["fields"]}
        assert fields["Keywords"]["visible_in_chooser"] is False
        assert fields["ID"]["visible_in_chooser"] is True

    def test_display_names_are_the_column_names(self, document):
        for field in document["libraries"][0]["fields"]:
            assert field["name"] == field["column"], (
                "renaming a field also renames the symbol field it maps to"
            )

    def test_all_thirty_two_parameter_pairs_are_mapped(self, document):
        fields = [field["column"] for field in document["libraries"][0]["fields"]]
        for index in range(1, PARAM_COUNT + 1):
            assert f"Param{index:02d}" in fields
            assert f"Value{index:02d}" in fields

    def test_stock_and_currency_columns_are_available(self, document):
        fields = {field["column"] for field in document["libraries"][0]["fields"]}
        # New in this program: the storefront's stock figure is worth showing.
        assert "QtyAvailable" in fields
        assert "UnitPrice" in fields


class TestPlatforms:
    @staticmethod
    def _without_source(platform: str) -> dict:
        document = load(platform)
        document.pop("source")
        return document

    def test_both_files_describe_the_same_library(self):
        assert self._without_source("windows") == self._without_source("linux")

    def test_connection_strings_use_the_platform_driver_and_cwd(self):
        windows = load("windows")["source"]["connection_string"]
        linux = load("linux")["source"]["connection_string"]
        assert "{SQLite3 ODBC Driver}" in windows
        assert windows.startswith("Driver={SQLite3 ODBC Driver};Database=${CWD}\\")
        assert windows.endswith("components.db")

        assert linux.startswith("Driver={SQLite3};Database=${CWD}/")
        assert linux.endswith("components.db")


class TestDatabase:
    def test_the_mapped_columns_exist_in_a_new_database(self, workdir):
        """Round trip: create a database the way the app does and query columns."""
        import sqlite3

        from services.database_service import DatabaseService

        path = workdir / "components.db"
        DatabaseService(path).open_or_create(create=True)
        document = load("windows")
        columns = [field["column"] for field in document["libraries"][0]["fields"]]

        connection = sqlite3.connect(path)
        try:
            present = {row[1] for row in connection.execute('PRAGMA table_info("components")')}
            select = ", ".join(f'"{column}"' for column in columns)
            rows = connection.execute(
                f'SELECT {select} FROM "components" WHERE "ID" IS NOT NULL').fetchall()
        finally:
            connection.close()
        assert set(columns) <= present
        assert rows == []

"""Database tests: schema, upsert (no duplicates), duplicates, locking, quotes."""

from __future__ import annotations

import sqlite3

import pytest

from kicad_core.database import (
    ALL_COLUMNS,
    ProductDb,
    product_from_row,
    table_columns,
)
from kicad_core.errors import DatabaseError, DatabaseLockedError, SchemaError
from kicad_core.models import ProductInfo, ProductInfoBase
from services.database_service import DatabaseService


def make_product(mpn: str = "TEST-1", symbol: str = "Symbol:?", footprint: str = "Footprint:?") -> ProductInfo:
    product = ProductInfo(
        base=ProductInfoBase(
            id=f"Test/{mpn}",
            description="A test part",
            keywords="test",
            value=mpn,
            manufacturer="Acme",
            manufacturer_product_number=mpn,
            package="0603",
            part_status="Active",
            qty_available="7",
            distributor="LCSC",
            distributor_product_number=mpn,
            unit_price="0.10@1",
            product_url="https://example.invalid/p",
            datasheet_url="https://example.invalid/d.pdf",
        )
    )
    product.params[0] = {"param": "Resistance", "value": "10k"}
    product.with_mapping(symbol, footprint)
    return product


def make_db(path) -> ProductDb:
    return ProductDb(path, create=True)


def test_create_schema_has_all_80_columns(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        assert db.count() == 0
        columns = table_columns(db.connection)
        assert columns == list(ALL_COLUMNS)
        assert len(columns) == 80


def test_insert_and_reinsert_does_not_duplicate(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        first = db.upsert(make_product())
        assert first.action == "inserted"
        assert db.count() == 1
        second = db.upsert(make_product())
        assert second.action == "updated"
        assert second.rows_updated == 1
        assert db.count() == 1


def test_update_rewrites_mapping_and_metadata(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        db.upsert(make_product())
        changed = make_product(symbol="Symbol:TEST-1", footprint="Footprint:TEST-1")
        changed.base.description = "Changed description"
        outcome = db.upsert(changed)
        assert outcome.action == "updated"
        stored = db.find_by_mpn("TEST-1")
        assert stored is not None
        assert stored.base.description == "Changed description"
        assert stored.base.kicad_symbol_library == "Symbol:TEST-1"
        assert stored.base.kicad_footprint_library == "Footprint:TEST-1"


def test_insert_record_matches_upstream_signature(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        values = db.insert_record("components", make_product())
        assert len(values) == 80
        assert db.query_record(make_product()) == ("TEST-1",)


def test_duplicate_detection_and_update_all_duplicates(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        db.upsert(make_product())
        row = make_product().to_row()
        placeholders = ", ".join("?" for _ in ALL_COLUMNS)
        columns = ", ".join(f'"{column}"' for column in ALL_COLUMNS)
        db.connection.execute(
            f'INSERT INTO "components" ({columns}) VALUES ({placeholders})', row
        )
        assert db.count() == 2
        assert db.duplicate_mpns() == [("TEST-1", 2)]
        outcome = db.upsert(make_product(symbol="Symbol:X", footprint="Footprint:X"))
        assert outcome.action == "updated"
        assert outcome.rows_updated == 2
        assert db.count() == 2
        stored = db.find_by_mpn("TEST-1")
        assert stored.base.kicad_symbol_library == "Symbol:X"


def test_parameterized_mpn_with_quotes(workdir):
    path = workdir / "components.db"
    tricky = 'A"B\'C'
    with make_db(path) as db:
        db.upsert(make_product(tricky))
        assert db.find_by_mpn(tricky) is not None
        assert db.query_record(make_product(tricky)) == (tricky,)
        assert db.find_by_mpn("A") is None


def test_row_round_trip(workdir):
    path = workdir / "components.db"
    product = make_product()
    product.normalise_params()
    with make_db(path) as db:
        db.upsert(product)
        stored = db.find_by_mpn("TEST-1")
        assert product_from_row(stored.to_row()).to_row() == product.to_row()


def test_open_existing_database_and_schema_validation(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        db.upsert(make_product())
    info = DatabaseService(path).open_or_create(create=False)
    assert info.count == 1
    assert info.parameter_count == 1
    assert info.created is False


def test_non_database_file_raises_schema_error(workdir):
    path = workdir / "components.db"
    path.write_text("not sqlite", encoding="utf-8")
    with pytest.raises((DatabaseError, SchemaError)):
        DatabaseService(path).open_or_create(create=False)


def test_missing_table_raises_schema_error(workdir):
    path = workdir / "empty.db"
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE other (x TEXT)")
    connection.commit()
    connection.close()
    with pytest.raises(SchemaError):
        ProductDb(path, create=False)


def test_partial_schema_raises_schema_error(workdir):
    path = workdir / "partial.db"
    connection = sqlite3.connect(path)
    connection.execute('CREATE TABLE components ("ID" TEXT, "Description" TEXT)')
    connection.commit()
    connection.close()
    with pytest.raises(SchemaError) as excinfo:
        ProductDb(path, create=False)
    assert "schema" in str(excinfo.value).lower()


def test_locked_database_maps_to_friendly_error(workdir):
    path = workdir / "components.db"
    with make_db(path) as db:
        db.upsert(make_product())
    locker = sqlite3.connect(path, isolation_level=None)
    try:
        locker.execute("BEGIN EXCLUSIVE")
        with pytest.raises(DatabaseLockedError):
            DatabaseService(path).upsert(make_product("TEST-2"))
    finally:
        locker.execute("ROLLBACK")
        locker.close()


def test_upsert_requires_mapping(workdir):
    path = workdir / "components.db"
    product = make_product()
    product.base.kicad_symbol_library = ""
    product.base.kicad_footprint_library = ""
    with pytest.raises(DatabaseError) as excinfo:
        DatabaseService(path).upsert(product)
    assert "required" in str(excinfo.value).lower()

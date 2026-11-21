"""SQLite access for the KiCad ``components`` table.

The schema is byte-for-byte the one created by upstream ``kicad_cip.py``:
the same 80 columns, same names, no ``UNIQUE`` constraint and no primary
key.  The upstream ``INSERT OR REPLACE`` therefore performed a plain insert
on a fresh database and duplicated re-added parts; :meth:`ProductDb.upsert`
fixes that with an explicit ``UPDATE``-then-``INSERT`` inside
``BEGIN IMMEDIATE`` while leaving the schema untouched.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import DatabaseError, DatabaseLockedError, SchemaError
from .models import (
    ALL_COLUMNS,
    DEFAULT_PARAM,
    PARAM_COUNT,
    ProductInfo,
    ProductInfoBase,
)

TABLE_NAME = "components"

_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS "components" (
    "ID" TEXT NOT NULL,
    "Description" TEXT NOT NULL,
    "Keywords" TEXT NOT NULL,
    "Value" TEXT NOT NULL,
    "Manufacturer" TEXT NOT NULL,
    "ManufacturerProductNumber" TEXT NOT NULL,
    "Package" TEXT NOT NULL,
    "KicadSymbolLibrary" TEXT NOT NULL,
    "KicadFootprintLibrary" TEXT NOT NULL,
    "PartStatus" TEXT NOT NULL,
    "QtyAvailable" TEXT,
    "Distributor" TEXT,
    "DistributorProductNumber" TEXT,
    "UnitPrice" TEXT,
    "ProductUrl" TEXT,
    "DatasheetUrl" TEXT,
""" + ",\n".join(
    f'    "Param{index:02d}" TEXT,\n    "Value{index:02d}" TEXT'
    for index in range(1, PARAM_COUNT + 1)
) + """
)
"""

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class UpsertOutcome:
    """The result of saving one product."""

    action: str  # "inserted" or "updated"
    rows_updated: int
    values: tuple[str, ...]

    def __bool__(self) -> bool:  # pragma: no cover - convenience
        return self.action in ("inserted", "updated")


def _check_identifier(name: str) -> str:
    if not _IDENTIFIER_RE.match(name):
        raise DatabaseError(f"Invalid table name: {name!r}")
    return name


def _quote(name: str) -> str:
    return f'"{_check_identifier(name)}"'


def open_connection(path: str | Path) -> sqlite3.Connection:
    """Open a short-lived connection with the project's settings."""
    try:
        connection = sqlite3.connect(
            str(path), timeout=5, isolation_level=None
        )
    except sqlite3.OperationalError as exc:  # e.g. path is a directory
        raise DatabaseError(
            "Cannot open the database file.", details=str(exc)
        ) from exc
    connection.row_factory = sqlite3.Row
    return connection


def _translate(exc: sqlite3.OperationalError) -> DatabaseError:
    message = str(exc)
    if "locked" in message.lower() or "busy" in message.lower():
        return DatabaseLockedError(details=message)
    return DatabaseError("The database operation failed.", details=message)


def translate_error(exc: sqlite3.Error) -> DatabaseError:
    """Public wrapper so services can map SQLite errors consistently."""
    if isinstance(exc, sqlite3.OperationalError):
        return _translate(exc)
    return DatabaseError("The database operation failed.", details=str(exc))


def table_names(connection: sqlite3.Connection) -> list[str]:
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'"
    ).fetchall()
    return [row[0] for row in rows]


def table_columns(connection: sqlite3.Connection, table: str = TABLE_NAME) -> list[str]:
    rows = connection.execute(f"PRAGMA table_info({_quote(table)})").fetchall()
    return [row[1] for row in rows]


def validate_schema(connection: sqlite3.Connection, table: str = TABLE_NAME) -> list[str]:
    """Return the required columns missing from *connection* (empty = valid)."""
    if table not in table_names(connection):
        raise SchemaError(
            f"The database has no '{table}' table. "
            "Choose a KiCad LibGen database or create a new one."
        )
    present = set(table_columns(connection, table))
    return [column for column in ALL_COLUMNS if column not in present]


def ensure_schema(connection: sqlite3.Connection, table: str = TABLE_NAME) -> None:
    missing = validate_schema(connection, table)
    if missing:
        shown = ", ".join(missing[:6])
        if len(missing) > 6:
            shown += f", ... ({len(missing)} missing)"
        raise SchemaError(
            "The database schema is not compatible with KiCad LibGen.",
            details=f"Missing columns: {shown}",
        )


def product_to_row(product: ProductInfo) -> tuple[str, ...]:
    return product.to_row()


def _row_value(row: Mapping[str, Any] | Iterable[Any], key: str, index: int) -> str:
    if isinstance(row, Mapping) or hasattr(row, "keys"):
        try:
            value = row[key]  # type: ignore[index]
        except (KeyError, IndexError):
            return ""
    else:
        values = list(row)
        value = values[index] if index < len(values) else ""
    return "" if value is None else str(value)


def product_from_row(row: Mapping[str, Any] | Iterable[Any]) -> ProductInfo:
    """Convert a database row (mapping or sequence) into :class:`ProductInfo`."""
    base = ProductInfoBase(
        main_category="",
        id=_row_value(row, "ID", 0),
        description=_row_value(row, "Description", 1),
        keywords=_row_value(row, "Keywords", 2),
        value=_row_value(row, "Value", 3),
        manufacturer=_row_value(row, "Manufacturer", 4),
        manufacturer_product_number=_row_value(row, "ManufacturerProductNumber", 5),
        package=_row_value(row, "Package", 6),
        kicad_symbol_library=_row_value(row, "KicadSymbolLibrary", 7),
        kicad_footprint_library=_row_value(row, "KicadFootprintLibrary", 8),
        part_status=_row_value(row, "PartStatus", 9),
        qty_available=_row_value(row, "QtyAvailable", 10),
        distributor=_row_value(row, "Distributor", 11),
        distributor_product_number=_row_value(row, "DistributorProductNumber", 12),
        unit_price=_row_value(row, "UnitPrice", 13),
        product_url=_row_value(row, "ProductUrl", 14),
        datasheet_url=_row_value(row, "DatasheetUrl", 15),
    )
    params = [dict(DEFAULT_PARAM) for _ in range(PARAM_COUNT)]
    for index in range(PARAM_COUNT):
        name = _row_value(row, f"Param{index + 1:02d}", 16 + index * 2)
        value = _row_value(row, f"Value{index + 1:02d}", 17 + index * 2)
        params[index] = {"param": name or "-", "value": value or "-"}
    return ProductInfo(base=base, params=params)


class ProductDb:
    """Thin, synchronous wrapper around the components table.

    One instance owns one connection; the GUI services open short-lived
    instances per operation so SQLite's thread affinity never matters.
    """

    def __init__(self, db_name: str | Path = "components.db", *, create: bool = True):
        self.db_name = str(db_name)
        self._connection = open_connection(self.db_name)
        self._connection.row_factory = sqlite3.Row
        self.cur = self._connection.cursor()
        try:
            present = table_names(self._connection)
        except sqlite3.Error as exc:
            self.close()
            raise translate_error(exc) from exc
        if TABLE_NAME not in present:
            if create:
                self.create_tbl(TABLE_NAME)
            else:
                self.close()
                raise SchemaError(
                    f"The database has no '{TABLE_NAME}' table. "
                    "Choose a KiCad LibGen database or create a new one."
                )
        else:
            try:
                ensure_schema(self._connection, TABLE_NAME)
            except SchemaError:
                self.close()
                raise

    # -- lifecycle -------------------------------------------------------

    @property
    def connection(self) -> sqlite3.Connection:
        return self._connection

    def close(self) -> None:
        try:
            self._connection.close()
        except sqlite3.Error:  # pragma: no cover - best effort
            pass

    def __enter__(self) -> ProductDb:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- schema ----------------------------------------------------------

    def create_tbl(self, tbl_name: str = TABLE_NAME) -> None:
        self._connection.execute(_CREATE_TABLE_SQL)

    # -- reads -----------------------------------------------------------

    def count(self) -> int:
        row = self._connection.execute(
            f"SELECT COUNT(*) FROM {_quote(TABLE_NAME)}"
        ).fetchone()
        return int(row[0]) if row else 0

    def query_record(self, product: ProductInfo) -> tuple[str] | None:
        """Return the MPN row if *product* already exists (upstream API)."""
        row = self._connection.execute(
            f"SELECT ManufacturerProductNumber FROM {_quote(TABLE_NAME)} "
            "WHERE ManufacturerProductNumber = ?",
            (product.base.manufacturer_product_number,),
        ).fetchone()
        return tuple(row) if row is not None else None

    def find_by_mpn(self, mpn: str) -> ProductInfo | None:
        row = self._connection.execute(
            f"SELECT * FROM {_quote(TABLE_NAME)} "
            "WHERE ManufacturerProductNumber = ? ORDER BY rowid LIMIT 1",
            (mpn,),
        ).fetchone()
        return product_from_row(row) if row is not None else None

    def query_symbols(self) -> list[tuple[int, str]]:
        rows = self._connection.execute(
            f"""
            SELECT MAX(_ROWID_) AS LastID, KicadSymbolLibrary
            FROM {_quote(TABLE_NAME)}
            WHERE TRIM(COALESCE(KicadSymbolLibrary, '')) <> ''
            GROUP BY KicadSymbolLibrary
            ORDER BY LastID DESC
            """
        ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def query_footprints(self) -> list[tuple[int, str]]:
        rows = self._connection.execute(
            f"""
            SELECT MAX(_ROWID_) AS LastID, KicadFootprintLibrary
            FROM {_quote(TABLE_NAME)}
            WHERE TRIM(COALESCE(KicadFootprintLibrary, '')) <> ''
            GROUP BY KicadFootprintLibrary
            ORDER BY LastID DESC
            """
        ).fetchall()
        return [(int(row[0]), str(row[1])) for row in rows]

    def duplicate_mpns(self) -> list[tuple[str, int]]:
        rows = self._connection.execute(
            f"""
            SELECT ManufacturerProductNumber, COUNT(*) AS n
            FROM {_quote(TABLE_NAME)}
            GROUP BY ManufacturerProductNumber
            HAVING COUNT(*) > 1
            ORDER BY n DESC, ManufacturerProductNumber
            """
        ).fetchall()
        return [(str(row[0]), int(row[1])) for row in rows]

    # -- writes ----------------------------------------------------------

    def upsert(self, product: ProductInfo) -> UpsertOutcome:
        """Insert or update exactly one logical record, without duplicates."""
        mpn = product.base.manufacturer_product_number
        if not str(mpn).strip():
            raise DatabaseError(
                "Cannot save a record without a manufacturer part number."
            )
        row = product.to_row()
        if len(row) != len(ALL_COLUMNS):  # pragma: no cover - defensive
            raise DatabaseError("Product row has an unexpected column count.")

        update_columns = [column for column in ALL_COLUMNS if column != "ManufacturerProductNumber"]
        assignments = ", ".join(f"{_quote(column)} = ?" for column in update_columns)
        update_values = [
            row[ALL_COLUMNS.index(column)] for column in update_columns
        ]
        insert_sql = (
            f"INSERT INTO {_quote(TABLE_NAME)} "
            f"({', '.join(_quote(column) for column in ALL_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in ALL_COLUMNS)})"
        )

        try:
            self._connection.execute("BEGIN IMMEDIATE")
            try:
                cursor = self._connection.execute(
                    f"UPDATE {_quote(TABLE_NAME)} SET {assignments} "
                    "WHERE ManufacturerProductNumber = ?",
                    (*update_values, mpn),
                )
                changed = cursor.rowcount
                if changed == 0:
                    self._connection.execute(insert_sql, row)
                    action = "inserted"
                    changed = 1
                else:
                    action = "updated"
                self._connection.execute("COMMIT")
            except BaseException:
                self._connection.execute("ROLLBACK")
                raise
        except sqlite3.OperationalError as exc:
            raise _translate(exc) from exc
        except sqlite3.Error as exc:
            raise DatabaseError(details=str(exc)) from exc
        return UpsertOutcome(action=action, rows_updated=changed, values=row)

    def insert_record(self, tbl_name: str, product: ProductInfo) -> tuple[str, ...]:
        """Upstream-compatible insert entry point used by the CLI."""
        if tbl_name != TABLE_NAME:
            raise DatabaseError(f"Unsupported table {tbl_name!r}")
        return self.upsert(product).values

    def update_mapping(self, mpn: str, symbol: str, footprint: str) -> int:
        try:
            cursor = self._connection.execute(
                f"UPDATE {_quote(TABLE_NAME)} "
                "SET KicadSymbolLibrary = ?, KicadFootprintLibrary = ? "
                "WHERE ManufacturerProductNumber = ?",
                (symbol, footprint, mpn),
            )
        except sqlite3.OperationalError as exc:
            raise _translate(exc) from exc
        return cursor.rowcount

    def delete_record(self, mpn: str) -> int:
        try:
            cursor = self._connection.execute(
                f"DELETE FROM {_quote(TABLE_NAME)} "
                "WHERE ManufacturerProductNumber = ?",
                (mpn,),
            )
        except sqlite3.OperationalError as exc:
            raise _translate(exc) from exc
        return cursor.rowcount

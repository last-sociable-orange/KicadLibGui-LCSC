"""UI-free database operations for the KiCad ``components`` table.

Every method opens a short-lived SQLite connection (``timeout=5``) so the
GUI can call this from worker threads without ``check_same_thread`` issues
and without holding a connection while a network request runs.
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from kicad_core.database import (
    ProductDb,
    UpsertOutcome,
    translate_error,
)
from kicad_core.errors import DatabaseError
from kicad_core.models import PARAM_COUNT, ProductInfo, validate_mapping

logger = logging.getLogger(__name__)

SUMMARY_COLUMNS = (
    "ManufacturerProductNumber",
    "Manufacturer",
    "Description",
    "KicadSymbolLibrary",
    "KicadFootprintLibrary",
    "PartStatus",
    "QtyAvailable",
    "ID",
    "DistributorProductNumber",
)


@dataclass(frozen=True)
class DatabaseInfo:
    path: str
    count: int
    duplicate_count: int
    parameter_count: int
    created: bool

    @property
    def duplicate_mpns(self) -> int:
        return self.duplicate_count


@dataclass(frozen=True)
class RecordSummary:
    mpn: str
    manufacturer: str
    description: str
    symbol: str
    footprint: str
    status: str
    qty: str
    id: str
    part: str = ""


class DatabaseService:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    # -- opening ---------------------------------------------------------

    def open_or_create(self, *, create: bool = True) -> DatabaseInfo:
        created = not self.path.exists()
        if not create and created:
            raise DatabaseError(
                f"Database not found: {self.path}",
                details="Choose an existing components.db or create a new one.",
            )
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with ProductDb(self.path, create=create) as db:
                info = self._info(db, created=created)
        except DatabaseError:
            raise
        except OSError as exc:
            raise DatabaseError(
                "The database file could not be opened.", details=str(exc)
            ) from exc
        logger.info("Opened database %s (%s records)", self.path, info.count)
        return info

    def validate(self) -> list[str]:
        from kicad_core.database import open_connection, validate_schema

        try:
            connection = open_connection(self.path)
            try:
                return validate_schema(connection)
            finally:
                connection.close()
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc

    def _info(self, db: ProductDb, *, created: bool) -> DatabaseInfo:
        duplicates = db.duplicate_mpns()
        return DatabaseInfo(
            path=str(self.path),
            count=db.count(),
            duplicate_count=len(duplicates),
            parameter_count=self._parameter_count(db),
            created=created,
        )

    def _parameter_count(self, db: ProductDb) -> int:
        clauses = []
        for index in range(1, PARAM_COUNT + 1):
            clauses.append(
                f"(CASE WHEN TRIM(COALESCE(\"Param{index:02d}\", '')) "
                f"NOT IN ('', '-') THEN 1 ELSE 0 END)"
            )
        sql = (
            'SELECT COALESCE(SUM(' + " + ".join(clauses) + '), 0) FROM "components"'
        )
        row = db.connection.execute(sql).fetchone()
        return int(row[0]) if row else 0

    # -- reads -----------------------------------------------------------

    def count(self) -> int:
        return self._read(lambda db: db.count())

    def find_by_mpn(self, mpn: str) -> ProductInfo | None:
        return self._read(lambda db: db.find_by_mpn(mpn))

    def list_records(self, filter_text: str = "", limit: int = 500, offset: int = 0) -> list[RecordSummary]:
        pattern = f"%{(filter_text or '').strip()}%"

        def query(db: ProductDb) -> list[RecordSummary]:
            rows = db.connection.execute(
                """
                SELECT ManufacturerProductNumber, Manufacturer, Description,
                       KicadSymbolLibrary, KicadFootprintLibrary, PartStatus,
                       QtyAvailable, ID, DistributorProductNumber
                FROM "components"
                WHERE ? = '%%'
                   OR ManufacturerProductNumber LIKE ?
                   OR Manufacturer LIKE ?
                   OR Description LIKE ?
                   OR KicadSymbolLibrary LIKE ?
                   OR KicadFootprintLibrary LIKE ?
                ORDER BY rowid DESC
                LIMIT ? OFFSET ?
                """,
                (pattern, pattern, pattern, pattern, pattern, pattern, int(limit), int(offset)),
            ).fetchall()
            return [
                RecordSummary(
                    mpn=str(row["ManufacturerProductNumber"] or ""),
                    manufacturer=str(row["Manufacturer"] or ""),
                    description=str(row["Description"] or ""),
                    symbol=str(row["KicadSymbolLibrary"] or ""),
                    footprint=str(row["KicadFootprintLibrary"] or ""),
                    status=str(row["PartStatus"] or ""),
                    qty=str(row["QtyAvailable"] or ""),
                    id=str(row["ID"] or ""),
                    part=str(row["DistributorProductNumber"] or ""),
                )
                for row in rows
            ]

        return self._read(query)

    def distinct_symbols(self) -> list[str]:
        return self._read(lambda db: [value for _last, value in db.query_symbols()])

    def distinct_footprints(self) -> list[str]:
        return self._read(lambda db: [value for _last, value in db.query_footprints()])

    def duplicate_mpns(self) -> list[tuple[str, int]]:
        return self._read(lambda db: db.duplicate_mpns())

    # -- writes ----------------------------------------------------------

    def upsert(self, product: ProductInfo) -> UpsertOutcome:
        """Resolve ``?``, validate mappings, and insert/update one row."""
        if not product.base.manufacturer_product_number.strip():
            raise DatabaseError(
                "Cannot save a record without a manufacturer part number."
            )
        symbol, footprint = product.resolved_mapping()
        try:
            symbol, footprint = validate_mapping(symbol, footprint, required=True)
        except ValueError as exc:
            raise DatabaseError(str(exc)) from exc
        product.base.kicad_symbol_library = symbol
        product.base.kicad_footprint_library = footprint

        def write(db: ProductDb) -> UpsertOutcome:
            return db.upsert(product)

        outcome = self._write(write)
        logger.info("Database %s: %s %s", self.path, outcome.action,
                    product.base.manufacturer_product_number)
        return outcome

    def update_mapping(self, mpn: str, symbol: str, footprint: str) -> int:
        try:
            symbol, footprint = validate_mapping(symbol, footprint, required=True)
        except ValueError as exc:
            raise DatabaseError(str(exc)) from exc

        def write(db: ProductDb) -> int:
            changed = db.update_mapping(mpn, symbol, footprint)
            if changed == 0:
                raise DatabaseError(f"No record with MPN {mpn!r} exists.")
            return changed

        return self._write(write)

    def delete(self, mpn: str) -> int:
        def write(db: ProductDb) -> int:
            changed = db.delete_record(mpn)
            if changed == 0:
                raise DatabaseError(f"No record with MPN {mpn!r} exists.")
            return changed

        return self._write(write)

    # -- plumbing --------------------------------------------------------

    def _read(self, operation):
        try:
            with ProductDb(self.path, create=False) as db:
                return operation(db)
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc

    def _write(self, operation):
        try:
            with ProductDb(self.path, create=False) as db:
                return operation(db)
        except sqlite3.Error as exc:
            raise translate_error(exc) from exc

    def full_record(self, mpn: str) -> ProductInfo | None:
        """Alias used by the Database tab to load a complete record."""
        return self.find_by_mpn(mpn)

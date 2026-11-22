"""Regenerate the KiCad database-library files from the schema definition.

The `.kicad_dbl` field list is derived from :data:`kicad_core.models.ALL_COLUMNS`,
so the mapping cannot drift from the SQLite table; ``tests/test_dbl_files.py``
asserts that the two still match.

    python tools/gen_dbl.py

Both platforms share everything except the ODBC connection string.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from kicad_core.models import ALL_COLUMNS, PARAM_COUNT  # noqa: E402

OUT = ROOT / "db_setup"

#: Columns hidden from the symbol chooser (long free text).
_HIDDEN_IN_CHOOSER = {"Keywords"}

#: The only field KiCad writes into the symbol when it is placed.
_VISIBLE_ON_ADD = {"Value"}

#: Display names stay equal to the column names on purpose: in KiCad the field name
#: is also the symbol field it maps to, so keeping them identical keeps an existing
#: library working and the mapping unambiguous.
_DISPLAY_NAMES: dict[str, str] = {}

#: Field order as the previous files had it, with ``QtyAvailable`` (new: the stock
#: the storefront reported) inserted after ``PartStatus`` where it belongs.  Keeping
#: the old order means the chooser columns appear where the user expects them.
_HEAD_ORDER = (
    "ID",
    "Description",
    "Keywords",
    "Value",
    "Manufacturer",
    "ManufacturerProductNumber",
    "KicadSymbolLibrary",
    "KicadFootprintLibrary",
    "Package",
    "PartStatus",
    "QtyAvailable",
    "Distributor",
    "DistributorProductNumber",
    "UnitPrice",
    "ProductUrl",
    "DatasheetUrl",
)


def field_order() -> tuple[str, ...]:
    """The head columns followed by the 32 parameter/value pairs."""
    tail = tuple(
        name
        for index in range(1, PARAM_COUNT + 1)
        for name in (f"Param{index:02d}", f"Value{index:02d}")
    )
    order = _HEAD_ORDER + tail
    missing = set(ALL_COLUMNS) - set(order)
    extra = set(order) - set(ALL_COLUMNS)
    if missing or extra:
        raise SystemExit(
            "field order no longer matches kicad_core.models.ALL_COLUMNS "
            f"(missing={sorted(missing)}, extra={sorted(extra)})"
        )
    return order

#: The connection strings are kept exactly as the user already had them: a path
#: relative to the current directory, so an existing KiCad setup keeps working
#: without editing.  Change them here (and rerun) if the database moves.
CONNECTION_STRINGS = {
    "windows": (
        "Driver={SQLite3 ODBC Driver};"
        "Database=${CWD}\\..\\kicad_lib_szlcsc\\components.db"
    ),
    "linux": "Driver={SQLite3};Database=${CWD}/../kicad_lib/components.db",
}


def fields() -> list[dict[str, object]]:
    return [
        {
            "column": column,
            "name": _DISPLAY_NAMES.get(column, column),
            "visible_on_add": column in _VISIBLE_ON_ADD,
            "visible_in_chooser": column not in _HIDDEN_IN_CHOOSER,
        }
        for column in field_order()
    ]


def document(platform: str) -> dict[str, object]:
    return {
        "meta": {"version": 0},
        "name": "LCSC Components",
        "description": (
            "LCSC component database written by KiCad LibGen LCSC "
            "(szlcsc.com / lcsc.com)"
        ),
        "source": {
            "type": "odbc",
            "dsn": "",
            "username": "",
            "password": "",
            "timeout_seconds": 2,
            "connection_string": CONNECTION_STRINGS[platform],
        },
        "libraries": [
            {
                "name": "components",
                "table": "components",
                "key": "ID",
                "symbols": "KicadSymbolLibrary",
                "footprints": "KicadFootprintLibrary",
                "fields": fields(),
            }
        ],
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for platform, filename in (
        ("windows", "components_db_windows.kicad_dbl"),
        ("linux", "components_db_linux.kicad_dbl"),
    ):
        path = OUT / filename
        path.write_text(
            json.dumps(document(platform), indent=4, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"wrote {path.relative_to(ROOT)} ({len(fields())} fields)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

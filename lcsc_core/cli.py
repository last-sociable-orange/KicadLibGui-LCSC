"""Headless entry point: search the selected storefront and show the 80-column row.

This is the Phase 1 acceptance tool and a handy way to check a part without the
GUI:

    python -m lcsc_core.cli C25804 --lang zh_CN
    python -m lcsc_core.cli "10k 0603 resistor" --lang en_US --limit 3
    python -m lcsc_core.cli C2040 --db components.db      # also insert/update
"""

from __future__ import annotations

import argparse
import json
import sys

from kicad_core.errors import AppError
from kicad_core.models import ALL_COLUMNS, ProductInfo
from services.database_service import DatabaseService

from .routing import create_backend, normalise_language, site_for
from .session import DEFAULT_MIN_INTERVAL, HttpSession


def _rowdict(product: ProductInfo) -> dict[str, str]:
    return product.row_dict()


def _print_product(product: ProductInfo, *, verbose: bool) -> None:
    row = _rowdict(product)
    print(f"--- {row['DistributorProductNumber']}  {row['ManufacturerProductNumber']}  "
          f"[{row['Manufacturer']}]")
    print(f"    description : {row['Description']}")
    print(f"    value       : {row['Value']}")
    print(f"    package     : {row['Package']}   status: {row['PartStatus']}   qty: {row['QtyAvailable']}")
    print(f"    price       : {row['UnitPrice'] or '-'}")
    print(f"    product     : {row['ProductUrl']}")
    print(f"    datasheet   : {row['DatasheetUrl'] or '-'}")
    print(f"    id          : {row['ID']}")
    params = [(p["param"], p["value"]) for p in product.params if p["param"] not in ("-", "")]
    print(f"    parameters  : {len(params)} stored, {len(product.source_parameters)} reported")
    for name, value in params:
        print(f"        {name} = {value}")
    if verbose:
        print("    full row:")
        for column in ALL_COLUMNS:
            print(f"        {column:28} {row[column]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lcsc_core.cli",
        description="Search LCSC/szlcsc and print the record written to components.db",
    )
    parser.add_argument("query", help="part number or keywords")
    parser.add_argument("--lang", default="zh_CN", choices=("zh_CN", "en_US"),
                        help="zh_CN searches szlcsc.com, en_US searches lcsc.com")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--limit", type=int, default=1,
                        help="how many results to print")
    parser.add_argument("--category", default="", help="category id to narrow to")
    parser.add_argument("--no-detail", action="store_true",
                        help="skip the detail request (search row only)")
    parser.add_argument("--db", default=None, help="insert/update the record into this database")
    parser.add_argument("--json", action="store_true", help="print full rows as JSON")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    language = normalise_language(args.lang)
    session = HttpSession(min_interval=DEFAULT_MIN_INTERVAL)
    backend = create_backend(language, session=session)
    print(f"{site_for(language)}  ({language}, {backend.currency})")

    try:
        page = backend.search(args.query, max(1, args.page), category_id=args.category)
    except AppError as exc:
        print(f"search failed: {exc}", file=sys.stderr)
        if exc.details:
            print(f"  {exc.details}", file=sys.stderr)
        return 1

    print(f"{page.total} matches, page {page.page}/{page.pages}"
          + (f", category {page.category_id}" if page.category_id else ""))
    if page.note:
        print(f"note: {page.note}")
    if page.categories:
        shown = ", ".join(f"{item.name}({item.count})" for item in page.categories[:6])
        print(f"categories: {shown}")
    if not page.items:
        print("no results")
        return 0

    database = DatabaseService(args.db) if args.db else None
    if database is not None:
        info = database.open_or_create(create=True)
        print(f"database: {info.path} ({info.count} records)")

    exit_code = 0
    for product in page.items[: max(1, args.limit)]:
        if not args.no_detail:
            try:
                product = backend.detail(product)
            except AppError as exc:
                print(f"detail failed for {product.base.distributor_product_number}: {exc}",
                      file=sys.stderr)
                if exc.details:
                    print(f"  {exc.details}", file=sys.stderr)
                exit_code = 1
        if args.json:
            print(json.dumps(_rowdict(product), ensure_ascii=False, indent=2))
        else:
            _print_product(product, verbose=args.verbose)
        if database is not None:
            try:
                product.with_mapping("Symbol:?", "Footprint:?")
                outcome = database.upsert(product)
            except AppError as exc:
                print(f"database write failed: {exc}", file=sys.stderr)
                exit_code = 1
            else:
                print(f"    {outcome.action} in database")
    backend.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

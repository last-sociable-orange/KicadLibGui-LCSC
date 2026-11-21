"""C-number CSV validation and the batch import engine."""

from __future__ import annotations

import threading

import pytest
from conftest import load_fixture

from kicad_core.errors import BatchError
from kicad_core.models import ProductInfo, ProductInfoBase
from lcsc_core import parsers
from lcsc_core.base import SearchPage
from services.batch_service import (
    STATUS_CANCELLED,
    STATUS_INSERTED,
    STATUS_SKIPPED_NO_RESULT,
    STATUS_UPDATED,
    BatchOptions,
    BatchRunner,
    validate_csv,
)
from services.database_service import DatabaseService

HEADER = "lcsc_part_number,kicad_symbol_library,kicad_footprint_library"


def write_csv(path, rows, header=HEADER):
    path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
    return path


def make_product(part="C25804", mpn="0603WAF1002T5E") -> ProductInfo:
    product = ProductInfo(base=ProductInfoBase(
        id=f"贴片电阻/{mpn}", description="厚膜电阻", value="10K",
        manufacturer="UNI-ROYAL(厚声)", manufacturer_product_number=mpn, package="0603",
        part_status="Active", qty_available="1000", distributor="LCSC",
        distributor_product_number=part, unit_price="¥0.01@1",
        product_url="https://item.szlcsc.com/26547.html",
    ))
    product.params[0] = {"param": "阻值", "value": "10kΩ"}
    return product


class FakeSearchService:
    """Stands in for SearchService: one part number resolves, one does not."""

    def __init__(self, known: dict[str, ProductInfo], *, enrich: bool = True):
        self.known = known
        self.enrich = enrich
        self.calls: list[tuple[str, int]] = []

    def search(self, query, page=1, *, category_id=""):
        self.calls.append((query, page))
        product = self.known.get(query)
        return SearchPage(items=[product] if product else [], total=1 if product else 0,
                          page=page, page_size=30, pages=1)

    def enrich_safely(self, product):
        if not self.enrich:
            return product, "details unavailable"
        enriched = product.copy()
        enriched.base.datasheet_url = "https://example.invalid/d.pdf"
        enriched.detail_state = "enriched"
        return enriched, ""


class TestValidateCsv:
    def test_good_file(self, workdir):
        path = write_csv(workdir / "parts.csv",
                         ["C25804,Symbol:?,Footprint:R_0603_1608Metric"])
        validation = validate_csv(path)
        assert validation.valid
        assert validation.total == 1
        assert validation.rows[0].part == "C25804"
        assert validation.rows[0].symbol == "Symbol:?"

    def test_legacy_header_is_accepted(self, workdir):
        path = write_csv(
            workdir / "parts.csv", ["C25804,Symbol:?,Footprint:F"],
            header="manufacturer_product_number,kicad_symbol_library,kicad_footprint_library")
        assert validate_csv(path).valid

    def test_a_manufacturer_part_number_is_rejected(self, workdir):
        path = write_csv(workdir / "parts.csv", ["LM324N,Symbol:?,Footprint:F"])
        validation = validate_csv(path)
        assert not validation.valid
        assert "not an LCSC part number" in validation.errors[0].message

    def test_lowercase_part_number_is_normalised(self, workdir):
        path = write_csv(workdir / "parts.csv", ["c25804,Symbol:?,Footprint:F"])
        validation = validate_csv(path)
        assert validation.valid and validation.rows[0].part == "C25804"

    def test_duplicate_row_is_a_warning(self, workdir):
        path = write_csv(workdir / "parts.csv",
                         ["C25804,S, F".replace(" ", ""), "C25804,X,Y"])
        validation = validate_csv(path)
        assert validation.valid
        assert validation.warnings and "Duplicate" in validation.warnings[0].message

    def test_wrong_column_count_is_an_error(self, workdir):
        path = write_csv(workdir / "parts.csv", ["C25804,Symbol:?"])
        assert not validate_csv(path).valid

    def test_unexpected_header_is_an_error(self, workdir):
        path = write_csv(workdir / "parts.csv", ["C25804,A,B"], header="mpn,symbol,footprint")
        validation = validate_csv(path)
        assert not validation.valid
        assert "Unexpected header" in validation.errors[0].message

    def test_empty_file_is_an_error(self, workdir):
        path = workdir / "parts.csv"
        path.write_text("", encoding="utf-8")
        assert not validate_csv(path).valid

    def test_missing_library_is_an_error(self, workdir):
        path = write_csv(workdir / "parts.csv", ["C25804,,Footprint:F"])
        assert not validate_csv(path).valid


class TestBatchRunner:
    def _database(self, workdir):
        service = DatabaseService(workdir / "components.db")
        service.open_or_create(create=True)
        return service

    def _validation(self, workdir, rows):
        return validate_csv(write_csv(workdir / "parts.csv", rows))

    def test_inserts_then_skips_duplicates(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product()})
        validation = self._validation(workdir, ["C25804,Symbol:?,Footprint:F"])
        runner = BatchRunner(search, database, BatchOptions(delay_ms=0))

        first = runner.run(validation)
        assert first.counts[STATUS_INSERTED] == 1
        stored = database.find_by_mpn("0603WAF1002T5E")
        assert stored.base.kicad_symbol_library == "Symbol:0603WAF1002T5E"
        assert stored.base.datasheet_url == "https://example.invalid/d.pdf"

        second = runner.run(validation)
        assert second.count("skipped_duplicates") == 1
        assert database.count() == 1

    def test_overwrite_existing_updates_the_row(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product()})
        validation = self._validation(workdir, ["C25804,Symbol:?,Footprint:F"])
        BatchRunner(search, database, BatchOptions(delay_ms=0)).run(validation)

        changed = self._validation(workdir, ["C25804,Symbol:Other,Footprint:Other"])
        options = BatchOptions(delay_ms=0, overwrite_existing=True, skip_duplicates=False)
        summary = BatchRunner(search, database, options).run(changed)
        assert summary.counts[STATUS_UPDATED] == 1
        stored = database.find_by_mpn("0603WAF1002T5E")
        assert stored.base.kicad_symbol_library == "Symbol:Other"
        assert stored.base.kicad_footprint_library == "Footprint:Other"

    def test_unknown_part_is_skipped(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({})
        validation = self._validation(workdir, ["C99999,Symbol:?,Footprint:F"])
        summary = BatchRunner(search, database, BatchOptions(delay_ms=0)).run(validation)
        assert summary.count("skipped_no_result") == 1
        assert database.count() == 0

    def test_failed_detail_still_saves_the_row(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product()}, enrich=False)
        validation = self._validation(workdir, ["C25804,Symbol:?,Footprint:F"])
        summary = BatchRunner(search, database, BatchOptions(delay_ms=0)).run(validation)
        assert summary.counts[STATUS_INSERTED] == 1
        assert database.count() == 1

    def test_log_file_matches_the_upstream_format(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product()})
        validation = self._validation(workdir, ["C25804,Symbol:?,Footprint:F"])
        summary = BatchRunner(search, database, BatchOptions(delay_ms=0)).run(validation)
        assert summary.log_path is not None
        text = (workdir / summary.log_path.split("\\")[-1]).read_text(encoding="utf-8")
        assert text.startswith("C25804: ")
        assert "==> inserted" in text

    def test_progress_is_reported_for_every_row(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product()})
        validation = self._validation(workdir, [
            "C25804,Symbol:?,Footprint:F",
            "C99999,Symbol:?,Footprint:F",
        ])
        seen: list[tuple[int, str]] = []
        runner = BatchRunner(search, database, BatchOptions(delay_ms=0),
                             on_progress=lambda p: seen.append((p.index, p.status)))
        runner.run(validation)
        assert [index for index, _ in seen] == [1, 2]
        assert seen[1][1] == STATUS_SKIPPED_NO_RESULT

    def test_cancellation_stops_the_run(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({"C25804": make_product(), "C25805": make_product("C25805")})
        validation = self._validation(workdir, [
            "C25804,Symbol:?,Footprint:F",
            "C25805,Symbol:?,Footprint:F",
        ])
        cancel = threading.Event()
        cancel.set()
        summary = BatchRunner(search, database, BatchOptions(delay_ms=0),
                              cancel_event=cancel).run(validation)
        assert summary.counts[STATUS_CANCELLED] == 2
        assert database.count() == 0
        assert search.calls == []

    def test_invalid_csv_raises_before_any_request(self, workdir):
        database = self._database(workdir)
        search = FakeSearchService({})
        validation = validate_csv(write_csv(workdir / "parts.csv", ["LM324N,A,B"]))
        with pytest.raises(BatchError):
            BatchRunner(search, database, BatchOptions(delay_ms=0)).run(validation)
        assert search.calls == []

    def test_ambiguous_part_number_is_skipped(self, workdir):
        database = self._database(workdir)
        first = make_product()
        second = make_product(mpn="OTHER-MPN")

        class Ambiguous(FakeSearchService):
            def search(self, query, page=1, *, category_id=""):
                self.calls.append((query, page))
                return SearchPage(items=[first, second], total=2, page=page, page_size=30,
                                  pages=1)

        summary = BatchRunner(Ambiguous({}), database, BatchOptions(delay_ms=0)).run(
            self._validation(workdir, ["C25804,Symbol:?,Footprint:F"]))
        assert summary.count("skipped_ambiguous") == 1
        assert database.count() == 0

    def test_search_error_is_reported_per_row(self, workdir):
        database = self._database(workdir)

        class Broken(FakeSearchService):
            def search(self, query, page=1, *, category_id=""):
                raise BatchError("the store refused the request")

        summary = BatchRunner(Broken({}), database,
                              BatchOptions(delay_ms=0)).run(
            self._validation(workdir, ["C25804,Symbol:?,Footprint:F"]))
        assert summary.count("errors") == 1


class TestParsedRowRoundTrip:
    def test_a_parsed_domestic_row_can_be_written_and_read_back(self, workdir):
        row = load_fixture("domestic_search")["result"]["searchResult"]["productRecordList"][0]
        product = parsers.domestic_product(row)
        product.with_mapping("Symbol:?", "Footprint:?")
        database = DatabaseService(workdir / "components.db")
        database.open_or_create(create=True)
        assert database.upsert(product).action == "inserted"
        stored = database.find_by_mpn(product.mpn)
        assert stored.base.distributor_product_number == "C25804"
        assert stored.base.unit_price.startswith("¥")
        assert stored.base.kicad_symbol_library == f"Symbol:{product.mpn}"

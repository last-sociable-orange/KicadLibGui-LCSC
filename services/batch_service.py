"""CSV validation and the batch import engine.

The CSV is keyed by LCSC part number: one cheap, unambiguous lookup per row.

```csv
lcsc_part_number,kicad_symbol_library,kicad_footprint_library
C25804,Symbol:?,Footprint:R_0603_1608Metric
```

The engine is UI-free: it searches, enriches, upserts, paces, backs off on 429
and honours cancellation, reporting progress through a callback.  The GUI runs it
on a worker thread.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from kicad_core.errors import (
    AppError,
    BatchError,
    DatabaseError,
    RateLimitError,
    ServerError,
)
from lcsc_core.text import part_number
from services.database_service import DatabaseService
from services.search_service import SearchService

logger = logging.getLogger(__name__)

EXPECTED_HEADER = ("lcsc_part_number", "kicad_symbol_library", "kicad_footprint_library")
#: Accepted so an existing KiCad LibGen BOM CSV still opens; the values must
#: nevertheless be LCSC part numbers.
LEGACY_HEADERS = (
    ("manufacturer_product_number", "kicad_symbol_library", "kicad_footprint_library"),
)

STATUS_INSERTED = "inserted"
STATUS_UPDATED = "updated"
STATUS_SKIPPED_DUPLICATE = "skipped-duplicate"
STATUS_SKIPPED_NO_RESULT = "skipped-no-result"
STATUS_SKIPPED_AMBIGUOUS = "skipped-ambiguous"
STATUS_ERROR = "error"
STATUS_CANCELLED = "cancelled"

COUNT_KEYS = (
    "inserted",
    "updated",
    "skipped_duplicates",
    "skipped_no_result",
    "skipped_ambiguous",
    "errors",
    "cancelled",
)


@dataclass(frozen=True)
class CsvIssue:
    line: int
    message: str
    severity: str = "error"


@dataclass(frozen=True)
class CsvRow:
    line: int
    part: str
    symbol: str
    footprint: str


@dataclass
class CsvValidation:
    path: Path
    header: tuple[str, ...] = ()
    rows: list[CsvRow] = field(default_factory=list)
    errors: list[CsvIssue] = field(default_factory=list)
    warnings: list[CsvIssue] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors and bool(self.rows)

    @property
    def total(self) -> int:
        return len(self.rows)


@dataclass
class BatchOptions:
    skip_duplicates: bool = True
    overwrite_existing: bool = False
    delay_ms: int = 350
    timeout: int = 20
    max_retries: int = 2

    def normalise(self) -> BatchOptions:
        self.delay_ms = max(0, min(10000, int(self.delay_ms)))
        self.timeout = max(5, min(300, int(self.timeout)))
        self.max_retries = max(0, min(5, int(self.max_retries)))
        return self


@dataclass(frozen=True)
class BatchLogEntry:
    line: int
    part: str
    record: str
    status: str
    message: str = ""

    def format(self) -> str:
        return f"{self.part}: {self.record} ==> {self.status}"


@dataclass
class BatchSummary:
    total: int
    counts: dict[str, int]
    entries: list[BatchLogEntry] = field(default_factory=list)
    log_path: str | None = None
    aborted: bool = False
    abort_reason: str = ""

    @property
    def processed(self) -> int:
        return sum(self.counts.values())

    def count(self, key: str) -> int:
        return self.counts.get(key, 0)


@dataclass(frozen=True)
class BatchProgress:
    index: int
    total: int
    row: CsvRow
    status: str
    counts: dict[str, int]


class _BatchAbort(Exception):
    """Internal signal: stop the run, preserve completed rows."""

    def __init__(self, message: str, *, cancelled: bool = False):
        super().__init__(message)
        self.message = message
        self.cancelled = cancelled


def _is_blank(row: list[str]) -> bool:
    return not any((cell or "").strip() for cell in row)


def _decode(path: Path) -> str:
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise BatchError(f"Could not read {path.name}.", details=str(exc)) from exc
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise BatchError("The CSV file is not valid UTF-8.", details=str(exc)) from exc


def validate_csv(path: str | Path) -> CsvValidation:
    """Read and validate the 3-column LCSC CSV."""
    csv_path = Path(path)
    validation = CsvValidation(path=csv_path)
    text = _decode(csv_path)

    try:
        reader = csv.reader(io.StringIO(text, newline=""), strict=True)
        all_rows: list[tuple[int, list[str]]] = []
        for row in reader:
            if _is_blank(row):
                continue
            all_rows.append((reader.line_num, row))
    except csv.Error as exc:
        validation.errors.append(CsvIssue(0, f"Malformed CSV: {exc}"))
        return validation

    if not all_rows:
        validation.errors.append(CsvIssue(0, "The CSV file is empty."))
        return validation

    header_line, header = all_rows[0]
    validation.header = tuple((cell or "").strip() for cell in header)
    normalised = tuple(cell.lower() for cell in validation.header)
    if len(header) != 3:
        validation.errors.append(CsvIssue(
            header_line,
            "The header must have exactly 3 columns: " + ", ".join(EXPECTED_HEADER)))
        return validation
    if normalised not in (EXPECTED_HEADER, *LEGACY_HEADERS):
        validation.errors.append(CsvIssue(
            header_line, "Unexpected header. Expected: " + ", ".join(EXPECTED_HEADER)))
        return validation

    seen: dict[str, int] = {}
    for line_number, row in all_rows[1:]:
        if len(row) != 3:
            validation.errors.append(CsvIssue(
                line_number,
                f"Expected 3 fields, found {len(row)}. Quote fields that contain commas."))
            continue
        raw_part, symbol, footprint = ((cell or "").strip() for cell in row)
        part = part_number(raw_part)
        if not raw_part:
            validation.errors.append(CsvIssue(line_number, "Missing LCSC part number."))
            continue
        if not part:
            validation.errors.append(CsvIssue(
                line_number,
                f"'{raw_part}' is not an LCSC part number (C followed by digits)."))
            continue
        if not symbol:
            validation.errors.append(CsvIssue(line_number, "Missing symbol library."))
        if not footprint:
            validation.errors.append(CsvIssue(line_number, "Missing footprint library."))
        if any("\n" in value or "\r" in value for value in (symbol, footprint)):
            validation.errors.append(
                CsvIssue(line_number, "Library names cannot contain line breaks."))
        if part in seen:
            validation.warnings.append(CsvIssue(
                line_number,
                f"Duplicate part number in CSV (first on line {seen[part]}).",
                severity="warning"))
        else:
            seen[part] = line_number
        validation.rows.append(CsvRow(line_number, part, symbol, footprint))

    if not validation.rows and not validation.errors:
        validation.errors.append(CsvIssue(0, "The CSV file has no data rows."))
    return validation


def _timestamp() -> str:
    return datetime.now().strftime("%y-%m-%d-%H-%M-%S")


def write_batch_log(entries: list[BatchLogEntry], csv_path: str | Path,
                    log_dir: str | Path | None = None) -> str:
    """Write the upstream-compatible batch log next to the CSV."""
    source = Path(csv_path)
    directory = Path(log_dir) if log_dir else source.parent
    directory.mkdir(parents=True, exist_ok=True)
    base = source.stem
    destination = directory / f"{base}-{_timestamp()}.log"
    counter = 1
    while destination.exists():
        destination = directory / f"{base}-{_timestamp()}-{counter}.log"
        counter += 1
    with destination.open("w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(entry.format() + "\n")
    return str(destination)


class BatchRunner:
    """Import a validated CSV, one LCSC part number at a time."""

    def __init__(
        self,
        search_service: SearchService,
        database_service: DatabaseService,
        options: BatchOptions | None = None,
        *,
        cancel_event=None,
        on_progress: Callable[[BatchProgress], None] | None = None,
        log_dir: str | Path | None = None,
        wait: Callable[[float], bool] | None = None,
    ):
        self.search = search_service
        self.database = database_service
        self.options = (options or BatchOptions()).normalise()
        self.cancel_event = cancel_event
        self.on_progress = on_progress
        self.log_dir = log_dir
        self._wait = wait or self._default_wait

    # -- cancellation helpers -------------------------------------------

    def _cancelled(self) -> bool:
        return bool(self.cancel_event and self.cancel_event.is_set())

    def _default_wait(self, seconds: float) -> bool:
        """Sleep, returning ``True`` when cancellation was requested."""
        if seconds <= 0:
            return self._cancelled()
        if self.cancel_event is not None:
            return bool(self.cancel_event.wait(seconds))
        time.sleep(seconds)
        return False

    # -- main ------------------------------------------------------------

    def run(self, validation: CsvValidation) -> BatchSummary:
        if validation.errors:
            raise BatchError(validation.errors[0].message,
                             details="Fix the CSV errors before importing.")
        if not validation.rows:
            raise BatchError("The CSV file has no data rows.")

        counts = {key: 0 for key in COUNT_KEYS}
        entries: list[BatchLogEntry] = []
        total = len(validation.rows)
        aborted = False
        abort_reason = ""

        for index, row in enumerate(validation.rows, start=1):
            if self._cancelled():
                counts["cancelled"] += 1
                entries.append(BatchLogEntry(row.line, row.part, "", STATUS_CANCELLED,
                                             "Cancelled before request"))
                self._report(index, total, row, STATUS_CANCELLED, counts)
                continue
            try:
                status, abort_reason = self._process_row(row, counts, entries)
            except _BatchAbort as exc:
                if exc.cancelled:
                    counts["cancelled"] += 1
                    entries.append(BatchLogEntry(row.line, row.part, "", STATUS_CANCELLED,
                                                 exc.message))
                    self._report(index, total, row, STATUS_CANCELLED, counts)
                else:
                    counts["errors"] += 1
                    entries.append(BatchLogEntry(row.line, row.part, exc.message, STATUS_ERROR,
                                                 exc.message))
                    self._report(index, total, row, STATUS_ERROR, counts)
                aborted = True
                abort_reason = exc.message
                self._cancel_remaining(validation.rows[index:], counts, entries, exc.message)
                break
            except AppError as exc:
                counts["errors"] += 1
                entries.append(BatchLogEntry(row.line, row.part, str(exc), STATUS_ERROR,
                                             str(exc)))
                logger.warning("Batch row %s (%s) failed: %s", row.line, row.part, exc)
                self._report(index, total, row, STATUS_ERROR, counts)
                self._pause()
                continue
            except Exception as exc:  # pragma: no cover - defensive
                counts["errors"] += 1
                entries.append(BatchLogEntry(row.line, row.part, str(exc), STATUS_ERROR,
                                             "Unexpected error"))
                logger.exception("Unexpected batch failure for %s", row.part)
                self._report(index, total, row, STATUS_ERROR, counts)
                self._pause()
                continue

            self._report(index, total, row, status, counts)
            if abort_reason:
                aborted = True
                self._cancel_remaining(validation.rows[index:], counts, entries, abort_reason)
                break
            self._pause()

        log_path = None
        if entries:
            try:
                log_path = write_batch_log(entries, validation.path, self.log_dir)
            except OSError as exc:
                logger.error("Could not write the batch log: %s", exc)

        return BatchSummary(total=total, counts=counts, entries=entries, log_path=log_path,
                            aborted=aborted, abort_reason=abort_reason)

    def _process_row(self, row: CsvRow, counts: dict[str, int],
                     entries: list[BatchLogEntry]) -> tuple[str, str]:
        page = self._search_with_retries(row)
        exact = [item for item in page.items
                 if item.base.distributor_product_number == row.part]
        if not exact:
            counts["skipped_no_result"] += 1
            entries.append(BatchLogEntry(row.line, row.part, "", STATUS_SKIPPED_NO_RESULT,
                                         "No search result for this part number"))
            return STATUS_SKIPPED_NO_RESULT, ""
        if len(exact) > 1:
            counts["skipped_ambiguous"] += 1
            entries.append(BatchLogEntry(row.line, row.part, "", STATUS_SKIPPED_AMBIGUOUS,
                                         f"{len(exact)} records share this part number"))
            return STATUS_SKIPPED_AMBIGUOUS, ""

        product = exact[0]
        existing = self.database.find_by_mpn(product.mpn)
        if existing is not None and not self.options.overwrite_existing:
            if self.options.skip_duplicates:
                counts["skipped_duplicates"] += 1
                entries.append(BatchLogEntry(row.line, row.part, "", STATUS_SKIPPED_DUPLICATE,
                                             "Already in the database"))
                return STATUS_SKIPPED_DUPLICATE, ""
            raise DatabaseError(
                f"{row.part} already exists. Enable 'Overwrite existing records' or "
                "'Skip records that already exist'.")

        # Enrich from the storefront; a failed detail call must not lose the row.
        enriched, warning = self.search.enrich_safely(product)
        if warning:
            logger.info("Batch row %s saved from search data: %s", row.part, warning)
        enriched.base.kicad_symbol_library = row.symbol
        enriched.base.kicad_footprint_library = row.footprint
        outcome = self.database.upsert(enriched)
        if outcome.action == STATUS_UPDATED:
            counts["updated"] += 1
            status = STATUS_UPDATED
        else:
            counts["inserted"] += 1
            status = STATUS_INSERTED
        entries.append(BatchLogEntry(row.line, row.part, str(outcome.values), status))
        return status, ""

    def _search_with_retries(self, row: CsvRow):
        attempt = 0
        while True:
            try:
                page = self.search.search(row.part, 1)
            except (RateLimitError, ServerError) as exc:
                if attempt >= self.options.max_retries:
                    raise _BatchAbort(
                        "LCSC is rate limiting or unavailable while importing "
                        f"{row.part}. Wait a few minutes and retry the remaining rows."
                    ) from exc
                delay = float(2 ** (attempt + 1))
                retry_after = getattr(exc, "retry_after", None)
                if retry_after:
                    delay = max(delay, float(min(int(retry_after), 60)))
                logger.warning("Rate limited on %s; waiting %.0fs before retry",
                               row.part, delay)
                if self._wait(delay) or self._cancelled():
                    raise _BatchAbort("Cancelled while waiting for the rate limit.",
                                      cancelled=True) from None
                attempt += 1
                continue
            if self._cancelled():
                raise _BatchAbort("Cancelled after the in-flight request.", cancelled=True)
            return page

    def _pause(self) -> None:
        if self.options.delay_ms:
            self._wait(self.options.delay_ms / 1000)

    def _cancel_remaining(self, remaining: list[CsvRow], counts: dict[str, int],
                          entries: list[BatchLogEntry], reason: str) -> None:
        for row in remaining:
            counts["cancelled"] += 1
            entries.append(BatchLogEntry(row.line, row.part, "", STATUS_CANCELLED, reason))

    def _report(self, index: int, total: int, row: CsvRow, status: str,
                counts: dict[str, int]) -> None:
        if self.on_progress is None:
            return
        try:
            self.on_progress(BatchProgress(index, total, row, status, dict(counts)))
        except Exception:  # pragma: no cover - a bad callback must not fail a run
            logger.exception("Batch progress callback failed")

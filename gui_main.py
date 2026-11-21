"""KiCad LibGen LCSC entry point.

Flags:
  --version            print the version and exit
  --self-test          run offline import/database/parser checks and exit
  --smoke-test         build the real window, pump the loop, then close (CI)
  --portable           keep settings, cache and logs beside the executable
  --db PATH            open this database at startup
  --lang zh_CN|en_US   override the stored language for this run
  --log-level          override the configured log level
"""

from __future__ import annotations

import argparse
import json
import logging
import multiprocessing
import os
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import version

logger = logging.getLogger(__name__)


def _emit(message: str) -> None:
    """Print when stdout exists (PyInstaller ``--windowed`` sets it to None)."""
    stream = sys.stdout
    if stream is not None:
        try:
            print(message, file=stream, flush=True)
        except Exception:
            pass


def _make_temp_dir(prefix: str) -> Path:
    """Create a writable temp directory, falling back to the CWD.

    ``tempfile.mkdtemp`` creates mode-0700 directories; on some locked-down
    Windows setups (sandboxes, service accounts, CI runners) that ACL makes the
    directory unwritable.  A plain ``mkdir`` inherits the parent ACL instead.
    """
    import uuid

    for parent in (None, os.getcwd()):
        base = Path(parent) if parent else Path(tempfile_dir())
        path = base / f"{prefix}{uuid.uuid4().hex[:10]}"
        try:
            path.mkdir(parents=False, exist_ok=False)
            probe = path / ".write-probe"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            return path
        except OSError as exc:
            logger.debug("Temp dir %r unusable: %s", path, exc)
    raise RuntimeError("No writable temporary directory is available.")


def tempfile_dir() -> str:
    import tempfile

    return tempfile.gettempdir()


def _cleanup_temp_dir(path: Path) -> None:
    import shutil

    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # pragma: no cover
        pass


@contextmanager
def _temp_directory(prefix: str):
    path = _make_temp_dir(prefix)
    try:
        yield str(path)
    finally:
        _cleanup_temp_dir(path)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="KiCadLibGenLCSC",
        description=f"{version.APP_NAME} - {version.APP_SUBTITLE}",
    )
    parser.add_argument("--version", action="store_true", help="print the version and exit")
    parser.add_argument("--self-test", action="store_true",
                        help="run offline import/database/parser checks and exit")
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--portable", action="store_true",
                        help="use a data folder beside the executable")
    parser.add_argument("--db", type=str, default=None, help="database to open at startup")
    parser.add_argument("--lang", type=str, default=None, choices=("zh_CN", "en_US"),
                        help="override the stored language for this run")
    parser.add_argument("--log-level", type=str, default=None,
                        choices=("DEBUG", "INFO", "WARNING", "ERROR"))
    return parser


def fixtures_dir() -> Path:
    """Recorded storefront responses, when running from a source checkout."""
    return Path(__file__).resolve().parent / "tests" / "fixtures"


def self_test() -> int:
    """Offline checks suitable for CI and PyInstaller smoke tests."""
    started = time.time()
    try:
        import kicad_core
        from gui import app as gui_app  # noqa: F401  (import must work offline)
        from lcsc_core import parsers, routing, texts
        from lcsc_core.session import HttpSession  # noqa: F401
        from services.batch_service import validate_csv
        from services.config import Settings  # noqa: F401
        from services.database_service import DatabaseService

        with _temp_directory("lcsc-libgen-selftest-") as temp:
            root = Path(temp)
            service = DatabaseService(root / "components.db")
            info = service.open_or_create(create=True)
            if info.count != 0:
                raise AssertionError("new database should be empty")

            product = kicad_core.ProductInfo(
                base=kicad_core.ProductInfoBase(
                    id="Resistors/TEST-1",
                    description="Self-test part",
                    keywords="self test",
                    value="10K",
                    manufacturer="Acme",
                    manufacturer_product_number="TEST-1",
                    package="0603",
                    part_status="Active",
                    qty_available="42",
                    distributor="LCSC",
                    distributor_product_number="C25804",
                    unit_price="¥0.0101@1",
                    product_url="https://item.szlcsc.com/26547.html",
                    datasheet_url="https://example.invalid/datasheet.pdf",
                )
            )
            product.params[0] = {"param": "阻值", "value": "10kΩ"}
            product.with_mapping("Symbol:?", "Footprint:?")
            if service.upsert(product).action != "inserted":
                raise AssertionError("first upsert was not an insert")
            if service.upsert(product).action != "updated":
                raise AssertionError("second upsert was not an update")
            if service.count() != 1:
                raise AssertionError("upsert duplicated a record")
            stored = service.find_by_mpn("TEST-1")
            if stored is None or stored.base.kicad_symbol_library != "Symbol:TEST-1":
                raise AssertionError("mapping placeholder was not resolved")
            if stored.base.distributor_product_number != "C25804":
                raise AssertionError("distributor part number was not stored")

            csv_path = root / "parts.csv"
            csv_path.write_text(
                "lcsc_part_number,kicad_symbol_library,kicad_footprint_library\n"
                "C25804,Symbol:?,Footprint:R_0603_1608Metric\n",
                encoding="utf-8-sig",
            )
            validation = validate_csv(csv_path)
            if not validation.valid or validation.total != 1:
                raise AssertionError("CSV validation failed")
            if validation.rows[0].part != "C25804":
                raise AssertionError("C-number was not preserved")

            bad_csv = root / "bad.csv"
            bad_csv.write_text(
                "lcsc_part_number,kicad_symbol_library,kicad_footprint_library\n"
                "LM324N,Symbol:X,Footprint:Y\n", encoding="utf-8")
            if validate_csv(bad_csv).valid:
                raise AssertionError("an MPN row must be rejected")

            # Every translation key must format in both languages.
            for key in texts.all_keys():
                for language in ("zh_CN", "en_US"):
                    texts.set_language(language)
                    texts.t(key)

            if not issubclass(routing.create_backend("en_US").__class__,
                              routing.Backend):
                raise AssertionError("en_US backend is not a Backend")
            domestic = routing.create_backend("zh_CN")
            international = routing.create_backend("en_US")
            try:
                if domestic.site != "szlcsc.com" or international.site != "lcsc.com":
                    raise AssertionError("language routing is wrong")
            finally:
                domestic.close()
                international.close()

            fixtures = fixtures_dir()
            if fixtures.exists():
                domestic_payload = json.loads(
                    (fixtures / "domestic_search.json").read_text(encoding="utf-8"))
                row = domestic_payload["result"]["searchResult"]["productRecordList"][0]
                parsed = parsers.domestic_product(row)
                if parsed is None or parsed.base.value != "10K":
                    raise AssertionError("domestic parser self-test failed")
                intl_payload = json.loads(
                    (fixtures / "international_list.json").read_text(encoding="utf-8"))
                intl = parsers.international_product(intl_payload["result"]["dataList"][0])
                if intl is None or not intl.base.unit_price.startswith("US$"):
                    raise AssertionError("international parser self-test failed")
    except BaseException as exc:
        logger.exception("Self-test failed")
        _emit(f"SELF-TEST FAILED: {exc}")
        return 1

    elapsed = time.time() - started
    _emit(f"SELF-TEST OK ({elapsed:.2f}s)")
    return 0


def smoke_test() -> int:
    """Construct the real window, pump the loop for 2 s, then close."""
    return _gui_lifetime_test(2000)


def _gui_lifetime_test(milliseconds: int) -> int:
    from gui.app import App

    with _temp_directory("lcsc-libgen-smoke-") as temp:
        os.environ["KICAD_LIBGEN_LCSC_CONFIG_DIR"] = temp
        os.environ["KICAD_LIBGEN_LCSC_LOG_DIR"] = str(Path(temp) / "logs")
        os.environ["KICAD_LIBGEN_LCSC_CACHE_DIR"] = str(Path(temp) / "cache")
        try:
            app = App(portable=False)
        except Exception as exc:  # pragma: no cover - display failures
            _emit(f"GUI-TEST FAILED: {exc}")
            logger.exception("GUI test could not construct the window")
            return 1
        app.root.after(milliseconds, app.close)
        try:
            app.run()
        except Exception as exc:  # pragma: no cover
            _emit(f"GUI-TEST FAILED: {exc}")
            logger.exception("GUI test failed")
            return 1
    _emit("GUI-TEST OK")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.version:
        _emit(f"{version.APP_NAME} {version.__version__}")
        return 0
    if args.self_test:
        return self_test()
    if args.smoke_test:
        return smoke_test()

    from gui.app import App

    try:
        app = App(portable=args.portable or None, database_path=args.db,
                  language=args.lang)
    except Exception as exc:  # pragma: no cover - startup failures
        logger.exception("Could not start the GUI")
        _emit(f"Could not start {version.APP_NAME}: {exc}")
        try:
            from tkinter import messagebox

            messagebox.showerror(
                version.APP_NAME,
                f"Could not start {version.APP_NAME}:\n\n{exc}",
            )
        except Exception:
            pass
        return 1
    if args.log_level:
        logging.getLogger().setLevel(args.log_level)
    return app.run()


if __name__ == "__main__":  # pragma: no cover - executable entry point
    multiprocessing.freeze_support()
    raise SystemExit(main())

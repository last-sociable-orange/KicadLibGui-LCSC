"""Application composition root: settings, services, Tk root, main window."""

from __future__ import annotations

import logging
import time
import tkinter as tk
import traceback
from pathlib import Path

import version
from gui import assets, theme
from gui.main_window import MainWindow
from gui.worker import TaskRunner
from kicad_core.errors import AppError
from lcsc_core import texts
from lcsc_core.routing import site_for
from services import config
from services.config import Settings, sync_folder_name
from services.database_service import DatabaseInfo, DatabaseService
from services.logging_setup import setup_logging
from services.search_service import SearchService

logger = logging.getLogger(__name__)


class App:
    def __init__(self, *, portable: bool | None = None, database_path: str | None = None,
                 language: str | None = None):
        theme.enable_dpi_awareness()

        self.settings = Settings.load(portable=portable)
        if database_path:
            self.settings.database_path = str(Path(database_path).expanduser())
        if language:
            self.settings.language = language
        self.settings.normalise()
        texts.set_language(self.settings.language)
        setup_logging(self.settings.log_level, portable=self.settings.portable)
        logger.info("Starting %s %s (%s)", version.APP_NAME, version.__version__,
                    self.settings.language)

        self.root = self._create_window()
        self.theme = theme.current()
        self.root.geometry("1180x860")
        self.root.minsize(940, 640)
        self._center_window()
        self._set_icon()

        self.search_service = SearchService(
            self.settings.language,
            timeout=self.settings.http_timeout,
            min_interval=self.settings.request_interval,
            cache_ttl=self.settings.cache_ttl,
            cache_directory=str(config.cache_dir(self.settings.portable)),
        )
        self.database: DatabaseService | None = None
        self.db_info: DatabaseInfo | None = None

        self.runner = TaskRunner(self.root, max_workers=3)
        self.root.report_callback_exception = self._report_callback_exception

        self.window = MainWindow(self.root, self)
        self.root.protocol("WM_DELETE_WINDOW", self.close)

        self.root.deiconify()
        self._update_title()
        self.root.after(80, self._startup)

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    @staticmethod
    def _create_window() -> tk.Tk:
        """Create the Tk root, retrying transient Tcl/Tk library I/O errors."""
        last_error: BaseException | None = None
        for attempt in range(4):
            root = None
            try:
                root = tk.Tk()
                root.withdraw()
                theme.apply(root)
                return root
            except tk.TclError as exc:
                last_error = exc
                logger.warning("Tk initialisation attempt %s failed: %s", attempt + 1, exc)
                if root is not None:
                    try:
                        root.destroy()
                    except tk.TclError:
                        pass
                time.sleep(0.25)
        assert last_error is not None
        raise last_error

    def _center_window(self) -> None:
        self.root.update_idletasks()
        try:
            width, height = 1180, 860
            screen_w = self.root.winfo_screenwidth()
            screen_h = self.root.winfo_screenheight()
            width = min(width, max(940, screen_w - 80))
            height = min(height, max(640, screen_h - 120))
            x = max(0, (screen_w - width) // 2)
            y = max(0, (screen_h - height) // 2 - 20)
            self.root.geometry(f"{width}x{height}+{x}+{y}")
        except tk.TclError:  # pragma: no cover
            pass

    def _set_icon(self) -> None:
        icon = assets.load_app_icon(self.root)
        if icon is not None:
            try:
                self.root.iconphoto(True, icon)
                self._icon_image = icon
            except tk.TclError:  # pragma: no cover
                pass

    def _update_title(self) -> None:
        name = Path(self.db_info.path).name if self.db_info else ""
        subtitle = t_subtitle()
        self.root.title(f"{version.APP_NAME} - {name}" if name
                        else f"{version.APP_NAME} - {subtitle}")

    def _startup(self) -> None:
        path = self.settings.database_path
        if path and Path(path).exists():
            try:
                self.open_database(path, create=False, remember=False)
            except AppError as exc:
                logger.warning("Could not reopen last database: %s", exc)
                self.window.show_banner(
                    f"Could not reopen {Path(path).name}: {exc}",
                    getattr(exc, "details", ""),
                    "warning",
                )
            else:
                sync = sync_folder_name(path)
                if sync:
                    self.window.show_banner(
                        f"This database is inside {sync}. Sync clients can lock or "
                        "corrupt SQLite files; consider moving it to a local folder "
                        "such as ~/KiCadLibGenLCSC.",
                        "",
                        "warning",
                    )
        else:
            self.window.update_db_info(None)

    # ------------------------------------------------------------------
    # Database
    # ------------------------------------------------------------------

    def open_database(self, path: str | Path, *, create: bool = False,
                      remember: bool = True) -> DatabaseInfo:
        service = DatabaseService(path)
        info = service.open_or_create(create=create)
        self.database = service
        self.db_info = info
        if remember:
            self.settings.add_recent(info.path)
            self.settings.save()
            self.window._refresh_recent_menu()
        self.window.update_db_info(info)
        self._update_title()
        logger.info("Database ready: %s (%s records)", info.path, info.count)
        return info

    def refresh_db_info(self) -> DatabaseInfo | None:
        if self.database is None:
            return None
        try:
            info = self.database.open_or_create(create=False)
        except AppError as exc:
            self.window.show_banner(str(exc), getattr(exc, "details", ""), "error")
            return None
        self.db_info = info
        return info

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def apply_settings(self, *, previous_language: str | None = None) -> None:
        self.settings.save()
        logging.getLogger().setLevel(
            getattr(logging, self.settings.log_level.upper(), logging.INFO))

        language_changed = (previous_language is not None
                            and previous_language != self.settings.language)
        if language_changed:
            texts.set_language(self.settings.language)
            self.search_service.set_language(self.settings.language)
            self.search_service.configure(timeout=self.settings.http_timeout,
                                          min_interval=self.settings.request_interval,
                                          cache_ttl=self.settings.cache_ttl)
            self.window.apply_language()
            logger.info("Switched to %s (%s)", self.settings.language,
                        site_for(self.settings.language))
        else:
            self.search_service.configure(timeout=self.settings.http_timeout,
                                          min_interval=self.settings.request_interval,
                                          cache_ttl=self.settings.cache_ttl)

        database_path = self.settings.database_path
        if database_path and Path(database_path).exists():
            if self.database is None or str(self.database.path) != str(Path(database_path)):
                try:
                    self.open_database(database_path, create=False, remember=False)
                except AppError as exc:
                    self.window.show_banner(str(exc), getattr(exc, "details", ""), "warning")
        self._update_title()
        logger.info("Settings applied")

    # ------------------------------------------------------------------
    # UI helpers used by tabs/dialogs
    # ------------------------------------------------------------------

    def show_banner(self, message: str, details: str = "", kind: str = "error") -> None:
        self.window.show_banner(message, details, kind)

    def toast(self, message: str) -> None:
        self.window.toast(message)

    # ------------------------------------------------------------------
    # Shutdown / errors
    # ------------------------------------------------------------------

    def _report_callback_exception(self, exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logger.error("Unhandled GUI exception:\n%s", text)
        try:
            self.window.show_banner(f"Unexpected error: {exc_value}", text, "error")
        except Exception:  # pragma: no cover - last resort
            pass

    def close(self) -> None:
        logger.info("Closing %s", version.APP_NAME)
        try:
            self.window.on_close()
        except Exception:  # pragma: no cover
            pass
        for shutdown in (
            lambda: self.runner.shutdown(),
            lambda: self.search_service.close(),
            lambda: self.root.destroy(),
        ):
            try:
                shutdown()
            except Exception:  # pragma: no cover
                pass

    def run(self) -> int:
        try:
            self.root.mainloop()
        finally:
            try:
                self.runner.shutdown()
            except Exception:  # pragma: no cover
                pass
            try:
                self.search_service.close()
            except Exception:  # pragma: no cover
                pass
        return 0


def t_subtitle() -> str:
    from lcsc_core.texts import t

    return t("app.subtitle")

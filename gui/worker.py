"""Background job runner for Tk.

Tk is not thread-safe.  Workers therefore never touch widgets: they put results,
errors and progress objects on a :class:`queue.Queue`, and the Tk main loop
drains it every 50 ms on the main thread.

Two kinds of job exist:

* a **foreground** job (:meth:`TaskRunner.submit`) -- search, batch import.  Only
  one may run at a time and it owns the busy flag;
* a **background** job (:meth:`TaskRunner.submit_background`) -- detail
  enrichment for the selected row.  It must not block a new search and never
  disturbs the busy flag; the shared HTTP session serialises the requests anyway.
"""

from __future__ import annotations

import logging
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)

POLL_MS = 50


class TaskRunner:
    def __init__(self, root: tk.Misc, max_workers: int = 3, poll_ms: int = POLL_MS):
        self.root = root
        self.poll_ms = poll_ms
        self._executor = ThreadPoolExecutor(max_workers=max_workers,
                                            thread_name_prefix="lcsc-libgen")
        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._busy = False
        self._active_name = ""
        self._cancel_event = threading.Event()
        self._after_id: str | None = root.after(poll_ms, self._drain)
        self._closing = False
        self._progress_handler: Callable[[Any], None] | None = None

    # -- state -----------------------------------------------------------

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def active_name(self) -> str:
        return self._active_name

    @property
    def cancel_event(self) -> threading.Event:
        return self._cancel_event

    def request_cancel(self) -> None:
        self._cancel_event.set()

    # -- submission ------------------------------------------------------

    def submit(self, fn: Callable[[], Any], on_success: Callable[[Any], None],
               on_error: Callable[[BaseException], None], *, name: str = "task") -> bool:
        """Start the one foreground job.  Returns ``False`` when already busy."""
        if self._closing:
            return False
        if self._busy:
            logger.warning("TaskRunner already busy with %s", self._active_name)
            return False
        self._busy = True
        self._active_name = name
        self._cancel_event.clear()
        self._executor.submit(self._run, fn, on_success, on_error, True)
        return True

    def submit_background(self, fn: Callable[[], Any], on_success: Callable[[Any], None],
                          on_error: Callable[[BaseException], None],
                          *, name: str = "background") -> bool:
        """Start a job that never touches the busy flag (detail enrichment)."""
        if self._closing:
            return False
        self._executor.submit(self._run, fn, on_success, on_error, False)
        return True

    def post_progress(self, payload: Any) -> None:
        """Called from a worker thread; delivered to the progress handler."""
        self._queue.put(("progress", payload))

    def _run(self, fn: Callable[[], Any], on_success: Callable[[Any], None],
             on_error: Callable[[BaseException], None], foreground: bool) -> None:
        try:
            result = fn()
        except BaseException as exc:  # reported to the UI
            self._queue.put(("error", (on_error, exc, foreground)))
            logger.debug("Background job failed: %s", exc)
        else:
            self._queue.put(("success", (on_success, result, foreground)))

    # -- main-thread draining -------------------------------------------

    def _drain(self) -> None:
        if self._closing:
            return
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "progress":
                    handler = self._progress_handler
                    if handler is not None:
                        try:
                            handler(payload)
                        except Exception:
                            logger.exception("Progress handler failed")
                    continue
                callback, result, foreground = payload
                if foreground:
                    self._busy = False
                    self._active_name = ""
                try:
                    callback(result)
                except Exception:
                    logger.exception("Task %s callback failed", kind)
        except queue.Empty:
            pass
        self._after_id = self.root.after(self.poll_ms, self._drain)

    # -- progress --------------------------------------------------------

    def set_progress_handler(self, handler: Callable[[Any], None] | None) -> None:
        self._progress_handler = handler

    # -- lifecycle -------------------------------------------------------

    def shutdown(self) -> None:
        self._closing = True
        self._cancel_event.set()
        if self._after_id is not None:
            try:
                self.root.after_cancel(self._after_id)
            except tk.TclError:
                pass
            self._after_id = None
        self._executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self):  # pragma: no cover - best effort
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass

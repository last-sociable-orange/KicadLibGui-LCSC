"""Batch import dialog: validate a C-number CSV, preview it, then import it."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from gui import theme
from gui.widgets import Pill, primary_button, secondary_button, set_enabled
from lcsc_core.texts import t, tn
from services.batch_service import (
    BatchOptions,
    BatchProgress,
    BatchRunner,
    BatchSummary,
    CsvValidation,
    validate_csv,
)

logger = logging.getLogger(__name__)


class BatchDialog(tk.Toplevel):
    def __init__(self, parent: tk.Misc, app, *, on_finished=None):
        super().__init__(parent)
        self.app = app
        self._on_finished = on_finished
        self.validation: CsvValidation | None = None
        self.summary: BatchSummary | None = None
        self._running = False

        self.title(t("batch.title"))
        self.configure(bg=theme.BG)
        self.transient(parent.winfo_toplevel())
        self.geometry("880x620")
        self.minsize(720, 520)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.bind("<Escape>", lambda _event: self._close())

        self._build()
        try:
            self.grab_set()
        except tk.TclError:  # pragma: no cover
            pass

    # -- layout ----------------------------------------------------------

    def _build(self) -> None:
        outer = tk.Frame(self, bg=theme.CARD, padx=20, pady=16)
        outer.pack(fill="both", expand=True, padx=14, pady=14)

        header = tk.Frame(outer, bg=theme.CARD)
        header.pack(fill="x")
        tk.Label(header, text=t("batch.title"), bg=theme.CARD, fg=theme.TEXT,
                 font=theme.current().title).pack(side="left")
        self.rows_pill = Pill(header, "", fg=theme.TEXT_SOFT)
        self.rows_pill.pack(side="left", padx=(10, 0))

        tk.Label(outer, text=t("batch.expected_header"), bg=theme.CARD, fg=theme.MUTED,
                 font=theme.current().tiny, wraplength=780, justify="left",
                 anchor="w").pack(anchor="w", pady=(6, 10))

        picker = tk.Frame(outer, bg=theme.CARD)
        picker.pack(fill="x")
        self.csv_var = tk.StringVar()
        self.csv_entry = ttk.Entry(picker, textvariable=self.csv_var,
                                   font=theme.current().base)
        self.csv_entry.pack(side="left", fill="x", expand=True)
        self.choose_button = secondary_button(picker, t("batch.choose"), self._choose_file)
        self.choose_button.pack(side="left", padx=(8, 0))

        self.status_label = tk.Label(outer, text="", bg=theme.CARD, fg=theme.MUTED,
                                     font=theme.current().small, anchor="w",
                                     wraplength=780, justify="left")
        self.status_label.pack(fill="x", pady=(8, 6))

        table_card = tk.Frame(outer, bg=theme.CARD, highlightbackground=theme.BORDER,
                              highlightthickness=1)
        table_card.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            table_card, columns=("line", "part", "symbol", "footprint", "issue"),
            show="headings", selectmode="browse")
        for key, title, width, stretch in (
            ("line", "#", 44, False),
            ("part", t("col.part"), 110, False),
            ("symbol", t("detail.symbol"), 200, False),
            ("footprint", t("detail.footprint"), 200, False),
            ("issue", t("col.status"), 260, True),
        ):
            self.tree.heading(key, text=title, anchor="w")
            self.tree.column(key, width=width, minwidth=40, anchor="w", stretch=stretch)
        scroll = ttk.Scrollbar(table_card, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.tag_configure("error", foreground=theme.DANGER)
        self.tree.tag_configure("warning", foreground=theme.WARNING)
        self.tree.tag_configure("ok", foreground=theme.TEXT)

        options = tk.Frame(outer, bg=theme.CARD)
        options.pack(fill="x", pady=(10, 0))
        self.skip_var = tk.BooleanVar(value=True)
        self.overwrite_var = tk.BooleanVar(value=False)
        self.skip_check = ttk.Checkbutton(options, text=t("batch.skip_duplicates"),
                                          variable=self.skip_var)
        self.skip_check.pack(side="left")
        self.overwrite_check = ttk.Checkbutton(options, text=t("batch.overwrite"),
                                               variable=self.overwrite_var)
        self.overwrite_check.pack(side="left", padx=(14, 0))

        progress_row = tk.Frame(outer, bg=theme.CARD)
        progress_row.pack(fill="x", pady=(10, 0))
        self.progress = ttk.Progressbar(progress_row, mode="determinate",
                                        style="Accent.Horizontal.TProgressbar")
        self.progress.pack(side="left", fill="x", expand=True)
        self.progress_label = tk.Label(progress_row, text="", bg=theme.CARD, fg=theme.MUTED,
                                       font=theme.current().small, width=12)
        self.progress_label.pack(side="left", padx=(10, 0))

        buttons = tk.Frame(outer, bg=theme.CARD)
        buttons.pack(fill="x", pady=(12, 0))
        self.close_button = secondary_button(buttons, t("common.close"), self._close)
        self.close_button.pack(side="right")
        self.start_button = primary_button(buttons, t("batch.start"), self._start)
        self.start_button.pack(side="right", padx=(0, 8))
        self.stop_button = secondary_button(buttons, t("batch.stop"), self._stop)
        self.stop_button.pack(side="right", padx=(0, 8))
        self.stop_button.configure(state="disabled")

    # -- validation ------------------------------------------------------

    def _choose_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self, title=t("batch.title"),
            filetypes=[("CSV", "*.csv"), ("All files", "*.*")])
        if path:
            self.csv_var.set(path)
            self._validate(path)

    def _validate(self, path: str) -> None:
        try:
            self.validation = validate_csv(path)
        except Exception as exc:
            self.validation = None
            self.status_label.configure(text=str(exc), fg=theme.DANGER)
            return
        self.tree.delete(*self.tree.get_children())
        validation = self.validation
        issues_by_line: dict[int, list] = {}
        for issue in [*validation.errors, *validation.warnings]:
            issues_by_line.setdefault(issue.line, []).append(issue)

        preview: list[tuple[int, tuple, str]] = []
        for row in validation.rows:
            issues = issues_by_line.pop(row.line, [])
            tag = "error" if any(i.severity == "error" for i in issues) else (
                "warning" if issues else "ok")
            message = "; ".join(i.message for i in issues)
            preview.append((row.line, (row.line, row.part, row.symbol or "-",
                                       row.footprint or "-", message or "ok"), tag))
        for line, issues in issues_by_line.items():
            preview.append((line, (line, "-", "-", "-",
                                   "; ".join(i.message for i in issues)), "error"))
        for _line, values, tag in sorted(preview, key=lambda item: item[0]):
            self.tree.insert("", "end", values=values, tags=(tag,))

        self.rows_pill.set(tn("batch.rows", validation.total))
        if validation.errors:
            first = validation.errors[0]
            prefix = f"line {first.line}: " if first.line else ""
            self.status_label.configure(text=f"{prefix}{first.message}", fg=theme.DANGER)
        elif validation.warnings:
            self.status_label.configure(
                text="; ".join(issue.message for issue in validation.warnings[:3]),
                fg=theme.WARNING)
        else:
            self.status_label.configure(text=tn("batch.rows", validation.total),
                                        fg=theme.SUCCESS)
        set_enabled(self.start_button, validation.valid, bg=theme.ACCENT)
        self.progress.configure(maximum=max(1, validation.total), value=0)
        self.progress_label.configure(text="")

    # -- run -------------------------------------------------------------

    def _start(self) -> None:
        if self.validation is None or not self.validation.valid:
            messagebox.showinfo(t("batch.title"), t("batch.no_rows"), parent=self)
            return
        if self.app.database is None:
            return
        if self.app.runner.busy:
            self.app.toast(t("status.wait"))
            return

        options = BatchOptions(
            skip_duplicates=bool(self.skip_var.get()),
            overwrite_existing=bool(self.overwrite_var.get()),
            delay_ms=self.app.settings.batch_delay_ms,
            timeout=self.app.settings.http_timeout,
        )
        runner = BatchRunner(
            self.app.search_service,
            self.app.database,
            options,
            cancel_event=self.app.runner.cancel_event,
            on_progress=self.app.runner.post_progress,
            log_dir=Path(self.validation.path).parent,
        )
        self._running = True
        self._set_running(True)
        self.progress.configure(maximum=max(1, self.validation.total), value=0)
        self.app.runner.set_progress_handler(self._on_progress)
        submitted = self.app.runner.submit(
            lambda: runner.run(self.validation),
            self._finished,
            self._failed,
            name="batch",
        )
        if not submitted:
            self._running = False
            self._set_running(False)
            self.app.runner.set_progress_handler(None)

    def _stop(self) -> None:
        self.app.runner.request_cancel()
        self.status_label.configure(text=t("batch.stop") + "…", fg=theme.WARNING)

    def _set_running(self, running: bool) -> None:
        state = "disabled" if running else "normal"
        self.start_button.configure(state=state)
        self.choose_button.configure(state=state)
        self.skip_check.configure(state=state)
        self.overwrite_check.configure(state=state)
        self.stop_button.configure(state="normal" if running else "disabled")

    def _on_progress(self, progress: BatchProgress) -> None:
        if not isinstance(progress, BatchProgress):
            return
        self.progress.configure(value=progress.index)
        self.progress_label.configure(
            text=t("batch.progress", done=progress.index, total=progress.total))
        self.status_label.configure(text=f"{progress.row.part}: {progress.status}",
                                    fg=theme.TEXT_SOFT)

    def _finished(self, summary: BatchSummary) -> None:
        self._running = False
        self._set_running(False)
        self.app.runner.set_progress_handler(None)
        self.summary = summary
        counts = summary.counts
        skipped = counts["skipped_duplicates"] + counts["skipped_no_result"] + counts[
            "skipped_ambiguous"]
        self.status_label.configure(
            text=t("batch.summary", inserted=counts["inserted"], updated=counts["updated"],
                   skipped=skipped, errors=counts["errors"]),
            fg=theme.DANGER if counts["errors"] else theme.SUCCESS)
        if summary.log_path:
            self.progress_label.configure(text="")
            self.status_label.configure(
                text=self.status_label.cget("text") + "   "
                + t("batch.log_written", path=Path(summary.log_path).name),
                fg=theme.DANGER if counts["errors"] else theme.SUCCESS)
        if self._on_finished is not None:
            self._on_finished(summary)

    def _failed(self, exc: BaseException) -> None:
        self._running = False
        self._set_running(False)
        self.app.runner.set_progress_handler(None)
        logger.info("Batch import failed: %s", exc)
        self.status_label.configure(text=str(exc), fg=theme.DANGER)

    # -- lifecycle -------------------------------------------------------

    def _close(self) -> None:
        if self._running:
            if not messagebox.askyesno(t("batch.title"), t("batch.stop") + "?",
                                       parent=self):
                return
            self.app.runner.request_cancel()
        self.app.runner.set_progress_handler(None)
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.destroy()

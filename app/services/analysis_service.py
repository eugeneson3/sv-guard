"""Runs svguard in a long-lived worker process, off the UI thread.

Why a process and not a thread: pyslang keeps the GIL while it compiles (measured: the
main thread stalls for ~80 ms at a time), so a thread would still freeze the editor.
A separate process also means a crash inside the parser cannot take the IDE down; the
worker is simply restarted on the next request.

Requests coalesce: saving again while a check runs queues one more run with the latest
request, never a backlog.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Callable
from concurrent.futures import Executor, Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from svguard.runner import AnalysisError, AnalysisReport, AnalysisRequest, analyze, warm_up

ExecutorFactory = Callable[[], Executor]


def process_executor() -> Executor:
    # spawn everywhere: no forked Qt state in the child, same behavior on Windows and Linux
    return ProcessPoolExecutor(max_workers=1, mp_context=multiprocessing.get_context("spawn"))


@dataclass(frozen=True)
class AnalysisOutcome:
    request: AnalysisRequest
    report: AnalysisReport | None = None
    error: str | None = None  # set instead of report when the run failed


class AnalysisService(QObject):
    started = Signal(object)  # AnalysisRequest
    finished = Signal(object)  # AnalysisOutcome
    _done = Signal(object, object)  # (request, future), emitted from the executor's thread

    default_executor_factory: ExecutorFactory = staticmethod(process_executor)

    def __init__(self, executor_factory: ExecutorFactory | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._factory = executor_factory or type(self).default_executor_factory
        self._executor: Executor | None = None
        self._running: AnalysisRequest | None = None
        self._pending: AnalysisRequest | None = None
        self._done.connect(self._on_done)  # queued to the GUI thread

    @property
    def busy(self) -> bool:
        return self._running is not None

    def warm_up(self) -> None:
        """Start the worker and import pyslang now, so the first save is checked quickly."""
        if self._executor is None:
            self._executor_or_new().submit(warm_up)

    def request(self, request: AnalysisRequest) -> None:
        if self._running is not None:
            self._pending = request  # only the newest matters
            return
        self._submit(request)

    def shutdown(self) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None
        self._pending = None

    def _executor_or_new(self) -> Executor:
        if self._executor is None:
            self._executor = self._factory()
        return self._executor

    def _submit(self, request: AnalysisRequest) -> None:
        self._running = request
        self.started.emit(request)
        try:
            future = self._executor_or_new().submit(analyze, request)
        except (BrokenProcessPool, RuntimeError) as exc:  # the worker died earlier
            self._executor = None
            self._finish(AnalysisOutcome(request, error=f"analysis worker unavailable: {exc}"))
            return
        future.add_done_callback(lambda f, r=request: self._done.emit(r, f))

    def _on_done(self, request: AnalysisRequest, future: Future) -> None:
        try:
            outcome = AnalysisOutcome(request, report=future.result())
        except AnalysisError as exc:
            outcome = AnalysisOutcome(request, error=str(exc))
        except BrokenProcessPool:
            self._executor = None  # restarted on the next request
            outcome = AnalysisOutcome(request, error="the analysis worker crashed; it will restart on the next save")
        except Exception as exc:  # noqa: BLE001 - report anything the parser throws
            outcome = AnalysisOutcome(request, error=f"{type(exc).__name__}: {exc}")
        self._finish(outcome)

    def _finish(self, outcome: AnalysisOutcome) -> None:
        self._running = None
        self.finished.emit(outcome)
        if self._pending is not None:
            pending, self._pending = self._pending, None
            self._submit(pending)

"""Runs page operations off the Qt UI thread and reports completion or cancellation
back through Qt signals."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from threading import Event, Thread
from typing import Any

from PySide6.QtCore import QObject, Property, QRunnable, QThreadPool, Qt, Signal, Slot


@dataclass(frozen=True, slots=True)
class TaskIdentity:
    generation: int
    profile_id: str
    page_id: str
    operation: str


@dataclass(frozen=True, slots=True)
class TaskFailure:
    code: str
    summary: str
    error_type: str


class _TaskSignals(QObject):
    completed = Signal(object, object, bool, object)


class _PageTask(QRunnable):
    def __init__(self, identity: TaskIdentity, operation: Callable[[], Any]) -> None:
        super().__init__()
        self.identity = identity
        self.operation = operation
        self.signals = _TaskSignals()
        self._cancelled = Event()

    def cancel(self) -> None:
        self._cancelled.set()

    @Slot()
    def run(self) -> None:
        if self._cancelled.is_set():
            return
        completed = Event()
        outcome: list[tuple[bool, object]] = []
        operation = self.operation

        def execute() -> None:
            try:
                outcome.append((True, operation()))
            except Exception as error:
                error_type = type(error).__name__
                if not error_type.isidentifier():
                    error_type = "Exception"
                outcome.append(
                    (
                        False,
                        TaskFailure(
                            code="page_reader_failed",
                            summary="The local page evidence could not be loaded.",
                            error_type=error_type,
                        ),
                    )
                )
            finally:
                completed.set()

        Thread(target=execute, name="sgfx-page-reader", daemon=True).start()
        while not completed.wait(0.025):
            if self._cancelled.is_set():
                return
        if self._cancelled.is_set() or not outcome:
            return
        succeeded, payload = outcome[0]
        self.signals.completed.emit(self, self.identity, succeeded, payload)


class PageTaskCoordinator(QObject):
    task_succeeded = Signal(object, object)
    task_failed = Signal(object, object)
    active_count_changed = Signal()

    def __init__(self, *, max_thread_count: int = 2, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if max_thread_count < 1:
            raise ValueError("max_thread_count must be at least one")
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(max_thread_count)
        self._active: dict[TaskIdentity, _PageTask] = {}
        self._accepting = True

    @Property(int, notify=active_count_changed)
    def active_count(self) -> int:
        return len(self._active)

    @Property(int, constant=True)
    def max_thread_count(self) -> int:
        return self._pool.maxThreadCount()

    def submit(self, identity: TaskIdentity, operation: Callable[[], Any]) -> bool:
        if not self._accepting or identity in self._active:
            return False
        task = _PageTask(identity, operation)
        task.signals.completed.connect(self._complete, Qt.ConnectionType.QueuedConnection)
        self._active[identity] = task
        self.active_count_changed.emit()
        self._pool.start(task)
        return True

    def cancel(self, identity: TaskIdentity) -> bool:
        task = self._active.pop(identity, None)
        if task is None:
            return False
        task.cancel()
        self._pool.tryTake(task)
        self.active_count_changed.emit()
        return True

    @Slot(object, object, bool, object)
    def _complete(
        self,
        task: _PageTask,
        identity: TaskIdentity,
        succeeded: bool,
        payload: Any,
    ) -> None:
        if self._active.get(identity) is not task:
            return
        self._active.pop(identity)
        self.active_count_changed.emit()
        if succeeded:
            self.task_succeeded.emit(identity, payload)
        else:
            self.task_failed.emit(identity, payload)

    def wait_for_done(self, timeout_ms: int = -1) -> bool:
        return self._pool.waitForDone(timeout_ms)

    def shutdown(self, *, timeout_ms: int = 500) -> bool:
        tasks = tuple(self._active.values())
        if self._accepting:
            self._accepting = False
            for task in tasks:
                task.cancel()
            self._pool.clear()
        completed = self._pool.waitForDone(timeout_ms)
        if completed:
            if self._active:
                self._active.clear()
                self.active_count_changed.emit()
        return completed

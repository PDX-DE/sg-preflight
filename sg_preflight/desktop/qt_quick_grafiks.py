"""Builds safe launch specs for the Grafiks 3D inspection subprocess and hosts its
process lifecycle for the Qt Quick shell."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Callable, Protocol

from PySide6.QtCore import QObject, Property, QElapsedTimer, QProcess, Signal, Slot

from sg_preflight.dashboard_grafiks import (
    _grafiks_runtime_issue,
    _grafiks_shell_command,
    _resolve_grafiks_shell_exe,
)
from sg_preflight.desktop.task_pool import PageTaskCoordinator, TaskIdentity


_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_MISSING_DETAIL = "3D inspection is unavailable in this installation."
_RUNTIME_DETAIL = "The 3D inspection runtime is incomplete."
_SPAWN_DETAIL = "3D inspection could not be started."
_EARLY_EXIT_DETAIL = "3D inspection stopped during startup."


class _Process(Protocol):
    started: object
    errorOccurred: object
    finished: object

    def setProgram(self, program: str) -> None: ...

    def setArguments(self, arguments: list[str]) -> None: ...

    def setWorkingDirectory(self, working_directory: str) -> None: ...

    def start(self) -> None: ...

    def kill(self) -> None: ...

    def deleteLater(self) -> None: ...


class _ElapsedTimer(Protocol):
    def start(self) -> None: ...

    def isValid(self) -> bool: ...

    def elapsed(self) -> int: ...


@dataclass(frozen=True, slots=True)
class GrafiksLaunchSpec:
    executable: Path | None
    arguments: tuple[str, ...]
    error_code: str = ""
    safe_detail: str = ""


def build_grafiks_launch_spec(
    profile_id: str,
    *,
    workspace: Path,
    bmw_root: Path | None,
) -> GrafiksLaunchSpec:
    if not _PROFILE_ID_PATTERN.fullmatch(profile_id):
        return GrafiksLaunchSpec(None, (), "grafiks_runtime_invalid", _RUNTIME_DETAIL)
    root = Path(workspace).resolve()
    resolved_bmw_root = Path(bmw_root).resolve() if bmw_root is not None else None
    try:
        executable = _resolve_grafiks_shell_exe(root)
        if executable is None:
            return GrafiksLaunchSpec(None, (), "grafiks_missing", _MISSING_DETAIL)
        executable = Path(executable).resolve()
        if _grafiks_runtime_issue(executable):
            return GrafiksLaunchSpec(None, (), "grafiks_runtime_invalid", _RUNTIME_DETAIL)
        command = _grafiks_shell_command(
            executable,
            profile_id=profile_id,
            bmw_root=resolved_bmw_root,
        )
        if not command or Path(command[0]).resolve() != executable:
            return GrafiksLaunchSpec(None, (), "grafiks_runtime_invalid", _RUNTIME_DETAIL)
    except (OSError, RuntimeError, ValueError):
        return GrafiksLaunchSpec(None, (), "grafiks_runtime_invalid", _RUNTIME_DETAIL)
    return GrafiksLaunchSpec(executable, tuple(str(item) for item in command[1:]))


def _create_process(parent: QObject) -> QProcess:
    return QProcess(parent)


class GrafiksHostAdapter(QObject):
    stateChanged = Signal()
    hideRequested = Signal()
    restoreRequested = Signal()

    def __init__(
        self,
        *,
        coordinator: PageTaskCoordinator,
        workspace: Path | str,
        bmw_root: Path | str | None = None,
        launch_spec_builder: Callable[..., GrafiksLaunchSpec] = build_grafiks_launch_spec,
        process_factory: Callable[[QObject], _Process] = _create_process,
        elapsed_timer: _ElapsedTimer | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._workspace = Path(workspace)
        self._bmw_root = Path(bmw_root) if bmw_root is not None else None
        self._launch_spec_builder = launch_spec_builder
        self._process_factory = process_factory
        self._elapsed_timer = elapsed_timer or QElapsedTimer()
        self._generation = 0
        self._pending_identity: TaskIdentity | None = None
        self._process: _Process | None = None
        self._window_hidden = False
        self._state = "idle"
        self._error_code = ""
        self._error_summary = ""
        self._closed = False
        self._coordinator.task_succeeded.connect(self._accept_launch_spec)
        self._coordinator.task_failed.connect(self._accept_launch_failure)

    @Property(str, notify=stateChanged)
    def state(self) -> str:
        return self._state

    @Property(str, notify=stateChanged)
    def errorCode(self) -> str:
        return self._error_code

    @Property(str, notify=stateChanged)
    def errorSummary(self) -> str:
        return self._error_summary

    @Property(bool, notify=stateChanged)
    def canLaunch(self) -> bool:
        return not self._closed and self._state in {"idle", "failed"}

    def launch(self, profile_id: str) -> bool:
        profile = str(profile_id or "").strip()
        if not self.canLaunch or not _PROFILE_ID_PATTERN.fullmatch(profile):
            return False
        self._generation += 1
        identity = TaskIdentity(self._generation, profile, "home", "grafiks_validate")
        self._pending_identity = identity
        self._set_status("validating")
        builder = self._launch_spec_builder
        workspace = self._workspace
        bmw_root = self._bmw_root

        def validate() -> GrafiksLaunchSpec:
            return builder(
                profile,
                workspace=workspace,
                bmw_root=bmw_root,
            )

        if not self._coordinator.submit(identity, validate):
            self._pending_identity = None
            self._set_failure("grafiks_runtime_invalid", _RUNTIME_DETAIL)
            return False
        return True

    @Slot(object, object)
    def _accept_launch_spec(self, identity: TaskIdentity, spec: object) -> None:
        if self._closed or identity != self._pending_identity:
            return
        self._pending_identity = None
        if not isinstance(spec, GrafiksLaunchSpec):
            self._set_failure("grafiks_runtime_invalid", _RUNTIME_DETAIL)
            return
        if spec.error_code:
            if spec.error_code == "grafiks_missing":
                self._set_failure("grafiks_missing", _MISSING_DETAIL)
            else:
                self._set_failure("grafiks_runtime_invalid", _RUNTIME_DETAIL)
            return
        if spec.executable is None:
            self._set_failure("grafiks_missing", _MISSING_DETAIL)
            return
        self._start_process(spec)

    @Slot(object, object)
    def _accept_launch_failure(self, identity: TaskIdentity, _failure: object) -> None:
        if self._closed or identity != self._pending_identity:
            return
        self._pending_identity = None
        self._set_failure("grafiks_runtime_invalid", _RUNTIME_DETAIL)

    def _start_process(self, spec: GrafiksLaunchSpec) -> None:
        try:
            process = self._process_factory(self)
            process.started.connect(self._handle_started)
            process.errorOccurred.connect(self._handle_error)
            process.finished.connect(self._handle_finished)
            process.setProgram(str(spec.executable))
            process.setArguments(list(spec.arguments))
            process.setWorkingDirectory(str(spec.executable.parent))
            self._process = process
            self._set_status("starting")
            process.start()
        except (OSError, RuntimeError):
            self._release_process()
            self._set_failure("grafiks_spawn_failed", _SPAWN_DETAIL)

    @Slot()
    def _handle_started(self) -> None:
        process = self._process
        if self._closed or process is None or self.sender() is not process:
            return
        self._elapsed_timer.start()
        self._window_hidden = True
        self._set_status("running")
        self.hideRequested.emit()

    @Slot(object)
    def _handle_error(self, _error: object) -> None:
        process = self._process
        if self._closed or process is None or self.sender() is not process:
            return
        self._release_process(kill=self._window_hidden)
        self._set_failure("grafiks_spawn_failed", _SPAWN_DETAIL)
        self._restore_if_hidden()

    @Slot(int, object)
    def _handle_finished(self, _exit_code: int, _exit_status: object) -> None:
        process = self._process
        if self._closed or process is None or self.sender() is not process:
            return
        early_exit = (
            self._state != "running"
            or not self._elapsed_timer.isValid()
            or self._elapsed_timer.elapsed() < 1500
        )
        self._release_process()
        if early_exit:
            self._set_failure("grafiks_early_exit", _EARLY_EXIT_DETAIL)
        else:
            self._set_status("idle")
        self._restore_if_hidden()

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._generation += 1
        self._pending_identity = None
        self._release_process(kill=True)
        if not self._set_status("idle"):
            self.stateChanged.emit()
        self._restore_if_hidden()

    def _release_process(self, *, kill: bool = False) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        if kill:
            try:
                process.kill()
            except (OSError, RuntimeError):
                pass
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def _restore_if_hidden(self) -> None:
        if not self._window_hidden:
            return
        self._window_hidden = False
        self.restoreRequested.emit()

    def _set_failure(self, code: str, summary: str) -> None:
        self._set_status("failed", error_code=code, error_summary=summary)

    def _set_status(
        self,
        state: str,
        *,
        error_code: str = "",
        error_summary: str = "",
    ) -> bool:
        next_values = (state, error_code, error_summary)
        if next_values == (self._state, self._error_code, self._error_summary):
            return False
        self._state, self._error_code, self._error_summary = next_values
        self.stateChanged.emit()
        return True

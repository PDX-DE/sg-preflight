from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import re
from typing import Any, Protocol

from PySide6.QtCore import QObject, Property, Signal, Slot

from sg_preflight.desktop.payload_adapter import adapt_page_payload
from sg_preflight.desktop.task_pool import PageTaskCoordinator, TaskFailure, TaskIdentity
from sg_preflight.shell_registry import HOME_ROUTE_ID, HOME_SUBTITLE, HOME_TITLE
from sg_preflight.surface_registry import get_surface_descriptor, is_registered_surface


_PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


class PageLoader(Protocol):
    def __call__(
        self,
        page_id: str,
        profile_id: str,
        workspace: Path,
        *,
        bmw_root: Path | None = None,
    ) -> Mapping[str, Any]: ...


class ProfileResolver(Protocol):
    def __call__(
        self,
        workspace: Path,
        *,
        bmw_root: Path | None = None,
    ) -> str: ...


class ShellLoader(Protocol):
    def __call__(
        self,
        workspace: Path,
        profile_id: str,
        *,
        bmw_root: Path | None = None,
    ) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class UiError:
    code: str
    title: str
    safe_detail: str
    retryable: bool
    recovery_action: str


EMPTY_UI_ERROR = UiError("", "", "", False, "")

UI_ERROR_DEFINITIONS = {
    "qml_resource_missing": (
        "Interface unavailable",
        "The Qt Quick interface files are unavailable.",
        False,
        "launch_clean",
    ),
    "qml_engine_load_failed": (
        "Interface unavailable",
        "The Qt Quick interface could not be initialized.",
        True,
        "retry",
    ),
    "page_reader_failed": (
        "Evidence unavailable",
        "The local page evidence could not be loaded.",
        True,
        "retry",
    ),
    "page_payload_invalid": (
        "Evidence unavailable",
        "The page evidence has an unsupported shape.",
        False,
        "open_clean",
    ),
    "action_rejected": (
        "Action unavailable",
        "This action is not available from the current page.",
        False,
        "dismiss",
    ),
    "grafiks_missing": (
        "Grafiks unavailable",
        "Grafiks is unavailable in this installation.",
        False,
        "stay_clean",
    ),
    "grafiks_runtime_invalid": (
        "Grafiks unavailable",
        "The Grafiks runtime is incomplete.",
        False,
        "stay_clean",
    ),
    "grafiks_spawn_failed": (
        "Grafiks unavailable",
        "Grafiks could not be started.",
        True,
        "retry",
    ),
    "grafiks_early_exit": (
        "Grafiks unavailable",
        "Grafiks stopped during startup.",
        True,
        "retry",
    ),
}


def _ui_error(code: str) -> UiError:
    definition = UI_ERROR_DEFINITIONS.get(code)
    if definition is None:
        code = "page_reader_failed"
        definition = UI_ERROR_DEFINITIONS[code]
    title, safe_detail, retryable, recovery_action = definition
    return UiError(code, title, safe_detail, retryable, recovery_action)


def load_dashboard_surface(
    page_id: str,
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
) -> Mapping[str, Any]:
    from sg_preflight.dashboard.main import ABOUT_CONTENT, build_dashboard_page

    if page_id == "about":
        descriptor = get_surface_descriptor(page_id)
        return {
            "id": descriptor.surface_id,
            "title": descriptor.title,
            "tagline": descriptor.subtitle,
            "content": dict(ABOUT_CONTENT),
        }
    return build_dashboard_page(
        page_id=page_id,
        profile_id=profile_id,
        workspace=Path(workspace),
        bmw_root=bmw_root,
        ui_mode="clean",
        persist_dependency_state=False,
    )


def resolve_dashboard_profile(
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
) -> str:
    from sg_preflight.dashboard_preferences import (
        _resolve_dashboard_profile_id,
        dashboard_profile_options,
    )
    from sg_preflight.profiles import PROFILE_SCOPE_DEFAULT

    default_options = dashboard_profile_options(
        bmw_root=bmw_root,
        profile_scope=PROFILE_SCOPE_DEFAULT,
    )
    all_options = dashboard_profile_options(bmw_root=bmw_root, profile_scope="all")
    return _resolve_dashboard_profile_id(
        "",
        all_options,
        workspace=Path(workspace).resolve(),
        fallback_options=default_options,
    )


def load_shell_context(
    workspace: Path | str,
    profile_id: str = "",
    *,
    bmw_root: Path | str | None = None,
    profile_resolver: ProfileResolver = resolve_dashboard_profile,
) -> Mapping[str, Any]:
    from sg_preflight.dashboard_preferences import dashboard_profile_options
    from sg_preflight.home_context import build_home_context

    raw_options = dashboard_profile_options(bmw_root=bmw_root, profile_scope="all")
    options: list[dict[str, str]] = []
    for option in raw_options:
        candidate = str(option.get("id", "") or "").strip()
        if not _PROFILE_ID_PATTERN.fullmatch(candidate):
            continue
        label = str(option.get("label", candidate) or candidate).strip()
        options.append({"id": candidate, "label": label or candidate})
    requested = str(profile_id or "").strip()
    selected = next(
        (option["id"] for option in options if option["id"].casefold() == requested.casefold()),
        "",
    )
    if not selected:
        resolved = profile_resolver(workspace=Path(workspace).resolve(), bmw_root=bmw_root)
        selected = next(
            (option["id"] for option in options if option["id"].casefold() == resolved.casefold()),
            options[0]["id"] if options else "",
        )
    return {
        **build_home_context(workspace),
        "profile_options": options,
        "selected_profile_id": selected,
    }


class DesktopController(QObject):
    currentRouteChanged = Signal()
    currentPageChanged = Signal()
    currentProfileChanged = Signal()
    profileOptionsChanged = Signal()
    pageStateChanged = Signal()
    operationChanged = Signal()
    payloadChanged = Signal()
    errorChanged = Signal()

    def __init__(
        self,
        *,
        workspace: Path | str,
        initial_profile_id: str = "",
        bmw_root: Path | str | None = None,
        task_coordinator: PageTaskCoordinator | None = None,
        page_loader: PageLoader | None = None,
        profile_resolver: ProfileResolver | None = None,
        shell_loader: ShellLoader | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        profile_id = initial_profile_id.strip()
        if profile_id and not _PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("initial_profile_id must be empty or a canonical profile ID")
        self._workspace = Path(workspace).resolve()
        self._bmw_root = Path(bmw_root).resolve() if bmw_root is not None else None
        self._current_route_id = HOME_ROUTE_ID
        self._current_profile_id = profile_id
        self._profile_options: list[dict[str, str]] = []
        self._page_state = "idle"
        self._payload: dict[str, Any] = {}
        self._error = EMPTY_UI_ERROR
        self._generation = 0
        self._current_identity: TaskIdentity | None = None
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._task_coordinator = task_coordinator or PageTaskCoordinator(parent=self)
        self._page_loader = page_loader or load_dashboard_surface
        self._profile_resolver = profile_resolver or resolve_dashboard_profile
        self._shell_loader = shell_loader or partial(
            load_shell_context,
            profile_resolver=self._profile_resolver,
        )
        self._closed = False
        self._initialized = False
        self._task_coordinator.task_succeeded.connect(self._accept_success)
        self._task_coordinator.task_failed.connect(self._accept_failure)

    @Property(str, notify=currentRouteChanged)
    def currentRouteId(self) -> str:
        return self._current_route_id

    @Property(str, notify=currentPageChanged)
    def currentPageId(self) -> str:
        return "" if self._current_route_id == HOME_ROUTE_ID else self._current_route_id

    @Property(str, notify=currentProfileChanged)
    def currentProfileId(self) -> str:
        return self._current_profile_id

    @Property("QVariantList", notify=profileOptionsChanged)
    def profileOptions(self) -> list[dict[str, str]]:
        return [dict(option) for option in self._profile_options]

    @Property(str, notify=operationChanged)
    def pageState(self) -> str:
        return self._page_state

    @Property(str, notify=pageStateChanged)
    def currentOperation(self) -> str:
        return self._current_identity.operation if self._current_identity is not None else ""

    @Property(str, notify=currentRouteChanged)
    def pageTitle(self) -> str:
        if self._current_route_id == HOME_ROUTE_ID:
            return HOME_TITLE
        return get_surface_descriptor(self._current_route_id).title

    @Property(str, notify=currentRouteChanged)
    def pageSubtitle(self) -> str:
        if self._current_route_id == HOME_ROUTE_ID:
            return HOME_SUBTITLE
        return get_surface_descriptor(self._current_route_id).subtitle

    @Property(object, notify=payloadChanged)
    def currentPayload(self) -> dict[str, Any]:
        return dict(self._payload)

    @Property(str, notify=errorChanged)
    def errorCode(self) -> str:
        return self._error.code

    @Property(str, notify=errorChanged)
    def errorTitle(self) -> str:
        return self._error.title

    @Property(str, notify=errorChanged)
    def errorSummary(self) -> str:
        return self._error.safe_detail

    @Property(bool, notify=errorChanged)
    def errorRetryable(self) -> bool:
        return self._error.retryable

    @Property(str, notify=errorChanged)
    def errorRecoveryAction(self) -> str:
        return self._error.recovery_action

    @Slot(str, result=bool)
    def navigate(self, route_id: str) -> bool:
        if self._closed:
            return False
        candidate = route_id.strip()
        if candidate != HOME_ROUTE_ID and not is_registered_surface(candidate):
            self._set_error(_ui_error("action_rejected"))
            return False
        if candidate == HOME_ROUTE_ID:
            self._set_route(HOME_ROUTE_ID)
            return self._schedule_shell_context()
        if not self._current_profile_id:
            self.initialize()
            return False
        if candidate == self._current_route_id and self._page_state == "loading":
            return False
        self._set_route(candidate)
        cached = self._cache.get(self._cache_key())
        if cached is not None:
            self._generation += 1
            self._set_current_identity(None)
            self._set_ready_payload(cached)
            return True
        return self._schedule_page("load")

    @Slot(str, result=bool)
    def selectProfile(self, profile_id: str) -> bool:
        if self._closed:
            return False
        candidate = profile_id.strip()
        canonical = next(
            (
                option["id"]
                for option in self._profile_options
                if option["id"].casefold() == candidate.casefold()
            ),
            "",
        )
        if not canonical:
            self._set_error(_ui_error("action_rejected"))
            return False
        if canonical == self._current_profile_id:
            return True
        self._current_profile_id = canonical
        self.currentProfileChanged.emit()
        if self._current_route_id == HOME_ROUTE_ID:
            return self._schedule_shell_context()
        return self._schedule_page("load")

    @Slot(result=bool)
    def refresh(self) -> bool:
        if self._closed:
            return False
        if self._current_route_id == HOME_ROUTE_ID:
            return self._schedule_shell_context()
        if self._current_identity is not None:
            return False
        self._cache.pop(self._cache_key(), None)
        return self._schedule_page("refresh")

    @Slot(result=bool)
    def initialize(self) -> bool:
        if self._closed or self._initialized or self._current_route_id != HOME_ROUTE_ID:
            return False
        accepted = self._schedule_shell_context()
        if accepted:
            self._initialized = True
        return accepted

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._set_current_identity(None)
        self._set_payload({})
        self._set_profile_options([])
        self._set_error(EMPTY_UI_ERROR)
        self._set_state("idle")

    def _cache_key(self) -> tuple[str, str]:
        return self._current_profile_id, self._current_route_id

    def _set_route(self, route_id: str) -> None:
        if route_id == self._current_route_id:
            return
        self._current_route_id = route_id
        self.currentRouteChanged.emit()
        self.currentPageChanged.emit()

    def _next_identity(self, operation: str) -> TaskIdentity:
        self._generation += 1
        return TaskIdentity(
            self._generation,
            self._current_profile_id,
            self._current_route_id,
            operation,
        )

    def _prepare_schedule(self, identity: TaskIdentity) -> None:
        self._set_current_identity(identity)
        self._set_state("loading")
        self._set_payload({})
        self._set_error(EMPTY_UI_ERROR)

    def _schedule_shell_context(self) -> bool:
        if self._closed:
            return False
        identity = self._next_identity("shell_context")
        self._prepare_schedule(identity)
        shell_loader = self._shell_loader
        workspace = self._workspace
        bmw_root = self._bmw_root

        def read_shell_context() -> dict[str, Any]:
            raw = shell_loader(
                workspace=workspace,
                profile_id=identity.profile_id,
                bmw_root=bmw_root,
            )
            return adapt_page_payload(raw, workspace=workspace)

        return self._submit(identity, read_shell_context)

    def _schedule_page(self, operation: str) -> bool:
        if self._closed:
            return False
        identity = self._next_identity(operation)
        self._prepare_schedule(identity)
        page_loader = self._page_loader
        workspace = self._workspace
        bmw_root = self._bmw_root

        def read_page() -> dict[str, Any]:
            raw = page_loader(
                page_id=identity.page_id,
                profile_id=identity.profile_id,
                workspace=workspace,
                bmw_root=bmw_root,
            )
            return adapt_page_payload(raw, workspace=workspace)

        return self._submit(identity, read_page)

    def _submit(self, identity: TaskIdentity, operation: Any) -> bool:
        accepted = self._task_coordinator.submit(identity, operation)
        if not accepted:
            if identity == self._current_identity:
                self._set_current_identity(None)
                self._set_state("error")
                self._set_error(_ui_error("action_rejected"))
        return accepted

    @Slot(object, object)
    def _accept_success(self, identity: TaskIdentity, payload: object) -> None:
        if identity != self._current_identity:
            return
        self._set_current_identity(None)
        if not isinstance(payload, Mapping):
            self._set_payload({})
            self._set_state("error")
            self._set_error(_ui_error("page_payload_invalid"))
            return
        normalized = dict(payload)
        if identity.operation == "shell_context":
            if not self._accept_shell_profile(normalized):
                self._set_payload({})
                self._set_state("error")
                self._set_error(_ui_error("page_payload_invalid"))
                return
        else:
            self._cache[(identity.profile_id, identity.page_id)] = dict(normalized)
        self._set_ready_payload(normalized)

    def _accept_shell_profile(self, payload: Mapping[str, Any]) -> bool:
        raw_options = payload.get("profile_options", [])
        if not isinstance(raw_options, list):
            return False
        options: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_option in raw_options:
            if not isinstance(raw_option, Mapping):
                return False
            profile_id = str(raw_option.get("id", "") or "").strip()
            label = str(raw_option.get("label", "") or "").strip()
            folded = profile_id.casefold()
            if not _PROFILE_ID_PATTERN.fullmatch(profile_id) or not label or folded in seen:
                return False
            seen.add(folded)
            options.append({"id": profile_id, "label": label})
        selected = str(payload.get("selected_profile_id", "") or "").strip()
        canonical = next(
            (option["id"] for option in options if option["id"].casefold() == selected.casefold()),
            "",
        )
        if not canonical:
            return False
        self._set_profile_options(options)
        if canonical != self._current_profile_id:
            self._current_profile_id = canonical
            self.currentProfileChanged.emit()
        return True

    @Slot(object, object)
    def _accept_failure(self, identity: TaskIdentity, failure: object) -> None:
        if identity != self._current_identity:
            return
        self._set_current_identity(None)
        code = (
            failure.code
            if isinstance(failure, TaskFailure) and failure.code in UI_ERROR_DEFINITIONS
            else "page_reader_failed"
        )
        self._set_payload({})
        self._set_state("error")
        self._set_error(_ui_error(code))

    def _set_ready_payload(self, payload: Mapping[str, Any]) -> None:
        self._set_payload(dict(payload))
        self._set_error(EMPTY_UI_ERROR)
        self._set_state("ready")

    def _set_state(self, state: str) -> None:
        if state == self._page_state:
            return
        self._page_state = state
        self.pageStateChanged.emit()

    def _set_current_identity(self, identity: TaskIdentity | None) -> None:
        if identity == self._current_identity:
            return
        self._current_identity = identity
        self.operationChanged.emit()

    def _set_payload(self, payload: dict[str, Any]) -> None:
        if payload == self._payload:
            return
        self._payload = payload
        self.payloadChanged.emit()

    def _set_profile_options(self, options: list[dict[str, str]]) -> None:
        if options == self._profile_options:
            return
        self._profile_options = [dict(option) for option in options]
        self.profileOptionsChanged.emit()

    def _set_error(self, error: UiError) -> None:
        if error == self._error:
            return
        self._error = error
        self.errorChanged.emit()

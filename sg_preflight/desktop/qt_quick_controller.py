from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Protocol

from PySide6.QtCore import QObject, Property, Signal, Slot

from sg_preflight.desktop.payload_adapter import adapt_page_payload
from sg_preflight.desktop.task_pool import PageTaskCoordinator, TaskFailure, TaskIdentity
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


class DesktopController(QObject):
    currentPageChanged = Signal()
    currentProfileChanged = Signal()
    pageStateChanged = Signal()
    payloadChanged = Signal()
    errorChanged = Signal()

    def __init__(
        self,
        *,
        workspace: Path | str,
        initial_profile_id: str = "",
        initial_page_id: str = "about",
        bmw_root: Path | str | None = None,
        task_coordinator: PageTaskCoordinator | None = None,
        page_loader: PageLoader | None = None,
        profile_resolver: ProfileResolver | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        if not is_registered_surface(initial_page_id):
            raise ValueError("initial_page_id must reference a registered surface")
        profile_id = initial_profile_id.strip()
        if profile_id and not _PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise ValueError("initial_profile_id must be empty or a canonical profile ID")
        self._workspace = Path(workspace).resolve()
        self._bmw_root = Path(bmw_root).resolve() if bmw_root is not None else None
        self._current_profile_id = profile_id
        self._current_page_id = initial_page_id
        self._page_state = "idle"
        self._payload: dict[str, Any] = {}
        self._error = EMPTY_UI_ERROR
        self._generation = 0
        self._current_identity: TaskIdentity | None = None
        self._profile_identity: TaskIdentity | None = None
        self._cache: dict[tuple[str, str], dict[str, Any]] = {}
        self._task_coordinator = task_coordinator or PageTaskCoordinator(parent=self)
        self._page_loader = page_loader or load_dashboard_surface
        self._profile_resolver = profile_resolver or resolve_dashboard_profile
        self._closed = False
        self._task_coordinator.task_succeeded.connect(self._accept_success)
        self._task_coordinator.task_failed.connect(self._accept_failure)

    @Property(str, notify=currentPageChanged)
    def currentPageId(self) -> str:
        return self._current_page_id

    @Property(str, notify=currentProfileChanged)
    def currentProfileId(self) -> str:
        return self._current_profile_id

    @Property(str, notify=pageStateChanged)
    def pageState(self) -> str:
        return self._page_state

    @Property(str, notify=currentPageChanged)
    def pageTitle(self) -> str:
        return get_surface_descriptor(self._current_page_id).title

    @Property(str, notify=currentPageChanged)
    def pageSubtitle(self) -> str:
        return get_surface_descriptor(self._current_page_id).subtitle

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
    def navigate(self, page_id: str) -> bool:
        if self._closed:
            return False
        candidate = page_id.strip()
        if not is_registered_surface(candidate):
            self._set_error(_ui_error("action_rejected"))
            return False
        if not self._current_profile_id and candidate != "about":
            self.initialize()
            return False
        if candidate == self._current_page_id:
            if self._page_state == "loading":
                return False
            cached = self._cache.get(self._cache_key())
            if cached is not None:
                self._set_ready_payload(cached)
                return True
        else:
            self._current_page_id = candidate
            self.currentPageChanged.emit()
        cached = self._cache.get(self._cache_key())
        if cached is not None:
            self._generation += 1
            self._current_identity = None
            self._set_ready_payload(cached)
            return True
        return self._schedule("load")

    @Slot(str, result=bool)
    def selectProfile(self, profile_id: str) -> bool:
        if self._closed:
            return False
        candidate = profile_id.strip()
        if not _PROFILE_ID_PATTERN.fullmatch(candidate):
            self._set_error(_ui_error("action_rejected"))
            return False
        if candidate == self._current_profile_id:
            return True
        self._profile_identity = None
        self._current_profile_id = candidate
        self.currentProfileChanged.emit()
        return self._schedule("load")

    @Slot(result=bool)
    def refresh(self) -> bool:
        if self._closed or self._current_identity is not None:
            return False
        self._cache.pop(self._cache_key(), None)
        return self._schedule("refresh")

    @Slot(result=bool)
    def initialize(self) -> bool:
        if self._closed or self._current_profile_id or self._profile_identity is not None:
            return False
        self._generation += 1
        identity = TaskIdentity(
            self._generation,
            "",
            self._current_page_id,
            "resolve-profile",
        )
        profile_resolver = self._profile_resolver
        workspace = self._workspace
        bmw_root = self._bmw_root

        def resolve_profile() -> str:
            return profile_resolver(workspace=workspace, bmw_root=bmw_root)

        if not self._task_coordinator.submit(identity, resolve_profile):
            self._set_error(_ui_error("action_rejected"))
            return False
        self._profile_identity = identity
        self._set_error(EMPTY_UI_ERROR)
        return True

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._current_identity = None
        self._profile_identity = None
        self._set_payload({})
        self._set_error(EMPTY_UI_ERROR)
        self._set_state("idle")

    def _cache_key(self) -> tuple[str, str]:
        return self._current_profile_id, self._current_page_id

    def _schedule(self, operation: str) -> bool:
        if self._closed:
            return False
        self._generation += 1
        identity = TaskIdentity(
            self._generation,
            self._current_profile_id,
            self._current_page_id,
            operation,
        )
        self._current_identity = identity
        self._set_state("loading")
        self._set_payload({})
        self._set_error(EMPTY_UI_ERROR)
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

        accepted = self._task_coordinator.submit(identity, read_page)
        if not accepted:
            self._current_identity = None
            self._set_state("error")
            self._set_error(_ui_error("action_rejected"))
        return accepted

    @Slot(object, object)
    def _accept_success(self, identity: TaskIdentity, payload: object) -> None:
        if identity == self._profile_identity:
            self._profile_identity = None
            candidate = str(payload or "").strip()
            if (
                not self._closed
                and not self._current_profile_id
                and _PROFILE_ID_PATTERN.fullmatch(candidate)
            ):
                self._current_profile_id = candidate
                self.currentProfileChanged.emit()
                self._set_error(EMPTY_UI_ERROR)
            elif not self._closed:
                self._set_state("error")
                self._set_error(_ui_error("page_reader_failed"))
            return
        if identity != self._current_identity:
            return
        self._current_identity = None
        if not isinstance(payload, Mapping):
            self._set_payload({})
            self._set_state("error")
            self._set_error(_ui_error("page_payload_invalid"))
            return
        normalized = dict(payload)
        self._cache[(identity.profile_id, identity.page_id)] = dict(normalized)
        self._set_ready_payload(normalized)

    @Slot(object, object)
    def _accept_failure(self, identity: TaskIdentity, failure: object) -> None:
        if identity == self._profile_identity:
            self._profile_identity = None
            if not self._closed:
                self._set_state("error")
                self._set_error(_ui_error("page_reader_failed"))
            return
        if identity != self._current_identity:
            return
        self._current_identity = None
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

    def _set_payload(self, payload: dict[str, Any]) -> None:
        if payload == self._payload:
            return
        self._payload = payload
        self.payloadChanged.emit()

    def _set_error(self, error: UiError) -> None:
        if error == self._error:
            return
        self._error = error
        self.errorChanged.emit()

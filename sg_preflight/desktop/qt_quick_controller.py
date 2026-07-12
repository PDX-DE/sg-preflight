from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import CancelledError, Future
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import re
from typing import Any, Callable, Protocol

from PySide6.QtCore import QObject, Property, Signal, Slot

from sg_preflight.desktop.artifact_registry import (
    ArtifactCandidate,
    ArtifactIdentity,
    ArtifactRegistry,
    extract_artifact_candidates,
)
from sg_preflight.desktop.page_presenter import PagePresentationError, present_page_payload
from sg_preflight.desktop.payload_adapter import adapt_page_payload
from sg_preflight.desktop.task_pool import PageTaskCoordinator, TaskFailure, TaskIdentity
from sg_preflight.desktop.ui_capabilities import (
    CapabilityEffectExecutor,
    audit_ui_diagnostic_action,
    capability_descriptor,
    get_ui_capability,
    validate_effect_text,
)
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


class GrafiksHost(Protocol):
    def launch(self, profile_id: str) -> bool: ...

    def shutdown(self) -> None: ...


@dataclass(frozen=True, slots=True)
class UiError:
    code: str
    title: str
    safe_detail: str
    retryable: bool
    recovery_action: str


@dataclass(frozen=True, slots=True)
class _InvalidPagePayload:
    code: str = "page_payload_invalid"


@dataclass(frozen=True, slots=True)
class _PresentedPageResult:
    payload: dict[str, Any]
    artifact_candidates: tuple[ArtifactCandidate, ...]
    diagnostic_actions: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class _EffectContext:
    effect_generation: int
    page_generation: int
    profile_id: str
    page_id: str
    capability_id: str


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
        "3D inspection unavailable",
        "3D inspection is unavailable in this installation.",
        False,
        "stay_clean",
    ),
    "grafiks_runtime_invalid": (
        "3D inspection unavailable",
        "The 3D inspection runtime is incomplete.",
        False,
        "stay_clean",
    ),
    "grafiks_spawn_failed": (
        "3D inspection unavailable",
        "3D inspection could not be started.",
        True,
        "retry",
    ),
    "grafiks_early_exit": (
        "3D inspection unavailable",
        "3D inspection stopped during startup.",
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
        dashboard_profile_options,
        resolve_explicit_dashboard_profile,
    )

    all_options = dashboard_profile_options(bmw_root=bmw_root, profile_scope="all")
    return resolve_explicit_dashboard_profile(
        workspace=Path(workspace).resolve(),
        options=all_options,
    )


def load_shell_context(
    workspace: Path | str,
    profile_id: str = "",
    *,
    bmw_root: Path | str | None = None,
    profile_resolver: ProfileResolver = resolve_dashboard_profile,
    action_lister: Callable[..., object] | None = None,
    diagnostic_read_roots: tuple[Path, ...] = (),
    diagnostic_output_root: Path | None = None,
) -> Mapping[str, Any]:
    from sg_preflight.dashboard_preferences import dashboard_profile_options
    from sg_preflight.home_context import build_home_context
    from sg_preflight.qa_action_persistence import list_recent_action_records
    from sg_preflight.qa_hub import build_qa_hub_snapshot
    from sg_preflight.qa_operator_actions import list_sgfx_preflight_actions
    from sg_preflight.services import list_recent_run_records

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
    if not selected and not requested:
        resolved = profile_resolver(workspace=Path(workspace).resolve(), bmw_root=bmw_root)
        selected = next(
            (option["id"] for option in options if option["id"].casefold() == resolved.casefold()),
            "",
        )
    root = Path(workspace).resolve()
    home_context = build_home_context(root)
    activity = home_context.get("activity", []) if isinstance(home_context, Mapping) else []
    try:
        action_records = list_recent_action_records(root, limit=12)
    except (OSError, ValueError):
        action_records = []
    try:
        run_records = list_recent_run_records(root, limit=12)
    except (OSError, ValueError):
        run_records = []

    actions: list[dict[str, object]] = []
    if selected:
        resolved_read_roots = _resolve_diagnostic_read_roots(root, diagnostic_read_roots)
        resolved_output_root = _resolve_diagnostic_output_root(root, diagnostic_output_root)
        try:
            raw_actions = (
                list_sgfx_preflight_actions(root)
                if action_lister is None
                else action_lister(root)
            )
        except (OSError, ValueError):
            raw_actions = []
        actions = [
            capability_descriptor(
                "diagnostic.run",
                label="Run local QA checks",
                action_id=str(getattr(action, "action_id", "")),
            )
            for action in raw_actions
            if audit_ui_diagnostic_action(
                action,
                read_only_roots=resolved_read_roots,
                output_root=resolved_output_root,
                allowed_output_root=root / "out",
                expected_profile_id=selected,
                owning_page_id=HOME_ROUTE_ID,
            )
        ]
    return build_qa_hub_snapshot(
        workspace=root,
        profile_options=options,
        selected_profile_id=selected,
        actions=actions,
        action_records=action_records,
        run_records=run_records,
        activity=activity if isinstance(activity, list) else [],
    )


def _resolve_diagnostic_read_roots(
    workspace: Path,
    configured_roots: tuple[Path, ...],
) -> tuple[Path, ...]:
    if configured_roots:
        return configured_roots
    from sg_preflight.profiles import resolve_source_repo_root

    candidates = (
        resolve_source_repo_root(workspace),
        workspace / "repositories" / "trunk",
    )
    roots: list[Path] = []
    for candidate in candidates:
        resolved = Path(candidate).resolve()
        if resolved.is_dir() and resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _resolve_diagnostic_output_root(
    workspace: Path,
    configured_root: Path | None,
) -> Path:
    if configured_root is not None:
        return configured_root
    from sg_preflight.qa_actions import operator_ui_actions_root

    return operator_ui_actions_root(workspace)


class DesktopController(QObject):
    currentRouteChanged = Signal()
    currentPageChanged = Signal()
    currentProfileChanged = Signal()
    profileOptionsChanged = Signal()
    pageStateChanged = Signal()
    operationChanged = Signal()
    payloadChanged = Signal()
    errorChanged = Signal()
    capabilityStateChanged = Signal()
    capabilityErrorChanged = Signal()
    diagnosticCanCancelChanged = Signal()
    _effectStarted = Signal(int)
    _effectFinished = Signal(int, bool, object)

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
        artifact_roots: tuple[Path | str, ...] = (),
        artifact_revealer: Callable[[Path], None] | None = None,
        effect_executor: CapabilityEffectExecutor | None = None,
        diagnostic_read_roots: tuple[Path | str, ...] = (),
        diagnostic_output_root: Path | str | None = None,
        action_lister: Callable[..., object] | None = None,
        action_getter: Callable[..., object] | None = None,
        action_executor: Callable[..., object] | None = None,
        manual_review_recorder: Callable[..., object] | None = None,
        operator_handoff_recorder: Callable[..., object] | None = None,
        grafiks_host: GrafiksHost | None = None,
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
        self._artifact_candidate_cache: dict[tuple[str, str], tuple[ArtifactCandidate, ...]] = {}
        self._diagnostic_action_cache: dict[tuple[str, str], tuple[dict[str, object], ...]] = {}
        self._task_coordinator = task_coordinator or PageTaskCoordinator(parent=self)
        self._page_loader = page_loader or load_dashboard_surface
        self._profile_resolver = profile_resolver or resolve_dashboard_profile
        self._configured_diagnostic_read_roots = tuple(
            Path(root).resolve() for root in diagnostic_read_roots
        )
        self._configured_diagnostic_output_root = (
            Path(diagnostic_output_root).absolute()
            if diagnostic_output_root is not None
            else None
        )
        self._action_lister = action_lister
        self._shell_loader = shell_loader or partial(
            load_shell_context,
            profile_resolver=self._profile_resolver,
            action_lister=self._action_lister,
            diagnostic_read_roots=self._configured_diagnostic_read_roots,
            diagnostic_output_root=self._configured_diagnostic_output_root,
        )
        default_artifact_roots = (
            self._workspace / "out",
            self._workspace / "operator_state",
        )
        configured_artifact_roots = tuple(Path(root).resolve() for root in artifact_roots)
        registry_arguments: dict[str, object] = {
            "approved_roots": (*default_artifact_roots, *configured_artifact_roots),
        }
        if artifact_revealer is not None:
            registry_arguments["revealer"] = artifact_revealer
        self._artifact_roots = tuple(registry_arguments["approved_roots"])
        self._artifact_registry = ArtifactRegistry(**registry_arguments)
        self._effect_executor = effect_executor or CapabilityEffectExecutor()
        self._action_getter = action_getter
        self._action_executor = action_executor
        self._manual_review_recorder = manual_review_recorder
        self._operator_handoff_recorder = operator_handoff_recorder
        self._grafiks_host = grafiks_host
        self._effect_generation = 0
        self._effect_context: _EffectContext | None = None
        self._effect_future: Future[object] | None = None
        self._capability_state = "idle"
        self._capability_error = ""
        self._diagnostic_can_cancel = False
        self._closed = False
        self._initialized = False
        self._task_coordinator.task_succeeded.connect(self._accept_success)
        self._task_coordinator.task_failed.connect(self._accept_failure)
        self._effectStarted.connect(self._accept_effect_started)
        self._effectFinished.connect(self._accept_effect_finished)

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

    @Property(str, notify=pageStateChanged)
    def pageState(self) -> str:
        return self._page_state

    @Property(str, notify=operationChanged)
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

    @Property("QVariantMap", notify=payloadChanged)
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

    @Property(str, notify=capabilityStateChanged)
    def capabilityState(self) -> str:
        return self._capability_state

    @Property(str, notify=capabilityErrorChanged)
    def capabilityError(self) -> str:
        return self._capability_error

    @Property(bool, notify=diagnosticCanCancelChanged)
    def diagnosticCanCancel(self) -> bool:
        return self._diagnostic_can_cancel

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
        if cached is not None and candidate in {"full-qa-pass", "batch-full-qa-pass"}:
            return self._schedule_page("load")
        if cached is not None:
            self._generation += 1
            self._set_current_identity(None)
            self._clear_artifacts()
            self._set_ready_payload(
                cached,
                artifact_candidates=self._artifact_candidate_cache.get(self._cache_key(), ()),
                diagnostic_actions=self._diagnostic_action_cache.get(self._cache_key(), ()),
            )
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
        self._artifact_candidate_cache.pop(self._cache_key(), None)
        self._diagnostic_action_cache.pop(self._cache_key(), None)
        return self._schedule_page("refresh")

    @Slot(result=bool)
    def initialize(self) -> bool:
        if self._closed or self._initialized or self._current_route_id != HOME_ROUTE_ID:
            return False
        accepted = self._schedule_shell_context()
        if accepted:
            self._initialized = True
        return accepted

    @Slot(str, object, result=bool)
    def invokeCapability(self, capability_id: str, inputs: object) -> bool:
        if self._closed or not isinstance(inputs, Mapping):
            return False
        try:
            capability = get_ui_capability(capability_id)
        except KeyError:
            self._set_capability_error("This capability is unavailable.")
            return False
        owner = "shell" if capability.capability_id in {
            "profile.select",
            "page.navigate",
            "grafiks.launch",
        } else self._current_route_id
        if owner not in capability.owning_pages:
            self._set_capability_error("This capability is unavailable from the current page.")
            return False
        if capability.capability_id == "profile.select":
            return self.selectProfile(str(inputs.get("profile_id", "")))
        if capability.capability_id == "page.navigate":
            return self.navigate(str(inputs.get("route_id", "")))
        if capability.capability_id == "page.refresh":
            return self.refresh()
        if capability.capability_id == "artifact.reveal":
            return self.revealArtifact(str(inputs.get("artifact_id", "")))
        if capability.capability_id == "diagnostic.run":
            raw_profiles = inputs.get("profile_ids", [])
            profiles = raw_profiles if isinstance(raw_profiles, list) else []
            return self.runDiagnostic(str(inputs.get("action_id", "")), profiles)
        if capability.capability_id == "manual_review.record":
            return self.recordManualReview(
                str(inputs.get("step_id", "")),
                str(inputs.get("verdict", "")),
                str(inputs.get("note", "")),
            )
        if capability.capability_id == "operator_handoff.record":
            return self.recordOperatorHandoff(
                str(inputs.get("stopping_point", "")),
                str(inputs.get("next_step", "")),
                str(inputs.get("note", "")),
            )
        if capability.capability_id == "grafiks.launch":
            requested_profile = str(inputs.get("profile_id", "") or "").strip()
            if requested_profile.casefold() != self._current_profile_id.casefold():
                self._set_capability_error("The 3D inspection profile selection is invalid.")
                return False
            return self.launchGrafiks()
        self._set_capability_error("This capability is not available yet.")
        return False

    @Slot(result=bool)
    def launchGrafiks(self) -> bool:
        host = self._grafiks_host
        if self._closed or host is None or not self._current_profile_id:
            self._set_capability_error("3D inspection is unavailable in this installation.")
            return False
        try:
            accepted = host.launch(self._current_profile_id)
        except RuntimeError:
            accepted = False
        if not accepted:
            self._set_capability_error("3D inspection could not be started.")
            return False
        self._set_capability_error("")
        return True

    @Slot(str, "QVariantList", result=bool)
    def runDiagnostic(self, action_id: str, profile_ids: list[object]) -> bool:
        if self._closed or self._current_route_id not in {
            HOME_ROUTE_ID,
            "full-qa-pass",
            "batch-full-qa-pass",
        }:
            return False
        try:
            clean_action_id = validate_effect_text(action_id, required=True, max_length=128)
            requested_profiles = tuple(
                validate_effect_text(item, required=True, max_length=64)
                for item in profile_ids
            )
        except ValueError:
            self._set_capability_error("The diagnostic request is invalid.")
            return False
        canonical_profiles = {
            option["id"].casefold(): option["id"]
            for option in self._profile_options
        }
        canonical_profiles.setdefault(
            self._current_profile_id.casefold(),
            self._current_profile_id,
        )
        clean_profiles: list[str] = []
        seen_profiles: set[str] = set()
        for requested in requested_profiles:
            folded = requested.casefold()
            canonical = canonical_profiles.get(folded, "")
            if (
                not _PROFILE_ID_PATTERN.fullmatch(requested)
                or not canonical
                or folded in seen_profiles
            ):
                self._set_capability_error("The diagnostic profile selection is invalid.")
                return False
            seen_profiles.add(folded)
            clean_profiles.append(canonical)
        if not clean_profiles or self._current_profile_id not in clean_profiles:
            self._set_capability_error("The diagnostic profile selection is invalid.")
            return False
        current_action_ids = {
            str(item.get("actionId", ""))
            for item in self._payload.get("actions", [])
            if isinstance(item, Mapping)
            and item.get("capabilityId") == "diagnostic.run"
            and bool(item.get("enabled", False))
        }
        if self._current_route_id == HOME_ROUTE_ID:
            next_action = self._payload.get("nextAction", {})
            if (
                isinstance(next_action, Mapping)
                and next_action.get("capabilityId") == "diagnostic.run"
                and next_action.get("actionId")
            ):
                current_action_ids.add(str(next_action["actionId"]))
        if clean_action_id not in current_action_ids:
            self._set_capability_error("This diagnostic is unavailable.")
            return False
        try:
            action = self._get_operator_action(clean_action_id)
        except (KeyError, ValueError):
            self._set_capability_error("This diagnostic is unavailable.")
            return False
        output_root = self._operator_action_output_root()
        read_only_roots = self._diagnostic_read_roots()
        action_profile_id = str(getattr(action, "profile_id", "") or "").strip()
        if (
            not bool(getattr(action, "ready", False))
            or action_profile_id not in clean_profiles
            or not audit_ui_diagnostic_action(
                action,
                read_only_roots=read_only_roots,
                output_root=output_root,
                allowed_output_root=self._workspace / "out",
                expected_profile_id=self._current_profile_id,
                owning_page_id=self._current_route_id,
            )
        ):
            self._set_capability_error("This diagnostic is unavailable.")
            return False
        return self._submit_effect(
            "diagnostic.run",
            lambda: self._execute_diagnostic(action, read_only_roots, output_root),
        )

    @Slot(result=bool)
    def cancelDiagnostic(self) -> bool:
        future = self._effect_future
        context = self._effect_context
        if future is None or context is None or context.capability_id != "diagnostic.run":
            return False
        if not future.cancel():
            self._set_diagnostic_can_cancel(False)
            return False
        self._set_diagnostic_can_cancel(False)
        self._set_capability_state("cancelled")
        return True

    @Slot(str, result=bool)
    def revealArtifact(self, artifact_id: str) -> bool:
        if self._closed or self._current_route_id == HOME_ROUTE_ID:
            return False
        try:
            clean_id = validate_effect_text(artifact_id, required=True, max_length=128)
        except ValueError:
            self._set_capability_error("The artifact handle is invalid.")
            return False
        identity = ArtifactIdentity(
            self._generation,
            self._current_profile_id,
            self._current_route_id,
        )
        if not self._artifact_registry.reveal(clean_id, identity):
            self._set_capability_state("failed")
            self._set_capability_error("This artifact is unavailable or stale.")
            return False
        self._set_capability_error("")
        self._set_capability_state("completed")
        return True

    @Slot(str, str, str, result=bool)
    def recordManualReview(self, step_id: str, verdict: str, note: str) -> bool:
        if self._closed or self._current_route_id != "manual-review":
            return False
        try:
            clean_step = validate_effect_text(step_id, required=True, max_length=128)
            clean_verdict = validate_effect_text(verdict, required=True, max_length=32).casefold()
            clean_note = validate_effect_text(note, max_length=1000, evidence_only=True)
        except ValueError:
            self._set_capability_error("The manual-review input is invalid.")
            return False
        if clean_verdict not in {"passed", "failed", "skipped", "incomplete"}:
            self._set_capability_error("The manual-review verdict is invalid.")
            return False
        current_steps = {
            str(item.get("itemId", ""))
            for item in self._payload.get("visibleItems", [])
            if isinstance(item, Mapping)
        }
        if clean_step not in current_steps:
            self._set_capability_error("The manual-review step is stale or unavailable.")
            return False
        profile_id = self._current_profile_id
        workspace = self._workspace
        return self._submit_effect(
            "manual_review.record",
            lambda: self._record_manual_review(
                profile_id=profile_id,
                workspace=workspace,
                step_slug=clean_step,
                verdict=clean_verdict,
                note=clean_note,
                suggested_verdict="",
            ),
        )

    @Slot(str, str, str, result=bool)
    def recordOperatorHandoff(self, stopping_point: str, next_step: str, note: str) -> bool:
        if self._closed or self._current_route_id != "operator-handoff":
            return False
        try:
            clean_stopping = validate_effect_text(
                stopping_point,
                required=True,
                max_length=1000,
                evidence_only=True,
            )
            clean_next = validate_effect_text(next_step, max_length=1000, evidence_only=True)
            clean_note = validate_effect_text(note, max_length=1000, evidence_only=True)
        except ValueError:
            self._set_capability_error("The operator-handoff input is invalid.")
            return False
        profile_id = self._current_profile_id
        workspace = self._workspace
        return self._submit_effect(
            "operator_handoff.record",
            lambda: self._record_operator_handoff(
                workspace=workspace,
                profile_id=profile_id,
                stopping_point=clean_stopping,
                next_step=clean_next,
                note=clean_note,
            ),
        )

    @Slot()
    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._grafiks_host is not None:
            self._grafiks_host.shutdown()
        self._effect_generation += 1
        if self._effect_future is not None:
            self._effect_future.cancel()
        self._effect_executor.shutdown()
        self._effect_future = None
        self._effect_context = None
        self._set_diagnostic_can_cancel(False)
        self._set_capability_state("idle")
        self._set_capability_error("")
        self._clear_artifacts()
        self._set_current_identity(None)
        self._set_payload({})
        self._set_profile_options([])
        self._set_error(EMPTY_UI_ERROR)
        self._set_state("idle")

    def _get_operator_action(self, action_id: str) -> object:
        if self._action_getter is not None:
            return self._action_getter(action_id, self._workspace)
        from sg_preflight.qa_actions import get_operator_action

        return get_operator_action(action_id, self._workspace)

    def _operator_action_output_root(self) -> Path:
        return _resolve_diagnostic_output_root(
            self._workspace,
            self._configured_diagnostic_output_root,
        )

    def _diagnostic_read_roots(self) -> tuple[Path, ...]:
        return _resolve_diagnostic_read_roots(
            self._workspace,
            self._configured_diagnostic_read_roots,
        )

    @staticmethod
    def _snapshot_read_only_roots(roots: tuple[Path, ...]) -> dict[str, tuple[int, int]]:
        snapshot: dict[str, tuple[int, int]] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for path in sorted(item for item in root.rglob("*") if item.is_file()):
                try:
                    stat_result = path.stat()
                except OSError:
                    continue
                snapshot[f"{root}/{path.relative_to(root).as_posix()}"] = (
                    stat_result.st_size,
                    stat_result.st_mtime_ns,
                )
        return snapshot

    def _execute_diagnostic(
        self,
        action: object,
        read_only_roots: tuple[Path, ...],
        output_root: Path,
    ) -> object:
        before = self._snapshot_read_only_roots(read_only_roots)
        if self._action_executor is not None:
            record = self._action_executor(action, self._workspace)
        else:
            from sg_preflight.qa_actions import execute_operator_action

            record = execute_operator_action(action, self._workspace)
        after = self._snapshot_read_only_roots(read_only_roots)
        if after != before:
            raise RuntimeError("The diagnostic modified a read-only source root.")
        paths = getattr(record, "paths", None)
        if not isinstance(paths, Mapping):
            raise RuntimeError("The diagnostic returned an invalid output contract.")
        resolved_output = output_root.resolve()
        for value in paths.values():
            raw = str(value or "").strip()
            if not raw:
                continue
            try:
                Path(raw).resolve().relative_to(resolved_output)
            except ValueError as error:
                raise RuntimeError("The diagnostic returned an invalid output contract.") from error
        return record

    def _record_manual_review(self, **kwargs: object) -> object:
        if self._manual_review_recorder is not None:
            return self._manual_review_recorder(**kwargs)
        from sg_preflight.dashboard.main import record_manual_review_dashboard_step

        return record_manual_review_dashboard_step(**kwargs)

    def _record_operator_handoff(self, **kwargs: object) -> object:
        if self._operator_handoff_recorder is not None:
            return self._operator_handoff_recorder(**kwargs)
        from sg_preflight.operator_handoff import record_operator_handoff

        return record_operator_handoff(**kwargs)

    def _submit_effect(self, capability_id: str, operation: Callable[[], object]) -> bool:
        if self._closed or (self._effect_future is not None and not self._effect_future.done()):
            self._set_capability_error("Another capability is already running.")
            return False
        self._effect_generation += 1
        generation = self._effect_generation
        context = _EffectContext(
            generation,
            self._generation,
            self._current_profile_id,
            self._current_route_id,
            capability_id,
        )
        self._effect_context = context
        self._set_capability_error("")
        self._set_capability_state("queued")
        self._set_diagnostic_can_cancel(capability_id == "diagnostic.run")

        def execute() -> object:
            self._effectStarted.emit(generation)
            return operation()

        try:
            future = self._effect_executor.submit(execute)
        except RuntimeError:
            self._effect_context = None
            self._set_diagnostic_can_cancel(False)
            self._set_capability_state("failed")
            self._set_capability_error("The capability could not be started.")
            return False
        self._effect_future = future

        def complete(completed: Future[object]) -> None:
            try:
                result = completed.result()
            except CancelledError:
                self._effectFinished.emit(generation, False, "cancelled")
            except Exception:
                self._effectFinished.emit(generation, False, None)
            else:
                self._effectFinished.emit(generation, True, result)

        future.add_done_callback(complete)
        return True

    @Slot(int)
    def _accept_effect_started(self, generation: int) -> None:
        context = self._effect_context
        if context is None or generation != context.effect_generation:
            return
        self._set_capability_state("running")
        self._set_diagnostic_can_cancel(False)

    @Slot(int, bool, object)
    def _accept_effect_finished(self, generation: int, succeeded: bool, result: object) -> None:
        context = self._effect_context
        if context is None or generation != context.effect_generation:
            return
        self._effect_future = None
        self._effect_context = None
        self._set_diagnostic_can_cancel(False)
        if succeeded:
            self._set_capability_error("")
            self._set_capability_state("completed")
        elif result == "cancelled":
            self._set_capability_error("")
            self._set_capability_state("cancelled")
        else:
            self._set_capability_state("failed")
            self._set_capability_error("The capability did not complete successfully.")
        is_current_page = (
            context.page_generation == self._generation
            and context.profile_id == self._current_profile_id
            and context.page_id == self._current_route_id
        )
        if succeeded and is_current_page and self._current_identity is None:
            self._clear_artifacts()
            if self._current_route_id == HOME_ROUTE_ID:
                self._schedule_shell_context()
            else:
                self.refresh()

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
        self._clear_artifacts()
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
        action_lister = self._action_lister
        configured_diagnostic_read_roots = self._configured_diagnostic_read_roots
        configured_diagnostic_output_root = self._configured_diagnostic_output_root

        def read_shell_context() -> dict[str, Any]:
            raw = shell_loader(
                workspace=workspace,
                profile_id=identity.profile_id,
                bmw_root=bmw_root,
            )
            adapted = adapt_page_payload(raw, workspace=workspace)
            if adapted.get("schemaVersion") == 1:
                return adapted
            adapted["actions"] = []
            selected_profile_id = str(adapted.get("selected_profile_id", "") or "").strip()
            if not selected_profile_id:
                return adapted
            diagnostic_read_roots = _resolve_diagnostic_read_roots(
                workspace,
                configured_diagnostic_read_roots,
            )
            diagnostic_output_root = _resolve_diagnostic_output_root(
                workspace,
                configured_diagnostic_output_root,
            )
            if action_lister is None:
                from sg_preflight.qa_operator_actions import list_sgfx_preflight_actions

                raw_actions = list_sgfx_preflight_actions(workspace)
            else:
                raw_actions = action_lister(workspace)
            if isinstance(raw_actions, (list, tuple)):
                adapted["actions"] = [
                    capability_descriptor(
                        "diagnostic.run",
                        label="Run local QA checks",
                        action_id=str(getattr(action, "action_id", "")),
                    )
                    for action in raw_actions
                    if audit_ui_diagnostic_action(
                        action,
                        read_only_roots=diagnostic_read_roots,
                        output_root=diagnostic_output_root,
                        allowed_output_root=workspace / "out",
                        expected_profile_id=selected_profile_id,
                        owning_page_id=HOME_ROUTE_ID,
                    )
                ]
            return adapted

        return self._submit(identity, read_shell_context)

    def _schedule_page(self, operation: str) -> bool:
        if self._closed:
            return False
        identity = self._next_identity(operation)
        self._prepare_schedule(identity)
        page_loader = self._page_loader
        workspace = self._workspace
        bmw_root = self._bmw_root

        artifact_roots = self._artifact_roots
        action_lister = self._action_lister
        diagnostic_page = identity.page_id in {"full-qa-pass", "batch-full-qa-pass"}
        configured_diagnostic_read_roots = self._configured_diagnostic_read_roots
        configured_diagnostic_output_root = self._configured_diagnostic_output_root

        def read_page() -> dict[str, Any] | _InvalidPagePayload | _PresentedPageResult:
            raw = page_loader(
                page_id=identity.page_id,
                profile_id=identity.profile_id,
                workspace=workspace,
                bmw_root=bmw_root,
            )
            if not isinstance(raw, Mapping):
                return _InvalidPagePayload()
            artifact_candidates = extract_artifact_candidates(
                identity.page_id,
                raw,
                approved_roots=artifact_roots,
            )
            adapted = adapt_page_payload(raw, workspace=workspace)
            try:
                presented = present_page_payload(
                    get_surface_descriptor(identity.page_id),
                    adapted,
                )
            except PagePresentationError:
                return _InvalidPagePayload()
            diagnostic_actions: tuple[dict[str, object], ...] = ()
            if diagnostic_page:
                diagnostic_read_roots = _resolve_diagnostic_read_roots(
                    workspace,
                    configured_diagnostic_read_roots,
                )
                diagnostic_output_root = _resolve_diagnostic_output_root(
                    workspace,
                    configured_diagnostic_output_root,
                )
                if action_lister is None:
                    from sg_preflight.qa_actions import list_operator_actions

                    raw_actions = list_operator_actions(workspace)
                else:
                    raw_actions = action_lister(workspace)
                if isinstance(raw_actions, (list, tuple)):
                    accepted_actions: list[dict[str, object]] = []
                    for action in raw_actions:
                        if bool(getattr(action, "ready", False)) and audit_ui_diagnostic_action(
                            action,
                            read_only_roots=diagnostic_read_roots,
                            output_root=diagnostic_output_root,
                            allowed_output_root=workspace / "out",
                            expected_profile_id=identity.profile_id,
                            owning_page_id=identity.page_id,
                        ):
                            accepted_actions.append(
                                capability_descriptor(
                                    "diagnostic.run",
                                    label=str(getattr(action, "label", "Run diagnostic")),
                                    action_id=str(getattr(action, "action_id", "")),
                                )
                            )
                    diagnostic_actions = tuple(accepted_actions)
            if artifact_candidates or diagnostic_actions:
                return _PresentedPageResult(
                    presented,
                    artifact_candidates,
                    diagnostic_actions,
                )
            return presented

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
        if isinstance(payload, _InvalidPagePayload):
            self._set_payload({})
            self._set_state("error")
            self._set_error(_ui_error(payload.code))
            return
        artifact_candidates: tuple[ArtifactCandidate, ...] = ()
        diagnostic_actions: tuple[dict[str, object], ...] = ()
        if isinstance(payload, _PresentedPageResult):
            artifact_candidates = payload.artifact_candidates
            diagnostic_actions = payload.diagnostic_actions
            payload = payload.payload
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
            self._artifact_candidate_cache[(identity.profile_id, identity.page_id)] = artifact_candidates
            self._diagnostic_action_cache[(identity.profile_id, identity.page_id)] = diagnostic_actions
        self._set_ready_payload(
            normalized,
            artifact_candidates=artifact_candidates,
            diagnostic_actions=diagnostic_actions,
        )

    def _accept_shell_profile(self, payload: Mapping[str, Any]) -> bool:
        if payload.get("schemaVersion") == 1:
            raw_options = payload.get("profileOptions", [])
            raw_selected = payload.get("selectedProfile", {})
            selected = (
                str(raw_selected.get("id", "") or "").strip()
                if isinstance(raw_selected, Mapping)
                else ""
            )
        else:
            raw_options = payload.get("profile_options", [])
            selected = str(payload.get("selected_profile_id", "") or "").strip()
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
        canonical = next(
            (option["id"] for option in options if option["id"].casefold() == selected.casefold()),
            "",
        )
        if selected and not canonical:
            return False
        if not selected and self._current_profile_id:
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
        self._clear_artifacts()
        self._set_state("error")
        self._set_error(_ui_error(code))

    def _set_ready_payload(
        self,
        payload: Mapping[str, Any],
        *,
        artifact_candidates: tuple[ArtifactCandidate, ...] = (),
        diagnostic_actions: tuple[dict[str, object], ...] = (),
    ) -> None:
        normalized = dict(payload)
        if self._current_route_id != HOME_ROUTE_ID:
            identity = ArtifactIdentity(
                self._generation,
                self._current_profile_id,
                self._current_route_id,
            )
            artifacts = self._artifact_registry.accept(identity, artifact_candidates)
            normalized["artifacts"] = artifacts
            normalized["actions"] = self._capability_actions_for_page(
                self._current_route_id,
                artifacts=artifacts,
                diagnostic_actions=diagnostic_actions,
            )
        self._set_payload(normalized)
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

    def _clear_artifacts(self) -> None:
        self._artifact_registry.clear()

    @staticmethod
    def _capability_actions_for_page(
        page_id: str,
        *,
        artifacts: list[dict[str, str]],
        diagnostic_actions: tuple[dict[str, object], ...],
    ) -> list[dict[str, object]]:
        actions = [
            capability_descriptor(
                "page.refresh",
                label="Refresh local evidence",
            )
        ]
        if artifacts:
            actions.append(
                capability_descriptor(
                    "artifact.reveal",
                    label="Reveal selected artifact",
                )
            )
        actions.extend(dict(item) for item in diagnostic_actions)
        if page_id == "manual-review":
            actions.append(
                capability_descriptor(
                    "manual_review.record",
                    label="Record operator verdict",
                )
            )
        if page_id == "operator-handoff":
            actions.append(
                capability_descriptor(
                    "operator_handoff.record",
                    label="Record operator handoff",
                )
            )
        return actions

    def _set_capability_state(self, state: str) -> None:
        if state == self._capability_state:
            return
        self._capability_state = state
        self.capabilityStateChanged.emit()

    def _set_capability_error(self, error: str) -> None:
        if error == self._capability_error:
            return
        self._capability_error = error
        self.capabilityErrorChanged.emit()

    def _set_diagnostic_can_cancel(self, enabled: bool) -> None:
        if enabled == self._diagnostic_can_cancel:
            return
        self._diagnostic_can_cancel = enabled
        self.diagnosticCanCancelChanged.emit()

    def _set_error(self, error: UiError) -> None:
        if error == self._error:
            return
        self._error = error
        self.errorChanged.emit()

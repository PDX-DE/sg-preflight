from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
from typing import Callable

from sg_preflight.qa_operator_actions import OperatorAction
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS


class EffectClass(str, Enum):
    SESSION_STATE = "session_state"
    READ_ONLY = "read_only"
    TOOL_OUTPUT_ONLY = "tool_output_only"
    EXTERNAL_PROCESS = "external_process"


@dataclass(frozen=True, slots=True)
class InputField:
    name: str
    value_kind: str
    required: bool = True
    max_length: int = 0


@dataclass(frozen=True, slots=True)
class UiCapability:
    capability_id: str
    owning_pages: tuple[str, ...]
    input_schema: tuple[InputField, ...]
    effect_class: EffectClass
    confirmation: str
    lifecycle: tuple[str, ...]
    backend_binding: str


class CapabilityEffectExecutor:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sgfx-ui-effect")
        self._closed = False

    @property
    def max_workers(self) -> int:
        return 1

    def submit(self, operation: Callable[[], object]) -> Future[object]:
        if self._closed:
            raise RuntimeError("The capability executor is unavailable.")
        return self._executor.submit(operation)

    def shutdown(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._executor.shutdown(wait=False, cancel_futures=True)


ARTIFACT_REVEAL_SURFACE_IDS = (
    "full-qa-pass",
    "batch-full-qa-pass",
    "delivery-checklist",
    "disabled-tests",
    "api-version-coverage",
    "country-variant-coverage",
    "export-size-trend",
    "screenshot-test-state",
    "risk-score",
    "daily-digest",
    "team-digest-board",
    "manual-review",
)

_PAGE_IDS = tuple(item.surface_id for item in SURFACE_DESCRIPTORS)

UI_CAPABILITIES = (
    UiCapability(
        "profile.select",
        ("shell",),
        (InputField("profile_id", "canonical_profile_id"),),
        EffectClass.SESSION_STATE,
        "selection",
        ("complete",),
        "selectProfile",
    ),
    UiCapability(
        "page.navigate",
        ("shell",),
        (InputField("route_id", "allowed_route_id"),),
        EffectClass.SESSION_STATE,
        "selection",
        ("complete",),
        "navigate",
    ),
    UiCapability(
        "page.refresh",
        ("home", *_PAGE_IDS),
        (),
        EffectClass.READ_ONLY,
        "explicit",
        ("start", "complete", "error"),
        "refresh",
    ),
    UiCapability(
        "artifact.reveal",
        ARTIFACT_REVEAL_SURFACE_IDS,
        (InputField("artifact_id", "opaque_current_payload_id", max_length=128),),
        EffectClass.READ_ONLY,
        "explicit",
        ("complete", "error"),
        "revealArtifact",
    ),
    UiCapability(
        "diagnostic.run",
        ("full-qa-pass", "batch-full-qa-pass"),
        (
            InputField("action_id", "audited_action_id", max_length=128),
            InputField("profile_ids", "canonical_profile_id_list"),
        ),
        EffectClass.TOOL_OUTPUT_ONLY,
        "explicit",
        ("start", "poll", "cancel", "complete", "error"),
        "runDiagnostic",
    ),
    UiCapability(
        "manual_review.record",
        ("manual-review",),
        (
            InputField("step_id", "current_review_step_id", max_length=128),
            InputField("verdict", "allowed_manual_verdict", max_length=32),
            InputField("note", "plain_text", False, 1000),
        ),
        EffectClass.TOOL_OUTPUT_ONLY,
        "explicit",
        ("start", "complete", "error"),
        "recordManualReview",
    ),
    UiCapability(
        "operator_handoff.record",
        ("operator-handoff",),
        (
            InputField("stopping_point", "plain_text", max_length=1000),
            InputField("next_step", "plain_text", False, 1000),
            InputField("note", "plain_text", False, 1000),
        ),
        EffectClass.TOOL_OUTPUT_ONLY,
        "explicit",
        ("start", "complete", "error"),
        "recordOperatorHandoff",
    ),
    UiCapability(
        "grafiks.launch",
        ("shell",),
        (InputField("profile_id", "canonical_profile_id"),),
        EffectClass.EXTERNAL_PROCESS,
        "explicit",
        ("validate", "start", "observe", "restore", "error"),
        "launchGrafiks",
    ),
)

_UI_CAPABILITY_BY_ID = {item.capability_id: item for item in UI_CAPABILITIES}

if len(_UI_CAPABILITY_BY_ID) != len(UI_CAPABILITIES):
    raise RuntimeError("UI capability inventory contains duplicate IDs.")


def get_ui_capability(capability_id: str) -> UiCapability:
    return _UI_CAPABILITY_BY_ID[capability_id]


ALLOWED_DIAGNOSTIC_KINDS = frozenset(
    {
        "daily_live_matrix",
        "profile_stack",
        "repo_checker",
        "unused_resources",
        "delivery_checklist",
        "scene_check",
        "bmw_screenshot_smoke",
    }
)

_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://")
_WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])")
_POSIX_PATH_PATTERN = re.compile(r"(?:^|\s)/(?:[^/\s]+/)*[^\s]*")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\b(?:token|password|secret|pat|api[_-]?key|authorization)\s*[:=])"
)
_APPROVAL_WORDING = (
    "approved",
    "cleared",
    "signed-off",
    "production-ready",
    "validated",
    "verified",
)


def _contained(path: Path, roots: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
        except ValueError:
            continue
        return True
    return False


def _is_reparse_or_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None and isjunction(path):
        return True
    if not os.path.lexists(path):
        return False
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return True
    reparse_flag = int(getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _output_root_is_allowed(output_root: Path, allowed_output_root: Path) -> bool:
    raw_output = Path(os.path.abspath(output_root))
    raw_allowed = Path(os.path.abspath(allowed_output_root))
    try:
        resolved_allowed = raw_allowed.resolve()
        raw_output.resolve().relative_to(resolved_allowed)
    except (OSError, RuntimeError, ValueError):
        return False
    current = raw_output
    while True:
        if _is_reparse_or_link(current):
            return False
        try:
            if current.resolve() == resolved_allowed:
                return True
        except (OSError, RuntimeError):
            return False
        if current.parent == current:
            return False
        current = current.parent


def audit_ui_diagnostic_action(
    action: OperatorAction,
    *,
    read_only_roots: tuple[Path, ...],
    output_root: Path,
    allowed_output_root: Path,
) -> bool:
    if action.kind not in ALLOWED_DIAGNOSTIC_KINDS or action.kind != "delivery_checklist":
        return False
    profile_id = action.profile_id.strip()
    if not _PROFILE_PATTERN.fullmatch(profile_id):
        return False
    if action.action_id.casefold() != f"delivery_checklist__{profile_id.casefold()}":
        return False
    if action.scope != "profile" or not action.project_root:
        return False
    project_root = Path(action.project_root)
    if not project_root.is_dir() or not _contained(project_root, read_only_roots):
        return False
    if not _output_root_is_allowed(output_root, allowed_output_root):
        return False
    resolved_output = output_root.resolve()
    if resolved_output.exists() and not resolved_output.is_dir():
        return False
    return True


def validate_effect_text(
    value: object,
    *,
    required: bool = False,
    max_length: int = 1000,
    evidence_only: bool = False,
) -> str:
    text = str(value or "").strip()
    if required and not text:
        raise ValueError("A required capability field is empty.")
    if len(text) > max_length:
        raise ValueError("A capability field exceeds its maximum length.")
    if any(ord(character) < 32 or ord(character) == 127 for character in text):
        raise ValueError("Capability text contains control characters.")
    if (
        _URL_PATTERN.search(text)
        or _WINDOWS_PATH_PATTERN.search(text)
        or _POSIX_PATH_PATTERN.search(text)
        or _CREDENTIAL_PATTERN.search(text)
    ):
        raise ValueError("Capability text contains disallowed data.")
    if evidence_only and any(token in text.casefold() for token in _APPROVAL_WORDING):
        raise ValueError("Capability text contains approval wording.")
    return text


def capability_descriptor(
    capability_id: str,
    *,
    label: str,
    enabled: bool = True,
    action_id: str = "",
) -> dict[str, object]:
    capability = get_ui_capability(capability_id)
    return {
        "capabilityId": capability.capability_id,
        "label": validate_effect_text(label, required=True, max_length=160),
        "enabled": bool(enabled),
        "actionId": validate_effect_text(action_id, max_length=128),
        "effectClass": capability.effect_class.value,
    }

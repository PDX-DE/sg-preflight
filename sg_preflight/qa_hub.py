from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any


_PROFILE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://")
_WINDOWS_PATH_PATTERN = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])")
_POSIX_PATH_PATTERN = re.compile(r"(?:^|\s)/(?:[^/\s]+/)*[^\s]*")
_CREDENTIAL_PATTERN = re.compile(
    r"(?i)(?:\bbearer\s+\S+|\b(?:token|password|secret|pat|api[_-]?key|authorization)\s*[:=])"
)
QA_HUB_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class QaGateDefinition:
    gate_id: str
    label: str
    route_ids: tuple[str, ...]
    default_state: str
    owner_label: str


QA_GATES = (
    QaGateDefinition("context", "Project context", ("setup-doctor",), "not_recorded", "Operator"),
    QaGateDefinition("asset", "Asset integrity", ("full-qa-pass",), "not_run", "Seriengrafik"),
    QaGateDefinition(
        "interface",
        "Export & interface",
        ("api-version-coverage", "disabled-tests", "export-size-trend"),
        "external",
        "Pipeline owner",
    ),
    QaGateDefinition(
        "variants",
        "Variants",
        ("country-variant-coverage",),
        "not_recorded",
        "Topic owner",
    ),
    QaGateDefinition(
        "visual",
        "Visual evidence",
        ("screenshot-test-state",),
        "external",
        "Visual reviewer",
    ),
    QaGateDefinition(
        "review",
        "Review & decisions",
        ("risk-score", "manual-review"),
        "human_review",
        "Reviewer",
    ),
    QaGateDefinition(
        "delivery",
        "Delivery & handoff",
        ("delivery-checklist", "operator-handoff"),
        "human_review",
        "Project coordinator",
    ),
)


def _plain_text(value: object, *, fallback: str = "", max_length: int = 240) -> str:
    if isinstance(value, BaseException):
        return fallback
    text = str(value or "").strip()
    if (
        not text
        or len(text) > max_length
        or any(ord(character) < 32 or ord(character) == 127 for character in text)
        or _URL_PATTERN.search(text)
        or _WINDOWS_PATH_PATTERN.search(text)
        or _POSIX_PATH_PATTERN.search(text)
        or _CREDENTIAL_PATTERN.search(text)
    ):
        return fallback
    return text


def _identifier(value: object) -> str:
    text = _plain_text(value, max_length=128)
    return text if _IDENTIFIER_PATTERN.fullmatch(text) else ""


def _timestamp(value: object) -> str:
    text = _plain_text(value, max_length=64)
    if not text:
        return ""
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return ""
    return text


def _value(source: object, key: str, default: object = "") -> object:
    if isinstance(source, Mapping):
        return source.get(key, default)
    if isinstance(source, BaseException):
        return default
    return getattr(source, key, default)


def _safe_profile_options(profile_options: Sequence[object]) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in profile_options[:128]:
        if not isinstance(item, Mapping):
            continue
        profile_id = _plain_text(item.get("id", ""), max_length=64)
        folded = profile_id.casefold()
        if not _PROFILE_PATTERN.fullmatch(profile_id) or folded in seen:
            continue
        seen.add(folded)
        label = _plain_text(item.get("label", ""), fallback=profile_id, max_length=120)
        options.append({"id": profile_id, "label": label})
    return options


def _matching_action(actions: Sequence[object], profile_id: str) -> dict[str, str] | None:
    expected_action_id = f"sgfx_preflight__{profile_id.casefold()}"
    for item in actions[:12]:
        if not isinstance(item, Mapping):
            continue
        if (
            str(item.get("capabilityId", "")) == "diagnostic.run"
            and str(item.get("actionId", "")).casefold() == expected_action_id
            and bool(item.get("enabled", False))
        ):
            return {
                "routeId": "",
                "capabilityId": "diagnostic.run",
                "actionId": expected_action_id,
            }
    return None


def _count(summary: object, key: str) -> int | None:
    if not isinstance(summary, Mapping):
        return None
    value = summary.get(key, 0)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _matching_action_record(action_records: Sequence[object], profile_id: str) -> dict[str, Any] | None:
    expected_action_id = f"sgfx_preflight__{profile_id.casefold()}"
    for record in action_records[:12]:
        if (
            str(_value(record, "kind", "")) != "sgfx_preflight"
            or str(_value(record, "profile_id", "")).casefold() != profile_id.casefold()
            or str(_value(record, "action_id", "")).casefold() != expected_action_id
        ):
            continue
        # This is the newest matching run. If it is unreadable, report no local run at all
        # rather than falling through to an older record and presenting stale results as current.
        status = str(_value(record, "status", "")).strip().lower()
        if status not in {"queued", "running", "completed", "failed"}:
            return None
        summary = _value(record, "summary", None)
        errors = _count(summary, "errors")
        warnings = _count(summary, "warnings")
        info = _count(summary, "info")
        if status == "completed" and None in {errors, warnings, info}:
            return None
        child_run_id = _identifier(summary.get("child_run_id", "")) if isinstance(summary, Mapping) else ""
        timestamp = (
            _timestamp(_value(record, "completed_at_utc", ""))
            or _timestamp(_value(record, "started_at_utc", ""))
            or _timestamp(_value(record, "created_at_utc", ""))
        )
        # The probe stage travels inside the same record snapshot as the core result, so a stale
        # completion can never pair old probe rows with a newer core verdict (req 23).
        probe: dict[str, Any] | None = None
        stage = summary.get("ramses_r0") if isinstance(summary, Mapping) else None
        if isinstance(stage, Mapping):
            family = str(stage.get("family", ""))
            if family in {"evidence", "execution_failure", "unavailable"}:
                probe = {
                    "family": family,
                    "outcome": _identifier(stage.get("outcome", "")),
                    "reason": _identifier(stage.get("reason", "")),
                    "errors": _count(stage, "finding_errors") or 0,
                    "warnings": _count(stage, "finding_warnings") or 0,
                    "recorded": stage.get("evidence_recorded", False) is True,
                }
        return {
            "actionId": expected_action_id,
            "actionRunId": _identifier(_value(record, "run_id", "")),
            "childRunId": child_run_id,
            "timestamp": timestamp,
            "status": status,
            "errors": errors or 0,
            "warnings": warnings or 0,
            "info": info or 0,
            "ramsesProbe": probe,
        }
    return None


def _matching_child_run(run_records: Sequence[object], profile_id: str, run_id: str) -> str:
    if not run_id:
        return ""
    for record in run_records[:12]:
        if (
            str(_value(record, "profile_id", "")).casefold() == profile_id.casefold()
            and _identifier(_value(record, "run_id", "")) == run_id
        ):
            return run_id
    return ""


def _asset_state(record: Mapping[str, Any] | None) -> str:
    if record is None:
        return "not_run"
    status = str(record.get("status", ""))
    if status in {"queued", "running", "failed"}:
        return status
    if status == "completed":
        if int(record.get("errors", 0)) or int(record.get("warnings", 0)):
            return "findings"
        return "passed"
    return "not_run"


def _action_identity(action: Mapping[str, Any] | None) -> dict[str, str]:
    if action is None:
        return {"routeId": "", "capabilityId": "", "actionId": ""}
    return {
        "routeId": str(action.get("routeId", "")),
        "capabilityId": str(action.get("capabilityId", "")),
        "actionId": str(action.get("actionId", "")),
    }


def _next_action(
    selected_profile_id: str,
    asset_state: str,
    action: Mapping[str, Any] | None,
) -> dict[str, str]:
    if not selected_profile_id:
        return {
            "kind": "select_profile",
            "label": "Choose profile",
            "routeId": "",
            "capabilityId": "",
            "actionId": "",
        }
    if asset_state in {"queued", "running"}:
        return {
            "kind": "wait",
            "label": "Local QA checks are running",
            "routeId": "",
            "capabilityId": "",
            "actionId": "",
        }
    if asset_state == "failed":
        return {
            "kind": "retry",
            "label": "Retry local QA checks",
            **_action_identity(action),
        }
    if asset_state == "findings":
        return {
            "kind": "review",
            "label": "Review local findings",
            "routeId": "full-qa-pass",
            "capabilityId": "page.navigate",
            "actionId": "",
        }
    if asset_state in {"not_run", "not_recorded"} and action is not None:
        return {
            "kind": "run",
            "label": "Run local QA checks",
            **_action_identity(action),
        }
    return {
        "kind": "review",
        "label": "Continue with export and interface evidence",
        "routeId": "api-version-coverage",
        "capabilityId": "page.navigate",
        "actionId": "",
    }


def _asset_summary(state: str, record: Mapping[str, Any] | None) -> str:
    if state == "not_run":
        return "Local QA checks have not run for this profile."
    if state == "queued":
        return "Local QA checks are queued."
    if state == "running":
        return "Local QA checks are running."
    if state == "failed":
        return "Local QA checks did not complete."
    if record is None:
        return "Local QA evidence is unavailable."
    errors = int(record.get("errors", 0))
    warnings = int(record.get("warnings", 0))
    info = int(record.get("info", 0))
    return f"Local QA result: {errors} errors, {warnings} warnings, {info} info."


def _ramses_check_rows(
    record: Mapping[str, Any] | None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    # Design section 13: probe results touch only exact Ramses check rows. Export & interface
    # carries the validation evidence, review carries the logic evidence; a clean row may read
    # scoped `passed` while its gate, the profile, and delivery stay independent; unavailable
    # adds nothing at all.
    probe = record.get("ramsesProbe") if isinstance(record, Mapping) else None
    if not isinstance(probe, Mapping) or probe.get("family") == "unavailable":
        return [], []
    if probe.get("family") == "execution_failure":
        return [
            {
                "id": "ramses-validation",
                "label": "Ramses scene probe",
                "state": "failed",
                "summary": "The scene probe did not complete; the local QA result stands on its own.",
                "routeId": "api-version-coverage",
            }
        ], []
    if probe.get("outcome") != "completed":
        # A classified diagnostic (for example an incompatible scene) is honest evidence of a
        # scene that could not be validated - it must never read like a validated clean scene,
        # and it only points at evidence that was actually retained.
        summary = (
            "The scene could not be validated; see the probe evidence."
            if probe.get("recorded")
            else "The scene could not be validated."
        )
        return [
            {
                "id": "ramses-validation",
                "label": "Ramses scene validation",
                "state": "failed",
                "summary": summary,
                "routeId": "api-version-coverage",
            }
        ], []
    errors = int(probe.get("errors", 0))
    warnings = int(probe.get("warnings", 0))
    state = "findings" if errors or warnings else "passed"
    interface_row = {
        "id": "ramses-validation",
        "label": "Ramses scene validation",
        "state": state,
        "summary": f"Scene validation recorded {errors} errors, {warnings} warnings. Evidence only.",
        "routeId": "api-version-coverage",
    }
    review_row = {
        "id": "ramses-logic",
        "label": "Ramses logic evidence",
        "state": "recorded",
        "summary": "Default logic update evidence recorded; manual review remains required.",
        "routeId": "risk-score",
    }
    return [interface_row], [review_row]


def _gate_payloads(
    selected_profile_id: str,
    asset_state: str,
    record: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    interface_rows, review_rows = _ramses_check_rows(record)
    gates: list[dict[str, Any]] = []
    for definition in QA_GATES:
        state = definition.default_state
        summary = f"Evidence is owned by {definition.owner_label}."
        checks = [
            {
                "id": f"{definition.gate_id}-evidence",
                "label": definition.label,
                "state": state,
                "summary": summary,
                "routeId": definition.route_ids[0] if definition.route_ids else "",
            }
        ]
        if definition.gate_id == "context":
            state = "available" if selected_profile_id else "not_recorded"
            summary = (
                f"Profile {selected_profile_id} is selected."
                if selected_profile_id
                else "Choose a profile to establish QA context."
            )
            checks = [
                {
                    "id": "selected-profile",
                    "label": "Selected profile",
                    "state": state,
                    "summary": summary,
                    "routeId": "setup-doctor",
                }
            ]
        elif definition.gate_id == "asset":
            state = asset_state
            summary = _asset_summary(asset_state, record)
            checks = [
                {
                    "id": "local-preflight",
                    "label": "Local QA checks",
                    "state": asset_state,
                    "summary": summary,
                    "routeId": "full-qa-pass",
                }
            ]
            if record is not None:
                checks.extend(
                    [
                        {
                            "id": "errors",
                            "label": "Errors",
                            "state": asset_state,
                            "summary": str(int(record.get("errors", 0))),
                            "routeId": "full-qa-pass",
                        },
                        {
                            "id": "warnings",
                            "label": "Warnings",
                            "state": asset_state,
                            "summary": str(int(record.get("warnings", 0))),
                            "routeId": "full-qa-pass",
                        },
                        {
                            "id": "info",
                            "label": "Info",
                            "state": asset_state,
                            "summary": str(int(record.get("info", 0))),
                            "routeId": "full-qa-pass",
                        },
                    ]
                )
        if definition.gate_id == "interface":
            checks = checks + interface_rows
        elif definition.gate_id == "review":
            checks = checks + review_rows
        gates.append(
            {
                "id": definition.gate_id,
                "label": definition.label,
                "state": state,
                "summary": summary,
                "ownerLabel": definition.owner_label,
                "routeIds": list(definition.route_ids),
                "checks": checks[:4],
            }
        )
    return gates


def _safe_activity(activity: Sequence[object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in activity[:5]:
        if not isinstance(item, Mapping):
            continue
        label = _plain_text(item.get("label", ""), fallback="Recent activity", max_length=120)
        status = _plain_text(item.get("status", ""), fallback="recorded", max_length=32)
        detail = _plain_text(item.get("detail", ""), fallback="", max_length=240)
        if not detail:
            continue
        rows.append({"label": label, "status": status, "detail": detail})
    return rows


def render_qa_evidence_summary(snapshot: Mapping[str, Any]) -> str:
    selected = snapshot.get("selectedProfile", {})
    profile_id = str(selected.get("id", "")) if isinstance(selected, Mapping) else ""
    latest = snapshot.get("latestLocalRun", {})
    errors = int(latest.get("errors", 0)) if isinstance(latest, Mapping) else 0
    warnings = int(latest.get("warnings", 0)) if isinstance(latest, Mapping) else 0
    info = int(latest.get("info", 0)) if isinstance(latest, Mapping) else 0
    next_action = snapshot.get("nextAction", {})
    next_label = str(next_action.get("label", "")) if isinstance(next_action, Mapping) else ""
    gates = snapshot.get("gates", [])
    open_owners = []
    if isinstance(gates, Sequence):
        for gate in gates:
            if not isinstance(gate, Mapping):
                continue
            if str(gate.get("state", "")) in {"external", "human_review", "not_recorded"}:
                owner = str(gate.get("ownerLabel", ""))
                if owner and owner not in open_owners:
                    open_owners.append(owner)
    owners = ", ".join(open_owners) or "None recorded"
    return (
        f"SGFX QA evidence | Profile: {profile_id or 'not selected'} | "
        f"Findings: {errors} errors, {warnings} warnings, {info} info | "
        f"Open owners: {owners} | Next: {next_label or 'Choose profile'}"
    )


def build_qa_hub_snapshot(
    *,
    workspace: Path | str,
    profile_options: Sequence[object],
    selected_profile_id: str,
    actions: Sequence[object],
    action_records: Sequence[object],
    run_records: Sequence[object],
    activity: Sequence[object],
) -> dict[str, Any]:
    Path(workspace)
    options = _safe_profile_options(profile_options)
    requested = _plain_text(selected_profile_id, max_length=64)
    selected = next(
        (option for option in options if option["id"].casefold() == requested.casefold()),
        None,
    )
    selected_id = selected["id"] if selected is not None else ""
    action = _matching_action(actions, selected_id) if selected_id else None
    record = _matching_action_record(action_records, selected_id) if selected_id else None
    state = _asset_state(record)
    next_action = _next_action(selected_id, state, action)
    gates = _gate_payloads(selected_id, state, record)
    latest_local_run: dict[str, Any] = {}
    if record is not None:
        child_run_id = str(record.get("childRunId", ""))
        confirmed_child_run_id = _matching_child_run(run_records, selected_id, child_run_id)
        latest_local_run = {
            "actionId": str(record.get("actionId", "")),
            "runId": confirmed_child_run_id or child_run_id or str(record.get("actionRunId", "")),
            "timestamp": str(record.get("timestamp", "")),
            "state": state,
            "errors": int(record.get("errors", 0)),
            "warnings": int(record.get("warnings", 0)),
            "info": int(record.get("info", 0)),
        }
    context_fields = [
        {
            "id": "profile",
            "label": "Profile",
            "value": selected["label"] if selected is not None else "Choose profile",
        },
        {"id": "scope", "label": "Scope", "value": "3D Car QA"},
    ]
    snapshot: dict[str, Any] = {
        "schemaVersion": QA_HUB_SCHEMA_VERSION,
        "scopeLabel": "3D Car QA",
        "selectedProfile": dict(selected) if selected is not None else {},
        "profileOptions": options,
        "contextFields": context_fields,
        "gates": gates,
        "selectedGateId": "asset" if selected_id else "context",
        "latestLocalRun": latest_local_run,
        "nextAction": next_action,
        "activity": _safe_activity(activity),
        "readOnly": True,
        "isApproval": False,
    }
    if latest_local_run:
        latest_local_run["evidenceSummary"] = render_qa_evidence_summary(snapshot)
    return snapshot

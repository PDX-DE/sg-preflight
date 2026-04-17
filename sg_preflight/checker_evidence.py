from __future__ import annotations

import ast
import re
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any


EVIDENCE_VERSION = 1

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_PHASE_RE = re.compile(r"starting\s+(\w+)\s+on\s+(\d+)\s+files", flags=re.IGNORECASE)
_ERROR_COUNT_RE = re.compile(r"(\d+)\s+errors found", flags=re.IGNORECASE)
_CHECKED_RE = re.compile(
    r"checked\s+(\d+)\s+files\s+\(src:\s*(\d+);\s*fmt:\s*(\d+);\s*license:\s*(\d+)\)",
    flags=re.IGNORECASE,
)
_ISSUE_COUNT_RE = re.compile(r"detected\s+(\d+)\s+style guide issues", flags=re.IGNORECASE)
_WARNING_RE = re.compile(
    r"(?P<path>[A-Za-z]:[\\/][^()\r\n]+)\((?P<line>\d+)\):\s+warning\s+PRJ9999:\s+(?P<message>.+?)\s+\[(?P<rule>[^\]]+)\]",
    flags=re.IGNORECASE,
)
_NO_SPACING_RE = re.compile(
    r"check_no_spacing_line_end\s+(?P<path>[A-Za-z]:[\\/][^\s]+)\s+(?P<line>\d+)",
    flags=re.IGNORECASE,
)
_BINARY_RE = re.compile(
    r"binary file:\s+(?P<path>[A-Za-z]:[\\/].+?)\s+seems to have invalid location",
    flags=re.IGNORECASE,
)
_FILE_ISSUE_RE = re.compile(
    r"(?P<path>[A-Za-z]:[\\/].+?)(?::(?P<line>\d+))(?:[:](?P<column>\d+))?:\s+(?P<message>.+)"
)
_SCENE_START_RE = re.compile(r"^Checking scene:\s+(?P<path>.+)$")
_DELIVERY_LOG_RE = re.compile(r"^(?P<key>[a-z0-9_]+)=(?P<path>.+?)\s+::\s+(?P<status>available|missing)$", flags=re.IGNORECASE)


def _clean_text(text: str) -> str:
    return _ANSI_RE.sub("", text.replace("\r\n", "\n").replace("\r", "\n")).lstrip("\ufeff")


def _normalize_path(path: str) -> str:
    cleaned = path.strip().strip('"').strip("'")
    if re.match(r"^[A-Za-z]:[\\/]", cleaned):
        return str(PureWindowsPath(cleaned))
    return cleaned


def _bytes_literal_line(line: str) -> str | None:
    candidate = line.strip()
    if not candidate.startswith(("b'", 'b"')):
        return None
    try:
        payload = ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(payload, (bytes, bytearray)):
        return None
    return payload.decode("utf-8", errors="replace")


def _severity_rank(value: str) -> int:
    severity = value.lower()
    if severity == "error":
        return 3
    if severity == "warning":
        return 2
    if severity == "info":
        return 1
    return 0


def _checker_status(issue_count: int) -> str:
    return "warning" if issue_count > 0 else "clean"


def _empty_evidence(*, source_kind: str, raw_log_path: str = "") -> dict[str, Any]:
    return {
        "evidence_version": EVIDENCE_VERSION,
        "source_kind": source_kind,
        "raw_log_path": raw_log_path,
        "checkers": [],
        "affected_files": [],
        "top_paths": [],
        "manual_followups": [],
        "summary_only": True,
    }


def _issue_key(issue: dict[str, Any]) -> tuple[Any, ...]:
    return (
        issue.get("path"),
        issue.get("checker"),
        issue.get("rule"),
        issue.get("line"),
        issue.get("message"),
    )


def _append_issue(payload: dict[str, Any], issue: dict[str, Any], seen: set[tuple[Any, ...]]) -> None:
    key = _issue_key(issue)
    if key in seen:
        return
    seen.add(key)
    payload["affected_files"].append(issue)


def _top_paths(affected_files: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for issue in affected_files:
        path = str(issue.get("path", "")).strip()
        if not path:
            continue
        bucket = grouped.setdefault(
            path,
            {
                "path": path,
                "issue_count": 0,
                "checkers": set(),
                "severity": str(issue.get("severity", "warning")).lower(),
                "message": str(issue.get("message", "")).strip(),
                "line": issue.get("line"),
                "source_kind": str(issue.get("source_kind", "")).strip(),
                "priority": int(issue.get("priority", 100)),
            },
        )
        bucket["issue_count"] += 1
        bucket["checkers"].add(str(issue.get("checker", "")).strip())
        if _severity_rank(str(issue.get("severity", ""))) > _severity_rank(str(bucket.get("severity", ""))):
            bucket["severity"] = str(issue.get("severity", "")).lower()
        if not bucket.get("message") and issue.get("message"):
            bucket["message"] = str(issue.get("message", "")).strip()
        if bucket.get("line") in (None, "") and issue.get("line") not in (None, ""):
            bucket["line"] = issue.get("line")
        bucket["priority"] = min(int(bucket.get("priority", 100)), int(issue.get("priority", 100)))

    items = []
    for item in grouped.values():
        checkers = sorted(checker for checker in item.pop("checkers") if checker)
        items.append(
            {
                **item,
                "checker": checkers[0] if checkers else "",
                "checkers": checkers,
            }
        )
    items.sort(
        key=lambda item: (
            -_severity_rank(str(item.get("severity", ""))),
            int(item.get("priority", 100)),
            -int(item.get("issue_count", 0)),
            str(item.get("path", "")).lower(),
        )
    )
    return items[:5]


def _manual_followups(top_paths: list[dict[str, Any]], *, source_kind: str) -> list[str]:
    notes: list[str] = []
    for item in top_paths[:3]:
        path = str(item.get("path", "")).strip()
        if not path:
            continue
        line = item.get("line")
        checker = str(item.get("checker", "")).strip() or source_kind
        message = str(item.get("message", "")).strip() or "reported a checker issue"
        suffix = f" line {line}" if line not in (None, "") else ""
        notes.append(f"Open {path}{suffix} first. {checker} reported: {message}")
    if not notes:
        notes.append("Open the raw log first because the checker output did not resolve to file-backed evidence.")
    return notes


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    affected_files = payload.get("affected_files", [])
    top_paths = _top_paths(affected_files)
    payload["top_paths"] = top_paths
    payload["manual_followups"] = _manual_followups(top_paths, source_kind=str(payload.get("source_kind", "")))
    payload["summary_only"] = not bool(affected_files)
    return payload


def _checker_for_rule(rule: str) -> str:
    normalized = rule.strip().lower()
    if normalized in {"check_correct_space_count", "check_tabs_no_spaces", "check_no_spacing_line_end"}:
        return "tabbingcheck"
    if normalized == "check_last_line_newline":
        return "newlinecheck"
    return "style_checker"


def _file_issue_from_text(
    text: str,
    *,
    checker: str,
    rule: str,
    source_kind: str,
    severity: str = "warning",
) -> dict[str, Any] | None:
    match = _FILE_ISSUE_RE.match(text.strip())
    if match is None:
        return None
    line = match.group("line")
    column = match.group("column")
    return {
        "path": _normalize_path(match.group("path")),
        "checker": checker,
        "rule": rule,
        "severity": severity,
        "line": int(line) if line else None,
        "column": int(column) if column else None,
        "message": match.group("message").strip(),
        "excerpt": "",
        "source_kind": source_kind,
    }


def parse_style_checker_output(
    output: str,
    *,
    raw_log_path: str = "",
    source_kind: str = "repo_checker",
) -> dict[str, Any]:
    text = _clean_text(output)
    payload = _empty_evidence(source_kind=source_kind, raw_log_path=raw_log_path)
    seen: set[tuple[Any, ...]] = set()

    checked_match = _CHECKED_RE.search(text)
    issue_match = _ISSUE_COUNT_RE.search(text)
    clean = "no style guide violations detected" in text.lower()
    checked_files = int(checked_match.group(1)) if checked_match else 0
    src_files = int(checked_match.group(2)) if checked_match else 0
    formatting_files = int(checked_match.group(3)) if checked_match else 0
    license_files = int(checked_match.group(4)) if checked_match else 0
    reported_issues = int(issue_match.group(1)) if issue_match else 0

    for match in _WARNING_RE.finditer(text):
        _append_issue(
            payload,
            {
                "path": _normalize_path(match.group("path")),
                "checker": "style_checker",
                "rule": match.group("rule").strip(),
                "severity": "warning",
                "line": int(match.group("line")),
                "column": None,
                "message": match.group("message").strip(),
                "excerpt": "",
                "source_kind": source_kind,
            },
            seen,
        )

    observed_issues = len(payload["affected_files"])
    payload["checkers"].append(
        {
            "name": "style_checker",
            "files_checked": checked_files,
            "issues": reported_issues or observed_issues,
            "status": "clean" if clean and (reported_issues or observed_issues) == 0 else _checker_status(reported_issues or observed_issues),
            "src_files": src_files,
            "formatting_files": formatting_files,
            "license_files": license_files,
        }
    )
    return _finalize(payload)


def parse_execute_checks_output(
    output: str,
    *,
    raw_log_path: str = "",
    source_kind: str = "repo_checker",
) -> dict[str, Any]:
    text = _clean_text(output)
    payload = _empty_evidence(source_kind=source_kind, raw_log_path=raw_log_path)
    seen: set[tuple[Any, ...]] = set()
    phase_counts: dict[str, int] = {}
    phase_error_counts: dict[str, int] = {}
    current_phase = ""
    pending_spacing: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if pending_spacing is not None:
                pending_spacing = None
            continue

        phase_match = _PHASE_RE.search(line)
        if phase_match is not None:
            current_phase = phase_match.group(1).strip().lower()
            phase_counts[current_phase] = int(phase_match.group(2))
            pending_spacing = None
            continue

        error_count_match = _ERROR_COUNT_RE.search(line)
        if error_count_match is not None and current_phase:
            phase_error_counts[current_phase] = int(error_count_match.group(1))
            pending_spacing = None
            continue

        spacing_match = _NO_SPACING_RE.match(line)
        if spacing_match is not None:
            pending_spacing = {
                "path": _normalize_path(spacing_match.group("path")),
                "line": int(spacing_match.group("line")),
            }
            continue

        if pending_spacing is not None:
            if line.lower().startswith("unneeded space(s) at end of line"):
                _append_issue(
                    payload,
                    {
                        "path": pending_spacing["path"],
                        "checker": "tabbingcheck",
                        "rule": "check_no_spacing_line_end",
                        "severity": "warning",
                        "line": pending_spacing["line"],
                        "column": None,
                        "message": line,
                        "excerpt": "",
                        "source_kind": source_kind,
                    },
                    seen,
                )
            pending_spacing = None
            continue

        warning_match = _WARNING_RE.match(line)
        if warning_match is not None:
            rule = warning_match.group("rule").strip()
            _append_issue(
                payload,
                {
                    "path": _normalize_path(warning_match.group("path")),
                    "checker": _checker_for_rule(rule),
                    "rule": rule,
                    "severity": "warning",
                    "line": int(warning_match.group("line")),
                    "column": None,
                    "message": warning_match.group("message").strip(),
                    "excerpt": "",
                    "source_kind": source_kind,
                },
                seen,
            )
            continue

        binary_match = _BINARY_RE.match(line)
        if binary_match is not None:
            _append_issue(
                payload,
                {
                    "path": _normalize_path(binary_match.group("path")),
                    "checker": "binarycheck",
                    "rule": "invalid_binary_location",
                    "severity": "warning",
                    "line": None,
                    "column": None,
                    "message": "binary file seems to have invalid location",
                    "excerpt": "",
                    "source_kind": source_kind,
                },
                seen,
            )
            continue

        decoded = _bytes_literal_line(line)
        if decoded:
            issue = _file_issue_from_text(
                decoded,
                checker=current_phase or "executeChecks",
                rule=current_phase or "executeChecks",
                source_kind=source_kind,
            )
            if issue is not None:
                _append_issue(payload, issue, seen)
            continue

        direct_issue = _file_issue_from_text(
            line,
            checker=current_phase or "executeChecks",
            rule=current_phase or "executeChecks",
            source_kind=source_kind,
        )
        if direct_issue is not None:
            _append_issue(payload, direct_issue, seen)

    checker_names = set(phase_counts)
    checker_names.update(
        str(item.get("checker", "")).strip()
        for item in payload["affected_files"]
        if str(item.get("checker", "")).strip()
    )
    for name in sorted(checker_names):
        files_checked = phase_counts.get(name, 0)
        observed = sum(1 for item in payload["affected_files"] if item.get("checker") == name)
        reported = phase_error_counts.get(name, observed)
        issues = max(observed, reported)
        payload["checkers"].append(
            {
                "name": name,
                "files_checked": files_checked,
                "issues": issues,
                "status": _checker_status(issues),
            }
        )

    return _finalize(payload)


def merge_checker_evidence(*items: dict[str, Any]) -> dict[str, Any]:
    if not items:
        return _finalize(_empty_evidence(source_kind="repo_checker"))

    merged = _empty_evidence(
        source_kind=str(items[0].get("source_kind", "repo_checker")),
        raw_log_path=str(items[0].get("raw_log_path", "")),
    )
    seen: set[tuple[Any, ...]] = set()
    checker_map: dict[str, dict[str, Any]] = {}

    for item in items:
        for checker in item.get("checkers", []):
            if not isinstance(checker, dict):
                continue
            name = str(checker.get("name", "")).strip()
            if not name:
                continue
            existing = checker_map.get(name)
            if existing is None:
                checker_map[name] = dict(checker)
                continue
            existing["files_checked"] = max(int(existing.get("files_checked", 0)), int(checker.get("files_checked", 0)))
            existing["issues"] = max(int(existing.get("issues", 0)), int(checker.get("issues", 0)))
            existing["status"] = "warning" if existing.get("issues", 0) else checker.get("status", "clean")
        for affected in item.get("affected_files", []):
            if isinstance(affected, dict):
                _append_issue(merged, dict(affected), seen)

    merged["checkers"] = [checker_map[name] for name in sorted(checker_map)]
    return _finalize(merged)


def parse_repo_checker_outputs(
    style_output: str,
    execute_output: str,
    *,
    raw_log_path: str = "",
) -> dict[str, Any]:
    style_evidence = parse_style_checker_output(
        style_output,
        raw_log_path=raw_log_path,
        source_kind="repo_checker",
    )
    execute_evidence = parse_execute_checks_output(
        execute_output,
        raw_log_path=raw_log_path,
        source_kind="repo_checker",
    )
    return merge_checker_evidence(style_evidence, execute_evidence)


def parse_repo_checker_log(output: str, *, raw_log_path: str = "") -> dict[str, Any]:
    style_output = output
    execute_output = ""
    if "=== check_all_styles.py ===" in output and "=== executeChecks.py ===" in output:
        style_output = output.split("=== check_all_styles.py ===", 1)[1].split("=== executeChecks.py ===", 1)[0].strip()
        execute_output = output.split("=== executeChecks.py ===", 1)[1].strip()
    return parse_repo_checker_outputs(style_output, execute_output, raw_log_path=raw_log_path)


def parse_scene_check_output(
    output: str,
    *,
    raw_log_path: str = "",
    workbook_path: str = "",
) -> dict[str, Any]:
    text = _clean_text(output)
    payload = _empty_evidence(source_kind="scene_check", raw_log_path=raw_log_path)
    payload["workbook_path"] = workbook_path
    seen: set[tuple[Any, ...]] = set()
    checked_scenes = 0
    scenes_with_errors = 0
    current_scene = ""
    current_error: list[str] = []
    scene_issue_indexes: dict[str, int] = {}

    def flush_error() -> None:
        nonlocal scenes_with_errors
        if not current_scene or not current_error:
            return
        block = "\n".join(current_error).strip()
        condensed = current_error[0]
        _append_issue(
            payload,
            {
                "path": current_scene,
                "checker": "scene_check",
                "rule": "scene_error",
                "severity": "error",
                "line": None,
                "column": None,
                "message": condensed,
                "excerpt": block,
                "source_kind": "scene_check",
            },
            seen,
        )
        scene_issue_indexes[current_scene] = scene_issue_indexes.get(current_scene, 0) + 1
        scenes_with_errors_for_path = sum(1 for item in payload["affected_files"] if item.get("path") == current_scene)
        if scenes_with_errors_for_path == 1:
            scenes_with_errors += 1

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        scene_match = _SCENE_START_RE.match(line.strip())
        if scene_match is not None:
            if current_error:
                flush_error()
                current_error = []
            current_scene = _normalize_path(scene_match.group("path"))
            checked_scenes += 1
            continue
        if not current_scene:
            continue
        if line.startswith("[E]"):
            if current_error:
                flush_error()
            current_error = [line]
            continue
        if current_error:
            if line.startswith("[") or not line.strip():
                flush_error()
                current_error = []
            else:
                current_error.append(line)

    if current_error:
        flush_error()

    payload["checked_scenes"] = checked_scenes
    payload["scenes_with_errors"] = scenes_with_errors
    payload["checkers"].append(
        {
            "name": "scene_check",
            "files_checked": checked_scenes,
            "issues": scenes_with_errors,
            "status": "error" if scenes_with_errors else "clean",
        }
    )
    return _finalize(payload)


def parse_unused_resources_output(
    output: str,
    *,
    raw_log_path: str = "",
) -> dict[str, Any]:
    text = _clean_text(output)
    payload = _empty_evidence(source_kind="unused_resources", raw_log_path=raw_log_path)
    seen: set[tuple[Any, ...]] = set()

    for raw_line in text.splitlines():
        candidate = raw_line.strip()
        if not candidate or candidate.startswith("Traceback") or candidate.lower().startswith("usage:"):
            continue
        path = _normalize_path(candidate)
        suffix = Path(path).suffix.lower()
        if suffix not in {".lua", ".png", ".vert", ".frag", ".gltf"}:
            continue
        _append_issue(
            payload,
            {
                "path": path,
                "checker": "unused_resources",
                "rule": "unused_resource",
                "severity": "warning",
                "line": None,
                "column": None,
                "message": "Resource was not referenced by any scanned `.rca` scene.",
                "excerpt": "",
                "source_kind": "unused_resources",
                "priority": 10,
            },
            seen,
        )

    payload["checkers"].append(
        {
            "name": "unused_resources",
            "files_checked": 0,
            "issues": len(payload["affected_files"]),
            "status": _checker_status(len(payload["affected_files"])),
        }
    )
    return _finalize(payload)


def parse_delivery_checklist_log(
    output: str,
    *,
    raw_log_path: str = "",
) -> dict[str, Any]:
    text = _clean_text(output)
    payload = _empty_evidence(source_kind="delivery_checklist", raw_log_path=raw_log_path)
    seen: set[tuple[Any, ...]] = set()
    local_asset_count = 0
    local_asset_missing = 0
    bmw_missing: list[str] = []
    viewer_hits = 0

    label_map = {
        "delivery_checklist_readme": ("delivery_checklist", "readme_available", 1, "Mirrored deliveryChecklist README is available locally."),
        "delivery_checklist_helper": ("delivery_checklist", "helper_available", 2, "Mirrored deliveryChecklist Python helper is available locally."),
        "delivery_checklist_camera_crane": ("delivery_checklist", "camera_crane_available", 3, "Mirrored deliveryChecklist cameraCrane helper is available locally."),
        "delivery_checklist_tool": ("delivery_checklist", "tool_available", 4, "Mirrored deliveryChecklist executable is available locally."),
        "bmw_car_manager_script": ("bmw_delivery_prereqs", "car_manager_available", 5, "BMW car_manager helper is available locally."),
        "bmw_test_main_script": ("bmw_delivery_prereqs", "test_main_available", 6, "BMW test/main helper is available locally."),
        "viewer_candidate": ("bmw_delivery_prereqs", "viewer_available", 7, "BMW viewer candidate is available locally."),
    }
    missing_messages = {
        "delivery_checklist_tool": "Mirrored deliveryChecklist executable is missing locally.",
        "delivery_checklist_helper": "Mirrored deliveryChecklist Python helper is missing locally.",
        "delivery_checklist_readme": "Mirrored deliveryChecklist README is missing locally.",
        "delivery_checklist_camera_crane": "Mirrored deliveryChecklist cameraCrane helper is missing locally.",
        "bmw_models_repo": "BMW delivery repo is missing locally.",
        "bmw_car_manager_script": "BMW `ci/scripts/car_manager.py` helper is missing locally.",
        "bmw_test_main_script": "BMW `ci/scripts/test/main.py` helper is missing locally.",
    }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line == "viewer_candidate=<none>":
            bmw_missing.append("No local `ramses*viewer*.exe` candidate was found during the BMW repo scan.")
            continue
        match = _DELIVERY_LOG_RE.match(line)
        if match is None:
            continue
        key = match.group("key").strip().lower()
        path = _normalize_path(match.group("path"))
        status = match.group("status").strip().lower()

        if key.startswith("delivery_checklist_"):
            if status == "available":
                local_asset_count += 1
            else:
                local_asset_missing += 1
        if key == "viewer_candidate" and status == "available":
            viewer_hits += 1

        if status == "available" and key in label_map:
            checker_name, rule, priority, message = label_map[key]
            _append_issue(
                payload,
                {
                    "path": path,
                    "checker": checker_name,
                    "rule": rule,
                    "severity": "info",
                    "line": None,
                    "column": None,
                    "message": message,
                    "excerpt": "",
                    "source_kind": "delivery_checklist",
                    "priority": priority,
                },
                seen,
            )
            continue

        if status == "missing":
            message = missing_messages.get(key)
            if message:
                bmw_missing.append(f"{message} Path: {path}")

    payload["checkers"].extend(
        [
            {
                "name": "delivery_checklist_assets",
                "files_checked": local_asset_count + local_asset_missing,
                "issues": local_asset_missing,
                "status": _checker_status(local_asset_missing),
            },
            {
                "name": "bmw_delivery_prereqs",
                "files_checked": len(bmw_missing) + viewer_hits,
                "issues": len(bmw_missing),
                "status": _checker_status(len(bmw_missing)),
            },
        ]
    )
    payload["manual_followups"] = bmw_missing
    payload = _finalize(payload)
    if bmw_missing:
        payload["manual_followups"] = bmw_missing + [
            note for note in payload["manual_followups"] if note not in bmw_missing
        ]
    return payload

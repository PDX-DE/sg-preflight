from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import asdict, dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

from sg_preflight.bmw_delivery import (
    discover_bmw_models_repo,
    inspect_bmw_screenshot_surface,
    resolve_bmw_profile_id,
)


_DEFAULT_SCOPE = ("NA8", "G78", "G50")
_DEFAULT_BATTERY_FILTERS = (
    "default",
    "openAllDoors_",
    "lights_drl_front",
    "lights_LowBeam",
    "lights_HighBeam",
    "lights_OnlyCones",
    "welcome_animation_",
    "automatic_Doors_",
    "highlighting_Doors",
)
_BEAM_FAMILY_FILTERS = ("lights_drl_front", "lights_LowBeam", "lights_HighBeam", "lights_OnlyCones")
_BATTERY_SCENARIO_SELECTORS: dict[str, tuple[str, ...]] = {
    "default": ("default_rear", "default"),
    "openAllDoors_": ("openAllDoors_rightView", "openAllDoors_leftView"),
    "lights_drl_front": ("lights_drl_front",),
    "lights_LowBeam": ("lights_LowBeam",),
    "lights_HighBeam": ("lights_HighBeam",),
    "lights_OnlyCones": ("lights_OnlyCones",),
    "welcome_animation_": ("welcome_animation_casual", "welcome_animation_stealth"),
    "automatic_Doors_": (
        "automatic_Doors_Full_Angles",
        "automatic_Doors_Colors",
        "automatic_Doors_Opacities",
        "automatic_Doors_Unavailable_Angles",
    ),
    "highlighting_Doors": ("highlighting_Doors",),
}
_BMW_SUPPORT_FILES = (
    "CarPaint.json",
    "perspectives_CID_2to1.json",
    "perspectives_CID_3to1.json",
    "perspectives_IC_mid.json",
    "perspectives_IC_high.json",
)
_SMOKE_SENTINEL = "SGPREFLIGHT_SMOKE_RESULT="
_BATTERY_SENTINEL = "SGPREFLIGHT_BATTERY_RESULT="
_CONFIG_SENTINEL = "SGPREFLIGHT_CONFIG_RESULT="
_LUA_TEST_STATUS_SENTINEL = "SGPREFLIGHT_LUA_TEST_STATUS="
_LUA_SCREENSHOT_STATUS_SENTINEL = "SGPREFLIGHT_LUA_SCREENSHOT_STATUS="
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_LOCAL_BATTERY_TEST_OVERRIDES = {
    "lights_LowBeam": (
        'if testViews["lights_LowBeam"] ~= nil then\n'
        '    testViews["lights_LowBeam"].enabled = true\n'
        '    testViews["lights_LowBeam"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); '
        'lights_beam(false, true); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
    "lights_HighBeam": (
        'if testViews["lights_HighBeam"] ~= nil then\n'
        '    testViews["lights_HighBeam"].enabled = true\n'
        '    testViews["lights_HighBeam"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); '
        'lights_beam(true, false); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
    "lights_OnlyCones": (
        'if testViews["lights_OnlyCones"] ~= nil then\n'
        '    testViews["lights_OnlyCones"].enabled = true\n'
        '    testViews["lights_OnlyCones"].update = function(time_ms)\n'
        '        reset(); forceUpdateScreen(); cameraView(7.0, 0.0, 45.0); '
        'lights_beam(false, false); road(true, 9.0, 12.0, 3.2, {1.0, 1.0, 1.0, 0.1}, true, {0.0, 0.0, 0.0, 0.5}, true); waitOnRendering(1000)\n'
        "    end\n"
        "end"
    ),
}
_LOCAL_DIRECT_SCREENSHOT_LUA_BY_TEST = {
    "lights_LowBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_HighBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_OnlyCones": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, 45.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = true; '
        'road(true, 9.0, 12.0, 3.2, {1.0, 1.0, 1.0, 0.1}, true, {0.0, 0.0, 0.0, 0.5}, true); '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
}
_LOCAL_PROXY_SCREENSHOT_LUA_BY_TEST = {
    "lights_LowBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = false; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
    "lights_HighBeam": (
        "reset(); forceUpdateScreen(); cameraView(7.0, 0.0, -75.0); "
        'R.logic().interfaces["Interface_Lights"]["IN"]["HighBeam_isActive"].value = true; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LowBeam_isActive"].value = false; '
        'R.logic().interfaces["Interface_Lights"]["IN"]["LightCones_isVisible"].value = false; '
        "waitOnRendering(1000); "
        'R.screenshot("__SGPREFLIGHT_SCREENSHOT_PATH__")'
    ),
}


def _workspace_root(explicit_root: Path | None = None) -> Path:
    return (explicit_root or Path(__file__).resolve().parents[1]).resolve()


def _default_output_root(workspace_root: Path) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    return workspace_root / "out" / f"daily-3d-car-qa-summary-{stamp}"


def _resolve_svn_trunk_root(workspace_root: Path) -> Path:
    candidates = (
        Path(r"C:\repositories\trunk"),
        workspace_root / "repositories" / "trunk",
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _resolve_sg_project_root(profile_id: str, workspace_root: Path) -> Path:
    trunk_root = _resolve_svn_trunk_root(workspace_root)
    candidates = (
        trunk_root / "Cars_IDCevo" / "BMW" / profile_id,
        trunk_root / "Cars" / "BMW" / profile_id,
        workspace_root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / profile_id,
        workspace_root / "repositories" / "trunk" / "Cars" / "BMW" / profile_id,
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return candidates[0].resolve()


def _resolve_idcevo_bmw_root(workspace_root: Path) -> Path:
    trunk_root = _resolve_svn_trunk_root(workspace_root)
    return (trunk_root / "Cars_IDCevo" / "BMW").resolve()


def _resolve_bmw_support_source_root(workspace_root: Path) -> Path:
    trunk_root = _resolve_svn_trunk_root(workspace_root)
    return (trunk_root / "Cars" / "BMW").resolve()


def _default_bmw_python(workspace_root: Path) -> Path:
    override = os.environ.get("SG_BMW_PYTHON_EXE", "").strip()
    if override:
        return Path(override).resolve()
    candidates = (
        workspace_root / ".venv_bmw_ci" / "Scripts" / "python.exe",
        Path(sys.executable),
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate.resolve()
    return Path(sys.executable).resolve()


def _image_count(root: Path) -> int:
    if not root.exists() or not root.is_dir():
        return 0
    return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES)


def _parse_sentinel(output: str, sentinel: str) -> dict[str, Any]:
    for line in reversed(output.splitlines()):
        if line.startswith(sentinel):
            payload = line[len(sentinel) :].strip()
            return json.loads(payload)
    return {}


def _extract_file_sizes(output: str) -> tuple[int, int]:
    match = re.search(r"File sizes:\s*Ramses:\s*(\d+)b\s*RLogic:\s*(\d+)b", output, flags=re.IGNORECASE)
    if not match:
        return 0, 0
    return int(match.group(1)), int(match.group(2))


def ensure_idcevo_bmw_support_files(
    workspace_root: Path | None = None,
    *,
    overwrite: bool = False,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    root = _workspace_root(workspace_root)
    source_root = _resolve_bmw_support_source_root(root)
    target_root = _resolve_idcevo_bmw_root(root)
    target_root.mkdir(parents=True, exist_ok=True)

    copied: list[str] = []
    notes: list[str] = []
    for name in _BMW_SUPPORT_FILES:
        source = source_root / name
        target = target_root / name
        if not source.exists():
            notes.append(f"Support file source missing: {source}")
            continue
        if target.exists() and not overwrite:
            notes.append(f"Support file already present: {target}")
            continue
        target.write_bytes(source.read_bytes())
        copied.append(str(target))
        notes.append(f"Prepared local BMW support file: {target}")
    return tuple(copied), tuple(notes)


@dataclass(frozen=True)
class BmwConfigCheckResult:
    status: str
    python_exe: str
    repo_root: str
    log_path: str
    output_excerpt: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BmwSmokeResult:
    profile_id: str
    bmw_profile_id: str
    status: str
    smoke_test: str
    python_exe: str
    sg_project_root: str
    bmw_test_config_path: str
    log_path: str
    exported_ramses_size: int = 0
    exported_rlogic_size: int = 0
    expected_count: int = 0
    actual_count: int = 0
    diff_count: int = 0
    compare_ok: bool = False
    error: str = ""
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class BmwBatteryResult:
    profile_id: str
    bmw_profile_id: str
    filter_name: str
    verdict: str
    status: str
    results_root: str
    log_path: str
    expected_count: int = 0
    actual_count: int = 0
    diff_count: int = 0
    compare_ok: bool = False
    error: str = ""
    missing_expected_baseline: str = ""
    actual_files: tuple[str, ...] = ()
    expected_files: tuple[str, ...] = ()
    diff_files: tuple[str, ...] = ()
    proxy_files: tuple[str, ...] = ()
    target_output_present: bool = False
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DailyQaSnapshot:
    created_at: str
    scope_profiles: tuple[str, ...]
    bmw_repo_root: str
    config_check: BmwConfigCheckResult
    smoke_results: tuple[BmwSmokeResult, ...]
    battery_results: tuple[BmwBatteryResult, ...]
    diagnostics: tuple[str, ...]
    blocked_steps: tuple[str, ...]
    top_review_items: tuple[str, ...]
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": self.created_at,
            "scope_profiles": list(self.scope_profiles),
            "bmw_repo_root": self.bmw_repo_root,
            "config_check": self.config_check.to_dict(),
            "smoke_results": [item.to_dict() for item in self.smoke_results],
            "battery_results": [item.to_dict() for item in self.battery_results],
            "diagnostics": list(self.diagnostics),
            "blocked_steps": list(self.blocked_steps),
            "top_review_items": list(self.top_review_items),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class DailyQaSnapshotResult:
    output_root: Path
    snapshot: DailyQaSnapshot
    markdown_path: Path
    json_path: Path
    battery_baseline_gaps_markdown_path: Path | None = None
    battery_baseline_gaps_json_path: Path | None = None
    review_gallery_html_path: Path | None = None
    review_priority_markdown_path: Path | None = None
    review_priority_json_path: Path | None = None
    delta_summary_markdown_path: Path | None = None
    delta_summary_json_path: Path | None = None


def _snapshot_result_from_dict(payload: dict[str, Any]) -> DailyQaSnapshot:
    config_payload = payload.get("config_check", {}) if isinstance(payload.get("config_check"), dict) else {}
    smoke_payloads = payload.get("smoke_results", [])
    if not isinstance(smoke_payloads, list):
        smoke_payloads = []
    battery_payloads = payload.get("battery_results", [])
    if not isinstance(battery_payloads, list):
        battery_payloads = []
    return DailyQaSnapshot(
        created_at=str(payload.get("created_at", "")),
        scope_profiles=tuple(str(item) for item in payload.get("scope_profiles", []) if str(item).strip()),
        bmw_repo_root=str(payload.get("bmw_repo_root", "")),
        config_check=BmwConfigCheckResult(
            status=str(config_payload.get("status", "")),
            python_exe=str(config_payload.get("python_exe", "")),
            repo_root=str(config_payload.get("repo_root", "")),
            log_path=str(config_payload.get("log_path", "")),
            output_excerpt=str(config_payload.get("output_excerpt", "")),
            error=str(config_payload.get("error", "")),
        ),
        smoke_results=tuple(
            BmwSmokeResult(
                profile_id=str(item.get("profile_id", "")),
                bmw_profile_id=str(item.get("bmw_profile_id", "")),
                status=str(item.get("status", "")),
                smoke_test=str(item.get("smoke_test", "")),
                python_exe=str(item.get("python_exe", "")),
                sg_project_root=str(item.get("sg_project_root", "")),
                bmw_test_config_path=str(item.get("bmw_test_config_path", "")),
                log_path=str(item.get("log_path", "")),
                exported_ramses_size=int(item.get("exported_ramses_size", 0) or 0),
                exported_rlogic_size=int(item.get("exported_rlogic_size", 0) or 0),
                expected_count=int(item.get("expected_count", 0) or 0),
                actual_count=int(item.get("actual_count", 0) or 0),
                diff_count=int(item.get("diff_count", 0) or 0),
                compare_ok=bool(item.get("compare_ok", False)),
                error=str(item.get("error", "")),
                notes=tuple(str(note) for note in item.get("notes", [])),
            )
            for item in smoke_payloads
            if isinstance(item, dict)
        ),
        battery_results=tuple(
            BmwBatteryResult(
                profile_id=str(item.get("profile_id", "")),
                bmw_profile_id=str(item.get("bmw_profile_id", "")),
                filter_name=str(item.get("filter_name", "")),
                verdict=str(item.get("verdict", "")),
                status=str(item.get("status", "")),
                results_root=str(item.get("results_root", "")),
                log_path=str(item.get("log_path", "")),
                expected_count=int(item.get("expected_count", 0) or 0),
                actual_count=int(item.get("actual_count", 0) or 0),
                diff_count=int(item.get("diff_count", 0) or 0),
                compare_ok=bool(item.get("compare_ok", False)),
                error=str(item.get("error", "")),
                missing_expected_baseline=str(item.get("missing_expected_baseline", "")),
                actual_files=tuple(str(name) for name in item.get("actual_files", [])),
                expected_files=tuple(str(name) for name in item.get("expected_files", [])),
                diff_files=tuple(str(name) for name in item.get("diff_files", [])),
                proxy_files=tuple(str(name) for name in item.get("proxy_files", [])),
                target_output_present=bool(item.get("target_output_present", False)),
                notes=tuple(str(note) for note in item.get("notes", [])),
            )
            for item in battery_payloads
            if isinstance(item, dict)
        ),
        diagnostics=tuple(str(item) for item in payload.get("diagnostics", [])),
        blocked_steps=tuple(str(item) for item in payload.get("blocked_steps", [])),
        top_review_items=tuple(str(item) for item in payload.get("top_review_items", [])),
        notes=tuple(str(item) for item in payload.get("notes", [])),
    )


def load_daily_qa_snapshot(output_root: Path) -> DailyQaSnapshotResult | None:
    root = output_root.resolve()
    json_path = root / "daily-3d-car-qa-summary.json"
    markdown_path = root / "daily-3d-car-qa-summary.md"
    baseline_gaps_markdown_path = root / "battery-baseline-gaps.md"
    baseline_gaps_json_path = root / "battery-baseline-gaps.json"
    review_gallery_html_path = root / "candidate-review-gallery.html"
    review_priority_markdown_path = root / "review-priority-ranking.md"
    review_priority_json_path = root / "review-priority-ranking.json"
    delta_summary_markdown_path = root / "daily-qa-delta-summary.md"
    delta_summary_json_path = root / "daily-qa-delta-summary.json"
    if not json_path.exists():
        return None
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        return None
    return DailyQaSnapshotResult(
        output_root=root,
        snapshot=_snapshot_result_from_dict(payload),
        markdown_path=markdown_path,
        json_path=json_path,
        battery_baseline_gaps_markdown_path=baseline_gaps_markdown_path if baseline_gaps_markdown_path.exists() else None,
        battery_baseline_gaps_json_path=baseline_gaps_json_path if baseline_gaps_json_path.exists() else None,
        review_gallery_html_path=review_gallery_html_path if review_gallery_html_path.exists() else None,
        review_priority_markdown_path=review_priority_markdown_path if review_priority_markdown_path.exists() else None,
        review_priority_json_path=review_priority_json_path if review_priority_json_path.exists() else None,
        delta_summary_markdown_path=delta_summary_markdown_path if delta_summary_markdown_path.exists() else None,
        delta_summary_json_path=delta_summary_json_path if delta_summary_json_path.exists() else None,
    )


def find_latest_daily_qa_snapshot(
    workspace_root: Path | None = None,
    *,
    required_profiles: tuple[str, ...] = (),
    exclude_output_roots: tuple[Path, ...] = (),
) -> DailyQaSnapshotResult | None:
    workspace = _workspace_root(workspace_root)
    out_root = workspace / "out"
    if not out_root.exists():
        return None

    normalized_required = {item.strip().upper() for item in required_profiles if item and item.strip()}
    excluded = {path.resolve() for path in exclude_output_roots}
    candidates: list[DailyQaSnapshotResult] = []
    for directory in out_root.glob("daily-3d-car-qa-summary-*"):
        if not directory.is_dir():
            continue
        if directory.resolve() in excluded:
            continue
        loaded = load_daily_qa_snapshot(directory)
        if loaded is None:
            continue
        available_profiles = {item.upper() for item in loaded.snapshot.scope_profiles}
        if normalized_required and not normalized_required.issubset(available_profiles):
            continue
        candidates.append(loaded)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item.json_path.stat().st_mtime if item.json_path.exists() else 0,
            item.output_root.name,
        ),
        reverse=True,
    )
    return candidates[0]


def _battery_verdict(
    *,
    expected_count: int,
    actual_count: int,
    diff_count: int,
    compare_ok: bool,
    status: str,
    missing_expected_baseline: str = "",
    target_output_present: bool = False,
    error: str = "",
    proxy_files: tuple[str, ...] | list[str] = (),
) -> str:
    if status == "blocked":
        return "blocked"
    if status == "proxy_completed" and proxy_files:
        return "proxy_candidate_ready"
    lowered_error = error.lower()
    if "viewer exited with code" in lowered_error:
        return "runtime_crash"
    if actual_count == 0 and diff_count == 0:
        return "blocked"
    if missing_expected_baseline:
        if actual_count > 0 and target_output_present:
            return "baseline_candidate_ready"
        if actual_count > 0 and not target_output_present:
            return "scenario_output_missing"
        return "baseline_missing"
    if "no such file or directory" in lowered_error and "expected" in lowered_error:
        return "baseline_missing"
    if expected_count == 0 and actual_count > 0:
        return "baseline_missing"
    if diff_count > 0:
        return "needs_manual_review"
    if compare_ok and expected_count > 0 and actual_count > 0:
        return "likely_ok"
    return "inconclusive"


def _sanitize_filter_slug(filter_name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", filter_name.strip().lower())
    return cleaned.strip("_") or "all_tests"


def _resolve_battery_selected_tests(filter_name: str, all_tests: list[str] | tuple[str, ...]) -> list[str]:
    exact = _BATTERY_SCENARIO_SELECTORS.get(filter_name)
    if exact:
        available = set(all_tests)
        return [name for name in exact if name in available]
    return [test for test in all_tests if filter_name in test]


def _render_local_battery_override_lua(selected_tests: tuple[str, ...] | list[str]) -> str:
    lines: list[str] = []
    for test_name in selected_tests:
        override = _LOCAL_BATTERY_TEST_OVERRIDES.get(test_name)
        if override:
            if lines:
                lines.append("")
            lines.append("-- Local SG preflight override: wait for beam-light resources before screenshot.")
            lines.append(override)
    return "\n".join(lines).strip()


def _render_local_call_screenshot_override_lua(selected_tests: tuple[str, ...] | list[str]) -> str:
    if not selected_tests:
        return ""
    return "\n".join(
        [
            "-- Local SG preflight override: instrument per-test screenshot execution.",
            "function callSingleScreenshotTest(name, path)",
            "    local test = testViews[name]",
            "    if test == nil then",
            f'        print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|false|missing_test")',
            "        return",
            "    end",
            "    if not test.enabled then",
            f'        print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|false|disabled_test")',
            "        return",
            "    end",
            "    local ok, err = pcall(function() test.update(0) end)",
            f'    print("{_LUA_TEST_STATUS_SENTINEL}" .. tostring(name) .. "|" .. tostring(ok) .. "|" .. tostring(err))',
            "    if ok then",
            "        waitOnRendering(1000)",
            '        local screenshotPath = path .. "/" .. tostring(name) .. ".png"',
            "        local shotOk, shotErr = pcall(function() R.screenshot(screenshotPath) end)",
            f'        print("{_LUA_SCREENSHOT_STATUS_SENTINEL}" .. tostring(name) .. "|" .. tostring(shotOk) .. "|" .. tostring(shotErr))',
            "    end",
            "end",
            "",
            "function callScreenshotTests(path)",
            "    for name, test in pairs(testViews) do",
            "        if test.enabled then",
            "            callSingleScreenshotTest(name, path)",
            "        end",
            "    end",
            "end",
        ]
    ).strip()


def _render_local_direct_screenshot_templates(selected_tests: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {
        test_name: template
        for test_name in selected_tests
        if (template := _LOCAL_DIRECT_SCREENSHOT_LUA_BY_TEST.get(test_name))
    }


def _render_local_proxy_screenshot_templates(selected_tests: tuple[str, ...] | list[str]) -> dict[str, str]:
    return {
        test_name: template
        for test_name in selected_tests
        if (template := _LOCAL_PROXY_SCREENSHOT_LUA_BY_TEST.get(test_name))
    }


def _extract_missing_expected_baseline(error: str) -> str:
    if not error:
        return ""
    match = re.search(r"No such file or directory:\s*'([^']+)'", error, flags=re.IGNORECASE)
    if not match:
        match = re.search(r"Expected screenshot missing:\s*([^\r\n]+)", error, flags=re.IGNORECASE)
    if not match:
        return ""
    missing_path = match.group(1).replace("\\\\", "\\")
    try:
        return Path(missing_path).name
    except OSError:
        return missing_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]


def _scenario_image_names(root: Path) -> tuple[str, ...]:
    if not root.exists() or not root.is_dir():
        return ()
    names = sorted(
        path.name
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES
    )
    return tuple(names)


def _battery_gap_recommendation(item: BmwBatteryResult) -> str:
    if item.verdict == "scenario_output_missing":
        return "Treat as config/output mismatch before human visual review."
    if item.verdict == "baseline_candidate_ready":
        return "Candidate output exists; quick baseline-approval pass is possible."
    if item.verdict == "proxy_candidate_ready":
        return "Proxy output exists; it validates local lamp-state rendering but not the exact beam-cone effect."
    return "Generate or locate the expected baseline before visual comparison."


def _review_priority_reason(item: BmwBatteryResult) -> str:
    if item.verdict == "needs_manual_review":
        return "Diff payload exists and needs a human pass/fail decision."
    if item.verdict == "baseline_candidate_ready":
        return "Exact candidate output exists; baseline approval can be done quickly."
    if item.verdict == "proxy_candidate_ready":
        return "Proxy lamp-state output exists, but the exact cone-enabled effect is not locally validated."
    if item.verdict == "likely_ok":
        return "Exact compare completed locally with no visible diff."
    if item.verdict == "runtime_crash":
        return "Local BMW viewer/runtime crashed during this scenario."
    if item.verdict == "scenario_output_missing":
        return "Scenario harness ran, but the requested target output name was not emitted."
    if item.verdict == "baseline_missing":
        return "No expected baseline is available yet."
    return "Needs investigation."


def _review_priority_score(item: BmwBatteryResult) -> int:
    base = 0
    if item.verdict == "runtime_crash":
        base = 100
    elif item.verdict == "needs_manual_review":
        base = 88
    elif item.verdict in {"scenario_output_missing", "baseline_missing"}:
        base = 92
    elif item.verdict == "proxy_candidate_ready":
        base = 72
    elif item.verdict == "baseline_candidate_ready":
        base = 55
    elif item.verdict == "likely_ok":
        base = 18

    family = item.filter_name.casefold()
    family_bonus = 0
    if family == "lights_onlycones":
        family_bonus = 16
    elif family in {"lights_highbeam", "lights_lowbeam"}:
        family_bonus = 10
    elif family.startswith("lights_"):
        family_bonus = 7
    elif family.startswith("openalldoors_"):
        family_bonus = 4
    elif family.startswith("welcome_animation_"):
        family_bonus = 2

    diff_bonus = min(max(item.diff_count, 0), 3) * 3
    actual_bonus = 4 if item.actual_count > 0 else 0
    target_bonus = 5 if item.target_output_present else 0
    proxy_bonus = 4 if item.proxy_files else 0
    return base + family_bonus + diff_bonus + actual_bonus + target_bonus + proxy_bonus


def _review_priority_signals(item: BmwBatteryResult) -> tuple[str, ...]:
    signals: list[str] = []
    if item.verdict == "runtime_crash":
        signals.append("runtime crash")
    elif item.verdict == "needs_manual_review":
        signals.append("diff review needed")
    elif item.verdict == "scenario_output_missing":
        signals.append("target output missing")
    elif item.verdict == "baseline_missing":
        signals.append("baseline missing")
    elif item.verdict == "proxy_candidate_ready":
        signals.append("proxy-only coverage")
    elif item.verdict == "baseline_candidate_ready":
        signals.append("exact candidate ready")
    elif item.verdict == "likely_ok":
        signals.append("exact compare likely ok")

    family = item.filter_name.casefold()
    if family == "lights_onlycones":
        signals.append("cone family")
    elif family in {"lights_highbeam", "lights_lowbeam"}:
        signals.append("beam family")
    elif family.startswith("lights_"):
        signals.append("lightfx family")

    if item.diff_count > 0:
        signals.append(f"{item.diff_count} diff payload")
    if item.actual_count == 0:
        signals.append("no actual output")
    elif item.actual_count > 1:
        signals.append(f"{item.actual_count} actual outputs")
    if item.target_output_present:
        signals.append("target output present")
    if item.proxy_files:
        signals.append("proxy files present")
    return tuple(signals)


def _review_priority_level(item: BmwBatteryResult) -> str:
    if item.verdict in {"runtime_crash", "scenario_output_missing", "baseline_missing"}:
        return "P0"
    if item.verdict in {"needs_manual_review", "proxy_candidate_ready"}:
        return "P1"
    if item.verdict == "baseline_candidate_ready":
        return "P2"
    return "P3"


def _review_priority_payload(snapshot: DailyQaSnapshot) -> dict[str, Any]:
    items = sorted(
        snapshot.battery_results,
        key=lambda item: (
            _review_priority_score(item),
            item.diff_count,
            item.actual_count,
            item.profile_id.upper(),
            item.filter_name.lower(),
        ),
        reverse=True,
    )
    ranked = [
        {
            "profile_id": item.profile_id,
            "filter_name": item.filter_name,
            "verdict": item.verdict,
            "priority_level": _review_priority_level(item),
            "priority_score": _review_priority_score(item),
            "signals": list(_review_priority_signals(item)),
            "reason": _review_priority_reason(item),
            "recommendation": _battery_gap_recommendation(item),
            "expected_count": item.expected_count,
            "actual_count": item.actual_count,
            "diff_count": item.diff_count,
            "target_output_present": item.target_output_present,
            "proxy_files": list(item.proxy_files),
            "actual_files": list(item.actual_files),
            "log_path": item.log_path,
        }
        for item in items
        if item.verdict in {
            "needs_manual_review",
            "baseline_candidate_ready",
            "proxy_candidate_ready",
            "likely_ok",
            "runtime_crash",
            "scenario_output_missing",
        }
    ]
    return {
        "created_at": snapshot.created_at,
        "scope_profiles": list(snapshot.scope_profiles),
        "ranked_items": ranked,
        "top_five": ranked[:5],
    }


def _render_review_priority_markdown(snapshot: DailyQaSnapshot) -> str:
    payload = _review_priority_payload(snapshot)
    lines = [
        "# Screenshot Review Priority Ranking",
        "",
        f"- Generated: `{snapshot.created_at}`",
        f"- Scope: `{', '.join(snapshot.scope_profiles)}`",
        "- This is deterministic operator ranking, not final visual signoff.",
        "",
        "| Priority | Profile | Scenario | Verdict | Reason | Recommendation |",
        "| ---: | --- | --- | --- | --- | --- |",
    ]
    for item in payload["ranked_items"]:
        lines.append(
            f"| {item['priority_level']} ({item['priority_score']}) | {item['profile_id']} | `{item['filter_name']}` | "
            f"`{item['verdict']}` | {item['reason']} | {item['recommendation']} |"
        )
    if not payload["ranked_items"]:
        lines.append("| 0 | - | - | - | No ranked screenshot items in this snapshot. | - |")
    lines.extend(["", "## Top 5 To Review", ""])
    for item in payload["top_five"]:
        lines.append(
            f"- {item['profile_id']}: `{item['filter_name']}` -> `{item['verdict']}` "
            f"({item['priority_level']} / {item['priority_score']})"
        )
    if not payload["top_five"]:
        lines.append("- No screenshot items require ranking in this snapshot.")
    lines.append("")
    return "\n".join(lines)


def _snapshot_failure_keys(snapshot: DailyQaSnapshot) -> set[str]:
    failure_keys: set[str] = set()
    for item in snapshot.smoke_results:
        if item.status != "completed" or item.diff_count > 0:
            failure_keys.add(f"smoke:{item.profile_id}:{item.smoke_test}")
    for item in snapshot.battery_results:
        if item.verdict in {"runtime_crash", "scenario_output_missing", "blocked", "baseline_missing", "needs_manual_review"}:
            failure_keys.add(f"battery:{item.profile_id}:{item.filter_name}")
    return failure_keys


def _snapshot_diff_keys(snapshot: DailyQaSnapshot) -> set[str]:
    diff_keys: set[str] = set()
    for item in snapshot.smoke_results:
        if item.diff_count > 0:
            diff_keys.add(f"smoke:{item.profile_id}:{item.smoke_test}")
    for item in snapshot.battery_results:
        if item.verdict == "needs_manual_review":
            diff_keys.add(f"battery:{item.profile_id}:{item.filter_name}")
    return diff_keys


def _snapshot_status_counts(snapshot: DailyQaSnapshot) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in snapshot.battery_results:
        counts[item.verdict] = counts.get(item.verdict, 0) + 1
    for item in snapshot.smoke_results:
        key = f"smoke_{item.status}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def _daily_delta_payload(
    current: DailyQaSnapshot,
    previous: DailyQaSnapshot | None,
    *,
    current_output_root: Path,
    previous_output_root: Path | None = None,
) -> dict[str, Any]:
    if previous is None:
        return {
            "current_created_at": current.created_at,
            "previous_created_at": "",
            "current_output_root": str(current_output_root),
            "previous_output_root": "",
            "scope_profiles": list(current.scope_profiles),
            "new_failures": [],
            "resolved_failures": [],
            "new_screenshot_diffs": [],
            "unchanged_blockers": list(current.blocked_steps),
            "changed_counts": {"current": _snapshot_status_counts(current), "previous": {}},
            "top_five_to_review": list(current.top_review_items[:5]),
        }

    current_failures = _snapshot_failure_keys(current)
    previous_failures = _snapshot_failure_keys(previous)
    current_diffs = _snapshot_diff_keys(current)
    previous_diffs = _snapshot_diff_keys(previous)
    return {
        "current_created_at": current.created_at,
        "previous_created_at": previous.created_at,
        "current_output_root": str(current_output_root),
        "previous_output_root": str(previous_output_root) if previous_output_root is not None else "",
        "scope_profiles": list(current.scope_profiles),
        "new_failures": sorted(current_failures - previous_failures),
        "resolved_failures": sorted(previous_failures - current_failures),
        "new_screenshot_diffs": sorted(current_diffs - previous_diffs),
        "unchanged_blockers": sorted(set(current.blocked_steps).intersection(previous.blocked_steps)),
        "changed_counts": {
            "current": _snapshot_status_counts(current),
            "previous": _snapshot_status_counts(previous),
        },
        "top_five_to_review": list(current.top_review_items[:5]),
    }


def _render_daily_delta_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Daily QA Delta Summary",
        "",
        f"- Current run: `{payload.get('current_created_at', '')}`",
        f"- Previous run: `{payload.get('previous_created_at', '') or 'none'}`",
        f"- Current output root: `{payload.get('current_output_root', '')}`",
    ]
    previous_output_root = str(payload.get("previous_output_root", "")).strip()
    if previous_output_root:
        lines.append(f"- Previous output root: `{previous_output_root}`")
    lines.extend(
        [
            "",
            "## New Failures",
        ]
    )
    new_failures = payload.get("new_failures", [])
    if new_failures:
        lines.extend(f"- `{item}`" for item in new_failures)
    else:
        lines.append("- None")
    lines.extend(["", "## Resolved Failures"])
    resolved_failures = payload.get("resolved_failures", [])
    if resolved_failures:
        lines.extend(f"- `{item}`" for item in resolved_failures)
    else:
        lines.append("- None")
    lines.extend(["", "## New Screenshot Diffs"])
    new_diffs = payload.get("new_screenshot_diffs", [])
    if new_diffs:
        lines.extend(f"- `{item}`" for item in new_diffs)
    else:
        lines.append("- None")
    lines.extend(["", "## Unchanged Blockers"])
    unchanged = payload.get("unchanged_blockers", [])
    if unchanged:
        lines.extend(f"- {item}" for item in unchanged)
    else:
        lines.append("- None")
    lines.extend(["", "## Changed Counts", "", "```json", json.dumps(payload.get("changed_counts", {}), indent=2, ensure_ascii=False), "```", "", "## Top 5 To Review"])
    top = payload.get("top_five_to_review", [])
    if top:
        lines.extend(f"- {item}" for item in top)
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _render_candidate_review_gallery(snapshot: DailyQaSnapshot, *, html_root: Path | None = None) -> str:
    sections: list[str] = [
        "<!doctype html>",
        "<html lang=\"en\">",
        "<head>",
        "<meta charset=\"utf-8\">",
        "<title>Candidate Review Gallery</title>",
        "<style>",
        "body { font-family: Segoe UI, Arial, sans-serif; margin: 24px; background: #111827; color: #f3f4f6; }",
        "h1, h2, h3 { margin-bottom: 0.4rem; }",
        ".note { color: #cbd5e1; max-width: 70rem; }",
        ".card { background: #1f2937; border: 1px solid #374151; border-radius: 12px; padding: 16px; margin: 16px 0; }",
        ".meta { color: #d1d5db; margin-bottom: 12px; }",
        ".gallery { display: flex; flex-wrap: wrap; gap: 16px; }",
        ".shot { background: #0f172a; border-radius: 8px; padding: 12px; width: min(31rem, 100%); }",
        ".shot img { max-width: 100%; height: auto; display: block; background: #000; border-radius: 6px; }",
        ".tag { display: inline-block; padding: 2px 8px; border-radius: 999px; background: #2563eb; color: #eff6ff; font-size: 12px; margin-right: 8px; }",
        ".tag.warn { background: #b45309; color: #fffbeb; }",
        ".tag.ok { background: #166534; color: #ecfdf5; }",
        ".tag.proxy { background: #7c3aed; color: #f5f3ff; }",
        ".summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }",
        ".summary .item { background: #0f172a; border: 1px solid #374151; border-radius: 10px; padding: 10px 12px; min-width: 14rem; }",
        ".recommendation { color: #cbd5e1; margin: 10px 0 0; }",
        "code { color: #bfdbfe; }",
        "</style>",
        "</head>",
        "<body>",
        "<h1>Candidate Review Gallery</h1>",
        "<p class=\"note\">This gallery flattens the broader screenshot battery into a quick visual pass. It is intended to reduce manual navigation overhead, not to replace final signoff.</p>",
    ]

    items = [
        item
        for item in snapshot.battery_results
        if item.verdict in {"baseline_candidate_ready", "proxy_candidate_ready", "needs_manual_review", "likely_ok"}
    ]
    items.sort(
        key=lambda item: (
            _review_priority_score(item),
            item.profile_id.upper(),
            item.filter_name.lower(),
        ),
        reverse=True,
    )
    if not items:
        sections.extend(
            [
                "<p>No candidate-ready or reviewable screenshot outputs were found in this snapshot.</p>",
                "</body>",
                "</html>",
            ]
        )
        return "\n".join(sections)

    verdict_counts: dict[str, int] = {}
    for item in items:
        verdict_counts[item.verdict] = verdict_counts.get(item.verdict, 0) + 1
    sections.extend(
        [
            "<div class=\"summary\">",
            f"<div class=\"item\"><strong>Total reviewable items</strong><br>{len(items)}</div>",
            f"<div class=\"item\"><strong>Needs manual diff review</strong><br>{verdict_counts.get('needs_manual_review', 0)}</div>",
            f"<div class=\"item\"><strong>Exact baseline candidates</strong><br>{verdict_counts.get('baseline_candidate_ready', 0)}</div>",
            f"<div class=\"item\"><strong>Proxy candidates</strong><br>{verdict_counts.get('proxy_candidate_ready', 0)}</div>",
            f"<div class=\"item\"><strong>Likely OK exact compares</strong><br>{verdict_counts.get('likely_ok', 0)}</div>",
            "</div>",
        ]
    )

    for item in items:
        priority_score = _review_priority_score(item)
        recommendation = (
            "Review the diff payload and decide pass/fail."
            if item.verdict == "needs_manual_review"
            else _battery_gap_recommendation(item)
        )
        verdict_tag_class = "ok" if item.verdict == "likely_ok" else "proxy" if item.verdict == "proxy_candidate_ready" else "warn" if item.verdict == "needs_manual_review" else ""
        sections.extend(
            [
                "<div class=\"card\">",
                f"<h2>{escape(item.profile_id)} / <code>{escape(item.filter_name)}</code></h2>",
                "<div class=\"meta\">",
                f"<span class=\"tag {verdict_tag_class}\">{escape(item.verdict)}</span>",
                f"<span class=\"tag\">priority {priority_score}</span>",
                f"<span>Expected {item.expected_count} | Actual {item.actual_count} | Diff {item.diff_count}</span>",
                "</div>",
                "<div class=\"gallery\">",
            ]
        )
        actual_root = Path(item.results_root) / "tests" / "actuals"
        proxy_root = Path(item.results_root) / "tests" / "proxy_actuals"
        shot_names = item.actual_files
        shot_root = actual_root
        shot_label = "actual"
        if item.verdict == "proxy_candidate_ready" and item.proxy_files:
            shot_names = item.proxy_files
            shot_root = proxy_root
            shot_label = "proxy"
        for name in shot_names:
            image_path = (shot_root / name).resolve()
            if not image_path.exists():
                continue
            image_src = image_path.as_uri()
            image_display_path = str(image_path)
            if html_root is not None:
                image_src = Path(os.path.relpath(image_path, html_root.parent)).as_posix()
                image_display_path = image_src
            sections.extend(
                [
                    "<div class=\"shot\">",
                    f"<h3>{escape(name)} <span class=\"tag {'proxy' if shot_label == 'proxy' else 'warn'}\">{escape(shot_label)}</span></h3>",
                    f"<img src=\"{escape(image_src)}\" alt=\"{escape(name)}\">",
                    f"<p><code>{escape(image_display_path)}</code></p>",
                    "</div>",
                ]
            )
        sections.extend(
            [
                "</div>",
                f"<p class=\"recommendation\"><strong>Suggested next action:</strong> {escape(recommendation)}</p>",
                "</div>",
            ]
        )

    sections.extend(["</body>", "</html>"])
    return "\n".join(sections)


def _group_battery_results_by_profile(battery_results: tuple[BmwBatteryResult, ...] | list[BmwBatteryResult]) -> dict[str, list[BmwBatteryResult]]:
    grouped: dict[str, list[BmwBatteryResult]] = {}
    for item in battery_results:
        grouped.setdefault(item.profile_id.strip().upper(), []).append(item)
    return grouped


def _beam_family_diagnostics(
    battery_results: tuple[BmwBatteryResult, ...] | list[BmwBatteryResult],
) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for profile_id, items in sorted(_group_battery_results_by_profile(battery_results).items()):
        by_filter = {item.filter_name: item for item in items}
        control = by_filter.get("lights_drl_front")
        if control is None or control.actual_count <= 0:
            continue
        unresolved_filters = [
            name
            for name in ("lights_LowBeam", "lights_HighBeam", "lights_OnlyCones")
            if (item := by_filter.get(name)) is not None
            and item.actual_count <= 0
            and not item.proxy_files
        ]
        proxy_filters = [
            name
            for name in ("lights_LowBeam", "lights_HighBeam", "lights_OnlyCones")
            if (item := by_filter.get(name)) is not None and item.proxy_files
        ]
        if unresolved_filters:
            unresolved_text = ", ".join(f"`{name}`" for name in unresolved_filters)
            diagnostics.append(
                f"{profile_id}: control `lights_drl_front` generated screenshot payload, but {unresolved_text} still emitted no exact PNG output. "
                "Treat this as a beam-family runtime/content failure, not as a wider battery harness failure."
            )
        if proxy_filters:
            proxy_text = ", ".join(f"`{name}`" for name in proxy_filters)
            diagnostics.append(
                f"{profile_id}: exact beam-cone rendering still fails locally for {proxy_text}, but proxy lamp-state screenshots were generated with `LightCones_isVisible = false`."
            )
    return tuple(diagnostics)


def _parse_named_bool_statuses(output: str, sentinel: str) -> dict[str, tuple[bool, str]]:
    parsed: dict[str, tuple[bool, str]] = {}
    for line in output.splitlines():
        if not line.startswith(sentinel):
            continue
        payload = line[len(sentinel) :].strip()
        parts = payload.split("|", 2)
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        ok_text = parts[1].strip().lower()
        error_text = parts[2].strip() if len(parts) > 2 else ""
        parsed[name] = (ok_text == "true", "" if error_text == "nil" else error_text)
    return parsed


def _battery_baseline_gap_payload(snapshot: DailyQaSnapshot) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, str]]] = {}
    for item in snapshot.battery_results:
        if item.verdict not in {"baseline_missing", "baseline_candidate_ready", "scenario_output_missing"}:
            continue
        missing_baseline = item.missing_expected_baseline or _extract_missing_expected_baseline(item.error)
        grouped.setdefault(item.profile_id, []).append(
            {
                "filter_name": item.filter_name,
                "verdict": item.verdict,
                "missing_expected_baseline": missing_baseline or "unknown expected file",
                "target_output_present": "yes" if item.target_output_present else "no",
                "actual_files": ", ".join(item.actual_files) if item.actual_files else "(none)",
                "recommendation": _battery_gap_recommendation(item),
                "error": item.error,
                "log_path": item.log_path,
            }
        )

    return {
        "created_at": snapshot.created_at,
        "scope_profiles": list(snapshot.scope_profiles),
        "profiles": [
            {
                "profile_id": profile_id,
                "gaps": gaps,
            }
            for profile_id, gaps in sorted(grouped.items())
        ],
    }


def _render_battery_baseline_gaps_markdown(snapshot: DailyQaSnapshot) -> str:
    payload = _battery_baseline_gap_payload(snapshot)
    lines = [
        "# Broader Screenshot Battery - Baseline And Output Gaps",
        "",
    ]

    profiles = payload.get("profiles", [])
    if not profiles:
        lines.append("No missing expected baselines were inferred from the current broader battery run.")
        lines.append("")
        return "\n".join(lines)

    for profile in profiles:
        profile_id = str(profile.get("profile_id", "")).strip() or "unknown"
        lines.extend(
            [
                f"## {profile_id}",
                "",
            ]
        )
        for gap in profile.get("gaps", []):
            filter_name = str(gap.get("filter_name", "")).strip() or "unknown"
            verdict = str(gap.get("verdict", "")).strip() or "unknown"
            missing_baseline = str(gap.get("missing_expected_baseline", "")).strip() or "unknown expected file"
            target_output_present = str(gap.get("target_output_present", "")).strip() or "no"
            actual_files = str(gap.get("actual_files", "")).strip() or "(none)"
            recommendation = str(gap.get("recommendation", "")).strip()
            lines.append(
                f"- `{filter_name}` -> verdict `{verdict}`; missing expected baseline `{missing_baseline}`; "
                f"target output present `{target_output_present}`; actual files `{actual_files}`"
            )
            if recommendation:
                lines.append(f"  Recommendation: {recommendation}")
        lines.append("")

    return "\n".join(lines)


def _render_snapshot_markdown(snapshot: DailyQaSnapshot) -> str:
    lines = [
        f"# Daily 3D Car QA Summary",
        "",
        f"- Generated: `{snapshot.created_at}`",
        f"- Scope: `{', '.join(snapshot.scope_profiles)}`",
        f"- BMW repo root: `{snapshot.bmw_repo_root or 'not found'}`",
        "",
        "## Config Check",
        "",
        f"- Status: `{snapshot.config_check.status}`",
        f"- Python: `{snapshot.config_check.python_exe}`",
        f"- Log: `{snapshot.config_check.log_path}`",
    ]
    if snapshot.config_check.error:
        lines.append(f"- Error: `{snapshot.config_check.error}`")
    if snapshot.config_check.output_excerpt:
        lines.extend(
            [
                "",
                "```text",
                snapshot.config_check.output_excerpt.rstrip(),
                "```",
            ]
        )

    lines.extend(
        [
            "",
            "## Smoke Results",
            "",
            "| Profile | Status | Smoke Test | Ramses Bytes | Expected | Actual | Diff | Compare |",
            "| --- | --- | --- | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for item in snapshot.smoke_results:
        lines.append(
            f"| {item.profile_id} | {item.status} | `{item.smoke_test}` | "
            f"{item.exported_ramses_size} | {item.expected_count} | {item.actual_count} | {item.diff_count} | "
            f"{'passed' if item.compare_ok else 'not-passed'} |"
        )
    for item in snapshot.smoke_results:
        lines.extend(
            [
                "",
                f"### {item.profile_id}",
                "",
                f"- BMW profile: `{item.bmw_profile_id}`",
                f"- SG project root: `{item.sg_project_root}`",
                f"- Test config: `{item.bmw_test_config_path or 'not found'}`",
                f"- Log: `{item.log_path}`",
            ]
        )
        if item.error:
            lines.append(f"- Error: `{item.error}`")
        if item.notes:
            lines.append("- Notes:")
            for note in item.notes:
                lines.append(f"  - {note}")

    if snapshot.battery_results:
        lines.extend(
            [
                "",
                "## Broader Screenshot Battery",
                "",
                "| Profile | Filter | Verdict | Expected | Actual | Diff | Log |",
                "| --- | --- | --- | ---: | ---: | ---: | --- |",
            ]
        )
        for item in snapshot.battery_results:
            lines.append(
                f"| {item.profile_id} | `{item.filter_name}` | {item.verdict} | "
                f"{item.expected_count} | {item.actual_count} | {item.diff_count} | `{item.log_path}` |"
            )

    lines.extend(
        [
            "",
            "## Diagnostics",
            "",
        ]
    )
    if snapshot.diagnostics:
        lines.extend(f"- {item}" for item in snapshot.diagnostics)
    else:
        lines.append("- No grouped cross-scenario diagnosis was inferred from the current battery run.")

    lines.extend(
        [
            "",
            "## Top Review Items",
            "",
        ]
    )
    if snapshot.top_review_items:
        lines.extend(f"- {item}" for item in snapshot.top_review_items)
    else:
        lines.append("- No immediate review items were inferred from the current smoke pass.")

    lines.extend(
        [
            "",
            "## Blocked Steps",
            "",
        ]
    )
    if snapshot.blocked_steps:
        lines.extend(f"- {item}" for item in snapshot.blocked_steps)
    else:
        lines.append("- No blockers were detected in this local snapshot.")

    if snapshot.notes:
        lines.extend(
            [
                "",
                "## Notes",
                "",
            ]
        )
        lines.extend(f"- {item}" for item in snapshot.notes)

    lines.append("")
    return "\n".join(lines)


def _run_bmw_configuration_check(
    repo_root: Path,
    python_exe: Path,
    output_root: Path,
) -> BmwConfigCheckResult:
    log_path = output_root / "bmw-configurations.log"
    command = [str(python_exe), "ci/scripts/car_manager.py", "configurations", "-e", "IPN"]
    env = os.environ.copy()
    completed = subprocess.run(
        command,
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=900,
    )
    combined = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    log_path.write_text(combined, encoding="utf-8")
    status = "ready" if completed.returncode == 0 else "failed"
    return BmwConfigCheckResult(
        status=status,
        python_exe=str(python_exe),
        repo_root=str(repo_root),
        log_path=str(log_path),
        output_excerpt="\n".join((completed.stdout or "").splitlines()[:12]),
        error="" if completed.returncode == 0 else (completed.stderr or completed.stdout or "configurations failed").strip(),
    )


def _write_smoke_script(
    script_path: Path,
    *,
    profile_id: str,
    sg_project_root: Path,
    bmw_test_config_path: Path,
    smoke_test: str,
) -> None:
    export_dir = sg_project_root / "export"
    export_file = export_dir / f"Export_{profile_id}.rca"
    script_text = textwrap.dedent(
        f"""
        import json
        import traceback
        from pathlib import Path

        from common import g_config
        from asset_testing import asset_testing

        IMAGE_SUFFIXES = {{".png", ".jpg", ".jpeg", ".webp", ".bmp"}}

        def image_count(root: Path) -> int:
            if not root.exists() or not root.is_dir():
                return 0
            return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)

        profile_id = {profile_id!r}
        smoke_test = {smoke_test!r}
        export_dir = Path({str(export_dir)!r})
        export_file = Path({str(export_file)!r})
        bmw_test_config = Path({str(bmw_test_config_path)!r})
        expected_dir = export_dir / "tests" / "expected"
        actuals_dir = export_dir / "tests" / "actuals"
        diff_dir = export_dir / "tests" / "diff"
        result = {{
            "profile_id": profile_id,
            "status": "failed",
            "smoke_test": smoke_test,
            "expected_count": 0,
            "actual_count": 0,
            "diff_count": 0,
            "exported_ramses_size": 0,
            "exported_rlogic_size": 0,
            "compare_ok": False,
            "error": "",
        }}

        try:
            (export_dir / "tests").mkdir(parents=True, exist_ok=True)
            if not export_file.exists():
                raise FileNotFoundError(f"Missing export scene: {{export_file}}")

            g_config.racoExport(
                car=None,
                featureLevel=2,
                dryRun=False,
                allowErrors=False,
                useCustomProj=True,
                rcaFile=export_file,
                rcaDir=export_dir,
            )
            print(f"{{profile_id}}: Export finished")

            ramses_path = export_dir / "exported.ramses"
            rlogic_path = export_dir / "exported.rlogic"
            result["exported_ramses_size"] = ramses_path.stat().st_size if ramses_path.exists() else 0
            result["exported_rlogic_size"] = rlogic_path.stat().st_size if rlogic_path.exists() else 0
            print(
                f"{{profile_id}}: File sizes -> "
                f"Ramses={{result['exported_ramses_size']}}b "
                f"RLogic={{result['exported_rlogic_size']}}b"
            )

            asset_testing.runScreenshotTests(
                car=None,
                filter=smoke_test,
                saveDiff=True,
                generate=True,
                dry_run=False,
                logs=False,
                testsConfigFile=bmw_test_config,
                useCustomProj=True,
                rcaDir=export_dir,
                ramsesFile=ramses_path,
                brand="BMW",
                noException=False,
                results_dir=None,
                no_clean=True,
            )

            asset_testing.runScreenshotTests(
                car=None,
                filter=smoke_test,
                saveDiff=True,
                generate=False,
                dry_run=False,
                logs=True,
                testsConfigFile=bmw_test_config,
                useCustomProj=True,
                rcaDir=export_dir,
                ramsesFile=ramses_path,
                brand="BMW",
                noException=False,
                results_dir=None,
                no_clean=True,
            )
            result["status"] = "completed"
            result["compare_ok"] = True
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
            print(traceback.format_exc())
        finally:
            result["expected_count"] = image_count(expected_dir)
            result["actual_count"] = image_count(actuals_dir)
            result["diff_count"] = image_count(diff_dir)
            print({_SMOKE_SENTINEL!r} + json.dumps(result, ensure_ascii=False))
        """
    ).strip()
    script_path.write_text(script_text + "\n", encoding="utf-8")


def _write_battery_script(
    script_path: Path,
    *,
    profile_id: str,
    sg_project_root: Path,
    bmw_test_config_path: Path,
    filters: tuple[str, ...],
    results_root: Path,
) -> None:
    export_dir = sg_project_root / "export"
    export_file = export_dir / f"Export_{profile_id}.rca"
    override_lua_payload = json.dumps(_render_local_battery_override_lua(filters))
    screenshot_override_payload = json.dumps(_render_local_call_screenshot_override_lua(filters))
    selector_payload = json.dumps(_BATTERY_SCENARIO_SELECTORS)
    proxy_payload = json.dumps(_render_local_proxy_screenshot_templates(filters))
    script_text = textwrap.dedent(
        f"""
        import json
        import re
        import shutil
        import subprocess
        import sys
        import traceback
        from pathlib import Path

        from asset_testing.image_cmp import compareAndGenerateDiffs
        from asset_testing import asset_testing, testing_utils
        from common import g_config

        IMAGE_SUFFIXES = {{".png", ".jpg", ".jpeg", ".webp", ".bmp"}}
        LOCAL_TEST_OVERRIDE_LUA = json.loads({override_lua_payload!r})
        LOCAL_SCREENSHOT_OVERRIDE_LUA = json.loads({screenshot_override_payload!r})
        DIRECT_SCREENSHOT_TEMPLATES = json.loads({json.dumps(_render_local_direct_screenshot_templates(filters))!r})
        PROXY_SCREENSHOT_TEMPLATES = json.loads({proxy_payload!r})
        BATTERY_SCENARIO_SELECTORS = json.loads({selector_payload!r})

        def image_count(root: Path) -> int:
            if not root.exists() or not root.is_dir():
                return 0
            return sum(1 for path in root.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_SUFFIXES)

        def slugify(value: str) -> str:
            value = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
            return value.strip("_") or "all_tests"

        def resolve_selected_tests(filter_name: str, all_tests: list[str]) -> list[str]:
            exact = BATTERY_SCENARIO_SELECTORS.get(filter_name)
            if exact:
                available = set(all_tests)
                return [name for name in exact if name in available]
            return [test for test in all_tests if filter_name in test]

        def run_viewer_capture(args: list[str], cwd: Path, *, headless: bool = False) -> tuple[int, str, str]:
            viewer_exec = g_config.raco.getViewerHeadless() if headless else g_config.raco.getViewer()
            cmd = [*(viewer_exec if isinstance(viewer_exec, tuple) else [str(viewer_exec)]), *args, "--no-ramsh"]
            if sys.platform == "linux":
                cmd = (["xvfb-run", "-a", *cmd] if not headless else ["bash", *cmd])
            completed = subprocess.run(
                cmd,
                cwd=cwd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            stdout = completed.stdout.decode("utf-8", errors="replace").strip()
            stderr = completed.stderr.decode("utf-8", errors="replace").strip()
            return completed.returncode, stdout, stderr

        def build_direct_exec_lua(test_name: str, screenshot_path: str) -> str | None:
            template = DIRECT_SCREENSHOT_TEMPLATES.get(test_name)
            if not template:
                return None
            return template.replace("__SGPREFLIGHT_SCREENSHOT_PATH__", screenshot_path)

        def build_proxy_exec_lua(test_name: str, screenshot_path: str) -> str | None:
            template = PROXY_SCREENSHOT_TEMPLATES.get(test_name)
            if not template:
                return None
            return template.replace("__SGPREFLIGHT_SCREENSHOT_PATH__", screenshot_path)

        def build_filtered_test_config(
            source_config: Path,
            filtered_config: Path,
            selected_tests: list[str],
            all_tests: list[str],
        ) -> None:
            filtered_config.parent.mkdir(parents=True, exist_ok=True)
            lines: list[str] = []
            if source_config.exists():
                lines.append(source_config.read_text(encoding="utf-8", errors="replace").rstrip())
            disabled_tests = [name for name in all_tests if name not in selected_tests]
            if lines and disabled_tests:
                lines.append("")
            lines.extend(f"disableTest({{json.dumps(name)}})" for name in disabled_tests)
            if lines and selected_tests:
                lines.append("")
            for name in selected_tests:
                lines.append(f"if testViews[{{json.dumps(name)}}] ~= nil then")
                lines.append(f"    testViews[{{json.dumps(name)}}].enabled = true")
                lines.append("end")
            if LOCAL_TEST_OVERRIDE_LUA:
                if lines:
                    lines.append("")
                lines.append(LOCAL_TEST_OVERRIDE_LUA)
            if LOCAL_SCREENSHOT_OVERRIDE_LUA:
                if lines:
                    lines.append("")
                lines.append(LOCAL_SCREENSHOT_OVERRIDE_LUA)
            filtered_config.write_text("\\n".join(lines).rstrip() + "\\n", encoding="utf-8")

        profile_id = {profile_id!r}
        filters = {list(filters)!r}
        export_dir = Path({str(export_dir)!r})
        export_file = Path({str(export_file)!r})
        bmw_test_config = Path({str(bmw_test_config_path)!r})
        battery_root = Path({str(results_root)!r})
        payload = []

        try:
            battery_root.mkdir(parents=True, exist_ok=True)
            if not export_file.exists():
                raise FileNotFoundError(f"Missing export scene: {{export_file}}")

            g_config.racoExport(
                car=None,
                featureLevel=2,
                dryRun=False,
                allowErrors=False,
                useCustomProj=True,
                rcaFile=export_file,
                rcaDir=export_dir,
            )
            print(f"{{profile_id}}: Export finished")

            ramses_path = export_dir / "exported.ramses"
            viewer_args_global = testing_utils.getViewerArgsGlobal(ramses_path, bmw_test_config)
            expected_dir_source = export_dir / "tests" / "expected"
            all_tests = g_config.raco.runViewer(
                args=[*viewer_args_global, '--exec=getAllScreenshotTests'],
                cwd=expected_dir_source if expected_dir_source.exists() else export_dir,
                headless=True,
            ).splitlines()
            for filter_name in filters:
                scenario_root = battery_root / slugify(filter_name)
                expected_dir = scenario_root / "tests" / "expected"
                actuals_dir = scenario_root / "tests" / "actuals"
                diff_dir = scenario_root / "tests" / "diff"
                result = {{
                    "profile_id": profile_id,
                    "filter_name": filter_name,
                    "status": "failed",
                    "expected_count": 0,
                    "actual_count": 0,
                    "diff_count": 0,
                    "compare_ok": False,
                    "results_root": str(scenario_root),
                    "error": "",
                    "proxy_files": [],
                }}
                try:
                    tests = resolve_selected_tests(filter_name, all_tests)
                    if not tests:
                        raise ValueError(f"No screenshot test matched filter '{{filter_name}}'")

                    filtered_config = scenario_root / "tests" / "filtered_test_config.lua"
                    build_filtered_test_config(bmw_test_config, filtered_config, tests, all_tests)
                    testing_utils.cleanTestDir(scenario_root, 'actuals')
                    testing_utils.cleanTestDir(scenario_root, 'diff')
                    expected_dir = testing_utils.getTestsDir(scenario_root, 'expected', False)
                    actuals_dir = testing_utils.getTestsDir(scenario_root, 'actuals', False)
                    diff_dir = testing_utils.getTestsDir(scenario_root, 'diff', False)
                    if expected_dir_source.exists() and expected_dir_source != expected_dir:
                        shutil.copytree(expected_dir_source, expected_dir, dirs_exist_ok=True)

                    viewer_args_global = testing_utils.getViewerArgsGlobal(ramses_path, filtered_config)
                    test_args_screenshots = testing_utils.getTestArgsScreenshot(viewer_args_global)
                    screenshot_file_path_lua = str(actuals_dir.absolute())
                    if "\\\\" in screenshot_file_path_lua:
                        screenshot_file_path_lua = screenshot_file_path_lua.replace("\\\\", "/")
                    proxy_actuals_dir = scenario_root / "tests" / "proxy_actuals"
                    proxy_actuals_dir.mkdir(parents=True, exist_ok=True)
                    proxy_file_path_lua = str(proxy_actuals_dir.absolute())
                    if "\\\\" in proxy_file_path_lua:
                        proxy_file_path_lua = proxy_file_path_lua.replace("\\\\", "/")

                    print("Creating screenshots...")
                    viewer_logs = []
                    proxy_files = []
                    used_proxy = False
                    for test_name in tests:
                        direct_exec_lua = build_direct_exec_lua(test_name, screenshot_file_path_lua + "/" + test_name + ".png")
                        if direct_exec_lua:
                            direct_viewer_args = [
                                str(ramses_path),
                                "--lua",
                                str(bmw_test_config),
                                "--exec-lua=" + direct_exec_lua,
                            ]
                            viewer_mode = "direct_exec_lua"
                        else:
                            direct_viewer_args = [
                                *test_args_screenshots,
                                '--exec-lua=callSingleScreenshotTest(' + json.dumps(test_name) + ', "' + screenshot_file_path_lua + '")',
                            ]
                            viewer_mode = "callSingleScreenshotTest"
                        return_code, viewer_stdout, viewer_stderr = run_viewer_capture(
                            direct_viewer_args,
                            cwd=actuals_dir,
                            headless=False,
                        )
                        viewer_logs.append(
                            f"[test={{test_name}} mode={{viewer_mode}}] rc={{return_code}}\\n{{viewer_stdout}}"
                            + (f"\\nSTDERR\\n{{viewer_stderr}}" if viewer_stderr else "")
                        )
                        if return_code != 0:
                            proxy_exec_lua = build_proxy_exec_lua(
                                test_name,
                                proxy_file_path_lua + "/" + test_name + ".png",
                            )
                            if proxy_exec_lua:
                                proxy_viewer_args = [
                                    str(ramses_path),
                                    "--lua",
                                    str(bmw_test_config),
                                    "--exec-lua=" + proxy_exec_lua,
                                ]
                                proxy_return_code, proxy_stdout, proxy_stderr = run_viewer_capture(
                                    proxy_viewer_args,
                                    cwd=proxy_actuals_dir,
                                    headless=False,
                                )
                                viewer_logs.append(
                                    f"[test={{test_name}} mode=proxy_direct_exec_lua] rc={{proxy_return_code}}\\n{{proxy_stdout}}"
                                    + (f"\\nSTDERR\\n{{proxy_stderr}}" if proxy_stderr else "")
                                )
                                proxy_png = proxy_actuals_dir / f"{{test_name}}.png"
                                if proxy_return_code == 0 and proxy_png.exists():
                                    proxy_files.append(proxy_png.name)
                                    used_proxy = True
                                    continue
                            raise RuntimeError(f"Viewer exited with code {{return_code}} while executing {{test_name}}")
                    print("\\n".join(viewer_logs))
                    if used_proxy and image_count(actuals_dir) == 0:
                        result["status"] = "proxy_completed"
                        result["proxy_files"] = proxy_files
                    else:
                        print("Running comparison...")
                        compareAndGenerateDiffs(expected_dir, actuals_dir, diff_dir, tests, True, True)
                        result["status"] = "completed"
                        result["compare_ok"] = True
                        result["proxy_files"] = proxy_files
                except Exception as exc:
                    result["status"] = "failed"
                    result["error"] = str(exc)
                    print(traceback.format_exc())
                finally:
                    result["expected_count"] = image_count(scenario_root / "tests" / "expected")
                    result["actual_count"] = image_count(scenario_root / "tests" / "actuals")
                    result["diff_count"] = image_count(scenario_root / "tests" / "diff")
                    payload.append(result)
        except Exception as exc:
            payload.append({{
                "profile_id": profile_id,
                "filter_name": "__export__",
                "status": "blocked",
                "expected_count": 0,
                "actual_count": 0,
                "diff_count": 0,
                "compare_ok": False,
                "results_root": str(battery_root),
                "error": str(exc),
            }})
            print(traceback.format_exc())
        finally:
            print({_BATTERY_SENTINEL!r} + json.dumps(payload, ensure_ascii=False))
        """
    ).strip()
    script_path.write_text(script_text + "\n", encoding="utf-8")


def _refresh_surface_notes(
    surface: Any,
    *,
    sg_project_root: Path,
    expected_count: int,
    actual_count: int,
    diff_count: int,
) -> tuple[str, ...]:
    notes: list[str] = []
    export_tests_root = Path(surface.export_tests_root) if getattr(surface, "export_tests_root", "") else Path()
    bmw_expected_root = Path(surface.bmw_expected_root) if getattr(surface, "bmw_expected_root", "") else Path()
    test_config_path = Path(surface.test_config_path) if getattr(surface, "test_config_path", "") else Path()
    sg_expected_root = sg_project_root / "export" / "tests" / "expected"

    if export_tests_root.exists():
        notes.append("BMW export/tests surface is present locally.")
    else:
        notes.append("BMW export/tests surface is not present locally for this profile.")

    if actual_count == 0:
        notes.append("BMW actuals root exists but currently contains no screenshot payload.")
    else:
        notes.append(f"BMW actuals payload is present locally ({actual_count} image(s)).")

    if diff_count == 0:
        notes.append("No diff payload was produced for the current local smoke run.")
    else:
        notes.append(f"BMW diff payload is present locally ({diff_count} image(s)).")

    if not bmw_expected_root.exists():
        notes.append("No BMW expected root is visible in the local snapshot for this profile.")
    if expected_count == 0:
        notes.append("No SG expected baseline root is available under the live SVN slice for this profile.")
    else:
        notes.append(f"SG expected baseline payload is present locally ({expected_count} image(s)).")

    if test_config_path.exists() and test_config_path.name != "test_config.lua":
        notes.append(f"BMW uses `{test_config_path.name}` in this snapshot instead of `test_config.lua`.")
    return tuple(notes)


def _run_profile_smoke(
    profile_id: str,
    *,
    workspace_root: Path,
    repo_root: Path,
    python_exe: Path,
    output_root: Path,
    smoke_test: str,
) -> BmwSmokeResult:
    sg_project_root = _resolve_sg_project_root(profile_id, workspace_root)
    surface = inspect_bmw_screenshot_surface(
        profile_id,
        workspace_root=workspace_root,
        sg_project_root=sg_project_root,
    )
    log_path = output_root / f"{profile_id.lower()}-bmw-smoke.log"
    notes = list(surface.notes)
    if not surface.test_config_path:
        notes.append("No BMW test config is available for this profile.")
        log_path.write_text("No BMW test config is available.\n", encoding="utf-8")
        return BmwSmokeResult(
            profile_id=profile_id,
            bmw_profile_id=surface.bmw_profile_id,
            status="blocked",
            smoke_test=smoke_test,
            python_exe=str(python_exe),
            sg_project_root=str(sg_project_root),
            bmw_test_config_path="",
            log_path=str(log_path),
            error="Missing BMW test config",
            notes=tuple(notes),
        )

    script_path = output_root / f"tmp_{profile_id.lower()}_smoke.py"
    _write_smoke_script(
        script_path,
        profile_id=profile_id,
        sg_project_root=sg_project_root,
        bmw_test_config_path=Path(surface.test_config_path),
        smoke_test=smoke_test,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str((repo_root / "ci" / "scripts").resolve())
    completed = subprocess.run(
        [str(python_exe), str(script_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=3600,
    )
    combined = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    log_path.write_text(combined, encoding="utf-8")
    payload = _parse_sentinel(combined, _SMOKE_SENTINEL)
    script_path.unlink(missing_ok=True)

    ramses_size, rlogic_size = _extract_file_sizes(combined)
    if payload:
        status = payload.get("status", "failed")
        expected_count = int(payload.get("expected_count", 0))
        actual_count = int(payload.get("actual_count", 0))
        diff_count = int(payload.get("diff_count", 0))
        return BmwSmokeResult(
            profile_id=profile_id,
            bmw_profile_id=surface.bmw_profile_id,
            status=status if completed.returncode == 0 else "failed",
            smoke_test=smoke_test,
            python_exe=str(python_exe),
            sg_project_root=str(sg_project_root),
            bmw_test_config_path=surface.test_config_path,
            log_path=str(log_path),
            exported_ramses_size=int(payload.get("exported_ramses_size") or ramses_size),
            exported_rlogic_size=int(payload.get("exported_rlogic_size") or rlogic_size),
            expected_count=expected_count,
            actual_count=actual_count,
            diff_count=diff_count,
            compare_ok=bool(payload.get("compare_ok", False)),
            error=(payload.get("error") or "").strip(),
            notes=_refresh_surface_notes(
                surface,
                sg_project_root=sg_project_root,
                expected_count=expected_count,
                actual_count=actual_count,
                diff_count=diff_count,
            ),
        )

    error = (completed.stderr or completed.stdout or "Smoke subprocess failed").strip()
    expected_count = _image_count(sg_project_root / "export" / "tests" / "expected")
    actual_count = _image_count(sg_project_root / "export" / "tests" / "actuals")
    diff_count = _image_count(sg_project_root / "export" / "tests" / "diff")
    return BmwSmokeResult(
        profile_id=profile_id,
        bmw_profile_id=surface.bmw_profile_id,
        status="failed",
        smoke_test=smoke_test,
        python_exe=str(python_exe),
        sg_project_root=str(sg_project_root),
        bmw_test_config_path=surface.test_config_path,
        log_path=str(log_path),
        exported_ramses_size=ramses_size,
        exported_rlogic_size=rlogic_size,
        expected_count=expected_count,
        actual_count=actual_count,
        diff_count=diff_count,
        compare_ok=False,
        error=error,
        notes=_refresh_surface_notes(
            surface,
            sg_project_root=sg_project_root,
            expected_count=expected_count,
            actual_count=actual_count,
            diff_count=diff_count,
        ),
    )


def _run_profile_battery(
    profile_id: str,
    *,
    workspace_root: Path,
    repo_root: Path,
    python_exe: Path,
    output_root: Path,
    filters: tuple[str, ...],
) -> tuple[BmwBatteryResult, ...]:
    if not filters:
        return ()

    sg_project_root = _resolve_sg_project_root(profile_id, workspace_root)
    surface = inspect_bmw_screenshot_surface(
        profile_id,
        workspace_root=workspace_root,
        sg_project_root=sg_project_root,
    )
    log_path = output_root / f"{profile_id.lower()}-bmw-battery.log"
    if not surface.test_config_path:
        log_path.write_text("No BMW test config is available.\n", encoding="utf-8")
        note_payload = tuple(list(surface.notes) + ["No BMW test config is available for this profile."])
        return tuple(
            BmwBatteryResult(
                profile_id=profile_id,
                bmw_profile_id=surface.bmw_profile_id,
                filter_name=filter_name,
                verdict="blocked",
                status="blocked",
                results_root="",
                log_path=str(log_path),
                error="Missing BMW test config",
                notes=note_payload,
            )
            for filter_name in filters
        )

    battery_root = output_root / profile_id.lower() / "battery"
    script_path = output_root / f"tmp_{profile_id.lower()}_battery.py"
    _write_battery_script(
        script_path,
        profile_id=profile_id,
        sg_project_root=sg_project_root,
        bmw_test_config_path=Path(surface.test_config_path),
        filters=filters,
        results_root=battery_root,
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str((repo_root / "ci" / "scripts").resolve())
    completed = subprocess.run(
        [str(python_exe), str(script_path)],
        cwd=repo_root,
        capture_output=True,
        text=True,
        env=env,
        timeout=7200,
    )
    combined = (completed.stdout or "") + ("\n" + completed.stderr if completed.stderr else "")
    log_path.write_text(combined, encoding="utf-8")
    payload = _parse_sentinel(combined, _BATTERY_SENTINEL)
    lua_update_status = _parse_named_bool_statuses(combined, _LUA_TEST_STATUS_SENTINEL)
    lua_screenshot_status = _parse_named_bool_statuses(combined, _LUA_SCREENSHOT_STATUS_SENTINEL)
    script_path.unlink(missing_ok=True)

    if not isinstance(payload, list):
        payload = []

    result_by_filter: dict[str, BmwBatteryResult] = {}
    base_notes = _refresh_surface_notes(
        surface,
        sg_project_root=sg_project_root,
        expected_count=surface.sg_expected_count,
        actual_count=surface.actual_count,
        diff_count=surface.diff_count,
    )
    for item in payload:
        if not isinstance(item, dict):
            continue
        filter_name = str(item.get("filter_name", "")).strip()
        if not filter_name:
            continue
        expected_count = int(item.get("expected_count", 0) or 0)
        actual_count = int(item.get("actual_count", 0) or 0)
        diff_count = int(item.get("diff_count", 0) or 0)
        status = str(item.get("status", "") or "failed")
        compare_ok = bool(item.get("compare_ok", False))
        results_root = Path(str(item.get("results_root", ""))).resolve()
        expected_files = _scenario_image_names(results_root / "tests" / "expected")
        actual_files = _scenario_image_names(results_root / "tests" / "actuals")
        diff_files = _scenario_image_names(results_root / "tests" / "diff")
        proxy_files = _scenario_image_names(results_root / "tests" / "proxy_actuals")
        missing_expected_baseline = _extract_missing_expected_baseline(str(item.get("error", "")).strip())
        target_output_present = bool(missing_expected_baseline and missing_expected_baseline in actual_files)
        verdict = _battery_verdict(
            expected_count=expected_count,
            actual_count=actual_count,
            diff_count=diff_count,
            compare_ok=compare_ok,
            status=status,
            missing_expected_baseline=missing_expected_baseline,
            target_output_present=target_output_present,
            error=str(item.get("error", "")).strip(),
            proxy_files=proxy_files,
        )
        notes = list(base_notes)
        if verdict == "likely_ok":
            notes.append("Representative local compare completed with no diff payload.")
        elif verdict == "needs_manual_review":
            notes.append("Diff payload exists and needs a human screenshot verdict.")
        elif verdict == "baseline_candidate_ready":
            notes.append("The requested scenario output exists in actuals, but the expected baseline is still missing.")
        elif verdict == "proxy_candidate_ready":
            notes.append("Exact cone-enabled rendering failed locally, but a proxy lamp-state screenshot was emitted with `LightCones_isVisible = false`.")
        elif verdict == "scenario_output_missing":
            notes.append("The requested scenario filename was not generated; treat this as config/output mismatch first.")
        elif verdict == "baseline_missing":
            notes.append("Actuals were generated but no local expected baseline was found in the results root.")
        elif verdict == "runtime_crash":
            notes.append("The viewer crashed while executing this scenario locally.")
        elif verdict == "blocked":
            notes.append("The broader screenshot battery did not produce a usable compare payload for this filter.")
        if filter_name in lua_update_status:
            update_ok, update_error = lua_update_status[filter_name]
            if update_ok:
                notes.append("Lua test update completed inside the viewer.")
            else:
                notes.append(f"Lua test update failed inside the viewer: {update_error or 'unknown error'}")
        if filter_name in lua_screenshot_status:
            shot_ok, shot_error = lua_screenshot_status[filter_name]
            if shot_ok and actual_count <= 0:
                notes.append("Viewer accepted `R.screenshot(...)`, but no PNG file was emitted.")
            elif shot_ok:
                notes.append("Viewer accepted `R.screenshot(...)` and emitted PNG payload.")
            else:
                notes.append(f"`R.screenshot(...)` failed inside the viewer: {shot_error or 'unknown error'}")

        result_by_filter[filter_name] = BmwBatteryResult(
            profile_id=profile_id,
            bmw_profile_id=surface.bmw_profile_id,
            filter_name=filter_name,
            verdict=verdict,
            status=status if completed.returncode == 0 else "failed",
            results_root=str(results_root),
            log_path=str(log_path),
            expected_count=expected_count,
            actual_count=actual_count,
            diff_count=diff_count,
            compare_ok=compare_ok,
            error=str(item.get("error", "")).strip(),
            missing_expected_baseline=missing_expected_baseline,
            actual_files=actual_files,
            expected_files=expected_files,
            diff_files=diff_files,
            proxy_files=proxy_files,
            target_output_present=target_output_present,
            notes=tuple(notes),
        )

    fallback_error = (completed.stderr or completed.stdout or "Battery subprocess failed").strip()
    ordered_results: list[BmwBatteryResult] = []
    for filter_name in filters:
        existing = result_by_filter.get(filter_name)
        if existing is not None:
            ordered_results.append(existing)
            continue
        scenario_root = battery_root / _sanitize_filter_slug(filter_name)
        ordered_results.append(
            BmwBatteryResult(
                profile_id=profile_id,
                bmw_profile_id=surface.bmw_profile_id,
                filter_name=filter_name,
                verdict="blocked",
                status="failed",
                results_root=str(scenario_root),
                log_path=str(log_path),
                error=fallback_error,
                notes=tuple(list(base_notes) + ["No battery result payload was captured for this filter."]),
            )
        )
    return tuple(ordered_results)


def materialize_daily_qa_snapshot(
    *,
    profile_ids: tuple[str, ...] = _DEFAULT_SCOPE,
    workspace_root: Path | None = None,
    output_root: Path | None = None,
    run_smoke: bool = True,
    smoke_test: str = "openAllDoors_rightView",
    battery_filters: tuple[str, ...] = (),
) -> DailyQaSnapshotResult:
    workspace = _workspace_root(workspace_root)
    repo_root = discover_bmw_models_repo(workspace).resolve()
    python_exe = _default_bmw_python(workspace)
    final_output_root = (output_root or _default_output_root(workspace)).resolve()
    final_output_root.mkdir(parents=True, exist_ok=True)

    _, support_notes = ensure_idcevo_bmw_support_files(workspace)
    config_check = _run_bmw_configuration_check(repo_root, python_exe, final_output_root)

    smoke_results: list[BmwSmokeResult] = []
    battery_results: list[BmwBatteryResult] = []
    if run_smoke:
        for profile_id in profile_ids:
            smoke_results.append(
                _run_profile_smoke(
                    profile_id,
                    workspace_root=workspace,
                    repo_root=repo_root,
                    python_exe=python_exe,
                    output_root=final_output_root,
                    smoke_test=smoke_test,
                )
            )
            if battery_filters:
                battery_results.extend(
                    _run_profile_battery(
                        profile_id,
                        workspace_root=workspace,
                        repo_root=repo_root,
                        python_exe=python_exe,
                        output_root=final_output_root,
                        filters=battery_filters,
                    )
                )

    diagnostics = list(_beam_family_diagnostics(tuple(battery_results)))
    beam_diagnostic_profiles = {
        item.split(":", 1)[0].strip().upper()
        for item in diagnostics
        if ":" in item
    }

    blocked_steps: list[str] = [
        "Jira writeback remains external to this local snapshot.",
        "CodeCraft / QX / full BMW ecosystem access is still not locally solved by this run.",
    ]
    if config_check.status != "ready":
        blocked_steps.append("BMW car_manager configuration check failed locally.")
    for item in smoke_results:
        if item.status != "completed":
            blocked_steps.append(f"{item.profile_id}: local BMW smoke run failed or stayed blocked.")
        if item.expected_count == 0:
            blocked_steps.append(f"{item.profile_id}: no local expected screenshot payload was generated.")
        if item.actual_count == 0:
            blocked_steps.append(f"{item.profile_id}: no local actual screenshot payload was generated.")
        if item.diff_count > 0:
            blocked_steps.append(f"{item.profile_id}: diff images were produced and need manual review.")
    for item in battery_results:
        if (
            item.profile_id.strip().upper() in beam_diagnostic_profiles
            and item.filter_name in {"lights_LowBeam", "lights_HighBeam", "lights_OnlyCones"}
            and item.verdict in {"blocked", "runtime_crash"}
        ):
            continue
        if item.verdict == "needs_manual_review":
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` produced diff payload and still needs a manual screenshot verdict."
            )
        elif item.verdict == "runtime_crash":
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` crashes the local BMW viewer/runtime during screenshot execution."
            )
        elif item.verdict == "scenario_output_missing":
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` did not generate the requested scenario output; treat as config/output mismatch."
            )
        elif item.verdict == "baseline_candidate_ready":
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` generated a candidate output but still lacks the expected baseline."
            )
        elif item.verdict == "proxy_candidate_ready":
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` exact cone-enabled render still fails locally, but a proxy lamp-state screenshot is available."
            )
        elif item.verdict in {"blocked", "baseline_missing"}:
            blocked_steps.append(
                f"{item.profile_id}: `{item.filter_name}` stayed incomplete during the broader screenshot battery."
            )
    blocked_steps.extend(diagnostics)

    top_review_items: list[str] = []
    for item in smoke_results:
        if item.compare_ok and item.diff_count == 0:
            top_review_items.append(
                f"{item.profile_id}: `{item.smoke_test}` passed locally with no visible diff."
            )
        elif item.diff_count > 0:
            top_review_items.append(
                f"{item.profile_id}: review diff output for `{item.smoke_test}`."
            )
        elif item.status != "completed":
            top_review_items.append(
                f"{item.profile_id}: inspect `{item.smoke_test}` smoke log for runtime failure."
            )
    for item in battery_results:
        if item.verdict == "likely_ok":
            top_review_items.append(
                f"{item.profile_id}: `{item.filter_name}` completed locally with no diff."
            )
        elif item.verdict == "needs_manual_review":
            top_review_items.append(
                f"{item.profile_id}: review diff output for `{item.filter_name}`."
            )
        elif item.verdict == "baseline_candidate_ready":
            top_review_items.append(
                f"{item.profile_id}: `{item.filter_name}` generated a candidate output; baseline approval can be done quickly."
            )
        elif item.verdict == "proxy_candidate_ready":
            top_review_items.append(
                f"{item.profile_id}: `{item.filter_name}` has a proxy lamp-state screenshot ready; exact cone effect is still blocked locally."
            )
        elif item.verdict == "scenario_output_missing":
            top_review_items.append(
                f"{item.profile_id}: `{item.filter_name}` did not emit its target screenshot name; fix config/output before visual review."
            )
        elif item.verdict == "runtime_crash":
            top_review_items.append(
                f"{item.profile_id}: `{item.filter_name}` crashes the local BMW viewer; this is a runtime/content issue, not a human review item."
            )
    top_review_items.extend(diagnostics)

    snapshot = DailyQaSnapshot(
        created_at=datetime.now().isoformat(timespec="seconds"),
        scope_profiles=tuple(profile_ids),
        bmw_repo_root=str(repo_root),
        config_check=config_check,
        smoke_results=tuple(smoke_results),
        battery_results=tuple(battery_results),
        diagnostics=tuple(diagnostics),
        blocked_steps=tuple(dict.fromkeys(blocked_steps)),
        top_review_items=tuple(top_review_items),
        notes=tuple(support_notes),
    )
    markdown_path = final_output_root / "daily-3d-car-qa-summary.md"
    json_path = final_output_root / "daily-3d-car-qa-summary.json"
    battery_baseline_gaps_markdown_path: Path | None = None
    battery_baseline_gaps_json_path: Path | None = None
    review_gallery_html_path: Path | None = None
    review_priority_markdown_path: Path | None = None
    review_priority_json_path: Path | None = None
    delta_summary_markdown_path: Path | None = None
    delta_summary_json_path: Path | None = None
    markdown_path.write_text(_render_snapshot_markdown(snapshot), encoding="utf-8")
    json_path.write_text(json.dumps(snapshot.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    if snapshot.battery_results:
        battery_baseline_gaps_markdown_path = final_output_root / "battery-baseline-gaps.md"
        battery_baseline_gaps_json_path = final_output_root / "battery-baseline-gaps.json"
        battery_baseline_gaps_markdown_path.write_text(
            _render_battery_baseline_gaps_markdown(snapshot),
            encoding="utf-8",
        )
        battery_baseline_gaps_json_path.write_text(
            json.dumps(_battery_baseline_gap_payload(snapshot), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        review_gallery_html_path = final_output_root / "candidate-review-gallery.html"
        review_gallery_html_path.write_text(
            _render_candidate_review_gallery(snapshot),
            encoding="utf-8",
        )
        review_priority_markdown_path = final_output_root / "review-priority-ranking.md"
        review_priority_json_path = final_output_root / "review-priority-ranking.json"
        review_priority_markdown_path.write_text(
            _render_review_priority_markdown(snapshot),
            encoding="utf-8",
        )
        review_priority_json_path.write_text(
            json.dumps(_review_priority_payload(snapshot), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    previous_snapshot = find_latest_daily_qa_snapshot(
        workspace,
        required_profiles=tuple(profile_ids),
        exclude_output_roots=(final_output_root,),
    )
    delta_payload = _daily_delta_payload(
        snapshot,
        previous_snapshot.snapshot if previous_snapshot is not None else None,
        current_output_root=final_output_root,
        previous_output_root=previous_snapshot.output_root if previous_snapshot is not None else None,
    )
    delta_summary_markdown_path = final_output_root / "daily-qa-delta-summary.md"
    delta_summary_json_path = final_output_root / "daily-qa-delta-summary.json"
    delta_summary_markdown_path.write_text(
        _render_daily_delta_markdown(delta_payload),
        encoding="utf-8",
    )
    delta_summary_json_path.write_text(
        json.dumps(delta_payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return DailyQaSnapshotResult(
        output_root=final_output_root,
        snapshot=snapshot,
        markdown_path=markdown_path,
        json_path=json_path,
        battery_baseline_gaps_markdown_path=battery_baseline_gaps_markdown_path,
        battery_baseline_gaps_json_path=battery_baseline_gaps_json_path,
        review_gallery_html_path=review_gallery_html_path,
        review_priority_markdown_path=review_priority_markdown_path,
        review_priority_json_path=review_priority_json_path,
        delta_summary_markdown_path=delta_summary_markdown_path,
        delta_summary_json_path=delta_summary_json_path,
    )

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import sys
import time
from typing import Any, Callable, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sg_preflight.bmw_delivery import LANE_IDC23, LANE_IDCEVO, LANE_UNKNOWN
from sg_preflight.delivery_workbook_generation import (
    check_delivery_workbook_generation_environment,
    poll_delivery_workbook_generation,
    start_delivery_workbook_generation,
)
from sg_preflight.screenshot_capture import (
    check_screenshot_capture_environment,
    poll_screenshot_capture,
    start_screenshot_capture,
)
from sg_preflight.utils import ensure_parent


REAL_PIPELINE_GATE_ENV = "SGFX_REAL_BMW_PIPELINE_AVAILABLE"
DEFAULT_PROFILES = ("G65", "G70", "NA8", "F70", "U10")
DEFAULT_ACTIONS = ("delivery_export", "screenshot_capture")
LANE_MINIMUM_PROFILES = {
    LANE_IDCEVO: ("G65", "G70", "NA8"),
    LANE_IDC23: ("F70", "U10"),
}
ACTION_LABELS = {
    "delivery_export": "Delivery workbook export",
    "screenshot_capture": "Screenshot capture",
}


@dataclass(frozen=True)
class ActionSpec:
    check: Callable[..., dict[str, Any]]
    start: Callable[..., Any]
    poll: Callable[[Any], dict[str, Any] | None]


ACTION_SPECS: dict[str, ActionSpec] = {
    "delivery_export": ActionSpec(
        check=check_delivery_workbook_generation_environment,
        start=start_delivery_workbook_generation,
        poll=poll_delivery_workbook_generation,
    ),
    "screenshot_capture": ActionSpec(
        check=check_screenshot_capture_environment,
        start=start_screenshot_capture,
        poll=poll_screenshot_capture,
    ),
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_parent(path)
    path.write_text(json.dumps(_json_safe(payload), indent=2, ensure_ascii=False), encoding="utf-8")


def _safe_token(value: str) -> str:
    token = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    token = "-".join(part for part in token.split("-") if part)
    return token or "probe"


def _copy_log(source: object, target: Path) -> str:
    source_text = str(source or "").strip()
    if not source_text:
        return ""
    source_path = Path(source_text)
    if not source_path.is_file():
        return source_text
    ensure_parent(target)
    shutil.copyfile(source_path, target)
    return str(target)


def _default_output_root(workspace: Path) -> Path:
    return workspace / "out" / f"g7-real-bmw-pipeline-{_stamp()}"


def _lane_coverage(results: list[dict[str, Any]]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for lane, profiles in LANE_MINIMUM_PROFILES.items():
        lane_results = [result for result in results if result.get("lane") == lane]
        invoked_profiles = {
            str(result.get("profile_id", ""))
            for result in lane_results
            if result.get("real_subprocess_invoked")
        }
        coverage[lane] = {
            "minimum_profiles": list(profiles),
            "profiles_seen": sorted({str(result.get("profile_id", "")) for result in lane_results}),
            "profiles_invoked": sorted(profile for profile in invoked_profiles if profile),
            "real_subprocess_evidence_recorded": bool(invoked_profiles),
            "minimum_profile_subset_invoked": all(profile in invoked_profiles for profile in profiles),
        }
    return coverage


def _profile_coverage(results: list[dict[str, Any]], profiles: Sequence[str], actions: Sequence[str]) -> dict[str, Any]:
    coverage: dict[str, Any] = {}
    for profile in profiles:
        profile_results = [result for result in results if result.get("profile_id") == profile]
        invoked_actions = {
            str(result.get("action", ""))
            for result in profile_results
            if result.get("real_subprocess_invoked")
        }
        coverage[profile] = {
            "actions": list(actions),
            "actions_invoked": sorted(action for action in invoked_actions if action),
            "all_actions_invoked": all(action in invoked_actions for action in actions),
        }
    return coverage


def _suite_status(
    results: list[dict[str, Any]],
    lane_coverage: dict[str, Any],
    profile_coverage: dict[str, Any],
) -> str:
    if not results:
        return "not_run"
    if any(str(result.get("status", "")).strip() == "failed" for result in results):
        return "failed"
    if any(str(result.get("status", "")).strip() == "unavailable" for result in results):
        return "unavailable"
    if all(item.get("real_subprocess_evidence_recorded") for item in lane_coverage.values()) and all(
        item.get("all_actions_invoked") for item in profile_coverage.values()
    ):
        return "passed"
    return "incomplete"


def _run_action(
    *,
    action_id: str,
    profile_id: str,
    workspace: Path,
    output_root: Path,
    bmw_root: Path | None,
    timeout_seconds: int,
    poll_interval_seconds: float,
) -> dict[str, Any]:
    spec = ACTION_SPECS[action_id]
    started_at = _utc_now()
    profile_token = _safe_token(profile_id)
    action_token = _safe_token(action_id)
    probe_path = output_root / "profiles" / profile_token / f"{action_token}.json"
    preflight = spec.check(profile_id=profile_id, workspace=workspace, bmw_root=bmw_root)
    lane = str(preflight.get("lane", LANE_UNKNOWN))
    payload: dict[str, Any] = {
        "profile_id": profile_id,
        "action": action_id,
        "label": ACTION_LABELS[action_id],
        "lane": lane,
        "status": "not_run",
        "started_at_utc": started_at,
        "completed_at_utc": "",
        "real_subprocess_invoked": False,
        "preflight": preflight,
        "result": {},
        "stdout_path": "",
        "stderr_path": "",
        "recorded_by_tool": True,
        "is_approval": False,
    }
    if not preflight.get("can_run"):
        payload.update(
            {
                "status": "unavailable",
                "completed_at_utc": _utc_now(),
                "summary": str(preflight.get("disabled_reason", "Environment pre-flight checks failed.")),
            }
        )
        _write_json(probe_path, payload)
        return payload

    try:
        job = spec.start(
            profile_id=profile_id,
            workspace=workspace,
            operator_confirmed=True,
            bmw_root=bmw_root,
            timeout_seconds=timeout_seconds,
        )
        payload["real_subprocess_invoked"] = True
        result: dict[str, Any] | None = None
        while result is None or not result.get("completed", False):
            result = spec.poll(job)
            if result is not None and result.get("completed", False):
                break
            time.sleep(poll_interval_seconds)
        final_result = result or {}
        stdout_copy = _copy_log(
            final_result.get("stdout_path", ""),
            output_root / "logs" / f"{profile_token}-{action_token}.stdout.log",
        )
        stderr_copy = _copy_log(
            final_result.get("stderr_path", ""),
            output_root / "logs" / f"{profile_token}-{action_token}.stderr.log",
        )
        payload.update(
            {
                "status": str(final_result.get("status", "unknown")),
                "completed_at_utc": _utc_now(),
                "summary": str(final_result.get("summary", "")),
                "exit_code": final_result.get("exit_code"),
                "command": list(final_result.get("command", [])),
                "stdout_path": stdout_copy,
                "stderr_path": stderr_copy,
                "result": final_result,
            }
        )
    except Exception as exc:  # noqa: BLE001
        payload.update(
            {
                "status": "failed",
                "completed_at_utc": _utc_now(),
                "summary": str(exc),
                "error_type": type(exc).__name__,
            }
        )
    _write_json(probe_path, payload)
    return payload


def run_probe_suite(
    *,
    workspace: Path | str,
    output_root: Path | str | None = None,
    bmw_root: Path | str | None = None,
    profiles: Sequence[str] = DEFAULT_PROFILES,
    actions: Sequence[str] = DEFAULT_ACTIONS,
    timeout_seconds: int = 900,
    poll_interval_seconds: float = 2.0,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    environment = os.environ if env is None else env
    workspace_path = Path(workspace).resolve()
    evidence_root = Path(output_root).resolve() if output_root is not None else _default_output_root(workspace_path)
    clean_profiles = [str(profile).strip().upper() for profile in profiles if str(profile).strip()]
    clean_actions = [str(action).strip() for action in actions if str(action).strip()]
    invalid_actions = [action for action in clean_actions if action not in ACTION_SPECS]
    if invalid_actions:
        raise ValueError(f"Unsupported action(s): {', '.join(invalid_actions)}")
    bmw_path = Path(bmw_root).resolve() if bmw_root is not None else None
    gate_enabled = environment.get(REAL_PIPELINE_GATE_ENV) == "1"
    payload: dict[str, Any] = {
        "status": "not_run",
        "gate_env": REAL_PIPELINE_GATE_ENV,
        "gate_enabled": gate_enabled,
        "started_at_utc": _utc_now(),
        "completed_at_utc": "",
        "workspace": str(workspace_path),
        "bmw_root": str(bmw_path or ""),
        "output_root": str(evidence_root),
        "minimum_profiles": list(DEFAULT_PROFILES),
        "profiles": clean_profiles,
        "actions": clean_actions,
        "results": [],
        "lane_coverage": {},
        "profile_coverage": {},
        "recorded_by_tool": True,
        "is_approval": False,
        "summary": "",
    }
    ensure_parent(evidence_root / "probe-summary.json")
    if not gate_enabled:
        payload.update(
            {
                "status": "skipped",
                "completed_at_utc": _utc_now(),
                "summary": f"Set {REAL_PIPELINE_GATE_ENV}=1 to run real BMW pipeline subprocess probes.",
            }
        )
        _write_json(evidence_root / "probe-summary.json", payload)
        return payload

    results: list[dict[str, Any]] = []
    for profile_id in clean_profiles:
        for action_id in clean_actions:
            results.append(
                _run_action(
                    action_id=action_id,
                    profile_id=profile_id,
                    workspace=workspace_path,
                    output_root=evidence_root,
                    bmw_root=bmw_path,
                    timeout_seconds=timeout_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                )
            )
    lane_coverage = _lane_coverage(results)
    profile_coverage = _profile_coverage(results, clean_profiles, clean_actions)
    status = _suite_status(results, lane_coverage, profile_coverage)
    payload.update(
        {
            "status": status,
            "completed_at_utc": _utc_now(),
            "results": results,
            "lane_coverage": lane_coverage,
            "profile_coverage": profile_coverage,
            "minimum_profile_set_real_subprocess_evidence_recorded": all(
                profile_coverage.get(profile, {}).get("all_actions_invoked", False) for profile in DEFAULT_PROFILES
            )
            if set(DEFAULT_PROFILES).issubset(set(clean_profiles))
            else False,
            "summary": (
                "Real BMW pipeline probe completed with per-lane evidence."
                if status == "passed"
                else "Real BMW pipeline probe completed; review unavailable or failed action records."
            ),
        }
    )
    _write_json(evidence_root / "probe-summary.json", payload)
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run env-gated real BMW pipeline probes for the SGFX walkthrough harness."
    )
    parser.add_argument("--workspace", default=".", help="SGFX/SVN workspace root used for local evidence output.")
    parser.add_argument("--bmw-root", default="", help="Optional BMW Git master checkout root.")
    parser.add_argument(
        "--output-root",
        default="",
        help="Evidence output folder. Defaults to <workspace>/out/g7-real-bmw-pipeline-<timestamp>.",
    )
    parser.add_argument(
        "--profiles",
        nargs="*",
        default=list(DEFAULT_PROFILES),
        help="Profiles to probe. Defaults to the Phase F minimum profile set.",
    )
    parser.add_argument(
        "--actions",
        nargs="*",
        choices=DEFAULT_ACTIONS,
        default=list(DEFAULT_ACTIONS),
        help="Probe actions to run.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=900, help="Timeout per subprocess action.")
    parser.add_argument("--poll-interval-seconds", type=float, default=2.0, help="Polling interval while actions run.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    payload = run_probe_suite(
        workspace=args.workspace,
        output_root=args.output_root or None,
        bmw_root=args.bmw_root or None,
        profiles=args.profiles,
        actions=args.actions,
        timeout_seconds=args.timeout_seconds,
        poll_interval_seconds=args.poll_interval_seconds,
    )
    print(json.dumps(_json_safe(payload), indent=2, ensure_ascii=False))
    return 1 if payload.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

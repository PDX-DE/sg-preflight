from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


sys.path.insert(0, str(_repo_root()))

from sg_preflight.bmw_delivery import read_bmw_screenshot_state
from sg_preflight.dashboard.main import DASHBOARD_GUARDRAILS, build_dashboard_snapshot


PAGES = (
    ("delivery-checklist", "Delivery Checklist", "04a-delivery-checklist"),
    ("screenshot-test-state", "Screenshot Test State", "04b-screenshot-test-state"),
    ("daily-digest", "Daily Digest", "04c-daily-digest"),
    ("manual-review", "Manual Review Companion", "04d-manual-review-companion"),
)
PHASE_F_HARNESS_PROFILES = ("G65", "G70", "NA8", "F70", "U10")
BUGGY_PROFILE_PROBES = ("G70", "NA8")
DEPENDENCY_PREFLIGHT_MAP = {
    "raco_gui": "raco",
    "raco_headless": "raco_headless",
    "blender": "blender",
    "digital_3d_car_repo": "digital_3d_car_repo",
}
OUTCOME_VOCABULARY = {
    "available",
    "missing",
    "unknown",
    "not_run",
    "passed",
    "failed",
    "skipped",
    "incomplete",
    "unavailable",
    "recorded",
}


def _page_map(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {page["id"]: page for page in snapshot["pages"]}


def _summarize_page(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": page.get("status"),
        "data_available": page.get("data_available"),
        "summary": page.get("summary"),
        "ownership_note": page.get("ownership_note", ""),
        "actions": [action.get("id") for action in page.get("actions", [])],
    }


def _clean_profiles(raw_profiles: str | list[str] | tuple[str, ...]) -> list[str]:
    raw_values: list[str] | tuple[str, ...] = [raw_profiles] if isinstance(raw_profiles, str) else raw_profiles
    profiles: list[str] = []
    for raw in raw_values:
        for part in str(raw).split(","):
            profile = part.strip().upper()
            if profile and profile not in profiles:
                profiles.append(profile)
    return profiles


def _harness_profile_sequence(raw_profiles: str | list[str] | tuple[str, ...]) -> list[str]:
    requested = _clean_profiles(raw_profiles)
    if not requested:
        requested = [PHASE_F_HARNESS_PROFILES[0]]
    profiles: list[str] = []
    for profile in [*requested, *PHASE_F_HARNESS_PROFILES]:
        if profile not in profiles:
            profiles.append(profile)
    return profiles


def _items_by_key(items: Any) -> dict[str, dict[str, Any]]:
    keyed: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        return keyed
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        if key:
            keyed[key] = item
    return keyed


def _generate_preflight(delivery_page: dict[str, Any]) -> dict[str, Any] | None:
    for action in delivery_page.get("actions", []):
        if not isinstance(action, dict):
            continue
        if action.get("id") != "generate-delivery-workbook":
            continue
        preflight = action.get("preflight")
        return preflight if isinstance(preflight, dict) else None
    return None


def _cross_panel_dependency_consistency(snapshot: dict[str, Any]) -> dict[str, Any]:
    delivery_page = _page_map(snapshot)["delivery-checklist"]
    preflight = _generate_preflight(delivery_page)
    if preflight is None:
        return {
            "status": "skipped",
            "summary": "Generate-workbook pre-flight did not render for this profile.",
            "compared": [],
            "mismatches": [],
        }
    setup_status = delivery_page.get("setup_status", {})
    setup_items = _items_by_key(setup_status.get("items", []) if isinstance(setup_status, dict) else [])
    preflight_checks = _items_by_key(preflight.get("checks", []))
    compared: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    for setup_key, preflight_key in DEPENDENCY_PREFLIGHT_MAP.items():
        setup_item = setup_items.get(setup_key)
        preflight_item = preflight_checks.get(preflight_key)
        if setup_item is None or preflight_item is None:
            continue
        setup_status_text = str(setup_item.get("status", "")).strip()
        preflight_status_text = str(preflight_item.get("status", "")).strip()
        result = {
            "setup_key": setup_key,
            "preflight_key": preflight_key,
            "setup_status": setup_status_text,
            "preflight_status": preflight_status_text,
            "matches": setup_status_text == preflight_status_text,
        }
        compared.append(result)
        if not result["matches"]:
            mismatches.append(result)
    return {
        "status": "failed" if mismatches else "passed",
        "summary": "Dependency setup panel and Generate-workbook pre-flight agree for compared dependencies."
        if not mismatches
        else "Dependency setup panel and Generate-workbook pre-flight disagree.",
        "compared": compared,
        "mismatches": mismatches,
    }


def _status_values_for_vocab_check(snapshot: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for page in snapshot.get("pages", []):
        if not isinstance(page, dict):
            continue
        status = str(page.get("status", "")).strip()
        if status:
            values.append(status)
        setup_status = page.get("setup_status")
        if isinstance(setup_status, dict):
            setup_status_text = str(setup_status.get("status", "")).strip()
            if setup_status_text:
                values.append(setup_status_text)
            for item in setup_status.get("items", []):
                if isinstance(item, dict) and str(item.get("status", "")).strip():
                    values.append(str(item.get("status", "")).strip())
        preflight = _generate_preflight(page)
        if preflight is not None:
            preflight_status = str(preflight.get("status", "")).strip()
            if preflight_status:
                values.append(preflight_status)
            for item in preflight.get("checks", []):
                if isinstance(item, dict) and str(item.get("status", "")).strip():
                    values.append(str(item.get("status", "")).strip())
    return values


def _outcome_vocab_assertion(snapshot: dict[str, Any]) -> dict[str, Any]:
    values = _status_values_for_vocab_check(snapshot)
    unexpected = sorted({value for value in values if value not in OUTCOME_VOCABULARY})
    return {
        "status": "passed" if not unexpected else "failed",
        "unexpected": unexpected,
        "checked": sorted(set(values)),
    }


def _select_profile(page: Any, profile: str, *, timeout_ms: int = 30000) -> None:
    expected_header = f"Profile: {profile}"
    body_text = page.locator("body").inner_text(timeout=timeout_ms)
    if expected_header in body_text:
        return
    selector = page.locator(".sgfx-profile-select").first
    selector.click(timeout=timeout_ms)
    try:
        page.get_by_role("option", name=profile, exact=True).click(timeout=5000)
    except Exception:  # noqa: BLE001
        page.locator(".q-menu .q-item").filter(has_text=profile).first.click(timeout=timeout_ms)
    page.get_by_text(expected_header, exact=False).wait_for(timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)


def _profile_url(base_url: str, profile: str) -> str:
    parts = urlsplit(base_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["profile"] = profile
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/", urlencode(query), parts.fragment))


def wait_for_clean_dashboard_ready(page: Any, base_url: str, *, profile: str = "", timeout_ms: int = 60000) -> None:
    target_url = _profile_url(base_url, profile) if profile else base_url
    page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    page.locator("body").wait_for(state="visible", timeout=timeout_ms)
    if profile:
        page.get_by_text(f"Profile: {profile}", exact=False).wait_for(timeout=timeout_ms)

    for _, label, _ in PAGES:
        page.get_by_role("button", name=label).wait_for(state="visible", timeout=timeout_ms)

    for guardrail in DASHBOARD_GUARDRAILS:
        page.get_by_text(guardrail, exact=True).wait_for(timeout=timeout_ms)


def wait_for_dashboard_page(page: Any, label: str, *, timeout_ms: int = 30000) -> str:
    button = page.get_by_role("button", name=label)
    button.wait_for(state="visible", timeout=timeout_ms)
    button.click(timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    page.locator(".sgfx-content .sgfx-panel-title").filter(has_text=label).first.wait_for(timeout=timeout_ms)
    body_text = page.locator("body").inner_text(timeout=timeout_ms)
    return body_text


def _browser_capture_for_profile(page: Any, evidence_dir: Path, profile: str, *, mirror_root: bool = False) -> dict[str, Any]:
    profile_dir = evidence_dir / "profiles" / profile
    profile_dir.mkdir(parents=True, exist_ok=True)
    page_results: list[dict[str, str]] = []
    guardrails_visible: dict[str, bool] = {}
    setup_visible = False

    wait_for_clean_dashboard_ready(page, page.url, profile=profile)
    for page_id, label, prefix in PAGES:
        body_now = wait_for_dashboard_page(page, label)
        html = page.content()
        html_path = profile_dir / f"{prefix}.html"
        html_path.write_text(html, encoding="utf-8")
        shot_path = profile_dir / f"{prefix}.png"
        page.screenshot(path=str(shot_path), full_page=True)
        result_html_path = html_path
        result_shot_path = shot_path
        if mirror_root:
            result_html_path = evidence_dir / f"{prefix}.html"
            result_html_path.write_text(html, encoding="utf-8")
            result_shot_path = evidence_dir / f"{prefix}.png"
            shutil.copyfile(shot_path, result_shot_path)
        page_results.append(
            {
                "page": page_id,
                "screenshot": str(result_shot_path),
                "html": str(result_html_path),
                "profile_screenshot": str(shot_path),
                "profile_html": str(html_path),
                "title": page.title(),
                "url": page.url,
            }
        )
        if page_id == "delivery-checklist":
            page.locator(".sgfx-panel-title").filter(has_text="Dependency setup").first.wait_for(timeout=30000)
            if "Local-only setup" in body_now:
                page.get_by_text("Local-only setup", exact=False).wait_for(timeout=30000)
                setup_visible = "Dependency setup" in body_now
            else:
                page.get_by_text("All setup dependencies are available.", exact=False).wait_for(timeout=30000)
                setup_visible = "Dependency setup" in body_now and "All setup dependencies are available." in body_now

    body_text = page.locator("body").inner_text(timeout=30000)
    html_text = page.content()
    for guardrail in DASHBOARD_GUARDRAILS:
        guardrails_visible[guardrail] = guardrail in body_text or guardrail in html_text
    return {
        "pages": page_results,
        "guardrails_visible_in_browser": guardrails_visible,
        "setup_surface_visible_in_browser": setup_visible,
    }


def _profile_contract(
    *,
    workspace: Path,
    profile: str,
    browser_path: str,
    browser_capture: dict[str, Any],
    console_entries: list[dict[str, str]],
) -> dict[str, Any]:
    snapshot = build_dashboard_snapshot(profile, workspace, ui_mode="clean")
    pages_by_id = _page_map(snapshot)
    delivery_page = pages_by_id["delivery-checklist"]
    setup_status = delivery_page.get("setup_status", {}) if isinstance(delivery_page, dict) else {}
    setup_items = setup_status.get("items", []) if isinstance(setup_status, dict) else []
    setup_actions = setup_status.get("actions", []) if isinstance(setup_status, dict) else []
    welcome = snapshot.get("welcome", {}) if isinstance(snapshot.get("welcome", {}), dict) else {}
    guardrails_visible = browser_capture.get("guardrails_visible_in_browser", {})
    cross_panel = _cross_panel_dependency_consistency(snapshot)
    outcome_vocab = _outcome_vocab_assertion(snapshot)
    screenshot_state = read_bmw_screenshot_state(profile, workspace=workspace)
    return {
        "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
        "workspace": str(workspace),
        "profile": profile,
        "browser_path": browser_path,
        "dashboard_pages": {
            key: _summarize_page(pages_by_id[key])
            for key in ("delivery-checklist", "screenshot-test-state", "daily-digest", "manual-review")
        },
        "welcome": welcome,
        "setup_status": setup_status,
        "cross_panel_dependency_consistency": cross_panel,
        "outcome_vocabulary": outcome_vocab,
        "screenshot_test_state_raw": screenshot_state,
        "guardrails": list(snapshot["guardrails"]),
        "assertions": {
            "guardrails_verbatim": tuple(snapshot["guardrails"]) == tuple(DASHBOARD_GUARDRAILS),
            "guardrails_visible_in_browser": all(guardrails_visible.get(guardrail, False) for guardrail in DASHBOARD_GUARDRAILS),
            "welcome_surface_present": welcome.get("setup_page_id") == "delivery-checklist" and bool(welcome.get("title")),
            "welcome_show_actual": bool(welcome.get("show")),
            "setup_surface_visible_in_browser": bool(browser_capture.get("setup_surface_visible_in_browser")),
            "setup_items_count": len(setup_items),
            "existing_install_fast_path": bool(setup_items)
            and not setup_actions
            and all(item.get("status") == "available" for item in setup_items if isinstance(item, dict)),
            "setup_actions_confirmation_gated": not setup_actions
            or all(action.get("requires_confirmation") is True for action in setup_actions),
            "cross_panel_dependency_consistency": cross_panel["status"] != "failed",
            "outcome_vocab_strict": outcome_vocab["status"] == "passed",
        },
        "browser_page_capture": {
            "pages": browser_capture.get("pages", []),
            "guardrails_visible_in_browser": guardrails_visible,
            "console_entries": console_entries,
        },
    }


def _multi_profile_assertions(profile_contracts: dict[str, dict[str, Any]]) -> dict[str, Any]:
    profiles = list(profile_contracts)
    cross_panel_by_profile = {
        profile: profile_contracts[profile]["cross_panel_dependency_consistency"]["status"] for profile in profiles
    }
    action_gates_by_profile = {
        profile: bool(profile_contracts[profile]["assertions"]["setup_actions_confirmation_gated"]) for profile in profiles
    }
    outcome_vocab_by_profile = {
        profile: bool(profile_contracts[profile]["assertions"]["outcome_vocab_strict"]) for profile in profiles
    }
    cross_panel_preflight_exercised = any(status == "passed" for status in cross_panel_by_profile.values())
    return {
        "profiles_requested": profiles,
        "minimum_profiles": list(PHASE_F_HARNESS_PROFILES),
        "minimum_profile_set_covered": all(profile in profile_contracts for profile in PHASE_F_HARNESS_PROFILES),
        "buggy_profile_covered": any(profile in profile_contracts for profile in BUGGY_PROFILE_PROBES),
        "single_run_profile_count": len(profile_contracts),
        "cross_panel_consistency_by_profile": cross_panel_by_profile,
        "cross_panel_preflight_exercised": cross_panel_preflight_exercised,
        "cross_panel_consistency": cross_panel_preflight_exercised
        and all(status != "failed" for status in cross_panel_by_profile.values()),
        "setup_actions_confirmation_gated_by_profile": action_gates_by_profile,
        "setup_actions_confirmation_gated": all(action_gates_by_profile.values()),
        "outcome_vocab_strict_by_profile": outcome_vocab_by_profile,
        "outcome_vocab_strict": all(outcome_vocab_by_profile.values()),
    }


def capture_clean_pages(base_url: str, evidence_dir: Path, workspace: Path, profiles: str | list[str] | tuple[str, ...]) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    profile_sequence = _harness_profile_sequence(profiles)
    console_entries: list[dict[str, str]] = []
    browser_path = "regular Playwright fallback"
    with sync_playwright() as playwright:
        launch_notes: list[str] = []
        try:
            browser = playwright.chromium.launch(headless=True)
        except Exception as exc:
            launch_notes.append(f"chromium launch failed: {exc!r}")
            browser = playwright.chromium.launch(channel="msedge", headless=True)

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.on("console", lambda msg: console_entries.append({"type": msg.type, "text": msg.text}))
        wait_for_clean_dashboard_ready(page, base_url)
        for note in launch_notes:
            console_entries.append({"type": "info", "text": note})
        primary_profile = profile_sequence[0]
        browser_captures = {
            profile: _browser_capture_for_profile(page, evidence_dir, profile, mirror_root=profile == primary_profile)
            for profile in profile_sequence
        }
        browser.close()

    profile_contracts = {
        profile: _profile_contract(
            workspace=workspace,
            profile=profile,
            browser_path=browser_path,
            browser_capture=browser_captures[profile],
            console_entries=console_entries,
        )
        for profile in profile_sequence
    }
    primary_profile = profile_sequence[0]
    contract = dict(profile_contracts[primary_profile])
    contract["primary_profile"] = primary_profile
    contract["profiles"] = profile_sequence
    contract["profile_contracts"] = profile_contracts
    contract["multi_profile_assertions"] = _multi_profile_assertions(profile_contracts)
    return contract


def main(argv: list[str]) -> int:
    if len(argv) < 5:
        print("usage: capture_clean_pages.py <base-url> <evidence-dir> <workspace> <profile> [profile ...]", file=sys.stderr)
        return 2

    base_url = argv[1]
    evidence_dir = Path(argv[2])
    workspace = Path(argv[3])
    profiles = _harness_profile_sequence(argv[4:])
    evidence_dir.mkdir(parents=True, exist_ok=True)
    contract = capture_clean_pages(base_url, evidence_dir, workspace, profiles)
    contract_path = evidence_dir / "page-guardrail-delivery-probes.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    print(json.dumps({"status": "recorded", "path": str(contract_path), "profiles": profiles}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

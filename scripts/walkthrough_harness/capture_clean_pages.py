from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any


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


def wait_for_clean_dashboard_ready(page: Any, base_url: str, *, timeout_ms: int = 60000) -> None:
    page.goto(base_url, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("networkidle", timeout=timeout_ms)
    page.locator("body").wait_for(state="visible", timeout=timeout_ms)

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


def capture_clean_pages(base_url: str, evidence_dir: Path, workspace: Path, profile: str) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    console_entries: list[dict[str, str]] = []
    page_results: list[dict[str, str]] = []
    guardrails_visible: dict[str, bool] = {}
    setup_visible = False
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

        for page_id, label, prefix in PAGES:
            body_now = wait_for_dashboard_page(page, label)
            html = page.content()
            html_path = evidence_dir / f"{prefix}.html"
            html_path.write_text(html, encoding="utf-8")
            shot_path = evidence_dir / f"{prefix}.png"
            page.screenshot(path=str(shot_path), full_page=True)
            page_results.append(
                {
                    "page": page_id,
                    "screenshot": str(shot_path),
                    "html": str(html_path),
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
        for note in launch_notes:
            console_entries.append({"type": "info", "text": note})
        browser.close()

    snapshot = build_dashboard_snapshot(profile, workspace, ui_mode="clean")
    pages_by_id = _page_map(snapshot)
    delivery_page = pages_by_id["delivery-checklist"]
    setup_status = delivery_page.get("setup_status", {}) if isinstance(delivery_page, dict) else {}
    setup_items = setup_status.get("items", []) if isinstance(setup_status, dict) else []
    setup_actions = setup_status.get("actions", []) if isinstance(setup_status, dict) else []
    welcome = snapshot.get("welcome", {}) if isinstance(snapshot.get("welcome", {}), dict) else {}

    screenshot_state = read_bmw_screenshot_state(profile, workspace=workspace)
    contract = {
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
        "screenshot_test_state_raw": screenshot_state,
        "guardrails": list(snapshot["guardrails"]),
        "assertions": {
            "guardrails_verbatim": tuple(snapshot["guardrails"]) == tuple(DASHBOARD_GUARDRAILS),
            "guardrails_visible_in_browser": all(guardrails_visible.get(guardrail, False) for guardrail in DASHBOARD_GUARDRAILS),
            "welcome_surface_present": welcome.get("setup_page_id") == "delivery-checklist" and bool(welcome.get("title")),
            "welcome_show_actual": bool(welcome.get("show")),
            "setup_surface_visible_in_browser": setup_visible,
            "setup_items_count": len(setup_items),
            "existing_install_fast_path": bool(setup_items)
            and not setup_actions
            and all(item.get("status") == "available" for item in setup_items if isinstance(item, dict)),
            "setup_actions_confirmation_gated": not setup_actions
            or all(action.get("requires_confirmation") is True for action in setup_actions),
        },
        "browser_page_capture": {
            "pages": page_results,
            "guardrails_visible_in_browser": guardrails_visible,
            "console_entries": console_entries,
        },
    }
    return contract


def main(argv: list[str]) -> int:
    if len(argv) != 5:
        print("usage: capture_clean_pages.py <base-url> <evidence-dir> <workspace> <profile>", file=sys.stderr)
        return 2

    base_url = argv[1]
    evidence_dir = Path(argv[2])
    workspace = Path(argv[3])
    profile = argv[4]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    contract = capture_clean_pages(base_url, evidence_dir, workspace, profile)
    contract_path = evidence_dir / "page-guardrail-delivery-probes.json"
    contract_path.write_text(json.dumps(contract, indent=2), encoding="utf-8")
    print(json.dumps({"status": "recorded", "path": str(contract_path)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

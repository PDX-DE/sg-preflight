"""Dashboard snapshot construction: navigation/page metadata, the per-profile
page-builder registry (`build_dashboard_snapshot` / `build_dashboard_page`),
and the ticket-context helpers that feed the snapshot's welcome/guardrail
payload.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from sg_preflight.dashboard_pages_config import (
    _api_version_coverage_page,
    _bmw_process_page,
    _country_variant_coverage_page,
    _cross_car_comparison_page,
    _daily_digest_page,
    _deferred_daily_digest_page,
    _deferred_team_digest_board_page,
    _delivery_checklist_page as _build_delivery_checklist_page,
    _disabled_tests_page,
    _export_size_trend_page,
    _home_page,
    _onboarding_guide_page,
    _operator_handoff_page,
    _qa_workflows_page,
    _risk_score_page,
    _screenshot_test_state_page,
    _setup_doctor_page,
    _team_digest_board_page,
)
from sg_preflight.dashboard_pages_workflows import _batch_full_qa_pass_page, _full_qa_pass_page, _manual_review_page
from sg_preflight.dashboard_preferences import (
    _clean_theme,
    _dashboard_profile_known,
    _dashboard_run_mode,
    _path_label,
    _resolve_dashboard_profile_id,
    _workspace,
    dashboard_profile_options,
    load_dashboard_preference,
)
from sg_preflight.profile_change_detection import detect_changed_profiles_since_last_run
from sg_preflight.profiles import PROFILE_REGISTRY_DYNAMIC_SOURCE, PROFILE_SCOPE_DEFAULT
from sg_preflight.services import operator_ui_root
from sg_preflight.shell_registry import (
    HOME_ROUTE_ID,
    HOME_SUBTITLE,
    HOME_TITLE,
    NAVIGATION_GROUP_ORDER,
    SHORTCUT_ACTIONS,
)
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS, get_surface_descriptor, is_registered_surface

DASHBOARD_TITLE = "Seriengrafik: Project Quality-Hero"
DASHBOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
DASHBOARD_NAVIGATION = ((HOME_ROUTE_ID, HOME_TITLE),) + tuple(
    (item.surface_id, item.title) for item in SURFACE_DESCRIPTORS
)
# Sidebar information architecture: the flat page list above is grouped into a small
# number of scannable sections. "home" is the standalone hub and is not listed here.
# Any page id missing from every group falls into a visible "More" catch-all so a new
# page can never silently vanish from navigation.
DASHBOARD_NAV_GROUPS = tuple(
    (
        group,
        tuple(
            item.surface_id
            for item in SURFACE_DESCRIPTORS
            if item.navigation_group == group
        ),
    )
    for group in NAVIGATION_GROUP_ORDER
)
DASHBOARD_SHORTCUTS = (
    "F1 Help",
    "F2 Profile switch",
    "F5 Refresh page",
    "/ Jump to page",
    "F12 Diagnostic",
    "Esc Close sidebar",
)
DASHBOARD_SHORTCUT_ACTIONS = SHORTCUT_ACTIONS
SETUP_COMPLETE_NOTE = "Setup complete — go to evidence pages to start your QA Hero workflow."


def _daily_digest_ticket_context(workspace: Path | str) -> dict[str, Any]:
    from sg_preflight.dashboard import main as _main_mod

    return _main_mod._daily_digest_ticket_context_impl(
        workspace,
        ticket_id_placeholder=_main_mod._dashboard_default_ticket_id(workspace),
        ticket_from_operator_state=_main_mod._dashboard_ticket_from_operator_state,
        ticket_from_git_branch=_main_mod._dashboard_ticket_from_git_branch,
    )


def _dashboard_active_ticket_id(workspace: Path | str) -> str:
    from sg_preflight.dashboard import main as _main_mod

    return _main_mod._dashboard_active_ticket_id_impl(
        workspace,
        fallback_ticket_id=_main_mod._dashboard_default_ticket_id(workspace),
        ticket_from_operator_state=_main_mod._dashboard_ticket_from_operator_state,
        ticket_from_git_branch=_main_mod._dashboard_ticket_from_git_branch,
    )


@lru_cache(maxsize=8)
def _dashboard_changed_profiles(workspace_text: str, bmw_root_text: str) -> dict[str, Any]:
    return detect_changed_profiles_since_last_run(
        workspace=Path(workspace_text),
        bmw_root=Path(bmw_root_text) if bmw_root_text else None,
    )


def _delivery_checklist_page(
    profile_id: str,
    workspace: Path,
    *,
    bmw_root: Path | str | None = None,
    setup_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    page = _build_delivery_checklist_page(
        profile_id,
        workspace,
        bmw_root=bmw_root,
        setup_status=setup_status,
    )
    descriptor = get_surface_descriptor("delivery-checklist")
    page["title"] = descriptor.title
    page["tagline"] = descriptor.subtitle
    return page


_EAGER_PAGE_IDS = frozenset({"home", "bmw-process"})


def _deferred_page_stub(page_id: str, title: str) -> dict[str, Any]:
    return _apply_shell_metadata(page_id, {
        "id": page_id,
        "title": title,
        "tagline": "",
        "status": "not_run",
        "raw_status": "not_run",
        "data_available": False,
        "deferred": True,
        "summary": f"{title} loads when opened.",
        "items": [],
        "actions": [],
    })


def _apply_shell_metadata(page_id: str, page: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(page)
    if page_id == HOME_ROUTE_ID:
        normalized["title"] = HOME_TITLE
        normalized["tagline"] = HOME_SUBTITLE
    elif is_registered_surface(page_id):
        descriptor = get_surface_descriptor(page_id)
        normalized["title"] = descriptor.title
        normalized["tagline"] = descriptor.subtitle
    return normalized


def build_dashboard_snapshot(
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
    defer_daily_digest: bool = False,
    defer_team_digest_board: bool = False,
    lazy_pages: bool = False,
    materialize_page_ids: tuple[str, ...] = (),
    persist_dependency_state: bool = True,
) -> dict[str, Any]:
    from sg_preflight.dashboard import main as _main_mod

    root = _workspace(workspace)
    profile_options = dashboard_profile_options(bmw_root=bmw_root, profile_scope=PROFILE_SCOPE_DEFAULT)
    profile_options_all = dashboard_profile_options(bmw_root=bmw_root, profile_scope="all")
    profile_registry_status = (
        "available"
        if any(option.get("registry_source") == PROFILE_REGISTRY_DYNAMIC_SOURCE for option in profile_options_all)
        else "unavailable"
    )
    resolved_profile_id = _resolve_dashboard_profile_id(
        profile_id,
        profile_options_all,
        workspace=root,
        fallback_options=profile_options,
    )
    profile_known = _dashboard_profile_known(resolved_profile_id, profile_options_all)
    profile_in_default_view = _dashboard_profile_known(resolved_profile_id, profile_options)
    theme = _clean_theme(ui_mode or load_dashboard_preference(root))
    setup_status = _main_mod.build_dependency_onboarding_status(
        workspace=root,
        bmw_root=bmw_root,
        persist_auto_detected_paths=persist_dependency_state,
    )
    active_ticket_id = _main_mod._dashboard_active_ticket_id(root)
    daily_ticket_context = _main_mod._daily_digest_ticket_context(root)
    output_root = operator_ui_root(root)
    daily_digest_page = (
        _deferred_daily_digest_page(resolved_profile_id, daily_ticket_context)
        if defer_daily_digest
        else _daily_digest_page(
            root,
            resolved_profile_id,
            active_ticket_id=active_ticket_id,
            ticket_context=daily_ticket_context,
        )
    )
    team_digest_page = (
        _deferred_team_digest_board_page(resolved_profile_id)
        if defer_team_digest_board
        else _team_digest_board_page(root, resolved_profile_id, bmw_root=bmw_root)
    )
    changed_profiles = _dashboard_changed_profiles(
        str(root),
        str(Path(bmw_root).resolve()) if bmw_root is not None else "",
    )
    shortcuts = list(DASHBOARD_SHORTCUTS)
    shortcut_actions = [{"key": key, "message": message} for key, message in DASHBOARD_SHORTCUT_ACTIONS]
    return {
        "title": DASHBOARD_TITLE,
        "profile_id": resolved_profile_id,
        "profile_known": profile_known,
        "profile_warning": ""
        if profile_known
        else f"Profile {resolved_profile_id} is not in the current profile registry. Select a registered profile or check config.",
        "profile_options": profile_options,
        "profile_options_all": profile_options_all,
        "profile_show_all": bool(profile_known and not profile_in_default_view),
        "profile_registry": {
            "status": profile_registry_status,
            "source": PROFILE_REGISTRY_DYNAMIC_SOURCE if profile_registry_status == "available" else "fallback_static_23",
            "default_count": len(profile_options),
            "total_count": len(profile_options_all),
            "summary": (
                f"{len(profile_options)} active build profile(s) shown by default; "
                f"{len(profile_options_all)} registered profile(s) available."
                if profile_registry_status == "available"
                else "BMW registry source unavailable; using the static fallback profile list."
            ),
        },
        "workspace": str(root),
        "workspace_label": _path_label(root),
        "output_root": str(output_root),
        "output_root_label": _path_label(output_root),
        "theme": theme,
        "navigation": [{"id": page_id, "label": label} for page_id, label in DASHBOARD_NAVIGATION],
        "navigation_groups": _build_navigation_groups(
            [{"id": page_id, "label": label} for page_id, label in DASHBOARD_NAVIGATION]
        ),
        "shortcuts": shortcuts,
        "shortcut_actions": shortcut_actions,
        "guardrails": list(DASHBOARD_GUARDRAILS),
        "welcome": {
            "show": bool(setup_status.get("first_run")),
            "title": "Pick a profile",
            "summary": (
                "Local-only preflight for collecting delivery evidence. "
                "Choose the car profile first, then start Full QA Pass from the visible entry point."
            ),
            "setup_page_id": "setup-doctor",
            "setup_action_count": len(
                [action for action in setup_status.get("actions", []) if isinstance(action, dict)]
            ),
            "setup_complete_note": SETUP_COMPLETE_NOTE,
            "guardrails": list(DASHBOARD_GUARDRAILS),
        },
        "changed_profiles": changed_profiles,
        "pages": _build_dashboard_pages(
            page_builders={
                "home": lambda: _home_page(root),
                "full-qa-pass": lambda: _full_qa_pass_page(
                    resolved_profile_id,
                    root,
                    bmw_root=bmw_root,
                    trusted_tool_mode=_dashboard_run_mode(root) == "automatic",
                ),
                "batch-full-qa-pass": lambda: _batch_full_qa_pass_page(resolved_profile_id, root),
                "delivery-checklist": lambda: _delivery_checklist_page(
                    resolved_profile_id, root, bmw_root=bmw_root, setup_status=setup_status
                ),
                "disabled-tests": lambda: _disabled_tests_page(root, bmw_root=bmw_root),
                "api-version-coverage": lambda: _api_version_coverage_page(root, bmw_root=bmw_root),
                "country-variant-coverage": lambda: _country_variant_coverage_page(root, bmw_root=bmw_root),
                "export-size-trend": lambda: _export_size_trend_page(root, bmw_root=bmw_root),
                "onboarding-guide": lambda: _onboarding_guide_page(
                    resolved_profile_id,
                    root,
                    bmw_root=bmw_root,
                    setup_status=setup_status,
                ),
                "setup-doctor": lambda: _setup_doctor_page(root),
                "qa-workflows": lambda: _qa_workflows_page(root),
                "bmw-process": lambda: _bmw_process_page(),
                "screenshot-test-state": lambda: _screenshot_test_state_page(
                    resolved_profile_id, root, bmw_root=bmw_root
                ),
                "risk-score": lambda: _risk_score_page(resolved_profile_id, root, bmw_root=bmw_root),
                "cross-car-comparison": lambda: _cross_car_comparison_page(root, bmw_root=bmw_root),
                "daily-digest": lambda: daily_digest_page,
                "team-digest-board": lambda: team_digest_page,
                "operator-handoff": lambda: _operator_handoff_page(resolved_profile_id, root),
                "manual-review": lambda: _manual_review_page(
                    resolved_profile_id, root, active_ticket_id=active_ticket_id
                ),
            },
            lazy_pages=lazy_pages,
            materialize_page_ids=materialize_page_ids,
        ),
    }


def _build_navigation_groups(
    navigation: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Group the flat navigation list into the sidebar sections.

    ``home`` is left out (it is the standalone hub). Any page not named in
    ``DASHBOARD_NAV_GROUPS`` lands in a visible ``More`` group so navigation can
    never silently drop a page.
    """

    labels = {str(item["id"]): str(item["label"]) for item in navigation}
    grouped_ids: set[str] = set()
    groups: list[dict[str, Any]] = []
    for title, page_ids in DASHBOARD_NAV_GROUPS:
        items = []
        for page_id in page_ids:
            if page_id not in labels:
                continue
            grouped_ids.add(page_id)
            items.append({"id": page_id, "label": labels[page_id]})
        if items:
            groups.append({"title": title, "items": items})
    leftover = [
        {"id": str(item["id"]), "label": str(item["label"])}
        for item in navigation
        if str(item["id"]) not in grouped_ids and str(item["id"]) != "home"
    ]
    if leftover:
        groups.append({"title": "More", "items": leftover})
    return groups


def _build_dashboard_pages(
    *,
    page_builders: dict[str, Any],
    lazy_pages: bool,
    materialize_page_ids: tuple[str, ...],
) -> list[dict[str, Any]]:
    titles = dict(DASHBOARD_NAVIGATION)
    requested = {str(item).strip() for item in materialize_page_ids if str(item).strip()}
    pages: list[dict[str, Any]] = []
    for page_id, builder in page_builders.items():
        if lazy_pages and page_id not in _EAGER_PAGE_IDS and page_id not in requested:
            pages.append(_deferred_page_stub(page_id, titles.get(page_id, page_id)))
        else:
            pages.append(_apply_shell_metadata(page_id, builder()))
    return pages


def build_dashboard_page(
    page_id: str,
    profile_id: str,
    workspace: Path | str,
    *,
    bmw_root: Path | str | None = None,
    ui_mode: str | None = None,
    persist_dependency_state: bool = True,
) -> dict[str, Any]:
    # Resolve through the dashboard.main facade so tests patching
    # "sg_preflight.dashboard.main.build_dashboard_snapshot" keep intercepting this call.
    import sg_preflight.dashboard.main as _main_mod

    snapshot = _main_mod.build_dashboard_snapshot(
        profile_id=profile_id,
        workspace=workspace,
        bmw_root=bmw_root,
        ui_mode=ui_mode,
        defer_daily_digest=page_id != "daily-digest",
        defer_team_digest_board=page_id != "team-digest-board",
        lazy_pages=True,
        materialize_page_ids=(page_id,),
        persist_dependency_state=persist_dependency_state,
    )
    for page in snapshot["pages"]:
        if str(page.get("id")) == page_id:
            return page
    raise KeyError(f"Unknown dashboard page: {page_id}")

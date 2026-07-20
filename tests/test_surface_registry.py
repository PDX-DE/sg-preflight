from __future__ import annotations

from dataclasses import FrozenInstanceError
import unittest

from sg_preflight.shell_registry import (
    HOME_HUB_TILES,
    HOME_ROUTE_ID,
    HOME_SUBTITLE,
    HOME_TITLE,
    NAVIGATION_GROUP_ORDER,
    SHORTCUT_ACTIONS,
)
from sg_preflight.surface_registry import (
    RENDERER_KINDS,
    SURFACE_DESCRIPTORS,
    get_surface_descriptor,
    is_registered_surface,
)


EXPECTED_SURFACES = (
    ("full-qa-pass", "Selected-Car Checks", "Run audited local checks and review evidence for the selected car.", "Daily work", "workflow", True),
    ("batch-full-qa-pass", "Batch QA Evidence", "Review existing sequential-run evidence across car profiles.", "Daily work", "workflow", True),
    ("delivery-checklist", "Delivery documentation", "Read-only delivery workbook evidence for the selected profile.", "Delivery", "evidence", True),
    ("disabled-tests", "Disabled Tests", "Per-car disabled-test inventory from local test_config.lua files.", "Screenshots & coverage", "matrix", True),
    ("api-version-coverage", "API Version", "Shared MainInterfaces API reference with cautious impact hints.", "Screenshots & coverage", "matrix", True),
    ("country-variant-coverage", "Country Variants", "Country-coding test matrix with expected, actual, and diff evidence slots.", "Screenshots & coverage", "matrix", True),
    ("export-size-trend", "Size Trend", "Export-size workbook trends from local size_analysis evidence.", "Screenshots & coverage", "evidence", True),
    ("onboarding-guide", "Onboarding Guide", "New-operator path through setup, evidence pages, manual review, and handoff.", "Setup & help", "workflow", True),
    ("setup-doctor", "Setup Doctor", "Detect-only setup status for local SGFX dependencies.", "Setup & help", "overview", True),
    ("qa-workflows", "QA Workflows", "Local JSON workflow catalog with manual-attestation gates preserved.", "Setup & help", "workflow", True),
    ("bmw-process", "BMW Process", "Read-only workflow contracts for BMW interface, triage, and visual review paths.", "Setup & help", "workflow", True),
    ("screenshot-test-state", "Screenshot Test State", "BMW + MINI baseline / actual / diff counts per brand.", "Screenshots & coverage", "matrix", True),
    ("risk-score", "Risk Score", "Per-car review focus signal with delta since latest local manual review.", "Screenshots & coverage", "evidence", True),
    ("cross-car-comparison", "Comparison Evidence", "Read comparison evidence when a car-profile pair is available.", "Screenshots & coverage", "matrix", True),
    ("daily-digest", "Daily Digest", "Morning status snapshot for the SG Daily standup.", "Reviews & digests", "overview", True),
    ("team-digest-board", "Team Digest Board", "Local snapshot for standup review across selected car profiles.", "Reviews & digests", "overview", True),
    ("operator-handoff", "Operator Handoff", "Record the stopping point before a shift handoff.", "Reviews & digests", "workflow", True),
    ("manual-review", "Manual Review Companion", "Step through the 7 Quality-Hero review steps. Operator verdict per step.", "Reviews & digests", "review", True),
    ("about", "About", "Local SGFX preflight scope, evidence sources, and data-handling guardrails.", "Setup & help", "about", False),
)

EXPECTED_SURFACE_IDS = tuple(item[0] for item in EXPECTED_SURFACES)
EXPECTED_HOME_TILES = (
    ("full-qa-pass", "Selected-Car Checks", "dashboard", "Open checks and evidence for the selected car."),
    ("delivery-checklist", "Delivery documentation", "fact_check", "Read delivery evidence for the selected car."),
    ("screenshot-test-state", "Screenshot Test State", "image", "Review expected, actual, and diff evidence."),
    ("manual-review", "Manual Review Companion", "rate_review", "Continue the operator-owned review steps."),
    ("daily-digest", "Daily Digest", "summarize", "Read the local standup snapshot."),
    ("setup-doctor", "Setup Doctor", "settings_suggest", "Check local dependency readiness."),
)


class TestSurfaceRegistry(unittest.TestCase):
    def test_surface_registry_matches_the_approved_contract(self) -> None:
        actual = tuple(
            (
                item.surface_id,
                item.title,
                item.subtitle,
                item.navigation_group,
                item.renderer_kind,
                item.operational,
            )
            for item in SURFACE_DESCRIPTORS
        )

        self.assertEqual(actual, EXPECTED_SURFACES)
        self.assertEqual(sum(item.operational for item in SURFACE_DESCRIPTORS), 18)
        self.assertEqual({item.navigation_group for item in SURFACE_DESCRIPTORS}, set(NAVIGATION_GROUP_ORDER))
        self.assertEqual(
            RENDERER_KINDS,
            frozenset({"overview", "matrix", "evidence", "workflow", "review", "about"}),
        )
        self.assertTrue(all(item.subtitle and "\n" not in item.subtitle for item in SURFACE_DESCRIPTORS))

    def test_lookup_and_immutability_preserve_stable_surface_ids(self) -> None:
        descriptor = get_surface_descriptor("delivery-checklist")

        self.assertEqual(descriptor.title, "Delivery documentation")
        self.assertTrue(is_registered_surface("delivery-checklist"))
        self.assertFalse(is_registered_surface("home"))
        with self.assertRaises(KeyError):
            get_surface_descriptor("not-a-surface")
        with self.assertRaises(FrozenInstanceError):
            descriptor.title = "Changed"

    def test_shell_contract_keeps_home_outside_the_surface_registry(self) -> None:
        self.assertEqual(HOME_ROUTE_ID, "home")
        self.assertEqual(HOME_TITLE, "QA overview")
        self.assertEqual(HOME_SUBTITLE, "Review the selected car and continue its next local QA action.")
        self.assertNotIn(HOME_ROUTE_ID, EXPECTED_SURFACE_IDS)
        self.assertEqual(
            tuple((item.surface_id, item.title, item.icon_key, item.subtitle) for item in HOME_HUB_TILES),
            EXPECTED_HOME_TILES,
        )
        self.assertTrue(all(is_registered_surface(item.surface_id) for item in HOME_HUB_TILES))

    def test_shell_groups_and_shortcuts_match_the_approved_contract(self) -> None:
        self.assertEqual(
            NAVIGATION_GROUP_ORDER,
            ("Daily work", "Delivery", "Screenshots & coverage", "Reviews & digests", "Setup & help"),
        )
        self.assertEqual(
            SHORTCUT_ACTIONS,
            (
                ("F1", "Open keyboard help"),
                ("F2", "Focus profile selection"),
                ("F5", "Refresh the active page"),
                ("/", "Jump to page"),
                ("F12", "Open local diagnostics"),
                ("Esc", "Close the topmost overlay or sidebar"),
            ),
        )

    def test_dashboard_consumes_the_shared_shell_and_surface_metadata(self) -> None:
        from sg_preflight.dashboard.main import (
            ABOUT_CONTENT,
            DASHBOARD_NAV_GROUPS,
            DASHBOARD_NAVIGATION,
            DASHBOARD_SHORTCUT_ACTIONS,
            HOME_HUB_TILES as DASHBOARD_HOME_HUB_TILES,
            PRIMARY_SURFACE_SUBTITLES,
        )

        labels = dict(DASHBOARD_NAVIGATION)
        self.assertEqual(DASHBOARD_NAVIGATION[0], (HOME_ROUTE_ID, HOME_TITLE))
        self.assertEqual(tuple(title for title, _page_ids in DASHBOARD_NAV_GROUPS), NAVIGATION_GROUP_ORDER)
        self.assertEqual(
            DASHBOARD_HOME_HUB_TILES,
            tuple(
                (item.surface_id, item.title, item.icon_key, item.subtitle)
                for item in HOME_HUB_TILES
            ),
        )
        self.assertEqual(DASHBOARD_SHORTCUT_ACTIONS, SHORTCUT_ACTIONS)
        self.assertTrue(all(labels[item.surface_id] == item.title for item in SURFACE_DESCRIPTORS))
        self.assertEqual(
            PRIMARY_SURFACE_SUBTITLES,
            {item.surface_id: item.subtitle for item in SURFACE_DESCRIPTORS},
        )
        groups = {title: page_ids for title, page_ids in DASHBOARD_NAV_GROUPS}
        for group_title in NAVIGATION_GROUP_ORDER:
            registered_ids = tuple(
                page_id for page_id in groups[group_title] if is_registered_surface(page_id)
            )
            expected_ids = tuple(
                item.surface_id
                for item in SURFACE_DESCRIPTORS
                if item.navigation_group == group_title
            )
            self.assertEqual(registered_ids, expected_ids)
            self.assertEqual(groups[group_title][: len(expected_ids)], expected_ids)
        self.assertEqual(ABOUT_CONTENT["tagline"], get_surface_descriptor("about").subtitle)

    def test_dashboard_normalizes_materialized_and_lazy_shell_metadata(self) -> None:
        from sg_preflight.dashboard.main import _build_dashboard_pages, _deferred_page_stub

        pages = _build_dashboard_pages(
            page_builders={
                "home": lambda: {"id": "home", "title": "Old Home", "tagline": "Old Home subtitle"},
                "setup-doctor": lambda: {
                    "id": "setup-doctor",
                    "title": "Old Setup",
                    "tagline": "Old Setup subtitle",
                },
            },
            lazy_pages=False,
            materialize_page_ids=(),
        )
        pages_by_id = {page["id"]: page for page in pages}
        lazy_page = _deferred_page_stub("risk-score", "Old Risk")

        self.assertEqual(pages_by_id["home"]["title"], HOME_TITLE)
        self.assertEqual(pages_by_id["home"]["tagline"], HOME_SUBTITLE)
        self.assertEqual(pages_by_id["setup-doctor"]["title"], "Setup Doctor")
        self.assertEqual(
            pages_by_id["setup-doctor"]["tagline"],
            get_surface_descriptor("setup-doctor").subtitle,
        )
        self.assertEqual(lazy_page["title"], "Risk Score")
        self.assertEqual(lazy_page["tagline"], get_surface_descriptor("risk-score").subtitle)


if __name__ == "__main__":
    unittest.main()

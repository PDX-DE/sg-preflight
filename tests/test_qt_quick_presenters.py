from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sg_preflight.surface_registry import SURFACE_DESCRIPTORS, SurfaceDescriptor, get_surface_descriptor


PRESENTED_KEYS = {
    "surfaceId",
    "rendererKind",
    "title",
    "subtitle",
    "status",
    "dataAvailable",
    "primaryText",
    "visibleItems",
    "visibleItemCount",
    "sections",
    "actions",
    "artifacts",
    "provenance",
    "ownershipNote",
    "readOnly",
    "isApproval",
    "manualReviewRequired",
    "recordsOperatorVerdict",
}

VISIBLE_ITEM_KEYS = {
    "itemId",
    "sectionId",
    "label",
    "value",
    "detail",
    "status",
    "expected",
    "actual",
    "diff",
    "source",
    "revision",
}


def _step(step_id: str, label: str) -> dict[str, object]:
    return {
        "id": step_id,
        "label": label,
        "title": label,
        "status": "partial",
        "summary": f"detail::{label}",
    }


def _surface_field_cases() -> dict[str, dict[str, object]]:
    cases: dict[str, dict[str, object]] = {
        "full-qa-pass": {
            "required": "steps",
            "payload": {
                "progress": {"completed_steps": 1, "total_steps": 9, "percent": 11},
                "steps": [_step("setup", "nested::full-qa-pass")],
                "evidence_summary": (
                    "Profile: G45\n"
                    "Local checks: 0 errors, 2 warnings, 3 info\n"
                    "Provenance: Local SGFX action sgfx_preflight__g45\n"
                    "Open owner: Reviewer\n"
                    "Retest hash: action-001-preflight\n"
                    "Next action: Review local findings"
                ),
            },
        },
        "batch-full-qa-pass": {
            "required": "results",
            "payload": {
                "progress": {"completed_profiles": 1, "total_profiles": 2, "percent": 50},
                "results": [
                    {
                        "profile_id": "nested::batch-full-qa-pass",
                        "status": "partial",
                        "summary": "one profile complete",
                    }
                ],
            },
        },
        "delivery-checklist": {
            "required": "checks",
            "payload": {
                "checks": [
                    {
                        "key": "delivery-revision",
                        "label": "Delivery revision",
                        "status": "available",
                        "raw_value": "nested::delivery-checklist",
                        "revision": "delivery-rev-1",
                    }
                ],
                "generated_at_utc": "2026-07-11T18:00:00Z",
            },
        },
        "disabled-tests": {
            "required": "board_rows",
            "payload": {
                "counts": {"disabled_call_total": 1},
                "baseline": {"state": "ready", "revision": "disabled-rev-1"},
                "board_rows": [
                    {"label": "Disabled call", "status": "review", "detail": "nested::disabled-tests"}
                ],
            },
        },
        "api-version-coverage": {
            "required": "shared_api_references",
            "payload": {
                "counts": {"shared_brand_ready": 1},
                "shared_api_references": [
                    {
                        "brand": "BMW",
                        "current_version": "nested::api-version-coverage",
                        "revision": "api-rev-1",
                    }
                ],
                "interface_family_entries": [
                    {"model_id": "G65", "hmi_family_label": "IDC", "hmi_interface_version": "7"}
                ],
                "impact_scans": [
                    {"matched_car_count": 1, "matched_file_count": 2, "status": "review"}
                ],
            },
        },
        "country-variant-coverage": {
            "required": "entries",
            "payload": {
                "counts": {"row_total": 1},
                "entries": [
                    {
                        "test_name": "nested::country-variant-coverage",
                        "country_variant_id": "DE",
                        "expected_path": "baseline.png",
                        "actual_path": "actual.png",
                        "diff_path": "diff.png",
                        "expected_present": True,
                        "actual_present": True,
                        "diff_present": True,
                        "status": "review",
                    }
                ],
                "expectations": [
                    {
                        "car": "G65",
                        "feature": "country coding",
                        "expected_variants": ["DE"],
                        "observed_rows": ["DE"],
                        "review_label": "mapped",
                    }
                ],
            },
        },
        "export-size-trend": {
            "required": "trend_changes",
            "payload": {
                "counts": {"trend_change_count": 1},
                "trend_changes": [
                    {
                        "profile_id": "nested::export-size-trend",
                        "status": "review",
                        "delta_total": 12.5,
                        "delta_percent": 2.5,
                        "revision": "size-rev-1",
                    }
                ],
                "workbooks": [
                    {"relative_path": "size.xlsx", "status": "parsed", "revision": "size-rev-1"}
                ],
            },
        },
        "onboarding-guide": {
            "required": "steps",
            "payload": {
                "profile_id": "G65",
                "onboarding_status": "partial",
                "setup_status": {"status": "blocked", "counts": {"missing": 1}},
                "steps": [_step("setup", "nested::onboarding-guide")],
                "items": [{"label": "Setup", "status": "blocked", "detail": "operator setup"}],
            },
        },
        "setup-doctor": {
            "required": "board_rows",
            "payload": {
                "counts": {"found": 3, "required_missing": 1},
                "version_validation": {"ok": 2, "drift": 1, "revision": "setup-rev-1"},
                "board_rows": [
                    {"label": "Dependency", "status": "blocked", "detail": "nested::setup-doctor"}
                ],
            },
        },
        "qa-workflows": {
            "required": "workflows",
            "payload": {
                "workflows": [
                    {
                        "id": "workflow-1",
                        "name": "nested::qa-workflows",
                        "last_status": "not_started",
                        "check_count": 2,
                    }
                ],
                "board_rows": [
                    {"label": "Workflow", "status": "not_started", "detail": "two checks"}
                ],
            },
        },
        "bmw-process": {
            "required": "contracts",
            "payload": {
                "contracts": [
                    {
                        "key": "triage",
                        "label": "nested::bmw-process",
                        "steps": ["Inspect"],
                        "evidence": ["local report"],
                        "source": "local contract",
                    }
                ]
            },
        },
        "screenshot-test-state": {
            "required": "display_type_groups",
            "payload": {
                "expected_count": 8,
                "actual_count": 7,
                "diff_count": 1,
                "display_type_groups": [
                    {"label": "nested::screenshot-test-state", "status": "partial", "count": 1}
                ],
                "rack_readiness_entries": [{"label": "Rack", "status": "available"}],
                "operator_checklist": [{"label": "Inspect diff", "status": "pending"}],
            },
        },
        "risk-score": {
            "required": "signals",
            "payload": {
                "risk_score": 42,
                "risk_level": "medium",
                "current_snapshot": {"status": "available", "revision": "risk-rev-2"},
                "latest_review": {"status": "recorded", "revision": "risk-rev-1"},
                "delta_since_last_review": {"value": 3, "status": "increased"},
                "signals": [
                    {"id": "nested::risk-score", "status": "review", "detail": "visual diff"}
                ],
            },
        },
        "cross-car-comparison": {
            "required": "comparison_rows",
            "payload": {
                "comparison_axis": "risk score",
                "left_profile": "G70",
                "right_profile": "G65",
                "profiles": [{"profile_id": "G70"}, {"profile_id": "G65"}],
                "comparison_rows": [
                    {
                        "label": "nested::cross-car-comparison",
                        "status": "review",
                        "left_value": "40",
                        "right_value": "42",
                        "delta_label": "+2",
                    }
                ],
            },
        },
        "daily-digest": {
            "required": "sections",
            "payload": {
                "date": "2026-07-11",
                "scope": ["G65"],
                "sections": {
                    "what_landed_today": {
                        "heading": "nested::daily-digest",
                        "count": 1,
                        "items": [{"label": "Change", "status": "available", "detail": "landed"}],
                    }
                },
            },
        },
        "team-digest-board": {
            "required": "sections",
            "payload": {
                "profiles": ["G65", "G70"],
                "share_decision": {
                    "status": "local_only",
                    "selected_model": "nested::team-digest-board",
                    "rationale": "operator controlled",
                },
                "sections": {
                    "risk_by_profile": {
                        "heading": "Risk",
                        "items": [{"label": "G65", "status": "review", "detail": "42"}],
                    }
                },
                "board_rows": [{"label": "G65", "status": "review", "detail": "42"}],
            },
        },
        "operator-handoff": {
            "required": "handoff_items",
            "payload": {
                "handoff_count": 1,
                "latest_handoff": {
                    "summary": "nested::operator-handoff",
                    "status": "recorded",
                    "revision": "handoff-rev-1",
                },
                "handoff_items": [
                    {"label": "Stopping point", "status": "recorded", "detail": "review page"}
                ],
            },
        },
        "manual-review": {
            "required": "steps",
            "payload": {
                "steps": [
                    _step(f"review-{index}", "nested::manual-review" if index == 1 else f"Review {index}")
                    for index in range(1, 8)
                ],
                "review_assist": {"status": "available", "summary": "suggestions only"},
                "review_templates": [{"family_id": "g-series", "label": "G series"}],
                "evidence_checklist": ["Expected", "Actual", "Diff"],
                "default_family_id": "g-series",
                "family_id": "g-series",
            },
            "records_operator_verdict": True,
        },
    }
    for surface_id, case in cases.items():
        payload = case["payload"]
        assert isinstance(payload, dict)
        payload.update(
            {
                "status": f"backend::{surface_id}",
                "summary": f"primary::{surface_id}",
                "provenance": {"source": f"source::{surface_id}", "revision": f"rev::{surface_id}"},
                "read_only": True,
                "is_approval": False,
                "manual_review_required": surface_id in {"full-qa-pass", "batch-full-qa-pass", "manual-review"},
                "records_operator_verdict": bool(case.get("records_operator_verdict", False)),
            }
        )
    return cases


SURFACE_FIELD_CASES = _surface_field_cases()


def _page_for(surface_id: str) -> dict[str, object]:
    nested = deepcopy(SURFACE_FIELD_CASES[surface_id]["payload"])
    page: dict[str, object] = {
        "id": surface_id,
        "status": "top-level-status-must-not-replace-nested-status",
        "data_available": surface_id != "operator-handoff",
        "summary": "top-level summary fallback",
        "ownership_note": f"ownership::{surface_id}",
        "items": [{"label": "lossy", "detail": "must not be parsed"}],
        "actions": [{"id": "task-11-only"}],
        "payload": nested,
        "unknown_safe_field": "must-not-leak",
    }
    if surface_id not in {
        "full-qa-pass",
        "batch-full-qa-pass",
        "onboarding-guide",
        "daily-digest",
        "manual-review",
    }:
        nested["data_available"] = surface_id != "operator-handoff"
    return page


def _presenter_api():
    from sg_preflight.desktop import page_presenter

    return page_presenter


class TestQtQuickPresenters(unittest.TestCase):
    def test_field_case_inventory_matches_all_operational_descriptors(self) -> None:
        operational = {descriptor.surface_id for descriptor in SURFACE_DESCRIPTORS if descriptor.operational}

        self.assertEqual(set(SURFACE_FIELD_CASES), operational)
        self.assertEqual(len(SURFACE_FIELD_CASES), 18)

    def test_every_operational_surface_has_the_exact_contract_and_unique_structured_evidence(self) -> None:
        api = _presenter_api()
        for descriptor in SURFACE_DESCRIPTORS:
            if not descriptor.operational:
                continue
            with self.subTest(surface_id=descriptor.surface_id):
                presented = api.present_page_payload(descriptor, _page_for(descriptor.surface_id))
                rendered_items = json.dumps(presented["visibleItems"], sort_keys=True)

                self.assertEqual(set(presented), PRESENTED_KEYS)
                self.assertEqual(presented["surfaceId"], descriptor.surface_id)
                self.assertEqual(presented["rendererKind"], descriptor.renderer_kind)
                self.assertEqual((presented["title"], presented["subtitle"]), (descriptor.title, descriptor.subtitle))
                self.assertEqual(presented["status"], f"backend::{descriptor.surface_id}")
                self.assertEqual(presented["dataAvailable"], descriptor.surface_id != "operator-handoff")
                self.assertEqual(presented["primaryText"], f"primary::{descriptor.surface_id}")
                self.assertEqual(presented["visibleItemCount"], len(presented["visibleItems"]))
                self.assertGreater(presented["visibleItemCount"], 0)
                self.assertTrue(all(set(item) == VISIBLE_ITEM_KEYS for item in presented["visibleItems"]))
                self.assertIn(f"nested::{descriptor.surface_id}", rendered_items)
                self.assertEqual(presented["actions"], [])
                self.assertEqual(presented["artifacts"], [])
                self.assertEqual(presented["ownershipNote"], f"ownership::{descriptor.surface_id}")
                self.assertTrue(presented["readOnly"])
                self.assertFalse(presented["isApproval"])
                self.assertEqual(
                    presented["manualReviewRequired"],
                    descriptor.surface_id in {"full-qa-pass", "batch-full-qa-pass", "manual-review"},
                )
                self.assertEqual(presented["recordsOperatorVerdict"], descriptor.surface_id == "manual-review")
                self.assertIn(f"source::{descriptor.surface_id}", json.dumps(presented["provenance"]))
                self.assertIn(f"rev::{descriptor.surface_id}", json.dumps(presented["provenance"]))
                self.assertNotIn("must-not-leak", json.dumps(presented))

    def test_country_expected_actual_and_diff_remain_distinct(self) -> None:
        api = _presenter_api()
        presented = api.present_page_payload(
            get_surface_descriptor("country-variant-coverage"),
            _page_for("country-variant-coverage"),
        )
        country_item = next(item for item in presented["visibleItems"] if item["expected"])

        self.assertEqual(country_item["expected"], "baseline.png")
        self.assertEqual(country_item["actual"], "actual.png")
        self.assertEqual(country_item["diff"], "diff.png")

    def test_full_qa_exposes_copy_ready_evidence_as_a_bounded_section(self) -> None:
        api = _presenter_api()
        presented = api.present_page_payload(
            get_surface_descriptor("full-qa-pass"),
            _page_for("full-qa-pass"),
        )

        evidence = next(
            section for section in presented["sections"] if section["sectionId"] == "evidence-summary"
        )
        self.assertEqual(evidence["title"], "Copy-ready evidence")
        self.assertEqual(len(evidence["items"]), 1)
        self.assertIn("Profile: G45", evidence["items"][0]["value"])
        self.assertIn("Retest hash: action-001-preflight", evidence["items"][0]["value"])
        self.assertNotIn(":\\", evidence["items"][0]["value"])
        self.assertNotIn("://", evidence["items"][0]["value"])

        unsafe = _page_for("full-qa-pass")
        unsafe["payload"]["evidence_summary"] = r"Profile: G45\nProvenance: C:\private\ticket.txt"
        with self.assertRaises(api.PagePresentationError):
            api.present_page_payload(get_surface_descriptor("full-qa-pass"), unsafe)

    def test_about_maps_version_placeholder_without_retaining_it(self) -> None:
        api = _presenter_api()
        descriptor = get_surface_descriptor("about")
        presented = api.present_page_payload(
            descriptor,
            {
                "id": "about",
                "title": descriptor.title,
                "tagline": descriptor.subtitle,
                "content": {
                    "description": "nested::about",
                    "data_handling_disclosure": "Local evidence only; no telemetry.",
                    "version_placeholder": "0.2-local",
                    "provenance": {"source": "local package", "revision": "about-rev-1"},
                    "read_only": True,
                    "is_approval": False,
                    "manual_review_required": False,
                    "records_operator_verdict": False,
                },
            },
        )
        rendered = json.dumps(presented, sort_keys=True)

        self.assertEqual(set(presented), PRESENTED_KEYS)
        self.assertEqual(presented["status"], "")
        self.assertTrue(presented["dataAvailable"])
        self.assertEqual(presented["primaryText"], "nested::about")
        self.assertIn("0.2-local", rendered)
        self.assertIn("Local evidence only", rendered)
        self.assertNotIn("version_placeholder", rendered)
        self.assertEqual(presented["rendererKind"], "about")

    def test_arbitrary_backend_status_and_honest_empty_state_are_not_normalized(self) -> None:
        api = _presenter_api()
        descriptor = get_surface_descriptor("batch-full-qa-pass")
        for status in ("unknown", "missing", "not_run", "unavailable", "blocked", "incomplete", "recorded"):
            with self.subTest(status=status):
                page = _page_for(descriptor.surface_id)
                page["data_available"] = False
                page["payload"]["status"] = status
                page["payload"]["results"] = []
                presented = api.present_page_payload(descriptor, page)

                self.assertEqual(presented["status"], status)
                self.assertFalse(presented["dataAvailable"])
                self.assertEqual(presented["primaryText"], "primary::batch-full-qa-pass")
                self.assertGreater(presented["visibleItemCount"], 0)

    def test_missing_required_wrong_list_and_malformed_contracts_are_rejected(self) -> None:
        api = _presenter_api()
        for surface_id, case in SURFACE_FIELD_CASES.items():
            descriptor = get_surface_descriptor(surface_id)
            required = str(case["required"])
            with self.subTest(surface_id=surface_id, failure="missing"):
                page = _page_for(surface_id)
                del page["payload"][required]
                with self.assertRaises(api.PagePresentationError):
                    api.present_page_payload(descriptor, page)
            with self.subTest(surface_id=surface_id, failure="wrong-type"):
                page = _page_for(surface_id)
                original = page["payload"][required]
                page["payload"][required] = {} if isinstance(original, list) else []
                with self.assertRaises(api.PagePresentationError):
                    api.present_page_payload(descriptor, page)

    def test_mismatch_unknown_renderer_forbidden_fields_and_home_are_rejected_safely(self) -> None:
        api = _presenter_api()
        descriptor = get_surface_descriptor("full-qa-pass")

        mismatch = _page_for(descriptor.surface_id)
        mismatch["id"] = "risk-score"
        with self.assertRaises(api.PagePresentationError):
            api.present_page_payload(descriptor, mismatch)

        with self.assertRaises(api.PagePresentationError):
            api.present_page_payload(replace(descriptor, renderer_kind="unknown"), _page_for(descriptor.surface_id))

        for forbidden_key in ("command", "url", "svg", "session_path"):
            with self.subTest(forbidden_key=forbidden_key):
                page = _page_for(descriptor.surface_id)
                page["payload"]["steps"][0][forbidden_key] = r"C:\private\operator-secret"
                with self.assertRaises(api.PagePresentationError) as captured:
                    api.present_page_payload(descriptor, page)
                self.assertNotIn("operator-secret", str(captured.exception))

        home = SurfaceDescriptor("home", "Home", "Home shell", "Daily work", "overview", False)
        with self.assertRaises(api.PagePresentationError):
            api.present_page_payload(home, {"id": "home", "payload": {}})

    def test_real_filesystem_all_surfaces_and_about_are_presented_without_writes(self) -> None:
        from sg_preflight.dashboard import main as dashboard_main
        from sg_preflight import dashboard_preferences
        from sg_preflight.desktop.payload_adapter import adapt_page_payload
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        api = _presenter_api()

        def snapshot_files(roots: tuple[Path, ...]) -> dict[str, tuple[int, str]]:
            snapshot: dict[str, tuple[int, str]] = {}
            for root in roots:
                for path in sorted(candidate for candidate in root.rglob("*") if candidate.is_file()):
                    relative = f"{root.name}/{path.relative_to(root).as_posix()}"
                    content = path.read_bytes()
                    snapshot[relative] = (len(content), hashlib.sha256(content).hexdigest())
            return snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            isolated_root = Path(temp_dir)
            workspace = isolated_root / "workspace"
            bmw_root = isolated_root / "bmw"
            source_root = isolated_root / "source"
            environment_root = isolated_root / "environment"
            config_root = isolated_root / "config"
            process_temp_root = isolated_root / "process-temp"
            roots = (
                workspace,
                bmw_root,
                source_root,
                environment_root,
                config_root,
                process_temp_root,
            )
            for root in roots:
                root.mkdir(parents=True)
            (source_root / "Cars").mkdir()

            isolated_environment = {
                key: value
                for key, value in os.environ.items()
                if not key.upper().startswith(("SGFX_", "SG_"))
            }
            isolated_environment.update(
                {
                    "SG_SOURCE_REPO_ROOT": str(source_root),
                    "SG_REPO": str(source_root),
                    "HOME": str(environment_root),
                    "USERPROFILE": str(environment_root),
                    "APPDATA": str(config_root),
                    "LOCALAPPDATA": str(config_root),
                    "PROGRAMDATA": str(config_root),
                    "TEMP": str(process_temp_root),
                    "TMP": str(process_temp_root),
                }
            )
            before = snapshot_files(roots)

            with (
                mock.patch.dict(os.environ, isolated_environment, clear=True),
                mock.patch.object(
                    dashboard_preferences,
                    "CANONICAL_SOURCE_REPO_ROOT",
                    source_root,
                ),
            ):
                for descriptor in SURFACE_DESCRIPTORS:
                    if not descriptor.operational:
                        continue
                    with self.subTest(surface_id=descriptor.surface_id):
                        raw = dashboard_main.build_dashboard_page(
                            descriptor.surface_id,
                            "G65",
                            workspace,
                            bmw_root=bmw_root,
                            ui_mode="clean",
                            persist_dependency_state=False,
                        )
                        adapted = adapt_page_payload(raw, workspace=workspace)
                        presented = api.present_page_payload(descriptor, adapted)
                        nested = adapted.get("payload", {})
                        expected_status = (
                            nested.get("status", adapted.get("status", ""))
                            if isinstance(nested, dict)
                            else adapted.get("status", "")
                        )

                        self.assertEqual(set(presented), PRESENTED_KEYS)
                        self.assertEqual(presented["surfaceId"], descriptor.surface_id)
                        self.assertEqual(presented["rendererKind"], descriptor.renderer_kind)
                        self.assertEqual(presented["status"], str(expected_status or ""))
                        self.assertEqual(presented["visibleItemCount"], len(presented["visibleItems"]))
                        self.assertGreater(presented["visibleItemCount"], 0)
                        self.assertTrue(presented["primaryText"])
                        self.assertNotIn("placeholder", json.dumps(presented).casefold())

                about_descriptor = get_surface_descriptor("about")
                raw_about = load_dashboard_surface(
                    "about",
                    "G65",
                    workspace,
                    bmw_root=bmw_root,
                )
                presented_about = api.present_page_payload(
                    about_descriptor,
                    adapt_page_payload(raw_about, workspace=workspace),
                )
                self.assertEqual(set(presented_about), PRESENTED_KEYS)
                self.assertEqual(presented_about["surfaceId"], "about")
                self.assertEqual(presented_about["rendererKind"], "about")
                self.assertTrue(presented_about["primaryText"])
                self.assertNotIn("version_placeholder", json.dumps(presented_about))

            after = snapshot_files(roots)

        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()

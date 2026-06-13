from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.services import (
    RunRequest,
    execute_profile_run,
    load_run_record,
    preview_profile_sources,
    qa_workflow_status,
)
from tests.operator_helpers import create_temp_g65_profile, isolated_missing_external_dependencies


class TestServices(unittest.TestCase):
    def test_preview_profile_sources_detects_expected_live_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            profile = create_temp_g65_profile(Path(temp_dir))
            preview = preview_profile_sources(profile)

        self.assertIn("scene_hierarchy", preview.source_paths)
        self.assertIn("constants_expected", preview.source_paths)
        self.assertIn("constants_exported", preview.source_paths)
        self.assertIn("carpaints", preview.source_paths)

    def test_execute_profile_run_persists_run_record_and_reports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            output_root = root / "out" / "operator-test" / "g65"

            record = execute_profile_run(
                profile,
                RunRequest(
                    profile_id="G65",
                    fail_on="never",
                    output_root=output_root,
                ),
                root,
            )

            loaded = load_run_record(output_root / "run.json", root)

            self.assertEqual(record.status, "completed")
            self.assertEqual(record.summary, loaded.summary)
            self.assertTrue((output_root / "bundle" / "bundle_metadata.json").exists())
            self.assertTrue((output_root / "g65-report.json").exists())
            self.assertTrue((output_root / "g65-report.html").exists())
            self.assertTrue((output_root / "g65-report.md").exists())
            self.assertEqual(record.summary["errors"], 0)
            self.assertGreaterEqual(record.summary["warnings"], 1)

    def test_qa_workflow_status_marks_bmw_dependent_stages_as_blocked_without_access(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            with isolated_missing_external_dependencies(root):
                steps = qa_workflow_status(root, profiles=[profile])

        step_map = {step["key"]: step for step in steps}
        self.assertEqual(step_map["deterministic_preflight"]["state"], "covered")
        self.assertEqual(step_map["delivery_checklist"]["state"], "partial")
        self.assertEqual(step_map["bmw_screenshot_smoke"]["state"], "blocked")
        self.assertEqual(step_map["rack_review"]["state"], "blocked")
        self.assertIn(
            "mirrored SG delivery-checklist assets are present locally",
            step_map["delivery_checklist"]["summary"],
        )
        self.assertIn(
            "BMW Git access or a local `digital-3d-car-models` clone",
            " ".join(step_map["bmw_screenshot_smoke"]["blockers"]),
        )
        self.assertIn(
            "BMW Git access or a local `digital-3d-car-models` clone",
            " ".join(step_map["delivery_checklist"]["blockers"]),
        )
        self.assertIn("bmw_interface_screenshot_smoke", step_map)
        self.assertIn("manual_visual_review", step_map)
        self.assertIn("defect_triage", step_map)
        self.assertIn("carpaint_lackcode_dlt", step_map)
        self.assertIn("country_variant_lightfx", step_map)
        self.assertIn("performance_kpi", step_map)
        self.assertIn("jira_field_link_templates", step_map)
        self.assertEqual(step_map["manual_visual_review"]["state"], "partial")
        self.assertIn("logos", " ".join(step_map["manual_visual_review"]["workflow"]["evidence"]).lower())
        self.assertIn("G50", step_map["country_variant_lightfx"]["expectations"]["G50"]["car"])
        self.assertIn(
            "ECE",
            step_map["country_variant_lightfx"]["expectations"]["G50"]["expected_selective_yellow_country_variants"],
        )
        self.assertEqual(step_map["bmw_interface_screenshot_smoke"]["state"], "blocked")
        self.assertIn(
            "test -c <target> -ns",
            " ".join(step_map["bmw_interface_screenshot_smoke"]["adapter"]["commands"]),
        )
        self.assertEqual(step_map["jira_field_link_templates"]["state"], "partial")
        self.assertIn("APINEXT: Wombat", step_map["jira_field_link_templates"]["templates"]["asset_update_ready"]["team"])


if __name__ == "__main__":
    unittest.main()

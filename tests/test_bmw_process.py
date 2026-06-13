from __future__ import annotations

import unittest

from sg_preflight.bmw_process import (
    bmw_interface_smoke_commands,
    country_variant_lightfx_expectations,
    jira_field_link_templates,
    normalize_lackcode,
    workflow_contracts,
)


class TestBmwProcess(unittest.TestCase):
    def test_normalize_lackcode_matches_bmw_dlt_lookup_rule(self) -> None:
        self.assertEqual(normalize_lackcode("0C5A"), "C5A")
        self.assertEqual(normalize_lackcode(" 00r46 "), "R46")
        self.assertEqual(normalize_lackcode("0000"), "0")
        self.assertEqual(normalize_lackcode(""), "")

    def test_bmw_interface_smoke_commands_include_interface_and_screenshot_steps(self) -> None:
        commands = bmw_interface_smoke_commands("G70_EVO")

        self.assertIn("python ci/scripts/car_manager.py test -c G70_EVO -ns", commands)
        self.assertIn("python ci/scripts/car_manager.py export G70_EVO", commands)
        self.assertIn("python ci/scripts/car_manager.py screenshots --diff G70_EVO", commands)

    def test_jira_templates_capture_bmw_delivery_fields_and_links(self) -> None:
        templates = jira_field_link_templates()

        defect = templates["sgfx_defect"]
        self.assertEqual(defect["team"], "APINEXT: Seriesgraphics")
        self.assertEqual(defect["component"], "UI Toolkit: Seriesgraphics")
        self.assertEqual(defect["variant3"], "TK_Seriesgraphics")

        asset_ready = templates["asset_update_ready"]
        self.assertEqual(asset_ready["team"], "APINEXT: Wombat")
        self.assertIn("3DCarAssetIntegration", asset_ready["labels"])
        self.assertEqual(asset_ready["variant3"], "TK_3D_Car")
        self.assertIn("blocked by", asset_ready["link_types"])

    def test_workflow_contracts_cover_current_bmw_process_lanes(self) -> None:
        contracts = {item["key"]: item for item in workflow_contracts()}

        self.assertIn("manual_visual_review", contracts)
        self.assertIn("bmw_interface_screenshot_smoke", contracts)
        self.assertIn("defect_triage", contracts)
        self.assertIn("carpaint_lackcode_dlt", contracts)
        self.assertIn("country_variant_lightfx", contracts)
        self.assertIn("performance_kpi", contracts)
        self.assertIn("jira_field_link_templates", contracts)
        self.assertIn("Selective Yellow", " ".join(contracts["manual_visual_review"]["steps"]))
        self.assertIn("Lackcode", " ".join(contracts["carpaint_lackcode_dlt"]["evidence"]))

    def test_country_variant_lightfx_expectations_capture_g50_selective_yellow_issue(self) -> None:
        expectation = country_variant_lightfx_expectations("G50")

        self.assertEqual(expectation["car"], "G50")
        self.assertEqual(expectation["expected_selective_yellow_country_variants"], ("ECE", "US"))
        self.assertIn("CN-only", expectation["known_bad_signal"])


if __name__ == "__main__":
    unittest.main()

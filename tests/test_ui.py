from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from sg_preflight.ui import create_app
from tests.operator_helpers import create_temp_g65_profile


class TestOperatorUI(unittest.TestCase):
    def test_home_and_run_pages_render_profile_information(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            client = TestClient(create_app(root=root, profiles=[profile]))

            home = client.get("/ui")
            run_view = client.get("/ui/profiles/G65")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Live Profiles", home.text)
        self.assertIn("BMW G65 test slice", home.text)
        self.assertEqual(run_view.status_code, 200)
        self.assertIn("Resolved Inputs", run_view.text)
        self.assertIn("Launch Run", run_view.text)

    def test_run_result_and_evidence_pages_render_grouped_findings_and_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            (profile.repo_root / "Cars_IDCevo" / "BMW" / "G70").mkdir(parents=True, exist_ok=True)
            main_rca = profile.project_root / "main.rca"
            main_rca.write_text(
                main_rca.read_text(encoding="utf-8")
                + "shared=/../../G70/_Common/interfaces/Link_Common_Variants.lua\n",
                encoding="utf-8",
            )
            (profile.project_root / "logic" / "unused_debug.lua").write_text(
                "-- intentionally unused\n",
                encoding="utf-8",
            )
            client = TestClient(create_app(root=root, profiles=[profile]))

            create_response = client.post(
                "/ui/api/runs",
                json={
                    "profile_id": "G65",
                    "packs": ["anchors", "constants", "carpaints", "project_sanity"],
                    "fail_on": "never",
                    "context": profile.default_context,
                },
            )
            self.assertEqual(create_response.status_code, 202)
            payload = create_response.json()

            result_page = client.get(payload["result_url"])
            evidence_page = client.get(payload["result_url"] + "/evidence")

        self.assertEqual(result_page.status_code, 200)
        self.assertIn("Grouped Findings", result_page.text)
        self.assertIn("TA / pipeline / integration owner", result_page.text)
        self.assertIn("Confirm whether the Lua file is intentionally unused", result_page.text)
        self.assertIn("Source file", result_page.text)
        self.assertIn("Lua source", result_page.text)
        self.assertEqual(evidence_page.status_code, 200)
        self.assertIn("JSON report", evidence_page.text)
        self.assertIn("Project manifest", evidence_page.text)


if __name__ == "__main__":
    unittest.main()

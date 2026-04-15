from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from sg_preflight.profiles import RunProfile
from sg_preflight.ui import create_app
from tests.operator_helpers import create_temp_g65_profile


class TestOperatorUI(unittest.TestCase):
    def test_home_and_run_pages_render_profile_information(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            with mock.patch.dict(
                os.environ,
                {"SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models")},
                clear=False,
            ):
                with mock.patch("sg_preflight.services.shutil.which", return_value=None):
                    client = TestClient(create_app(root=root, profiles=[profile]))

                    home = client.get("/ui")
                    run_view = client.get("/ui/profiles/G65")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Start With A Car", home.text)
        self.assertIn("Common QA Tasks", home.text)
        self.assertIn("BMW G65 test slice", home.text)
        self.assertIn("Current QA Workflow Fit", home.text)
        self.assertIn("BMW screenshot / export / interface smoke", home.text)
        self.assertIn("blocked", home.text)
        self.assertEqual(run_view.status_code, 200)
        self.assertIn("Resolved Source Inputs", run_view.text)
        self.assertIn("Standard Check", run_view.text)
        self.assertIn("Run Standard Check", run_view.text)

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
        self.assertIn("Do This Next", result_page.text)
        self.assertIn("Copy Quick Update", result_page.text)
        self.assertIn("Copy Finding", result_page.text)
        self.assertIn("Grouped Findings", result_page.text)
        self.assertIn("TA / pipeline / integration owner", result_page.text)
        self.assertIn("Confirm whether the Lua file is intentionally unused", result_page.text)
        self.assertIn("Source file", result_page.text)
        self.assertIn("Lua source", result_page.text)
        self.assertEqual(evidence_page.status_code, 200)
        self.assertIn("JSON report", evidence_page.text)
        self.assertIn("Project manifest", evidence_page.text)

    def test_deep_audit_route_persists_and_renders_playground_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mirror_root = root / "repositories" / "trunk"
            reference_root = root / "reference" / "trunk"

            (mirror_root / "Cars_IDCevo" / "BMW" / "G65").mkdir(parents=True, exist_ok=True)
            (reference_root / "Cars_IDCevo" / "BMW" / "G65").mkdir(parents=True, exist_ok=True)
            (mirror_root / "Cars" / "BMW").mkdir(parents=True, exist_ok=True)
            (reference_root / "Cars" / "BMW").mkdir(parents=True, exist_ok=True)
            (reference_root / "Playground" / "RaCoSceneMerging_PoC").mkdir(parents=True, exist_ok=True)

            (mirror_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca").write_text("same\n", encoding="utf-8")
            (reference_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca").write_text("same\n", encoding="utf-8")
            (mirror_root / "Cars" / "BMW" / "CarPaint.json").write_text("{ }\n", encoding="utf-8")
            (reference_root / "Cars" / "BMW" / "CarPaint.json").write_text("{ }\n", encoding="utf-8")
            (
                reference_root / "Playground" / "RaCoSceneMerging_PoC" / "only-on-reference.txt"
            ).write_text("drift\n", encoding="utf-8")

            profile = RunProfile(
                profile_id="G65",
                label="BMW G65 test slice",
                repo_root=mirror_root,
                project_root=mirror_root / "Cars_IDCevo" / "BMW" / "G65",
                config_path=root / "config" / "sg_rules_live_g65.json",
                mirror_audit_targets=("Cars_IDCevo/BMW/G65", "Cars/BMW/CarPaint.json"),
                reference_repo_root=reference_root,
            )

            client = TestClient(create_app(root=root, profiles=[profile]))

            response = client.get("/ui/audits/mirror/deep", follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            home = client.get("/ui")

        self.assertEqual(home.status_code, 200)
        self.assertIn("Refresh Deep Mirror Audit", home.text)
        self.assertIn("Show Audit Detail", home.text)
        self.assertIn("Playground/RaCoSceneMerging_PoC", home.text)


if __name__ == "__main__":
    unittest.main()

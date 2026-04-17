from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from sg_preflight.profiles import get_run_profile
from sg_preflight.ui import create_app


ROOT = Path(__file__).resolve().parents[1]
MIRROR_ROOT = ROOT / "repositories" / "trunk"


@unittest.skipUnless(MIRROR_ROOT.exists(), "Live SG mirror is required for acceptance coverage")
class TestRunProfileAcceptance(unittest.TestCase):
    def test_run_profile_cli_surfaces_current_live_baseline_signals(self) -> None:
        expected_codes = {
            "G70": {"carpaints.duplicate_unique_value", "project_sanity.cross_car_reference"},
            "G65": {"constants.out_of_tolerance"},
            "G45": {"project_sanity.raco_version_not_recommended"},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for profile_id, codes in expected_codes.items():
                output_root = temp_root / profile_id.lower()
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "sg_preflight",
                        "run-profile",
                        profile_id,
                        "--output-root",
                        str(output_root),
                        "--fail-on",
                        "never",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
                report = json.loads((output_root / f"{profile_id.lower()}-report.json").read_text(encoding="utf-8"))
                found_codes = {
                    finding["code"]
                    for pack in report["packs"]
                    for finding in pack["findings"]
                }
                self.assertTrue(codes.issubset(found_codes), msg=f"{profile_id}: {sorted(found_codes)}")

    def test_ui_flow_can_launch_and_render_real_live_profiles(self) -> None:
        expected_codes = {
            "G70": "project_sanity.cross_car_reference",
            "G65": "constants.out_of_tolerance",
            "G45": "project_sanity.raco_version_not_recommended",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            for profile_id, expected_code in expected_codes.items():
                profile = get_run_profile(profile_id, ROOT)
                client = TestClient(create_app(root=temp_root / profile_id.lower(), profiles=[profile]))

                response = client.post(
                    "/ui/api/runs",
                    json={
                        "profile_id": profile_id,
                        "packs": ["anchors", "constants", "carpaints", "project_sanity"],
                        "fail_on": "never",
                        "context": profile.default_context,
                    },
                )
                self.assertEqual(response.status_code, 202)
                payload = response.json()
                result_page = client.get(payload["result_url"])
                evidence_page = client.get(payload["result_url"] + "/evidence")

                self.assertEqual(result_page.status_code, 200)
                self.assertIn("Show all grouped problems", result_page.text)
                self.assertIn("Copy quick update", result_page.text)
                self.assertIn(expected_code, result_page.text)
                self.assertEqual(evidence_page.status_code, 200)
                self.assertIn("Project manifest", evidence_page.text)
                self.assertIn("JSON report", evidence_page.text)


if __name__ == "__main__":
    unittest.main()

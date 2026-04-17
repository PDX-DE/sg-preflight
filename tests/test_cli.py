from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestCLI(unittest.TestCase):
    def test_list_profiles_includes_live_registry(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-profiles", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        profile_ids = {item["profile_id"] for item in payload}
        self.assertTrue({"G70", "G65", "G45"}.issubset(profile_ids))

    def test_list_actions_includes_operator_registry(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-actions", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        action_ids = {item["action_id"] for item in payload}
        self.assertIn("daily_live_matrix", action_ids)
        self.assertIn("repo_checker_idcevo", action_ids)
        self.assertIn("qa_stack__g65", action_ids)
        self.assertIn("unused_resources__g65", action_ids)
        self.assertIn("delivery_checklist__g65", action_ids)
        self.assertIn("bmw_screenshot_smoke__g65", action_ids)

    def test_good_demo_passes(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "demo-good"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        report_path = ROOT / "out" / "demo-good.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["summary"]["errors"], 0)

    def test_broken_demo_fails(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "demo-broken"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2, msg=result.stdout + "\n" + result.stderr)
        report_path = ROOT / "out" / "demo-broken.json"
        self.assertTrue(report_path.exists())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertGreater(report["summary"]["errors"], 0)


if __name__ == "__main__":
    unittest.main()

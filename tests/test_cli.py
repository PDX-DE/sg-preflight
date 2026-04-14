from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestCLI(unittest.TestCase):
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

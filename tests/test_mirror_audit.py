from __future__ import annotations

import tempfile
from pathlib import Path
import unittest

from sg_preflight.mirror_audit import run_deep_mirror_audit, run_fast_mirror_audit
from sg_preflight.profiles import RunProfile


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestMirrorAudit(unittest.TestCase):
    def test_fast_mirror_audit_reports_matching_live_targets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mirror_root = root / "mirror" / "trunk"
            reference_root = root / "reference" / "trunk"

            _write_text(mirror_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca", "same\n")
            _write_text(reference_root / "Cars_IDCevo" / "BMW" / "G65" / "main.rca", "same\n")
            _write_text(mirror_root / "Cars" / "BMW" / "CarPaint.json", "{ }\n")
            _write_text(reference_root / "Cars" / "BMW" / "CarPaint.json", "{ }\n")

            profile = RunProfile(
                profile_id="G65",
                label="BMW G65 test slice",
                repo_root=mirror_root,
                project_root=mirror_root / "Cars_IDCevo" / "BMW" / "G65",
                config_path=root / "config.json",
                mirror_audit_targets=("Cars_IDCevo/BMW/G65", "Cars/BMW/CarPaint.json"),
                reference_repo_root=reference_root,
            )

            report = run_fast_mirror_audit([profile])

            self.assertEqual(report.status, "match")
            self.assertEqual(len(report.entries), 2)
            self.assertTrue(all(entry.status == "match" for entry in report.entries))

    def test_deep_mirror_audit_flags_playground_only_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            mirror_root = root / "mirror" / "trunk"
            reference_root = root / "reference" / "trunk"

            _write_text(mirror_root / "Cars_IDCevo" / "BMW" / "G70" / "main.rca", "same\n")
            _write_text(reference_root / "Cars_IDCevo" / "BMW" / "G70" / "main.rca", "same\n")
            _write_text(
                reference_root / "Playground" / "RaCoSceneMerging_PoC" / "only-on-reference.txt",
                "machine-only drift\n",
            )

            report = run_deep_mirror_audit(mirror_root, reference_root)

            self.assertEqual(report.status, "drift")
            self.assertEqual(len(report.entries), 1)
            self.assertTrue(
                any("Playground/RaCoSceneMerging_PoC" in note for note in report.notes),
                msg=report.notes,
            )
            self.assertTrue(
                any(
                    "playground/racoscenemerging_poc/" in item.lower()
                    for item in report.entries[0].sample_differences
                ),
                msg=report.entries[0].sample_differences,
            )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

from sg_preflight.bmw_pipeline_auto_fix import run_missing_actual_diagnostic_chain
from sg_preflight.cli import main


class TestBmwPipelineAutoFix(unittest.TestCase):
    def _write_bmp(self, path: Path, color: tuple[int, int, int] = (204, 51, 204)) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        width = 4
        height = 4
        row_pad = (4 - (width * 3) % 4) % 4
        row_size = width * 3 + row_pad
        pixel_size = row_size * height
        file_size = 14 + 40 + pixel_size
        with path.open("wb") as handle:
            handle.write(b"BM")
            handle.write(struct.pack("<IHHI", file_size, 0, 0, 54))
            handle.write(struct.pack("<IIIHHIIIIII", 40, width, height, 1, 24, 0, pixel_size, 2835, 2835, 0, 0))
            bgr = bytes((color[2], color[1], color[0]))
            row = bgr * width + (b"\x00" * row_pad)
            for _ in range(height):
                handle.write(row)

    def _fixture(self, root: Path, *, config_text: str = "return { tests = { 'highlighting' } }\n") -> tuple[Path, Path, Path]:
        project_root = root / "Cars_IDCevo" / "BMW" / "G70"
        expected_root = project_root / "export" / "tests" / "expected"
        actual_root = root / "empty_actuals"
        actual_root.mkdir(parents=True, exist_ok=True)
        self._write_bmp(expected_root / "highlighting.bmp")
        config_path = project_root / "export" / "tests" / "test_config.lua"
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(config_text, encoding="utf-8")
        return project_root, expected_root, actual_root

    def test_missing_actual_chain_requires_read_refresh_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root, expected_root, actual_root = self._fixture(root)

            payload = run_missing_actual_diagnostic_chain(
                profile_id="G70",
                workspace=root,
                project_root=project_root,
                expected_root=expected_root,
                candidate_roots=(actual_root,),
                output_root=root / "out",
            )

            self.assertEqual(payload["status"], "confirmation_pending")
            self.assertTrue(payload["operator_confirmation_required"])
            self.assertEqual(payload["missing_actual_count"], 1)
            self.assertEqual(payload["missing_actuals"][0]["diagnostic_chain_status"], "incomplete")
            steps = {step["id"]: step["status"] for step in payload["steps"]}
            self.assertEqual(steps["read-refresh"], "confirmation_pending")
            self.assertEqual(steps["retry-capture"], "not_run")
            self.assertIn("Manual review", json.dumps(payload))

    def test_asset_doctor_reports_missing_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root, expected_root, actual_root = self._fixture(
                root,
                config_text="return { tests = { 'highlighting' }, assets = { 'textures/missing.png' } }\n",
            )

            payload = run_missing_actual_diagnostic_chain(
                profile_id="G70",
                workspace=root,
                project_root=project_root,
                expected_root=expected_root,
                candidate_roots=(actual_root,),
                output_root=root / "out",
            )

            asset_step = next(step for step in payload["steps"] if step["id"] == "asset-doctor")
            asset_payload = asset_step["payload"]
            self.assertEqual(asset_step["status"], "incomplete")
            self.assertEqual(asset_payload["missing_references"][0]["reference"], "textures/missing.png")

    def test_read_refresh_runner_executes_only_after_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root, expected_root, actual_root = self._fixture(root)
            bmw_root = root / "digital-3d-car-models"
            (bmw_root / ".git").mkdir(parents=True)
            (root / ".svn").mkdir()
            commands: list[list[str]] = []

            def runner(command: list[str], cwd: Path, timeout_seconds: int) -> subprocess.CompletedProcess[str]:
                commands.append(command)
                return subprocess.CompletedProcess(command, 0, stdout=f"ok:{cwd.name}", stderr="")

            payload = run_missing_actual_diagnostic_chain(
                profile_id="G70",
                workspace=root,
                bmw_root=bmw_root,
                project_root=project_root,
                expected_root=expected_root,
                candidate_roots=(actual_root,),
                output_root=root / "out",
                operator_confirmed_read_refresh=True,
                command_runner=runner,
            )

            read_refresh = next(step for step in payload["steps"] if step["id"] == "read-refresh")
            self.assertEqual(read_refresh["status"], "available")
            self.assertEqual(len(commands), 2)
            self.assertEqual(commands[0][:2], ["git", "-C"])
            self.assertEqual(commands[1][:2], ["svn", "update"])
            self.assertFalse(payload["operator_confirmation_required"])

    def test_cli_missing_actuals_outputs_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root, expected_root, actual_root = self._fixture(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "bmw-pipeline-diagnostics",
                        "missing-actuals",
                        "--project-root",
                        str(project_root),
                        "--expected-root",
                        str(expected_root),
                        "--candidate-root",
                        str(actual_root),
                        "--output-root",
                        str(root / "out"),
                        "--json",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["profile_id"], "G70")
            self.assertEqual(payload["action_id"], "missing-actual-diagnostic-chain")
            self.assertEqual(payload["missing_actual_count"], 1)
            self.assertTrue(payload["operator_confirmation_required"])


if __name__ == "__main__":
    unittest.main()

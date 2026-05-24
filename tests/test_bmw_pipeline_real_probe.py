from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "scripts" / "walkthrough_harness" / "probe_bmw_pipeline_real.py"


def _load_probe_module():
    spec = importlib.util.spec_from_file_location("probe_bmw_pipeline_real", PROBE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load probe_bmw_pipeline_real.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestBmwPipelineRealProbe(unittest.TestCase):
    def test_probe_is_env_gated_and_writes_skipped_summary(self) -> None:
        probe = _load_probe_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out" / "g7"

            payload = probe.run_probe_suite(
                workspace=root,
                output_root=output_root,
                env={},
            )

            self.assertEqual(payload["status"], "skipped")
            self.assertFalse(payload["gate_enabled"])
            self.assertFalse(payload["is_approval"])
            summary = output_root / "probe-summary.json"
            self.assertTrue(summary.is_file())
            written = json.loads(summary.read_text(encoding="utf-8"))
            self.assertEqual(written["status"], "skipped")
            self.assertIn("SGFX_REAL_BMW_PIPELINE_AVAILABLE", written["summary"])

    def test_probe_runs_both_actions_and_records_per_lane_evidence_with_mocks(self) -> None:
        probe = _load_probe_module()

        def fake_check(*, profile_id, workspace, bmw_root=None):
            lane = "idc_evo" if profile_id == "G65" else "idc_23"
            return {
                "profile_id": profile_id,
                "workspace": str(Path(workspace)),
                "bmw_root": str(bmw_root or ""),
                "lane": lane,
                "status": "available",
                "can_run": True,
                "checks": [],
                "disabled_reason": "",
            }

        def fake_start(*, profile_id, workspace, operator_confirmed, bmw_root=None, timeout_seconds=900):
            self.assertTrue(operator_confirmed)
            return SimpleNamespace(profile_id=profile_id, workspace=Path(workspace), bmw_root=bmw_root)

        def fake_poll(job):
            stdout = Path(job.workspace) / "operator_state" / f"{job.profile_id}.stdout.log"
            stderr = Path(job.workspace) / "operator_state" / f"{job.profile_id}.stderr.log"
            stdout.parent.mkdir(parents=True, exist_ok=True)
            stdout.write_text("stdout fixture\n", encoding="utf-8")
            stderr.write_text("stderr fixture\n", encoding="utf-8")
            return {
                "profile_id": job.profile_id,
                "status": "available",
                "completed": True,
                "exit_code": 0,
                "command": ["python", "bmw-script.py", job.profile_id],
                "summary": "fixture completed",
                "stdout_path": str(stdout),
                "stderr_path": str(stderr),
                "recorded_by_tool": True,
                "is_approval": False,
            }

        fake_spec = probe.ActionSpec(check=fake_check, start=fake_start, poll=fake_poll)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output_root = root / "out" / "g7"
            with mock.patch.dict(
                probe.ACTION_SPECS,
                {"delivery_export": fake_spec, "screenshot_capture": fake_spec},
                clear=True,
            ):
                payload = probe.run_probe_suite(
                    workspace=root,
                    output_root=output_root,
                    profiles=("G65", "F70"),
                    env={"SGFX_REAL_BMW_PIPELINE_AVAILABLE": "1"},
                    poll_interval_seconds=0,
                )

                self.assertEqual(payload["status"], "passed")
                self.assertTrue(payload["gate_enabled"])
                self.assertEqual(len(payload["results"]), 4)
                self.assertTrue(payload["lane_coverage"]["idc_evo"]["real_subprocess_evidence_recorded"])
                self.assertTrue(payload["lane_coverage"]["idc_23"]["real_subprocess_evidence_recorded"])
                self.assertTrue(payload["profile_coverage"]["G65"]["all_actions_invoked"])
                self.assertTrue(payload["profile_coverage"]["F70"]["all_actions_invoked"])
                self.assertTrue(all(result["real_subprocess_invoked"] for result in payload["results"]))
                self.assertTrue(all(result["is_approval"] is False for result in payload["results"]))
                self.assertTrue((output_root / "probe-summary.json").is_file())
                self.assertTrue((output_root / "profiles" / "g65" / "delivery-export.json").is_file())
                self.assertTrue((output_root / "logs" / "g65-delivery-export.stdout.log").is_file())

    def test_reviewer_template_requires_real_subprocess_evidence(self) -> None:
        template = (ROOT / "scripts" / "walkthrough_harness" / "reviewer_sweep_template.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("probe_bmw_pipeline_real.py", template)
        self.assertIn("SGFX_REAL_BMW_PIPELINE_AVAILABLE=1", template)
        self.assertIn("probe-summary.json", template)
        self.assertIn("minimum_profile_set_real_subprocess_evidence_recorded: true", template)
        self.assertIn("lane_coverage.idc_evo.real_subprocess_evidence_recorded: true", template)
        self.assertIn("lane_coverage.idc_23.real_subprocess_evidence_recorded: true", template)
        self.assertIn("profile_coverage", template)
        self.assertIn("is_approval: false", template)


if __name__ == "__main__":
    unittest.main()

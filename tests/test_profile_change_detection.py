from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sg_preflight.full_qa_history import record_full_qa_run_history
from sg_preflight.profile_change_detection import detect_changed_profiles_since_last_run
from sg_preflight.profiles import RunProfile


class ProfileChangeDetectionTests(unittest.TestCase):
    def _profile(self, workspace: Path, *, bmw_profile_id: str = "F70_EVO") -> RunProfile:
        return RunProfile(
            profile_id="F70",
            label="BMW F70 test profile",
            repo_root=workspace,
            project_root=workspace / "Cars_IDCevo" / "BMW" / "F70",
            project_relative=Path("Cars_IDCevo") / "BMW" / "F70",
            config_path=workspace / "config" / "sg_rules_live.json",
            reference_repo_root=workspace,
            bmw_profile_id=bmw_profile_id,
            brand="BMW",
        )

    def test_detect_changed_profile_after_last_successful_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "svn"
            bmw_root = root / "bmw"
            svn_profile = workspace / "Cars_IDCevo" / "BMW" / "F70"
            bmw_profile = bmw_root / "cars" / "BMW" / "F70_EVO"
            svn_profile.mkdir(parents=True)
            bmw_profile.mkdir(parents=True)
            svn_config = svn_profile / "test_config.lua"
            bmw_config = bmw_profile / "model.yaml"
            svn_config.write_text("return {}", encoding="utf-8")
            bmw_config.write_text("profile: F70", encoding="utf-8")
            old = datetime(2026, 5, 27, 10, 0, tzinfo=timezone.utc).timestamp()
            new = datetime(2026, 5, 28, 10, 0, tzinfo=timezone.utc).timestamp()
            os.utime(svn_config, (new, new))
            os.utime(bmw_config, (old, old))
            with mock.patch.dict(os.environ, {"SGFX_FULL_QA_HISTORY_ROOT": str(root / "history")}):
                record_full_qa_run_history(
                    "F70",
                    {"status": "recorded", "summary": "done", "steps": [{"status": "passed"}]},
                    completed_at_utc="2026-05-27T12:00:00Z",
                )

                payload = detect_changed_profiles_since_last_run(
                    workspace=workspace,
                    bmw_root=bmw_root,
                    profiles=[self._profile(workspace)],
                )

            self.assertEqual(payload["status"], "available")
            self.assertEqual(payload["changed_profile_ids"], ["F70"])
            self.assertEqual(payload["changed_profiles"][0]["status"], "changed")
            self.assertTrue(payload["changed_profiles"][0]["changed_since_last_run"])
            self.assertEqual(
                Path(payload["changed_profiles"][0]["newest_config_path"]).resolve(),
                svn_config.resolve(),
            )
            self.assertFalse(payload["changed_profiles"][0]["is_approval"])

    def test_missing_sources_report_unavailable_without_needs_qa_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "svn"
            bmw_root = root / "bmw"

            payload = detect_changed_profiles_since_last_run(
                workspace=workspace,
                bmw_root=bmw_root,
                profiles=[self._profile(workspace)],
            )

            self.assertEqual(payload["status"], "unavailable")
            self.assertIn("Change-detection unavailable; refresh manually.", payload["summary"])
            self.assertNotIn("needs" + " qa", payload["summary"].casefold())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from contextlib import redirect_stdout

from fastapi.testclient import TestClient

from sg_preflight.cli import main
from sg_preflight.setup_doctor import build_setup_doctor_report
from sg_preflight.ui import create_app


def _write_stub(path: Path, text: str = "stub") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _healthy_subprocess(cmd, *args, **kwargs):
    # Models a fully-provisioned environment: RaCo reports its pinned version, git case
    # sensitivity is set (core.ignorecase false), and the pipeline Python is 3.12+.
    parts = [str(part) for part in (cmd if isinstance(cmd, (list, tuple)) else [cmd])]
    joined = " ".join(parts)
    if "core.ignorecase" in joined:
        return mock.Mock(stdout="false\n", stderr="", returncode=0)
    first = parts[0].casefold() if parts else ""
    if first.endswith("python.exe") or first.endswith("python"):
        return mock.Mock(stdout="Python 3.13.0\n", stderr="", returncode=0)
    return mock.Mock(stdout="RaCo Headless 2.9.0\n", stderr="", returncode=0)


def _bmw_ci_python_path(repo_root: Path) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    executable = "python.exe" if os.name == "nt" else "python"
    return repo_root / ".venv_bmw_ci" / scripts_dir / executable


def _doctor_fixture(root: Path) -> dict[str, str]:
    repo_root = root / "repositories" / "trunk"
    bmw_repo = root / "digital-3d-car-models"
    idc23 = root / "worktrees" / "assets-idc23"
    raco_headless = root / "external" / "ramses" / "bin" / "RelWithDebInfo" / "RaCoHeadless.exe"
    raco_gui = root / "external" / "ramses" / "bin" / "RelWithDebInfo" / "RamsesComposer.exe"
    blender = root / "external" / "blender" / "blender.exe"

    _write_stub(raco_headless)
    _write_stub(raco_gui)
    _write_stub(blender)
    _write_stub(bmw_repo / "ci" / "scripts" / "common" / "models_build_config.yaml", "models: []\n")
    _write_stub(_bmw_ci_python_path(bmw_repo))
    _write_stub(root / "dist" / "sgfx-preflight" / "_internal" / "PySide6" / "Qt6WebEngineCore.dll")
    _write_stub(root / "cpp" / "build" / "vs2022-ramses-28.16" / "Release" / "ramses-shared-lib-headless.dll")
    repo_root.mkdir(parents=True, exist_ok=True)
    idc23.mkdir(parents=True, exist_ok=True)

    return {
        "SG_SOURCE_REPO_ROOT": str(repo_root),
        "SG_RACO_HEADLESS": str(raco_headless),
        "SG_RACO_GUI": str(raco_gui),
        "SG_BLENDER_EXE": str(blender),
        "Digital-3D-Car-Repo": str(bmw_repo),
        "Digital-3D-Car-Repo-IDC23": str(idc23),
    }


class TestSetupDoctor(unittest.TestCase):
    def setUp(self) -> None:
        # Pin the display-resolution advisory to a healthy value so the real host's monitor size
        # cannot leak into these deterministic report assertions.
        patcher = mock.patch(
            "sg_preflight.setup_doctor._virtual_screen_size", return_value=(3840, 2160))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_report_uses_real_paths_and_does_not_require_optional_jira_pat(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)
            _write_stub(
                Path(env["Digital-3D-Car-Repo"]) / "ci" / "scripts" / "common" / "interface_versions.yaml",
                "12:\n  raco_version: 2.3.0\n23:\n  raco_version: 2.9.0\n24:\n  raco_version: 2.9.0\n",
            )

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run",
                                    side_effect=_healthy_subprocess):
                        report = build_setup_doctor_report(root).to_dict()

        self.assertTrue(report["ready"])
        self.assertEqual(report["required_missing_count"], 0)
        self.assertEqual(report["optional_missing_count"], 1)
        self.assertEqual(report["status"], "ready")
        self.assertEqual(report["mode"], "detect_and_validate")
        self.assertEqual(report["version_validation"]["drift"], 0)
        self.assertGreaterEqual(report["version_validation"]["ok"], 3)
        self.assertGreaterEqual(report["version_validation"]["not_pinned"], 1)
        self.assertEqual(report["next_action"]["status"], "optional")
        self.assertEqual(report["next_action"]["item_key"], "jira_pat")
        self.assertTrue(report["shell_signal"]["ready"])
        self.assertEqual(
            [step["key"] for step in report["wizard_steps"]],
            ["runtime", "pipeline_tools", "bmw_worktrees", "connected_extras"],
        )
        items = {item["key"]: item for item in report["items"]}
        self.assertEqual(items["raco_headless"]["status"], "found")
        self.assertEqual(items["raco_headless"]["recommended_version"], "2.3.0, 2.9.0")
        self.assertEqual(items["raco_headless"]["version_status"], "ok")
        self.assertIn("IDCevo", items["raco_headless"]["version_check_detail"])
        self.assertEqual(items["bmw_git_worktree"]["status"], "found")
        self.assertEqual(items["idc23_worktree"]["status"], "found")
        self.assertEqual(items["bmw_ci_python_deps"]["status"], "found")
        self.assertEqual(items["qt_webengine_core"]["status"], "found")
        self.assertEqual(items["python_runtime"]["recommended_version"], ">=3.10")
        self.assertEqual(items["python_runtime"]["version_status"], "ok")
        self.assertEqual(items["ramses_sdk_runtime"]["recommended_version"], "28.16")
        self.assertIn("pipeline", items["ramses_sdk_runtime"]["version_check_detail"].casefold())
        self.assertEqual(items["blender"]["version_status"], "not_pinned")
        self.assertIn("no pinned", items["blender"]["version_check_detail"].casefold())
        self.assertEqual(items["jira_pat"]["status"], "optional_missing")
        self.assertIn("OS keychain", items["jira_pat"]["fix"])
        self.assertIn(
            "sgfx-preflight.exe integration jira register --confirm-local-write",
            items["jira_pat"]["fix"],
        )

    def test_raco_drift_is_guidance_not_verdict_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="RaCo Headless 2.5.0\n", stderr="", returncode=0)
                        report = build_setup_doctor_report(root).to_dict()

        items = {item["key"]: item for item in report["items"]}
        detail = items["raco_headless"]["version_check_detail"]
        self.assertEqual(items["raco_headless"]["version_status"], "drift")
        self.assertEqual(report["version_validation"]["drift"], 1)
        self.assertIn("2.3.0", detail)
        self.assertIn("2.9.0", detail)
        self.assertNotIn("wrong", detail.casefold())
        self.assertNotIn("invalid", detail.casefold())
        self.assertNotIn("must", detail.casefold())

    def test_report_marks_bmw_ci_python_deps_missing_until_probe_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)
            bmw_ci_python = _bmw_ci_python_path(Path(env["Digital-3D-Car-Repo"]))
            bmw_ci_python.unlink()

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="RaCo Headless 2.9.0\n", stderr="", returncode=0)
                        missing_report = build_setup_doctor_report(root).to_dict()
                        _write_stub(bmw_ci_python)
                        found_report = build_setup_doctor_report(root).to_dict()

        missing_items = {item["key"]: item for item in missing_report["items"]}
        missing_steps = {step["key"]: step for step in missing_report["wizard_steps"]}
        found_items = {item["key"]: item for item in found_report["items"]}
        self.assertEqual(missing_items["bmw_ci_python_deps"]["status"], "missing")
        self.assertEqual(missing_steps["bmw_worktrees"]["status"], "missing")
        self.assertEqual(found_items["bmw_ci_python_deps"]["status"], "found")

    def test_report_marks_first_required_blocker_as_next_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            with mock.patch.dict(os.environ, {}, clear=True):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.shutil.which", return_value=None):
                        with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                            run.return_value = mock.Mock(stdout="", stderr="", returncode=1)
                            report = build_setup_doctor_report(root).to_dict()

        self.assertFalse(report["ready"])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["next_action"]["status"], "blocked")
        self.assertEqual(report["next_action"]["item_key"], "raco_headless")
        self.assertTrue(report["next_action"]["blocking"])
        self.assertFalse(report["shell_signal"]["ready"])
        self.assertIn("RaCoHeadless", report["shell_signal"]["blocking_labels"])
        blocked_steps = [step for step in report["wizard_steps"] if step["status"] == "missing"]
        self.assertTrue(blocked_steps)

    def test_cli_doctor_outputs_json_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)
            stdout = io.StringIO()

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="Blender 4.5.8\n", stderr="", returncode=0)
                        with redirect_stdout(stdout):
                            result = main(["doctor", "--workspace", str(root), "--json"])

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["schema_version"], 1)
        self.assertTrue(payload["ready"])
        self.assertIn("version_validation", payload)
        self.assertIn("items", payload)
        self.assertIn("wizard_steps", payload)
        self.assertIn("shell_signal", payload)

    def test_cli_doctor_text_includes_version_validation_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)
            stdout = io.StringIO()

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="RaCo Headless 2.9.0\n", stderr="", returncode=0)
                        with redirect_stdout(stdout):
                            result = main(["doctor", "--workspace", str(root)])

        self.assertEqual(result, 0)
        text = stdout.getvalue()
        self.assertIn("Version validation ->", text)
        self.assertIn("recommended: 2.3.0, 2.9.0", text)
        self.assertIn("validation: ok", text)
        self.assertIn("not_pinned", text)

    def test_setup_page_and_api_render_shared_doctor_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)

            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor.Path.home", return_value=root / "home"):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="Python 3.13.0\n", stderr="", returncode=0)
                        client = TestClient(create_app(root=root, profiles=[]))
                        page = client.get("/ui/setup")
                        api = client.get("/ui/api/setup-doctor")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Setup / Doctor", page.text)
        self.assertIn("Setup wizard path", page.text)
        self.assertIn("RaCoHeadless", page.text)
        self.assertIn("Qt6WebEngineCore.dll", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertTrue(api.json()["ready"])
        self.assertEqual(api.json()["mode"], "detect_and_validate")


class TestConfluenceGroundedChecks(unittest.TestCase):
    def test_git_ignorecase_false_is_found_and_true_is_advised(self) -> None:
        from sg_preflight.setup_doctor import _check_git_ignorecase

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "digital-3d-car-models").mkdir(parents=True)
            with mock.patch.dict(os.environ,
                                 {"Digital-3D-Car-Repo": str(root / "digital-3d-car-models")},
                                 clear=False):
                with mock.patch("sg_preflight.setup_doctor.shutil.which", return_value="git"):
                    with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                    return_value="false"):
                        good = _check_git_ignorecase(root)
                    with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                    return_value="true"):
                        bad = _check_git_ignorecase(root)
                    with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                    return_value=""):
                        unset = _check_git_ignorecase(root)
        self.assertEqual(good.status, "found")
        self.assertFalse(good.required)
        self.assertNotEqual(bad.status, "found")
        self.assertNotEqual(unset.status, "found")
        self.assertIn("ignorecase", bad.fix)
        # Advisory only: it must never make the report not-ready.
        self.assertFalse(bad.required)

    def test_bmw_python_version_flags_below_312_only(self) -> None:
        from sg_preflight.setup_doctor import _check_bmw_ci_python_version

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_python = _bmw_ci_python_path(root / "digital-3d-car-models")
            _write_stub(fake_python)
            with mock.patch("sg_preflight.setup_doctor._resolve_bmw_ci_python",
                            return_value=(fake_python, "resolved")):
                with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                return_value="Python 3.12.7"):
                    ok = _check_bmw_ci_python_version(root)
                with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                return_value="Python 3.9.13"):
                    old = _check_bmw_ci_python_version(root)
                with mock.patch("sg_preflight.setup_doctor._version_from_command",
                                return_value="Python 3.13.1"):
                    newer = _check_bmw_ci_python_version(root)
        self.assertEqual(ok.status, "found")
        self.assertEqual(newer.status, "found")
        self.assertNotEqual(old.status, "found")
        self.assertEqual(old.version, "3.9.13")
        self.assertFalse(old.required)

    def test_screenshot_resolution_flags_only_below_the_documented_minimum(self) -> None:
        from sg_preflight.setup_doctor import _check_screenshot_display_resolution

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch("sg_preflight.setup_doctor._virtual_screen_size",
                            return_value=(3840, 2160)):
                ample = _check_screenshot_display_resolution(root)
            with mock.patch("sg_preflight.setup_doctor._virtual_screen_size",
                            return_value=(3340, 1440)):
                exactly = _check_screenshot_display_resolution(root)
            with mock.patch("sg_preflight.setup_doctor._virtual_screen_size",
                            return_value=(1920, 1080)):
                small = _check_screenshot_display_resolution(root)
            with mock.patch("sg_preflight.setup_doctor._virtual_screen_size",
                            return_value=None):
                unknown = _check_screenshot_display_resolution(root)
        self.assertEqual(ample.status, "found")
        self.assertEqual(exactly.status, "found")
        self.assertNotEqual(small.status, "found")
        self.assertFalse(small.required)
        self.assertIn("3340", small.fix)
        # Unreadable display (headless / non-Windows) must stay quiet, not nag.
        self.assertEqual(unknown.status, "found")

    def test_new_advisory_checks_are_in_the_report_and_never_block_ready(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = _doctor_fixture(root)
            with mock.patch.dict(os.environ, env, clear=False):
                with mock.patch("sg_preflight.setup_doctor._virtual_screen_size",
                                return_value=(1280, 720)):
                    with mock.patch("sg_preflight.setup_doctor.subprocess.run") as run:
                        run.return_value = mock.Mock(stdout="Python 3.13.0\n", stderr="", returncode=0)
                        report = build_setup_doctor_report(root).to_dict()
        keys = {item["key"] for item in report["items"]}
        self.assertIn("git_ignorecase", keys)
        self.assertIn("bmw_ci_python_version", keys)
        self.assertIn("screenshot_display_resolution", keys)
        advisory = {"git_ignorecase", "bmw_ci_python_version", "screenshot_display_resolution"}
        for item in report["items"]:
            if item["key"] in advisory:
                self.assertFalse(item["required"])
        # A tiny display and everything advisory being missing must never block readiness.
        self.assertTrue(report["ready"])


if __name__ == "__main__":
    unittest.main()

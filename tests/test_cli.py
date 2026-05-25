from __future__ import annotations

import io
import importlib
import json
import shutil
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import unittest
from unittest import mock

from openpyxl import Workbook

from sg_preflight.activity_log import read_activity_entries
from sg_preflight.cli import main
from sg_preflight.qa_actions import build_action_record, get_operator_action, save_action_record
from sg_preflight.services import RunRequest, execute_profile_run
from tests.operator_helpers import create_review_package_fixture, create_temp_g65_profile, write_text
from tests.test_qa_actions import _create_checker_files


ROOT = Path(__file__).resolve().parents[1]


def _write_delivery_checklist_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Delivery"
    worksheet.append(
        [
            "Car",
            "Last Tested",
            "SVN Revision",
            "Changelog Revision",
            "Export Size",
            "Screenshots",
            "Interface",
            "Perspectives",
        ]
    )
    worksheet.append(["G65_EVO", "2026-05-14 08:30", "r12345", "r12340", "OK", "Fail", "n/a", "Blocked"])
    workbook.save(path)


def _write_export_size_analysis_workbook(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Overview"
    worksheet.append(["G65", None, None, None, None, None, None])
    worksheet.append(["Variant", "TextureCube", "Texture2D", "ArrayResource", "Effect", "Total", "Valeo est."])
    worksheet.append(["BEV-Basis", 5616, 11935.61, 10677.94, 435.56, 28665.11, 25225.3])
    worksheet.append(["ICE-MPP", 5616, 11935.61, 10677.94, 435.56, 28666.11, 25226.3])
    workbook.save(path)


def _write_screenshot_test_state(root: Path) -> None:
    tests_root = root / "digital-3d-car-models" / "cars" / "BMW" / "G65_EVO" / "export" / "tests"
    write_text(root / "digital-3d-car-models" / "ci" / "scripts" / "README.md", "fixture\n")
    write_text(tests_root / "expected" / "front.png", "fake\n")
    write_text(tests_root / "expected" / "rear.png", "fake\n")
    write_text(tests_root / "actuals" / "front.png", "fake\n")
    write_text(tests_root / "diff" / "rear.png", "fake\n")
    write_text(tests_root / "test_config.lua", 'disableTest("country_variant_extra")\n')


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _write_bmw_git_readiness_state(root: Path) -> None:
    repo = root / "digital-3d-car-models"
    car_root = repo / "cars" / "BMW" / "G65_EVO"
    write_text(repo / "cars" / "BMW" / "README_IDCevo.md", "brand readme\n")
    write_text(car_root / "README.md", "profile readme\n")
    write_text(car_root / "_Workfiles" / ".keep", "\n")
    write_text(car_root / "main" / "Main_G65.rca", "scene\n")
    write_text(car_root / "export" / "tests" / "test_config.lua", "-- config\n")
    write_text(car_root / "perspectives_CID180_LHD.json", "{}\n")
    write_text(car_root / "CHANGELOG.md", "# Changelog\n")
    write_text(car_root / "lids.json", "{}\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _git(repo, "config", "user.name", "David Erik Garcia Arena")
    _git(repo, "config", "user.email", "operator@example.invalid")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture profile")


def _write_qa_hero_readiness_state(root: Path) -> None:
    repo = root / "digital-3d-car-models"
    car_root = repo / "cars" / "BMW" / "G65_EVO"
    write_text(repo / "cars" / "BMW" / "CarPaint.json", '{"paints": [{"id": "black"}]}\n')
    write_text(car_root / "resources" / "RES_G65_LightFX" / "RES_G65_LightFX.rca", "lightfx\n")
    write_text(car_root / "resources" / "RES_G65_WelcomeFX" / "RES_G65_WelcomeFX.rca", "welcomefx\n")
    write_text(car_root / "resources" / "RES_G65_ShadesFX" / "RES_G65_ShadesFX.rca", "shadesfx\n")
    write_text(car_root / "resources" / "RES_G65_AnchorPoints" / "RES_G65_AnchorPoints.rca", "anchors\n")
    write_text(car_root / "_Common" / "constants" / "scripts" / "Module_constants_G65.lua", "constants = {}\n")
    write_text(car_root / "perspectives_CID180_LHD.json", "{}\n")


class TestCLI(unittest.TestCase):
    def test_frozen_exe_entry_defaults_to_clean_dashboard_when_double_clicked(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=17) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main([])

        self.assertEqual(result, 17)
        runner.assert_called_once_with(["dashboard", "run", "--ui-mode", "clean", "--workspace", r"C:\bundle"])

    def test_frozen_exe_entry_keeps_explicit_clean_dashboard_mode(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=29) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["dashboard", "run", "--ui-mode", "clean"])

        self.assertEqual(result, 29)
        runner.assert_called_once_with(["dashboard", "run", "--ui-mode", "clean", "--workspace", r"C:\bundle"])

    def test_frozen_exe_entry_keeps_inline_clean_dashboard_mode(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=29) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["dashboard", "run", "--ui-mode=clean"])

        self.assertEqual(result, 29)
        runner.assert_called_once_with(["dashboard", "run", "--ui-mode=clean", "--workspace", r"C:\bundle"])

    def test_frozen_exe_entry_adds_workspace_for_dashboard_without_ui_mode(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=29) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["dashboard", "run"])

        self.assertEqual(result, 29)
        runner.assert_called_once_with(["dashboard", "run", "--workspace", r"C:\bundle"])

    def test_frozen_exe_entry_installs_no_window_subprocess_patch(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=41):
            with mock.patch("sg_preflight.subprocess_utils.install_no_window_subprocess_patch") as installer:
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["--help"])

        self.assertEqual(result, 41)
        installer.assert_called_once_with()

    def test_no_window_subprocess_patch_keeps_popen_subclassable(self) -> None:
        if not hasattr(subprocess, "CREATE_NO_WINDOW"):
            self.skipTest("Windows-only subprocess creation flag")
        module = importlib.import_module("sg_preflight.subprocess_utils")
        original_popen = module.subprocess.Popen
        original_patched = module._PATCHED
        try:
            module.subprocess.Popen = module._ORIGINAL_POPEN
            module._PATCHED = False
            module.install_no_window_subprocess_patch()

            class ProbePopen(module.subprocess.Popen):
                pass

            self.assertTrue(issubclass(ProbePopen, module._ORIGINAL_POPEN))
        finally:
            module.subprocess.Popen = original_popen
            module._PATCHED = original_patched

    def test_frozen_exe_entry_keeps_server_mode_server_only_when_requested(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=31) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["dashboard", "run", "--ui-mode", "clean", "--no-native"])

        self.assertEqual(result, 31)
        runner.assert_called_once_with(
            ["dashboard", "run", "--ui-mode", "clean", "--no-native", "--workspace", r"C:\bundle"]
        )

    def test_frozen_exe_entry_adds_default_workspace_for_explicit_dashboard_mode(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=19) as runner:
            with mock.patch.object(module, "default_workspace", return_value=r"C:\bundle"):
                with mock.patch.object(module.sys, "frozen", True, create=True):
                    result = module.main(["dashboard", "run", "--ui-mode", "grafiks"])

        self.assertEqual(result, 19)
        runner.assert_called_once_with(["dashboard", "run", "--ui-mode", "grafiks", "--workspace", r"C:\bundle"])

    def test_frozen_exe_entry_preserves_full_cli_surface_when_args_are_present(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=23) as runner:
            result = module.main(["list-profiles", "--format", "json"])

        self.assertEqual(result, 23)
        runner.assert_called_once_with(["list-profiles", "--format", "json"])

    def test_frozen_exe_entry_attaches_console_for_explicit_cli_args(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        with mock.patch("sg_preflight.cli.main", return_value=0):
            with mock.patch.object(module, "attach_parent_console") as attach_console:
                module.main(["--help"])

        attach_console.assert_called_once_with()

    def test_frozen_exe_entry_restores_inherited_stdout_handles(self) -> None:
        source = (ROOT / "sg_preflight" / "exe_entry.py").read_text(encoding="utf-8")

        self.assertIn("GetStdHandle", source)
        self.assertIn("open_osfhandle", source)
        self.assertIn("ensure_standard_streams", source)
        self.assertIn("os.devnull", source)
        self.assertNotIn("ctypes.get_last_error() != 5", source)

    def test_frozen_exe_entry_replaces_invalid_standard_stream_handles(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        class InvalidStream:
            closed = False

            def fileno(self) -> int:
                return -1

        invalid_stdin = InvalidStream()
        invalid_stdout = InvalidStream()
        invalid_stderr = InvalidStream()
        with (
            mock.patch.object(module.sys, "stdin", invalid_stdin),
            mock.patch.object(module.sys, "stdout", invalid_stdout),
            mock.patch.object(module.sys, "stderr", invalid_stderr),
        ):
            module.ensure_standard_streams()
            restored_streams = [module.sys.stdin, module.sys.stdout, module.sys.stderr]
            try:
                self.assertIsNot(module.sys.stdin, invalid_stdin)
                self.assertIsNot(module.sys.stdout, invalid_stdout)
                self.assertIsNot(module.sys.stderr, invalid_stderr)
                self.assertFalse(module._stream_needs_replacement(module.sys.stdout))
                module.sys.stdout.write("")
            finally:
                for stream in restored_streams:
                    stream.close()

    def test_frozen_exe_entry_writes_visible_startup_failure_log(self) -> None:
        source = (ROOT / "sg_preflight" / "exe_entry.py").read_text(encoding="utf-8")

        self.assertIn("sgfx-preflight-startup-", source)
        self.assertIn("MessageBoxW", source)

    def test_frozen_exe_entry_shows_startup_dialog_only_for_desktop_routes(self) -> None:
        module = importlib.import_module("sg_preflight.exe_entry")

        self.assertTrue(module.should_show_startup_error([]))
        self.assertTrue(module.should_show_startup_error(["desktop"]))
        self.assertTrue(module.should_show_startup_error(["dashboard", "run", "--ui-mode", "grafiks"]))
        self.assertFalse(module.should_show_startup_error(["dashboard", "run", "--ui-mode", "clean", "--no-native"]))
        self.assertFalse(module.should_show_startup_error(["list-profiles", "--format", "json"]))
        self.assertFalse(module.should_show_startup_error(["ui", "--host", "127.0.0.1", "--port", "8899"]))

    def test_frozen_cli_discards_detached_stdout_error(self) -> None:
        module = importlib.import_module("sg_preflight.cli")
        args = mock.Mock(output_path="")

        def render() -> None:
            raise OSError(22, "Invalid argument")

        with mock.patch.object(module.sys, "frozen", True, create=True):
            module._emit_console(render, args)

    def test_source_cli_does_not_hide_stdout_errors(self) -> None:
        module = importlib.import_module("sg_preflight.cli")
        args = mock.Mock(output_path="")

        def render() -> None:
            raise OSError(22, "Invalid argument")

        with mock.patch.object(module.sys, "frozen", False, create=True):
            with self.assertRaises(OSError):
                module._emit_console(render, args)

    def test_template_cli_roundtrip_save_list_show_delete(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            save_stdout = io.StringIO()
            save_stderr = io.StringIO()
            with redirect_stdout(save_stdout), redirect_stderr(save_stderr):
                save_result = main(
                    [
                        "template",
                        "save",
                        "morning-digest",
                        "--workspace",
                        str(root),
                        "--command",
                        "daily-digest",
                        "--args",
                        "latest --format markdown",
                        "--description",
                        "Morning digest for SG Daily",
                        "--json",
                    ]
                )

            list_stdout = io.StringIO()
            list_stderr = io.StringIO()
            with redirect_stdout(list_stdout), redirect_stderr(list_stderr):
                list_result = main(["template", "list", "--workspace", str(root), "--json"])

            show_stdout = io.StringIO()
            show_stderr = io.StringIO()
            with redirect_stdout(show_stdout), redirect_stderr(show_stderr):
                show_result = main(["template", "show", "morning-digest", "--workspace", str(root), "--json"])

            delete_stdout = io.StringIO()
            delete_stderr = io.StringIO()
            with redirect_stdout(delete_stdout), redirect_stderr(delete_stderr):
                delete_result = main(["template", "delete", "morning-digest", "--workspace", str(root), "--json"])

        self.assertEqual(save_result, 0, msg=save_stderr.getvalue())
        self.assertEqual(list_result, 0, msg=list_stderr.getvalue())
        self.assertEqual(show_result, 0, msg=show_stderr.getvalue())
        self.assertEqual(delete_result, 0, msg=delete_stderr.getvalue())
        save_payload = json.loads(save_stdout.getvalue())
        list_payload = json.loads(list_stdout.getvalue())
        show_payload = json.loads(show_stdout.getvalue())
        delete_payload = json.loads(delete_stdout.getvalue())
        self.assertEqual(save_payload["status"], "saved")
        self.assertEqual(save_payload["note"], "Templates are operator-local saved command configurations. SGFX does not share templates between operators or post them anywhere.")
        self.assertEqual(list_payload["templates"][0]["name"], "morning-digest")
        self.assertEqual(show_payload["template"]["args"], ["latest", "--format", "markdown"])
        self.assertEqual(delete_payload["status"], "deleted")

    def test_template_run_executes_saved_command_without_shelling_out(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_stdout = io.StringIO()
            save_stderr = io.StringIO()
            with redirect_stdout(save_stdout), redirect_stderr(save_stderr):
                save_result = main(
                    [
                        "template",
                        "save",
                        "profiles",
                        "--workspace",
                        str(root),
                        "--command",
                        "list-profiles",
                        "--args",
                        "--format json",
                    ]
                )

            run_stdout = io.StringIO()
            run_stderr = io.StringIO()
            with redirect_stdout(run_stdout), redirect_stderr(run_stderr):
                run_result = main(["template", "run", "profiles", "--workspace", str(root)])

        self.assertEqual(save_result, 0, msg=save_stderr.getvalue())
        self.assertEqual(run_result, 0, msg=run_stderr.getvalue())
        self.assertIn("Templates are operator-local saved command configurations", run_stdout.getvalue())
        self.assertIn('"profile_id": "G65"', run_stdout.getvalue())

    def test_template_cli_duplicate_save_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_stdout = io.StringIO()
            save_stderr = io.StringIO()
            with redirect_stdout(save_stdout), redirect_stderr(save_stderr):
                save_result = main(
                    [
                        "template",
                        "save",
                        "profiles",
                        "--workspace",
                        str(root),
                        "--command",
                        "list-profiles",
                    ]
                )
            self.assertEqual(save_result, 0, msg=save_stderr.getvalue())

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                duplicate_result = main(
                    [
                        "template",
                        "save",
                        "profiles",
                        "--workspace",
                        str(root),
                        "--command",
                        "list-actions",
                    ]
                )

        self.assertEqual(duplicate_result, 1)
        self.assertIn("already exists", stderr.getvalue())

    def test_manual_review_cli_lists_and_uses_family_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            templates_stdout = io.StringIO()
            templates_stderr = io.StringIO()
            with redirect_stdout(templates_stdout), redirect_stderr(templates_stderr):
                templates_result = main(["manual-review", "templates", "--json"])

            session_stdout = io.StringIO()
            session_stderr = io.StringIO()
            with redirect_stdout(session_stdout), redirect_stderr(session_stderr):
                session_result = main(
                    [
                        "manual-review",
                        "session",
                        "--workspace",
                        str(root),
                        "--profile",
                        "F66",
                        "--ticket",
                        "IDCEVODEV-1009244",
                        "--session-id",
                        "manual-mini",
                        "--family",
                        "mini",
                        "--json",
                    ]
                )

        self.assertEqual(templates_result, 0, msg=templates_stderr.getvalue())
        self.assertEqual(session_result, 0, msg=session_stderr.getvalue())
        templates_payload = json.loads(templates_stdout.getvalue())
        session_payload = json.loads(session_stdout.getvalue())
        self.assertIn("mini", {item["family_id"] for item in templates_payload["templates"]})
        self.assertEqual(session_payload["family_id"], "mini")
        self.assertTrue(session_payload["evidence_checklist"])
        self.assertTrue(all(step["verdict"] == "not_run" for step in session_payload["steps"]))

    def test_cli_with_workspace_appends_activity_log_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(["daily-digest", "latest", "--workspace", str(root), "--format", "text"])

            self.assertEqual(result, 0)
            payload = read_activity_entries(root, since="all")
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["entries"][0]["surface"], "daily-digest latest")
            self.assertEqual(payload["entries"][0]["outcome"], "ok")

    def test_jira_post_defaults_to_dry_run_from_numbered_section(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wording_file = root / "out" / "agent-control" / "HANDOVER_WORDING.md"
            wording_file.parent.mkdir(parents=True, exist_ok=True)
            wording_file.write_text(
                "## 19. Jira update\n\n```text\nStatus update\n\nEvidence is not approval.\n```\n",
                encoding="utf-8",
            )

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "jira",
                        "post",
                        "--workspace",
                        str(root),
                        "--ticket",
                        "IDCEVODEV-977874",
                        "--section",
                        "19",
                        "--json",
                    ]
                )

        self.assertEqual(result, 0, msg=stderr.getvalue())
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "dry_run")
        self.assertFalse(payload["posted"])
        self.assertTrue(payload["dry_run"])
        self.assertIn("Evidence is not approval.", payload["body"])
        self.assertIn("--confirm", payload["guard"])

    def test_jira_post_confirm_requires_pat_and_base_url(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            result = main(
                [
                    "jira",
                    "post",
                    "--ticket",
                    "IDCEVODEV-977874",
                    "--body",
                    "Status update",
                    "--confirm",
                ]
            )

        self.assertEqual(result, 1)
        self.assertIn("Jira post failed", stderr.getvalue())
        self.assertIn("base URL", stderr.getvalue())

    def test_jira_status_cli_reports_operator_local_loader_state(self) -> None:
        with mock.patch(
            "sg_preflight.cli.jira_status",
            return_value={
                "status": "available",
                "connection_status": "available",
                "ticket_status": "available",
                "credential": {"pat_loaded": True, "pat_length": 29, "pat_fingerprint": "****real"},
                "is_approval": False,
            },
        ) as status_mock:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(["jira", "status", "--ticket", "IDCEVODEV-1009244", "--format", "json"])

        self.assertEqual(result, 0)
        status_mock.assert_called_once_with(ticket="IDCEVODEV-1009244", api_version="2")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertNotIn("test-pat-placeholder-not-real", stdout.getvalue())

    def test_jira_post_comment_cli_uses_auto_confirm_gate(self) -> None:
        with mock.patch(
            "sg_preflight.cli.post_jira_comment_action",
            return_value={
                "status": "skipped",
                "ticket": "IDCEVODEV-1009244",
                "action": "add-comment",
                "dry_run": True,
                "confirm_required": True,
                "is_approval": False,
            },
        ) as post_mock:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "jira",
                        "post-comment",
                        "--ticket",
                        "IDCEVODEV-1009244",
                        "--body",
                        "Status update",
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "skipped")
        post_mock.assert_called_once()
        self.assertFalse(post_mock.call_args.kwargs["auto_confirm"])

    def test_jira_register_cli_writes_redacted_operator_local_credentials(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            pat_file = root / "pat.txt"
            pat_file.write_text("test-pat-placeholder-not-real\n", encoding="utf-8")
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "jira",
                        "register",
                        "--jira-url",
                        "https://jira.example/",
                        "--pat-file",
                        str(pat_file),
                        "--state-dir",
                        str(root / "state"),
                        "--format",
                        "json",
                    ]
                )
            credential_path = root / "state" / "jira_pat.json"
            saved = json.loads(credential_path.read_text(encoding="utf-8"))

        self.assertEqual(result, 0)
        self.assertEqual(saved["jira_url"], "https://jira.example")
        self.assertEqual(saved["pat"], "test-pat-placeholder-not-real")
        self.assertNotIn("test-pat-placeholder-not-real", stdout.getvalue())

    def test_jira_update_issue_cli_parses_fields_json(self) -> None:
        with mock.patch(
            "sg_preflight.cli.update_jira_issue_action",
            return_value={"status": "skipped", "ticket": "IDCEVODEV-1009244", "action": "update-issue"},
        ) as update_mock:
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "jira",
                        "update-issue",
                        "--ticket",
                        "IDCEVODEV-1009244",
                        "--fields",
                        '{"summary":"Updated summary"}',
                        "--format",
                        "json",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["action"], "update-issue")
        update_mock.assert_called_once()
        self.assertEqual(update_mock.call_args.args[1], {"summary": "Updated summary"})

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
        self.assertIn("repo_checker_all", action_ids)
        self.assertIn("repo_checker_idcevo", action_ids)
        self.assertIn("qa_stack__g65", action_ids)
        self.assertIn("unused_resources__g65", action_ids)
        self.assertIn("delivery_checklist__g65", action_ids)
        self.assertIn("bmw_screenshot_smoke__g65", action_ids)

    def test_list_actions_text_uses_available_vocab(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-actions"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("[available]", result.stdout)
        self.assertNotIn("[ready]", result.stdout)

    def test_list_profiles_accepts_format_and_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_path = Path(temp_dir) / "profiles.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "list-profiles",
                    "--format",
                    "json",
                    "--output-path",
                    str(output_path),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            self.assertEqual(result.stdout, "")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
            profile_ids = {item["profile_id"] for item in payload}
            self.assertIn("G65", profile_ids)

    def test_list_checkers_reports_checker_catalog(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "list-checkers", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        checker_keys = {item["key"] for item in payload}
        self.assertIn("execute_checks", checker_keys)
        self.assertIn("checkall_bat", checker_keys)
        self.assertIn("delivery_checklist", checker_keys)
        self.assertIn("bmw_smoke", checker_keys)

    def test_delivery_checklist_read_cli_returns_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_path = root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist" / "Delivery Data - BMW.xlsx"
            _write_delivery_checklist_workbook(workbook_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "delivery-checklist",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "delivery-checklist",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        checks = {item["key"]: item for item in payload["checks"]}
        self.assertEqual(checks["export_size"]["status"], "passed")
        self.assertEqual(checks["screenshots"]["status"], "failed")
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Delivery checklist data is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run the delivery checklist or modify the workbook.", markdown_stdout.getvalue())

    def test_export_size_analysis_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_path = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(workbook_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "export-size-analysis",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--latest",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "export-size-analysis",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--date",
                        "20251002",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65")
        self.assertEqual(payload["workbook_date"], "2025-10-02")
        self.assertEqual(payload["variant_count"], 2)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Export-size analysis data is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run the export size workflow or modify the workbook.", markdown_stdout.getvalue())
        self.assertIn("BEV-Basis", markdown_stdout.getvalue())

    def test_read_commands_accept_format_and_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            delivery_workbook = root / "repositories" / "trunk" / ".pdx" / "checkers" / "deliveryChecklist" / "Delivery Data - BMW.xlsx"
            export_workbook = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            json_output = root / "reports" / "delivery.json"
            markdown_output = root / "reports" / "export.md"
            _write_delivery_checklist_workbook(delivery_workbook)
            _write_export_size_analysis_workbook(export_workbook)

            delivery_stdout = io.StringIO()
            with redirect_stdout(delivery_stdout):
                delivery_result = main(
                    [
                        "delivery-checklist",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--format",
                        "json",
                        "--out",
                        str(json_output),
                    ]
                )

            export_stdout = io.StringIO()
            with redirect_stdout(export_stdout):
                export_result = main(
                    [
                        "export-size-analysis",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--latest",
                        "--format",
                        "markdown",
                        "--output-path",
                        str(markdown_output),
                    ]
                )

            self.assertEqual(delivery_result, 0)
            self.assertEqual(delivery_stdout.getvalue(), "")
            delivery_payload = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(delivery_payload["status"], "available")
            self.assertFalse(delivery_payload["is_approval"])
            self.assertEqual(export_result, 0)
            self.assertEqual(export_stdout.getvalue(), "")
            markdown = markdown_output.read_text(encoding="utf-8")
            self.assertIn("Export-size analysis data is read-only", markdown)
            self.assertIn("Manual delivery review", markdown)

    def test_daily_digest_format_output_path_is_fresh_workspace_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            digest_path = root / "daily" / "morning.md"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--format",
                        "markdown",
                        "--output-path",
                        str(digest_path),
                    ]
                )

            self.assertEqual(result, 0)
            self.assertEqual(stdout.getvalue(), "")
            self.assertEqual(stderr.getvalue(), "")
            markdown = digest_path.read_text(encoding="utf-8")
            self.assertIn("No review package found", markdown)
            self.assertIn("Manual review remains required", markdown)
            self.assertNotIn("approved", markdown.lower())

    def test_format_rejects_conflicting_legacy_alias(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workbook_path = root / "Cars" / "size_analysis" / "G65_20251002.xlsx"
            _write_export_size_analysis_workbook(workbook_path)

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    main(
                        [
                            "export-size-analysis",
                            "read",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--json",
                            "--format",
                            "markdown",
                        ]
                    )

        self.assertNotEqual(raised.exception.code, 0)
        self.assertIn("cannot be combined", stderr.getvalue())

    def test_run_reports_malformed_json_config_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "broken.json"
            config_path.write_text('{"packs": [', encoding="utf-8")

            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = main(
                    [
                        "run",
                        "--bundle",
                        str(ROOT / "demo" / "good"),
                        "--config",
                        str(config_path),
                        "--fail-on",
                        "never",
                    ]
                )

        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Malformed JSON", stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_screenshot_test_state_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_test_state(root)
            clean_env = {
                "SG_BMW_CAR_MODELS_ROOT": "",
                "SG_CARMODELS_REPO": "",
                "SG-CarModels-Repo": "",
                "Digital-3D-Car-Repo": "",
            }

            stdout = io.StringIO()
            with mock.patch.dict("os.environ", clean_env):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "screenshot-test-state",
                            "read",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--json",
                        ]
                    )

                markdown_stdout = io.StringIO()
                with redirect_stdout(markdown_stdout):
                    markdown_result = main(
                        [
                            "screenshot-test-state",
                            "read",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--markdown",
                        ]
                    )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertEqual(payload["expected_count"], 2)
        self.assertEqual(payload["actual_count"], 1)
        self.assertEqual(payload["diff_count"], 1)
        self.assertEqual(payload["disabled_test_count"], 1)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Screenshot test state is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not run screenshot tests or approve screenshots.", markdown_stdout.getvalue())
        self.assertNotIn("approved", markdown_stdout.getvalue().lower())

    def test_risk_score_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_test_state(root)
            clean_env = {
                "SG_BMW_CAR_MODELS_ROOT": "",
                "SG_CARMODELS_REPO": "",
                "SG-CarModels-Repo": "",
                "Digital-3D-Car-Repo": "",
            }

            stdout = io.StringIO()
            with mock.patch.dict("os.environ", clean_env):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "risk-score",
                            "read",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--json",
                        ]
                    )

                markdown_stdout = io.StringIO()
                with redirect_stdout(markdown_stdout):
                    markdown_result = main(
                        [
                            "risk-score",
                            "read",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--markdown",
                        ]
                    )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["risk_score"] > 0, True)
        self.assertEqual(payload["delta_since_last_review"]["status"], "not_run")
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Per-car risk score", markdown_stdout.getvalue())
        self.assertIn("Manual review remains required", markdown_stdout.getvalue())
        self.assertNotIn("production-" "ready", markdown_stdout.getvalue().lower())

    def test_team_digest_board_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_test_state(root)
            clean_env = {
                "SG_BMW_CAR_MODELS_ROOT": "",
                "SG_CARMODELS_REPO": "",
                "SG-CarModels-Repo": "",
                "Digital-3D-Car-Repo": "",
            }

            stdout = io.StringIO()
            with mock.patch.dict("os.environ", clean_env):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "team-digest-board",
                            "snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--json",
                        ]
                    )

                markdown_stdout = io.StringIO()
                with redirect_stdout(markdown_stdout):
                    markdown_result = main(
                        [
                            "team-digest-board",
                            "snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--markdown",
                        ]
                    )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["share_decision"]["selected_model"], "local_snapshot")
        self.assertEqual(payload["share_decision"]["options"][0]["status"], "available")
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Sharing Model Trade-Offs", markdown_stdout.getvalue())
        self.assertIn("local_snapshot", markdown_stdout.getvalue())
        self.assertIn("Manual review remains required", markdown_stdout.getvalue())
        self.assertNotIn("validated", markdown_stdout.getvalue().lower())

    def test_cross_car_comparison_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_screenshot_test_state(root)
            clean_env = {
                "SG_BMW_CAR_MODELS_ROOT": "",
                "SG_CARMODELS_REPO": "",
                "SG-CarModels-Repo": "",
                "Digital-3D-Car-Repo": "",
            }

            stdout = io.StringIO()
            with mock.patch.dict("os.environ", clean_env):
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "cross-car-comparison",
                            "snapshot",
                            "--workspace",
                            str(root),
                            "--left-profile",
                            "G70",
                            "--right-profile",
                            "G65",
                            "--json",
                        ]
                    )

                markdown_stdout = io.StringIO()
                with redirect_stdout(markdown_stdout):
                    markdown_result = main(
                        [
                            "cross-car-comparison",
                            "snapshot",
                            "--workspace",
                            str(root),
                            "--left-profile",
                            "G70",
                            "--right-profile",
                            "G65",
                            "--markdown",
                        ]
                    )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["comparison_axis"], "risk-score")
        self.assertEqual(payload["profiles"], ["G70", "G65"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("Cross-Car Comparison", markdown_stdout.getvalue())
        self.assertIn("Manual review remains required", markdown_stdout.getvalue())
        self.assertNotIn("validated", markdown_stdout.getvalue().lower())

    def test_operator_handoff_cli_records_and_reads_latest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            record_stdout = io.StringIO()
            with redirect_stdout(record_stdout):
                record_result = main(
                    [
                        "operator-handoff",
                        "record",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--ticket",
                        "IDCEVODEV-977874",
                        "--stopping-point",
                        "Exterior diffs reviewed through right-front view.",
                        "--next-step",
                        "Continue with interior lighting screenshots.",
                        "--json",
                    ]
                )

            latest_stdout = io.StringIO()
            with redirect_stdout(latest_stdout):
                latest_result = main(
                    [
                        "operator-handoff",
                        "latest",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(record_result, 0)
        payload = json.loads(record_stdout.getvalue())
        self.assertEqual(payload["status"], "recorded")
        self.assertEqual(payload["latest_handoff"]["profile_id"], "G65")
        self.assertFalse(payload["is_approval"])
        self.assertEqual(latest_result, 0)
        self.assertIn("Operator Handoff", latest_stdout.getvalue())
        self.assertIn("Stopping point", latest_stdout.getvalue())
        self.assertIn("Manual review remains required", latest_stdout.getvalue())
        self.assertNotIn("validated", latest_stdout.getvalue().lower())

    def test_bmw_git_readiness_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_bmw_git_readiness_state(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "bmw-git-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "bmw-git-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertTrue(payload["main_scene_present"])
        self.assertTrue(payload["latest_commit"]["sha"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("BMW Git per-profile readiness is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX does not write to BMW Git or fetch from the remote.", markdown_stdout.getvalue())
        self.assertNotIn("approved", markdown_stdout.getvalue().lower())

    def test_qa_hero_readiness_read_cli_returns_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_qa_hero_readiness_state(root)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "qa-hero-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--json",
                    ]
                )

            markdown_stdout = io.StringIO()
            with redirect_stdout(markdown_stdout):
                markdown_result = main(
                    [
                        "qa-hero-readiness",
                        "read",
                        "--workspace",
                        str(root),
                        "--profile",
                        "G65",
                        "--markdown",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertEqual(payload["available_count"], 7)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(markdown_result, 0)
        self.assertIn("QA Hero readiness state is read-only", markdown_stdout.getvalue())
        self.assertIn("SGFX surfaces presence and counts only", markdown_stdout.getvalue())
        self.assertIn("LightFX resources", markdown_stdout.getvalue())
        self.assertNotIn("approved", markdown_stdout.getvalue().lower())

    def test_workflow_status_reports_repo_scene_stage(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "workflow-status", "--json"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = json.loads(result.stdout)
        workflow_keys = {item["key"] for item in payload}
        self.assertIn("repo_scene_checks", workflow_keys)
        self.assertIn("bmw_screenshot_smoke", workflow_keys)

    def test_desktop_help_is_available(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "desktop", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("desktop operator shell", result.stdout.lower())
        self.assertIn("--ui-mode", result.stdout)

    def test_desktop_state_profiles_help_uses_available_vocab(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "desktop-state", "profiles", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("available desktop profiles", result.stdout.lower())
        self.assertNotIn("ready desktop profiles", result.stdout.lower())

    def test_retro_extract_help_uses_neutral_team_retro_wording(self) -> None:
        result = subprocess.run(
            [sys.executable, "-m", "sg_preflight", "retro-extract", "--help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertIn("team retrospective export", result.stdout)
        self.assertNotIn("White" "board retro export", result.stdout)

    def test_desktop_command_dispatches_to_runner(self) -> None:
        with mock.patch("sg_preflight.desktop.app.run_desktop_app", return_value=7) as runner:
            result = main(["desktop", "--profile", "G65"])
        self.assertEqual(result, 7)
        runner.assert_called_once_with(workspace=None, initial_profile_id="G65", initial_mode="clean")

    def test_desktop_state_surfaces_returns_eight_grafiks_evidence_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                result = main(["desktop-state", "surfaces", "G65", "--workspace", str(root), "--json"])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(result, 0)
        self.assertEqual(
            [item["key"] for item in payload],
            [
                "delivery-checklist",
                "screenshot-test-state",
                "risk-score",
                "cross-car-comparison",
                "daily-digest",
                "team-digest-board",
                "operator-handoff",
                "manual-review",
            ],
        )

    def test_launch_action_spawns_worker_and_returns_queued_record(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            stdout = io.StringIO()
            with mock.patch("sg_preflight.cli.subprocess.Popen") as popen:
                with mock.patch("sg_preflight.qa_actions.prerequisite_status", return_value=[]):
                    with redirect_stdout(stdout):
                        result = main(
                            [
                                "launch-action",
                                "qa_stack__g65",
                                "--workspace",
                                str(root),
                                "--json",
                            ]
                        )

        self.assertEqual(result, 0)
        popen.assert_called_once()
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["action_id"], "qa_stack__g65")
        self.assertEqual(payload["status"], "queued")
        self.assertTrue(payload["run_id"])

    def test_launch_action_uses_frozen_exe_directly_for_worker(self) -> None:
        import sg_preflight.cli as cli_module

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            stdout = io.StringIO()
            with mock.patch.object(cli_module.sys, "frozen", True, create=True):
                with mock.patch.object(cli_module.sys, "executable", r"C:\bundle\sgfx-preflight.exe"):
                    with mock.patch("sg_preflight.cli.subprocess.Popen") as popen:
                        with mock.patch("sg_preflight.qa_actions.prerequisite_status", return_value=[]):
                            with redirect_stdout(stdout):
                                result = cli_module.main(
                                    [
                                        "launch-action",
                                        "qa_stack__g65",
                                        "--workspace",
                                        str(root),
                                        "--json",
                                    ]
                                )

        self.assertEqual(result, 0)
        command = popen.call_args.args[0]
        self.assertEqual(command[:2], [r"C:\bundle\sgfx-preflight.exe", "run-action-worker"])
        self.assertNotIn("-m", command)
        self.assertNotIn("sg_preflight", command)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "queued")

    def test_dependency_setup_worker_invokes_hidden_runner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            stdout = io.StringIO()
            with mock.patch(
                "sg_preflight.dependency_onboarding.run_dependency_setup_action",
                return_value={"status": "recorded", "summary": "ok", "is_approval": False},
            ) as runner:
                with redirect_stdout(stdout):
                    result = main(
                        [
                            "dependency-setup-worker",
                            "setup-digital-3d-car-repo",
                            "--workspace",
                            str(root),
                            "--target-path",
                            str(root / "digital-3d-car-models"),
                        ]
                    )

        self.assertEqual(result, 0)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "recorded")
        runner.assert_called_once_with(
            action_id="setup-digital-3d-car-repo",
            workspace=root.resolve(),
            operator_confirmed=True,
            target_path=str(root / "digital-3d-car-models"),
            source_path=None,
            stream_output=True,
        )

    def test_desktop_state_recent_actions_runs_and_snapshots_use_workspace_override(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            action = get_operator_action("repo_checker_profile__g65", root)
            record = build_action_record(action, root)
            record.status = "completed"
            record.summary = {
                "title": "Repo checker result",
                "lines": [
                    "Style checker: 1 style-guide issue(s) across 8 checked file(s).",
                    "Open first: C:\\repo\\repositories\\trunk\\Cars_IDCevo\\BMW\\G65\\logic\\car_logic.lua (style_checker) - style issue",
                ],
            }
            write_text(Path(record.paths["log"]), "synthetic log\n")
            save_action_record(record)
            run_record = execute_profile_run(
                profile,
                RunRequest(
                    profile_id="G65",
                    packs=["anchors", "constants", "carpaints", "project_sanity"],
                    fail_on="never",
                ),
                root,
            )

            recent_stdout = io.StringIO()
            with redirect_stdout(recent_stdout):
                recent_result = main(
                    [
                        "desktop-state",
                        "recent-actions",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

            recent_runs_stdout = io.StringIO()
            with redirect_stdout(recent_runs_stdout):
                recent_runs_result = main(
                    [
                        "desktop-state",
                        "recent-runs",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

            snapshot_stdout = io.StringIO()
            with redirect_stdout(snapshot_stdout):
                snapshot_result = main(
                    [
                        "desktop-state",
                        "snapshot",
                        record.run_id,
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

            run_snapshot_stdout = io.StringIO()
            with redirect_stdout(run_snapshot_stdout):
                run_snapshot_result = main(
                    [
                        "desktop-state",
                        "run-snapshot",
                        run_record.run_id,
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

        self.assertEqual(recent_result, 0)
        recent_payload = json.loads(recent_stdout.getvalue())
        self.assertEqual(recent_payload[0]["run_id"], record.run_id)
        self.assertEqual(recent_payload[0]["profile_id"], "G65")
        self.assertEqual(recent_runs_result, 0)
        recent_runs_payload = json.loads(recent_runs_stdout.getvalue())
        self.assertEqual(recent_runs_payload[0]["run_id"], run_record.run_id)
        self.assertEqual(recent_runs_payload[0]["profile_id"], "G65")
        self.assertEqual(snapshot_result, 0)
        snapshot_payload = json.loads(snapshot_stdout.getvalue())
        self.assertEqual(snapshot_payload["run_id"], record.run_id)
        self.assertIn("Style checker:", snapshot_payload["summary_lines"][0])
        self.assertEqual(run_snapshot_result, 0)
        run_snapshot_payload = json.loads(run_snapshot_stdout.getvalue())
        self.assertEqual(run_snapshot_payload["run_id"], run_record.run_id)
        self.assertIn("Counts:", run_snapshot_payload["summary_lines"][1])

    def test_desktop_state_overview_returns_native_startup_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            create_temp_g65_profile(root)
            _create_checker_files(root)
            (root / "config").mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / "config" / "sg_rules_live_g65.json", root / "config" / "sg_rules_live_g65.json")

            overview_stdout = io.StringIO()
            with redirect_stdout(overview_stdout):
                result = main(
                    [
                        "desktop-state",
                        "overview",
                        "--workspace",
                        str(root),
                        "--profile-id",
                        "G65",
                        "--json",
                    ]
                )

        self.assertEqual(result, 0)
        payload = json.loads(overview_stdout.getvalue())
        self.assertEqual(payload["recommended_profile_id"], "G65")
        self.assertEqual(payload["recommended_action_id"], "qa_stack__g65")
        self.assertGreaterEqual(payload["action_count"], 5)
        self.assertGreaterEqual(payload["blocker_count"], 1)
        self.assertIn("summary_line", payload)

    def test_ticket_review_cli_forwards_candidate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            candidate_root = root / "manual-candidates"
            candidate_root.mkdir(parents=True, exist_ok=True)
            fake_result = mock.Mock()
            fake_result.bundle = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_ticket_review_bundle", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_ticket_review") as console:
                    result = main(
                        [
                            "ticket-review",
                            "IDCEVODEV-960073",
                            "--workspace",
                            str(root),
                            "--profile",
                            "G65",
                            "--candidate-root",
                            str(candidate_root),
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["candidate_roots"],
            (candidate_root.resolve(),),
        )

    def test_review_board_related_commands_return_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fixture = create_review_package_fixture(root)

            review_board_stdout = io.StringIO()
            with redirect_stdout(review_board_stdout):
                review_board_result = main(
                    [
                        "review-board",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            copy_update_stdout = io.StringIO()
            with redirect_stdout(copy_update_stdout):
                copy_update_result = main(
                    [
                        "review-board",
                        "copy-update",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                    ]
                )

            copy_update_json_stdout = io.StringIO()
            with redirect_stdout(copy_update_json_stdout):
                copy_update_json_result = main(
                    [
                        "review-board",
                        "copy-update",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            verify_stdout = io.StringIO()
            with redirect_stdout(verify_stdout):
                verify_result = main(
                    [
                        "review-board",
                        "verify",
                        "--workspace",
                        str(root),
                        "--path",
                        str(fixture["zip_path"]),
                        "--json",
                    ]
                )

            priority_stdout = io.StringIO()
            with redirect_stdout(priority_stdout):
                priority_result = main(
                    [
                        "review-priority",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            delta_stdout = io.StringIO()
            with redirect_stdout(delta_stdout):
                delta_result = main(
                    [
                        "daily-delta",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            digest_stdout = io.StringIO()
            with redirect_stdout(digest_stdout):
                digest_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                    ]
                )

            digest_json_stdout = io.StringIO()
            with redirect_stdout(digest_json_stdout):
                digest_json_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            digest_markdown_stdout = io.StringIO()
            with redirect_stdout(digest_markdown_stdout):
                digest_markdown_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--markdown",
                    ]
                )

            desktop_stdout = io.StringIO()
            with redirect_stdout(desktop_stdout):
                desktop_result = main(
                    [
                        "desktop-state",
                        "review-board",
                        "--workspace",
                        str(root),
                        "--ticket-id",
                        "IDCEVODEV-960073",
                        "--json",
                    ]
                )

            decisions_stdout = io.StringIO()
            with redirect_stdout(decisions_stdout):
                decisions_result = main(
                    [
                        "review-decisions",
                        "set",
                        "IDCEVODEV-960073",
                        "lights_OnlyCones",
                        "--workspace",
                        str(root),
                        "--status",
                        "follow_up",
                        "--owner",
                        "Adrian",
                        "--note",
                        "Treat as follow-up.",
                        "--json",
                    ]
                )

            findings_stdout = io.StringIO()
            with redirect_stdout(findings_stdout):
                findings_result = main(
                    [
                        "external-findings",
                        "add",
                        "IDCEVODEV-960073",
                        "--workspace",
                        str(root),
                        "--source",
                        "Teams / 3D Car - Bug Reports / Jana",
                        "--reported-by",
                        "Jana",
                        "--category",
                        "changelog",
                        "--type",
                        "changelog finding",
                        "--scope",
                        "G50,NA8",
                        "--finding",
                        "Missing changelog entry for light cones position change",
                        "--owner",
                        "Ana-Karina Nazare",
                        "--status",
                        "reported",
                        "--related-surface",
                        "lights_OnlyCones",
                        "--json",
                    ]
                )

        self.assertEqual(review_board_result, 0)
        self.assertEqual(copy_update_result, 0)
        self.assertEqual(copy_update_json_result, 0)
        self.assertEqual(verify_result, 0)
        self.assertEqual(priority_result, 0)
        self.assertEqual(delta_result, 0)
        self.assertEqual(digest_result, 0)
        self.assertEqual(digest_json_result, 0)
        self.assertEqual(digest_markdown_result, 0)
        self.assertEqual(desktop_result, 0)
        self.assertEqual(decisions_result, 0)
        self.assertEqual(findings_result, 0)
        self.assertEqual(json.loads(review_board_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertIn("IDCEVODEV-960073 QA status", copy_update_stdout.getvalue())
        self.assertEqual(json.loads(copy_update_json_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(json.loads(verify_stdout.getvalue())["status"], "warning")
        self.assertEqual(json.loads(priority_stdout.getvalue())["source"], "daily_snapshot")
        self.assertIn("current_created_at", json.loads(delta_stdout.getvalue()))
        self.assertIn("Daily 3D Car QA Digest", digest_stdout.getvalue())
        digest_payload = json.loads(digest_json_stdout.getvalue())
        self.assertEqual(digest_payload["ticket_id"], "IDCEVODEV-960073")
        self.assertIn("evidence_prepared", digest_payload["sections"])
        self.assertIn("what_landed_today", digest_payload["sections"])
        self.assertIn("workflow_status", digest_payload["sections"])
        self.assertIn("manual_review_pending", digest_payload["sections"])
        self.assertIn("waiting_for_owner", digest_payload["sections"])
        self.assertIn("suggested_review_order", digest_payload["sections"])
        self.assertIn("# Daily 3D Car QA Digest", digest_markdown_stdout.getvalue())
        self.assertIn("Workflow status", digest_markdown_stdout.getvalue())
        self.assertIn("Suggested review order", digest_markdown_stdout.getvalue())
        self.assertEqual(json.loads(desktop_stdout.getvalue())["ticket_id"], "IDCEVODEV-960073")
        self.assertEqual(json.loads(decisions_stdout.getvalue())["decisions"][0]["status"], "follow_up")
        self.assertEqual(json.loads(findings_stdout.getvalue())["findings"][0]["category"], "changelog")

    def test_daily_digest_latest_handles_fresh_workspace_without_review_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            markdown_stdout = io.StringIO()
            markdown_stderr = io.StringIO()
            with redirect_stdout(markdown_stdout), redirect_stderr(markdown_stderr):
                markdown_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--markdown",
                    ]
                )

            json_stdout = io.StringIO()
            json_stderr = io.StringIO()
            with redirect_stdout(json_stdout), redirect_stderr(json_stderr):
                json_result = main(
                    [
                        "daily-digest",
                        "latest",
                        "--workspace",
                        str(root),
                        "--json",
                    ]
                )

        self.assertEqual(markdown_result, 0)
        self.assertEqual(markdown_stderr.getvalue(), "")
        self.assertIn("No review package found", markdown_stdout.getvalue())
        self.assertIn("ticket-review", markdown_stdout.getvalue())
        self.assertIn("Manual review remains required", markdown_stdout.getvalue())
        self.assertEqual(json_result, 0)
        self.assertEqual(json_stderr.getvalue(), "")
        payload = json.loads(json_stdout.getvalue())
        self.assertFalse(payload["data_available"])
        self.assertEqual(payload["status"], "no_review_package")
        self.assertIn("ticket-review", payload["setup_hint"])
        self.assertIn("what_landed_today", payload["sections"])
        self.assertIn("workflow_status", payload["sections"])

    def test_ticket_review_cli_sendable_disables_action_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.bundle = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_ticket_review_bundle", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_ticket_review"):
                    result = main(
                        [
                            "ticket-review",
                            "IDCEVODEV-960073",
                            "--workspace",
                            str(root),
                            "--sendable",
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertFalse(materialize.call_args.kwargs["include_action_bundles"])

    def test_daily_snapshot_cli_forwards_battery_filters(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.snapshot = mock.Mock()
            fake_result.markdown_path = root / "snapshot.md"
            fake_result.json_path = root / "snapshot.json"

            with mock.patch("sg_preflight.cli.materialize_daily_qa_snapshot", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_daily_snapshot") as console:
                    result = main(
                        [
                            "daily-qa-snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "NA8",
                            "--battery-defaults",
                            "--battery-filter",
                            "lights_drl_front",
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["battery_filters"],
            (
                "default",
                "openAllDoors_",
                "lights_drl_front",
                "lights_LowBeam",
                "lights_HighBeam",
                "lights_OnlyCones",
                "welcome_animation_",
                "automatic_Doors_",
                "highlighting_Doors",
            ),
        )

    def test_screenshot_triage_cli_forwards_candidate_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project_root = root / "Cars_IDCevo" / "BMW" / "G70"
            project_root.mkdir(parents=True, exist_ok=True)
            candidate_root = root / "manual-candidates"
            candidate_root.mkdir(parents=True, exist_ok=True)
            fake_bundle = mock.Mock()
            fake_bundle.report = mock.Mock()

            with mock.patch("sg_preflight.cli.build_visual_review_prep", return_value=mock.Mock(priority_screenshots=("focus.png",))):
                with mock.patch("sg_preflight.cli.materialize_screenshot_triage", return_value=fake_bundle) as materialize:
                    with mock.patch("sg_preflight.cli._console_screenshot_triage") as console:
                        result = main(
                            [
                                "screenshot-triage",
                                "--project-root",
                                str(project_root),
                                "--workspace",
                                str(root),
                                "--candidate-root",
                                str(candidate_root),
                                "--structural-min-review-score",
                                "99",
                                "--external-vision",
                            ]
                        )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["candidate_roots"],
            (candidate_root.resolve(),),
        )
        self.assertEqual(materialize.call_args.kwargs["visual_thresholds"].structural_min_review_score, 99.0)
        self.assertTrue(materialize.call_args.kwargs["external_classifier_requested"])

    def test_daily_qa_snapshot_cli_forwards_profiles_and_smoke_options(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake_result = mock.Mock()
            fake_result.snapshot = mock.Mock()

            with mock.patch("sg_preflight.cli.materialize_daily_qa_snapshot", return_value=fake_result) as materialize:
                with mock.patch("sg_preflight.cli._console_daily_snapshot") as console:
                    result = main(
                        [
                            "daily-qa-snapshot",
                            "--workspace",
                            str(root),
                            "--profile",
                            "NA8",
                            "--profile",
                            "G78",
                            "--smoke-test",
                            "openAllDoors_rightView",
                            "--no-smoke",
                        ]
                    )

        self.assertEqual(result, 0)
        console.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["profile_ids"],
            ("NA8", "G78"),
        )
        self.assertEqual(materialize.call_args.kwargs["smoke_test"], "openAllDoors_rightView")
        self.assertFalse(materialize.call_args.kwargs["run_smoke"])

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

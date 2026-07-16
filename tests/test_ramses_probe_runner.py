from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from sg_preflight.ramses_probe_runner import (
    EVIDENCE_FILE_NAME,
    NATIVE_REPORT_NAME,
    ProbeRunRequest,
    build_helper_arguments,
    run_probe,
    sha256_file,
    validate_native_report,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _native_report(*, profile: str, scene_path: str, failure: dict | None = None,
                   frame: dict | None = None) -> dict[str, object]:
    phase_names = ("arguments", "metadata", "scene_load", "validation", "inventory", "logic",
                   "perspective", "frame")
    statuses = ["completed"] * 6 + ["not_requested", "not_requested"]
    if failure is not None:
        failed_index = phase_names.index(failure["phase"])
        statuses = ["completed"] * failed_index + ["failed"] + ["not_run"] * (7 - failed_index)
    return {
        "schemaVersion": 1,
        "probeVersion": "0.1.0",
        "profile": profile,
        "backend": "opengl",
        "scenePath": scene_path,
        "metadata": {
            "versionString": "28.16.0",
            "versionMajor": 28,
            "versionMinor": 16,
            "versionPatch": 0,
            "featureLevel": 1,
        },
        "phases": [
            {"phase": name, "status": status}
            for name, status in zip(phase_names, statuses)
        ],
        "failure": failure,
        "findings": [],
        "inventory": [],
        "logic": [],
        "lifecycle": None,
        "frame": frame,
    }


class RamsesProbeRunnerRequestTests(unittest.TestCase):
    def test_build_helper_arguments_matches_probe_grammar(self) -> None:
        request = ProbeRunRequest(
            profile="G45",
            scene_path=Path(r"C:\evidence\exported.ramses"),
            output_root=Path(r"C:\evidence\out"),
            helper_path=Path(r"C:\tools\sgfx_cine_ramses_probe.exe"),
            helper_sha256="0" * 64,
        )
        arguments = build_helper_arguments(request)
        self.assertEqual(
            arguments,
            [
                "--scene", r"C:\evidence\exported.ramses",
                "--output-root", r"C:\evidence\out",
                "--profile", "G45",
                "--backend", "opengl",
            ],
        )

    def test_build_helper_arguments_appends_perspective_pair(self) -> None:
        request = ProbeRunRequest(
            profile="G45",
            scene_path=Path(r"C:\evidence\exported.ramses"),
            output_root=Path(r"C:\evidence\out"),
            helper_path=Path(r"C:\tools\probe.exe"),
            helper_sha256="0" * 64,
            perspective_path=Path(r"C:\evidence\perspectives.json"),
            perspective_id="CID_CARHUB_ALL_GOOD",
        )
        arguments = build_helper_arguments(request)
        self.assertEqual(arguments[-4:], ["--perspective", r"C:\evidence\perspectives.json",
                                          "--perspective-id", "CID_CARHUB_ALL_GOOD"])


class RamsesProbeRunnerValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scene_path = r"C:\evidence\exported.ramses"
        self.report = _native_report(profile="G45", scene_path=self.scene_path)

    def _rejections(self, report: object) -> list[str]:
        return validate_native_report(report, expected_profile="G45",
                                      expected_scene_path=self.scene_path)

    def test_valid_report_is_accepted(self) -> None:
        self.assertEqual(self._rejections(self.report), [])

    def test_non_object_report_is_malformed(self) -> None:
        self.assertIn("malformed_report", self._rejections(["not", "a", "report"]))

    def test_unknown_top_level_key_is_malformed(self) -> None:
        self.report["extraKey"] = True
        self.assertIn("malformed_report", self._rejections(self.report))

    def test_missing_top_level_key_is_malformed(self) -> None:
        del self.report["inventory"]
        self.assertIn("malformed_report", self._rejections(self.report))

    def test_wrong_schema_version_is_malformed(self) -> None:
        self.report["schemaVersion"] = 2
        self.assertIn("malformed_report", self._rejections(self.report))

    def test_wrong_phase_order_is_partial(self) -> None:
        self.report["phases"][0], self.report["phases"][1] = (
            self.report["phases"][1], self.report["phases"][0])
        self.assertIn("partial_report", self._rejections(self.report))

    def test_unknown_phase_status_is_partial(self) -> None:
        self.report["phases"][2]["status"] = "sort_of_done"
        self.assertIn("partial_report", self._rejections(self.report))

    def test_failed_phase_without_failure_record_is_partial(self) -> None:
        self.report["phases"][2]["status"] = "failed"
        self.assertIn("partial_report", self._rejections(self.report))

    def test_mismatched_profile_is_rejected(self) -> None:
        self.report["profile"] = "G70"
        self.assertIn("mismatched_profile", self._rejections(self.report))

    def test_mismatched_source_is_rejected(self) -> None:
        self.report["scenePath"] = r"C:\somewhere\else.ramses"
        self.assertIn("mismatched_source", self._rejections(self.report))

    def test_escaped_frame_path_is_rejected(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            frame={"outcome": "readback_complete", "classification": "black",
                   "file": r"..\evil.png", "drivenInputs": 1})
        self.assertIn("escaped_path", self._rejections(report))

    def test_non_object_frame_fails_closed(self) -> None:
        report = _native_report(profile="G45", scene_path=self.scene_path)
        report["frame"] = "i-am-not-a-dict-or-null"
        self.assertIn("malformed_report", self._rejections(report))
        report["frame"] = ["outcome_list_smuggle"]
        self.assertIn("malformed_report", self._rejections(report))

    def test_unknown_frame_outcome_fails_closed(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            frame={"outcome": "sort_of_rendered", "classification": "black",
                   "file": "first-frame.png", "drivenInputs": 1})
        self.assertIn("malformed_report", self._rejections(report))

    def test_unknown_frame_classification_fails_closed(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            frame={"outcome": "readback_complete", "classification": "greenish",
                   "file": "first-frame.png", "drivenInputs": 1})
        self.assertIn("malformed_report", self._rejections(report))

    def test_frame_with_unknown_key_fails_closed(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            frame={"outcome": "readback_complete", "classification": "content",
                   "file": "first-frame.png", "drivenInputs": 1,
                   "smuggled_payload": {"anything": [1, 2, 3]}})
        self.assertIn("malformed_report", self._rejections(report))

    def test_failure_reason_cannot_spoof_a_reserved_outcome(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            failure={"phase": "scene_load", "reason": "completed"})
        self.assertIn("partial_report", self._rejections(report))

    def test_failure_reason_outside_whitelist_is_rejected(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            failure={"phase": "scene_load", "reason": "totally_made_up_reason"})
        self.assertIn("partial_report", self._rejections(report))

    def test_failure_phase_outside_whitelist_is_rejected(self) -> None:
        report = _native_report(
            profile="G45", scene_path=self.scene_path,
            failure={"phase": "scene_load", "reason": "scene_unavailable"})
        report["failure"]["phase"] = "not_a_real_phase"
        self.assertIn("partial_report", self._rejections(report))


class RamsesProbeRunnerLaunchTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name)
        self.scene = self.root / "source" / "export" / "exported.ramses"
        _write_text(self.scene, "synthetic-scene-bytes")
        self.output_root = self.root / "out"
        self.output_root.mkdir()

    def _helper(self, body: str) -> tuple[Path, str]:
        helper = self.root / "fake_probe.bat"
        helper.write_text(body, encoding="ascii")
        return helper, sha256_file(helper)

    def _request(self, helper: Path, digest: str) -> ProbeRunRequest:
        return ProbeRunRequest(
            profile="G45",
            scene_path=self.scene,
            output_root=self.output_root,
            helper_path=helper,
            helper_sha256=digest,
        )

    def _success_helper(self) -> tuple[Path, str]:
        report = _native_report(profile="G45", scene_path=str(self.scene))
        fixture = self.root / "report-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            f'echo %* > "{self.root / "captured-args.txt"}"\r\n'
            "exit /b 0\r\n"
        )
        return self._helper(body)

    def test_untrusted_helper_never_launches(self) -> None:
        helper, _ = self._success_helper()
        result = run_probe(self._request(helper, "f" * 64))
        self.assertEqual(result.outcome, "untrusted_helper")
        self.assertFalse((self.root / "captured-args.txt").exists())
        self.assertIsNone(result.native_report)

    def test_stale_report_blocks_launch(self) -> None:
        helper, digest = self._success_helper()
        _write_text(self.output_root / NATIVE_REPORT_NAME, "{}")
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "stale_report")
        self.assertFalse((self.root / "captured-args.txt").exists())

    def test_successful_run_produces_completed_evidence(self) -> None:
        helper, digest = self._success_helper()
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "completed")
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(result.rejections, ())
        captured = (self.root / "captured-args.txt").read_text(encoding="ascii")
        self.assertIn("--profile G45", captured)
        self.assertIn("--backend opengl", captured)
        evidence = json.loads(
            (self.output_root / EVIDENCE_FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(evidence["schemaVersion"], 1)
        self.assertEqual(evidence["outcome"], "completed")
        self.assertEqual(evidence["digests"]["sceneBefore"], evidence["digests"]["sceneAfter"])
        self.assertEqual(evidence["nativeReport"]["profile"], "G45")
        self.assertEqual(
            set(evidence.keys()),
            {"schemaVersion", "banner", "request", "helper", "digests", "helperExitCode",
             "outcome", "rejections", "nativeReport"},
        )

    def test_helper_crash_is_not_a_validation_finding(self) -> None:
        helper, digest = self._helper(
            "@echo off\r\necho probing >&2\r\necho phase metadata\r\nexit /b 3\r\n")
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "helper_crash")
        self.assertEqual(result.exit_code, 3)
        evidence = json.loads(
            (self.output_root / EVIDENCE_FILE_NAME).read_text(encoding="utf-8"))
        self.assertEqual(evidence["outcome"], "helper_crash")
        self.assertIsNone(evidence["nativeReport"])
        stdout_log = (self.output_root / "stdout.log").read_text(encoding="utf-8", errors="replace")
        stderr_log = (self.output_root / "stderr.log").read_text(encoding="utf-8", errors="replace")
        self.assertIn("phase metadata", stdout_log)
        self.assertIn("probing", stderr_log)

    def test_console_streams_are_capped(self) -> None:
        helper, digest = self._helper(
            "@echo off\r\nfor /l %%i in (1,1,9000) do echo the quick brown fox pads the console stream\r\n"
            "exit /b 3\r\n")
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "helper_crash")
        self.assertLessEqual((self.output_root / "stdout.log").stat().st_size, 256 * 1024)

    def test_classified_failure_is_not_a_helper_crash(self) -> None:
        report = _native_report(
            profile="G45", scene_path=str(self.scene),
            failure={"phase": "scene_load", "reason": "scene_unavailable"})
        fixture = self.root / "failure-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            "exit /b 65\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "scene_unavailable")
        self.assertNotEqual(result.outcome, "helper_crash")
        self.assertEqual(result.exit_code, 65)

    def test_findings_with_exit_zero_stay_completed(self) -> None:
        report = _native_report(profile="G45", scene_path=str(self.scene))
        report["findings"] = [{
            "severity": "error", "message": "meshnode does not have an appearance set",
            "objectType": "MeshNode", "objectId": 7, "objectName": "",
            "sourceClass": "scene", "identity": "MeshNode#7|scene|error|38:meshnode",
        }]
        fixture = self.root / "findings-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "completed")

    def test_source_mutation_is_rejected(self) -> None:
        report = _native_report(profile="G45", scene_path=str(self.scene))
        fixture = self.root / "mutation-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            f'echo mutated >> "{self.scene}"\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "source_mutated")
        self.assertIn("source_mutated", result.rejections)

    def test_mismatched_report_profile_is_rejected_end_to_end(self) -> None:
        report = _native_report(profile="G70", scene_path=str(self.scene))
        fixture = self.root / "wrong-profile-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "mismatched_profile")

    def test_missing_report_with_exit_zero_is_helper_crash(self) -> None:
        helper, digest = self._helper("@echo off\r\nexit /b 0\r\n")
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "helper_crash")

    def test_output_root_inside_source_tree_is_rejected(self) -> None:
        helper, digest = self._success_helper()
        nested_output = self.scene.parent / "nested-out"
        nested_output.mkdir()
        request = ProbeRunRequest(
            profile="G45",
            scene_path=self.scene,
            output_root=nested_output,
            helper_path=helper,
            helper_sha256=digest,
        )
        result = run_probe(request)
        self.assertEqual(result.outcome, "roots_not_disjoint")
        self.assertFalse((self.root / "captured-args.txt").exists())

    def test_worktree_status_mutation_is_rejected(self) -> None:
        import subprocess as sp
        worktree = self.root / "wt"
        worktree.mkdir()
        for command in (["git", "init", "-q"], ["git", "add", "-A"]):
            sp.run(command, cwd=worktree, check=False, capture_output=True)
        scene = worktree / "export" / "exported.ramses"
        _write_text(scene, "worktree-scene-bytes")

        report = _native_report(profile="G45", scene_path=str(scene))
        fixture = self.root / "wt-fixture.json"
        _write_text(fixture, json.dumps(report))
        sibling = worktree / "untracked-sibling.txt"
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            f'echo dirty > "{sibling}"\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        request = ProbeRunRequest(
            profile="G45",
            scene_path=scene,
            output_root=self.output_root,
            helper_path=helper,
            helper_sha256=digest,
        )
        result = run_probe(request)
        self.assertEqual(result.outcome, "worktree_status_changed")
        evidence = json.loads(
            (self.output_root / EVIDENCE_FILE_NAME).read_text(encoding="utf-8"))
        self.assertIn("worktreeStatusBefore", evidence["digests"])

    def test_output_inside_scene_repo_does_not_self_trigger_worktree_guard(self) -> None:
        import subprocess as sp
        worktree = self.root / "wt2"
        worktree.mkdir()
        sp.run(["git", "init", "-q"], cwd=worktree, check=False, capture_output=True)
        scene = worktree / "export" / "exported.ramses"
        _write_text(scene, "worktree-scene-bytes")
        output_root = worktree / "probe-out"
        output_root.mkdir()

        report = _native_report(profile="G45", scene_path=str(scene))
        fixture = self.root / "wt2-fixture.json"
        _write_text(fixture, json.dumps(report))
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        request = ProbeRunRequest(
            profile="G45",
            scene_path=scene,
            output_root=output_root,
            helper_path=helper,
            helper_sha256=digest,
        )
        result = run_probe(request)
        self.assertEqual(result.outcome, "completed")

    def test_scene_inside_output_root_is_rejected(self) -> None:
        helper, digest = self._success_helper()
        nested_scene = self.output_root / "exported.ramses"
        _write_text(nested_scene, "scene-inside-output")
        request = ProbeRunRequest(
            profile="G45",
            scene_path=nested_scene,
            output_root=self.output_root,
            helper_path=helper,
            helper_sha256=digest,
        )
        result = run_probe(request)
        self.assertEqual(result.outcome, "roots_not_disjoint")

    def test_helper_renaming_tracked_source_into_output_root_is_caught(self) -> None:
        import subprocess as sp
        worktree = self.root / "wt3"
        worktree.mkdir()
        sp.run(["git", "init", "-q"], cwd=worktree, check=False, capture_output=True)
        sp.run(["git", "config", "user.email", "t@example.com"], cwd=worktree,
               check=False, capture_output=True)
        sp.run(["git", "config", "user.name", "Test"], cwd=worktree,
               check=False, capture_output=True)
        scene = worktree / "export" / "exported.ramses"
        _write_text(scene, "worktree-scene-bytes")
        secret = worktree / "export" / "secret_source.txt"
        _write_text(secret, "a tracked source file that must not disappear silently")
        output_root = worktree / "probe-out"
        output_root.mkdir()
        sp.run(["git", "add", "-A"], cwd=worktree, check=False, capture_output=True)
        sp.run(["git", "commit", "-q", "-m", "seed"], cwd=worktree, check=False, capture_output=True)

        report = _native_report(profile="G45", scene_path=str(scene))
        fixture = self.root / "wt3-fixture.json"
        _write_text(fixture, json.dumps(report))
        # The helper moves a tracked source file OUT of the source tree into the probe output
        # root and stages it, producing a single `R export/... -> probe-out/...` rename line.
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            f'git -C "{worktree}" mv export/secret_source.txt probe-out/secret_source.txt\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        request = ProbeRunRequest(
            profile="G45",
            scene_path=scene,
            output_root=output_root,
            helper_path=helper,
            helper_sha256=digest,
        )
        result = run_probe(request)
        self.assertEqual(result.outcome, "worktree_status_changed")
        self.assertFalse(secret.exists())

    def test_helper_swapped_after_hash_check_is_rejected(self) -> None:
        report = _native_report(profile="G45", scene_path=str(self.scene))
        fixture = self.root / "swap-fixture.json"
        _write_text(fixture, json.dumps(report))
        # The helper writes a valid report, then rewrites its own on-disk bytes before exiting,
        # so its digest no longer matches the pinned hash that was verified before launch.
        body = (
            "@echo off\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            'echo tampered-after-launch >> "%~f0"\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "untrusted_helper")

    def test_helper_is_fully_awaited_no_detached_child(self) -> None:
        marker = self.root / "helper-finished.marker"
        report = _native_report(profile="G45", scene_path=str(self.scene))
        fixture = self.root / "await-fixture.json"
        _write_text(fixture, json.dumps(report))
        # The helper sleeps, then writes a completion marker as its final action. Because the
        # runner must block on the child (no detach/orphan), the marker is always present by
        # the time run_probe returns.
        body = (
            "@echo off\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            f'copy /Y "{fixture}" "{self.output_root / NATIVE_REPORT_NAME}" >nul\r\n'
            f'echo done > "{marker}"\r\n'
            "exit /b 0\r\n"
        )
        helper, digest = self._helper(body)
        result = run_probe(self._request(helper, digest))
        self.assertEqual(result.outcome, "completed")
        self.assertTrue(marker.is_file())
        self.assertEqual(marker.read_text(encoding="ascii").strip(), "done")


if __name__ == "__main__":
    unittest.main()

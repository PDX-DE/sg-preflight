from __future__ import annotations

import re
import tempfile
from pathlib import Path
import unittest


EXPECTED_GATE_IDS = (
    "context",
    "asset",
    "interface",
    "variants",
    "visual",
    "review",
    "delivery",
)

EXPECTED_TOP_LEVEL_KEYS = {
    "schemaVersion",
    "scopeLabel",
    "selectedProfile",
    "profileOptions",
    "contextFields",
    "gates",
    "selectedGateId",
    "latestLocalRun",
    "nextAction",
    "activity",
    "readOnly",
    "isApproval",
}


class TestQaHubSnapshot(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    @staticmethod
    def _action_descriptor(action_id: str = "sgfx_preflight__g45") -> dict[str, object]:
        return {
            "capabilityId": "diagnostic.run",
            "label": "Run local QA checks",
            "enabled": True,
            "actionId": action_id,
            "effectClass": "tool_output_only",
        }

    @staticmethod
    def _record(
        *,
        status: str = "completed",
        errors: int = 0,
        warnings: int = 0,
        info: int = 0,
        profile_id: str = "G45",
        action_id: str = "sgfx_preflight__g45",
        kind: str = "sgfx_preflight",
    ) -> dict[str, object]:
        return {
            "run_id": "action-001",
            "action_id": action_id,
            "kind": kind,
            "profile_id": profile_id,
            "status": status,
            "created_at_utc": "2026-07-12T20:00:00+00:00",
            "completed_at_utc": "2026-07-12T20:01:00+00:00" if status == "completed" else None,
            "summary": {
                "errors": errors,
                "warnings": warnings,
                "info": info,
                "child_run_id": "action-001-preflight",
            },
            "error_message": RuntimeError(r"private C:\operator\trace.txt"),
            "paths": {"summary": r"C:\operator\summary.json"},
        }

    def _snapshot(
        self,
        *,
        selected: str = "G45",
        actions: list[dict[str, object]] | None = None,
        action_records: list[object] | None = None,
        run_records: list[object] | None = None,
        activity: list[object] | None = None,
    ) -> dict[str, object]:
        from sg_preflight.qa_hub import build_qa_hub_snapshot

        return build_qa_hub_snapshot(
            workspace=self.root,
            profile_options=[
                {"id": "G45", "label": "BMW G45"},
                {"id": "G70", "label": "BMW G70"},
            ],
            selected_profile_id=selected,
            actions=list(actions if actions is not None else [self._action_descriptor()]),
            action_records=list(action_records or []),
            run_records=list(run_records or []),
            activity=list(activity or []),
        )

    def assertSafe(self, value: object) -> None:
        forbidden_key = re.compile(r"(?i)(command|executable|environment|credential|password|secret|token|path|url)")
        windows_path = re.compile(r"(?i)(?:[A-Z]:[\\/]|\\\\[^\\/\s]+[\\/])")

        def visit(item: object) -> None:
            self.assertNotIsInstance(item, BaseException)
            if isinstance(item, dict):
                for key, child in item.items():
                    self.assertIsInstance(key, str)
                    self.assertIsNone(forbidden_key.search(key), msg=key)
                    visit(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    visit(child)
            elif isinstance(item, str):
                self.assertNotIn("://", item)
                self.assertIsNone(windows_path.search(item), msg=item)
                self.assertFalse(item.startswith("/"), msg=item)

        visit(value)

    def test_empty_selection_has_exact_contract_and_no_runnable_action(self) -> None:
        snapshot = self._snapshot(selected="", actions=[], activity=[])

        self.assertEqual(set(snapshot), EXPECTED_TOP_LEVEL_KEYS)
        self.assertEqual(snapshot["schemaVersion"], 1)
        self.assertEqual(snapshot["selectedProfile"], {})
        self.assertEqual(snapshot["selectedGateId"], "context")
        self.assertEqual(snapshot["latestLocalRun"], {})
        self.assertEqual(snapshot["nextAction"], {
            "kind": "select_profile",
            "label": "Choose profile",
            "routeId": "",
            "capabilityId": "",
            "actionId": "",
        })
        self.assertEqual(tuple(gate["id"] for gate in snapshot["gates"]), EXPECTED_GATE_IDS)
        self.assertSafe(snapshot)

    def test_available_action_is_the_only_not_run_primary_action(self) -> None:
        snapshot = self._snapshot()

        states = {gate["id"]: gate["state"] for gate in snapshot["gates"]}
        self.assertEqual(states["context"], "available")
        self.assertEqual(states["asset"], "not_run")
        self.assertEqual(snapshot["nextAction"], {
            "kind": "run",
            "label": "Run local QA checks",
            "routeId": "",
            "capabilityId": "diagnostic.run",
            "actionId": "sgfx_preflight__g45",
        })

    def test_queued_and_running_records_wait_without_an_effect_identity(self) -> None:
        for status in ("queued", "running"):
            with self.subTest(status=status):
                snapshot = self._snapshot(action_records=[self._record(status=status)])
                asset = next(gate for gate in snapshot["gates"] if gate["id"] == "asset")
                self.assertEqual(asset["state"], status)
                self.assertEqual(snapshot["nextAction"]["kind"], "wait")
                self.assertEqual(snapshot["nextAction"]["capabilityId"], "")

    def test_completed_zero_findings_is_passed_but_not_overall_approval(self) -> None:
        snapshot = self._snapshot(action_records=[self._record(info=3)])

        states = {gate["id"]: gate["state"] for gate in snapshot["gates"]}
        self.assertEqual(states["asset"], "passed")
        self.assertEqual(states["interface"], "external")
        self.assertEqual(states["review"], "human_review")
        self.assertEqual(states["delivery"], "human_review")
        self.assertEqual(snapshot["nextAction"]["routeId"], "api-version-coverage")
        self.assertNotIn("overallStatus", snapshot)
        self.assertFalse(snapshot["isApproval"])
        self.assertNotIn("percent", repr(snapshot).casefold())

    def test_completed_warnings_and_errors_are_findings(self) -> None:
        for errors, warnings in ((0, 2), (3, 0), (1, 2)):
            with self.subTest(errors=errors, warnings=warnings):
                snapshot = self._snapshot(
                    action_records=[self._record(errors=errors, warnings=warnings, info=1)]
                )
                states = {gate["id"]: gate["state"] for gate in snapshot["gates"]}
                self.assertEqual(states["asset"], "findings")
                self.assertEqual(states["review"], "human_review")
                self.assertEqual(snapshot["nextAction"]["kind"], "review")
                self.assertEqual(snapshot["nextAction"]["routeId"], "full-qa-pass")
                self.assertNotIn("overallStatus", snapshot)

    def test_execution_failure_retries_only_the_exact_audited_action(self) -> None:
        snapshot = self._snapshot(action_records=[self._record(status="failed")])

        asset = next(gate for gate in snapshot["gates"] if gate["id"] == "asset")
        self.assertEqual(asset["state"], "failed")
        self.assertEqual(snapshot["nextAction"], {
            "kind": "retry",
            "label": "Retry local QA checks",
            "routeId": "",
            "capabilityId": "diagnostic.run",
            "actionId": "sgfx_preflight__g45",
        })
        self.assertNotIn("private", repr(snapshot).casefold())

    def test_malformed_and_wrong_scope_records_never_reduce_truth(self) -> None:
        malformed = [
            object(),
            {"kind": "sgfx_preflight", "profile_id": "G45", "action_id": "wrong"},
            self._record(kind="profile_stack"),
            self._record(profile_id="G70", action_id="sgfx_preflight__g70"),
            self._record(errors=-1),
            self._record(warnings="two"),
        ]
        snapshot = self._snapshot(action_records=malformed)

        asset = next(gate for gate in snapshot["gates"] if gate["id"] == "asset")
        self.assertEqual(asset["state"], "not_run")
        self.assertEqual(snapshot["latestLocalRun"], {})
        self.assertEqual(snapshot["nextAction"]["kind"], "run")

    def test_snapshot_is_bounded_sanitized_and_renders_copy_ready_evidence(self) -> None:
        from sg_preflight.qa_hub import render_qa_evidence_summary

        activity = [
            {"label": f"Entry {index}", "status": "recorded", "detail": f"Local event {index}"}
            for index in range(8)
        ]
        activity.extend(
            [
                {"label": "Unsafe", "status": "failed", "detail": r"C:\private\result.json"},
                {"label": "Unsafe", "status": "failed", "detail": "https://private.invalid"},
            ]
        )
        snapshot = self._snapshot(
            action_records=[self._record(warnings=2, info=1)],
            run_records=[RuntimeError("raw exception")] * 20,
            activity=activity,
        )

        self.assertEqual(len(snapshot["activity"]), 5)
        evidence = snapshot["latestLocalRun"]["evidenceSummary"]
        self.assertEqual(evidence, render_qa_evidence_summary(snapshot))
        self.assertIn("Profile: G45", evidence)
        self.assertIn("2 warnings", evidence)
        self.assertIn("Next: Review local findings", evidence)
        self.assertSafe(snapshot)


if __name__ == "__main__":
    unittest.main()

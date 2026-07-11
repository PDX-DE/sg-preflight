from __future__ import annotations

from dataclasses import FrozenInstanceError
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from unittest import mock


PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None


class TestUiCapabilityInventory(unittest.TestCase):
    def test_inventory_is_exact_frozen_and_audited(self) -> None:
        from sg_preflight.desktop.ui_capabilities import (
            ARTIFACT_REVEAL_SURFACE_IDS,
            UI_CAPABILITIES,
            get_ui_capability,
        )

        expected = {
            "profile.select": "session_state",
            "page.navigate": "session_state",
            "page.refresh": "read_only",
            "artifact.reveal": "read_only",
            "diagnostic.run": "tool_output_only",
            "manual_review.record": "tool_output_only",
            "operator_handoff.record": "tool_output_only",
            "grafiks.launch": "external_process",
        }
        self.assertEqual(
            {item.capability_id: item.effect_class.value for item in UI_CAPABILITIES},
            expected,
        )
        self.assertTrue(all(item.input_schema is not None for item in UI_CAPABILITIES))
        self.assertEqual(
            get_ui_capability("artifact.reveal").owning_pages,
            ARTIFACT_REVEAL_SURFACE_IDS,
        )
        self.assertEqual(len(UI_CAPABILITIES), 8)
        self.assertTrue(all(not hasattr(item, "__dict__") for item in UI_CAPABILITIES))
        with self.assertRaises(FrozenInstanceError):
            UI_CAPABILITIES[0].capability_id = "changed"
        with self.assertRaises(KeyError):
            get_ui_capability("unknown.command")

    def test_concrete_diagnostic_audit_exposes_only_delivery_checklist(self) -> None:
        from sg_preflight.desktop.ui_capabilities import (
            ALLOWED_DIAGNOSTIC_KINDS,
            audit_ui_diagnostic_action,
        )
        from sg_preflight.qa_operator_actions import OperatorAction

        self.assertEqual(
            ALLOWED_DIAGNOSTIC_KINDS,
            frozenset(
                {
                    "daily_live_matrix",
                    "profile_stack",
                    "repo_checker",
                    "unused_resources",
                    "delivery_checklist",
                    "scene_check",
                    "bmw_screenshot_smoke",
                }
            ),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            project = source / "Cars" / "G65"
            output = root / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            output.mkdir(parents=True)
            actions = [
                OperatorAction(
                    action_id=f"{kind}__g65",
                    label=kind,
                    description=kind,
                    kind=kind,
                    scope="profile",
                    ready=True,
                    profile_id="G65",
                    project_root=str(project),
                )
                for kind in sorted(ALLOWED_DIAGNOSTIC_KINDS)
            ]

            audited = {
                action.kind: audit_ui_diagnostic_action(
                    action,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                )
                for action in actions
            }

            self.assertEqual(
                audited,
                {
                    "bmw_screenshot_smoke": False,
                    "daily_live_matrix": False,
                    "delivery_checklist": True,
                    "profile_stack": False,
                    "repo_checker": False,
                    "scene_check": False,
                    "unused_resources": False,
                },
            )
            escaped = actions[2]
            escaped = type(escaped)(
                **{
                    **escaped.__dict__,
                    "project_root": str(root / "sibling"),
                }
            )
            self.assertFalse(
                audit_ui_diagnostic_action(
                    escaped,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                )
            )


class TestArtifactRegistry(unittest.TestCase):
    def test_handles_are_opaque_current_and_revalidated_before_reveal(self) -> None:
        from sg_preflight.desktop.artifact_registry import (
            ArtifactCandidate,
            ArtifactIdentity,
            ArtifactRegistry,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            target = evidence / "report.json"
            target.parent.mkdir()
            target.write_text("{}\n", encoding="utf-8")
            revealed: list[Path] = []
            registry = ArtifactRegistry(
                approved_roots=(evidence,),
                revealer=lambda path: revealed.append(path),
            )
            identity = ArtifactIdentity(7, "G65", "delivery-checklist")
            public = registry.accept(
                identity,
                (
                    ArtifactCandidate(
                        target=target,
                        approved_root=evidence,
                        artifact_type="json",
                        label="Delivery report",
                    ),
                ),
            )

            self.assertEqual(len(public), 1)
            self.assertEqual(set(public[0]), {"artifactId", "label", "type"})
            self.assertEqual(public[0]["label"], "Delivery report")
            self.assertNotIn(str(target), repr(public))
            self.assertNotIn(target.name, public[0]["artifactId"])
            artifact_id = public[0]["artifactId"]
            self.assertFalse(registry.reveal(artifact_id, ArtifactIdentity(8, "G65", "delivery-checklist")))
            self.assertFalse(registry.reveal(artifact_id, ArtifactIdentity(7, "G70", "delivery-checklist")))
            self.assertFalse(registry.reveal(artifact_id, ArtifactIdentity(7, "G65", "risk-score")))
            self.assertTrue(registry.reveal(artifact_id, identity))
            self.assertEqual(revealed, [target.resolve()])
            target.unlink()
            self.assertFalse(registry.reveal(artifact_id, identity))
            registry.clear()
            self.assertFalse(registry.reveal(artifact_id, identity))

    def test_registry_rejects_wrong_roots_types_suffixes_and_link_escapes(self) -> None:
        from sg_preflight.desktop.artifact_registry import (
            ArtifactCandidate,
            ArtifactIdentity,
            ArtifactRegistry,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            sibling = root / "evidence-private"
            evidence.mkdir()
            sibling.mkdir()
            good = evidence / "report.md"
            good.write_text("# report\n", encoding="utf-8")
            executable = evidence / "run.exe"
            executable.write_bytes(b"MZ")
            escaped = sibling / "report.md"
            escaped.write_text("private\n", encoding="utf-8")
            registry = ArtifactRegistry(approved_roots=(evidence,), revealer=lambda _path: None)
            identity = ArtifactIdentity(1, "G65", "delivery-checklist")

            for candidate in (
                ArtifactCandidate(executable, evidence, "file", "Executable"),
                ArtifactCandidate(escaped, evidence, "markdown", "Sibling"),
                ArtifactCandidate(good, sibling, "markdown", "Wrong root"),
                ArtifactCandidate(evidence, evidence, "markdown", "Wrong directory type"),
                ArtifactCandidate(good, evidence, "json", "Wrong artifact type"),
            ):
                with self.subTest(candidate=candidate.label):
                    self.assertEqual(registry.accept(identity, (candidate,)), [])

            link = evidence / "linked.md"
            try:
                link.symlink_to(escaped)
            except (OSError, NotImplementedError):
                pass
            else:
                self.assertEqual(
                    registry.accept(
                        identity,
                        (ArtifactCandidate(link, evidence, "markdown", "Link"),),
                    ),
                    [],
                )
            internal_link = evidence / "internal-linked.md"
            try:
                internal_link.symlink_to(good)
            except (OSError, NotImplementedError):
                pass
            else:
                self.assertEqual(
                    registry.accept(
                        identity,
                        (ArtifactCandidate(internal_link, evidence, "markdown", "Internal link"),),
                    ),
                    [],
                )

    def test_candidate_extraction_is_page_specific_and_keeps_paths_private(self) -> None:
        from sg_preflight.desktop.artifact_registry import extract_artifact_candidates

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            evidence = root / "evidence"
            workbook = evidence / "delivery.xlsx"
            report = evidence / "manual-review.md"
            evidence.mkdir()
            workbook.write_bytes(b"xlsx")
            report.write_text("# review\n", encoding="utf-8")

            delivery = extract_artifact_candidates(
                "delivery-checklist",
                {"payload": {"workbook_path": str(workbook)}},
                approved_roots=(evidence,),
            )
            manual = extract_artifact_candidates(
                "manual-review",
                {"payload": {"markdown_path": str(report)}},
                approved_roots=(evidence,),
            )
            unrelated = extract_artifact_candidates(
                "about",
                {"content": {"workbook_path": str(workbook)}},
                approved_roots=(evidence,),
            )

            self.assertEqual([item.target.resolve() for item in delivery], [workbook.resolve()])
            self.assertEqual([item.target.resolve() for item in manual], [report.resolve()])
            self.assertEqual(unrelated, ())


class TestCapabilityInputValidation(unittest.TestCase):
    def test_effect_text_is_bounded_and_rejects_paths_urls_controls_and_credentials(self) -> None:
        from sg_preflight.desktop.ui_capabilities import validate_effect_text

        self.assertEqual(validate_effect_text("  review complete  ", required=True), "review complete")
        for value in (
            "x" * 1001,
            "line\nfeed",
            r"C:\private\note.txt",
            "/private/note.txt",
            "https://private.invalid/note",
            "token=super-secret",
            "Bearer private-token",
        ):
            with self.subTest(value=value[:20]):
                with self.assertRaises(ValueError):
                    validate_effect_text(value, required=True)
        for value in ("Evidence approved", "Production-ready", "Result verified"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    validate_effect_text(value, required=True, evidence_only=True)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestCapabilityControllerSurface(unittest.TestCase):
    def test_controller_exposes_only_typed_capability_slots(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController

        meta = DesktopController.staticMetaObject
        methods = {
            bytes(meta.method(index).methodSignature()).decode("ascii")
            for index in range(meta.methodOffset(), meta.methodCount())
        }

        for prefix in (
            "invokeCapability(",
            "runDiagnostic(",
            "cancelDiagnostic(",
            "revealArtifact(",
            "recordManualReview(",
            "recordOperatorHandoff(",
            "launchGrafiks(",
        ):
            self.assertTrue(any(method.startswith(prefix) for method in methods), msg=prefix)
        rendered = "\n".join(sorted(methods)).casefold()
        for forbidden in (
            "command",
            "network",
            "setup",
            "install",
            "clone",
            "worktree",
            "credential",
        ):
            self.assertNotIn(forbidden, rendered)


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestCapabilityControllerIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from PySide6.QtCore import QCoreApplication

        cls.application = QCoreApplication.instance() or QCoreApplication([])

    @staticmethod
    def _delivery_page(workbook: Path | None = None) -> dict[str, object]:
        payload: dict[str, object] = {
            "status": "available",
            "data_available": True,
            "summary": "Delivery evidence",
            "checks": [
                {
                    "key": "delivery",
                    "label": "Delivery",
                    "status": "available",
                    "raw_value": "ready",
                }
            ],
        }
        if workbook is not None:
            payload["workbook_path"] = str(workbook)
        return {
            "id": "delivery-checklist",
            "status": "available",
            "data_available": True,
            "summary": "Delivery evidence",
            "payload": payload,
        }

    @staticmethod
    def _full_qa_page() -> dict[str, object]:
        return {
            "id": "full-qa-pass",
            "status": "not_run",
            "data_available": True,
            "summary": "Full QA has not run",
            "payload": {
                "status": "not_run",
                "summary": "Full QA has not run",
                "progress": {"completed_steps": 0, "total_steps": 9, "percent": 0},
                "steps": [],
                "read_only": True,
                "manual_review_required": True,
                "records_operator_verdict": False,
                "is_approval": False,
            },
        }

    @staticmethod
    def _manual_page() -> dict[str, object]:
        return {
            "id": "manual-review",
            "status": "pending",
            "data_available": True,
            "summary": "0/7 steps recorded",
            "payload": {
                "status": "pending",
                "data_available": True,
                "summary": "0/7 steps recorded",
                "steps": [
                    {
                        "id": f"review-{index}",
                        "title": f"Review {index}",
                        "status": "pending",
                        "summary": "Operator review required",
                    }
                    for index in range(1, 8)
                ],
                "read_only": True,
                "manual_review_required": True,
                "records_operator_verdict": True,
                "is_approval": False,
            },
        }

    def test_page_artifacts_use_fresh_opaque_handles_on_cache_hits(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            workbook = workspace / "out" / "delivery" / "delivery.xlsx"
            workbook.parent.mkdir(parents=True)
            workbook.write_bytes(b"xlsx")
            revealed: list[Path] = []
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._delivery_page(workbook)),
                artifact_revealer=lambda path: revealed.append(path),
            )

            self.assertTrue(controller.navigate("delivery-checklist"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            first = controller.currentPayload["artifacts"][0]
            self.assertEqual(set(first), {"artifactId", "label", "type"})
            self.assertNotIn(str(workbook), repr(controller.currentPayload))
            self.assertEqual(
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
                ["page.refresh", "artifact.reveal"],
            )
            self.assertTrue(controller.revealArtifact(first["artifactId"]))
            self.assertEqual(revealed, [workbook.resolve()])

            self.assertTrue(controller.navigate("delivery-checklist"))
            second = controller.currentPayload["artifacts"][0]
            self.assertNotEqual(second["artifactId"], first["artifactId"])
            self.assertFalse(controller.revealArtifact(first["artifactId"]))
            self.assertTrue(controller.revealArtifact(second["artifactId"]))
            controller.shutdown()

    def test_manual_review_effect_validates_current_step_and_republishes(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        recorder = mock.Mock(return_value={"status": "recorded"})
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._manual_page()),
                manual_review_recorder=recorder,
            )
            self.assertTrue(controller.navigate("manual-review"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertIn(
                "manual_review.record",
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
            )
            self.assertFalse(controller.recordManualReview("review-1", "passed", r"C:\private\note.txt"))
            self.assertFalse(controller.recordManualReview("review-1", "passed", "Evidence approved"))
            self.assertFalse(controller.recordManualReview("stale-step", "passed", "Reviewed locally"))
            self.assertTrue(controller.recordManualReview("review-1", "passed", "Reviewed locally"))
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            recorder.assert_called_once_with(
                profile_id="G65",
                workspace=Path(temp_dir).resolve(),
                step_slug="review-1",
                verdict="passed",
                note="Reviewed locally",
                suggested_verdict="",
            )
            self.assertEqual(coordinator.requests[-1][0].operation, "refresh")
            controller.shutdown()

    def test_running_diagnostic_is_single_worker_non_cancellable_and_output_bounded(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            started = threading.Event()
            release = threading.Event()

            class Record:
                paths = {"summary": str(output / "run-1" / "summary.json")}

            def execute(_action: object, _workspace: Path) -> Record:
                started.set()
                release.wait(5)
                return Record()

            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=execute,
            )
            self.assertTrue(controller.navigate("full-qa-pass"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            diagnostic_actions = [
                item for item in controller.currentPayload["actions"]
                if item["capabilityId"] == "diagnostic.run"
            ]
            self.assertEqual([item["actionId"] for item in diagnostic_actions], [action.action_id])
            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertTrue(started.wait(2))
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "running"))
            self.assertFalse(controller.diagnosticCanCancel)
            self.assertFalse(controller.cancelDiagnostic())
            self.assertFalse(controller.runDiagnostic(action.action_id, ["G65"]))
            release.set()
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            self.assertEqual(coordinator.requests[-1][0].operation, "refresh")
            controller.shutdown()

    def test_diagnostic_requires_an_explicit_output_path_contract(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=mock.Mock(return_value=object()),
            )
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertTrue(
                _pump_until(lambda: controller.capabilityState in {"completed", "failed"})
            )
            self.assertEqual(controller.capabilityState, "failed")
            controller.shutdown()

    def test_queued_diagnostic_can_cancel_without_running(self) -> None:
        from concurrent.futures import Future
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        class QueuedExecutor:
            max_workers = 1

            def __init__(self) -> None:
                self.future: Future[object] = Future()
                self.operation: object = None

            def submit(self, operation: object) -> Future[object]:
                self.operation = operation
                return self.future

            def shutdown(self) -> None:
                self.future.cancel()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            executor = QueuedExecutor()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=mock.Mock(),
                effect_executor=executor,
            )
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertTrue(controller.diagnosticCanCancel)
            self.assertTrue(controller.cancelDiagnostic())
            self.assertEqual(controller.capabilityState, "cancelled")
            self.assertTrue(executor.future.cancelled())
            controller.shutdown()

    def test_handoff_effect_rejects_sensitive_text_and_records_current_profile(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        page = {
            "id": "operator-handoff",
            "status": "not_run",
            "data_available": False,
            "summary": "No handoff recorded",
            "payload": {
                "status": "not_run",
                "data_available": False,
                "summary": "No handoff recorded",
                "handoff_items": [],
                "read_only": True,
                "manual_review_required": True,
                "records_operator_verdict": False,
                "is_approval": False,
            },
        }
        recorder = mock.Mock(return_value={"status": "recorded"})
        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=page),
                operator_handoff_recorder=recorder,
            )
            controller.navigate("operator-handoff")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertFalse(
                controller.recordOperatorHandoff(
                    "Stopped after review",
                    "https://private.invalid/next",
                    "",
                )
            )
            self.assertTrue(
                controller.recordOperatorHandoff(
                    "Stopped after review",
                    "Continue local evidence review",
                    "No external action taken",
                )
            )
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            recorder.assert_called_once_with(
                workspace=Path(temp_dir).resolve(),
                profile_id="G65",
                stopping_point="Stopped after review",
                next_step="Continue local evidence review",
                note="No external action taken",
            )
            controller.shutdown()

    def test_unaudited_diagnostic_is_rejected_before_effect_submission(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="repo_checker__g65",
                label="Repo checker",
                description="Repo checker",
                kind="repo_checker",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            executor = mock.Mock()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=executor,
            )
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertNotIn(
                "diagnostic.run",
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
            )
            self.assertFalse(controller.runDiagnostic(action.action_id, ["G65"]))
            executor.assert_not_called()
            self.assertFalse(output.exists())
            controller.shutdown()

    def test_diagnostic_output_root_must_stay_beneath_workspace_output(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            escaped_output = source / "generated"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            effect_executor = mock.Mock()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=escaped_output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=mock.Mock(),
                effect_executor=effect_executor,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertFalse(controller.runDiagnostic(action.action_id, ["G65"]))
            effect_executor.submit.assert_not_called()
            self.assertFalse(escaped_output.exists())

    def test_diagnostic_profiles_are_canonical_before_action_lookup(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            action_getter = mock.Mock(return_value=action)
            effect_executor = mock.Mock()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=action_getter,
                action_executor=mock.Mock(),
                effect_executor=effect_executor,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertFalse(controller.runDiagnostic(action.action_id, ["G65", "../G70"]))
            action_getter.assert_not_called()
            effect_executor.submit.assert_not_called()
            self.assertFalse(output.exists())

    def test_diagnostic_action_profile_must_be_in_the_requested_profiles(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G70"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g70",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G70",
                project_root=str(project),
            )
            effect_executor = mock.Mock()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=mock.Mock(),
                effect_executor=effect_executor,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertFalse(controller.runDiagnostic(action.action_id, ["G65"]))
            effect_executor.submit.assert_not_called()
            self.assertFalse(output.exists())

    def test_busy_diagnostic_rejection_does_not_create_its_output_root(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        started = threading.Event()
        release = threading.Event()

        def record(**_inputs: object) -> dict[str, str]:
            started.set()
            release.wait(5)
            return {"status": "recorded"}

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )

            def load_page(*, page_id: str, **_inputs: object) -> dict[str, object]:
                if page_id == "manual-review":
                    return self._manual_page()
                return self._full_qa_page()

            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=load_page,
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=mock.Mock(),
                manual_review_recorder=record,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("manual-review")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertTrue(controller.recordManualReview("review-1", "passed", "Reviewed locally"))
            self.assertTrue(started.wait(2))

            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            accepted = controller.runDiagnostic(action.action_id, ["G65"])
            output_exists = output.exists()
            release.set()
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            self.assertFalse(accepted)
            self.assertFalse(output_exists)

    def test_cached_diagnostic_page_is_reaudited_before_actions_are_republished(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            coordinator = _FakeTaskCoordinator()

            def load_page(*, page_id: str, **_inputs: object) -> dict[str, object]:
                if page_id == "full-qa-pass":
                    return self._full_qa_page()
                return self._delivery_page()

            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=load_page,
                diagnostic_read_roots=(source,),
                action_lister=lambda _workspace: [action],
            )
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertIn(
                "diagnostic.run",
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
            )

            controller.navigate("delivery-checklist")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            project.rmdir()
            request_count = len(coordinator.requests)

            self.assertTrue(controller.navigate("full-qa-pass"))
            self.assertEqual(len(coordinator.requests), request_count + 1)
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertNotIn(
                "diagnostic.run",
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
            )
            controller.shutdown()

    def test_diagnostic_root_resolution_runs_inside_the_page_worker(self) -> None:
        from sg_preflight.desktop import qt_quick_controller as controller_module
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="delivery_checklist__g65",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
            )
            read_roots = mock.Mock(return_value=(source,))
            output_root = mock.Mock(return_value=output)
            with (
                mock.patch.object(
                    controller_module,
                    "_resolve_diagnostic_read_roots",
                    read_roots,
                ),
                mock.patch.object(
                    controller_module,
                    "_resolve_diagnostic_output_root",
                    output_root,
                ),
            ):
                self.assertTrue(controller.navigate("full-qa-pass"))
                read_roots.assert_not_called()
                output_root.assert_not_called()
                identity, operation = coordinator.requests[-1]
                result = operation()
                read_roots.assert_called_once_with(
                    workspace.resolve(),
                    (source.resolve(),),
                )
                output_root.assert_called_once_with(
                    workspace.resolve(),
                    output.absolute(),
                )
                coordinator.succeed(identity, result)
            controller.shutdown()

    def test_effect_completion_does_not_clear_new_page_artifacts(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        started = threading.Event()
        release = threading.Event()

        def record(**_inputs: object) -> dict[str, str]:
            started.set()
            release.wait(5)
            return {"status": "recorded"}

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            workbook = workspace / "out" / "delivery" / "delivery.xlsx"
            workbook.parent.mkdir(parents=True)
            workbook.write_bytes(b"xlsx")
            coordinator = _FakeTaskCoordinator()

            def load_page(*, page_id: str, **_inputs: object) -> dict[str, object]:
                if page_id == "manual-review":
                    return self._manual_page()
                return self._delivery_page(workbook)

            revealed: list[Path] = []
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=load_page,
                manual_review_recorder=record,
                artifact_revealer=lambda path: revealed.append(path),
            )
            controller.navigate("manual-review")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertTrue(controller.recordManualReview("review-1", "passed", "Reviewed locally"))
            self.assertTrue(started.wait(2))

            controller.navigate("delivery-checklist")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            artifact = controller.currentPayload["artifacts"][0]

            release.set()
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            self.assertEqual(controller.currentPayload["artifacts"], [artifact])
            self.assertTrue(controller.revealArtifact(artifact["artifactId"]))
            self.assertEqual(revealed, [workbook.resolve()])
            controller.shutdown()

    def test_effect_completion_does_not_refresh_a_new_generation_of_the_same_page(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        started = threading.Event()
        release = threading.Event()

        def record(**_inputs: object) -> dict[str, str]:
            started.set()
            release.wait(5)
            return {"status": "recorded"}

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._manual_page()),
                manual_review_recorder=record,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("manual-review")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertTrue(controller.recordManualReview("review-1", "passed", "Reviewed locally"))
            self.assertTrue(started.wait(2))

            self.assertTrue(controller.navigate("manual-review"))
            current_payload = dict(controller.currentPayload)
            request_count = len(coordinator.requests)
            release.set()
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))

            self.assertEqual(len(coordinator.requests), request_count)
            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.currentPayload, current_payload)


class TestCapabilityQmlBindings(unittest.TestCase):
    def test_artifact_visibility_is_always_a_boolean(self) -> None:
        qml = (
            Path(__file__).resolve().parents[1]
            / "sg_preflight"
            / "desktop"
            / "qml"
            / "components"
            / "PageFrame.qml"
        ).read_text(encoding="utf-8")

        self.assertIn('visible: Boolean(root.pageState === "ready"', qml)
        self.assertNotIn(
            'visible: root.pageState === "ready" && root.page.artifacts && root.page.artifacts.length > 0',
            qml,
        )

    def test_qml_binds_only_typed_capabilities_and_artifact_handles(self) -> None:
        root = Path(__file__).resolve().parents[1] / "sg_preflight" / "desktop" / "qml"
        main = (root / "Main.qml").read_text(encoding="utf-8")
        page_frame = (root / "components" / "PageFrame.qml").read_text(encoding="utf-8")
        workflow = (root / "renderers" / "WorkflowRenderer.qml").read_text(encoding="utf-8")
        review = (root / "renderers" / "ReviewRenderer.qml").read_text(encoding="utf-8")

        self.assertIn("desktopController: window.desktopController", main)
        self.assertIn("desktopController.revealArtifact", page_frame)
        self.assertIn('objectName: "artifactRevealControl"', page_frame)
        self.assertIn("controller.runDiagnostic", workflow)
        self.assertIn('objectName: "diagnosticActionControl"', workflow)
        self.assertIn("controller.cancelDiagnostic", workflow)
        self.assertIn('objectName: "cancelDiagnosticControl"', workflow)
        self.assertIn("controller.capabilityState", workflow)
        self.assertIn("controller.capabilityError", workflow)
        self.assertIn("controller.recordOperatorHandoff", workflow)
        self.assertIn('capabilityId === "operator_handoff.record"', workflow)
        self.assertIn("controller.recordManualReview", review)
        self.assertIn('capabilityId === "manual_review.record"', review)
        self.assertIn("selectedStepIndex", review)
        self.assertIn("root.selectedStepIndex = reviewDelegate.index", review)
        self.assertNotIn("command", (page_frame + workflow + review).casefold())

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_qml_enables_only_declared_current_capabilities(self) -> None:
        root = Path(__file__).resolve().parents[1]
        qml_root = root / "sg_preflight" / "desktop" / "qml"
        environment = os.environ.copy()
        environment["QT_QPA_PLATFORM"] = "offscreen"
        environment["QSG_RHI_BACKEND"] = "software"
        environment["QT_QUICK_CONTROLS_STYLE"] = "Basic"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [
                sys.executable,
                "-B",
                "-c",
                textwrap.dedent(
                    f"""
                    import json
                    from PySide6.QtCore import QObject, Property, Slot, QUrl
                    from PySide6.QtGui import QGuiApplication
                    from PySide6.QtQml import QQmlComponent, QQmlEngine

                    class Controller(QObject):
                        @Property(str, constant=True)
                        def currentProfileId(self):
                            return "G65"
                        @Property(str, constant=True)
                        def capabilityState(self):
                            return "idle"
                        @Property(str, constant=True)
                        def capabilityError(self):
                            return ""
                        @Slot(str, list, result=bool)
                        def runDiagnostic(self, _action_id, _profiles):
                            return True
                        @Slot(str, str, str, result=bool)
                        def recordManualReview(self, _step, _verdict, _note):
                            return True
                        @Slot(str, result=bool)
                        def revealArtifact(self, _artifact_id):
                            return True

                    app = QGuiApplication(["sgfx-task11-qml-test"])
                    engine = QQmlEngine()
                    engine.addImportPath({str(qml_root)!r})
                    controller = Controller()
                    item = {{
                        "itemId": "review-1", "sectionId": "main", "label": "Review 1",
                        "value": "Pending", "detail": "", "status": "pending", "expected": "",
                        "actual": "", "diff": "", "source": "", "revision": ""
                    }}
                    base = {{
                        "surfaceId": "manual-review", "rendererKind": "review", "title": "Review",
                        "subtitle": "Review", "status": "pending", "dataAvailable": True,
                        "primaryText": "Review evidence", "visibleItems": [item], "visibleItemCount": 1,
                        "sections": [], "artifacts": [], "provenance": {{}}, "ownershipNote": "Operator owned",
                        "readOnly": True, "isApproval": False, "manualReviewRequired": True,
                        "recordsOperatorVerdict": True,
                        "actions": [{{"capabilityId": "manual_review.record", "label": "Record", "enabled": True,
                                     "actionId": "", "effectClass": "tool_output_only"}}]
                    }}
                    component = QQmlComponent(engine, QUrl.fromLocalFile({str(qml_root / 'renderers' / 'ReviewRenderer.qml')!r}))
                    review = component.createWithInitialProperties({{"page": base, "controller": controller}})
                    if review is None:
                        raise SystemExit(" | ".join(error.toString() for error in component.errors()))
                    review.setProperty("width", 720)
                    review.setProperty("height", 480)
                    app.processEvents()
                    verdict = review.findChild(QObject, "reviewVerdictControl")
                    note = review.findChild(QObject, "reviewNoteControl")
                    record = review.findChild(QObject, "recordManualReviewControl")
                    print(json.dumps({{
                        "verdictEnabled": bool(verdict.property("enabled")),
                        "noteReadOnly": bool(note.property("readOnly")),
                        "recordEnabled": bool(record.property("enabled")),
                    }}))
                    review.deleteLater()
                    """
                ),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        self.assertEqual(
            __import__("json").loads(result.stdout),
            {"verdictEnabled": True, "noteReadOnly": False, "recordEnabled": True},
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
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
        self.assertEqual(
            get_ui_capability("diagnostic.run").owning_pages,
            ("home", "full-qa-pass"),
        )
        self.assertEqual(len(UI_CAPABILITIES), 8)
        self.assertTrue(all(not hasattr(item, "__dict__") for item in UI_CAPABILITIES))
        with self.assertRaises(FrozenInstanceError):
            UI_CAPABILITIES[0].capability_id = "changed"
        with self.assertRaises(KeyError):
            get_ui_capability("unknown.command")

    def test_concrete_diagnostic_audit_is_page_profile_and_path_exact(self) -> None:
        from sg_preflight.desktop import ui_capabilities as capability_module
        from sg_preflight.desktop.ui_capabilities import (
            ALLOWED_DIAGNOSTIC_KINDS,
            audit_ui_diagnostic_action,
        )
        from sg_preflight.qa_operator_actions import OperatorAction

        self.assertEqual(
            ALLOWED_DIAGNOSTIC_KINDS,
            frozenset({"sgfx_preflight", "delivery_checklist"}),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            project = source / "Cars" / "G45"
            output = root / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            output.mkdir(parents=True)
            preflight = OperatorAction(
                action_id="sgfx_preflight__g45",
                label="Run local QA checks",
                description="Four deterministic packs",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )
            delivery = OperatorAction(
                action_id="delivery_checklist__g45",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )

            self.assertTrue(
                audit_ui_diagnostic_action(
                    preflight,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="home",
                )
            )
            self.assertTrue(
                audit_ui_diagnostic_action(
                    delivery,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="full-qa-pass",
                )
            )
            self.assertFalse(
                audit_ui_diagnostic_action(
                    delivery,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="batch-full-qa-pass",
                )
            )
            self.assertFalse(
                audit_ui_diagnostic_action(
                    delivery,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="home",
                )
            )
            self.assertTrue(
                audit_ui_diagnostic_action(
                    preflight,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="full-qa-pass",
                )
            )

            rejected = [
                OperatorAction(
                    action_id=f"{kind}__g45",
                    label=kind,
                    description=kind,
                    kind=kind,
                    scope="profile",
                    ready=True,
                    profile_id="G45",
                    project_root=str(project),
                )
                for kind in (
                    "profile_stack",
                    "repo_checker",
                    "unused_resources",
                    "scene_check",
                    "bmw_screenshot_smoke",
                )
            ]
            rejected.extend(
                [
                    replace(preflight, action_id="sgfx_preflight__g45/escape"),
                    replace(preflight, profile_id="../G45"),
                    replace(preflight, profile_id="G65", action_id="sgfx_preflight__g65"),
                    replace(preflight, scope="workspace"),
                    replace(preflight, project_root=""),
                    replace(preflight, project_root=str(root / "missing")),
                    replace(preflight, ready=False),
                ]
            )
            escaped_project = root / "sibling" / "G45"
            escaped_project.mkdir(parents=True)
            rejected.append(replace(preflight, project_root=str(escaped_project)))

            for action in rejected:
                with self.subTest(action=action.action_id, kind=action.kind):
                    self.assertFalse(
                        audit_ui_diagnostic_action(
                            action,
                            read_only_roots=(source,),
                            output_root=output,
                            allowed_output_root=root / "out",
                            expected_profile_id="G45",
                            owning_page_id="home",
                        )
                    )

            self.assertFalse(
                audit_ui_diagnostic_action(
                    preflight,
                    read_only_roots=(source,),
                    output_root=root / "escaped-output",
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="home",
                )
            )
            with mock.patch.object(capability_module, "_is_reparse_or_link", return_value=True):
                self.assertFalse(
                    audit_ui_diagnostic_action(
                        preflight,
                        read_only_roots=(source,),
                        output_root=output,
                        allowed_output_root=root / "out",
                        expected_profile_id="G45",
                        owning_page_id="home",
                    )
                )

    def test_full_qa_pages_bind_actions_to_the_selected_profile(self) -> None:
        from sg_preflight.desktop.ui_capabilities import audit_ui_diagnostic_action
        from sg_preflight.qa_operator_actions import OperatorAction

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            project = source / "Cars" / "G45"
            output = root / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            output.mkdir(parents=True)
            preflight = OperatorAction(
                action_id="sgfx_preflight__g45",
                label="Run local QA checks",
                description="Four deterministic packs",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )
            delivery = OperatorAction(
                action_id="delivery_checklist__g45",
                label="Delivery readiness",
                description="Local delivery readiness",
                kind="delivery_checklist",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )

            self.assertTrue(
                audit_ui_diagnostic_action(
                    preflight,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="full-qa-pass",
                )
            )
            self.assertFalse(
                audit_ui_diagnostic_action(
                    preflight,
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="batch-full-qa-pass",
                )
            )
            for action in (preflight, delivery):
                self.assertFalse(
                    audit_ui_diagnostic_action(
                        action,
                        read_only_roots=(source,),
                        output_root=output,
                        allowed_output_root=root / "out",
                        expected_profile_id="G65",
                        owning_page_id="full-qa-pass",
                    )
                )
            self.assertFalse(
                audit_ui_diagnostic_action(
                    replace(preflight, ready=False),
                    read_only_roots=(source,),
                    output_root=output,
                    allowed_output_root=root / "out",
                    expected_profile_id="G45",
                    owning_page_id="full-qa-pass",
                )
            )

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_home_publishes_only_selected_profile_preflight(self) -> None:
        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        # A bare QCoreApplication would poison later in-process Qt Quick tests: the runtime
        # requires a graphical application and Qt allows only one instance per process.
        application = QCoreApplication.instance() or QGuiApplication([])
        self.assertIsNotNone(application)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G45"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            preflight = OperatorAction(
                action_id="sgfx_preflight__g45",
                label="Run local QA checks",
                description="Four deterministic packs",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )
            broad = replace(
                preflight,
                action_id="qa_stack__g45",
                label="Run recommended QA stack",
                kind="profile_stack",
            )
            action_lister = mock.Mock(return_value=[preflight, broad])

            class Record:
                paths = {"summary": str(output / "run-1" / "summary.json")}

            action_executor = mock.Mock(return_value=Record())

            def shell_loader(*, profile_id: str, **_kwargs: object) -> dict[str, object]:
                return {
                    "status": "not_run",
                    "summary": "No local activity recorded yet.",
                    "profile_options": [{"id": "G45", "label": "G45 label"}],
                    "selected_profile_id": profile_id,
                }

            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="",
                task_coordinator=coordinator,
                shell_loader=shell_loader,
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_lister=action_lister,
                action_getter=lambda _action_id, _workspace: preflight,
                action_executor=action_executor,
            )
            self.addCleanup(controller.shutdown)

            self.assertTrue(controller.initialize())
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertEqual(controller.currentPayload.get("actions", []), [])
            action_lister.assert_not_called()

            self.assertTrue(controller.selectProfile("G45"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertIn("actions", controller.currentPayload)
            actions = controller.currentPayload["actions"]
            self.assertEqual(len(actions), 1)
            self.assertEqual(
                actions[0],
                {
                    "capabilityId": "diagnostic.run",
                    "label": "Run local QA checks",
                    "enabled": True,
                    "actionId": "sgfx_preflight__g45",
                    "effectClass": "tool_output_only",
                },
            )
            self.assertNotIn(str(project), repr(actions))
            self.assertNotIn(str(output), repr(actions))
            action_lister.assert_called_once_with(workspace.resolve())

            self.assertTrue(controller.runDiagnostic("sgfx_preflight__g45", ["G45"]))
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            self.assertEqual(coordinator.requests[-1][0].operation, "effect_refresh")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertEqual(
                [item["actionId"] for item in controller.currentPayload["actions"]],
                ["sgfx_preflight__g45"],
            )
            action_executor.assert_called_once_with(preflight, workspace.resolve())


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
        from PySide6.QtGui import QGuiApplication

        cls.application = QCoreApplication.instance() or QGuiApplication([])

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
    def _batch_qa_page() -> dict[str, object]:
        return {
            "id": "batch-full-qa-pass",
            "status": "not_run",
            "data_available": True,
            "summary": "No batch evidence recorded",
            "payload": {
                "status": "not_run",
                "summary": "No batch evidence recorded",
                "progress": {"completed_profiles": 0, "total_profiles": 0, "percent": 0},
                "results": [],
                "read_only": True,
                "manual_review_required": True,
                "records_operator_verdict": False,
                "is_approval": False,
            },
        }

    @staticmethod
    def _complete_action_readiness(coordinator: object) -> object:
        identity, operation = coordinator.requests[-1]
        if identity.operation != "action_readiness":
            raise AssertionError(f"Expected action_readiness, received {identity.operation}")
        coordinator.succeed(identity, operation())
        return identity

    def test_batch_evidence_page_does_not_enumerate_selected_car_diagnostics(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            action_lister = mock.Mock(return_value=[])
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G45",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._batch_qa_page()),
                action_lister=action_lister,
            )
            self.addCleanup(controller.shutdown)

            self.assertTrue(controller.navigate("batch-full-qa-pass"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            action_lister.assert_not_called()
            self.assertNotIn(
                "diagnostic.run",
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
            )

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
            self.assertEqual(controller.lastActionResult["capabilityId"], "artifact.reveal")
            self.assertFalse(controller.revealArtifact(r"C:\private\artifact.txt"))
            self.assertEqual(controller.capabilityState, "failed")
            self.assertEqual(controller.lastActionResult, {})

            self.assertTrue(controller.navigate("delivery-checklist"))
            second = controller.currentPayload["artifacts"][0]
            self.assertNotEqual(second["artifactId"], first["artifactId"])
            self.assertFalse(controller.revealArtifact(first["artifactId"]))
            self.assertTrue(controller.revealArtifact(second["artifactId"]))
            controller.shutdown()

    def test_selected_car_checks_publish_before_action_readiness_and_preserve_evidence_on_failure(
        self,
    ) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import TaskFailure
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            project = root / "source" / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="sgfx_preflight__g65",
                label="Run local QA checks",
                description="Local selected-car checks",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            action_lister = mock.Mock(return_value=[action])
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(root / "source",),
                diagnostic_output_root=output,
                action_lister=action_lister,
            )
            self.addCleanup(controller.shutdown)

            self.assertTrue(controller.navigate("full-qa-pass"))
            base_identity, base_operation = coordinator.requests[-1]
            base_payload = base_operation()
            action_lister.assert_not_called()
            coordinator.succeed(base_identity, base_payload)

            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.errorCode, "")
            self.assertEqual(controller.currentPayload["actionReadinessState"], "loading")
            self.assertEqual(controller.currentPayload["surfaceId"], "full-qa-pass")
            self.assertEqual(
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
                ["page.refresh"],
            )
            readiness_identity, readiness_operation = coordinator.requests[-1]
            self.assertEqual(readiness_identity.operation, "action_readiness")
            self.assertEqual(readiness_identity.generation, base_identity.generation)
            admitted = readiness_operation()
            action_lister.assert_called_once_with(workspace.resolve())
            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.currentPayload["actionReadinessState"], "loading")

            coordinator.succeed(readiness_identity, admitted)
            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.currentPayload["actionReadinessState"], "ready")
            self.assertEqual(
                [
                    item["actionId"]
                    for item in controller.currentPayload["actions"]
                    if item["capabilityId"] == "diagnostic.run"
                ],
                [action.action_id],
            )

            self.assertTrue(controller.refresh())
            refresh_identity, refresh_operation = coordinator.requests[-1]
            coordinator.succeed(refresh_identity, refresh_operation())
            before_failure = {
                key: value
                for key, value in controller.currentPayload.items()
                if key not in {"actions", "actionReadinessState", "actionReadinessMessage"}
            }
            failed_identity, _failed_operation = coordinator.requests[-1]
            self.assertEqual(failed_identity.operation, "action_readiness")
            coordinator.fail(
                failed_identity,
                TaskFailure(
                    "page_reader_failed",
                    r"raw C:\private\readiness failure",
                    "PrivateError",
                ),
            )

            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.errorCode, "")
            self.assertEqual(controller.currentPayload["actionReadinessState"], "unavailable")
            self.assertNotIn("private", controller.currentPayload["actionReadinessMessage"].casefold())
            self.assertEqual(
                {
                    key: value
                    for key, value in controller.currentPayload.items()
                    if key not in {"actions", "actionReadinessState", "actionReadinessMessage"}
                },
                before_failure,
            )
            self.assertEqual(
                [item["capabilityId"] for item in controller.currentPayload["actions"]],
                ["page.refresh"],
            )

    def test_stale_action_readiness_is_cancelled_and_ignored(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import TaskFailure
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        def assert_transition(transition: str) -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                coordinator = _FakeTaskCoordinator()
                controller = DesktopController(
                    workspace=temp_dir,
                    initial_profile_id="G65",
                    task_coordinator=coordinator,
                    page_loader=mock.Mock(return_value=self._full_qa_page()),
                    action_lister=mock.Mock(return_value=[]),
                )
                controller._set_profile_options(
                    [{"id": "G65", "label": "G65"}, {"id": "G70", "label": "G70"}]
                )
                self.assertTrue(controller.navigate("full-qa-pass"))
                base_identity, base_operation = coordinator.requests[-1]
                coordinator.succeed(base_identity, base_operation())
                readiness_identity, readiness_operation = coordinator.requests[-1]
                readiness_payload = readiness_operation()

                if transition == "navigation":
                    self.assertTrue(controller.navigate("risk-score"))
                elif transition == "profile":
                    self.assertTrue(controller.selectProfile("G70"))
                elif transition == "refresh":
                    self.assertTrue(controller.refresh())
                else:
                    controller.shutdown()

                self.assertIn(readiness_identity, coordinator.cancelled)
                before = (
                    controller.currentRouteId,
                    controller.currentProfileId,
                    controller.pageState,
                    dict(controller.currentPayload),
                    dict(controller._cache),
                    controller.errorCode,
                )
                coordinator.succeed(readiness_identity, readiness_payload)
                coordinator.fail(
                    readiness_identity,
                    TaskFailure("page_reader_failed", "stale", "RuntimeError"),
                )
                self.assertEqual(
                    (
                        controller.currentRouteId,
                        controller.currentProfileId,
                        controller.pageState,
                        dict(controller.currentPayload),
                        dict(controller._cache),
                        controller.errorCode,
                    ),
                    before,
                )
                controller.shutdown()

        for transition in ("navigation", "profile", "refresh", "shutdown"):
            with self.subTest(transition=transition):
                assert_transition(transition)

    def test_gated_action_readiness_does_not_block_page_or_rotate_artifacts(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import PageTaskCoordinator
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _pump_until

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            project = root / "source" / "Cars" / "G65"
            output = workspace / "out" / "operator-ui" / "actions"
            summary = workspace / "out" / "full-qa" / "summary.json"
            project.mkdir(parents=True)
            summary.parent.mkdir(parents=True)
            summary.write_text("{}", encoding="utf-8")
            page = self._full_qa_page()
            page["payload"]["summary_json"] = str(summary)
            action = OperatorAction(
                action_id="sgfx_preflight__g65",
                label="Run local QA checks",
                description="Local selected-car checks",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G65",
                project_root=str(project),
            )
            readiness_started = threading.Event()
            release_readiness = threading.Event()
            revealed: list[Path] = []

            def gated_lister(_workspace: Path) -> list[OperatorAction]:
                readiness_started.set()
                release_readiness.wait(5)
                return [action]

            coordinator = PageTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=page),
                diagnostic_read_roots=(root / "source",),
                diagnostic_output_root=output,
                action_lister=gated_lister,
                artifact_revealer=lambda path: revealed.append(path),
            )
            states: list[str] = []
            controller.pageStateChanged.connect(lambda: states.append(controller.pageState))
            try:
                self.assertTrue(controller.navigate("full-qa-pass"))
                self.assertTrue(
                    _pump_until(
                        lambda: controller.pageState == "ready" and readiness_started.is_set(),
                        timeout_ms=3000,
                    )
                )
                self.assertEqual(controller.currentPayload["actionReadinessState"], "loading")
                self.assertEqual(
                    [item["capabilityId"] for item in controller.currentPayload["actions"]],
                    ["page.refresh", "artifact.reveal"],
                )
                artifact = dict(controller.currentPayload["artifacts"][0])
                self.assertEqual(states.count("loading"), 1)

                release_readiness.set()
                self.assertTrue(
                    _pump_until(
                        lambda: controller.currentPayload.get("actionReadinessState") == "ready",
                        timeout_ms=3000,
                    )
                )
                self.assertEqual(controller.pageState, "ready")
                self.assertEqual(controller.currentPayload["artifacts"], [artifact])
                self.assertEqual(states.count("loading"), 1)
                self.assertTrue(controller.revealArtifact(artifact["artifactId"]))
                self.assertEqual(revealed, [summary.resolve()])
            finally:
                release_readiness.set()
                controller.shutdown()
                coordinator.shutdown(timeout_ms=1000)

    def test_profile_change_clears_completed_feedback_before_loading_the_new_car(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            workbook = workspace / "out" / "delivery" / "delivery.xlsx"
            workbook.parent.mkdir(parents=True)
            workbook.write_bytes(b"xlsx")
            coordinator = _FakeTaskCoordinator()

            def shell_loader(*, profile_id: str, **_inputs: object) -> dict[str, object]:
                return {
                    "status": "not_run",
                    "summary": "No local activity recorded yet.",
                    "profile_options": [
                        {"id": "G65", "label": "G65"},
                        {"id": "G70", "label": "G70"},
                    ],
                    "selected_profile_id": profile_id,
                }

            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                shell_loader=shell_loader,
                page_loader=mock.Mock(return_value=self._delivery_page(workbook)),
                artifact_revealer=lambda _path: None,
            )
            self.addCleanup(controller.shutdown)
            self.assertTrue(controller.initialize())
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertTrue(controller.navigate("delivery-checklist"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            artifact = controller.currentPayload["artifacts"][0]
            self.assertTrue(controller.revealArtifact(artifact["artifactId"]))
            self.assertEqual(controller.capabilityState, "completed")

            self.assertTrue(controller.selectProfile("G70"))

            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.activeActionLabel, "")
            self.assertEqual(controller.lastActionResult, {})

    def test_old_profile_effect_completion_cannot_repopulate_new_car_feedback(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        for should_fail in (False, True):
            with self.subTest(should_fail=should_fail), tempfile.TemporaryDirectory() as temp_dir:
                started = threading.Event()
                release = threading.Event()

                def record(**_inputs: object) -> dict[str, str]:
                    started.set()
                    release.wait(5)
                    if should_fail:
                        raise RuntimeError("record failed")
                    return {"status": "recorded"}

                def shell_loader(*, profile_id: str, **_inputs: object) -> dict[str, object]:
                    return {
                        "status": "not_run",
                        "summary": "No local activity recorded yet.",
                        "profile_options": [
                            {"id": "G65", "label": "G65"},
                            {"id": "G70", "label": "G70"},
                        ],
                        "selected_profile_id": profile_id,
                    }

                coordinator = _FakeTaskCoordinator()
                controller = DesktopController(
                    workspace=temp_dir,
                    initial_profile_id="G65",
                    task_coordinator=coordinator,
                    shell_loader=shell_loader,
                    page_loader=mock.Mock(return_value=self._manual_page()),
                    manual_review_recorder=record,
                )
                self.assertTrue(controller.initialize())
                identity, operation = coordinator.requests[-1]
                coordinator.succeed(identity, operation())
                self.assertTrue(controller.navigate("manual-review"))
                identity, operation = coordinator.requests[-1]
                coordinator.succeed(identity, operation())
                self.assertTrue(controller.recordManualReview("review-1", "passed", "Reviewed locally"))
                self.assertTrue(started.wait(2))
                effect_generation = controller._effect_context.effect_generation

                self.assertTrue(controller.selectProfile("G70"))
                identity, operation = coordinator.requests[-1]
                coordinator.succeed(identity, operation())
                request_count = len(coordinator.requests)
                controller._accept_effect_started(effect_generation)
                self.assertEqual(controller.capabilityState, "idle")
                self.assertFalse(controller.cancelDiagnostic())
                release.set()
                self.assertTrue(_pump_until(lambda: controller._effect_future is None))

                self.assertEqual(controller.currentProfileId, "G70")
                self.assertEqual(controller.capabilityState, "idle")
                self.assertEqual(controller.capabilityError, "")
                self.assertEqual(controller.activeActionLabel, "")
                self.assertEqual(controller.lastActionResult, {})
                self.assertEqual(len(coordinator.requests), request_count)
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
            self.assertEqual(controller.activeActionLabel, "Record operator verdict")
            self.assertEqual(controller.lastActionStatus, "completed")
            self.assertEqual(
                controller.lastActionResult,
                {
                    "capabilityId": "manual_review.record",
                    "label": "Record operator verdict",
                    "status": "completed",
                    "lines": [],
                    "outputRoot": "",
                },
            )
            recorder.assert_called_once_with(
                profile_id="G65",
                workspace=Path(temp_dir).resolve(),
                step_slug="review-1",
                verdict="passed",
                note="Reviewed locally",
                suggested_verdict="",
            )
            self.assertEqual(coordinator.requests[-1][0].operation, "effect_refresh")
            refresh_identity, refresh_operation = coordinator.requests[-1]
            coordinator.succeed(refresh_identity, refresh_operation())
            self.assertEqual(controller.capabilityState, "completed")
            self.assertEqual(controller.lastActionStatus, "completed")
            controller.shutdown()

    def test_explicit_refresh_publishes_shared_feedback_for_success_and_failure(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import TaskFailure
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._manual_page()),
            )
            self.addCleanup(controller.shutdown)
            self.assertTrue(controller.navigate("manual-review"))
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertTrue(controller.refresh())
            refresh_identity, refresh_operation = coordinator.requests[-1]
            self.assertEqual(refresh_identity.operation, "refresh")
            self.assertEqual(controller.capabilityState, "queued")
            self.assertEqual(controller.activeActionLabel, "Refresh local evidence")
            self.assertEqual(controller.lastActionResult, {})

            coordinator.succeed(refresh_identity, refresh_operation())
            self.assertEqual(controller.capabilityState, "completed")
            self.assertEqual(
                controller.lastActionResult,
                {
                    "capabilityId": "page.refresh",
                    "label": "Refresh local evidence",
                    "status": "completed",
                    "lines": [],
                    "outputRoot": "",
                },
            )

            self.assertTrue(controller.refresh())
            failed_identity, _failed_operation = coordinator.requests[-1]
            self.assertEqual(controller.capabilityState, "queued")
            self.assertEqual(controller.lastActionResult, {})
            coordinator.fail(
                failed_identity,
                TaskFailure(
                    "page_reader_failed",
                    "The local page evidence could not be loaded.",
                    "RuntimeError",
                ),
            )
            self.assertEqual(controller.capabilityState, "failed")
            self.assertEqual(controller.capabilityError, "The local evidence could not be refreshed.")
            self.assertEqual(controller.lastActionResult, {})

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
            self._complete_action_readiness(coordinator)
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
            self.assertEqual(coordinator.requests[-1][0].operation, "effect_refresh")
            controller.shutdown()

    def test_diagnostic_requires_an_output_contract_and_a_safe_public_label(self) -> None:
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
                label=r"C:\private\diagnostic.txt",
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
            self._complete_action_readiness(coordinator)

            diagnostic = next(
                item
                for item in controller.currentPayload["actions"]
                if item["capabilityId"] == "diagnostic.run"
            )
            self.assertEqual(diagnostic["label"], "Local diagnostic")
            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertEqual(controller.activeActionLabel, "Local diagnostic")
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
            self._complete_action_readiness(coordinator)

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
            self.assertEqual(controller.activeActionLabel, "Record operator handoff")
            self.assertEqual(controller.lastActionStatus, "completed")
            self.assertEqual(controller.lastActionResult["capabilityId"], "operator_handoff.record")
            self.assertNotIn("Stopped after review", repr(controller.lastActionResult))
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

    def test_completed_diagnostic_publishes_running_label_and_result(self) -> None:
        from types import SimpleNamespace

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
            record = SimpleNamespace(
                status="completed",
                label="Delivery readiness",
                summary={
                    "lines": [
                        "4/4 assets found",
                        "BMW repo available",
                        r"C:\private\evidence.txt",
                        "x" * 300,
                    ]
                },
                paths={
                    "output_root": str(output / "run-1"),
                    "run_record": str(output / "run-1" / "action.json"),
                },
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
                action_executor=lambda _action, _workspace: record,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self._complete_action_readiness(coordinator)

            self.assertEqual(controller.lastActionStatus, "")
            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertEqual(controller.activeActionLabel, "Delivery readiness")
            self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
            self.assertTrue(_pump_until(lambda: controller.lastActionStatus == "completed"))
            result = controller.lastActionResult
            self.assertEqual(result["label"], "Delivery readiness")
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["lines"], ["4/4 assets found", "BMW repo available"])
            self.assertEqual(result["outputRoot"], "out/operator-ui/actions/run-1")
            self.assertNotIn(str(workspace), repr(result))
            refresh_identity, refresh_operation = coordinator.requests[-1]
            self.assertEqual(refresh_identity.operation, "effect_refresh")
            self.assertFalse(controller.refresh())
            self.assertEqual(controller.lastActionResult, result)
            coordinator.succeed(refresh_identity, refresh_operation())
            self.assertEqual(controller.capabilityState, "completed")
            self.assertEqual(controller.lastActionResult, result)

    def test_evidence_writes_inside_a_flat_workspace_read_root_do_not_fail_the_run(self) -> None:
        from types import SimpleNamespace

        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            project = workspace / "Cars" / "G65"
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

            def executor(_action: object, _workspace: object) -> object:
                run_dir = output / "run-1"
                run_dir.mkdir(parents=True)
                (run_dir / "action.json").write_text("{}", encoding="utf-8")
                return SimpleNamespace(
                    status="completed",
                    summary={"lines": ["ok"]},
                    paths={"output_root": str(run_dir)},
                )

            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(workspace,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=executor,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self._complete_action_readiness(coordinator)

            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertTrue(
                _pump_until(lambda: controller.capabilityState in {"completed", "failed"})
            )
            self.assertEqual(controller.capabilityState, "completed")
            self.assertEqual(controller.lastActionStatus, "completed")

    def test_source_mutations_outside_the_output_area_still_fail_the_run(self) -> None:
        from types import SimpleNamespace

        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            project = workspace / "Cars" / "G65"
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

            def executor(_action: object, _workspace: object) -> object:
                run_dir = output / "run-1"
                run_dir.mkdir(parents=True)
                (project / "injected.lua").write_text("-- mutated", encoding="utf-8")
                return SimpleNamespace(
                    status="completed",
                    summary={"lines": ["ok"]},
                    paths={"output_root": str(run_dir)},
                )

            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=self._full_qa_page()),
                diagnostic_read_roots=(workspace,),
                diagnostic_output_root=output,
                action_lister=lambda _workspace: [action],
                action_getter=lambda _action_id, _workspace: action,
                action_executor=executor,
            )
            self.addCleanup(controller.shutdown)
            controller.navigate("full-qa-pass")
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self._complete_action_readiness(coordinator)

            self.assertTrue(controller.runDiagnostic(action.action_id, ["G65"]))
            self.assertTrue(
                _pump_until(lambda: controller.capabilityState in {"completed", "failed"})
            )
            self.assertEqual(controller.capabilityState, "failed")

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
            self._complete_action_readiness(coordinator)
            accepted = controller.runDiagnostic(action.action_id, ["G65"])
            output_exists = output.exists()
            release.set()
            self.assertTrue(_pump_until(lambda: controller._effect_future is None))
            self.assertFalse(accepted)
            self.assertFalse(output_exists)
            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.capabilityError, "Another capability is already running.")

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
            self._complete_action_readiness(coordinator)
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
            self._complete_action_readiness(coordinator)
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
                read_roots.assert_not_called()
                output_root.assert_not_called()
                coordinator.succeed(identity, result)
                identity, operation = coordinator.requests[-1]
                self.assertEqual(identity.operation, "action_readiness")
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
            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.capabilityError, "")
            self.assertEqual(controller.activeActionLabel, "")
            self.assertEqual(controller.lastActionResult, {})

            release.set()
            self.assertTrue(_pump_until(lambda: controller._effect_future is None))
            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.lastActionResult, {})
            self.assertEqual(controller.currentPayload["artifacts"], [artifact])
            self.assertTrue(controller.revealArtifact(artifact["artifactId"]))
            self.assertEqual(controller.activeActionLabel, "Reveal local artifact")
            self.assertEqual(controller.lastActionStatus, "completed")
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
            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.activeActionLabel, "")
            self.assertEqual(controller.lastActionResult, {})
            release.set()
            self.assertTrue(_pump_until(lambda: controller._effect_future is None))

            self.assertEqual(len(coordinator.requests), request_count)
            self.assertEqual(controller.capabilityState, "idle")
            self.assertEqual(controller.lastActionResult, {})
            self.assertEqual(controller.pageState, "ready")
            self.assertEqual(controller.currentPayload, current_payload)


class TestCapabilityQmlBindings(unittest.TestCase):
    def test_shared_feedback_and_primary_action_contract_is_centralized(self) -> None:
        root = Path(__file__).resolve().parents[1] / "sg_preflight" / "desktop" / "qml"
        feedback_path = root / "components" / "ActionFeedback.qml"
        self.assertTrue(feedback_path.is_file())
        feedback = feedback_path.read_text(encoding="utf-8")
        home = (root / "components" / "HomePage.qml").read_text(encoding="utf-8")
        page_frame = (root / "components" / "PageFrame.qml").read_text(encoding="utf-8")
        workflow = (root / "renderers" / "WorkflowRenderer.qml").read_text(encoding="utf-8")
        review = (root / "renderers" / "ReviewRenderer.qml").read_text(encoding="utf-8")

        for object_name in (
            "pageActionFeedback",
            "pageActionBusyBanner",
            "actionResultPanel",
            "pageActionErrorCard",
        ):
            self.assertIn(f'objectName: "{object_name}"', feedback)
        self.assertIn("ActionFeedback", page_frame)
        self.assertIn("ActionFeedback", home)
        self.assertIn('objectName: "pageRefreshControl"', page_frame)
        self.assertIn("property bool primaryAction: false", page_frame)
        self.assertIn("primaryAction", page_frame + workflow + review)
        self.assertNotIn('objectName: "runningActionText"', workflow)
        self.assertNotIn('objectName: "actionResultPanel"', workflow)
        self.assertNotIn('objectName: "capabilityLifecycleText"', workflow + review)
        self.assertIn('Accessible.name: "Handoff stopping point"', workflow)
        self.assertIn('Accessible.name: "Handoff next local step"', workflow)
        self.assertIn('Accessible.name: "Handoff operator note"', workflow)
        self.assertIn('capabilityId === "operator_handoff.record"', workflow)

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

    def test_selected_car_action_area_exposes_bounded_progress_and_unavailable_feedback(self) -> None:
        qml = (
            Path(__file__).resolve().parents[1]
            / "sg_preflight"
            / "desktop"
            / "qml"
            / "components"
            / "PageFrame.qml"
        ).read_text(encoding="utf-8")

        self.assertIn("actionReadinessState", qml)
        self.assertIn('objectName: "actionReadinessProgress"', qml)
        self.assertIn('objectName: "actionReadinessMessage"', qml)
        self.assertIn('root.actionReadinessState === "loading"', qml)
        self.assertIn('root.actionReadinessState === "unavailable"', qml)
        self.assertIn("Accessible.name: text", qml)

    def test_qml_binds_only_typed_capabilities_and_artifact_handles(self) -> None:
        root = Path(__file__).resolve().parents[1] / "sg_preflight" / "desktop" / "qml"
        main = (root / "Main.qml").read_text(encoding="utf-8")
        page_frame = (root / "components" / "PageFrame.qml").read_text(encoding="utf-8")
        feedback = (root / "components" / "ActionFeedback.qml").read_text(encoding="utf-8")
        workflow = (root / "renderers" / "WorkflowRenderer.qml").read_text(encoding="utf-8")
        review = (root / "renderers" / "ReviewRenderer.qml").read_text(encoding="utf-8")

        self.assertIn("desktopController: window.desktopController", main)
        self.assertIn("desktopController.revealArtifact", page_frame)
        self.assertIn('objectName: "artifactRevealControl"', page_frame)
        self.assertIn("controller.runDiagnostic", workflow)
        self.assertIn('objectName: "diagnosticActionControl"', workflow)
        self.assertIn("controller.cancelDiagnostic", feedback)
        self.assertIn('objectName: "cancelDiagnosticControl"', feedback)
        self.assertIn("controller.capabilityState", feedback)
        self.assertIn("controller.capabilityError", feedback)
        self.assertIn("controller.activeActionLabel", feedback)
        self.assertIn("controller.lastActionResult", feedback)
        self.assertIn('objectName: "runningActionText"', feedback)
        self.assertIn('objectName: "actionResultPanel"', feedback)
        self.assertIn("controller.recordOperatorHandoff", workflow)
        self.assertIn('capabilityId === "operator_handoff.record"', workflow)
        self.assertIn("controller.recordManualReview", review)
        self.assertIn('capabilityId === "manual_review.record"', review)
        self.assertIn("selectedStepIndex", review)
        self.assertIn("root.selectReviewStep(reviewDelegate.index)", review)
        self.assertNotIn("command", (page_frame + feedback + workflow + review).casefold())

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
                        "recordPrimary": bool(record.property("primaryAction")),
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
            {
                "verdictEnabled": True,
                "noteReadOnly": False,
                "recordEnabled": True,
                "recordPrimary": True,
            },
        )

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_page_frame_primary_feedback_and_handoff_completion_are_runtime_exact(self) -> None:
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
                    from PySide6.QtCore import QObject, Property, Signal, Slot, QUrl
                    from PySide6.QtGui import QAccessible, QGuiApplication
                    from PySide6.QtQml import QQmlComponent, QQmlEngine

                    class Controller(QObject):
                        capabilityStateChanged = Signal()
                        capabilityErrorChanged = Signal()
                        actionFeedbackChanged = Signal()
                        diagnosticCanCancelChanged = Signal()

                        def __init__(self):
                            super().__init__()
                            self._state = "idle"
                            self._error = ""
                            self._result = {{}}

                        @Property(str, constant=True)
                        def currentProfileId(self):
                            return "G65"

                        @Property(str, notify=capabilityStateChanged)
                        def capabilityState(self):
                            return self._state

                        @Property(str, notify=capabilityErrorChanged)
                        def capabilityError(self):
                            return self._error

                        @Property(str, notify=actionFeedbackChanged)
                        def activeActionLabel(self):
                            return "Local evidence action"

                        @Property(str, notify=actionFeedbackChanged)
                        def lastActionStatus(self):
                            return str(self._result.get("status", ""))

                        @Property("QVariantMap", notify=actionFeedbackChanged)
                        def lastActionResult(self):
                            return dict(self._result)

                        @Property(bool, notify=diagnosticCanCancelChanged)
                        def diagnosticCanCancel(self):
                            return False

                        def publish(self, state, error, result):
                            self._state = state
                            self._error = error
                            self._result = dict(result)
                            self.capabilityStateChanged.emit()
                            self.capabilityErrorChanged.emit()
                            self.actionFeedbackChanged.emit()

                        @Slot(result=bool)
                        def refresh(self):
                            return True

                        @Slot(str, result=bool)
                        def revealArtifact(self, _artifact_id):
                            return True

                        @Slot(str, list, result=bool)
                        def runDiagnostic(self, _action_id, _profiles):
                            return True

                        @Slot(str, str, str, result=bool)
                        def recordOperatorHandoff(self, _stopping, _next, _note):
                            return True

                        @Slot(result=bool)
                        def cancelDiagnostic(self):
                            return True

                    app = QGuiApplication(["sgfx-slice2-runtime-test"])
                    engine = QQmlEngine()
                    engine.addImportPath({str(qml_root)!r})
                    controller = Controller()
                    component = QQmlComponent(engine, QUrl.fromLocalFile({str(qml_root / 'components' / 'PageFrame.qml')!r}))

                    item = {{
                        "itemId": "item-1", "sectionId": "main", "label": "Evidence",
                        "value": "Available", "detail": "", "status": "available",
                        "expected": "", "actual": "", "diff": "", "source": "", "revision": ""
                    }}

                    def page(surface_id, renderer_kind, actions, artifacts=None):
                        return {{
                            "surfaceId": surface_id, "rendererKind": renderer_kind,
                            "title": surface_id, "subtitle": "Local evidence", "status": "available",
                            "dataAvailable": True, "primaryText": "Local evidence", "visibleItems": [item],
                            "visibleItemCount": 1, "sections": [], "actions": actions,
                            "artifacts": list(artifacts or []), "provenance": {{}}, "ownershipNote": "",
                            "readOnly": True, "isApproval": False, "manualReviewRequired": False,
                            "recordsOperatorVerdict": False
                        }}

                    def create_frame(payload):
                        frame = component.createWithInitialProperties({{
                            "pageState": "ready", "page": payload, "errorCode": "",
                            "errorSummary": "", "reducedMotion": False, "desktopController": controller
                        }})
                        if frame is None:
                            raise SystemExit(" | ".join(error.toString() for error in component.errors()))
                        frame.setProperty("width", 900)
                        frame.setProperty("height", 620)
                        app.processEvents()
                        return frame

                    diagnostics = [
                        {{"capabilityId": "diagnostic.run", "label": "Run selected-car checks", "enabled": True, "actionId": "diag-1", "effectClass": "tool_output_only"}},
                        {{"capabilityId": "diagnostic.run", "label": "Run delivery readiness", "enabled": True, "actionId": "diag-2", "effectClass": "tool_output_only"}},
                    ]
                    full = create_frame(page("full-qa-pass", "workflow", diagnostics))
                    handoff = create_frame(page("operator-handoff", "workflow", [
                        {{"capabilityId": "operator_handoff.record", "label": "Record handoff", "enabled": True, "actionId": "", "effectClass": "local_write"}}
                    ]))
                    evidence = create_frame(page("delivery-checklist", "evidence", [
                        {{"capabilityId": "page.refresh", "label": "Refresh", "enabled": True, "actionId": "", "effectClass": "read_only"}},
                        {{"capabilityId": "artifact.reveal", "label": "Reveal", "enabled": True, "actionId": "", "effectClass": "local_reveal"}},
                    ], [{{"artifactId": "opaque-handle", "label": "Local workbook", "type": "xlsx"}}]))

                    full_controls = [full.findChild(QObject, "pageRefreshControl"), *full.findChildren(QObject, "diagnosticActionControl")]
                    secondary_diagnostics = full.findChild(QObject, "secondaryDiagnosticRepeater")
                    handoff_controls = [handoff.findChild(QObject, "pageRefreshControl"), handoff.findChild(QObject, "recordOperatorHandoffControl")]
                    evidence_controls = [evidence.findChild(QObject, "pageRefreshControl"), evidence.findChild(QObject, "artifactRevealControl")]

                    stopping = handoff.findChild(QObject, "handoffStoppingPointControl")
                    next_step = handoff.findChild(QObject, "handoffNextStepControl")
                    note = handoff.findChild(QObject, "handoffNoteControl")
                    record = handoff.findChild(QObject, "recordOperatorHandoffControl")
                    stopping.setProperty("text", "Stopped after review")
                    next_step.setProperty("text", "Continue evidence review")
                    note.setProperty("text", "Local note")
                    app.processEvents()
                    before_record_enabled = bool(record.property("enabled"))
                    controller.publish("completed", "", {{"capabilityId": "diagnostic.run", "label": "Diagnostic", "status": "completed", "lines": [], "outputRoot": ""}})
                    app.processEvents()
                    after_unrelated = [stopping.property("text"), next_step.property("text"), note.property("text")]
                    controller.publish("completed", "", {{"capabilityId": "operator_handoff.record", "label": "Record operator handoff", "status": "completed", "lines": [], "outputRoot": ""}})
                    app.processEvents()
                    after_handoff = [stopping.property("text"), next_step.property("text"), note.property("text"), bool(record.property("enabled"))]

                    def accessible_name(control):
                        interface = QAccessible.queryAccessibleInterface(control)
                        return interface.text(QAccessible.Text.Name) if interface is not None else ""

                    busy = evidence.findChild(QObject, "pageActionBusyBanner")
                    result_card = evidence.findChild(QObject, "actionResultPanel")
                    error_card = evidence.findChild(QObject, "pageActionErrorCard")
                    controller.publish("queued", "", {{}})
                    app.processEvents()
                    busy_state = [bool(busy.property("visible")), bool(result_card.property("visible")), bool(error_card.property("visible"))]
                    handoff_fields_enabled_while_busy = [bool(stopping.property("enabled")), bool(next_step.property("enabled")), bool(note.property("enabled"))]
                    controller.publish("completed", "", {{"capabilityId": "artifact.reveal", "label": "Reveal local artifact", "status": "completed", "lines": [], "outputRoot": "out/evidence"}})
                    app.processEvents()
                    result_state = [bool(busy.property("visible")), bool(result_card.property("visible")), bool(error_card.property("visible"))]
                    completed_tone = result_card.property("semanticColor")
                    completed_tone_name = completed_tone.name() if hasattr(completed_tone, "name") else ""
                    controller.publish("cancelled", "", {{}})
                    app.processEvents()
                    cancelled_state = [bool(busy.property("visible")), bool(result_card.property("visible")), bool(error_card.property("visible"))]
                    cancelled_tone = result_card.property("semanticColor")
                    cancelled_tone_name = cancelled_tone.name() if hasattr(cancelled_tone, "name") else ""
                    controller.publish("failed", "Local action failed.", {{}})
                    app.processEvents()
                    error_state = [bool(busy.property("visible")), bool(result_card.property("visible")), bool(error_card.property("visible"))]

                    def primary_count(controls):
                        return sum(1 for control in controls if control is not None and bool(control.property("visible")) and bool(control.property("primaryAction")))

                    print(json.dumps({{
                        "primaryCounts": [primary_count(full_controls), primary_count(handoff_controls), primary_count(evidence_controls)],
                        "fullPrimaryFlags": [bool(control.property("primaryAction")) for control in full_controls],
                        "secondaryDiagnosticCount": int(secondary_diagnostics.property("count")),
                        "evidencePrimaryFlags": [bool(control.property("primaryAction")) for control in evidence_controls if control is not None],
                        "beforeRecordEnabled": before_record_enabled,
                        "afterUnrelated": after_unrelated,
                        "afterHandoff": after_handoff,
                        "accessibleNames": [accessible_name(stopping), accessible_name(next_step), accessible_name(note)],
                        "handoffFieldsEnabledWhileBusy": handoff_fields_enabled_while_busy,
                        "feedbackStates": [busy_state, result_state, cancelled_state, error_state],
                        "feedbackTones": [completed_tone_name, cancelled_tone_name],
                    }}))
                    for frame in (full, handoff, evidence):
                        frame.deleteLater()
                    """
                ),
            ],
            cwd=root,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
            timeout=45,
        )

        self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
        payload = __import__("json").loads(result.stdout)
        self.assertEqual(payload["primaryCounts"], [1, 1, 1])
        self.assertEqual(payload["fullPrimaryFlags"], [False, True])
        self.assertEqual(payload["secondaryDiagnosticCount"], 1)
        self.assertEqual(payload["evidencePrimaryFlags"], [True])
        self.assertTrue(payload["beforeRecordEnabled"])
        self.assertEqual(payload["afterUnrelated"], ["Stopped after review", "Continue evidence review", "Local note"])
        self.assertEqual(payload["afterHandoff"], ["", "", "", False])
        self.assertEqual(
            payload["accessibleNames"],
            ["Handoff stopping point", "Handoff next local step", "Handoff operator note"],
        )
        self.assertEqual(payload["handoffFieldsEnabledWhileBusy"], [False, False, False])
        self.assertEqual(
            payload["feedbackStates"],
            [[True, False, False], [False, True, False], [False, True, False], [False, False, True]],
        )
        self.assertNotEqual(payload["feedbackTones"][0], payload["feedbackTones"][1])


if __name__ == "__main__":
    unittest.main()

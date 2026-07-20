from __future__ import annotations

from dataclasses import asdict, replace
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import threading
import time
import unittest
from unittest import mock


PYSIDE_AVAILABLE = importlib.util.find_spec("PySide6") is not None

if PYSIDE_AVAILABLE:
    from PySide6.QtCore import QObject, QSize, Signal, QUrl
    from PySide6.QtGui import QColor, QImage
    from PySide6.QtQml import QQmlComponent


class TestNativePreviewHelper(unittest.TestCase):
    @staticmethod
    def _helper() -> Path | None:
        root = Path(__file__).resolve().parents[1]
        candidates = (
            root / "cpp" / "bin" / "sgfx_cine_ramses_preview_cli.exe",
            root / "build" / "cine-c0" / "RelWithDebInfo" / "sgfx_cine_ramses_preview_cli.exe",
        )
        return next((candidate for candidate in candidates if candidate.is_file()), None)

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        helper = self._helper()
        if helper is None:
            self.skipTest("native preview helper has not been built")
        return subprocess.run(
            [str(helper), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_cli_rejects_unknown_missing_and_out_of_bounds_requests_without_writes(self) -> None:
        unknown = self._run("--unknown")
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(unknown.stdout, "")
        self.assertEqual(unknown.stderr.strip().splitlines(), ["invalid_arguments"])

        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir)
            request = (
                "--scene", str(output / "missing.ramses"),
                "--output-root", str(output),
                "--width", "961",
                "--height", "270",
                "--frames", "1",
            )
            oversized = self._run(*request)
            self.assertEqual(oversized.returncode, 1)
            self.assertEqual(oversized.stdout, "")
            self.assertEqual(oversized.stderr.strip().splitlines(), ["request_out_of_bounds"])
            self.assertEqual(tuple(output.iterdir()), ())

            reduced = self._run(
                *request[:-6],
                "--width", "480",
                "--height", "270",
                "--frames", "2",
                "--reduced-motion",
            )
            self.assertEqual(reduced.returncode, 1)
            self.assertEqual(reduced.stdout, "")
            self.assertEqual(reduced.stderr.strip().splitlines(), ["request_out_of_bounds"])
            self.assertEqual(tuple(output.iterdir()), ())

    @unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
    def test_local_compatible_scene_round_trips_through_the_coordinator_when_available(self) -> None:
        from sg_preflight.desktop.qt_quick_app import _preview_profile_resolver
        from sg_preflight.desktop.preview_coordinator import PreviewCoordinator
        from sg_preflight.desktop.preview_image_provider import PreviewImageProvider

        helper = self._helper()
        scene = Path(os.environ.get("SGFX_CINE_PREVIEW_SCENE", ""))
        if helper is None or not scene.is_file():
            self.skipTest("compatible local preview inputs are unavailable")
        bmw_root = scene.parents[4]
        expected_scene = bmw_root / "Cars" / "BMW" / "G45" / "export" / "exported.ramses"
        self.assertEqual(scene.resolve(), expected_scene.resolve())
        before = self._sha256(scene)
        with tempfile.TemporaryDirectory() as temp_dir:
            provider = PreviewImageProvider()
            coordinator = PreviewCoordinator(
                cache_root=Path(temp_dir) / "cache",
                helper_path=helper,
                image_provider=provider,
                profile_resolver=_preview_profile_resolver(Path(temp_dir), bmw_root),
            )
            try:
                coordinator.request_profile(
                    "G45",
                    generation=1,
                    reduced_motion=False,
                    allow_launch=True,
                )
                self.assertTrue(coordinator.wait_for_idle(30))
                state = coordinator.public_state()

                self.assertEqual(state.state, "ready")
                self.assertEqual(state.frame_count, 48)
                self.assertRegex(state.token, re.compile(r"^[A-Za-z0-9_-]{16,}$"))
                self.assertNotIn(str(scene), asdict(state).values())
                self.assertEqual(self._sha256(scene), before)
            finally:
                coordinator.shutdown()


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestPreviewCoordinator(unittest.TestCase):
    class FakeHelper:
        def __init__(self, *, mode: str = "success", block: bool = False) -> None:
            self.mode = mode
            self.block = block
            self.calls: list[tuple[str, ...]] = []
            self.started = threading.Event()
            self.release = threading.Event()
            self.terminated = 0

        def __call__(self, command: tuple[str, ...], *, timeout: float, creationflags: int) -> int:
            self.calls.append(tuple(command))
            call_number = len(self.calls)
            self.started.set()
            if self.block and call_number == 1:
                self.release.wait(timeout)
            if self.terminated >= call_number:
                raise RuntimeError("terminated")
            if self.mode == "timeout":
                raise subprocess.TimeoutExpired(command, timeout)
            output_root = Path(command[command.index("--output-root") + 1])
            width = int(command[command.index("--width") + 1])
            height = int(command[command.index("--height") + 1])
            requested_count = int(command[command.index("--frames") + 1])
            reduced_motion = "--reduced-motion" in command
            frame_count = 1 if reduced_motion else min(3, requested_count)
            if self.mode == "too_many_frames":
                frame_count = 49
            if self.mode == "oversized_frame":
                width = width + 1
            output_root.mkdir(parents=True, exist_ok=True)
            frames: list[str] = []
            for index in range(frame_count):
                name = f"frame-{index:03d}.png"
                image = QImage(width, height, QImage.Format.Format_RGBA8888)
                image.fill(QColor("#1d282d"))
                if not image.save(str(output_root / name)):
                    raise RuntimeError("fixture image save failed")
                frames.append(name)
            manifest = {
                "schema_version": 1,
                "state": "rendered",
                "frame_count": frame_count,
                "width": width,
                "height": height,
                "frames": frames,
                "ramses_version": "test-runtime",
                "feature_level": 1,
            }
            (output_root / "preview-manifest.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )
            if self.mode == "extra_output":
                (output_root / "undeclared.txt").write_text("not accepted", encoding="utf-8")
            if self.mode == "mutate_source":
                Path(command[command.index("--scene") + 1]).write_bytes(b"changed during preview")
            return 0

        def terminate(self) -> None:
            self.terminated += 1
            self.release.set()

    def setUp(self) -> None:
        from sg_preflight.profiles import RunProfile

        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.project = self.root / "source" / "Cars" / "G45"
        self.scene = self.project / "export" / "exported.ramses"
        self.scene.parent.mkdir(parents=True)
        self.scene.write_bytes(b"ramses-scene-fixture-v1")
        self.helper_path = self.root / "bin" / "sgfx_cine_ramses_preview_cli.exe"
        self.helper_path.parent.mkdir()
        self.helper_path.write_bytes(b"preview-helper-fixture-v1")
        self.profile = RunProfile(
            profile_id="G45",
            label="BMW G45",
            repo_root=self.root / "source",
            project_root=self.project,
            project_relative=Path("Cars/G45"),
            config_path=self.root / "config.json",
            reference_repo_root=self.root / "missing-reference",
        )

    def _coordinator(
        self,
        *,
        helper: "TestPreviewCoordinator.FakeHelper | None" = None,
        cache_limit_bytes: int = 256 * 1024 * 1024,
    ) -> tuple[object, object, "TestPreviewCoordinator.FakeHelper"]:
        from sg_preflight.desktop.preview_coordinator import PreviewCoordinator
        from sg_preflight.desktop.preview_image_provider import PreviewImageProvider

        provider = PreviewImageProvider()
        owned_helper = helper or self.FakeHelper()
        coordinator = PreviewCoordinator(
            cache_root=self.root / "out" / "preview-cache",
            helper_path=self.helper_path,
            image_provider=provider,
            runner=owned_helper,
            cache_limit_bytes=cache_limit_bytes,
        )
        self.addCleanup(coordinator.shutdown)
        return coordinator, provider, owned_helper

    def test_success_publishes_only_an_opaque_token_and_bounded_frames(self) -> None:
        coordinator, provider, helper = self._coordinator()

        handle = coordinator.request(
            profile=self.profile,
            generation=4,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(handle.request_id)
        self.assertTrue(coordinator.wait_for_idle(3))
        state = coordinator.public_state()

        self.assertEqual(state.state, "ready")
        self.assertEqual(state.frame_count, 3)
        self.assertEqual(state.frame_index, 0)
        self.assertRegex(state.token, r"^[A-Za-z0-9_-]{20,}$")
        self.assertEqual(provider.token_count, 1)
        image = provider.requestImage(f"{state.token}/0", QSize(), QSize())
        self.assertFalse(image.isNull())
        self.assertEqual((image.width(), image.height()), (960, 540))
        self.assertEqual(len(helper.calls), 1)
        rendered = repr(asdict(state))
        self.assertNotIn(str(self.root), rendered)
        self.assertNotIn(".ramses", rendered)
        self.assertNotIn(".exe", rendered)

    def test_missing_scene_invalid_profile_timeout_and_bad_manifest_fail_quietly(self) -> None:
        invalid = replace(self.profile, profile_id="bad profile")
        cases = (
            ("invalid-profile", invalid, self.FakeHelper()),
            ("timeout", self.profile, self.FakeHelper(mode="timeout")),
            ("too-many", self.profile, self.FakeHelper(mode="too_many_frames")),
            ("oversized", self.profile, self.FakeHelper(mode="oversized_frame")),
            ("extra-output", self.profile, self.FakeHelper(mode="extra_output")),
        )
        for label, profile, helper in cases:
            with self.subTest(label=label):
                coordinator, provider, _owned = self._coordinator(helper=helper)
                coordinator.request(
                    profile=profile,
                    generation=1,
                    reduced_motion=False,
                    allow_launch=True,
                )
                self.assertTrue(coordinator.wait_for_idle(3))
                self.assertEqual(coordinator.public_state().state, "fallback")
                self.assertEqual(coordinator.public_state().token, "")
                self.assertEqual(provider.token_count, 0)

        self.scene.unlink()
        coordinator, provider, helper = self._coordinator()
        coordinator.request(
            profile=self.profile,
            generation=2,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(coordinator.wait_for_idle(3))
        self.assertEqual(coordinator.public_state().state, "fallback")
        self.assertEqual(provider.token_count, 0)
        self.assertEqual(helper.calls, [])

    def test_source_change_during_helper_execution_is_detected_and_rejected(self) -> None:
        coordinator, provider, helper = self._coordinator(
            helper=self.FakeHelper(mode="mutate_source")
        )
        coordinator.request(
            profile=self.profile,
            generation=1,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(coordinator.wait_for_idle(3))

        self.assertEqual(coordinator.public_state().state, "fallback")
        self.assertEqual(provider.token_count, 0)
        self.assertEqual(len(helper.calls), 1)

    def test_stale_generation_and_preemption_never_publish_a_token(self) -> None:
        for action in ("invalidate", "preempt"):
            with self.subTest(action=action):
                helper = self.FakeHelper(block=True)
                coordinator, provider, _owned = self._coordinator(helper=helper)
                coordinator.request(
                    profile=self.profile,
                    generation=4,
                    reduced_motion=False,
                    allow_launch=True,
                )
                self.assertTrue(helper.started.wait(2))
                if action == "invalidate":
                    coordinator.invalidate(generation=5)
                else:
                    coordinator.preempt()
                self.assertTrue(coordinator.wait_for_idle(3))
                state = coordinator.public_state()
                self.assertEqual(state.state, "fallback")
                self.assertEqual(state.token, "")
                self.assertEqual(provider.token_count, 0)
                self.assertGreaterEqual(helper.terminated, 1)

    def test_stale_profile_result_is_rejected_before_the_new_profile_publishes(self) -> None:
        second_project = self.root / "source" / "Cars" / "G70"
        second_scene = second_project / "export" / "exported.ramses"
        second_scene.parent.mkdir(parents=True)
        second_scene.write_bytes(b"ramses-scene-fixture-g70")
        second_profile = replace(
            self.profile,
            profile_id="G70",
            label="BMW G70",
            project_root=second_project,
            project_relative=Path("Cars/G70"),
        )
        helper = self.FakeHelper(block=True)
        coordinator, provider, _owned = self._coordinator(helper=helper)
        with mock.patch.object(provider, "register", wraps=provider.register) as register:
            coordinator.request(
                profile=self.profile,
                generation=4,
                reduced_motion=False,
                allow_launch=True,
            )
            self.assertTrue(helper.started.wait(2))
            coordinator.request(
                profile=second_profile,
                generation=4,
                reduced_motion=False,
                allow_launch=True,
            )
            self.assertTrue(coordinator.wait_for_idle(3))

        self.assertEqual(coordinator.public_state().state, "ready")
        self.assertEqual(register.call_count, 1)
        self.assertEqual(provider.token_count, 1)
        self.assertEqual(len(helper.calls), 2)

    def test_startup_reuses_a_valid_cache_but_never_launches_a_helper(self) -> None:
        coordinator, provider, helper = self._coordinator()
        coordinator.request(
            profile=self.profile,
            generation=1,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(coordinator.wait_for_idle(3))
        first_token = coordinator.public_state().token
        self.assertEqual(len(helper.calls), 1)

        coordinator.invalidate(generation=2)
        coordinator.request(
            profile=self.profile,
            generation=2,
            reduced_motion=False,
            allow_launch=False,
        )
        self.assertTrue(coordinator.wait_for_idle(3))
        state = coordinator.public_state()

        self.assertEqual(state.state, "ready")
        self.assertNotEqual(state.token, first_token)
        self.assertEqual(len(helper.calls), 1)
        self.assertEqual(provider.token_count, 1)
        self.assertTrue(provider.requestImage(f"{first_token}/0", QSize(), QSize()).isNull())

    def test_completed_cache_entries_are_evicted_least_recently_used_to_the_byte_limit(self) -> None:
        first, _provider, _helper = self._coordinator()
        first.request(
            profile=self.profile,
            generation=1,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(first.wait_for_idle(3))
        cache_root = self.root / "out" / "preview-cache"
        first_entries = [item for item in cache_root.iterdir() if item.is_dir()]
        self.assertEqual(len(first_entries), 1)
        first_name = first_entries[0].name
        entry_bytes = sum(item.stat().st_size for item in first_entries[0].rglob("*") if item.is_file())
        first.shutdown()

        self.scene.write_bytes(b"ramses-scene-fixture-v2")
        second, _second_provider, _second_helper = self._coordinator(
            cache_limit_bytes=entry_bytes + 128
        )
        second.request(
            profile=self.profile,
            generation=2,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(second.wait_for_idle(3))
        remaining = [item for item in cache_root.iterdir() if item.is_dir()]

        self.assertEqual(second.public_state().state, "ready")
        self.assertEqual(len(remaining), 1)
        self.assertNotEqual(remaining[0].name, first_name)
        self.assertLessEqual(
            sum(item.stat().st_size for item in remaining[0].rglob("*") if item.is_file()),
            entry_bytes + 128,
        )

    def test_cache_miss_without_launch_permission_and_cache_over_budget_are_fallbacks(self) -> None:
        coordinator, provider, helper = self._coordinator()
        coordinator.request(
            profile=self.profile,
            generation=1,
            reduced_motion=False,
            allow_launch=False,
        )
        self.assertTrue(coordinator.wait_for_idle(3))
        self.assertEqual(coordinator.public_state().state, "fallback")
        self.assertEqual(helper.calls, [])
        self.assertFalse((self.root / "out" / "preview-cache").exists())

        limited, limited_provider, limited_helper = self._coordinator(cache_limit_bytes=1)
        limited.request(
            profile=self.profile,
            generation=2,
            reduced_motion=False,
            allow_launch=True,
        )
        self.assertTrue(limited.wait_for_idle(3))
        self.assertEqual(limited.public_state().state, "fallback")
        self.assertEqual(limited_provider.token_count, 0)
        self.assertEqual(len(limited_helper.calls), 1)

    def test_reduced_motion_accepts_exactly_one_static_frame_and_selection_clamps(self) -> None:
        coordinator, _provider, _helper = self._coordinator()
        coordinator.request(
            profile=self.profile,
            generation=1,
            reduced_motion=True,
            allow_launch=True,
        )
        self.assertTrue(coordinator.wait_for_idle(3))
        self.assertEqual(coordinator.public_state().frame_count, 1)
        self.assertTrue(coordinator.select_frame(99))
        self.assertEqual(coordinator.public_state().frame_index, 0)

    def test_public_state_type_is_frozen_slotted_and_path_free(self) -> None:
        from sg_preflight.desktop.preview_coordinator import PreviewPublicState

        state = PreviewPublicState()
        self.assertEqual(
            asdict(state),
            {
                "state": "fallback",
                "token": "",
                "frame_count": 0,
                "frame_index": 0,
                "label": "Static profile preview",
            },
        )
        self.assertFalse(hasattr(state, "__dict__"))


@unittest.skipUnless(PYSIDE_AVAILABLE, "PySide6 is not installed")
class TestPreviewControllerAndQml(unittest.TestCase):
    class FakePreviewCoordinator(QObject):
        state_changed = Signal(object)

        def __init__(self) -> None:
            super().__init__()
            from sg_preflight.desktop.preview_coordinator import PreviewPublicState

            self.state = PreviewPublicState()
            self.requests: list[dict[str, object]] = []
            self.invalidations: list[int] = []
            self.preemptions = 0
            self.selections: list[int] = []
            self.closed = False

        def public_state(self):
            return self.state

        def request_profile(self, profile_id: str, *, generation: int, reduced_motion: bool, allow_launch: bool):
            from sg_preflight.desktop.preview_coordinator import PreviewPublicState, PreviewRequestHandle

            self.requests.append(
                {
                    "profile_id": profile_id,
                    "generation": generation,
                    "reduced_motion": reduced_motion,
                    "allow_launch": allow_launch,
                }
            )
            self.state = PreviewPublicState("ready", "opaque-preview-token-12345", 3, 0, "3D profile preview")
            self.state_changed.emit(self.state)
            return PreviewRequestHandle("fake-request")

        def invalidate(self, *, generation: int) -> None:
            self.invalidations.append(generation)

        def preempt(self) -> None:
            self.preemptions += 1

        def select_frame(self, frame_index: int) -> bool:
            self.selections.append(frame_index)
            return True

        def shutdown(self) -> None:
            self.closed = True

    def test_controller_schedules_only_cache_reuse_at_startup_then_allows_explicit_selection(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        coordinator = _FakeTaskCoordinator()
        preview = self.FakePreviewCoordinator()

        def shell_loader(*, profile_id: str, **_kwargs: object) -> dict[str, object]:
            return {
                "schemaVersion": 1,
                "profileOptions": [{"id": "G45", "label": "BMW G45"}],
                "selectedProfile": {"id": profile_id, "label": "BMW G45"} if profile_id else {},
                "gates": [],
                "selectedGateId": "context",
                "latestLocalRun": {},
                "nextAction": {},
                "activity": [],
                "readOnly": True,
                "isApproval": False,
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G45",
                task_coordinator=coordinator,
                shell_loader=shell_loader,
                preview_coordinator=preview,
            )
            self.assertTrue(controller.initialize())
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            self.assertFalse(preview.requests[-1]["allow_launch"])
            self.assertTrue(controller.selectProfile("G45"))
            self.assertTrue(preview.requests[-1]["allow_launch"])
            self.assertEqual(controller.previewState, "ready")
            self.assertEqual(controller.previewToken, "opaque-preview-token-12345")
            self.assertEqual(controller.previewFrameCount, 3)
            self.assertTrue(controller.selectPreviewFrame(2))
            self.assertEqual(preview.selections, [2])
            from sg_preflight.desktop.preview_coordinator import PreviewPublicState

            preview.state_changed.emit(
                PreviewPublicState("ready", r"C:\private\frame.png", 1, 0, "Private frame")
            )
            self.assertEqual(controller.previewToken, "opaque-preview-token-12345")
            controller.setPreviewReducedMotion(True)
            self.assertTrue(preview.requests[-1]["reduced_motion"])
            self.assertTrue(preview.requests[-1]["allow_launch"])
            controller.shutdown()

        self.assertTrue(preview.closed)

    def test_diagnostic_preempts_preview_before_effect_submission(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G45"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="sgfx_preflight__g45",
                label="Run local QA checks",
                description="Four deterministic packs",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )

            class Record:
                paths = {"summary": str(output / "run-1" / "summary.json")}

            preview = self.FakePreviewCoordinator()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G45",
                task_coordinator=coordinator,
                shell_loader=lambda **_kwargs: {
                    "schemaVersion": 1,
                    "profileOptions": [{"id": "G45", "label": "BMW G45"}],
                    "selectedProfile": {"id": "G45", "label": "BMW G45"},
                    "gates": [],
                    "selectedGateId": "asset",
                    "latestLocalRun": {},
                    "nextAction": {
                        "capabilityId": "diagnostic.run",
                        "actionId": action.action_id,
                        "label": action.label,
                    },
                    "activity": [],
                    "readOnly": True,
                    "isApproval": False,
                },
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_getter=lambda _action_id, _workspace: action,
                action_executor=lambda _action, _workspace: Record(),
                preview_coordinator=preview,
            )
            controller.initialize()
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())

            self.assertTrue(controller.runDiagnostic(action.action_id, ["G45"]))
            self.assertEqual(preview.preemptions, 1)
            controller.shutdown()

    def test_frozen_shutdown_wiring_needs_no_weak_reference(self) -> None:
        from sg_preflight.desktop.qt_quick_app import _wire_shutdown, create_qt_quick_runtime

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = create_qt_quick_runtime(
                workspace=temp_dir,
                initial_profile_id="",
                argv=["sgfx-shutdown-wire-test"],
            )
            try:
                # The slotted runtime cannot be weak-referenced, so connecting the bound method
                # directly fails - exactly the frozen-exe startup crash an operator hit live.
                with self.assertRaises((SystemError, TypeError)):
                    runtime.application.aboutToQuit.connect(runtime.close)
                handler = _wire_shutdown(runtime)
                runtime.application.aboutToQuit.disconnect(handler)
            finally:
                runtime.close()

    def test_preview_requests_defer_while_the_render_slot_is_held(self) -> None:
        import threading

        from PySide6.QtCore import QCoreApplication
        from PySide6.QtGui import QGuiApplication
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.qa_operator_actions import OperatorAction
        from tests.test_qt_quick_core import _FakeTaskCoordinator, _pump_until

        application = QCoreApplication.instance() or QGuiApplication(["sgfx-interlock-test"])
        self.assertIsNotNone(application)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = root / "workspace"
            source = root / "source"
            project = source / "Cars" / "G45"
            output = workspace / "out" / "operator-ui" / "actions"
            project.mkdir(parents=True)
            action = OperatorAction(
                action_id="sgfx_preflight__g45",
                label="Run local QA checks",
                description="Four deterministic packs",
                kind="sgfx_preflight",
                scope="profile",
                ready=True,
                profile_id="G45",
                project_root=str(project),
            )

            class Record:
                paths = {"summary": str(output / "run-1" / "summary.json")}

            release = threading.Event()

            def slow_executor(_action: object, _workspace: object) -> object:
                release.wait(timeout=10)
                return Record()

            preview = self.FakePreviewCoordinator()
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G45",
                task_coordinator=coordinator,
                shell_loader=lambda **_kwargs: {
                    "schemaVersion": 1,
                    "profileOptions": [{"id": "G45", "label": "BMW G45"}],
                    "selectedProfile": {"id": "G45", "label": "BMW G45"},
                    "gates": [],
                    "selectedGateId": "asset",
                    "latestLocalRun": {},
                    "nextAction": {
                        "capabilityId": "diagnostic.run",
                        "actionId": action.action_id,
                        "label": action.label,
                    },
                    "activity": [],
                    "readOnly": True,
                    "isApproval": False,
                },
                diagnostic_read_roots=(source,),
                diagnostic_output_root=output,
                action_getter=lambda _action_id, _workspace: action,
                action_executor=slow_executor,
                preview_coordinator=preview,
            )
            try:
                controller.initialize()
                identity, operation = coordinator.requests[-1]
                coordinator.succeed(identity, operation())

                self.assertTrue(controller.runDiagnostic(action.action_id, ["G45"]))
                self.assertTrue(_pump_until(lambda: controller.capabilityState == "running"))
                requests_before = len(preview.requests)
                # A profile page refresh while the effect holds the render slot must queue the
                # preview instead of racing a second renderer next to the probe (req 22).
                self.assertTrue(controller.selectProfile("G45"))
                identity, operation = coordinator.requests[-1]
                coordinator.succeed(identity, operation())
                self.assertEqual(len(preview.requests), requests_before)

                release.set()
                self.assertTrue(_pump_until(lambda: controller.capabilityState == "completed"))
                self.assertTrue(_pump_until(lambda: len(preview.requests) > requests_before))
                self.assertTrue(preview.requests[-1]["allow_launch"])
            finally:
                release.set()
                controller.shutdown()

    def test_qml_uses_only_opaque_provider_urls_and_bounded_one_revolution_playback(self) -> None:
        root = Path(__file__).resolve().parents[1]
        qml = (
            root / "sg_preflight" / "desktop" / "qml" / "components" / "QaContextPreview.qml"
        ).read_text(encoding="utf-8")

        self.assertIn("image://sgfx-preview/", qml)
        self.assertIn("previewFrameRequested", qml)
        self.assertIn("selectPreviewFrame", (
            root / "sg_preflight" / "desktop" / "qml" / "Main.qml"
        ).read_text(encoding="utf-8"))
        self.assertIn("setPreviewReducedMotion", (
            root / "sg_preflight" / "desktop" / "qml" / "Main.qml"
        ).read_text(encoding="utf-8"))
        self.assertIn("root.visible", qml)
        self.assertIn("!root.reducedMotion", qml)
        self.assertIn("root.previewFrameCount > 1", qml)
        self.assertIn("playbackComplete", qml)
        self.assertNotIn("file://", qml)
        self.assertNotIn(".ramses", qml)
        self.assertNotRegex(qml, re.compile(r"(?i)\b(?:path|command|executable)\b"))

    def test_qml_loads_an_opaque_provider_frame_and_stays_stopped_while_hidden(self) -> None:
        from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            frame = Path(temp_dir) / "frame-000.png"
            image = QImage(64, 32, QImage.Format.Format_RGBA8888)
            image.fill(QColor("#45c9b0"))
            self.assertTrue(image.save(str(frame)))
            runtime = create_qt_quick_runtime(
                workspace=temp_dir,
                initial_profile_id="",
                argv=["sgfx-preview-qml-test"],
            )
            deadline = time.monotonic() + 20
            while runtime.controller.pageState not in {"ready", "error"} and time.monotonic() < deadline:
                runtime.application.processEvents()
                time.sleep(0.005)
            token = "opaque-preview-token-12345"
            self.assertTrue(runtime.preview_image_provider.register(token, (frame,)))
            component = QQmlComponent(
                runtime.engine,
                QUrl.fromLocalFile(
                    str(root / "sg_preflight" / "desktop" / "qml" / "components" / "QaContextPreview.qml")
                ),
            )
            preview = component.createWithInitialProperties(
                {
                    "width": 318,
                    "height": 266,
                    "selectedProfile": {"id": "G45", "label": "BMW G45"},
                    "latestLocalRun": {},
                    "previewState": "ready",
                    "previewToken": token,
                    "previewFrameCount": 1,
                    "previewFrameIndex": 0,
                    "previewLabel": "3D profile preview",
                    "reducedMotion": False,
                }
            )
            if preview is None:
                self.fail(" | ".join(error.toString() for error in component.errors()))
            runtime.application.processEvents()
            preview_image = preview.findChild(QObject, "profilePreviewImage")
            playback = preview.findChild(QObject, "previewPlayback")

            self.assertEqual(preview_image.property("source").toString(), f"image://sgfx-preview/{token}/0")
            self.assertEqual(float(preview_image.property("progress")), 1.0)
            self.assertGreater(float(preview_image.property("paintedWidth")), 0.0)
            self.assertFalse(playback.property("running"))
            preview.deleteLater()
            runtime.close()


if __name__ == "__main__":
    unittest.main()

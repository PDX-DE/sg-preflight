from __future__ import annotations

from collections.abc import Callable
from dataclasses import FrozenInstanceError, dataclass, replace
from datetime import date, datetime, timezone
from enum import Enum
import gc
import inspect
from pathlib import Path
import tempfile
import threading
import time
from types import MappingProxyType
import unittest
from unittest import mock
import weakref

try:
    from PySide6.QtCore import QCoreApplication, QModelIndex, QObject, QThreadPool, Signal, Slot, Qt
    from PySide6.QtTest import QSignalSpy

    def _gui_application():
        # A bare QCoreApplication would poison later in-process Qt Quick tests: the runtime
        # requires a graphical application and Qt allows only one instance per process.
        from PySide6.QtGui import QGuiApplication

        return QGuiApplication([])
except ModuleNotFoundError as error:
    if error.name != "PySide6":
        raise
    raise unittest.SkipTest("PySide6 is not installed") from error

from sg_preflight.shell_registry import HOME_ROUTE_ID, NAVIGATION_GROUP_ORDER
from sg_preflight.surface_registry import SURFACE_DESCRIPTORS


def _pump_until(predicate: Callable[[], bool], timeout_ms: int = 3000) -> bool:
    deadline = time.monotonic() + timeout_ms / 1000
    application = QCoreApplication.instance()
    while not predicate() and time.monotonic() < deadline:
        if application is not None:
            application.processEvents()
        time.sleep(0.001)
    return predicate()


class _CompletionThreadReceiver(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.callback_thread_id = 0
        self.worker_thread_id = 0

    @Slot(object, object)
    def receive(self, _identity: object, payload: object) -> None:
        self.callback_thread_id = threading.get_ident()
        self.worker_thread_id = int(payload)


class _PayloadStatus(Enum):
    AVAILABLE = "available"


@dataclass(frozen=True)
class _PayloadFixture:
    report_path: Path
    status: _PayloadStatus
    count: int
    revision: str
    provenance: str
    observed_on: date
    observed_at: datetime
    labels: set[str]


@dataclass(frozen=True)
class _PayloadWithExecutionFields:
    command: tuple[str, ...]
    environment: dict[str, str]
    executable: Path
    capability: str
    revision: str


class _FakeTaskCoordinator(QObject):
    task_succeeded = Signal(object, object)
    task_failed = Signal(object, object)

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[tuple[object, object]] = []
        self.active: set[object] = set()
        self.cancelled: list[object] = []
        self.reject_next = False
        self.shutdown_calls: list[int] = []

    def submit(self, identity: object, operation: object) -> bool:
        if self.reject_next:
            self.reject_next = False
            return False
        if identity in self.active:
            return False
        self.active.add(identity)
        self.requests.append((identity, operation))
        return True

    def succeed(self, identity: object, payload: object) -> None:
        self.active.discard(identity)
        self.task_succeeded.emit(identity, payload)

    def fail(self, identity: object, failure: object) -> None:
        self.active.discard(identity)
        self.task_failed.emit(identity, failure)

    def cancel(self, identity: object) -> bool:
        if identity not in self.active:
            return False
        self.active.remove(identity)
        self.cancelled.append(identity)
        return True

    def shutdown(self, timeout_ms: int = 1000) -> bool:
        self.shutdown_calls.append(timeout_ms)
        self.active.clear()
        return True


class TestSurfaceRegistryModel(unittest.TestCase):
    def setUp(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRegistryModel

        self.model = SurfaceRegistryModel()
        self.role_items = tuple(
            (int(role), bytes(name)) for role, name in self.model.roleNames().items()
        )

    def test_roles_use_the_exact_qml_names_and_integer_sequence(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRole

        first_role = int(Qt.ItemDataRole.UserRole) + 1
        expected_enum = (
            ("SurfaceId", first_role),
            ("Title", first_role + 1),
            ("Subtitle", first_role + 2),
            ("Group", first_role + 3),
            ("RendererKind", first_role + 4),
            ("Operational", first_role + 5),
        )
        expected_roles = (
            (first_role, b"surfaceId"),
            (first_role + 1, b"title"),
            (first_role + 2, b"subtitle"),
            (first_role + 3, b"group"),
            (first_role + 4, b"rendererKind"),
            (first_role + 5, b"operational"),
        )

        self.assertEqual(tuple((role.name, int(role)) for role in SurfaceRole), expected_enum)
        self.assertEqual(self.role_items, expected_roles)

    def test_constructor_snapshots_mutable_descriptor_sequences(self) -> None:
        from sg_preflight.desktop.surface_model import SurfaceRegistryModel, SurfaceRole

        source_descriptors = list(SURFACE_DESCRIPTORS[:2])
        model = SurfaceRegistryModel(source_descriptors)

        source_descriptors.clear()

        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(
            model.data(model.index(1, 0), int(SurfaceRole.SurfaceId)),
            SURFACE_DESCRIPTORS[1].surface_id,
        )

    def test_rows_project_every_descriptor_value_in_stable_order(self) -> None:
        expected_rows = tuple(
            (
                descriptor.surface_id,
                descriptor.title,
                descriptor.subtitle,
                descriptor.navigation_group,
                descriptor.renderer_kind,
                descriptor.operational,
            )
            for descriptor in SURFACE_DESCRIPTORS
        )
        actual_rows = tuple(
            tuple(
                self.model.data(self.model.index(row, 0), role)
                for role, _name in self.role_items
            )
            for row in range(self.model.rowCount())
        )

        self.assertIs(type(SURFACE_DESCRIPTORS), tuple)
        self.assertEqual(self.model.rowCount(), 19)
        self.assertEqual(self.model.count, 19)
        self.assertEqual(actual_rows, expected_rows)
        self.assertNotIn(HOME_ROUTE_ID, tuple(row[0] for row in actual_rows))
        self.assertEqual({row[3] for row in actual_rows}, set(NAVIGATION_GROUP_ORDER))
        self.assertIn("Evidence", {row[3] for row in actual_rows})

    def test_invalid_indexes_roles_and_default_display_role_return_none(self) -> None:
        first_role = self.role_items[0][0]
        first_index = self.model.index(0, 0)
        out_of_range_index = self.model.createIndex(self.model.rowCount(), 0)

        self.assertTrue(first_index.isValid())
        self.assertTrue(out_of_range_index.isValid())
        self.assertIsNone(self.model.data(QModelIndex(), first_role))
        self.assertIsNone(self.model.data(out_of_range_index, first_role))
        self.assertIsNone(self.model.data(first_index, int(Qt.ItemDataRole.UserRole) + 99))
        self.assertIsNone(self.model.data(first_index))

    def test_valid_parent_has_no_rows(self) -> None:
        parent = self.model.index(0, 0)

        self.assertTrue(parent.isValid())
        self.assertEqual(self.model.rowCount(parent), 0)

    def test_count_property_is_constant_and_model_has_no_mutation_slots(self) -> None:
        meta_object = self.model.metaObject()
        count_property = meta_object.property(meta_object.indexOfProperty("count"))
        own_methods = tuple(
            bytes(meta_object.method(index).methodSignature())
            for index in range(meta_object.methodOffset(), meta_object.methodCount())
        )

        self.assertTrue(count_property.isValid())
        self.assertTrue(count_property.isReadable())
        self.assertTrue(count_property.isConstant())
        self.assertFalse(count_property.isWritable())
        self.assertEqual(count_property.read(self.model), 19)
        self.assertEqual(own_methods, ())


class TestShellRegistryModel(unittest.TestCase):
    def test_roles_order_and_immutable_shell_metadata_are_exact(self) -> None:
        from sg_preflight.desktop.shell_model import (
            QT_QUICK_SHORTCUT_ACTIONS,
            ShellRegistryModel,
            ShellRole,
        )
        from sg_preflight.shell_registry import HOME_HUB_TILES

        model = ShellRegistryModel()
        roles = tuple((int(role), bytes(name)) for role, name in model.roleNames().items())
        first_role = int(Qt.ItemDataRole.UserRole) + 1
        self.assertEqual(
            roles,
            (
                (first_role, b"routeId"),
                (first_role + 1, b"title"),
                (first_role + 2, b"subtitle"),
                (first_role + 3, b"group"),
                (first_role + 4, b"rendererKind"),
                (first_role + 5, b"operational"),
            ),
        )
        self.assertEqual(tuple(int(role) for role in ShellRole), tuple(range(first_role, first_role + 6)))
        route_ids = tuple(
            model.data(model.index(row, 0), int(ShellRole.RouteId))
            for row in range(model.rowCount())
        )
        expected_descriptors = tuple(
            descriptor.surface_id
            for group in NAVIGATION_GROUP_ORDER
            for descriptor in SURFACE_DESCRIPTORS
            if descriptor.navigation_group == group
        )
        self.assertEqual(route_ids, (HOME_ROUTE_ID,) + expected_descriptors)
        self.assertEqual(
            tuple((item["group"], item["routeId"]) for item in model.routes),
            (
                ("Current Session", "home"),
                ("Current Session", "full-qa-pass"),
                ("Manual Review", "manual-review"),
                ("Manual Review", "screenshot-test-state"),
                ("Manual Review", "country-variant-coverage"),
                ("Evidence", "delivery-checklist"),
                ("Evidence", "disabled-tests"),
                ("Evidence", "api-version-coverage"),
                ("Evidence", "export-size-trend"),
                ("Evidence", "operator-handoff"),
                ("History", "batch-full-qa-pass"),
                ("History", "cross-car-comparison"),
                ("History", "daily-digest"),
                ("History", "team-digest-board"),
                ("Tools", "setup-doctor"),
                ("Tools", "onboarding-guide"),
                ("Tools", "qa-workflows"),
                ("Tools", "bmw-process"),
                ("Tools", "risk-score"),
                ("Tools", "about"),
            ),
        )
        self.assertEqual(model.count, 20)
        self.assertEqual(tuple(model.groupOrder), NAVIGATION_GROUP_ORDER)
        self.assertEqual(
            tuple(item["routeId"] for item in model.homeTiles),
            tuple(item.surface_id for item in HOME_HUB_TILES),
        )
        self.assertEqual(
            tuple((item["key"], item["label"]) for item in model.shortcuts),
            QT_QUICK_SHORTCUT_ACTIONS,
        )
        self.assertEqual(dict(QT_QUICK_SHORTCUT_ACTIONS)["Esc"], "Close the topmost overlay or return Home")
        meta_object = model.metaObject()
        own_methods = tuple(
            bytes(meta_object.method(index).methodSignature())
            for index in range(meta_object.methodOffset(), meta_object.methodCount())
        )
        self.assertEqual(own_methods, ())
        for name in ("count", "groupOrder", "homeTiles", "shortcuts"):
            qt_property = meta_object.property(meta_object.indexOfProperty(name))
            self.assertTrue(qt_property.isConstant())
            self.assertFalse(qt_property.isWritable())


class TestPageTaskCoordinator(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or _gui_application()

    def _coordinator(self, *, max_thread_count: int = 2):
        from sg_preflight.desktop.task_pool import PageTaskCoordinator

        coordinator = PageTaskCoordinator(max_thread_count=max_thread_count)
        self.addCleanup(lambda: coordinator.shutdown(timeout_ms=1000))
        return coordinator

    def test_task_values_are_frozen_slotted_and_use_the_full_identity(self) -> None:
        from sg_preflight.desktop.task_pool import TaskFailure, TaskIdentity

        identity = TaskIdentity(7, "G65", "delivery-checklist", "load")
        failure = TaskFailure(
            "page_reader_failed",
            "The local page evidence could not be loaded.",
            "PermissionError",
        )

        self.assertFalse(hasattr(identity, "__dict__"))
        self.assertFalse(hasattr(failure, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            identity.generation = 8
        with self.assertRaises(FrozenInstanceError):
            failure.code = "changed"
        for field_name, changed_value in (
            ("generation", 8),
            ("profile_id", "G70"),
            ("page_id", "risk-score"),
            ("operation", "refresh"),
        ):
            with self.subTest(field=field_name):
                self.assertNotEqual(identity, replace(identity, **{field_name: changed_value}))

    def test_default_coordinator_constructs_a_private_two_thread_pool(self) -> None:
        from sg_preflight.desktop import task_pool

        class PoolFactory:
            @staticmethod
            def globalInstance() -> object:
                raise AssertionError("global thread pool must stay unused")

            def __new__(cls, parent: QObject) -> QThreadPool:
                return QThreadPool(parent)

        with mock.patch.object(task_pool, "QThreadPool", PoolFactory):
            coordinator = task_pool.PageTaskCoordinator()
        self.addCleanup(lambda: coordinator.shutdown(timeout_ms=1000))

        self.assertEqual(coordinator.max_thread_count, 2)
        self.assertEqual(coordinator._pool.maxThreadCount(), 2)
        self.assertIs(coordinator._pool.parent(), coordinator)
        self.assertEqual(coordinator.active_count, 0)

    def test_default_pool_never_runs_more_than_two_of_three_gated_readers(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator()
        release = threading.Event()
        two_started = threading.Event()
        counter_lock = threading.Lock()
        current = 0
        peak = 0
        started = 0

        def gated_reader() -> str:
            nonlocal current, peak, started
            with counter_lock:
                current += 1
                started += 1
                peak = max(peak, current)
                if started == 2:
                    two_started.set()
            try:
                if not release.wait(3):
                    raise TimeoutError("gated reader release timed out")
                return "complete"
            finally:
                with counter_lock:
                    current -= 1

        spy = QSignalSpy(coordinator.task_succeeded)
        for generation in range(3):
            self.assertTrue(
                coordinator.submit(
                    TaskIdentity(generation, "G65", "delivery-checklist", "load"),
                    gated_reader,
                )
            )

        try:
            self.assertTrue(two_started.wait(1))
            time.sleep(0.05)
            with counter_lock:
                self.assertEqual(started, 2)
                self.assertEqual(peak, 2)
            self.assertEqual(coordinator.active_count, 3)
        finally:
            release.set()

        self.assertTrue(_pump_until(lambda: spy.count() == 3))
        self.assertEqual(peak, 2)
        self.assertEqual(coordinator.active_count, 0)

    def test_reader_runs_off_gui_thread_and_completion_is_queued_to_gui(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator()
        identity = TaskIdentity(1, "G65", "delivery-checklist", "load")
        receiver = _CompletionThreadReceiver()
        coordinator.task_succeeded.connect(receiver.receive)
        spy = QSignalSpy(coordinator.task_succeeded)
        gui_thread_id = threading.get_ident()

        self.assertTrue(coordinator.submit(identity, threading.get_ident))
        self.assertTrue(_pump_until(lambda: spy.count() == 1))
        self.assertEqual(receiver.callback_thread_id, gui_thread_id)
        self.assertNotEqual(receiver.worker_thread_id, gui_thread_id)
        self.assertEqual(coordinator.active_count, 0)

    def test_duplicate_full_identity_is_coalesced_but_other_operations_are_not(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator()
        release = threading.Event()
        started = threading.Event()
        identity = TaskIdentity(2, "G65", "disabled-tests", "load")

        def delayed_result() -> str:
            started.set()
            if not release.wait(3):
                raise TimeoutError("delayed reader release timed out")
            return "complete"

        spy = QSignalSpy(coordinator.task_succeeded)
        self.assertTrue(coordinator.submit(identity, delayed_result))
        self.assertTrue(started.wait(1))
        self.assertFalse(coordinator.submit(identity, delayed_result))
        self.assertTrue(coordinator.submit(replace(identity, operation="refresh"), delayed_result))
        self.assertEqual(coordinator.active_count, 2)
        release.set()

        self.assertTrue(_pump_until(lambda: spy.count() == 2))
        self.assertEqual(coordinator.active_count, 0)

    def test_worker_failure_is_sanitized_and_clears_active_state(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator()
        identity = TaskIdentity(3, "G65", "risk-score", "load")
        spy = QSignalSpy(coordinator.task_failed)

        def fail_with_private_detail() -> None:
            raise PermissionError(r"denied C:\operator-private\runtime --bearer secret-value")

        self.assertTrue(coordinator.submit(identity, fail_with_private_detail))
        self.assertTrue(_pump_until(lambda: spy.count() == 1))
        completed_identity, failure = spy.at(0)
        rendered = repr(failure).casefold()

        self.assertEqual(completed_identity, identity)
        self.assertEqual(failure.code, "page_reader_failed")
        self.assertEqual(failure.summary, "The local page evidence could not be loaded.")
        self.assertEqual(failure.error_type, "PermissionError")
        for fragment in ("operator-private", "secret-value", "c:\\"):
            self.assertNotIn(fragment, rendered)
        self.assertEqual(coordinator.active_count, 0)

    def test_task_cancelled_before_execution_never_starts_its_reader(self) -> None:
        from sg_preflight.desktop.task_pool import _PageTask, TaskIdentity

        executed = threading.Event()
        task = _PageTask(
            TaskIdentity(4, "G65", "risk-score", "load"),
            executed.set,
        )

        task.cancel()
        task.run()

        self.assertFalse(executed.is_set())

    def test_cancel_releases_one_identity_and_ignores_its_late_completion(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator(max_thread_count=1)
        identity = TaskIdentity(4, "G65", "full-qa-pass", "action_readiness")
        started = threading.Event()
        release = threading.Event()
        spy = QSignalSpy(coordinator.task_succeeded)

        def gated_reader() -> str:
            started.set()
            release.wait(3)
            return "stale"

        self.assertTrue(coordinator.submit(identity, gated_reader))
        stale_task = coordinator._active[identity]
        self.assertTrue(started.wait(1))
        self.assertTrue(coordinator.cancel(identity))
        self.assertEqual(coordinator.active_count, 0)
        self.assertFalse(coordinator.cancel(identity))
        current_release = threading.Event()
        self.assertTrue(
            coordinator.submit(
                identity,
                lambda: current_release.wait(3) and "current",
            )
        )
        coordinator._complete(stale_task, identity, True, "stale")
        self.assertEqual(coordinator.active_count, 1)
        self.assertEqual(spy.count(), 0)

        current_release.set()
        self.assertTrue(_pump_until(lambda: spy.count() == 1))
        self.assertEqual(spy.at(0), [identity, "current"])

        release.set()
        self.assertTrue(coordinator.wait_for_done(1000))
        self.application.processEvents()
        self.assertEqual(spy.count(), 1)

    def test_shutdown_cancels_queued_work_is_bounded_and_rejects_new_tasks(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator(max_thread_count=1)
        running_started = threading.Event()
        running_release = threading.Event()
        queued_executed = threading.Event()
        finalized_on: list[int] = []

        def running_reader() -> None:
            running_started.set()
            running_release.wait(3)

        self.assertTrue(
            coordinator.submit(
                TaskIdentity(4, "G65", "full-qa-pass", "load"),
                running_reader,
            )
        )
        self.assertTrue(running_started.wait(1))
        self.assertTrue(
            coordinator.submit(
                TaskIdentity(4, "G65", "risk-score", "load"),
                queued_executed.set,
            )
        )
        task_references = tuple(weakref.ref(task) for task in coordinator._active.values())
        for task in tuple(coordinator._active.values()):
            weakref.finalize(task, lambda: finalized_on.append(threading.get_ident()))
        del task

        started_at = time.monotonic()
        try:
            self.assertTrue(coordinator.shutdown(timeout_ms=100))
            self.assertLess(time.monotonic() - started_at, 0.6)
            self.assertFalse(queued_executed.is_set())
            self.assertEqual(coordinator.active_count, 0)
            self.assertFalse(
                coordinator.submit(
                    TaskIdentity(5, "G65", "risk-score", "load"),
                    lambda: None,
                )
            )
        finally:
            running_release.set()
        self.assertTrue(coordinator.wait_for_done(1000))
        self.assertFalse(queued_executed.is_set())
        gc.collect()
        self.assertTrue(all(reference() is None for reference in task_references))
        self.assertEqual(finalized_on, [threading.get_ident()] * 2)

    def test_completed_wrapper_releases_python_ownership_without_unbounded_retention(self) -> None:
        from sg_preflight.desktop.task_pool import TaskIdentity

        coordinator = self._coordinator()
        identity = TaskIdentity(6, "G65", "risk-score", "load")
        spy = QSignalSpy(coordinator.task_succeeded)
        finalized_on: list[int] = []

        self.assertTrue(coordinator.submit(identity, lambda: "complete"))
        task = coordinator._active[identity]
        task_reference = weakref.ref(task)
        weakref.finalize(task, lambda: finalized_on.append(threading.get_ident()))
        self.assertTrue(_pump_until(lambda: spy.count() == 1))
        self.assertFalse(hasattr(coordinator, "_retained"))
        self.assertTrue(coordinator.wait_for_done(1000))
        self.application.processEvents()
        del task
        for _attempt in range(10):
            self.application.processEvents()
            gc.collect()
            if task_reference() is None:
                break

        self.assertIsNone(task_reference())
        self.assertEqual(finalized_on, [threading.get_ident()])


class TestPayloadAdapter(unittest.TestCase):
    def test_adapter_preserves_safe_structures_and_workspace_relative_labels(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        revision = "0123456789abcdef0123456789abcdef01234567"
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            fixture = _PayloadFixture(
                report_path=workspace / "evidence" / "result.json",
                status=_PayloadStatus.AVAILABLE,
                count=3,
                revision=revision,
                provenance="local_scan",
                observed_on=date(2026, 7, 11),
                observed_at=datetime(2026, 7, 11, 8, 30, tzinfo=timezone.utc),
                labels={"beta", "alpha"},
            )

            adapted = adapt_page_payload(
                {"fixture": fixture, "source": workspace / "evidence" / "result.json"},
                workspace=workspace,
            )

        self.assertEqual(
            adapted,
            {
                "fixture": {
                    "report_path": "evidence/result.json",
                    "status": "available",
                    "count": 3,
                    "revision": revision,
                    "provenance": "local_scan",
                    "observed_on": "2026-07-11",
                    "observed_at": "2026-07-11T08:30:00+00:00",
                    "labels": ["alpha", "beta"],
                },
                "source": "evidence/result.json",
            },
        )

    def test_adapter_orders_sets_deterministically_and_reduces_external_paths(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir).resolve()
            outside = workspace.parent / "operator-private" / "evidence.xlsx"

            first = adapt_page_payload(
                {"labels": {"charlie", "alpha", "bravo"}, "path": outside},
                workspace=workspace,
            )
            second = adapt_page_payload(
                {"labels": {"bravo", "charlie", "alpha"}, "path": outside},
                workspace=workspace,
            )

        self.assertEqual(first, second)
        self.assertEqual(first["labels"], ["alpha", "bravo", "charlie"])
        self.assertEqual(first["path"], "evidence.xlsx")
        self.assertNotIn("operator-private", repr(first))

    def test_adapter_omits_execution_environment_executable_and_capability_fields_recursively(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        revision = "abc123"
        adapted = adapt_page_payload(
            {
                "command": ["secret-tool", "--token", "value"],
                "environment": {"TOKEN": "value"},
                "executable": Path(r"C:\private\secret-tool.exe"),
                "capability": "launch arbitrary process",
                "nested": {
                    "command_line": "private --secret",
                    "reader_command_status": "private-command-status",
                    "environment_status": {"TOKEN": "available"},
                    "safe_environment_summary": "private-environment-summary",
                    "executable_path": r"C:\private\tool.exe",
                    "runtime_executable_status": "private-executable-status",
                    "capability_flags": ["write", "network"],
                    "read_capability_flags": ["private-capability"],
                    "revision": revision,
                },
                "items": [
                    _PayloadWithExecutionFields(
                        command=("private-command",),
                        environment={"PRIVATE": "private-environment"},
                        executable=Path(r"C:\private\runner.exe"),
                        capability="repository-write",
                        revision=revision,
                    )
                ],
            },
            workspace=Path.cwd(),
        )

        self.assertEqual(adapted, {"nested": {"revision": revision}, "items": [{"revision": revision}]})
        rendered = repr(adapted).casefold()
        for fragment in ("secret-tool", "token", "private", "runner", "repository-write"):
            self.assertNotIn(fragment, rendered)

    def test_adapter_redacts_sensitive_containers_and_inline_secrets(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        adapted = adapt_page_payload(
            {
                "token": "short-token",
                "credential_bundle": ["account", "short-credential"],
                "nested": {
                    "password": "tiny-password",
                    "authorization_data": {"value": "short-authorization"},
                    "operator_token_value": "nested-token",
                    "local_credential_bundle": {"value": "nested-credential"},
                    "summary": (
                        "token=inline-token password:inline-password "
                        "Authorization: Bearer bearer-secret status available"
                    ),
                    "status": "available",
                },
            },
            workspace=Path.cwd(),
        )

        self.assertEqual(adapted["token"], "****")
        self.assertEqual(adapted["credential_bundle"], "****")
        self.assertEqual(adapted["nested"]["password"], "****")
        self.assertEqual(adapted["nested"]["authorization_data"], "****")
        self.assertEqual(adapted["nested"]["operator_token_value"], "****")
        self.assertEqual(adapted["nested"]["local_credential_bundle"], "****")
        self.assertEqual(adapted["nested"]["status"], "available")
        rendered = repr(adapted).casefold()
        for fragment in (
            "short-token",
            "short-credential",
            "tiny-password",
            "short-authorization",
            "nested-token",
            "nested-credential",
            "inline-token",
            "inline-password",
            "bearer-secret",
        ):
            self.assertNotIn(fragment, rendered)

    def test_adapter_redacts_every_scheme_url_and_embedded_absolute_path(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        raw_urls = (
            "https://user:pass@example.invalid/private",
            "http://example.invalid/private",
            "ftp://example.invalid/private",
            "file://server/private/report.json",
            "sgfx+local://private/operation",
        )
        adapted = adapt_page_payload(
            {
                "summary": (
                    "Read C:\\operator-private\\first.json, "
                    "C:\\Operator Private\\reports with spaces\\fourth report.json, "
                    "\\\\fileserver\\share\\second.json and /home/operator/third.json; "
                    "also /secret.txt; "
                    + " ".join(raw_urls)
                ),
                "network_notes": (
                    r"network \\rootonly-server\rootonly-share; "
                    r"network \\dotted-server\dotted-share."
                ),
                "links": list(raw_urls),
                "url": raw_urls[0],
                "report_path": raw_urls[3],
            },
            workspace=Path.cwd(),
        )

        self.assertNotIn("url", adapted)
        self.assertEqual(adapted["links"], ["$EXTERNAL_LINK"] * len(raw_urls))
        self.assertEqual(adapted["report_path"], "$EXTERNAL_LINK")
        self.assertGreaterEqual(adapted["summary"].count("$EXTERNAL_LINK"), len(raw_urls))
        self.assertIn("first.json", adapted["summary"])
        self.assertIn("second.json", adapted["summary"])
        self.assertIn("third.json", adapted["summary"])
        self.assertIn("fourth report.json", adapted["summary"])
        self.assertIn("secret.txt", adapted["summary"])
        rendered = repr(adapted).casefold()
        for fragment in (
            "example.invalid",
            "user:pass",
            "fileserver",
            "/home/operator",
            "operator private",
            "reports with spaces",
            "rootonly-server",
            "rootonly-share",
            "dotted-server",
            "dotted-share",
            "/secret.txt",
            "c:\\",
        ):
            self.assertNotIn(fragment, rendered)

    def test_adapter_inspects_mapping_keys_before_emitting_them(self) -> None:
        from sg_preflight.desktop.payload_adapter import adapt_page_payload

        raw_fragments = (
            "https://example.invalid/key",
            r"C:\operator-private\key",
            r"C:\Operator Private\key with spaces.txt",
            r"\\key-server\key-share",
            r"\\dotted-key-server\dotted-key-share.",
            "/home/operator/private/key",
            "/secret-key",
            "Authorization: Bearer bearer-key-secret",
            "password=inline-key-secret",
        )
        payload = {fragment: "otherwise-safe" for fragment in raw_fragments}
        payload["revision"] = "abc123"

        adapted = adapt_page_payload(payload, workspace=Path.cwd())

        self.assertEqual(adapted, {"revision": "abc123"})
        rendered = repr(adapted).casefold()
        for fragment in raw_fragments:
            self.assertNotIn(fragment.casefold(), rendered)


class TestDesktopController(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or _gui_application()

    def _controller(
        self,
        workspace: Path,
        *,
        initial_profile_id: str = "G65",
        loader: object | None = None,
        resolver: object | None = None,
        shell_loader: object | None = None,
    ):
        from sg_preflight.desktop.qt_quick_controller import DesktopController

        coordinator = _FakeTaskCoordinator()
        page_loader = loader or mock.Mock(
            return_value=MappingProxyType({"id": "delivery-checklist", "rows": [1]})
        )
        profile_resolver = resolver or mock.Mock(return_value="G65")
        shell_context_loader = shell_loader or mock.Mock(
            return_value={
                "status": "not_run",
                "profile_options": [
                    {"id": "G65", "label": "G65"},
                    {"id": "G70", "label": "G70"},
                ],
                "selected_profile_id": initial_profile_id or "G65",
            }
        )
        controller = DesktopController(
            workspace=workspace,
            initial_profile_id=initial_profile_id,
            task_coordinator=coordinator,
            page_loader=page_loader,
            profile_resolver=profile_resolver,
            shell_loader=shell_context_loader,
        )
        return controller, coordinator, page_loader, profile_resolver

    @staticmethod
    def _error_values(controller: QObject) -> tuple[object, ...]:
        return (
            controller.errorCode,
            controller.errorTitle,
            controller.errorSummary,
            controller.errorRetryable,
            controller.errorRecoveryAction,
        )

    def test_ui_error_contract_is_frozen_slotted_canonical_and_uses_one_notify_signal(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import (
            EMPTY_UI_ERROR,
            UI_ERROR_DEFINITIONS,
            DesktopController,
            UiError,
        )

        expected_definitions = {
            "qml_resource_missing": (
                "Interface unavailable",
                "The Qt Quick interface files are unavailable.",
                False,
                "launch_clean",
            ),
            "qml_engine_load_failed": (
                "Interface unavailable",
                "The Qt Quick interface could not be initialized.",
                True,
                "retry",
            ),
            "page_reader_failed": (
                "Evidence unavailable",
                "The local page evidence could not be loaded.",
                True,
                "retry",
            ),
            "page_payload_invalid": (
                "Evidence unavailable",
                "The page evidence has an unsupported shape.",
                False,
                "open_clean",
            ),
            "action_rejected": (
                "Action unavailable",
                "This action is not available from the current page.",
                False,
                "dismiss",
            ),
            "grafiks_missing": (
                "3D inspection unavailable",
                "3D inspection is unavailable in this installation.",
                False,
                "stay_clean",
            ),
            "grafiks_runtime_invalid": (
                "3D inspection unavailable",
                "The 3D inspection runtime is incomplete.",
                False,
                "stay_clean",
            ),
            "grafiks_spawn_failed": (
                "3D inspection unavailable",
                "3D inspection could not be started.",
                True,
                "retry",
            ),
            "grafiks_early_exit": (
                "3D inspection unavailable",
                "3D inspection stopped during startup.",
                True,
                "retry",
            ),
        }
        self.assertEqual(UI_ERROR_DEFINITIONS, expected_definitions)
        self.assertEqual(EMPTY_UI_ERROR, UiError("", "", "", False, ""))
        self.assertFalse(hasattr(EMPTY_UI_ERROR, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            EMPTY_UI_ERROR.code = "changed"

        meta_object = DesktopController.staticMetaObject
        notify_signatures = set()
        for property_name in (
            "errorCode",
            "errorTitle",
            "errorSummary",
            "errorRetryable",
            "errorRecoveryAction",
        ):
            qt_property = meta_object.property(meta_object.indexOfProperty(property_name))
            self.assertTrue(qt_property.isValid())
            self.assertTrue(qt_property.isReadable())
            self.assertFalse(qt_property.isWritable())
            notify_signatures.add(bytes(qt_property.notifySignal().methodSignature()))
        self.assertEqual(notify_signatures, {b"errorChanged()"})

    def test_page_state_and_operation_properties_use_matching_notify_signals(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, _coordinator, _loader, _resolver = self._controller(Path(temp_dir))

        meta_object = controller.metaObject()
        actual = {
            name: bytes(
                meta_object.property(meta_object.indexOfProperty(name))
                .notifySignal()
                .methodSignature()
            )
            for name in ("pageState", "currentOperation")
        }

        self.assertEqual(
            actual,
            {
                "pageState": b"pageStateChanged()",
                "currentOperation": b"operationChanged()",
            },
        )

    def test_construction_is_reader_free_and_starts_on_home(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, loader, resolver = self._controller(Path(temp_dir))

        loader.assert_not_called()
        resolver.assert_not_called()
        self.assertEqual(coordinator.requests, [])
        self.assertEqual(controller.currentRouteId, "home")
        self.assertEqual(controller.currentPageId, "")
        self.assertEqual(controller.currentProfileId, "G65")
        self.assertEqual(controller.workspaceStatus, "unresolved")
        self.assertEqual(controller.workspaceDisplayLabel, "Unresolved")
        self.assertEqual(controller.workspaceCandidateLabel, Path(temp_dir).name)
        self.assertEqual(controller.pageTitle, "QA overview")
        self.assertTrue(controller.pageSubtitle)
        self.assertEqual(controller.pageState, "idle")
        self.assertEqual(controller.currentPayload, {})
        self.assertEqual(self._error_values(controller), ("", "", "", False, ""))

    def test_invalid_initial_profile_is_rejected_before_it_can_be_observed(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController

        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "initial_profile_id"):
                DesktopController(workspace=temp_dir, initial_profile_id=r"..\private")

    def test_lazy_load_uses_keyword_page_first_arguments_then_cache_refresh_and_profile_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            loader = mock.Mock(
                return_value=MappingProxyType(
                    {
                        "id": "delivery-checklist",
                        "status": "available",
                        "data_available": True,
                        "summary": "delivery fixture",
                        "payload": {
                            "status": "available",
                            "data_available": True,
                            "summary": "delivery fixture",
                            "checks": [
                                {
                                    "key": "fixture",
                                    "label": "Fixture row",
                                    "status": "available",
                                    "raw_value": "1",
                                }
                            ],
                        },
                    }
                )
            )
            controller, coordinator, _loader, _resolver = self._controller(
                workspace,
                loader=loader,
            )
            self.assertTrue(controller.initialize())
            shell_identity, shell_operation = coordinator.requests[-1]
            coordinator.succeed(shell_identity, shell_operation())

            self.assertTrue(controller.navigate("delivery-checklist"))
            self.assertFalse(controller.navigate("delivery-checklist"))
            identity, operation = coordinator.requests[-1]
            self.assertEqual(
                (
                    identity.generation,
                    identity.profile_id,
                    identity.page_id,
                    identity.operation,
                ),
                (2, "G65", "delivery-checklist", "load"),
            )
            self.assertEqual(controller.pageState, "loading")
            self.assertNotIn("self", operation.__code__.co_freevars)
            self.assertNotIn(controller, tuple(cell.cell_contents for cell in operation.__closure__ or ()))
            loader.assert_not_called()

            raw_payload = operation()
            loader.assert_called_once_with(
                page_id="delivery-checklist",
                profile_id="G65",
                workspace=workspace.resolve(),
                bmw_root=None,
            )
            coordinator.succeed(identity, raw_payload)
            self.assertEqual(controller.pageState, "ready")
            self.assertIs(type(controller.currentPayload), dict)
            self.assertEqual(controller.currentPayload["visibleItems"][0]["value"], "1")

            self.assertTrue(controller.navigate("delivery-checklist"))
            self.assertEqual(len(coordinator.requests), 2)
            self.assertEqual(controller.pageState, "ready")

            self.assertTrue(controller.refresh())
            refresh_identity, _refresh_operation = coordinator.requests[-1]
            self.assertEqual(refresh_identity.operation, "refresh")
            self.assertGreater(refresh_identity.generation, identity.generation)

            self.assertTrue(controller.selectProfile("G70"))
            profile_identity, _profile_operation = coordinator.requests[-1]

        self.assertEqual(profile_identity.profile_id, "G70")
        self.assertEqual(profile_identity.page_id, "delivery-checklist")
        self.assertEqual(profile_identity.operation, "load")
        self.assertGreater(profile_identity.generation, refresh_identity.generation)
        self.assertEqual(controller.currentProfileId, "G70")

    def test_initialize_defers_profile_resolution_inside_shell_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            resolver = mock.Mock(return_value="G70")
            shell_loader = mock.Mock(
                return_value={
                    "status": "not_run",
                    "profile_options": [{"id": "G70", "label": "G70"}],
                    "selected_profile_id": "G70",
                }
            )
            controller, coordinator, loader, _resolver = self._controller(
                workspace,
                initial_profile_id="",
                resolver=resolver,
                shell_loader=shell_loader,
            )

            self.assertEqual(coordinator.requests, [])
            self.assertTrue(controller.initialize())
            self.assertFalse(controller.initialize())
            self.assertFalse(controller.navigate("delivery-checklist"))
            self.assertEqual(len(coordinator.requests), 1)
            identity, operation = coordinator.requests[0]
            self.assertEqual(identity.operation, "shell_context")
            resolver.assert_not_called()

            resolved_context = operation()
            shell_loader.assert_called_once_with(
                workspace=workspace.resolve(),
                profile_id="",
                bmw_root=None,
            )
            coordinator.succeed(identity, resolved_context)

        loader.assert_not_called()
        self.assertEqual(controller.currentProfileId, "G70")
        self.assertEqual(controller.pageState, "ready")

    def test_setup_and_onboarding_routes_are_reachable_without_a_selected_profile(self) -> None:
        for route_id in ("setup-doctor", "onboarding-guide"):
            with self.subTest(route_id=route_id), tempfile.TemporaryDirectory() as temp_dir:
                workspace = Path(temp_dir)
                shell_loader = mock.Mock(
                    return_value={
                        "status": "not_run",
                        "profile_options": [{"id": "G65", "label": "G65"}],
                        "selected_profile_id": "",
                    }
                )
                controller, coordinator, loader, _resolver = self._controller(
                    workspace,
                    initial_profile_id="",
                    shell_loader=shell_loader,
                )
                self.assertTrue(controller.initialize())
                shell_identity, shell_operation = coordinator.requests[-1]
                coordinator.succeed(shell_identity, shell_operation())
                self.assertEqual(controller.currentProfileId, "")

                self.assertTrue(controller.navigate(route_id))
                page_identity, _page_operation = coordinator.requests[-1]

                self.assertEqual(page_identity.profile_id, "")
                self.assertEqual(page_identity.page_id, route_id)
                self.assertEqual(controller.currentRouteId, route_id)
                loader.assert_not_called()

        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(
                Path(temp_dir),
                initial_profile_id="",
                shell_loader=mock.Mock(
                    return_value={
                        "status": "not_run",
                        "profile_options": [{"id": "G65", "label": "G65"}],
                        "selected_profile_id": "",
                    }
                ),
            )
            self.assertTrue(controller.initialize())
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            request_count = len(coordinator.requests)

            self.assertFalse(controller.navigate("delivery-checklist"))
            self.assertEqual(controller.currentRouteId, "home")
            self.assertEqual(len(coordinator.requests), request_count)

    def test_invalid_route_sets_all_error_properties_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            observed: list[tuple[object, ...]] = []
            controller.errorChanged.connect(lambda: observed.append(self._error_values(controller)))

            self.assertFalse(controller.navigate("not-a-surface"))
            expected = (
                "action_rejected",
                "Action unavailable",
                "This action is not available from the current page.",
                False,
                "dismiss",
            )
            self.assertEqual(observed, [expected])
            self.assertTrue(controller.navigate("delivery-checklist"))

        empty = ("", "", "", False, "")
        expected = (
            "action_rejected",
            "Action unavailable",
            "This action is not available from the current page.",
            False,
            "dismiss",
        )
        self.assertEqual(observed, [expected, empty])
        self.assertEqual(self._error_values(controller), empty)
        self.assertEqual(len(coordinator.requests), 1)

    def test_schedule_rejection_maps_to_action_rejected_without_raw_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            coordinator.reject_next = True

            self.assertFalse(controller.navigate("delivery-checklist"))

        self.assertEqual(controller.pageState, "error")
        self.assertEqual(controller.errorCode, "action_rejected")
        self.assertEqual(
            controller.errorSummary,
            "This action is not available from the current page.",
        )
        self.assertEqual(coordinator.requests, [])

    def test_invalid_profile_is_rejected_without_work_or_raw_input_exposure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            raw_profile = r"..\operator-private\secret"

            self.assertFalse(controller.selectProfile(raw_profile))

        self.assertEqual(controller.currentProfileId, "G65")
        self.assertEqual(coordinator.requests, [])
        self.assertEqual(controller.errorCode, "action_rejected")
        rendered = repr(self._error_values(controller)).casefold()
        self.assertNotIn("operator-private", rendered)
        self.assertNotIn("secret", rendered)

    def test_current_mapping_success_is_copied_to_plain_dict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            controller.navigate("delivery-checklist")
            identity, _operation = coordinator.requests[-1]
            source = {"id": "delivery-checklist", "rows": [1]}

            coordinator.succeed(identity, MappingProxyType(source))
            source["rows"] = [2]

        self.assertEqual(controller.pageState, "ready")
        self.assertIs(type(controller.currentPayload), dict)
        self.assertEqual(controller.currentPayload["rows"], [1])

    def test_current_non_mapping_success_maps_to_page_payload_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            controller.navigate("delivery-checklist")
            identity, _operation = coordinator.requests[-1]

            coordinator.succeed(identity, ["unsupported", r"C:\private\payload"])

        self.assertEqual(controller.pageState, "error")
        self.assertEqual(controller.currentPayload, {})
        self.assertEqual(
            self._error_values(controller),
            (
                "page_payload_invalid",
                "Evidence unavailable",
                "The page evidence has an unsupported shape.",
                False,
                "open_clean",
            ),
        )
        self.assertNotIn("private", repr(self._error_values(controller)).casefold())

    def test_malformed_or_unknown_failure_maps_to_canonical_page_reader_failed(self) -> None:
        from sg_preflight.desktop.task_pool import TaskFailure

        failures = (
            None,
            {"code": "raw", "summary": r"C:\private\failure"},
            TaskFailure("page_reader_failed", r"C:\private\known raw secret", "PrivateError"),
            TaskFailure("unknown_worker_code", r"C:\private\raw secret", "PrivateError"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with tempfile.TemporaryDirectory() as temp_dir:
                    controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
                    controller.navigate("risk-score")
                    identity, _operation = coordinator.requests[-1]

                    coordinator.fail(identity, failure)

                self.assertEqual(controller.pageState, "error")
                self.assertEqual(
                    self._error_values(controller),
                    (
                        "page_reader_failed",
                        "Evidence unavailable",
                        "The local page evidence could not be loaded.",
                        True,
                        "retry",
                    ),
                )
                rendered = repr(self._error_values(controller)).casefold()
                self.assertNotIn("private", rendered)
                self.assertNotIn("secret", rendered)
                self.assertNotIn("privateerror", rendered)

    def _assert_stale_identity_field_is_rejected(self, field_name: str, changed_value: object) -> None:
        from sg_preflight.desktop.task_pool import TaskFailure

        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            controller.navigate("delivery-checklist")
            current_identity, _operation = coordinator.requests[-1]
            stale_identity = replace(current_identity, **{field_name: changed_value})
            before = (
                controller.currentPageId,
                controller.currentProfileId,
                controller.pageState,
                dict(controller.currentPayload),
                dict(controller._cache),
                self._error_values(controller),
            )

            coordinator.succeed(
                stale_identity,
                {"id": "delivery-checklist", "rows": ["stale-success"]},
            )
            self.assertEqual(
                (
                    controller.currentPageId,
                    controller.currentProfileId,
                    controller.pageState,
                    dict(controller.currentPayload),
                    dict(controller._cache),
                    self._error_values(controller),
                ),
                before,
            )

            coordinator.fail(
                stale_identity,
                TaskFailure(
                    "page_reader_failed",
                    r"raw C:\private\stale failure",
                    "PrivateError",
                ),
            )

        self.assertEqual(
            (
                controller.currentPageId,
                controller.currentProfileId,
                controller.pageState,
                dict(controller.currentPayload),
                dict(controller._cache),
                self._error_values(controller),
            ),
            before,
        )

    def test_stale_generation_success_and_failure_change_nothing(self) -> None:
        self._assert_stale_identity_field_is_rejected("generation", 99)

    def test_stale_profile_success_and_failure_change_nothing(self) -> None:
        self._assert_stale_identity_field_is_rejected("profile_id", "G70")

    def test_stale_page_success_and_failure_change_nothing(self) -> None:
        self._assert_stale_identity_field_is_rejected("page_id", "risk-score")

    def test_stale_operation_success_and_failure_change_nothing(self) -> None:
        self._assert_stale_identity_field_is_rejected("operation", "refresh")

    def test_real_coordinator_keeps_reader_work_off_the_gui_thread(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import PageTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = PageTaskCoordinator()
            reader_threads: list[int] = []
            signal_threads: list[tuple[str, int]] = []

            def loader(**kwargs: object) -> dict[str, object]:
                reader_threads.append(threading.get_ident())
                return {
                    "id": kwargs["page_id"],
                    "status": "available",
                    "data_available": True,
                    "summary": "threaded delivery fixture",
                    "payload": {
                        "status": "available",
                        "data_available": True,
                        "summary": "threaded delivery fixture",
                        "checks": [
                            {
                                "key": "threaded",
                                "label": "Threaded read",
                                "status": "available",
                                "raw_value": "available",
                            }
                        ],
                    },
                }

            controller = DesktopController(
                workspace=temp_dir,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=loader,
                shell_loader=lambda **_kwargs: {
                    "status": "not_run",
                    "profile_options": [
                        {"id": "G65", "label": "G65"},
                        {"id": "G70", "label": "G70"},
                    ],
                    "selected_profile_id": "G65",
                },
            )
            gui_thread_id = threading.get_ident()
            for signal_name in (
                "currentPageChanged",
                "currentProfileChanged",
                "pageStateChanged",
                "payloadChanged",
                "errorChanged",
            ):
                signal = getattr(controller, signal_name)
                signal.connect(
                    lambda signal_name=signal_name: signal_threads.append(
                        (signal_name, threading.get_ident())
                    )
                )

            self.assertTrue(controller.initialize())
            self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            self.assertFalse(controller.navigate("not-a-surface"))
            self.assertTrue(controller.navigate("delivery-checklist"))
            self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            self.assertTrue(controller.selectProfile("G70"))
            self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            self.assertTrue(coordinator.wait_for_done(1000))
            coordinator.shutdown(timeout_ms=1000)

        self.assertEqual(controller.pageState, "ready")
        self.assertEqual(controller.currentPayload["status"], "available")
        self.assertEqual(len(reader_threads), 2)
        self.assertTrue(all(thread_id != gui_thread_id for thread_id in reader_threads))
        self.assertEqual(
            {signal_name for signal_name, _thread_id in signal_threads},
            {
                "currentPageChanged",
                "currentProfileChanged",
                "pageStateChanged",
                "payloadChanged",
                "errorChanged",
            },
        )
        self.assertTrue(
            all(thread_id == gui_thread_id for _signal_name, thread_id in signal_threads)
        )

    def test_shutdown_clears_state_is_idempotent_and_rejects_later_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _loader, _resolver = self._controller(Path(temp_dir))
            controller.navigate("delivery-checklist")
            identity, _operation = coordinator.requests[-1]
            coordinator.succeed(identity, {"id": "delivery-checklist", "rows": [1]})
            controller.navigate("not-a-surface")

            self.assertIsNone(controller.shutdown())
            self.assertIsNone(controller.shutdown())
            self.assertFalse(controller.navigate("risk-score"))
            self.assertFalse(controller.selectProfile("G70"))
            self.assertFalse(controller.refresh())
            self.assertFalse(controller.initialize())

        self.assertEqual(coordinator.shutdown_calls, [])
        self.assertEqual(controller.pageState, "idle")
        self.assertEqual(controller.currentPayload, {})
        self.assertEqual(self._error_values(controller), ("", "", "", False, ""))


class TestTask10ControllerPresentation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or _gui_application()

    @staticmethod
    def _error_values(controller: QObject) -> tuple[object, ...]:
        return (
            controller.errorCode,
            controller.errorTitle,
            controller.errorSummary,
            controller.errorRetryable,
            controller.errorRecoveryAction,
        )

    @staticmethod
    def _presented_payload(
        page_id: str = "delivery-checklist",
        *,
        renderer_kind: str = "evidence",
    ) -> dict[str, object]:
        from sg_preflight.surface_registry import get_surface_descriptor

        descriptor = get_surface_descriptor(page_id)
        item = {
            "itemId": "controller-sentinel",
            "sectionId": "delivery-evidence",
            "label": "Controller integration",
            "value": "presented-only sentinel",
            "detail": "",
            "status": "partial",
            "expected": "",
            "actual": "",
            "diff": "",
            "source": "",
            "revision": "revision-controller-10",
        }
        return {
            "surfaceId": page_id,
            "rendererKind": renderer_kind,
            "title": descriptor.title,
            "subtitle": descriptor.subtitle,
            "status": "partial",
            "dataAvailable": True,
            "primaryText": "presented-only sentinel",
            "visibleItems": [item],
            "visibleItemCount": 1,
            "sections": [
                {
                    "sectionId": "delivery-evidence",
                    "title": "Delivery evidence",
                    "status": "partial",
                    "items": [item],
                }
            ],
            "actions": [],
            "artifacts": [],
            "provenance": {"revision": "revision-controller-10"},
            "ownershipNote": "",
            "readOnly": True,
            "isApproval": False,
            "manualReviewRequired": False,
            "recordsOperatorVerdict": False,
        }

    def test_registered_page_worker_adapts_then_presents_before_cache_publication(self) -> None:
        from sg_preflight.desktop import qt_quick_controller as controller_module
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.surface_registry import get_surface_descriptor

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            coordinator = _FakeTaskCoordinator()
            raw = {
                "id": "delivery-checklist",
                "status": "partial",
                "payload": {"checks": [{"label": "raw-only sentinel"}]},
            }
            adapted = {
                "id": "delivery-checklist",
                "status": "partial",
                "payload": {"checks": [{"label": "adapted-only sentinel"}]},
            }
            presented = self._presented_payload()
            adapter = mock.Mock(return_value=adapted)
            presenter = mock.Mock(return_value=presented)
            pipeline = mock.Mock()
            pipeline.attach_mock(adapter, "adapt")
            pipeline.attach_mock(presenter, "present")
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value=raw),
            )

            with (
                mock.patch.object(controller_module, "adapt_page_payload", adapter),
                mock.patch.object(
                    controller_module,
                    "present_page_payload",
                    presenter,
                    create=True,
                ),
            ):
                self.assertTrue(controller.navigate("delivery-checklist"))
                identity, operation = coordinator.requests[-1]
                worker_result = operation()

                self.assertEqual(controller._cache, {})
                self.assertEqual(
                    pipeline.mock_calls,
                    [
                        mock.call.adapt(raw, workspace=workspace.resolve()),
                        mock.call.present(
                            get_surface_descriptor("delivery-checklist"),
                            adapted,
                        ),
                    ],
                )
                self.assertEqual(worker_result, presented)
                coordinator.succeed(identity, worker_result)

        self.assertEqual(controller.pageState, "ready")
        published = dict(controller.currentPayload)
        published_actions = published.pop("actions")
        expected_presented = dict(presented)
        expected_presented.pop("actions")
        self.assertEqual(published, expected_presented)
        self.assertEqual(
            [item["capabilityId"] for item in published_actions],
            ["page.refresh"],
        )
        self.assertEqual(
            controller._cache,
            {("G65", "delivery-checklist"): presented},
        )
        self.assertNotIn("raw-only sentinel", repr(controller.currentPayload))
        self.assertNotIn("adapted-only sentinel", repr(controller.currentPayload))

    def test_home_shell_context_bypasses_presentation_and_page_cache(self) -> None:
        from sg_preflight.desktop import qt_quick_controller as controller_module
        from sg_preflight.desktop.qt_quick_controller import DesktopController

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            coordinator = _FakeTaskCoordinator()
            shell_payload = {
                "status": "not_run",
                "summary": "home shell sentinel",
                "profile_options": [{"id": "G65", "label": "G65"}],
                "selected_profile_id": "G65",
            }
            presenter = mock.Mock(side_effect=AssertionError("Home must bypass presentation"))
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                shell_loader=mock.Mock(return_value=shell_payload),
            )

            with mock.patch.object(
                controller_module,
                "present_page_payload",
                presenter,
                create=True,
            ):
                self.assertTrue(controller.initialize())
                identity, operation = coordinator.requests[-1]
                self.assertEqual(identity.operation, "shell_context")
                worker_result = operation()
                coordinator.succeed(identity, worker_result)

        presenter.assert_not_called()
        self.assertEqual(controller.pageState, "ready")
        self.assertEqual(controller.currentPayload["summary"], "home shell sentinel")
        self.assertNotIn("rendererKind", controller.currentPayload)
        self.assertEqual(controller._cache, {})

    def test_missing_required_page_payload_is_uncached_atomic_page_payload_invalid(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import PageTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            before = tuple(workspace.rglob("*"))
            coordinator = PageTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=lambda **_kwargs: {
                    "id": "delivery-checklist",
                    "status": "available",
                    "payload": {},
                },
            )
            observed: list[tuple[object, ...]] = []
            controller.errorChanged.connect(
                lambda: observed.append(self._error_values(controller))
            )

            self.assertTrue(controller.navigate("delivery-checklist"))
            self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            self.assertTrue(coordinator.wait_for_done(1000))
            after = tuple(workspace.rglob("*"))
            coordinator.shutdown(timeout_ms=1000)

        expected_error = (
            "page_payload_invalid",
            "Evidence unavailable",
            "The page evidence has an unsupported shape.",
            False,
            "open_clean",
        )
        self.assertEqual(controller.pageState, "error")
        self.assertEqual(controller.currentPayload, {})
        self.assertEqual(controller._cache, {})
        self.assertEqual(observed, [expected_error])
        self.assertEqual(self._error_values(controller), expected_error)
        self.assertEqual(before, after)

    def test_about_uses_the_special_content_shape_and_publishes_only_presented_fields(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.surface_registry import get_surface_descriptor

        descriptor = get_surface_descriptor("about")
        raw_about = {
            "id": "about",
            "title": descriptor.title,
            "tagline": descriptor.subtitle,
            "content": {
                "heading": "About",
                "description": "about controller sentinel",
                "version_placeholder": "version: task-10-about-sentinel",
                "data_handling_disclosure": (
                    "Data handling",
                    "Local-only evidence.",
                ),
            },
        }
        expected_keys = {
            "surfaceId",
            "rendererKind",
            "title",
            "subtitle",
            "status",
            "dataAvailable",
            "primaryText",
            "visibleItems",
            "visibleItemCount",
            "sections",
            "actions",
            "artifacts",
            "provenance",
            "ownershipNote",
            "readOnly",
            "isApproval",
            "manualReviewRequired",
            "recordsOperatorVerdict",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            before = tuple(workspace.rglob("*"))
            coordinator = _FakeTaskCoordinator()
            loader = mock.Mock(return_value=raw_about)
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=loader,
            )

            self.assertTrue(controller.navigate("about"))
            identity, operation = coordinator.requests[-1]
            worker_result = operation()
            self.assertEqual(controller._cache, {})
            coordinator.succeed(identity, worker_result)
            after = tuple(workspace.rglob("*"))

        loader.assert_called_once_with(
            page_id="about",
            profile_id="G65",
            workspace=workspace.resolve(),
            bmw_root=None,
        )
        self.assertEqual(set(controller.currentPayload), expected_keys)
        self.assertEqual(controller.currentPayload["surfaceId"], "about")
        self.assertEqual(controller.currentPayload["rendererKind"], "about")
        rendered = repr(controller.currentPayload)
        self.assertIn("version: task-10-about-sentinel", rendered)
        self.assertNotIn("version_placeholder", rendered)
        cached_about = controller._cache[("G65", "about")]
        self.assertEqual(cached_about["actions"], [])
        self.assertEqual(
            [item["capabilityId"] for item in controller.currentPayload["actions"]],
            ["page.refresh"],
        )
        self.assertEqual(before, after)

    def test_stale_presented_success_and_failure_reject_each_full_identity_mismatch(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import TaskFailure

        with tempfile.TemporaryDirectory() as temp_dir:
            coordinator = _FakeTaskCoordinator()
            controller = DesktopController(
                workspace=Path(temp_dir),
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=mock.Mock(return_value={}),
            )
            self.assertTrue(controller.navigate("delivery-checklist"))
            current_identity, _operation = coordinator.requests[-1]
            presented = self._presented_payload()
            stale_identities = (
                replace(current_identity, generation=current_identity.generation + 1),
                replace(current_identity, profile_id="G70"),
                replace(current_identity, page_id="risk-score"),
                replace(current_identity, operation="refresh"),
            )
            before = (
                controller._current_identity,
                controller.currentRouteId,
                controller.currentPageId,
                controller.currentProfileId,
                controller.pageState,
                dict(controller.currentPayload),
                dict(controller._cache),
                self._error_values(controller),
            )

            for stale_identity in stale_identities:
                with self.subTest(identity=stale_identity):
                    coordinator.succeed(stale_identity, presented)
                    coordinator.fail(
                        stale_identity,
                        TaskFailure(
                            "page_payload_invalid",
                            "private stale detail",
                            "PrivatePresentationError",
                        ),
                    )
                    self.assertEqual(
                        (
                            controller._current_identity,
                            controller.currentRouteId,
                            controller.currentPageId,
                            controller.currentProfileId,
                            controller.pageState,
                            dict(controller.currentPayload),
                            dict(controller._cache),
                            self._error_values(controller),
                        ),
                        before,
                    )

    def test_generic_reader_exception_remains_uncached_atomic_page_reader_failed(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import PageTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            before = tuple(workspace.rglob("*"))
            coordinator = PageTaskCoordinator()

            def failed_reader(**_kwargs: object) -> dict[str, object]:
                raise PermissionError(r"denied C:\operator-private\evidence secret-value")

            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="G65",
                task_coordinator=coordinator,
                page_loader=failed_reader,
            )
            observed: list[tuple[object, ...]] = []
            controller.errorChanged.connect(
                lambda: observed.append(self._error_values(controller))
            )

            self.assertTrue(controller.navigate("delivery-checklist"))
            self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            self.assertTrue(coordinator.wait_for_done(1000))
            after = tuple(workspace.rglob("*"))
            coordinator.shutdown(timeout_ms=1000)

        expected_error = (
            "page_reader_failed",
            "Evidence unavailable",
            "The local page evidence could not be loaded.",
            True,
            "retry",
        )
        self.assertEqual(controller.pageState, "error")
        self.assertEqual(controller.currentPayload, {})
        self.assertEqual(controller._cache, {})
        self.assertEqual(observed, [expected_error])
        self.assertEqual(self._error_values(controller), expected_error)
        self.assertNotIn("operator-private", repr(observed).casefold())
        self.assertNotIn("secret-value", repr(observed).casefold())
        self.assertEqual(before, after)


class TestQtShellRoute(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.application = QCoreApplication.instance() or _gui_application()

    @staticmethod
    def _error_values(controller: QObject) -> tuple[object, ...]:
        return (
            controller.errorCode,
            controller.errorTitle,
            controller.errorSummary,
            controller.errorRetryable,
            controller.errorRecoveryAction,
        )

    def _controller(self, workspace: Path, *, initial_profile_id: str = "G65"):
        from sg_preflight.desktop.qt_quick_controller import DesktopController

        coordinator = _FakeTaskCoordinator()
        shell_loader = mock.Mock(
            return_value={
                "status": "not_run",
                "summary": "No local activity recorded yet.",
                "profile_options": [
                    {"id": "G65", "label": "G65 label"},
                    {"id": "G70", "label": "G70 label"},
                ],
                "selected_profile_id": initial_profile_id,
                "unsafe": {"command": ["secret"], "path": r"C:\private\activity.jsonl"},
            }
        )
        page_loader = mock.Mock(return_value={"id": "risk-score", "status": "available"})
        controller = DesktopController(
            workspace=workspace,
            initial_profile_id=initial_profile_id,
            task_coordinator=coordinator,
            shell_loader=shell_loader,
            page_loader=page_loader,
        )
        return controller, coordinator, shell_loader, page_loader

    def test_shell_loader_builds_exact_bounded_qa_hub_snapshot(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_shell_context
        from sg_preflight.qa_operator_actions import OperatorAction

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            source = workspace / "repositories" / "trunk"
            project = source / "Cars" / "BMW" / "G45"
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
            record = {
                "run_id": "action-001",
                "action_id": "sgfx_preflight__g45",
                "kind": "sgfx_preflight",
                "profile_id": "G45",
                "status": "completed",
                "created_at_utc": "2026-07-12T20:00:00+00:00",
                "completed_at_utc": "2026-07-12T20:01:00+00:00",
                "summary": {
                    "errors": 0,
                    "warnings": 1,
                    "info": 2,
                    "findings": [
                        {
                            "severity": "warning",
                            "pack": "materials",
                            "code": "duplicate-carpaint",
                            "message": "Carpaint identifier is duplicated",
                            "location": "materials.carpaint",
                            "expected": "unique",
                            "actual": "duplicate",
                        }
                    ],
                },
            }
            action_records = mock.Mock(return_value=[record])
            run_records = mock.Mock(return_value=[])
            with (
                mock.patch(
                    "sg_preflight.dashboard_preferences.dashboard_profile_options",
                    return_value=[{"id": "G45", "label": "BMW G45"}],
                ),
                mock.patch(
                    "sg_preflight.home_context.build_home_context",
                    return_value={
                        "activity": [
                            {"label": "Recent", "status": "recorded", "detail": "Opened local QA"}
                        ]
                    },
                ),
                mock.patch(
                    "sg_preflight.qa_operator_actions.list_sgfx_preflight_actions",
                    return_value=[action],
                ) as action_lister,
                mock.patch(
                    "sg_preflight.qa_action_persistence.list_recent_action_records",
                    action_records,
                ),
                mock.patch(
                    "sg_preflight.services.list_recent_run_records",
                    run_records,
                ),
            ):
                payload = load_shell_context(
                    workspace=workspace,
                    profile_id="G45",
                    profile_resolver=lambda **_kwargs: "",
                )

        self.assertEqual(
            set(payload),
            {
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
            },
        )
        self.assertEqual(payload["selectedProfile"], {"id": "G45", "label": "BMW G45"})
        self.assertEqual(payload["nextAction"]["kind"], "review")
        self.assertEqual(payload["nextAction"]["routeId"], "full-qa-pass")
        self.assertEqual(payload["latestLocalRun"]["warnings"], 1)
        self.assertEqual(
            payload["latestLocalRun"]["findings"],
            [
                {
                    "severity": "warning",
                    "pack": "materials",
                    "code": "duplicate-carpaint",
                    "message": "Carpaint identifier is duplicated",
                    "location": "materials.carpaint",
                    "expected": "unique",
                    "actual": "duplicate",
                }
            ],
        )
        selected_car_check = next(
            check
            for gate in payload["gates"]
            for check in gate["checks"]
            if check.get("routeId") == "full-qa-pass"
        )
        self.assertEqual(selected_car_check["label"], "Open selected-car checks")
        action_records.assert_called_once_with(workspace.resolve(), limit=12)
        run_records.assert_called_once_with(workspace.resolve(), limit=12)
        action_lister.assert_called_once_with(workspace.resolve())

    def test_initial_home_submits_one_adapted_shell_context_and_stays_outside_surfaces(self) -> None:
        from sg_preflight.surface_registry import is_registered_surface

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            controller, coordinator, shell_loader, page_loader = self._controller(workspace)

            self.assertEqual(controller.currentRouteId, "home")
            self.assertEqual(controller.currentPageId, "")
            self.assertEqual(controller.pageTitle, "QA overview")
            self.assertEqual(coordinator.requests, [])
            self.assertTrue(controller.initialize())
            self.assertFalse(controller.initialize())
            identity, operation = coordinator.requests[-1]
            self.assertEqual(
                (identity.profile_id, identity.page_id, identity.operation),
                ("G65", "home", "shell_context"),
            )
            payload = operation()
            coordinator.succeed(identity, payload)

        shell_loader.assert_called_once_with(
            workspace=workspace.resolve(),
            profile_id="G65",
            bmw_root=None,
        )
        page_loader.assert_not_called()
        self.assertEqual(controller.currentRouteId, "home")
        self.assertEqual(controller.currentPageId, "")
        self.assertEqual(controller.pageState, "ready")
        self.assertEqual(controller.profileOptions, [{"id": "G65", "label": "G65 label"}, {"id": "G70", "label": "G70 label"}])
        rendered = repr(controller.currentPayload).casefold()
        self.assertNotIn("secret", rendered)
        self.assertNotIn("private", rendered)
        self.assertFalse(is_registered_surface("home"))

    def test_no_profile_stays_empty_inside_exactly_one_shell_context(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _shell_loader, _page_loader = self._controller(
                Path(temp_dir), initial_profile_id=""
            )
            self.assertTrue(controller.initialize())
            identity, operation = coordinator.requests[0]
            self.assertEqual((identity.profile_id, identity.page_id, identity.operation), ("", "home", "shell_context"))
            coordinator.succeed(identity, operation())

        self.assertEqual(len(coordinator.requests), 1)
        self.assertEqual(controller.currentProfileId, "")
        self.assertEqual(controller.pageState, "ready")
        self.assertEqual(controller.errorCode, "")

    def test_unknown_route_preserves_route_payload_and_work_and_sets_atomic_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _shell_loader, _page_loader = self._controller(Path(temp_dir))
            controller.initialize()
            identity, operation = coordinator.requests[-1]
            coordinator.succeed(identity, operation())
            before = (
                controller.currentRouteId,
                controller.currentPageId,
                controller.pageState,
                dict(controller.currentPayload),
                len(coordinator.requests),
            )
            observed: list[tuple[object, ...]] = []
            controller.errorChanged.connect(lambda: observed.append(self._error_values(controller)))

            self.assertFalse(controller.navigate("weekly-ticket-draft"))

        self.assertEqual(
            (
                controller.currentRouteId,
                controller.currentPageId,
                controller.pageState,
                dict(controller.currentPayload),
                len(coordinator.requests),
            ),
            before,
        )
        self.assertEqual(
            observed,
            [("action_rejected", "Action unavailable", "This action is not available from the current page.", False, "dismiss")],
        )

    def test_home_refresh_profile_and_navigation_use_full_stale_identities(self) -> None:
        from sg_preflight.desktop.task_pool import TaskFailure

        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _shell_loader, _page_loader = self._controller(Path(temp_dir))
            controller.initialize()
            initial_identity, initial_operation = coordinator.requests[-1]
            coordinator.succeed(initial_identity, initial_operation())
            self.assertTrue(controller.refresh())
            stale_identity, _stale_operation = coordinator.requests[-1]
            self.assertTrue(controller.navigate("home"))
            current_identity, current_operation = coordinator.requests[-1]
            self.assertNotEqual(stale_identity, current_identity)
            before = (controller.currentRouteId, controller.pageState, dict(controller.currentPayload))
            coordinator.succeed(stale_identity, {"status": "available", "summary": "stale"})
            coordinator.fail(stale_identity, TaskFailure("page_reader_failed", "private", "PrivateError"))
            self.assertEqual((controller.currentRouteId, controller.pageState, dict(controller.currentPayload)), before)
            coordinator.succeed(current_identity, current_operation())
            self.assertTrue(controller.selectProfile("G70"))
            profile_identity, _profile_operation = coordinator.requests[-1]
            self.assertEqual((profile_identity.profile_id, profile_identity.page_id, profile_identity.operation), ("G70", "home", "shell_context"))
            self.assertFalse(controller.selectProfile("UNLISTED"))
            self.assertEqual(len(coordinator.requests), 4)
            self.assertTrue(controller.navigate("risk-score"))
            page_identity, _page_operation = coordinator.requests[-1]

        self.assertEqual((page_identity.profile_id, page_identity.page_id, page_identity.operation), ("G70", "risk-score", "load"))
        self.assertEqual(controller.currentRouteId, "risk-score")
        self.assertEqual(controller.currentPageId, "risk-score")

    def test_page_home_profile_refresh_and_repeated_home_reject_every_stale_tuple(self) -> None:
        from sg_preflight.desktop.task_pool import TaskFailure

        with tempfile.TemporaryDirectory() as temp_dir:
            controller, coordinator, _shell_loader, _page_loader = self._controller(Path(temp_dir))
            controller.initialize()
            initial_identity, initial_operation = coordinator.requests[-1]
            coordinator.succeed(initial_identity, initial_operation())

            controller.navigate("risk-score")
            page_identity, _page_operation = coordinator.requests[-1]
            controller.navigate("home")
            home_identity, _home_operation = coordinator.requests[-1]
            before_page_stale = (
                controller.currentRouteId,
                controller.currentPageId,
                controller.pageState,
                dict(controller.currentPayload),
            )
            coordinator.succeed(page_identity, {"id": "risk-score", "status": "stale"})
            self.assertEqual(
                (controller.currentRouteId, controller.currentPageId, controller.pageState, dict(controller.currentPayload)),
                before_page_stale,
            )

            controller.selectProfile("G70")
            profile_identity, _profile_operation = coordinator.requests[-1]
            before_home_stale = (
                controller.currentRouteId,
                controller.currentProfileId,
                controller.pageState,
                dict(controller.currentPayload),
            )
            coordinator.fail(home_identity, TaskFailure("page_reader_failed", "private", "PrivateError"))
            self.assertEqual(
                (controller.currentRouteId, controller.currentProfileId, controller.pageState, dict(controller.currentPayload)),
                before_home_stale,
            )

            controller.refresh()
            refresh_identity, _refresh_operation = coordinator.requests[-1]
            controller.navigate("home")
            repeated_identity, _repeated_operation = coordinator.requests[-1]

        self.assertEqual(
            [
                (identity.generation, identity.profile_id, identity.page_id, identity.operation)
                for identity in (
                    page_identity,
                    home_identity,
                    profile_identity,
                    refresh_identity,
                    repeated_identity,
                )
            ],
            [
                (2, "G65", "risk-score", "load"),
                (3, "G65", "home", "shell_context"),
                (4, "G70", "home", "shell_context"),
                (5, "G70", "home", "refresh"),
                (6, "G70", "home", "shell_context"),
            ],
        )

    def test_real_shell_context_resolves_profile_options_off_thread_and_never_persists_selection(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import DesktopController
        from sg_preflight.desktop.task_pool import PageTaskCoordinator

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            gui_thread_id = threading.get_ident()
            option_threads: list[int] = []

            def options(**_kwargs: object) -> list[dict[str, object]]:
                option_threads.append(threading.get_ident())
                return [
                    {"id": "G65", "label": "BMW G65", "select_label": "BMW / build / G65"},
                    {"id": "G70", "label": "BMW G70", "select_label": "BMW / build / G70"},
                ]

            coordinator = PageTaskCoordinator()
            controller = DesktopController(
                workspace=workspace,
                initial_profile_id="",
                task_coordinator=coordinator,
                profile_resolver=lambda **_kwargs: "",
            )
            before = tuple(path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file())
            with mock.patch(
                "sg_preflight.dashboard_preferences.dashboard_profile_options",
                side_effect=options,
            ):
                self.assertTrue(controller.initialize())
                self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
                initial_profile_id = controller.currentProfileId
                self.assertTrue(controller.selectProfile("g70"))
                self.assertTrue(_pump_until(lambda: controller.pageState != "loading"))
            after = tuple(path.relative_to(workspace) for path in workspace.rglob("*") if path.is_file())
            coordinator.shutdown(timeout_ms=1000)

        self.assertEqual(initial_profile_id, "")
        self.assertEqual(controller.currentProfileId, "G70")
        self.assertEqual(
            controller.profileOptions,
            [
                {"id": "G65", "label": "BMW G65"},
                {"id": "G70", "label": "BMW G70"},
            ],
        )
        self.assertEqual(len(option_threads), 2)
        self.assertTrue(all(thread_id != gui_thread_id for thread_id in option_threads))
        self.assertEqual(before, after)


class TestQtPageReadSafety(unittest.TestCase):
    @staticmethod
    def _dependency_item(key: str) -> dict[str, object]:
        return {
            "key": key,
            "label": key,
            "status": "missing",
            "detail": "Unavailable in test fixture.",
            "path": "",
            "setup_action": None,
        }

    def test_public_page_and_loader_contracts_remain_page_first(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_page
        from sg_preflight.desktop.qt_quick_controller import (
            PageLoader,
            ProfileResolver,
            load_dashboard_surface,
            resolve_dashboard_profile,
        )

        page_parameters = tuple(inspect.signature(build_dashboard_page).parameters.values())
        loader_parameters = tuple(inspect.signature(load_dashboard_surface).parameters.values())
        resolver_parameters = tuple(inspect.signature(resolve_dashboard_profile).parameters.values())
        loader_protocol_parameters = tuple(inspect.signature(PageLoader.__call__).parameters.values())
        resolver_protocol_parameters = tuple(inspect.signature(ProfileResolver.__call__).parameters.values())

        self.assertEqual(tuple(item.name for item in page_parameters[:3]), ("page_id", "profile_id", "workspace"))
        self.assertEqual(tuple(item.name for item in loader_parameters[:3]), ("page_id", "profile_id", "workspace"))
        self.assertEqual(loader_parameters[3].name, "bmw_root")
        self.assertEqual(loader_parameters[3].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(resolver_parameters[0].name, "workspace")
        self.assertEqual(resolver_parameters[1].name, "bmw_root")
        self.assertEqual(resolver_parameters[1].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(
            tuple(item.name for item in loader_protocol_parameters[1:4]),
            ("page_id", "profile_id", "workspace"),
        )
        self.assertEqual(loader_protocol_parameters[4].name, "bmw_root")
        self.assertEqual(loader_protocol_parameters[4].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertEqual(resolver_protocol_parameters[1].name, "workspace")
        self.assertEqual(resolver_protocol_parameters[2].name, "bmw_root")
        self.assertEqual(resolver_protocol_parameters[2].kind, inspect.Parameter.KEYWORD_ONLY)

    def test_page_first_loader_calls_dashboard_builder_by_keyword_and_disables_persistence(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "sg_preflight.dashboard.main.build_dashboard_page",
                return_value={"id": "delivery-checklist", "revision": "abc123"},
            ) as page_builder:
                payload = load_dashboard_surface(
                    "delivery-checklist",
                    "G65",
                    workspace,
                    bmw_root=None,
                )

        self.assertEqual(payload["id"], "delivery-checklist")
        page_builder.assert_called_once_with(
            page_id="delivery-checklist",
            profile_id="G65",
            workspace=workspace,
            bmw_root=None,
            ui_mode="clean",
            persist_dependency_state=False,
        )

    def test_qt_read_only_pages_replace_unavailable_input_prompts_without_mutating_source(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        cases = (
            (
                "batch-full-qa-pass",
                "results",
                "Select multiple profiles and run.",
                "No batch QA evidence is available for this session.",
            ),
            (
                "cross-car-comparison",
                "comparison_rows",
                "Choose two profiles to compare.",
                "No car-comparison evidence is available for this session.",
            ),
        )
        for page_id, evidence_key, source_summary, expected_summary in cases:
            with self.subTest(page_id=page_id), tempfile.TemporaryDirectory() as temp_dir:
                source_payload = {
                    "id": page_id,
                    "summary": source_summary,
                    "payload": {"summary": source_summary, evidence_key: []},
                }
                with mock.patch(
                    "sg_preflight.dashboard.main.build_dashboard_page",
                    return_value=source_payload,
                ):
                    payload = load_dashboard_surface(page_id, "G65", Path(temp_dir))

                self.assertEqual(payload["summary"], expected_summary)
                self.assertEqual(payload["empty_state_note"], expected_summary)
                self.assertEqual(payload["payload"]["summary"], expected_summary)
                self.assertFalse(payload["data_available"])
                self.assertFalse(payload["payload"]["data_available"])
                self.assertEqual(source_payload["summary"], source_summary)
                self.assertEqual(source_payload["payload"]["summary"], source_summary)

                source_payload["payload"][evidence_key] = [{"status": "recorded"}]
                with mock.patch(
                    "sg_preflight.dashboard.main.build_dashboard_page",
                    return_value=source_payload,
                ):
                    recorded = load_dashboard_surface(page_id, "G65", Path(temp_dir))
                self.assertIs(recorded, source_payload)

    def test_profile_resolver_uses_direct_read_only_profile_options_by_keyword(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import resolve_dashboard_profile

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            all_options = [{"id": "G65"}, {"id": "G70"}]
            with (
                mock.patch(
                    "sg_preflight.dashboard_preferences.dashboard_profile_options",
                    return_value=all_options,
                ) as profile_options,
                mock.patch(
                    "sg_preflight.dashboard_preferences.resolve_explicit_dashboard_profile",
                    return_value="",
                ) as profile_resolver,
                mock.patch(
                    "sg_preflight.dashboard.main.build_dashboard_snapshot",
                    side_effect=AssertionError("profile resolution must stay on direct readers"),
                ) as snapshot_builder,
            ):
                profile_id = resolve_dashboard_profile(workspace=workspace, bmw_root=None)

        self.assertEqual(profile_id, "")
        self.assertEqual(
            profile_options.call_args_list,
            [mock.call(bmw_root=None, profile_scope="all")],
        )
        profile_resolver.assert_called_once_with(
            workspace=workspace.resolve(),
            options=all_options,
        )
        snapshot_builder.assert_not_called()

    def test_dashboard_page_forwards_persistence_mode_to_snapshot_by_keyword(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_page

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "sg_preflight.dashboard.main.build_dashboard_snapshot",
                return_value={"pages": [{"id": "setup-doctor", "status": "available"}]},
            ) as snapshot_builder:
                page = build_dashboard_page(
                    "setup-doctor",
                    "G65",
                    workspace,
                    persist_dependency_state=False,
                )

        self.assertEqual(page["id"], "setup-doctor")
        kwargs = snapshot_builder.call_args.kwargs
        self.assertEqual(kwargs["profile_id"], "G65")
        self.assertEqual(kwargs["workspace"], workspace)
        self.assertFalse(kwargs["persist_dependency_state"])
        self.assertEqual(snapshot_builder.call_args.args, ())

    def test_snapshot_forwards_non_persistence_to_dependency_status(self) -> None:
        from sg_preflight.dashboard.main import build_dashboard_snapshot

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "sg_preflight.dashboard.main.build_dependency_onboarding_status",
                return_value={"first_run": False, "actions": []},
            ) as status:
                build_dashboard_snapshot(
                    "G65",
                    workspace,
                    defer_daily_digest=True,
                    defer_team_digest_board=True,
                    lazy_pages=True,
                    persist_dependency_state=False,
                )

        self.assertFalse(status.call_args.kwargs["persist_auto_detected_paths"])

    def test_dependency_status_guard_skips_only_the_final_task4_persistence_helper(self) -> None:
        from sg_preflight import dependency_onboarding as onboarding

        item = self._dependency_item("fixture")
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            patches = (
                mock.patch.object(onboarding, "_raco_status", return_value=(dict(item), dict(item))),
                mock.patch.object(onboarding, "_blender_status", return_value=dict(item)),
                mock.patch.object(onboarding, "_bmw_repo_status", return_value=dict(item)),
                mock.patch.object(onboarding, "_idc23_repo_status", return_value=dict(item)),
                mock.patch.object(onboarding, "_bmw_ci_requirements_status", return_value=dict(item)),
                mock.patch.object(onboarding, "_persist_auto_detected_dependency_paths"),
            )
            with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5] as persist:
                onboarding.build_dependency_onboarding_status(
                    workspace=workspace,
                    persist_auto_detected_paths=False,
                )
                persist.assert_not_called()

                onboarding.build_dependency_onboarding_status(workspace=workspace)
                persist.assert_called_once()

    def test_qt_loader_disables_dependency_persistence_in_the_real_page_chain(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            with mock.patch(
                "sg_preflight.dashboard.main.build_dependency_onboarding_status",
                return_value={"first_run": False, "actions": []},
            ) as status:
                load_dashboard_surface("setup-doctor", "G65", workspace)

        self.assertFalse(status.call_args.kwargs["persist_auto_detected_paths"])

    def test_qt_profile_free_loader_preserves_an_empty_profile(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            page = {
                "id": "onboarding-guide",
                "status": "incomplete",
                "payload": {"profile_id": ""},
            }
            with mock.patch(
                "sg_preflight.dashboard.main.build_dashboard_page",
                return_value=page,
            ) as page_builder:
                loaded = load_dashboard_surface("onboarding-guide", "", workspace)

        self.assertEqual(loaded["payload"]["profile_id"], "")
        page_builder.assert_called_once_with(
            page_id="onboarding-guide",
            profile_id="",
            workspace=workspace,
            bmw_root=None,
            ui_mode="clean",
            persist_dependency_state=False,
            preserve_empty_profile=True,
        )

    def test_real_qt_read_leaves_the_temporary_workspace_file_set_unchanged(self) -> None:
        from sg_preflight.desktop.qt_quick_controller import load_dashboard_surface

        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            before = tuple(
                path.relative_to(workspace)
                for path in workspace.rglob("*")
                if path.is_file()
            )

            payload = load_dashboard_surface("delivery-checklist", "G65", workspace)

            after = tuple(
                path.relative_to(workspace)
                for path in workspace.rglob("*")
                if path.is_file()
            )

        self.assertEqual(payload["id"], "delivery-checklist")
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()

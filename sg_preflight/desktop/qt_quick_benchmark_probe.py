from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import threading
import time
from typing import Any, Callable, Mapping


_SCENARIOS = frozenset({"startup", "navigation", "reader-stress"})
_ROUTES = {
    "overview": "setup-doctor",
    "matrix": "country-variant-coverage",
    "evidence": "delivery-checklist",
    "workflow": "onboarding-guide",
    "review": "manual-review",
    "about": "about",
}
_CALLBACK_FILES = (
    "artifact_registry.py",
    "qt_quick_controller.py",
    "qt_quick_grafiks.py",
    "shell_model.py",
    "surface_model.py",
    "task_pool.py",
    "ui_capabilities.py",
)


class BenchmarkProbeError(RuntimeError):
    pass


class _GuiCallbackProfiler:
    def __init__(self) -> None:
        self._started: dict[int, int] = {}
        self.samples_ms: list[float] = []

    def __call__(self, frame: Any, event: str, _argument: object) -> None:
        filename = frame.f_code.co_filename.replace("\\", "/")
        if not filename.endswith(_CALLBACK_FILES):
            return
        identity = id(frame)
        if event == "call":
            self._started[identity] = time.perf_counter_ns()
        elif event in {"return", "exception"}:
            started = self._started.pop(identity, None)
            if started is not None:
                self.samples_ms.append((time.perf_counter_ns() - started) / 1_000_000)


def _read_request(path: Path) -> dict[str, Any]:
    request_path = Path(path).resolve()
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BenchmarkProbeError("The benchmark request is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise BenchmarkProbeError("The benchmark request is invalid.")
    scenario = payload.get("scenario")
    output_path = payload.get("output_path")
    workspace = payload.get("workspace")
    start_ns = payload.get("start_ns")
    ready_path = payload.get("ready_path")
    if scenario not in _SCENARIOS:
        raise BenchmarkProbeError("The benchmark request is invalid.")
    if not isinstance(output_path, str) or not output_path:
        raise BenchmarkProbeError("The benchmark request is invalid.")
    if not isinstance(workspace, str) or not workspace:
        raise BenchmarkProbeError("The benchmark request is invalid.")
    if type(start_ns) is not int or start_ns <= 0:
        raise BenchmarkProbeError("The benchmark request is invalid.")
    if scenario == "reader-stress":
        if not isinstance(ready_path, str) or not ready_path:
            raise BenchmarkProbeError("The benchmark request is invalid.")
    elif ready_path is not None:
        raise BenchmarkProbeError("The benchmark request is invalid.")
    request_root = request_path.parent
    temp_root = Path(tempfile.gettempdir()).resolve()
    output = Path(output_path).resolve()
    workspace_path = Path(workspace).resolve()
    ready = Path(ready_path).resolve() if isinstance(ready_path, str) else None
    if (
        not request_root.is_relative_to(temp_root)
        or request_root == temp_root
        or output.parent != request_root
        or workspace_path.parent != request_root
        or not workspace_path.is_dir()
        or (ready is not None and (ready.parent != request_root or ready.exists()))
    ):
        raise BenchmarkProbeError("The benchmark request is outside its temporary boundary.")
    request = {
        "scenario": scenario,
        "output_path": output,
        "workspace": workspace_path,
        "start_ns": start_ns,
    }
    if ready is not None:
        request["ready_path"] = ready
    return request


def _write_response(path: Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(payload), sort_keys=True), encoding="utf-8")
    temporary.replace(target)


def _process_until(application: object, predicate: Callable[[], bool], timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        application.processEvents()  # type: ignore[attr-defined]
        if predicate():
            return True
        time.sleep(0.001)
    application.processEvents()  # type: ignore[attr-defined]
    return predicate()


def _create_runtime(workspace: Path):
    from sg_preflight.desktop.qt_quick_app import create_qt_quick_runtime

    return create_qt_quick_runtime(
        workspace=workspace,
        initial_profile_id="G65",
        argv=["sgfx-qt-benchmark"],
    )


def _run_startup(request: Mapping[str, Any]) -> dict[str, object]:
    from PySide6.QtCore import QTimer

    runtime = _create_runtime(request["workspace"])
    acknowledged = False
    response: dict[str, object] = {}
    root = runtime.engine.rootObjects()[0]

    def complete() -> None:
        nonlocal acknowledged
        if acknowledged:
            return
        acknowledged = True
        response.update(
            {
                "acknowledged": True,
                "duration_ms": (time.perf_counter_ns() - request["start_ns"]) / 1_000_000,
            }
        )
        runtime.application.quit()

    def timeout() -> None:
        if not acknowledged:
            runtime.application.quit()

    root.frameSwapped.connect(complete)
    QTimer.singleShot(10_000, timeout)
    root.requestUpdate()
    try:
        runtime.application.exec()
    finally:
        runtime.close()
    if not acknowledged:
        raise BenchmarkProbeError("The startup frame acknowledgement was missed.")
    return response


def _wait_for_page(runtime: object, route: str, frame_before: int, frames: list[int]) -> bool:
    controller = runtime.controller
    return _process_until(
        runtime.application,
        lambda: (
            controller.currentRouteId == route
            and controller.pageState == "ready"
            and frames[0] > frame_before
        ),
        30,
    )


def _prepare_cached_routes(runtime: object, root: object, frames: list[int]) -> None:
    for _round in range(2):
        for route in _ROUTES.values():
            frame_before = frames[0]
            accepted = runtime.controller.navigate(route)
            root.requestUpdate()
            if not accepted or not _wait_for_page(runtime, route, frame_before, frames):
                raise BenchmarkProbeError("A benchmark page could not be prepared.")


def _run_navigation(request: Mapping[str, Any]) -> dict[str, object]:
    runtime = _create_runtime(request["workspace"])
    root = runtime.engine.rootObjects()[0]
    frames = [0]
    root.frameSwapped.connect(lambda: frames.__setitem__(0, frames[0] + 1))
    samples: dict[str, list[dict[str, object]]] = {renderer: [] for renderer in _ROUTES}
    try:
        _prepare_cached_routes(runtime, root, frames)
        cached_routes = tuple(_ROUTES.values())
        for renderer_index, (renderer, route) in enumerate(_ROUTES.items()):
            fallback_route = cached_routes[(renderer_index + 1) % len(cached_routes)]
            for _index in range(20):
                fallback_frame = frames[0]
                runtime.controller.navigate(fallback_route)
                root.requestUpdate()
                _process_until(
                    runtime.application,
                    lambda: runtime.controller.currentRouteId == fallback_route and frames[0] > fallback_frame,
                    1,
                )
                frame_before = frames[0]
                started = time.perf_counter_ns()
                accepted = runtime.controller.navigate(route)
                root.requestUpdate()
                feedback_ready = accepted and _process_until(
                    runtime.application,
                    lambda: (
                        runtime.controller.currentRouteId == route
                        and runtime.controller.pageState in {"loading", "ready"}
                        and frames[0] > frame_before
                    ),
                    2,
                )
                feedback_ms = (time.perf_counter_ns() - started) / 1_000_000
                settled = _wait_for_page(runtime, route, frame_before, frames)
                settle_ms = (time.perf_counter_ns() - started) / 1_000_000
                samples[renderer].append(
                    {
                        "feedback_ms": feedback_ms,
                        "settle_ms": settle_ms,
                        "acknowledged": feedback_ready and settled,
                    }
                )
    finally:
        runtime.close()
    return {"acknowledged": True, "raw_samples": {"renderers": samples}}


def _run_reader_stress(request: Mapping[str, Any]) -> dict[str, object]:
    runtime = _create_runtime(request["workspace"])
    root = runtime.engine.rootObjects()[0]
    controller = runtime.controller
    frames = [0]
    root.frameSwapped.connect(lambda: frames.__setitem__(0, frames[0] + 1))
    release_readers = threading.Event()
    original_loader = controller._page_loader

    def delayed_loader(*args: object, **kwargs: object):
        release_readers.wait(65)
        raise RuntimeError("Benchmark reader released.")

    profiler = _GuiCallbackProfiler()
    navigation_ack: list[float] = []
    resize_ack: list[float] = []
    missing_navigation = 0
    missing_resize = 0
    routes = tuple(_ROUTES.values())
    try:
        _prepare_cached_routes(runtime, root, frames)
        controller._page_loader = delayed_loader
        first_reader = controller.navigate("disabled-tests")
        second_reader = controller.navigate("screenshot-test-state")
        controller._page_loader = original_loader
        if (
            not first_reader
            or not second_reader
            or controller._task_coordinator.active_count != 2
        ):
            raise BenchmarkProbeError("The delayed benchmark readers could not be occupied.")
        request["ready_path"].touch(exist_ok=False)
        load_started = time.monotonic()
        _process_until(
            runtime.application,
            lambda: time.monotonic() >= load_started + 0.5,
            0.6,
        )
        sys.setprofile(profiler)
        started = time.monotonic()
        for index in range(30):
            due = started + index * 2
            _process_until(
                runtime.application,
                lambda: time.monotonic() >= due,
                max(0.1, due - time.monotonic() + 0.1),
            )
            route = routes[index % len(routes)]
            frame_before = frames[0]
            callback_started = time.perf_counter_ns()
            accepted = controller.navigate(route)
            root.requestUpdate()
            acknowledged = accepted and _process_until(
                runtime.application,
                lambda: controller.currentRouteId == route and frames[0] > frame_before,
                0.25,
            )
            if acknowledged:
                navigation_ack.append((time.perf_counter_ns() - callback_started) / 1_000_000)
            else:
                missing_navigation += 1
            if index % 5 == 0:
                width, height = ((1280, 720) if (index // 5) % 2 == 0 else (1024, 640))
                frame_before = frames[0]
                resize_started = time.perf_counter_ns()
                root.resize(width, height)
                root.requestUpdate()
                resized = _process_until(
                    runtime.application,
                    lambda: root.width() == width and root.height() == height and frames[0] > frame_before,
                    0.25,
                )
                if resized:
                    resize_ack.append((time.perf_counter_ns() - resize_started) / 1_000_000)
                else:
                    missing_resize += 1
        _process_until(
            runtime.application,
            lambda: time.monotonic() >= started + 60,
            max(0.1, started + 60 - time.monotonic() + 0.1),
        )
    finally:
        sys.setprofile(None)
        controller._page_loader = original_loader
        release_readers.set()
        runtime.close()
    return {
        "acknowledged": True,
        "raw_samples": {
            "duration_s": 60,
            "reader_count": 2,
            "cpu_target_percent": 75,
            "navigation_ack_ms": navigation_ack,
            "resize_ack_ms": resize_ack,
            "gui_callback_ms": profiler.samples_ms,
            "missing_navigation_acknowledgements": missing_navigation,
            "missing_resize_acknowledgements": missing_resize,
        },
    }


def run_benchmark_request(request_path: Path) -> int:
    try:
        request = _read_request(request_path)
        runners = {
            "startup": _run_startup,
            "navigation": _run_navigation,
            "reader-stress": _run_reader_stress,
        }
        response = runners[request["scenario"]](request)
        _write_response(request["output_path"], response)
        return 0
    except (BenchmarkProbeError, OSError, RuntimeError, ValueError):
        return 87

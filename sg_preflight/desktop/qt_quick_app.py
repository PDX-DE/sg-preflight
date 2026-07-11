from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Sequence

try:
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtGui import QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
except ImportError as exc:
    raise RuntimeError(
        "Qt Quick desktop mode requires the optional PySide6 dependency. "
        "Install it with `pip install -e .[desktop]`."
    ) from exc

from sg_preflight.assets import runtime_asset_path
from sg_preflight.desktop.qt_quick_controller import DesktopController
from sg_preflight.desktop.qt_quick_grafiks import GrafiksHostAdapter
from sg_preflight.desktop.shell_model import ShellRegistryModel
from sg_preflight.desktop.surface_model import SurfaceRegistryModel
from sg_preflight.desktop.task_pool import PageTaskCoordinator


APPLICATION_NAME = "SGFX QA Preflight"
APPLICATION_ORGANIZATION = "Paradox Cat"
QML_ENTRY_POINT = "sg_preflight/desktop/qml/Main.qml"
_LOAD_ERROR = "The Qt Quick interface could not be initialized."


@dataclass(slots=True)
class QtQuickRuntime:
    application: QGuiApplication
    engine: QQmlApplicationEngine
    surface_model: SurfaceRegistryModel
    shell_model: ShellRegistryModel
    controller: DesktopController
    task_coordinator: PageTaskCoordinator
    grafiks_host: GrafiksHostAdapter | None = None
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.controller.shutdown()
        self.task_coordinator.shutdown(timeout_ms=500)
        for root in self.engine.rootObjects():
            close = getattr(root, "close", None)
            if callable(close):
                close()
        self.engine.clearComponentCache()
        self.application.processEvents()


def _application(argv: Sequence[str] | None) -> QGuiApplication:
    existing = QCoreApplication.instance()
    if existing is not None and not isinstance(existing, QGuiApplication):
        raise RuntimeError("Qt Quick requires a graphical application instance.")
    if existing is None:
        QQuickStyle.setStyle("Basic")
    application = existing or QGuiApplication(list(argv) if argv is not None else sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    application.setOrganizationName(APPLICATION_ORGANIZATION)
    application.setQuitOnLastWindowClosed(True)
    icon_path = runtime_asset_path("desktop_native/resources/exe_ico.ico")
    if not icon_path.is_file():
        icon_path = runtime_asset_path("sgfx_icon.png")
    if icon_path.is_file():
        icon = QIcon(str(icon_path))
        if not icon.isNull():
            application.setWindowIcon(icon)
    return application


def _shutdown_created(
    controller: DesktopController | None,
    task_coordinator: PageTaskCoordinator | None,
    grafiks_host: GrafiksHostAdapter | None = None,
) -> None:
    if controller is not None:
        controller.shutdown()
    elif grafiks_host is not None:
        grafiks_host.shutdown()
    if task_coordinator is not None:
        task_coordinator.shutdown(timeout_ms=500)


def _hide_qt_windows(engine: QQmlApplicationEngine) -> None:
    for root in engine.rootObjects():
        hide = getattr(root, "hide", None)
        if callable(hide):
            hide()


def _restore_qt_windows(engine: QQmlApplicationEngine) -> None:
    for root in engine.rootObjects():
        for method_name in ("show", "raise_", "requestActivate"):
            method = getattr(root, method_name, None)
            if callable(method):
                method()


def create_qt_quick_runtime(
    *,
    workspace: Path | str,
    initial_profile_id: str = "",
    bmw_root: Path | str | None = None,
    qml_path: Path | str | None = None,
    argv: Sequence[str] | None = None,
) -> QtQuickRuntime:
    source = Path(qml_path) if qml_path is not None else runtime_asset_path(QML_ENTRY_POINT)
    if not source.is_file():
        raise RuntimeError("The Qt Quick interface files are unavailable.")

    task_coordinator: PageTaskCoordinator | None = None
    grafiks_host: GrafiksHostAdapter | None = None
    controller: DesktopController | None = None
    try:
        application = _application(argv)
        engine = QQmlApplicationEngine()
        qml_import_root = runtime_asset_path("sg_preflight/desktop/qml")
        if not qml_import_root.is_dir():
            qml_import_root = source.parent
        engine.addImportPath(str(qml_import_root.resolve()))
        task_coordinator = PageTaskCoordinator(parent=engine)
        grafiks_host = GrafiksHostAdapter(
            coordinator=task_coordinator,
            workspace=workspace,
            bmw_root=bmw_root,
            parent=engine,
        )
        controller = DesktopController(
            workspace=workspace,
            initial_profile_id=initial_profile_id,
            bmw_root=bmw_root,
            task_coordinator=task_coordinator,
            grafiks_host=grafiks_host,
            parent=engine,
        )
        surface_model = SurfaceRegistryModel(parent=engine)
        shell_model = ShellRegistryModel(parent=engine)
        context = engine.rootContext()
        context.setContextProperty("surfaceModel", surface_model)
        context.setContextProperty("shellModel", shell_model)
        context.setContextProperty("desktopController", controller)
        context.setContextProperty("grafiksHost", grafiks_host)
        engine.setInitialProperties(
            {
                "surfaceModel": surface_model,
                "shellModel": shell_model,
                "desktopController": controller,
                "grafiksHost": grafiks_host,
            }
        )
        engine.load(QUrl.fromLocalFile(str(source.resolve())))
        if not engine.rootObjects():
            raise RuntimeError(_LOAD_ERROR)
        grafiks_host.hideRequested.connect(lambda: _hide_qt_windows(engine))
        grafiks_host.restoreRequested.connect(lambda: _restore_qt_windows(engine))
    except Exception:
        _shutdown_created(controller, task_coordinator, grafiks_host)
        raise RuntimeError(_LOAD_ERROR) from None

    return QtQuickRuntime(
        application=application,
        engine=engine,
        surface_model=surface_model,
        shell_model=shell_model,
        controller=controller,
        task_coordinator=task_coordinator,
        grafiks_host=grafiks_host,
    )


def run_qt_quick_app(
    *,
    workspace: Path | str,
    initial_profile_id: str = "",
    bmw_root: Path | str | None = None,
) -> int:
    runtime = create_qt_quick_runtime(
        workspace=workspace,
        initial_profile_id=initial_profile_id,
        bmw_root=bmw_root,
    )
    runtime.application.aboutToQuit.connect(runtime.close)
    try:
        return runtime.application.exec()
    finally:
        runtime.close()

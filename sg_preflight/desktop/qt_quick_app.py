from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
import sys
from typing import Callable, Sequence

try:
    from PySide6.QtCore import QCoreApplication, QUrl
    from PySide6.QtGui import QFontDatabase, QGuiApplication, QIcon
    from PySide6.QtQml import QQmlApplicationEngine
    from PySide6.QtQuickControls2 import QQuickStyle
except ImportError as exc:
    raise RuntimeError(
        "Qt Quick desktop mode requires the optional PySide6 dependency. "
        "Install it with `pip install -e .[desktop]`."
    ) from exc

from sg_preflight.assets import runtime_asset_path
from sg_preflight.desktop.preview_coordinator import PreviewCoordinator
from sg_preflight.desktop.preview_image_provider import PreviewImageProvider
from sg_preflight.desktop.qt_quick_controller import DesktopController
from sg_preflight.desktop.qt_quick_grafiks import GrafiksHostAdapter
from sg_preflight.desktop.shell_model import ShellRegistryModel
from sg_preflight.desktop.surface_model import SurfaceRegistryModel
from sg_preflight.desktop.task_pool import PageTaskCoordinator
from sg_preflight.profiles import RunProfile


APPLICATION_NAME = "Seriengrafik: Project Quality-Hero"
APPLICATION_ORGANIZATION = "Paradox Cat"
QML_ENTRY_POINT = "sg_preflight/desktop/qml/Main.qml"
PREVIEW_HELPER_ASSET = "cpp/bin/sgfx_cine_ramses_preview_cli.exe"
PREVIEW_PROVIDER_ID = "sgfx-preview"
_LOAD_ERROR = "The Qt Quick interface could not be initialized."


@dataclass(slots=True)
class QtQuickRuntime:
    application: QGuiApplication
    engine: QQmlApplicationEngine
    surface_model: SurfaceRegistryModel
    shell_model: ShellRegistryModel
    controller: DesktopController
    task_coordinator: PageTaskCoordinator
    preview_coordinator: PreviewCoordinator
    preview_image_provider: PreviewImageProvider
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


def _load_product_fonts() -> dict[str, str]:
    fallback = "sans-serif"
    if not isinstance(QCoreApplication.instance(), QGuiApplication):
        return {"operational": fallback, "display": fallback}
    families: dict[str, str] = {}
    for key, relative in (
        ("operational", "cpp/assets/fonts/Inter.ttf"),
        ("display", "cpp/assets/fonts/Fredoka.ttf"),
    ):
        font_id = QFontDatabase.addApplicationFont(str(runtime_asset_path(relative)))
        names = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        families[key] = names[0] if names else ""
    families["operational"] = families["operational"] or fallback
    families["display"] = families["display"] or families["operational"]
    return families


def _shutdown_created(
    controller: DesktopController | None,
    task_coordinator: PageTaskCoordinator | None,
    grafiks_host: GrafiksHostAdapter | None = None,
    preview_coordinator: PreviewCoordinator | None = None,
) -> None:
    if controller is not None:
        controller.shutdown()
    else:
        if grafiks_host is not None:
            grafiks_host.shutdown()
        if preview_coordinator is not None:
            preview_coordinator.shutdown()
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


def _preview_profile_resolver(
    workspace: Path,
    bmw_root: Path | None,
) -> Callable[[str], RunProfile | None]:
    def resolve(profile_id: str) -> RunProfile | None:
        from sg_preflight.bmw_delivery import discover_bmw_models_repo
        from sg_preflight.profiles import list_run_profiles

        try:
            profiles = list_run_profiles(workspace, bmw_root=bmw_root)
        except (OSError, RuntimeError, ValueError):
            return None
        profile = next(
            (profile for profile in profiles if profile.profile_id.casefold() == profile_id.casefold()),
            None,
        )
        if profile is None:
            return None
        source_root = (
            bmw_root
            if bmw_root is not None
            else discover_bmw_models_repo(workspace)
        ).absolute()
        project_root = source_root / profile.project_relative
        if not (project_root / "export" / "exported.ramses").is_file():
            return profile
        return replace(
            profile,
            repo_root=source_root,
            project_root=project_root,
            reference_repo_root=source_root,
        )

    return resolve


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
    preview_coordinator: PreviewCoordinator | None = None
    preview_image_provider: PreviewImageProvider | None = None
    controller: DesktopController | None = None
    try:
        application = _application(argv)
        product_fonts = _load_product_fonts()
        engine = QQmlApplicationEngine()
        qml_import_root = runtime_asset_path("sg_preflight/desktop/qml")
        if not qml_import_root.is_dir():
            qml_import_root = source.parent
        engine.addImportPath(str(qml_import_root.resolve()))
        preview_image_provider = PreviewImageProvider()
        engine.addImageProvider(PREVIEW_PROVIDER_ID, preview_image_provider)
        workspace_path = Path(workspace).resolve()
        bmw_root_path = Path(bmw_root).resolve() if bmw_root is not None else None
        preview_coordinator = PreviewCoordinator(
            cache_root=workspace_path / "out" / "preview-cache",
            helper_path=runtime_asset_path(PREVIEW_HELPER_ASSET),
            image_provider=preview_image_provider,
            profile_resolver=_preview_profile_resolver(workspace_path, bmw_root_path),
            parent=engine,
        )
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
            preview_coordinator=preview_coordinator,
            parent=engine,
        )
        surface_model = SurfaceRegistryModel(parent=engine)
        shell_model = ShellRegistryModel(parent=engine)
        context = engine.rootContext()
        context.setContextProperty("surfaceModel", surface_model)
        context.setContextProperty("shellModel", shell_model)
        context.setContextProperty("desktopController", controller)
        context.setContextProperty("grafiksHost", grafiks_host)
        context.setContextProperty("sgfxProductFonts", product_fonts)
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
    except Exception as exc:
        _shutdown_created(controller, task_coordinator, grafiks_host, preview_coordinator)
        # Keep the public message stable but preserve the cause: masking it hid a test-order
        # defect (a bare QCoreApplication created earlier in the process) for three full runs.
        raise RuntimeError(_LOAD_ERROR) from exc

    return QtQuickRuntime(
        application=application,
        engine=engine,
        surface_model=surface_model,
        shell_model=shell_model,
        controller=controller,
        task_coordinator=task_coordinator,
        preview_coordinator=preview_coordinator,
        preview_image_provider=preview_image_provider,
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
    _wire_shutdown(runtime)
    try:
        return runtime.application.exec()
    finally:
        runtime.close()


def _wire_shutdown(runtime: QtQuickRuntime) -> Callable[[], None]:
    # The slotted runtime cannot be weak-referenced, and connecting a bound method makes Qt take
    # a weak reference to its receiver - which only fails in the frozen launch path, since tests
    # drive create_qt_quick_runtime directly. A closure holds a strong reference and needs none.
    def close_runtime() -> None:
        runtime.close()

    runtime.application.aboutToQuit.connect(close_runtime)
    return close_runtime

from __future__ import annotations

import sys
from pathlib import Path

from sg_preflight.assets import runtime_asset_path
from sg_preflight.services import workspace_root


def _desktop_taskbar_icon_path() -> Path:
    icon_path = runtime_asset_path("desktop_native/resources/exe_ico.ico")
    if icon_path.is_file():
        return icon_path
    return runtime_asset_path("sgfx_icon.png")


def _desktop_tooltip_stylesheet() -> str:
    return """
QToolTip {
  color: #f4fbf7;
  background: rgba(18, 27, 31, 245);
  border: 1px solid rgba(78, 201, 176, 210);
  border-radius: 8px;
  padding: 8px 10px;
  font-family: "Segoe UI", "Bahnschrift", sans-serif;
  font-size: 12px;
}
"""


def run_desktop_app(*, workspace: Path | None = None, initial_profile_id: str = "", initial_mode: str = "clean") -> int:
    try:
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "Desktop Operator Shell requires the optional PySide6 dependency. "
            "Install it with `pip install -e .[desktop]`."
        ) from exc

    from sg_preflight.desktop.clean_host import CleanDashboardWindow
    from sg_preflight.desktop.theme import desktop_stylesheet

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Seriengrafik Project Quality-Hero")
    icon_path = _desktop_taskbar_icon_path()
    window_icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
    if not window_icon.isNull():
        app.setWindowIcon(window_icon)
    app.setStyleSheet(desktop_stylesheet() + _desktop_tooltip_stylesheet())
    controller = _DesktopModeController(
        workspace=workspace_root(workspace),
        initial_profile_id=initial_profile_id,
        window_icon=window_icon,
    )
    app.aboutToQuit.connect(controller.close_all)
    controller.show()
    return app.exec()


class _DesktopModeController:
    def __init__(
        self,
        *,
        workspace: Path,
        initial_profile_id: str,
        window_icon: object,
    ) -> None:
        self.workspace = workspace
        self.initial_profile_id = initial_profile_id
        self.window_icon = window_icon
        self.window: CleanDashboardWindow | None = None

    def show(self) -> None:
        window = self._ensure_window()
        self.window = window
        window.show()
        window.raise_()
        window.activateWindow()

    def close_all(self) -> None:
        if self.window is not None:
            self.window.close()
        self.window = None

    def _ensure_window(self) -> CleanDashboardWindow:
        if self.window is None:
            self.window = CleanDashboardWindow(
                workspace=self.workspace,
                initial_profile_id=self.initial_profile_id,
            )
            if self.window_icon is not None and not self.window_icon.isNull():
                self.window.setWindowIcon(self.window_icon)
        return self.window

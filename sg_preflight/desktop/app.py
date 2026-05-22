from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

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
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "Desktop Operator Shell requires the optional PySide6 dependency. "
            "Install it with `pip install -e .[desktop]`."
        ) from exc

    from sg_preflight.desktop.clean_host import CleanDashboardWindow
    from sg_preflight.desktop.main_window import DesktopMainWindow
    from sg_preflight.desktop.theme import desktop_stylesheet

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SGFX Desktop Operator Console")
    icon_path = _desktop_taskbar_icon_path()
    window_icon = QIcon(str(icon_path)) if icon_path.is_file() else QIcon()
    if not window_icon.isNull():
        app.setWindowIcon(window_icon)
    app.setStyleSheet(desktop_stylesheet() + _desktop_tooltip_stylesheet())
    controller = _DesktopModeController(
        workspace=workspace_root(workspace),
        initial_profile_id=initial_profile_id,
        clean_window_type=CleanDashboardWindow,
        grafiks_window_type=DesktopMainWindow,
        window_icon=window_icon,
    )
    app.aboutToQuit.connect(controller.close_all)
    controller.show(initial_mode)
    preload_mode = "grafiks" if _clean_presentation_mode(initial_mode) == "clean" else "clean"
    QTimer.singleShot(2500, lambda: controller.prewarm(preload_mode))
    return app.exec()


def _clean_presentation_mode(mode: str | None) -> str:
    normalized = str(mode or "clean").strip().casefold()
    return normalized if normalized in {"clean", "grafiks"} else "clean"


class _DesktopModeController:
    def __init__(
        self,
        *,
        workspace: Path,
        initial_profile_id: str,
        clean_window_type: type[CleanDashboardWindow],
        grafiks_window_type: type[DesktopMainWindow],
        window_icon: Any,
    ) -> None:
        self.workspace = workspace
        self.initial_profile_id = initial_profile_id
        self.clean_window_type = clean_window_type
        self.grafiks_window_type = grafiks_window_type
        self.window_icon = window_icon
        self.window: CleanDashboardWindow | DesktopMainWindow | None = None
        self._windows: dict[str, CleanDashboardWindow | DesktopMainWindow] = {}
        self._closing = False

    def show(self, mode: str) -> None:
        normalized = _clean_presentation_mode(mode)
        previous = self.window
        window = self._ensure_window(normalized)
        if previous is not None and previous is not window:
            previous.hide()
        self.window = window
        window.show()
        window.raise_()
        window.activateWindow()

    def prewarm(self, mode: str) -> None:
        normalized = _clean_presentation_mode(mode)
        if normalized in self._windows or self._closing:
            return
        window = self._ensure_window(normalized)
        window.hide()

    def close_all(self) -> None:
        self._closing = True
        for window in list(self._windows.values()):
            window.close()
        self._windows.clear()
        self.window = None

    def _ensure_window(self, mode: str) -> CleanDashboardWindow | DesktopMainWindow:
        normalized = _clean_presentation_mode(mode)
        cached = self._windows.get(normalized)
        if cached is not None:
            return cached
        if normalized == "grafiks":
            window = self.grafiks_window_type(
                workspace=self.workspace,
                initial_profile_id=self.initial_profile_id,
                initial_mode="grafiks",
            )
        else:
            window = self.clean_window_type(
                workspace=self.workspace,
                initial_profile_id=self.initial_profile_id,
            )
        if self.window_icon is not None and not self.window_icon.isNull():
            window.setWindowIcon(self.window_icon)
        window.switch_requested.connect(self.show)
        self._windows[normalized] = window
        return window

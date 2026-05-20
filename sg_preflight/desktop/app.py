from __future__ import annotations

import sys
from pathlib import Path

from sg_preflight.assets import runtime_asset_path
from sg_preflight.services import workspace_root


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
    from sg_preflight.desktop.main_window import DesktopMainWindow
    from sg_preflight.desktop.theme import desktop_stylesheet

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SGFX Desktop Operator Console")
    icon_path = runtime_asset_path("sgfx_icon.png")
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyleSheet(desktop_stylesheet())
    controller = _DesktopModeController(
        workspace=workspace_root(workspace),
        initial_profile_id=initial_profile_id,
        clean_window_type=CleanDashboardWindow,
        grafiks_window_type=DesktopMainWindow,
    )
    controller.show(initial_mode)
    return app.exec()


class _DesktopModeController:
    def __init__(
        self,
        *,
        workspace: Path,
        initial_profile_id: str,
        clean_window_type: type[CleanDashboardWindow],
        grafiks_window_type: type[DesktopMainWindow],
    ) -> None:
        self.workspace = workspace
        self.initial_profile_id = initial_profile_id
        self.clean_window_type = clean_window_type
        self.grafiks_window_type = grafiks_window_type
        self.window: CleanDashboardWindow | DesktopMainWindow | None = None

    def show(self, mode: str) -> None:
        normalized = str(mode or "clean").strip().casefold()
        if normalized not in {"clean", "grafiks"}:
            normalized = "clean"
        previous = self.window
        self.window = None
        if previous is not None:
            previous.close()
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
        window.switch_requested.connect(self.show)
        self.window = window
        window.show()

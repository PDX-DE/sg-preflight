from __future__ import annotations

import sys
from pathlib import Path

from sg_preflight.services import workspace_root


def run_desktop_app(*, workspace: Path | None = None, initial_profile_id: str = "") -> int:
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise RuntimeError(
            "Desktop Operator Shell requires the optional PySide6 dependency. "
            "Install it with `pip install -e .[desktop]`."
        ) from exc

    from sg_preflight.desktop.main_window import DesktopMainWindow
    from sg_preflight.desktop.theme import desktop_stylesheet

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("SG Preflight Desktop Operator Shell")
    app.setStyleSheet(desktop_stylesheet())
    window = DesktopMainWindow(
        workspace=workspace_root(workspace),
        initial_profile_id=initial_profile_id,
    )
    window.show()
    return app.exec()

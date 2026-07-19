"""Entry point that dispatches to the requested desktop UI mode, Clean or Qt Quick."""

from __future__ import annotations

from pathlib import Path


def run_desktop_app(
    *,
    workspace: Path | None = None,
    initial_profile_id: str = "",
    initial_mode: str = "clean",
    bmw_root: Path | None = None,
) -> int:
    mode = initial_mode.strip().casefold()
    if mode == "clean":
        from sg_preflight.desktop.clean_app import run_clean_desktop_app

        return run_clean_desktop_app(
            workspace=workspace,
            initial_profile_id=initial_profile_id,
            initial_mode=initial_mode,
        )
    if mode == "qt-quick":
        from sg_preflight.desktop.qt_quick_app import run_qt_quick_app

        resolved_workspace = workspace or Path(__file__).resolve().parents[2]
        return run_qt_quick_app(
            workspace=resolved_workspace,
            initial_profile_id=initial_profile_id,
            bmw_root=bmw_root,
        )
    raise ValueError(f"Unsupported desktop UI mode: {initial_mode}")

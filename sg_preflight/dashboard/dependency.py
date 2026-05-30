from __future__ import annotations

from typing import Any


NICEGUI_VERSION = "3.11.1"
NICEGUI_PACKAGE_PIN = f"nicegui[native]=={NICEGUI_VERSION}"
NICEGUI_SETUP_GUIDANCE = (
    "NiceGUI is required for `sg-preflight dashboard run`. "
    f"Install the dashboard dependency with `python -m pip install {NICEGUI_PACKAGE_PIN}` "
    "or install the project dependencies from pyproject.toml."
)


class NiceGuiUnavailable(RuntimeError):
    """Raised when the dashboard command is used without NiceGUI installed."""


def require_nicegui() -> Any:
    try:
        from nicegui import app, ui
    except ImportError as exc:  # pragma: no cover - exercised in CLI environments without NiceGUI
        raise NiceGuiUnavailable(NICEGUI_SETUP_GUIDANCE) from exc
    return ui, app

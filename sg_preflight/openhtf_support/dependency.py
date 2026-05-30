from __future__ import annotations

import importlib
from types import ModuleType


OPENHTF_PACKAGE_PIN = "openhtf==1.6.1"
OPENHTF_SETUP_GUIDANCE = (
    "OpenHTF is required for `sg-preflight station run`. "
    f"Install the station dependency with `python -m pip install {OPENHTF_PACKAGE_PIN}` "
    "or install the project dependencies from pyproject.toml."
)


class OpenHtfUnavailable(RuntimeError):
    """Raised when the station command is used without OpenHTF installed."""


def require_openhtf() -> ModuleType:
    try:
        return importlib.import_module("openhtf")
    except ImportError as exc:
        raise OpenHtfUnavailable(OPENHTF_SETUP_GUIDANCE) from exc


def require_openhtf_module(module_name: str) -> ModuleType:
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        raise OpenHtfUnavailable(OPENHTF_SETUP_GUIDANCE) from exc

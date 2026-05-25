from __future__ import annotations

import os
import subprocess
import sys
from typing import Any


_ORIGINAL_POPEN = subprocess.Popen
_PATCHED = False


def no_window_creationflags(existing: int | None = None) -> int:
    flags = int(existing or 0)
    if os.name == "nt":
        flags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return flags


def hidden_subprocess_kwargs() -> dict[str, int]:
    if os.name != "nt":
        return {}
    return {"creationflags": no_window_creationflags()}


def sgfx_cli_command(*args: str, bytecode: bool = True) -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    command = [sys.executable]
    if bytecode:
        command.append("-B")
    command.extend(["-m", "sg_preflight", *args])
    return command


def install_no_window_subprocess_patch() -> None:
    global _PATCHED
    if _PATCHED or os.name != "nt":
        return

    class _NoWindowPopen(_ORIGINAL_POPEN):  # type: ignore[misc, valid-type]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            kwargs["creationflags"] = no_window_creationflags(kwargs.get("creationflags"))
            super().__init__(*args, **kwargs)

    _NoWindowPopen.__name__ = "Popen"
    _NoWindowPopen.__qualname__ = "Popen"

    subprocess.Popen = _NoWindowPopen  # type: ignore[assignment]
    _PATCHED = True

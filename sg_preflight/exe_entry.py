from __future__ import annotations

import sys


DEFAULT_DOUBLE_CLICK_ARGS = ["dashboard", "run", "--ui-mode", "clean"]


def _restore_inherited_standard_handles() -> bool:
    try:
        import ctypes
        import msvcrt
        import os
    except ImportError:
        return False

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetStdHandle.restype = ctypes.c_void_p
    invalid_handle = ctypes.c_void_p(-1).value
    restored = False
    for name, handle_id, mode, flags in (
        ("stdin", -10, "r", os.O_RDONLY | os.O_TEXT),
        ("stdout", -11, "w", os.O_WRONLY | os.O_TEXT),
        ("stderr", -12, "w", os.O_WRONLY | os.O_TEXT),
    ):
        handle = kernel32.GetStdHandle(handle_id)
        if handle in (None, 0, invalid_handle):
            continue
        try:
            fd = msvcrt.open_osfhandle(int(handle), flags)
            stream = open(fd, mode, buffering=1, encoding="utf-8", errors="replace", closefd=False)
        except OSError:
            continue
        setattr(sys, name, stream)
        restored = True
    return restored


def attach_parent_console() -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        if _restore_inherited_standard_handles():
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        attached = bool(kernel32.AttachConsole(-1))
        if not attached and ctypes.get_last_error() != 5:
            return
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        try:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except OSError:
            pass
    except OSError:
        return


def main(argv: list[str] | None = None) -> int:
    from sg_preflight.cli import main as cli_main

    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        args = list(DEFAULT_DOUBLE_CLICK_ARGS)
    else:
        attach_parent_console()
    return cli_main(args)


if __name__ == "__main__":
    raise SystemExit(main())

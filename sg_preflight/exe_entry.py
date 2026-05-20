from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import sys
import tempfile
import traceback


DEFAULT_DOUBLE_CLICK_ARGS = ["dashboard", "run", "--ui-mode", "grafiks"]


def default_workspace() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys.executable).resolve().parent)
    return str(Path.cwd().resolve())


def _has_option(args: list[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _option_value(args: list[str], option: str) -> str | None:
    for index, arg in enumerate(args):
        if arg.startswith(f"{option}="):
            return arg.split("=", 1)[1]
        if arg == option and index + 1 < len(args):
            return args[index + 1]
    return None


def _is_dashboard_run(args: list[str]) -> bool:
    return len(args) >= 2 and args[0] == "dashboard" and args[1] == "run"


def _is_clean_dashboard(args: list[str]) -> bool:
    return (_option_value(args, "--ui-mode") or "clean").casefold() == "clean"


def _replace_or_append_option(args: list[str], option: str, value: str) -> list[str]:
    updated: list[str] = []
    replaced = False
    skip_next = False
    for index, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        if arg.startswith(f"{option}="):
            updated.append(f"{option}={value}")
            replaced = True
            continue
        if arg == option:
            updated.extend([option, value])
            replaced = True
            skip_next = index + 1 < len(args)
            continue
        updated.append(arg)
    if not replaced:
        updated.extend([option, value])
    return updated


def _with_default_workspace(args: list[str]) -> list[str]:
    if _is_dashboard_run(args) and not _has_option(args, "--workspace"):
        return [*args, "--workspace", default_workspace()]
    return args


def _with_frozen_clean_desktop_fallback(args: list[str]) -> list[str]:
    if (
        getattr(sys, "frozen", False)
        and _is_dashboard_run(args)
        and _is_clean_dashboard(args)
        and not _has_option(args, "--no-native")
    ):
        return _replace_or_append_option(args, "--ui-mode", "grafiks")
    return args


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
        ensure_standard_streams()
        return
    try:
        import ctypes

        if _restore_inherited_standard_handles():
            ensure_standard_streams()
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        attached = bool(kernel32.AttachConsole(-1))
        if not attached:
            ensure_standard_streams()
            return
        sys.stdout = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        sys.stderr = open("CONOUT$", "w", buffering=1, encoding="utf-8", errors="replace")
        try:
            sys.stdin = open("CONIN$", "r", encoding="utf-8", errors="replace")
        except OSError:
            pass
    except OSError:
        pass
    ensure_standard_streams()


def ensure_standard_streams() -> None:
    if _stream_needs_replacement(sys.stdin):
        sys.stdin = open(os.devnull, "r", encoding="utf-8", errors="replace")
    if _stream_needs_replacement(sys.stdout):
        sys.stdout = open(os.devnull, "w", buffering=1, encoding="utf-8", errors="replace")
    if _stream_needs_replacement(sys.stderr):
        sys.stderr = open(os.devnull, "w", buffering=1, encoding="utf-8", errors="replace")


def _stream_needs_replacement(stream: object) -> bool:
    if stream is None:
        return True
    if getattr(stream, "closed", False):
        return True
    try:
        fileno = stream.fileno()  # type: ignore[attr-defined]
    except (AttributeError, OSError, ValueError):
        return True
    try:
        os.fstat(fileno)
    except OSError:
        return True
    return False


def write_startup_error_log(exc: BaseException) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path(tempfile.gettempdir()) / f"sgfx-preflight-startup-{timestamp}.log"
    details = [
        "SGFX Preflight startup failed.",
        f"Executable: {sys.executable}",
        f"Arguments: {sys.argv[1:]}",
        f"Python frozen: {bool(getattr(sys, 'frozen', False))}",
        "",
        "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    ]
    path.write_text("\n".join(details), encoding="utf-8")
    return path


def show_startup_error(exc: BaseException, log_path: Path) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        message = (
            "SGFX Preflight could not start.\n\n"
            f"{type(exc).__name__}: {exc}\n\n"
            f"Details were written to:\n{log_path}"
        )
        ctypes.windll.user32.MessageBoxW(None, message, "SGFX Preflight startup error", 0x10)
    except Exception:
        return


def should_show_startup_error(args: list[str]) -> bool:
    if not args:
        return True
    if args[0] == "desktop":
        return True
    if _is_dashboard_run(args) and not _has_option(args, "--no-native"):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    from sg_preflight.cli import main as cli_main

    args = list(sys.argv[1:] if argv is None else argv)
    ensure_standard_streams()
    if not args:
        args = list(DEFAULT_DOUBLE_CLICK_ARGS)
    else:
        attach_parent_console()
    args = _with_default_workspace(args)
    args = _with_frozen_clean_desktop_fallback(args)
    return cli_main(args)


if __name__ == "__main__":
    startup_args = list(sys.argv[1:])
    try:
        raise SystemExit(main())
    except Exception as exc:
        log_path = write_startup_error_log(exc)
        if should_show_startup_error(startup_args):
            show_startup_error(exc, log_path)
        raise SystemExit(1)

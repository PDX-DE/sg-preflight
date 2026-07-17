from __future__ import annotations

from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import tempfile
import traceback

from sg_preflight.live_state import sanitize_payload


DEFAULT_DOUBLE_CLICK_ARGS = ["dashboard", "run", "--ui-mode", "qt-quick"]
DEFAULT_OPERATOR_WORKSPACE = Path(r"C:\repositories\trunk")
WORKSPACE_ENV = "SGFX_PREFLIGHT_WORKSPACE"
PACKAGING_IMPORT_PROBE_ENV = "SGFX_PACKAGING_IMPORT_PROBE"
BENCHMARK_REQUEST_ENV = "SGFX_QT_BENCHMARK_REQUEST"
PACKAGING_REQUIRED_IMPORTS = (
    "keyring",
    "keyring.backends.Windows",
    "PySide6",
    "PySide6.QtCore",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
)
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")


def _packaging_runtime_is_complete(
    imported: dict[str, object],
    *,
    qml_entry: Path | None = None,
) -> bool:
    try:
        qt_core = imported["PySide6.QtCore"]
        library_info = qt_core.QLibraryInfo  # type: ignore[attr-defined]
        library_path = library_info.LibraryPath
        libraries = Path(library_info.path(library_path.LibrariesPath))
        plugins = Path(library_info.path(library_path.PluginsPath))
        qml_imports = Path(library_info.path(library_path.QmlImportsPath))
        library_roots = [libraries]
        module_file = getattr(qt_core, "__file__", None)
        if isinstance(module_file, str) and module_file:
            library_roots.append(Path(module_file).resolve().parent)
        if qml_entry is None:
            from sg_preflight.assets import runtime_asset_path

            qml_entry = runtime_asset_path("sg_preflight/desktop/qml/Main.qml")
        libraries_complete = any(
            (root / "Qt6Qml.dll").is_file() and (root / "Qt6Quick.dll").is_file()
            for root in library_roots
        )
        required = (
            plugins / "platforms" / "qwindows.dll",
            qml_imports / "QtQuick" / "Controls" / "qmldir",
            Path(qml_entry),
        )
        return libraries_complete and all(path.is_file() for path in required)
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        return False


def _packaging_manifest_matches_runtime(
    imported: dict[str, object],
    *,
    manifest_path: Path,
) -> bool:
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return False
        from sg_preflight import __version__

        pyside6 = imported["PySide6"]
        qt_core = imported["PySide6.QtCore"]
        expected = {
            "schema_version": 1,
            "sgfx_version": __version__,
            "python_version": platform.python_version(),
            "pyside6_version": pyside6.__version__,  # type: ignore[attr-defined]
            "qt_version": qt_core.qVersion(),  # type: ignore[attr-defined]
            "qml_contract_version": 1,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            return False
        commit = payload.get("source_commit")
        modes = payload.get("presentation_modes")
        imports = payload.get("qml_imports")
        return (
            isinstance(commit, str)
            and _COMMIT_PATTERN.fullmatch(commit) is not None
            and isinstance(modes, list)
            and "clean" in modes
            and "qt-quick" in modes
            and isinstance(imports, list)
            and bool(imports)
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return False


def run_packaging_import_probe() -> int | None:
    if os.environ.get(PACKAGING_IMPORT_PROBE_ENV) != "1":
        return None
    try:
        imported: dict[str, object] = {}
        for module_name in PACKAGING_REQUIRED_IMPORTS:
            imported[module_name] = importlib.import_module(module_name)
        windows_backend = imported["keyring.backends.Windows"]
        if windows_backend.WinVaultKeyring.priority <= 0:  # type: ignore[attr-defined]
            return 86
        if not _packaging_runtime_is_complete(imported):
            return 86
        if getattr(sys, "frozen", False):
            manifest_path = Path(sys.executable).resolve().parent / "bundle-manifest.json"
            if not _packaging_manifest_matches_runtime(imported, manifest_path=manifest_path):
                return 86
    except Exception:
        return 86
    return 0


def run_qt_benchmark_probe() -> int | None:
    configured = os.environ.get(BENCHMARK_REQUEST_ENV, "").strip()
    if not configured:
        return None
    try:
        from sg_preflight.desktop.qt_quick_benchmark_probe import run_benchmark_request

        return run_benchmark_request(Path(configured))
    except Exception:
        return 87


def _svn_trunk_ancestor(path: Path) -> Path | None:
    for parent in path.parents:
        if parent.name.casefold() == "trunk" and parent.parent.name.casefold() == "repositories":
            return parent
    return None


def default_workspace() -> str:
    configured = os.environ.get(WORKSPACE_ENV, "").strip()
    if configured:
        return str(Path(configured).resolve())
    if getattr(sys, "frozen", False):
        executable_path = Path(sys.executable).resolve()
        trunk_ancestor = _svn_trunk_ancestor(executable_path)
        if trunk_ancestor is not None:
            return str(trunk_ancestor)
        if DEFAULT_OPERATOR_WORKSPACE.exists():
            return str(DEFAULT_OPERATOR_WORKSPACE.resolve())
        return str(executable_path.parent)
    return str(Path.cwd().resolve())


def _has_option(args: list[str], option: str) -> bool:
    return any(arg == option or arg.startswith(f"{option}=") for arg in args)


def _is_dashboard_run(args: list[str]) -> bool:
    return len(args) >= 2 and args[0] == "dashboard" and args[1] == "run"


def _uses_operator_workspace(args: list[str]) -> bool:
    return _is_dashboard_run(args) or bool(args and args[0] == "session-log")


def _with_default_workspace(args: list[str]) -> list[str]:
    if _uses_operator_workspace(args) and not _has_option(args, "--workspace"):
        return [*args, "--workspace", default_workspace()]
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


def install_frozen_runtime_hooks() -> None:
    if not getattr(sys, "frozen", False):
        return
    from sg_preflight.subprocess_utils import install_no_window_subprocess_patch

    install_no_window_subprocess_patch()


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
    path.write_text(str(sanitize_payload("\n".join(details))), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path


def show_startup_error(exc: BaseException, log_path: Path) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        detail = f"{type(exc).__name__}: {exc}"
        if len(detail) > 500:
            detail = detail[:497] + "..."
        message = (
            "SGFX Preflight could not start.\n\n"
            f"{detail}\n\n"
            f"Details were written to:\n{log_path}"
        )
        ctypes.windll.user32.MessageBoxW(None, message, "Seriengrafik: Project Quality-Hero - Startup Error", 0x10)
    except Exception:
        return


def should_show_startup_error(args: list[str]) -> bool:
    if not args:
        return True
    if _is_dashboard_run(args) and not _has_option(args, "--no-native"):
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    benchmark_result = run_qt_benchmark_probe()
    if benchmark_result is not None:
        return benchmark_result
    probe_result = run_packaging_import_probe()
    if probe_result is not None:
        return probe_result
    from sg_preflight.cli import main as cli_main

    args = list(sys.argv[1:] if argv is None else argv)
    install_frozen_runtime_hooks()
    try:
        from sg_preflight.session_log import install_exception_hooks

        install_exception_hooks()
    except Exception:
        pass
    ensure_standard_streams()
    if not args:
        args = list(DEFAULT_DOUBLE_CLICK_ARGS)
    else:
        attach_parent_console()
    args = _with_default_workspace(args)
    return cli_main(args)


if __name__ == "__main__":
    startup_args = list(sys.argv[1:])
    try:
        raise SystemExit(main())
    except Exception as exc:
        try:
            from sg_preflight.session_log import exception_event

            exception_event(surface="exe_entry", exc=exc, message="Packaged startup failed")
        except Exception:
            pass
        log_path = write_startup_error_log(exc)
        if should_show_startup_error(startup_args):
            show_startup_error(exc, log_path)
        raise SystemExit(1)

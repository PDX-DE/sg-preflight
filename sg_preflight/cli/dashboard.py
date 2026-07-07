from __future__ import annotations

import argparse
from importlib import import_module
from pathlib import Path
import sys

common = import_module("sg_preflight.cli")


def _show_native_fallback_notice(message: str, *, icon_error: bool) -> None:
    if sys.platform != "win32" or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Seriengrafik: Project Quality-Hero",
            0x10 if icon_error else 0x40,
        )
    except Exception:
        pass


def _frozen_browser_fallback(args: argparse.Namespace, reason: str) -> int | None:
    try:
        from sg_preflight.dashboard.main import _dashboard_run_port
        from sg_preflight.dashboard_webserver import (
            _launch_browser_fallback_process,
            append_startup_log,
        )

        append_startup_log(
            f"desktop shell unavailable ({reason}); opening the dashboard in the default browser"
        )
        fallback_port = _dashboard_run_port(native=False, port=int(getattr(args, "port", 0) or 0))
        exit_code = _launch_browser_fallback_process(
            profile_id=args.profile or "",
            workspace=Path(args.workspace).resolve(),
            bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
            ui_mode="clean",
            host=getattr(args, "host", None) or "127.0.0.1",
            fallback_port=fallback_port,
        )
    except Exception as exc:  # noqa: BLE001
        _show_native_fallback_notice(
            "The native SGFX window could not start, and the browser fallback also failed.\n\n"
            f"Native detail: {reason}\nFallback detail: {exc}",
            icon_error=True,
        )
        return None
    _show_native_fallback_notice(
        "The native SGFX window could not start on this machine.\n"
        "The dashboard is opening in your default browser instead.\n\n"
        f"Technical detail: {reason}",
        icon_error=False,
    )
    return exit_code


def handle_dashboard_command(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    if args.command == "station":
        try:
            from sg_preflight.openhtf_support.dependency import OpenHtfUnavailable
            from sg_preflight.openhtf_support.station import run_station

            if args.station_command == "run":
                return run_station(
                    profile_id=args.profile,
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    ui_mode=args.ui_mode,
                    port=args.port,
                    history_path=Path(args.history),
                    open_browser=not args.no_browser,
                    once=args.once,
                )
            parser.error(f"Unhandled station command: {args.station_command}")
            return 1
        except OpenHtfUnavailable as exc:
            print(common._console_safe(str(exc)), file=sys.stderr)
            return 1
        except Exception as exc:
            print(common._console_safe(f"station failed: {exc}"), file=sys.stderr)
            return 1

    if args.command == "dashboard":
        if args.dashboard_command == "run" and args.ui_mode == "grafiks":
            try:
                from sg_preflight.dashboard.main import run_grafiks_mode

                return run_grafiks_mode(
                    profile_id=args.profile or "",
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                )
            except Exception as exc:
                print(common._console_safe(f"dashboard grafiks failed: {exc}"), file=sys.stderr)
                return 1
        use_desktop_shell = (
            args.dashboard_command == "run"
            and (common._is_frozen_exe() and not args.no_native and args.ui_mode in {None, "clean"})
        )
        if use_desktop_shell:
            try:
                import os

                _existing = os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
                _flags = "--disable-background-timer-throttling --disable-backgrounding-occluded-windows --disable-renderer-backgrounding"
                os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (_existing + " " + _flags).strip()
                from sg_preflight.desktop.app import run_desktop_app

                return run_desktop_app(
                    workspace=Path(args.workspace),
                    initial_profile_id=args.profile or "",
                    initial_mode=args.ui_mode or "clean",
                )
            except RuntimeError as exc:
                print(common._console_safe(str(exc)), file=sys.stderr)
                fallback_code = _frozen_browser_fallback(args, str(exc))
                if fallback_code is not None:
                    return fallback_code
                return 1
        try:
            from sg_preflight.dashboard.dependency import NiceGuiUnavailable
            from sg_preflight.dashboard.main import run_dashboard

            if args.dashboard_command == "run":
                return run_dashboard(
                    profile_id=args.profile,
                    workspace=Path(args.workspace),
                    bmw_root=Path(args.bmw_root).resolve() if args.bmw_root else None,
                    ui_mode=args.ui_mode,
                    host=args.host,
                    port=args.port,
                    native=not args.no_native,
                    reload=args.reload,
                )
            parser.error(f"Unhandled dashboard command: {args.dashboard_command}")
            return 1
        except NiceGuiUnavailable as exc:
            print(common._console_safe(str(exc)), file=sys.stderr)
            return 1
        except Exception as exc:
            log_path = None
            if common._is_frozen_exe():
                try:
                    from sg_preflight.exe_entry import write_startup_error_log

                    log_path = write_startup_error_log(exc)
                except Exception:
                    log_path = None
                if args.dashboard_command == "run" and not args.no_native:
                    raise
            message = f"dashboard failed: {exc}"
            if log_path is not None:
                message = f"{message}. Details were written to: {log_path}"
            print(common._console_safe(message), file=sys.stderr)
            return 1

    parser.error(f"Unhandled dashboard command: {args.command}")
    return 1

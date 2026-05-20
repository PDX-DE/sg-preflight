from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
ENTRY_POINT_RELATIVE = Path("sg_preflight/exe_entry.py")
ENTRY_POINT = ROOT / ENTRY_POINT_RELATIVE
DIST_PATH = ROOT / "dist"
WORK_PATH = ROOT / "build" / "pyinstaller"
ICON_PATH = ROOT / "desktop_native" / "resources" / "exe_ico.ico"


def _data_arg(source: str, destination: str) -> str:
    return f"{ROOT / source}{os.pathsep}{destination}"


def build_pyinstaller_args() -> list[str]:
    data_files = (
        ("sgfx_icon.png", "."),
        ("framework_sgfx_logo.png", "."),
        ("logo_sgfx.png", "."),
        ("exe_ico.png", "."),
        ("desktop_native/resources/exe_ico.ico", "desktop_native/resources"),
        ("desktop_native/resources/debug_icon.ico", "desktop_native/resources"),
        ("sg_preflight/static", "sg_preflight/static"),
        ("sg_preflight/templates", "sg_preflight/templates"),
        ("sg_preflight/dashboard", "sg_preflight/dashboard"),
    )
    args = [
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        "sgfx-preflight",
        "--icon",
        str(ICON_PATH),
        "--distpath",
        str(DIST_PATH),
        "--workpath",
        str(WORK_PATH),
        "--specpath",
        str(WORK_PATH),
        "--collect-all",
        "nicegui",
        "--collect-all",
        "PySide6",
    ]
    for source, destination in data_files:
        args.extend(["--add-data", _data_arg(source, destination)])
    args.append(str(ENTRY_POINT))
    return args


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the SGFX Preflight Windows executable.")
    parser.add_argument("--print-args", action="store_true", help="Print PyInstaller arguments without building")
    args = parser.parse_args(argv)

    pyinstaller_args = build_pyinstaller_args()
    if args.print_args:
        for item in pyinstaller_args:
            print(item)
        return 0

    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("PyInstaller is required. Install with `pip install -e .[packaging]`.") from exc

    PyInstaller.__main__.run(pyinstaller_args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

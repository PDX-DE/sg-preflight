from __future__ import annotations

import argparse
from pathlib import Path
import shutil
import subprocess
import sys
from typing import Callable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QML_ROOT = ROOT / "sg_preflight" / "desktop" / "qml"


def find_qml_formatter() -> Path:
    candidates = (
        Path(sys.executable).with_name("pyside6-qmlformat.exe"),
        Path(sys.executable).with_name("pyside6-qmlformat"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    discovered = shutil.which("pyside6-qmlformat")
    if discovered:
        return Path(discovered).resolve()
    raise RuntimeError("The QML formatter is unavailable.")


def _normalize_newlines(value: bytes) -> bytes:
    return value.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def check_qml_format(
    qml_root: Path = DEFAULT_QML_ROOT,
    *,
    formatter: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[str, ...]:
    root = Path(qml_root)
    if not root.is_dir():
        raise RuntimeError("The QML source tree is unavailable.")
    executable = Path(formatter) if formatter is not None else find_qml_formatter()
    files = tuple(sorted(root.rglob("*.qml"), key=lambda path: path.relative_to(root).as_posix()))
    if not files:
        raise RuntimeError("The QML source tree is empty.")
    mismatches: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        try:
            completed = runner(
                [str(executable), str(path)],
                capture_output=True,
                check=False,
                timeout=30,
            )
            source = path.read_bytes()
        except (OSError, subprocess.SubprocessError):
            mismatches.append(relative)
            continue
        if (
            completed.returncode != 0
            or not isinstance(completed.stdout, bytes)
            or _normalize_newlines(completed.stdout) != _normalize_newlines(source)
        ):
            mismatches.append(relative)
    return tuple(mismatches)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the tracked QML tree with pyside6-qmlformat.")
    parser.add_argument("--qml-root", type=Path, default=DEFAULT_QML_ROOT)
    parser.add_argument("--formatter", type=Path)
    args = parser.parse_args(argv)
    try:
        mismatches = check_qml_format(args.qml_root, formatter=args.formatter)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if mismatches:
        print("QML formatting differs for:")
        for relative in mismatches:
            print(relative)
        return 1
    print("QML formatting is clean.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sg_preflight.bundle_manifest import (
    QmlImport,
    create_current_bundle_manifest,
    scan_qml_imports,
    validate_staged_bundle_contents,
    write_bundle_manifest,
)
from sg_preflight.grafiks_provenance import (
    GrafiksProvenance,
    GrafiksProvenanceError,
    accept_grafiks_bundle,
    copy_grafiks_provenance_evidence,
    grafiks_manifest_reference,
    license_manifest_covers_files,
    load_grafiks_provenance,
    sha256_file,
)


ENTRY_POINT_RELATIVE = Path("sg_preflight/exe_entry.py")
ENTRY_POINT = ROOT / ENTRY_POINT_RELATIVE
DIST_PATH = ROOT / "dist"
WORK_PATH = ROOT / "build" / "pyinstaller"
# Keep these short for PySide6 QML paths on Windows.
STAGING_DIST_PATH = ROOT / "build" / "b"
BACKUP_BUNDLE_PATH = ROOT / "build" / "p"
BACKUP_SINGLE_FILE_PATH = ROOT / "build" / "p.exe"
ICON_PATH = ROOT / "desktop_native" / "resources" / "exe_ico.ico"
GRAFIKS_RUNTIME_ENV = "SGFX_GRAFIKS_RUNTIME_DIR"
GRAFIKS_PROVENANCE_ENV = "SGFX_GRAFIKS_PROVENANCE_RECORD"
PACKAGING_IMPORT_PROBE_ENV = "SGFX_PACKAGING_IMPORT_PROBE"
PACKAGING_REQUIRED_IMPORTS = ("keyring", "keyring.backends.Windows")
GRAFIKS_RUNTIME_SOURCE = ROOT / "cpp" / "build" / "vs2022-ramses-28.16" / "Release"
GRAFIKS_RUNTIME_FILES = (
    "sgfx_cine_cinematic_shell.exe",
    "ramses-shared-lib-headless.dll",
    "ramses-shared-lib-renderer.dll",
    "ramses-shared-lib.dll",
    "SDL3.dll",
)
# The operator console (Grafiks mode) — its whole dist travels under _internal/grafiks_shell/
# so the double-clicked exe opens it instead of the cinematic R&D shell.
OPERATOR_CONSOLE_DIST_ENV = "SGFX_GRAFIKS_OPERATOR_CONSOLE_DIST"
OPERATOR_CONSOLE_DIST_SOURCE = Path(r"C:\swardbuild\sgfx_ui\dist")
OPERATOR_CONSOLE_SHELL_EXE_NAME = "sgfx_screens.exe"
GRAFIKS_BUNDLED_SHELL_DIR_NAME = "grafiks_shell"


def _data_arg(source: str, destination: str) -> str:
    return f"{ROOT / source}{os.pathsep}{destination}"


def validate_build_environment() -> None:
    try:
        imported: dict[str, object] = {}
        for module_name in PACKAGING_REQUIRED_IMPORTS:
            imported[module_name] = importlib.import_module(module_name)
        windows_backend = imported["keyring.backends.Windows"]
        if windows_backend.WinVaultKeyring.priority <= 0:  # type: ignore[attr-defined]
            raise RuntimeError("Windows credential backend is unavailable")
    except Exception as exc:
        raise SystemExit(
            "The build environment is missing required runtime dependencies. "
            "Install with `pip install -e .[packaging,desktop]`."
        ) from exc


def qml_package_inputs(qml_root: Path | None = None) -> tuple[Path, ...]:
    root = qml_root or ROOT / "sg_preflight" / "desktop" / "qml"
    qml_files = tuple(root.rglob("*.qml"))
    qmldir_files = tuple(root.rglob("qmldir"))
    if not qml_files or not qmldir_files:
        raise RuntimeError("Qt Quick package inputs are incomplete.")
    return tuple(sorted(qml_files + qmldir_files))


def build_pyinstaller_args(*, dist_path: Path = DIST_PATH) -> list[str]:
    qml_package_inputs()
    data_files = (
        ("sgfx_icon.png", "."),
        ("framework_sgfx_logo.png", "."),
        ("logo_sgfx.png", "."),
        ("exe_ico.png", "."),
        ("debug_icon.png", "."),
        ("desktop_native/resources/exe_ico.ico", "desktop_native/resources"),
        ("desktop_native/resources/debug_icon.ico", "desktop_native/resources"),
        ("sg_preflight/static", "sg_preflight/static"),
        ("sg_preflight/templates", "sg_preflight/templates"),
        ("sg_preflight/dashboard", "sg_preflight/dashboard"),
        ("sg_preflight/data", "sg_preflight/data"),
        ("sg_preflight/desktop/qml", "sg_preflight/desktop/qml"),
    )
    args = [
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        "sgfx-preflight",
        "--icon",
        str(ICON_PATH),
        "--distpath",
        str(dist_path),
        "--workpath",
        str(WORK_PATH),
        "--specpath",
        str(WORK_PATH),
        "--collect-all",
        "nicegui",
        "--collect-all",
        "PySide6",
        "--collect-all",
        "keyring",
        "--collect-all",
        "win32ctypes",
        "--hidden-import",
        "keyring.backends.Windows",
        "--hidden-import",
        "PySide6.QtQml",
        "--hidden-import",
        "PySide6.QtQuick",
        "--hidden-import",
        "PySide6.QtQuickControls2",
    ]
    for source, destination in data_files:
        args.extend(["--add-data", _data_arg(source, destination)])
    args.append(str(ENTRY_POINT))
    return args


def clean_staging_outputs() -> None:
    if STAGING_DIST_PATH.exists():
        shutil.rmtree(STAGING_DIST_PATH)


def _grafiks_runtime_source() -> Path | None:
    configured = os.environ.get(GRAFIKS_RUNTIME_ENV, "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(GRAFIKS_RUNTIME_SOURCE)
    for candidate in candidates:
        runtime_dir = candidate.resolve()
        if (runtime_dir / GRAFIKS_RUNTIME_FILES[0]).is_file():
            return runtime_dir
    return None


def copy_grafiks_runtime(
    bundle_dir: Path,
    provenance: GrafiksProvenance | None,
) -> list[Path]:
    runtime_dir = _grafiks_runtime_source()
    if runtime_dir is None:
        print("Grafiks C++ runtime not found; skipping optional runtime copy.")
        return []
    executable = runtime_dir / GRAFIKS_RUNTIME_FILES[0]
    if provenance is None or not accept_grafiks_bundle(executable, provenance):
        print("Grafiks provenance is absent or does not match; omitting the optional runtime.")
        return []
    if not license_manifest_covers_files(
        Path(provenance.license_manifest_path),
        GRAFIKS_RUNTIME_FILES,
    ):
        print("Grafiks license evidence is incomplete; omitting the optional runtime.")
        return []
    missing = [name for name in GRAFIKS_RUNTIME_FILES if not (runtime_dir / name).is_file()]
    if missing:
        print("Grafiks C++ runtime is incomplete; omitting the optional runtime.")
        return []

    target_dir = bundle_dir / "_internal"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    for name in GRAFIKS_RUNTIME_FILES:
        target = target_dir / name
        shutil.copy2(runtime_dir / name, target)
        copied.append(target)
    copied_executable = target_dir / GRAFIKS_RUNTIME_FILES[0]
    if sha256_file(copied_executable).casefold() != provenance.sha256.casefold():
        for target in copied:
            target.unlink(missing_ok=True)
        print("The copied Grafiks runtime changed; omitting the optional runtime.")
        return []
    copied.extend(
        copy_grafiks_provenance_evidence(
            provenance,
            target_dir / "grafiks-provenance",
        )
    )
    print("Copied the provenance-cleared Grafiks C++ runtime.")
    return copied


def _operator_console_dist_source() -> Path | None:
    configured = os.environ.get(OPERATOR_CONSOLE_DIST_ENV, "").strip()
    candidates = [Path(configured)] if configured else []
    candidates.append(OPERATOR_CONSOLE_DIST_SOURCE)
    for candidate in candidates:
        dist_dir = candidate.resolve()
        if (dist_dir / OPERATOR_CONSOLE_SHELL_EXE_NAME).is_file():
            return dist_dir
    return None


def copy_operator_console_shell(
    bundle_dir: Path,
    provenance: GrafiksProvenance | None,
) -> Path | None:
    dist_dir = _operator_console_dist_source()
    if dist_dir is None:
        print("Grafiks operator console dist not found; skipping optional copy.")
        return None
    executable = dist_dir / OPERATOR_CONSOLE_SHELL_EXE_NAME
    if provenance is None or not accept_grafiks_bundle(executable, provenance):
        print("Grafiks provenance is absent or does not match; omitting the optional operator console.")
        return None
    relative_files = tuple(
        sorted(path.relative_to(dist_dir).as_posix() for path in dist_dir.rglob("*") if path.is_file())
    )
    if not license_manifest_covers_files(
        Path(provenance.license_manifest_path),
        relative_files,
    ):
        print("Grafiks license evidence is incomplete; omitting the optional operator console.")
        return None
    target_dir = bundle_dir / "_internal" / GRAFIKS_BUNDLED_SHELL_DIR_NAME
    if target_dir.exists():
        shutil.rmtree(target_dir)
    shutil.copytree(dist_dir, target_dir)
    copied_executable = target_dir / OPERATOR_CONSOLE_SHELL_EXE_NAME
    if sha256_file(copied_executable).casefold() != provenance.sha256.casefold():
        shutil.rmtree(target_dir)
        print("The copied Grafiks operator console changed; omitting it.")
        return None
    copy_grafiks_provenance_evidence(provenance, target_dir / "provenance")
    print("Copied the provenance-cleared Grafiks operator console.")
    return target_dir / OPERATOR_CONSOLE_SHELL_EXE_NAME


def load_configured_grafiks_provenance() -> GrafiksProvenance | None:
    configured = os.environ.get(GRAFIKS_PROVENANCE_ENV, "").strip()
    if not configured:
        return None
    try:
        return load_grafiks_provenance(Path(configured))
    except GrafiksProvenanceError:
        print("Grafiks provenance is invalid; omitting all optional Grafiks binaries.")
        return None


def validate_staged_bundle(qml_imports: tuple[QmlImport, ...] | None = None) -> Path:
    bundle_dir = STAGING_DIST_PATH / "sgfx-preflight"
    exe_path = bundle_dir / "sgfx-preflight.exe"
    if not exe_path.is_file():
        raise SystemExit("PyInstaller did not produce the expected executable.")
    if qml_imports is not None:
        try:
            validate_staged_bundle_contents(bundle_dir, qml_imports)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
    environment = os.environ.copy()
    environment[PACKAGING_IMPORT_PROBE_ENV] = "1"
    for key in ("QML2_IMPORT_PATH", "QML_IMPORT_PATH", "QT_PLUGIN_PATH", "PYTHONPATH"):
        environment.pop(key, None)
    try:
        probe = subprocess.run(
            [str(exe_path)],
            cwd=bundle_dir,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired as exc:
        raise SystemExit("Packaged runtime dependency validation timed out.") from exc
    if probe.returncode != 0:
        raise SystemExit(
            "Packaged runtime dependency validation failed. "
            "Reinstall with `pip install -e .[packaging,desktop]` and rebuild."
        )
    return bundle_dir


def _remove_existing(path: Path) -> None:
    if path.is_dir():
        shutil.rmtree(path)
    elif path.exists():
        path.unlink()


def _rename_existing(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    source.rename(target)


def swap_staged_bundle(staged_bundle: Path) -> None:
    DIST_PATH.mkdir(parents=True, exist_ok=True)
    WORK_PATH.mkdir(parents=True, exist_ok=True)
    final_bundle = DIST_PATH / "sgfx-preflight"
    final_single_file = DIST_PATH / "sgfx-preflight.exe"
    backup_bundle = BACKUP_BUNDLE_PATH
    backup_single_file = BACKUP_SINGLE_FILE_PATH

    _remove_existing(backup_bundle)
    _remove_existing(backup_single_file)

    moved_bundle = False
    moved_single_file = False
    try:
        if final_bundle.exists():
            _rename_existing(final_bundle, backup_bundle)
            moved_bundle = True
        if final_single_file.exists():
            _rename_existing(final_single_file, backup_single_file)
            moved_single_file = True
        shutil.move(str(staged_bundle), str(final_bundle))
    except Exception:
        if moved_bundle and backup_bundle.exists() and not final_bundle.exists():
            _rename_existing(backup_bundle, final_bundle)
        if moved_single_file and backup_single_file.exists() and not final_single_file.exists():
            _rename_existing(backup_single_file, final_single_file)
        raise
    _remove_existing(backup_bundle)
    _remove_existing(backup_single_file)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the SGFX Preflight Windows executable.")
    parser.add_argument("--print-args", action="store_true", help="Print PyInstaller arguments without building")
    args = parser.parse_args(argv)

    pyinstaller_args = build_pyinstaller_args(dist_path=STAGING_DIST_PATH)
    if args.print_args:
        for item in pyinstaller_args:
            print(item)
        return 0

    validate_build_environment()
    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("PyInstaller is required. Install with `pip install -e .[packaging]`.") from exc

    clean_staging_outputs()
    PyInstaller.__main__.run(pyinstaller_args)
    staged_bundle = STAGING_DIST_PATH / "sgfx-preflight"
    qml_imports = scan_qml_imports(ROOT / "sg_preflight" / "desktop" / "qml")
    provenance = load_configured_grafiks_provenance()
    copied_operator = copy_operator_console_shell(staged_bundle, provenance)
    copied_runtime = [] if copied_operator is not None else copy_grafiks_runtime(staged_bundle, provenance)
    accepted_provenance = provenance if copied_operator is not None or copied_runtime else None
    manifest = create_current_bundle_manifest(
        ROOT,
        qml_imports,
        grafiks_reference=(
            grafiks_manifest_reference(accepted_provenance)
            if accepted_provenance is not None
            else None
        ),
    )
    write_bundle_manifest(staged_bundle, manifest)
    staged_bundle = validate_staged_bundle(qml_imports)
    swap_staged_bundle(staged_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

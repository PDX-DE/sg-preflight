from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sg_preflight.bundle_manifest import (
    PREVIEW_RUNTIME_FILES,
    PRODUCT_FONT_SHA256,
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
FRESH_DISTPATH_PREFIX = "s-"
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
PROTECTED_FONT_TOKENS = ("dynafont", "rodin", "sonic", "sega", "gamefont")
PREVIEW_RUNTIME_SOURCE = ROOT / "cpp" / "bin"


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


def product_font_package_inputs(font_root: Path | None = None) -> tuple[Path, ...]:
    root = font_root or ROOT / "cpp" / "assets" / "fonts"
    if not root.is_dir() or root.is_symlink() or getattr(root, "is_junction", lambda: False)():
        raise RuntimeError("The audited product font directory is unavailable.")
    files = tuple(sorted(root.iterdir()))
    if tuple(path.name for path in files) != tuple(PRODUCT_FONT_SHA256) or any(
        not path.is_file() for path in files
    ):
        raise RuntimeError("The product font directory contains an unaudited asset set.")
    for path in files:
        if path.is_symlink() or getattr(path, "is_junction", lambda: False)():
            raise RuntimeError("A product font asset is linked.")
        if any(token in path.name.casefold() for token in PROTECTED_FONT_TOKENS):
            raise RuntimeError("A protected font asset is not permitted.")
        if sha256_file(path).casefold() != PRODUCT_FONT_SHA256[path.name]:
            raise RuntimeError("A product font asset failed its audit digest.")
    for license_name in ("OFL-Fredoka.txt", "OFL-Inter.txt"):
        license_text = (root / license_name).read_text(encoding="utf-8")
        if "SIL OPEN FONT LICENSE Version 1.1" not in license_text:
            raise RuntimeError("A product font OFL record is invalid.")
    return files


def copy_preview_runtime(
    bundle_dir: Path,
    source_dir: Path = PREVIEW_RUNTIME_SOURCE,
) -> bool:
    target = Path(bundle_dir) / "_internal" / "cpp" / "bin"
    if target.exists():
        shutil.rmtree(target)
    source = Path(source_dir)
    if not source.is_dir() or source.is_symlink() or getattr(source, "is_junction", lambda: False)():
        return False
    entries = tuple(sorted(source.iterdir()))
    if {path.name for path in entries} != set(PREVIEW_RUNTIME_FILES) or any(
        not path.is_file()
        or path.is_symlink()
        or getattr(path, "is_junction", lambda: False)()
        for path in entries
    ):
        return False
    source_hashes = {path.name: sha256_file(path) for path in entries}
    target.mkdir(parents=True)
    for path in entries:
        shutil.copy2(path, target / path.name)
    if any(sha256_file(target / name) != digest for name, digest in source_hashes.items()):
        shutil.rmtree(target)
        return False
    return True


def remove_private_install_metadata(bundle_dir: Path) -> tuple[Path, ...]:
    bundle = Path(bundle_dir)
    removed: list[Path] = []
    # rglob follows junctions; the guarded walk keeps the unlink inside the bundle.
    for path in _iter_tree(bundle):
        if path.name == "direct_url.json" and path.is_file() and \
                path.parent.name.casefold().endswith(".dist-info"):
            path.unlink()
            removed.append(path)
    return tuple(sorted(removed))


def _qml_cache_generator() -> Path:
    candidates = (
        Path(sys.executable).with_name("pyside6-qmlcachegen.exe"),
        Path(sys.executable).with_name("pyside6-qmlcachegen"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    discovered = shutil.which("pyside6-qmlcachegen")
    if discovered:
        return Path(discovered).resolve()
    raise RuntimeError("The QML cache generator is unavailable.")


def prune_staged_qml_roots(
    bundle_dir: Path,
    qml_imports: Sequence[QmlImport],
) -> tuple[str, ...]:
    bundle = Path(bundle_dir).resolve()
    qml_root = bundle / "_internal" / "PySide6" / "qml"
    if (
        not qml_root.is_dir()
        or qml_root.is_symlink()
        or getattr(qml_root, "is_junction", lambda: False)()
        or not qml_imports
        or any(not isinstance(item, QmlImport) for item in qml_imports)
    ):
        raise RuntimeError("The staged Qt QML roots are unavailable.")
    allowed_roots = {
        item.module.split(".", 1)[0]
        for item in qml_imports
        if item.module not in {"QML", "SGFX"}
    }
    if not allowed_roots or any(not (qml_root / name).is_dir() for name in allowed_roots):
        raise RuntimeError("The staged Qt QML roots are unavailable.")
    candidates = tuple(
        sorted(
            (path for path in qml_root.iterdir() if path.is_dir() and path.name not in allowed_roots),
            key=lambda path: path.name,
        )
    )
    for candidate in candidates:
        if (
            candidate.is_symlink()
            or getattr(candidate, "is_junction", lambda: False)()
            or not candidate.resolve().is_relative_to(qml_root)
        ):
            raise RuntimeError("The staged Qt QML roots are unavailable.")
    for candidate in candidates:
        shutil.rmtree(candidate)
    return tuple(path.name for path in candidates)


def compile_staged_qml_cache(
    bundle_dir: Path,
    *,
    generator: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[bytes]] = subprocess.run,
) -> tuple[Path, ...]:
    bundle = Path(bundle_dir)
    qml_root = bundle / "_internal" / "sg_preflight" / "desktop" / "qml"
    qt_qml_root = bundle / "_internal" / "PySide6" / "qml"
    executable = Path(generator) if generator is not None else _qml_cache_generator()
    sources = tuple(sorted(
        path for path in _iter_tree(qml_root) if path.suffix == ".qml" and path.is_file()))
    if not executable.is_file() or not qml_root.is_dir() or not qt_qml_root.is_dir() or not sources:
        raise RuntimeError("The staged QML cache inputs are unavailable.")
    compiled: list[Path] = []
    for source in sources:
        output = source.with_suffix(source.suffix + "c")
        command = [
            str(executable),
            "--only-bytecode",
            "-I",
            str(qml_root),
            "-I",
            str(qt_qml_root),
            "-o",
            str(output),
            str(source),
        ]
        try:
            completed = runner(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise RuntimeError("The staged QML cache could not be generated.") from exc
        if completed.returncode != 0 or not output.is_file():
            raise RuntimeError("The staged QML cache could not be generated.")
        compiled.append(output)
    private_paths = (str(ROOT.resolve()), str(bundle.resolve()))
    for output in compiled:
        payload = output.read_bytes()
        variants = tuple(
            value.encode(encoding)
            for path in private_paths
            for value in (path, path.replace("\\", "/"))
            for encoding in ("utf-8", "utf-16-le")
        )
        if any(variant in payload for variant in variants):
            raise RuntimeError("The staged QML cache contains a private build path.")
    return tuple(compiled)


def build_pyinstaller_args(*, dist_path: Path = DIST_PATH) -> list[str]:
    qml_package_inputs()
    product_fonts = product_font_package_inputs()
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
    ) + tuple(
        (path.relative_to(ROOT).as_posix(), "cpp/assets/fonts")
        for path in product_fonts
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


def _is_link(path: Path) -> bool:
    # NTFS junctions report is_dir() true and is_symlink() FALSE, so both spellings are needed
    # before any tree walk may descend; following a junction can cycle or escape the tree.
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _iter_tree(root: Path):
    # Every entry beneath root, never descending into symlinks or junctions — including a root
    # that is itself a link.
    pending = [] if _is_link(root) else [root]
    while pending:
        directory = pending.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            yield child
            try:
                if child.is_dir() and not _is_link(child):
                    pending.append(child)
            except OSError:
                continue


def _is_directory_skeleton(path: Path) -> bool:
    return all(entry.is_dir() and not _is_link(entry) for entry in _iter_tree(path))


def _rmtree_tolerating_held_dirs(root: Path) -> None:
    # A Windows Explorer/terminal handle on a directory blocks its rmdir but not writes into it,
    # and PyInstaller runs with --noconfirm. Every file must still be removable; only empty
    # directory skeletons may survive. Junctions are removed as reparse points, never entered.
    for path in sorted(_iter_tree(root), key=lambda entry: len(entry.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError:
            if path.is_dir() and _is_directory_skeleton(path):
                continue
            raise
    try:
        root.rmdir()
    except OSError:
        if not _is_directory_skeleton(root):
            raise


def clean_staging_outputs() -> None:
    if STAGING_DIST_PATH.exists():
        _rmtree_tolerating_held_dirs(STAGING_DIST_PATH)
    # Failed builds deliberately leave their fresh distpath behind (so a partial relocate never
    # destroys assembled output); sweep only stale leftovers so a concurrently running build's
    # live distpath survives, and never let an undeletable leftover block a build that does not
    # need it removed.
    if STAGING_DIST_PATH.parent.is_dir():
        cutoff = time.time() - 2.0 * 3600.0
        for leftover in STAGING_DIST_PATH.parent.glob(f"{FRESH_DISTPATH_PREFIX}*"):
            try:
                # A link with our prefix was never created by this build; sweeping it would
                # walk straight through the reparse point into a foreign target.
                if not leftover.is_dir() or _is_link(leftover):
                    continue
                if _tree_newest_mtime(leftover) > cutoff:
                    continue
                _rmtree_tolerating_held_dirs(leftover)
            except OSError:
                continue


def _tree_newest_mtime(root: Path) -> float:
    # NTFS freezes a directory's own mtime once its direct-child listing stops changing, so a
    # live build writing deep inside a distpath keeps only nested timestamps fresh. Staleness
    # must therefore consider every entry in the tree.
    newest = root.stat().st_mtime
    for path in _iter_tree(root):
        try:
            # Links are not build outputs and their targets are not part of this tree.
            if _is_link(path):
                continue
            newest = max(newest, path.stat().st_mtime)
        except OSError:
            continue
    return newest


def _merge_move_into_held(source: Path, dest: Path) -> None:
    # Move the *contents* of source into dest. dest may already exist and carry an external
    # directory handle that blocks its own removal but still permits writes into it; a same-named
    # held subdirectory is merged into rather than replaced, so a nested hold never nests the tree.
    # The freshly built source is authoritative: if a stale destination entry has the wrong type
    # (a file where a directory belongs, or vice versa), it is cleared rather than crashing the swap.
    dest.mkdir(parents=True, exist_ok=True)
    for child in sorted(source.iterdir()):
        if _is_link(child):
            # PyInstaller output never contains links; relocating one would either merge foreign
            # content through it or leave a live reparse point inside the shipped bundle.
            raise OSError(f"unexpected link in build output: {child}")
        target = dest / child.name
        child_is_dir = child.is_dir()
        target_exists = target.exists() or target.is_symlink()
        if target_exists and _is_link(target):
            # A stale link at the destination is cleared as a reparse point; its target is
            # foreign and stays untouched.
            if target.is_dir():
                target.rmdir()
            else:
                target.unlink()
            target_exists = False
        target_is_dir = target_exists and target.is_dir()
        if child_is_dir:
            if target_exists and not target_is_dir:
                target.unlink()
                target_exists = False
            if not target_exists:
                shutil.move(str(child), str(target))
            else:
                _merge_move_into_held(child, target)
                try:
                    child.rmdir()
                except OSError:
                    if not _is_directory_skeleton(child):
                        raise
        else:
            if target_is_dir:
                _rmtree_tolerating_held_dirs(target)
                if target.exists():
                    raise OSError(
                        f"cannot place file {child} over a held directory at {target}")
            elif target_exists:
                target.unlink()
            shutil.move(str(child), str(target))


def relocate_fresh_bundle(source_bundle: Path, dest_bundle: Path) -> Path:
    # PyInstaller assembles into a fresh, unheld distpath because its own --noconfirm cleanup
    # rmtrees the output directory before assembling, and an Explorer-style handle on the canonical
    # staging directory makes that rmtree fail. Move the finished bundle into the canonical path,
    # which may survive from a prior run only as a held-but-empty skeleton.
    _merge_move_into_held(source_bundle, dest_bundle)
    return dest_bundle


def _fresh_staging_distpath() -> Path:
    # A never-before-used distpath so PyInstaller's own --noconfirm rmtree never has to touch a
    # held canonical output directory. Kept as short as a unique name allows, because the entire
    # bundle (including the deep QtQuick QML assets) is assembled beneath it and Windows still
    # caps most build tools near MAX_PATH; the fixed prefix makes leftovers from failed builds
    # identifiable so clean_staging_outputs can sweep them.
    STAGING_DIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=FRESH_DISTPATH_PREFIX, dir=str(STAGING_DIST_PATH.parent)))


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
    if _is_link(dist_dir) or any(_is_link(path) for path in _iter_tree(dist_dir)):
        # copytree recurses into junctions and would materialize foreign content in the bundle.
        print("The Grafiks operator console dist contains links; omitting the optional operator console.")
        return None
    executable = dist_dir / OPERATOR_CONSOLE_SHELL_EXE_NAME
    if provenance is None or not accept_grafiks_bundle(executable, provenance):
        print("Grafiks provenance is absent or does not match; omitting the optional operator console.")
        return None
    relative_files = tuple(
        sorted(path.relative_to(dist_dir).as_posix() for path in _iter_tree(dist_dir) if path.is_file())
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

    # Self-heal a previously interrupted swap: the backup is the last known good bundle and is
    # only redundant while the canonical bundle exists, so restore it before clearing anything.
    if not final_bundle.exists() and backup_bundle.exists():
        _rename_existing(backup_bundle, final_bundle)
    if not final_single_file.exists() and backup_single_file.exists():
        _rename_existing(backup_single_file, final_single_file)
    _remove_existing(backup_bundle)
    _remove_existing(backup_single_file)

    # Copy first: reading the staged bundle succeeds even when an external handle blocks moves
    # out of it, and a failed copy leaves every original untouched. The swap itself then commits
    # through whole-directory renames, so the canonical path never holds a partial bundle and no
    # failure path ever deletes the only copy of anything.
    # Ship gate: copytree recurses into junctions, so a link anywhere in the staged bundle
    # would bake foreign content into the delivered product. Nothing legitimate puts one there.
    if _is_link(staged_bundle) or any(_is_link(path) for path in _iter_tree(staged_bundle)):
        raise OSError("the staged bundle contains links; refusing to ship it")
    staged_copy = DIST_PATH / "sgfx-preflight.new"
    if staged_copy.exists():
        _rmtree_tolerating_held_dirs(staged_copy)
    moved_bundle = False
    moved_single_file = False
    try:
        shutil.copytree(staged_bundle, staged_copy, dirs_exist_ok=True)
        if final_bundle.exists():
            _rename_existing(final_bundle, backup_bundle)
            moved_bundle = True
        if final_single_file.exists():
            _rename_existing(final_single_file, backup_single_file)
            moved_single_file = True
        staged_copy.rename(final_bundle)
    except Exception:
        if moved_bundle and backup_bundle.exists() and not final_bundle.exists():
            _rename_existing(backup_bundle, final_bundle)
        if moved_single_file and backup_single_file.exists() and not final_single_file.exists():
            _rename_existing(backup_single_file, final_single_file)
        if staged_copy.exists():
            _rmtree_tolerating_held_dirs(staged_copy)
        raise
    _remove_existing(backup_bundle)
    _remove_existing(backup_single_file)
    # Post-commit cleanup only: a held staging directory must not fail a completed swap.
    try:
        _rmtree_tolerating_held_dirs(staged_bundle)
    except OSError:
        print("The staged bundle directory is still held; the swap itself completed.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the SGFX Preflight Windows executable.")
    parser.add_argument("--print-args", action="store_true", help="Print PyInstaller arguments without building")
    parser.add_argument("--staged-only", action="store_true", help="Validate the staged bundle without swapping the accepted default")
    args = parser.parse_args(argv)

    if args.print_args:
        for item in build_pyinstaller_args(dist_path=STAGING_DIST_PATH):
            print(item)
        return 0

    validate_build_environment()
    try:
        import PyInstaller.__main__
    except ImportError as exc:
        raise SystemExit("PyInstaller is required. Install with `pip install -e .[packaging]`.") from exc

    clean_staging_outputs()
    fresh_dist = _fresh_staging_distpath()
    PyInstaller.__main__.run(build_pyinstaller_args(dist_path=fresh_dist))
    staged_bundle = relocate_fresh_bundle(
        fresh_dist / "sgfx-preflight", STAGING_DIST_PATH / "sgfx-preflight"
    )
    # Remove the fresh distpath only after a successful relocate; on any failure above it is left
    # intact so a partial move never destroys freshly assembled output that had not yet been moved.
    if fresh_dist.exists():
        _rmtree_tolerating_held_dirs(fresh_dist)
    remove_private_install_metadata(staged_bundle)
    qml_imports = scan_qml_imports(ROOT / "sg_preflight" / "desktop" / "qml")
    prune_staged_qml_roots(staged_bundle, qml_imports)
    compile_staged_qml_cache(staged_bundle)
    provenance = load_configured_grafiks_provenance()
    copied_operator = copy_operator_console_shell(staged_bundle, provenance)
    copied_runtime = [] if copied_operator is not None else copy_grafiks_runtime(staged_bundle, provenance)
    preview_included = copy_preview_runtime(staged_bundle)
    accepted_provenance = provenance if copied_operator is not None or copied_runtime else None
    manifest = create_current_bundle_manifest(
        ROOT,
        qml_imports,
        grafiks_reference=(
            grafiks_manifest_reference(accepted_provenance)
            if accepted_provenance is not None
            else None
        ),
        ramses_preview_helper="included" if preview_included else "unavailable",
    )
    write_bundle_manifest(staged_bundle, manifest)
    staged_bundle = validate_staged_bundle(qml_imports)
    if not args.staged_only:
        swap_staged_bundle(staged_bundle)
    else:
        print(staged_bundle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

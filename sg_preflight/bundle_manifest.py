from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
from typing import Any, Callable, Mapping, Sequence


BUNDLE_MANIFEST_NAME = "bundle-manifest.json"
BUNDLE_MANIFEST_SCHEMA_VERSION = 1
QML_CONTRACT_VERSION = 1
_REQUIRED_QML_MODULES = frozenset({"QtQml", "QtQuick", "QtQuick.Controls"})
_BUILTIN_QML_MODULES = frozenset({"QML"})
_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_PLUGIN_PATTERN = re.compile(r"^(?:[A-Za-z0-9_][A-Za-z0-9_.-]*)?$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]{0,63}$")
_COMMIT_PATTERN = re.compile(r"^[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?$")
_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_GRAFIKS_REFERENCE_KEYS = frozenset(
    {
        "sha256",
        "notice_sha256",
        "license_manifest_sha256",
        "dependency_inventory_sha256",
    }
)


class BundleManifestError(ValueError):
    pass


@dataclass(frozen=True, order=True, slots=True)
class QmlImport:
    module: str
    plugin: str = ""

    def as_manifest_entry(self) -> dict[str, str]:
        return {"module": self.module, "plugin": self.plugin}


def find_qml_import_scanner() -> Path:
    candidates = (
        Path(sys.executable).with_name("pyside6-qmlimportscanner.exe"),
        Path(sys.executable).with_name("pyside6-qmlimportscanner"),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    discovered = shutil.which("pyside6-qmlimportscanner")
    if discovered:
        return Path(discovered).resolve()
    raise BundleManifestError("The QML import scanner is unavailable.")


def qt_qml_import_root() -> Path:
    try:
        import PySide6
    except ImportError as exc:
        raise BundleManifestError("The Qt QML import root is unavailable.") from exc
    root = Path(PySide6.__file__).resolve().parent / "qml"
    if not root.is_dir():
        raise BundleManifestError("The Qt QML import root is unavailable.")
    return root


def scan_qml_imports(
    qml_root: Path,
    *,
    scanner_executable: Path | None = None,
    qt_qml_root: Path | None = None,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[QmlImport, ...]:
    source_root = Path(qml_root)
    scanner = Path(scanner_executable) if scanner_executable is not None else find_qml_import_scanner()
    import_root = Path(qt_qml_root) if qt_qml_root is not None else qt_qml_import_root()
    if not source_root.is_dir() or not scanner.is_file() or not import_root.is_dir():
        raise BundleManifestError("The QML import scan inputs are unavailable.")
    command = [
        str(scanner.resolve()),
        "-rootPath",
        str(source_root.resolve()),
        "-importPath",
        str(import_root.resolve()),
    ]
    try:
        completed = runner(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleManifestError("The QML import scan could not be completed.") from exc
    if completed.returncode != 0:
        raise BundleManifestError("The QML import scan could not be completed.")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise BundleManifestError("The QML import scan returned invalid data.") from exc
    if not isinstance(payload, list):
        raise BundleManifestError("The QML import scan returned invalid data.")
    imports: set[QmlImport] = set()
    for item in payload:
        if not isinstance(item, Mapping) or item.get("type") != "module":
            continue
        module = item.get("name")
        plugin = item.get("plugin", "")
        if not isinstance(module, str) or _MODULE_PATTERN.fullmatch(module) is None:
            raise BundleManifestError("The QML import scan returned invalid data.")
        if not isinstance(plugin, str) or _PLUGIN_PATTERN.fullmatch(plugin) is None:
            raise BundleManifestError("The QML import scan returned invalid data.")
        imports.add(QmlImport(module, plugin))
    modules = {item.module for item in imports}
    if not _REQUIRED_QML_MODULES.issubset(modules):
        raise BundleManifestError("The QML import inventory is incomplete.")
    return tuple(sorted(imports))


def _validated_version(name: str, value: str) -> str:
    if not isinstance(value, str) or _VERSION_PATTERN.fullmatch(value) is None:
        raise BundleManifestError(f"The {name} version is invalid.")
    return value


def _validated_imports(qml_imports: Sequence[QmlImport]) -> tuple[QmlImport, ...]:
    normalized: set[QmlImport] = set()
    for item in qml_imports:
        if not isinstance(item, QmlImport):
            raise BundleManifestError("The QML import inventory is invalid.")
        if _MODULE_PATTERN.fullmatch(item.module) is None or _PLUGIN_PATTERN.fullmatch(item.plugin) is None:
            raise BundleManifestError("The QML import inventory is invalid.")
        normalized.add(item)
    if not _REQUIRED_QML_MODULES.issubset({item.module for item in normalized}):
        raise BundleManifestError("The QML import inventory is incomplete.")
    return tuple(sorted(normalized))


def _validated_grafiks_reference(reference: Mapping[str, str] | None) -> dict[str, str] | None:
    if reference is None:
        return None
    if set(reference) != _GRAFIKS_REFERENCE_KEYS:
        raise BundleManifestError("The Grafiks manifest reference is invalid.")
    normalized: dict[str, str] = {}
    for key in sorted(_GRAFIKS_REFERENCE_KEYS):
        value = reference.get(key)
        if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
            raise BundleManifestError("The Grafiks manifest reference is invalid.")
        normalized[key] = value.casefold()
    return normalized


def create_bundle_manifest(
    *,
    source_commit: str,
    sgfx_version: str,
    python_version: str,
    pyside6_version: str,
    qt_version: str,
    qml_imports: Sequence[QmlImport],
    grafiks_reference: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    if not isinstance(source_commit, str) or _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise BundleManifestError("The source commit is invalid.")
    imports = _validated_imports(qml_imports)
    grafiks = _validated_grafiks_reference(grafiks_reference)
    modes = ["clean", "qt-quick"]
    if grafiks is not None:
        modes.append("grafiks")
    manifest: dict[str, Any] = {
        "schema_version": BUNDLE_MANIFEST_SCHEMA_VERSION,
        "source_commit": source_commit.casefold(),
        "sgfx_version": _validated_version("SGFX", sgfx_version),
        "python_version": _validated_version("Python", python_version),
        "pyside6_version": _validated_version("PySide6", pyside6_version),
        "qt_version": _validated_version("Qt", qt_version),
        "qml_contract_version": QML_CONTRACT_VERSION,
        "presentation_modes": sorted(modes),
        "qml_imports": [item.as_manifest_entry() for item in imports],
    }
    if grafiks is not None:
        manifest["grafiks"] = grafiks
    return manifest


def source_commit(
    source_root: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> str:
    try:
        completed = runner(
            ["git", "-C", str(Path(source_root).resolve()), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleManifestError("The source commit could not be determined.") from exc
    commit = completed.stdout.strip() if completed.returncode == 0 else ""
    if _COMMIT_PATTERN.fullmatch(commit) is None:
        raise BundleManifestError("The source commit could not be determined.")
    try:
        status = runner(
            [
                "git",
                "-C",
                str(Path(source_root).resolve()),
                "status",
                "--porcelain",
                "--untracked-files=all",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BundleManifestError("The source worktree state could not be verified.") from exc
    if status.returncode != 0 or status.stdout.strip():
        raise BundleManifestError("The source worktree must be clean before packaging.")
    return commit.casefold()


def create_current_bundle_manifest(
    source_root: Path,
    qml_imports: Sequence[QmlImport],
    *,
    grafiks_reference: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    try:
        import PySide6
        from PySide6.QtCore import qVersion

        from sg_preflight import __version__
    except ImportError as exc:
        raise BundleManifestError("The runtime versions could not be determined.") from exc
    return create_bundle_manifest(
        source_commit=source_commit(source_root),
        sgfx_version=__version__,
        python_version=platform.python_version(),
        pyside6_version=PySide6.__version__,
        qt_version=qVersion(),
        qml_imports=qml_imports,
        grafiks_reference=grafiks_reference,
    )


def write_bundle_manifest(bundle_dir: Path, manifest: Mapping[str, Any]) -> Path:
    target = Path(bundle_dir) / BUNDLE_MANIFEST_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n").encode("utf-8")
    temporary = target.with_suffix(".json.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(target)
    return target


def _load_bundle_manifest(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BundleManifestError("The staged bundle manifest is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise BundleManifestError("The staged bundle manifest is invalid.")
    return payload


def _bundle_file_parts(bundle_dir: Path) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(part.casefold() for part in path.parts)
        for path in Path(bundle_dir).rglob("*")
        if path.is_file()
    )


def _has_file_suffix(file_parts: Sequence[tuple[str, ...]], suffix: Sequence[str]) -> bool:
    expected = tuple(part.casefold() for part in suffix)
    for parts in file_parts:
        if len(parts) >= len(expected) and parts[-len(expected) :] == expected:
            return True
    return False


def _module_is_staged(file_parts: Sequence[tuple[str, ...]], module: str) -> bool:
    if module in _BUILTIN_QML_MODULES:
        return True
    if module == "SGFX":
        return _has_file_suffix(file_parts, ("sg_preflight", "desktop", "qml", "SGFX", "qmldir"))
    return _has_file_suffix(file_parts, ("qml", *module.split("."), "qmldir"))


def _plugin_is_staged(
    file_parts: Sequence[tuple[str, ...]],
    module: str,
    plugin: str,
) -> bool:
    if not plugin:
        return True
    module_directory = (
        ("sg_preflight", "desktop", "qml", "SGFX")
        if module == "SGFX"
        else ("qml", *module.split("."))
    )
    candidates = (
        f"{plugin}.dll".casefold(),
        f"lib{plugin}.so".casefold(),
        f"lib{plugin}.dylib".casefold(),
    )
    return any(
        _has_file_suffix(file_parts, (*module_directory, candidate))
        for candidate in candidates
    )


def validate_staged_bundle_contents(bundle_dir: Path, qml_imports: Sequence[QmlImport]) -> None:
    bundle = Path(bundle_dir)
    imports = _validated_imports(qml_imports)
    manifest = _load_bundle_manifest(bundle / BUNDLE_MANIFEST_NAME)
    expected_entries = [item.as_manifest_entry() for item in imports]
    if manifest.get("qml_imports") != expected_entries:
        raise BundleManifestError("The staged bundle QML inventory does not match its manifest.")
    file_parts = _bundle_file_parts(bundle)
    file_names = {parts[-1] for parts in file_parts}
    required_files = {
        "sgfx-preflight.exe",
        "qt6qml.dll",
        "qt6quick.dll",
        "qwindows.dll",
    }
    if not required_files.issubset(file_names):
        raise BundleManifestError("The staged bundle is missing required Qt runtime files.")
    if not _has_file_suffix(file_parts, ("sg_preflight", "desktop", "qml", "Main.qml")):
        raise BundleManifestError("The staged bundle is missing the application QML tree.")
    for item in imports:
        if not _module_is_staged(file_parts, item.module):
            raise BundleManifestError(f"The staged bundle is missing QML module {item.module}.")
        if not _plugin_is_staged(file_parts, item.module, item.plugin):
            raise BundleManifestError(f"The staged bundle is missing QML plugin for {item.module}.")

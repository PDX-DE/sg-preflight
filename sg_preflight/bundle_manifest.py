"""Builds, writes, and validates the Qt desktop bundle manifest: QML import inventory,
runtime/tooling versions, and Ramses preview/probe helper state, checked against the
actual staged bundle contents before packaging."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
_PREVIEW_HELPER_STATES = frozenset({"included", "unavailable"})
PRODUCT_FONT_SHA256 = {
    "Fredoka.ttf": "2ba02e68b152868aef9ba28e24b3648c7d457fe6f25c761f2c2c53fb61a73fc8",
    "Inter.ttf": "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
    "OFL-Fredoka.txt": "c4ae95e05c7ef05a3a749aad4a6a8feba31dcd17bc198f828768366ad7da770b",
    "OFL-Inter.txt": "d7cee39dfa656bffe74385c76debffe635788a83c00ce4370718c99d4c2650ff",
}
CONTROL_CENTER_QML_FILES = (
    "HomePage.qml",
    "QaContextPreview.qml",
    "QaGateDetail.qml",
    "QaPipelineSpine.qml",
)
PREVIEW_RUNTIME_FILES = (
    "SDL3.dll",
    "ramses-shared-lib-headless.dll",
    "ramses-shared-lib-renderer.dll",
    "ramses-shared-lib.dll",
    "sgfx_cine_ramses_preview_cli.exe",
)
PROBE_HELPER_FILE = "sgfx_cine_ramses_probe.exe"
_PROBE_SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
    ramses_preview_helper: str = "unavailable",
    ramses_probe_helper: str = "unavailable",
    ramses_probe_helper_sha256: str = "",
) -> dict[str, Any]:
    if not isinstance(source_commit, str) or _COMMIT_PATTERN.fullmatch(source_commit) is None:
        raise BundleManifestError("The source commit is invalid.")
    imports = _validated_imports(qml_imports)
    grafiks = _validated_grafiks_reference(grafiks_reference)
    if ramses_preview_helper not in _PREVIEW_HELPER_STATES:
        raise BundleManifestError("The Ramses preview helper state is invalid.")
    if ramses_probe_helper not in _PREVIEW_HELPER_STATES:
        raise BundleManifestError("The Ramses probe helper state is invalid.")
    if ramses_probe_helper == "included":
        # The probe helper shares the preview runtime's libraries and cannot ship without them,
        # and its digest is recorded at build time so the runtime can verify what it launches.
        if ramses_preview_helper != "included":
            raise BundleManifestError("The Ramses probe helper requires the preview runtime.")
        if not isinstance(ramses_probe_helper_sha256, str) or \
                _PROBE_SHA256_PATTERN.fullmatch(ramses_probe_helper_sha256) is None:
            raise BundleManifestError("The Ramses probe helper digest is invalid.")
    elif ramses_probe_helper_sha256 != "":
        raise BundleManifestError("The Ramses probe helper digest contradicts its state.")
    from sg_preflight.desktop.ui_capabilities import UI_CAPABILITIES
    from sg_preflight.qa_hub import QA_HUB_SCHEMA_VERSION
    from sg_preflight.surface_registry import SURFACE_DESCRIPTORS

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
        "ui_capability_count": len(UI_CAPABILITIES),
        "surface_descriptor_count": len(SURFACE_DESCRIPTORS),
        "qa_hub_schema_version": QA_HUB_SCHEMA_VERSION,
        "control_center_qml_present": True,
        "product_fonts_licensed": True,
        "ramses_preview_helper": ramses_preview_helper,
        "ramses_probe_helper": ramses_probe_helper,
        "ramses_probe_helper_sha256": ramses_probe_helper_sha256,
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
    ramses_preview_helper: str = "unavailable",
    ramses_probe_helper: str = "unavailable",
    ramses_probe_helper_sha256: str = "",
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
        ramses_preview_helper=ramses_preview_helper,
        ramses_probe_helper=ramses_probe_helper,
        ramses_probe_helper_sha256=ramses_probe_helper_sha256,
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _suffix_files(bundle: Path, suffix: Sequence[str]) -> tuple[Path, ...]:
    expected = tuple(part.casefold() for part in suffix)
    return tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file()
        and len(path.parts) >= len(expected)
        and tuple(part.casefold() for part in path.parts[-len(expected) :]) == expected
    )


def _reject_forbidden_bundle_content(bundle: Path) -> None:
    forbidden_parts = {
        ".git",
        ".svn",
        "digital-3d-car-models",
        "preview-cache",
        "control-center-c0",
    }
    private_markers = (b"c:\\users\\", b"/home/", b"/users/")
    for path in bundle.rglob("*"):
        if not path.is_file():
            continue
        folded_parts = {part.casefold() for part in path.relative_to(bundle).parts}
        folded_name = path.name.casefold()
        if (
            folded_parts & forbidden_parts
            or folded_name.endswith(".ramses")
            or re.fullmatch(r"frame-[0-9]{3}\.png", folded_name)
            or folded_name in {".env", "credentials.json", "id_rsa", "id_ed25519"}
        ):
            raise BundleManifestError("The staged bundle contains forbidden content.")
        if path.suffix.casefold() in {".json", ".md", ".qml", ".txt"} and path.stat().st_size <= 5 * 1024 * 1024:
            try:
                payload = path.read_bytes().lower()
            except OSError as exc:
                raise BundleManifestError("The staged bundle could not be inspected.") from exc
            if any(marker in payload for marker in private_markers):
                raise BundleManifestError("The staged bundle contains a private path string.")


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
    for name in CONTROL_CENTER_QML_FILES:
        if not _has_file_suffix(file_parts, ("sg_preflight", "desktop", "qml", "components", name)):
            raise BundleManifestError("The staged bundle is missing the Control Center QML tree.")
    font_matches = {
        name: _suffix_files(bundle, ("cpp", "assets", "fonts", name))
        for name in PRODUCT_FONT_SHA256
    }
    font_directories = {
        paths[0].parent
        for paths in font_matches.values()
        if len(paths) == 1
    }
    if (
        len(font_directories) != 1
        or {path.name for path in next(iter(font_directories)).iterdir()} != set(PRODUCT_FONT_SHA256)
        or any(not path.is_file() for path in next(iter(font_directories)).iterdir())
    ):
        raise BundleManifestError("The staged bundle product-font evidence is invalid.")
    for name, expected_sha256 in PRODUCT_FONT_SHA256.items():
        matches = font_matches[name]
        if len(matches) != 1 or _sha256_file(matches[0]) != expected_sha256:
            raise BundleManifestError("The staged bundle product-font evidence is invalid.")
    helper_state = manifest.get("ramses_preview_helper")
    if helper_state not in _PREVIEW_HELPER_STATES:
        raise BundleManifestError("The staged bundle preview-helper state is invalid.")
    probe_state = manifest.get("ramses_probe_helper", "unavailable")
    probe_sha256 = manifest.get("ramses_probe_helper_sha256", "")
    if probe_state not in _PREVIEW_HELPER_STATES:
        raise BundleManifestError("The staged bundle probe-helper state is invalid.")
    if probe_state == "included" and helper_state != "included":
        raise BundleManifestError("The staged bundle probe helper lacks its runtime.")
    preview_runtime = tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file()
        and path.parent.name.casefold() == "bin"
        and path.parent.parent.name.casefold() == "cpp"
    )
    expected_runtime = set(PREVIEW_RUNTIME_FILES)
    if probe_state == "included":
        expected_runtime.add(PROBE_HELPER_FILE)
    if helper_state == "included" and (
        len(preview_runtime) != len(expected_runtime)
        or {path.name for path in preview_runtime} != expected_runtime
    ):
        raise BundleManifestError("The staged bundle preview runtime is incomplete.")
    if helper_state == "unavailable" and preview_runtime:
        raise BundleManifestError("The staged bundle preview runtime contradicts its manifest.")
    if probe_state == "included":
        probe_matches = [path for path in preview_runtime if path.name == PROBE_HELPER_FILE]
        if len(probe_matches) != 1 or not isinstance(probe_sha256, str) or \
                _sha256_file(probe_matches[0]) != probe_sha256:
            raise BundleManifestError("The staged bundle probe helper failed its digest.")
    for item in imports:
        if not _module_is_staged(file_parts, item.module):
            raise BundleManifestError(f"The staged bundle is missing QML module {item.module}.")
        if not _plugin_is_staged(file_parts, item.module, item.plugin):
            raise BundleManifestError(f"The staged bundle is missing QML plugin for {item.module}.")
    _reject_forbidden_bundle_content(bundle)

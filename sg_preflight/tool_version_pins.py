from __future__ import annotations

from importlib import metadata
from pathlib import Path
import re
import tomllib
from typing import Any, Iterable, Mapping

from sg_preflight.bmw_delivery import discover_bmw_models_repo


RAMSES_PIPELINE_PIN = "28.16"
RAMSES_PIPELINE_PIN_SOURCE = "bundled Ramses shared-lib path"

_INTERFACE_VERSIONS_RELATIVE = Path("ci") / "scripts" / "common" / "interface_versions.yaml"
_EMBEDDED_RACO_VERSIONS = {"2.3.0": [12], "2.9.0": [23, 24]}
_VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[-+._a-zA-Z0-9]*)?")

try:  # pragma: no cover - exercised implicitly when packaging is present
    from packaging.specifiers import SpecifierSet
    from packaging.version import Version
except Exception:  # pragma: no cover - fallback is tested through public behavior
    SpecifierSet = None  # type: ignore[assignment]
    Version = None  # type: ignore[assignment]


def _version_key(value: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", value))


def _extract_version(value: str) -> str:
    match = _VERSION_RE.search(str(value or ""))
    return match.group(0) if match else ""


def _versions_equal(installed: str, expected: str) -> bool:
    if Version is not None:
        try:
            return Version(installed) == Version(expected)
        except Exception:
            pass
    return _version_key(installed) == _version_key(expected)


def _sort_versions(values: Iterable[str]) -> list[str]:
    return sorted(values, key=_version_key)


def _fallback_pins() -> dict[str, Any]:
    return {
        "versions": dict(_EMBEDDED_RACO_VERSIONS),
        "source": "embedded fallback (interface_versions.yaml not found)",
        "fallback": True,
    }


def _parse_interface_versions_yaml(text: str) -> dict[str, list[int]]:
    versions: dict[str, list[int]] = {}
    current_interface: int | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        interface_match = re.match(r"^(\d+):\s*$", line)
        if interface_match:
            current_interface = int(interface_match.group(1))
            continue
        version_match = re.match(r"^\s*raco_version:\s*['\"]?([^'\"\s#]+)", line)
        if version_match and current_interface is not None:
            version = version_match.group(1).strip()
            versions.setdefault(version, []).append(current_interface)
    return {version: sorted(set(interfaces)) for version, interfaces in versions.items() if interfaces}


def load_raco_pins(bmw_repo_root: Path | str | None = None) -> dict[str, Any]:
    repo_root = Path(bmw_repo_root) if bmw_repo_root is not None else discover_bmw_models_repo()
    pin_file = repo_root / _INTERFACE_VERSIONS_RELATIVE
    try:
        text = pin_file.read_text(encoding="utf-8")
    except OSError:
        return _fallback_pins()
    versions = _parse_interface_versions_yaml(text)
    if not versions:
        return _fallback_pins()
    return {
        "versions": {version: versions[version] for version in _sort_versions(versions)},
        "source": str(pin_file),
        "fallback": False,
    }


def _pin_versions(pins: Mapping[str, Any] | Iterable[str] | None) -> dict[str, list[int]]:
    if pins is None:
        return {}
    if isinstance(pins, Mapping):
        raw_versions = pins.get("versions", pins)
        if isinstance(raw_versions, Mapping):
            normalized: dict[str, list[int]] = {}
            for version, interfaces in raw_versions.items():
                if isinstance(interfaces, Iterable) and not isinstance(interfaces, (str, bytes)):
                    normalized[str(version)] = sorted(int(value) for value in interfaces)
                else:
                    normalized[str(version)] = []
            return normalized
    return {str(version): [] for version in pins}


def recommended_versions_text(pins: Mapping[str, Any] | Iterable[str] | None) -> str:
    return ", ".join(_sort_versions(_pin_versions(pins)))


def _interface_label(interfaces: list[int]) -> str:
    if interfaces == [12]:
        return "IDC23 interface 12"
    if interfaces == [23, 24]:
        return "IDCevo interfaces 23, 24"
    if interfaces:
        joined = ", ".join(str(value) for value in interfaces)
        return f"interfaces {joined}"
    return "documented pin"


def _valid_set_detail(versions: dict[str, list[int]]) -> str:
    return ", ".join(f"{version} ({_interface_label(interfaces)})" for version, interfaces in versions.items())


def compare_version(installed: str, pins: Mapping[str, Any] | Iterable[str] | None) -> tuple[str, str]:
    versions = _pin_versions(pins)
    if not versions:
        return "not_pinned", "No pinned version documented; detected only."
    installed_version = _extract_version(installed)
    if not installed_version:
        return "unknown", "Installed version could not parse from the detected tool output."
    for expected, interfaces in versions.items():
        if _versions_equal(installed_version, expected):
            return "ok", f"Installed {installed_version} matches {_interface_label(interfaces)}."
    valid_set = _valid_set_detail(versions)
    return "drift", f"Installed {installed_version} is outside the documented guidance set: {valid_set}."


def python_requirement() -> tuple[str, str]:
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        specifier = str(data.get("project", {}).get("requires-python", "")).strip()
        if specifier:
            return specifier, "pyproject requires-python"
    except OSError:
        pass
    try:
        specifier = str(metadata.metadata("sg-preflight").get("Requires-Python", "")).strip()
    except metadata.PackageNotFoundError:
        specifier = ""
    return specifier, "installed package metadata requires-python"


def _satisfies_specifier(version: str, specifier: str) -> bool | None:
    if SpecifierSet is not None and Version is not None:
        try:
            return Version(version) in SpecifierSet(specifier)
        except Exception:
            pass
    match = re.match(r"^>=\s*(\d+(?:\.\d+)*)$", specifier.strip())
    if match:
        return _version_key(version) >= _version_key(match.group(1))
    return None


def compare_python_requirement(installed: str, specifier: str) -> tuple[str, str]:
    if not specifier.strip():
        return "not_pinned", "No Python requirement was found; detected only."
    installed_version = _extract_version(installed)
    if not installed_version:
        return "unknown", "Installed Python version could not parse from the detected runtime."
    satisfied = _satisfies_specifier(installed_version, specifier)
    if satisfied is None:
        return (
            "unknown",
            f"Installed Python {installed_version} could not be checked against requires-python "
            f"{specifier} on this machine; detected only.",
        )
    if satisfied:
        return "ok", f"Installed Python {installed_version} satisfies {specifier}."
    return "drift", f"Installed Python {installed_version} is outside pyproject requires-python {specifier}."

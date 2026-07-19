"""Verifies the provenance of a distributed Grafiks binary — hash, license
manifest, dependency inventory — before it is approved for distribution."""

from __future__ import annotations

from dataclasses import dataclass, fields
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any, Mapping


_SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
_WINDOWS_ABSOLUTE_PATTERN = re.compile(r"^[A-Za-z]:/")
_PERMISSIVE_LICENSES = frozenset(
    {
        "0BSD",
        "Apache-2.0",
        "BSD-2-Clause",
        "BSD-3-Clause",
        "BSL-1.0",
        "CC0-1.0",
        "ISC",
        "MIT",
        "Python-2.0",
        "Unlicense",
        "Zlib",
    }
)


class GrafiksProvenanceError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GrafiksProvenance:
    sha256: str
    notice_path: str
    notice_sha256: str
    license_manifest_path: str
    license_manifest_sha256: str
    dependency_inventory_path: str
    dependency_inventory_sha256: str
    permissive_dependencies_verified: bool
    converted_layouts_absent: bool
    protected_fonts_absent: bool
    protected_assets_absent: bool
    derived_shaders_absent: bool
    approved_for_distribution: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json_mapping(path: Path) -> Mapping[str, Any] | None:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, Mapping) else None


def dependency_inventory_is_permissive(path: Path) -> bool:
    payload = _read_json_mapping(path)
    if payload is None:
        return False
    dependencies = payload.get("dependencies")
    if not isinstance(dependencies, list) or not dependencies:
        return False
    for dependency in dependencies:
        if not isinstance(dependency, Mapping):
            return False
        name = dependency.get("name")
        license_id = dependency.get("license")
        if not isinstance(name, str) or not name.strip():
            return False
        if not isinstance(license_id, str) or license_id not in _PERMISSIVE_LICENSES:
            return False
        if dependency.get("redistributable") is not True:
            return False
    return True


def _relative_manifest_path(value: str) -> PurePosixPath | None:
    normalized = value.replace("\\", "/")
    if (
        normalized.startswith("/")
        or _WINDOWS_ABSOLUTE_PATTERN.match(normalized)
        or ":" in normalized
        or any(character in normalized for character in ("\x00", "\r", "\n"))
    ):
        return None
    parsed = PurePosixPath(normalized)
    if parsed.is_absolute() or ".." in parsed.parts or not parsed.parts:
        return None
    return parsed


def _licensed_paths(path: Path) -> set[str] | None:
    payload = _read_json_mapping(path)
    if payload is None:
        return None
    entries = payload.get("entries")
    if not isinstance(entries, list) or not entries:
        return None
    paths: set[str] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            return None
        relative_path = entry.get("path")
        reference = entry.get("license_reference")
        if not isinstance(relative_path, str) or not relative_path.strip():
            return None
        parsed_path = _relative_manifest_path(relative_path)
        if parsed_path is None:
            return None
        if not isinstance(reference, str) or not reference.strip():
            return None
        if entry.get("redistributable") is not True:
            return None
        paths.add(parsed_path.as_posix().casefold())
    return paths


def license_manifest_allows_distribution(path: Path) -> bool:
    return _licensed_paths(path) is not None


def license_manifest_covers_files(path: Path, relative_files: tuple[str, ...]) -> bool:
    licensed = _licensed_paths(path)
    if licensed is None or not relative_files:
        return False
    required: set[str] = set()
    for value in relative_files:
        parsed = _relative_manifest_path(str(value))
        if parsed is None:
            return False
        required.add(parsed.as_posix().casefold())
    return required.issubset(licensed)


def accept_grafiks_bundle(executable: Path, record: GrafiksProvenance | None) -> bool:
    if record is None or not record.approved_for_distribution:
        return False
    if not all(
        (
            record.permissive_dependencies_verified,
            record.converted_layouts_absent,
            record.protected_fonts_absent,
            record.protected_assets_absent,
            record.derived_shaders_absent,
        )
    ):
        return False
    digests = (
        record.sha256,
        record.notice_sha256,
        record.license_manifest_sha256,
        record.dependency_inventory_sha256,
    )
    if any(_SHA256_PATTERN.fullmatch(digest) is None for digest in digests):
        return False
    evidence = (
        (Path(record.notice_path), record.notice_sha256),
        (Path(record.license_manifest_path), record.license_manifest_sha256),
        (Path(record.dependency_inventory_path), record.dependency_inventory_sha256),
    )
    try:
        if any(not path.is_file() or sha256_file(path).casefold() != digest.casefold() for path, digest in evidence):
            return False
        if not dependency_inventory_is_permissive(Path(record.dependency_inventory_path)):
            return False
        if not license_manifest_allows_distribution(Path(record.license_manifest_path)):
            return False
        executable_path = Path(executable)
        return executable_path.is_file() and sha256_file(executable_path).casefold() == record.sha256.casefold()
    except OSError:
        return False


def load_grafiks_provenance(path: Path) -> GrafiksProvenance:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise GrafiksProvenanceError("The Grafiks provenance record is invalid.") from exc
    if not isinstance(payload, Mapping):
        raise GrafiksProvenanceError("The Grafiks provenance record is invalid.")
    field_names = {field.name for field in fields(GrafiksProvenance)}
    if set(payload) != field_names:
        raise GrafiksProvenanceError("The Grafiks provenance record is invalid.")
    string_fields = {
        "sha256",
        "notice_path",
        "notice_sha256",
        "license_manifest_path",
        "license_manifest_sha256",
        "dependency_inventory_path",
        "dependency_inventory_sha256",
    }
    digest_fields = {
        "sha256",
        "notice_sha256",
        "license_manifest_sha256",
        "dependency_inventory_sha256",
    }
    for name in string_fields:
        value = payload.get(name)
        if not isinstance(value, str) or not value.strip():
            raise GrafiksProvenanceError("The Grafiks provenance record is invalid.")
        if name in digest_fields and _SHA256_PATTERN.fullmatch(value) is None:
            raise GrafiksProvenanceError("The Grafiks provenance record is invalid.")
    for name in field_names - string_fields:
        if type(payload.get(name)) is not bool:
            raise GrafiksProvenanceError("The Grafiks provenance record is invalid.")
    return GrafiksProvenance(**{name: payload[name] for name in field_names})


def grafiks_manifest_reference(record: GrafiksProvenance) -> dict[str, str]:
    return {
        "sha256": record.sha256.casefold(),
        "notice_sha256": record.notice_sha256.casefold(),
        "license_manifest_sha256": record.license_manifest_sha256.casefold(),
        "dependency_inventory_sha256": record.dependency_inventory_sha256.casefold(),
    }


def copy_grafiks_provenance_evidence(record: GrafiksProvenance, target_dir: Path) -> tuple[Path, ...]:
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    sources = (
        (Path(record.notice_path), "NOTICE.txt", record.notice_sha256),
        (Path(record.license_manifest_path), "license-manifest.json", record.license_manifest_sha256),
        (
            Path(record.dependency_inventory_path),
            "dependency-inventory.json",
            record.dependency_inventory_sha256,
        ),
    )
    copied: list[Path] = []
    try:
        for source, name, expected_digest in sources:
            destination = target / name
            shutil.copy2(source, destination)
            copied.append(destination)
            if sha256_file(destination).casefold() != expected_digest.casefold():
                raise GrafiksProvenanceError("The copied Grafiks provenance evidence changed.")
    except (OSError, GrafiksProvenanceError):
        for destination in copied:
            try:
                destination.unlink()
            except OSError:
                pass
        raise
    return tuple(copied)

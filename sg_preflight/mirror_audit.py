from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sg_preflight.config_loader import load_json
from sg_preflight.profiles import RunProfile
from sg_preflight.utils import ensure_parent


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    ensure_parent(path)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_index(root: Path) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        payload[relative] = {
            "size": path.stat().st_size,
            "sha256": _hash_file(path),
        }
    return payload


@dataclass
class MirrorAuditEntry:
    label: str
    relative_path: str
    status: str
    kind: str
    mirror_path: str
    reference_path: str
    mirror_file_count: int = 0
    reference_file_count: int = 0
    difference_count: int = 0
    sample_differences: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "relative_path": self.relative_path,
            "status": self.status,
            "kind": self.kind,
            "mirror_path": self.mirror_path,
            "reference_path": self.reference_path,
            "mirror_file_count": self.mirror_file_count,
            "reference_file_count": self.reference_file_count,
            "difference_count": self.difference_count,
            "sample_differences": list(self.sample_differences),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MirrorAuditEntry":
        return cls(
            label=str(payload.get("label", "")),
            relative_path=str(payload.get("relative_path", "")),
            status=str(payload.get("status", "")),
            kind=str(payload.get("kind", "")),
            mirror_path=str(payload.get("mirror_path", "")),
            reference_path=str(payload.get("reference_path", "")),
            mirror_file_count=int(payload.get("mirror_file_count", 0)),
            reference_file_count=int(payload.get("reference_file_count", 0)),
            difference_count=int(payload.get("difference_count", 0)),
            sample_differences=[
                str(item) for item in payload.get("sample_differences", []) if item
            ],
        )


@dataclass
class MirrorAuditReport:
    mode: str
    created_at_utc: str
    mirror_root: str
    reference_root: str
    status: str
    entries: list[MirrorAuditEntry] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "created_at_utc": self.created_at_utc,
            "mirror_root": self.mirror_root,
            "reference_root": self.reference_root,
            "status": self.status,
            "entries": [entry.to_dict() for entry in self.entries],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "MirrorAuditReport":
        return cls(
            mode=str(payload.get("mode", "")),
            created_at_utc=str(payload.get("created_at_utc", "")),
            mirror_root=str(payload.get("mirror_root", "")),
            reference_root=str(payload.get("reference_root", "")),
            status=str(payload.get("status", "")),
            entries=[
                MirrorAuditEntry.from_dict(item)
                for item in payload.get("entries", [])
                if isinstance(item, dict)
            ],
            notes=[str(item) for item in payload.get("notes", []) if item],
        )


def _compare_file(label: str, relative_path: str, mirror_path: Path, reference_path: Path) -> MirrorAuditEntry:
    if not mirror_path.exists() and not reference_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_both",
            kind="file",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in mirror and reference"],
        )
    if not mirror_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_mirror",
            kind="file",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in mirror"],
        )
    if not reference_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_reference",
            kind="file",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in reference"],
        )

    mirror_size = mirror_path.stat().st_size
    reference_size = reference_path.stat().st_size
    if mirror_size == reference_size and _hash_file(mirror_path) == _hash_file(reference_path):
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="match",
            kind="file",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            mirror_file_count=1,
            reference_file_count=1,
        )

    return MirrorAuditEntry(
        label=label,
        relative_path=relative_path,
        status="drift",
        kind="file",
        mirror_path=str(mirror_path),
        reference_path=str(reference_path),
        mirror_file_count=1,
        reference_file_count=1,
        difference_count=1,
        sample_differences=[f"content differs ({mirror_size} vs {reference_size} bytes)"],
    )


def _compare_directory(
    label: str,
    relative_path: str,
    mirror_path: Path,
    reference_path: Path,
) -> MirrorAuditEntry:
    if not mirror_path.exists() and not reference_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_both",
            kind="directory",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in mirror and reference"],
        )
    if not mirror_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_mirror",
            kind="directory",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in mirror"],
        )
    if not reference_path.exists():
        return MirrorAuditEntry(
            label=label,
            relative_path=relative_path,
            status="missing_reference",
            kind="directory",
            mirror_path=str(mirror_path),
            reference_path=str(reference_path),
            difference_count=1,
            sample_differences=["missing in reference"],
        )

    mirror_index = _directory_index(mirror_path)
    reference_index = _directory_index(reference_path)
    differences: list[str] = []
    for path in sorted(set(mirror_index) | set(reference_index)):
        mirror_entry = mirror_index.get(path)
        reference_entry = reference_index.get(path)
        if mirror_entry is None:
            differences.append(f"missing in mirror: {path}")
            continue
        if reference_entry is None:
            differences.append(f"missing in reference: {path}")
            continue
        if mirror_entry["sha256"] != reference_entry["sha256"]:
            differences.append(f"content differs: {path}")

    return MirrorAuditEntry(
        label=label,
        relative_path=relative_path,
        status="match" if not differences else "drift",
        kind="directory",
        mirror_path=str(mirror_path),
        reference_path=str(reference_path),
        mirror_file_count=len(mirror_index),
        reference_file_count=len(reference_index),
        difference_count=len(differences),
        sample_differences=differences[:12],
    )


def compare_relative_path(
    *,
    mirror_root: Path,
    reference_root: Path,
    relative_path: str,
    label: str,
) -> MirrorAuditEntry:
    relative = Path(relative_path)
    mirror_path = mirror_root / relative
    reference_path = reference_root / relative

    if mirror_path.is_dir() or reference_path.is_dir():
        return _compare_directory(label, relative_path, mirror_path, reference_path)
    return _compare_file(label, relative_path, mirror_path, reference_path)


def _overall_status(entries: list[MirrorAuditEntry]) -> str:
    if not entries:
        return "unknown"
    if all(entry.status == "match" for entry in entries):
        return "match"
    return "drift"


def run_fast_mirror_audit(profiles: list[RunProfile]) -> MirrorAuditReport:
    entries: list[MirrorAuditEntry] = []
    notes: list[str] = []
    if not profiles:
        return MirrorAuditReport(
            mode="fast",
            created_at_utc=_utc_now(),
            mirror_root="",
            reference_root="",
            status="unknown",
            notes=["No profiles were provided."],
        )

    mirror_root = profiles[0].repo_root
    reference_root = profiles[0].reference_repo_root
    for profile in profiles:
        seen: set[str] = set()
        for relative_path in profile.mirror_audit_targets:
            if relative_path in seen:
                continue
            seen.add(relative_path)
            entries.append(
                compare_relative_path(
                    mirror_root=profile.repo_root,
                    reference_root=profile.reference_repo_root,
                    relative_path=relative_path,
                    label=f"{profile.profile_id}: {relative_path}",
                )
            )
        notes.append(f"{profile.profile_id}: compared {len(seen)} configured live targets")

    return MirrorAuditReport(
        mode="fast",
        created_at_utc=_utc_now(),
        mirror_root=str(mirror_root),
        reference_root=str(reference_root),
        status=_overall_status(entries),
        entries=entries,
        notes=notes,
    )


def run_deep_mirror_audit(mirror_root: Path, reference_root: Path) -> MirrorAuditReport:
    entry = _compare_directory("Full trunk", ".", mirror_root, reference_root)
    notes = []
    if entry.sample_differences:
        playground_only = all(
            item.lower().replace("missing in reference: ", "").startswith("playground/racoscenemerging_poc/")
            or item.lower().replace("missing in mirror: ", "").startswith("playground/racoscenemerging_poc/")
            or item.lower().replace("content differs: ", "").startswith("playground/racoscenemerging_poc/")
            for item in entry.sample_differences
        )
        if playground_only:
            notes.append("Observed differences are currently limited to Playground/RaCoSceneMerging_PoC in the sampled output.")

    return MirrorAuditReport(
        mode="deep",
        created_at_utc=_utc_now(),
        mirror_root=str(mirror_root),
        reference_root=str(reference_root),
        status=_overall_status([entry]),
        entries=[entry],
        notes=notes,
    )


def load_cached_audit(cache_path: Path) -> MirrorAuditReport | None:
    if not cache_path.exists():
        return None
    payload = load_json(cache_path)
    if not isinstance(payload, dict):
        return None
    return MirrorAuditReport.from_dict(payload)


def save_cached_audit(cache_path: Path, report: MirrorAuditReport) -> None:
    _write_json(cache_path, report.to_dict())

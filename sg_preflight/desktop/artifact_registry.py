from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import secrets
from typing import Callable, Iterable, Mapping


_ALLOWED_SUFFIXES_BY_TYPE = {
    "json": frozenset({".json"}),
    "markdown": frozenset({".md"}),
    "workbook": frozenset({".xlsx"}),
}
_PAGE_PATH_FIELDS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "full-qa-pass": (
        ("summary_json", "json", "Full QA summary"),
        ("summary_md", "markdown", "Full QA report"),
    ),
    "batch-full-qa-pass": (("summary_md", "markdown", "Batch QA report"),),
    "delivery-checklist": (("workbook_path", "workbook", "Delivery workbook"),),
    "disabled-tests": (("report_path", "markdown", "Disabled-tests report"),),
    "api-version-coverage": (("report_path", "json", "API coverage report"),),
    "country-variant-coverage": (("report_path", "json", "Country coverage report"),),
    "export-size-trend": (("workbook_path", "workbook", "Export-size workbook"),),
    "screenshot-test-state": (
        ("expected_root", "directory", "Expected screenshots"),
        ("actuals_root", "directory", "Actual screenshots"),
        ("diff_root", "directory", "Diff screenshots"),
    ),
    "risk-score": (("report_path", "json", "Risk-score report"),),
    "daily-digest": (("report_path", "markdown", "Daily digest"),),
    "team-digest-board": (("report_path", "markdown", "Team digest"),),
    "manual-review": (("markdown_path", "markdown", "Manual-review report"),),
}


@dataclass(frozen=True, slots=True)
class ArtifactIdentity:
    generation: int
    profile_id: str
    page_id: str


@dataclass(frozen=True, slots=True)
class ArtifactCandidate:
    target: Path
    approved_root: Path
    artifact_type: str
    label: str


@dataclass(frozen=True, slots=True)
class _ArtifactRecord:
    artifact_id: str
    identity: ArtifactIdentity
    target: Path
    approved_root: Path
    artifact_type: str
    label: str


def _default_revealer(path: Path) -> None:
    startfile = getattr(os, "startfile", None)
    if startfile is None:
        raise OSError("Artifact reveal is unavailable on this platform.")
    startfile(str(path))


def _is_reparse_or_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if isjunction is not None and isjunction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return True
    reparse_flag = int(getattr(__import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse_flag)


def _contained(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
    except ValueError:
        return False
    return True


def _path_chain_is_plain(target: Path, root: Path) -> bool:
    current = target
    while True:
        if _is_reparse_or_link(current):
            return False
        try:
            if current == root or os.path.samefile(current, root):
                return True
        except OSError:
            pass
        if current.parent == current:
            return False
        current = current.parent


class ArtifactRegistry:
    def __init__(
        self,
        *,
        approved_roots: Iterable[Path],
        revealer: Callable[[Path], None] = _default_revealer,
    ) -> None:
        root_sources = tuple(
            (Path(os.path.abspath(Path(root))), Path(root).resolve())
            for root in approved_roots
        )
        self._approved_root_sources = root_sources
        self._approved_roots = tuple(dict.fromkeys(resolved for _source, resolved in root_sources))
        self._revealer = revealer
        self._records: dict[str, _ArtifactRecord] = {}

    @property
    def count(self) -> int:
        return len(self._records)

    def clear(self) -> None:
        self._records.clear()

    def _validated_candidate(self, candidate: ArtifactCandidate) -> tuple[Path, Path] | None:
        raw_declared_root = Path(candidate.approved_root)
        raw_target = Path(candidate.target)
        if not raw_declared_root.is_absolute() or not raw_target.is_absolute():
            return None
        declared_root = raw_declared_root.resolve()
        if declared_root not in self._approved_roots or not declared_root.is_dir():
            return None
        matching_sources = tuple(
            source
            for source, resolved in self._approved_root_sources
            if resolved == declared_root
        )
        if not any(
            source.is_dir()
            and source.resolve() == declared_root
            and not _is_reparse_or_link(source)
            for source in matching_sources
        ):
            return None
        if any(":" in part for part in raw_target.parts[1:]):
            return None
        if not _path_chain_is_plain(raw_target, declared_root):
            return None
        try:
            target = raw_target.resolve(strict=True)
        except (OSError, RuntimeError):
            return None
        if not _contained(target, declared_root):
            return None
        if not _path_chain_is_plain(target, declared_root):
            return None
        if target.is_dir():
            if candidate.artifact_type != "directory":
                return None
        else:
            allowed_suffixes = _ALLOWED_SUFFIXES_BY_TYPE.get(candidate.artifact_type)
            if (
                not target.is_file()
                or allowed_suffixes is None
                or target.suffix.casefold() not in allowed_suffixes
            ):
                return None
        label = " ".join(str(candidate.label or "").split())
        if not label or len(label) > 160 or any(ord(character) < 32 for character in label):
            return None
        return target, declared_root

    def accept(
        self,
        identity: ArtifactIdentity,
        candidates: Iterable[ArtifactCandidate],
    ) -> list[dict[str, str]]:
        self.clear()
        public: list[dict[str, str]] = []
        for candidate in candidates:
            validated = self._validated_candidate(candidate)
            if validated is None:
                continue
            target, approved_root = validated
            artifact_id = f"artifact_{secrets.token_hex(16)}"
            record = _ArtifactRecord(
                artifact_id,
                identity,
                target,
                approved_root,
                str(candidate.artifact_type),
                " ".join(str(candidate.label).split()),
            )
            self._records[artifact_id] = record
            public.append(
                {
                    "artifactId": artifact_id,
                    "label": record.label,
                    "type": record.artifact_type,
                }
            )
        return public

    def reveal(self, artifact_id: str, identity: ArtifactIdentity) -> bool:
        record = self._records.get(str(artifact_id))
        if record is None or record.identity != identity:
            return False
        validated = self._validated_candidate(
            ArtifactCandidate(
                record.target,
                record.approved_root,
                record.artifact_type,
                record.label,
            )
        )
        if validated is None:
            return False
        target, _root = validated
        try:
            self._revealer(target)
        except OSError:
            return False
        return True


def _candidate_root(target: Path, roots: tuple[Path, ...]) -> Path | None:
    try:
        resolved = target.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    for root in roots:
        resolved_root = root.resolve()
        if _contained(resolved, resolved_root):
            return resolved_root
    return None


def extract_artifact_candidates(
    page_id: str,
    raw_page: Mapping[str, object],
    *,
    approved_roots: Iterable[Path],
) -> tuple[ArtifactCandidate, ...]:
    fields = _PAGE_PATH_FIELDS.get(page_id, ())
    if not fields:
        return ()
    payload = raw_page.get("payload", {})
    if not isinstance(payload, Mapping):
        return ()
    roots = tuple(Path(root).resolve() for root in approved_roots)
    candidates: list[ArtifactCandidate] = []
    for field, artifact_type, label in fields:
        value = str(payload.get(field, "") or "").strip()
        if not value:
            continue
        target = Path(value)
        root = _candidate_root(target, roots)
        if root is None:
            continue
        candidates.append(ArtifactCandidate(target, root, artifact_type, label))
    return tuple(candidates)

"""H-27 size-analysis workbook discovery.

Searches the documented Format A (date-stamped IDC_EVO) and Format B
(version-tagged IDC_23) workbook locations across SVN trunk + BMW Git
worktrees. Returns the newest match plus all candidates so the delivery
checklist surface can cite the resolved path verbatim.

Search precedence (per Lexus 2026-05-29 07:20 directive, eight locations):

1. `<workspace>/Cars/size_analysis/<PROFILE>_*.xlsx` (Format A, date-stamped IDC_EVO)
2. `<workspace>/Cars/size_analysis/<PROFILE>_v*.xlsx` (Format B, version-tagged IDC_23)
3. `<workspace>/Cars_IDCevo/BMW/<PROFILE>/size_analysis/*.xlsx`
4. `<workspace>/Cars/BMW/<PROFILE>/size_analysis/*.xlsx`
5. `<bmw_root>/cars/BMW/<PROFILE>_EVO/export/size_analysis/*.xlsx`
6. `<bmw_root>/cars/BMW/<PROFILE>/export/size_analysis/*.xlsx`
7. `<bmw_root>/cars/BMW/<PROFILE>_EVO/export/size-analysis/*.xlsx` (variant spelling)
8. `<workspace>/Cars/BMW/<PROFILE>/export/size_analysis/*.xlsx` (IDC_23 worktree variant)

`<workspace>` and `<bmw_root>` are operator-local paths; the finder reads
filesystem metadata only (mtime + size). BMW Git access is read-only per
`[[feedback-grade-production-alignment]]`.

If no Format A or B workbook exists AND raw export-size data is available
locally, the companion `workbook_generator.auto_generate_if_raw_available`
function produces a `~/sgfx_outputs/<profile>/delivery-workbook/<PROFILE>_auto_<YYYYMMDD>.xlsx`
that this finder will then prefer on subsequent calls (Format A shape,
classified `auto_generated_locally` rather than `from_ci`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

# Honest classification per `[[phase-j-automated-verdict-trajectory]]`.
SOURCE_FROM_CI = "from_ci"
SOURCE_AUTO_GENERATED_LOCALLY = "auto_generated_locally"
SOURCE_UNKNOWN = "unknown"

WORKBOOK_FORMAT_A_DATE_STAMPED = "format_a_date_stamped"
WORKBOOK_FORMAT_B_VERSION_TAGGED = "format_b_version_tagged"
WORKBOOK_FORMAT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class WorkbookCandidate:
    """One workbook resolved from one of the search locations."""

    path: Path
    mtime_ns: int
    size_bytes: int
    source_key: str  # which of the 8 search slots produced this candidate
    source_classification: str  # SOURCE_FROM_CI / SOURCE_AUTO_GENERATED_LOCALLY
    workbook_format: str  # WORKBOOK_FORMAT_A_DATE_STAMPED / _B_VERSION_TAGGED / _UNKNOWN

    @property
    def mtime_iso(self) -> str:
        try:
            return datetime.fromtimestamp(self.mtime_ns / 1_000_000_000, tz=timezone.utc).isoformat(
                timespec="seconds"
            )
        except (OSError, ValueError):
            return ""


@dataclass(frozen=True)
class WorkbookResolution:
    profile_id: str
    candidates: tuple[WorkbookCandidate, ...] = ()
    selected: WorkbookCandidate | None = None
    search_paths: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        return "available" if self.selected is not None else "unavailable"

    def to_payload(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "status": self.status,
            "selected": (
                {
                    "path": str(self.selected.path),
                    "source_key": self.selected.source_key,
                    "source_classification": self.selected.source_classification,
                    "workbook_format": self.selected.workbook_format,
                    "mtime_iso": self.selected.mtime_iso,
                    "size_bytes": self.selected.size_bytes,
                }
                if self.selected is not None
                else None
            ),
            "candidates": [
                {
                    "path": str(c.path),
                    "source_key": c.source_key,
                    "source_classification": c.source_classification,
                    "workbook_format": c.workbook_format,
                    "mtime_iso": c.mtime_iso,
                    "size_bytes": c.size_bytes,
                }
                for c in self.candidates
            ],
            "search_paths": list(self.search_paths),
            "candidate_count": len(self.candidates),
            "note": (
                "Read-only multi-location workbook discovery. Operator-local search; "
                "BMW Git access is read-only. SGFX never modifies BMW source."
            ),
        }


def _candidate_profile_ids(profile_id: str) -> tuple[str, ...]:
    """Build the ordered list of profile-id variants to try (e.g., G70 + G70_EVO)."""
    raw = (profile_id or "").strip()
    if not raw:
        return ()
    normalized = raw.upper()
    candidates: list[str] = [normalized]
    if not normalized.endswith("_EVO"):
        candidates.append(f"{normalized}_EVO")
    if normalized.endswith("_EVO"):
        stripped = normalized[:-4]
        if stripped:
            candidates.append(stripped)
    # De-dup while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        ordered.append(candidate)
    return tuple(ordered)


def _safe_resolve(path: Path | str | None) -> Path | None:
    if path is None:
        return None
    text = str(path).strip()
    if not text:
        return None
    return Path(text).resolve()


def _format_hint(path: Path) -> str:
    """Detect workbook format from filename per WORKBOOK_SCHEMA_AUDIT.md (filename
    is a hint only; the reader should sniff content for authoritative detection)."""
    stem = path.stem
    suffix_match = re.search(r"_([^_]+)$", stem)
    if not suffix_match:
        return WORKBOOK_FORMAT_UNKNOWN
    suffix = suffix_match.group(1)
    if re.fullmatch(r"\d{8}", suffix):
        return WORKBOOK_FORMAT_A_DATE_STAMPED
    if re.fullmatch(r"v\d+|vx", suffix.casefold()):
        return WORKBOOK_FORMAT_B_VERSION_TAGGED
    if suffix.lower().startswith("auto"):
        # Auto-generated workbooks always use Format A shape per H-27 spec.
        return WORKBOOK_FORMAT_A_DATE_STAMPED
    return WORKBOOK_FORMAT_UNKNOWN


def _stat_workbook(path: Path) -> tuple[int, int] | None:
    """Return (mtime_ns, size_bytes) or None if not a readable file."""
    try:
        stat = path.stat()
    except OSError:
        return None
    if not path.is_file():
        return None
    return (int(stat.st_mtime_ns), int(stat.st_size))


def _glob_workbooks(directory: Path, glob_pattern: str) -> Iterable[Path]:
    if not directory.exists() or not directory.is_dir():
        return ()
    try:
        return tuple(directory.glob(glob_pattern))
    except OSError:
        return ()


def _classification_for_path(path: Path) -> str:
    """Classify a discovered workbook by where it lives — auto-generated lives in
    `~/sgfx_outputs/<profile>/delivery-workbook/`; everything else is `from_ci`."""
    parts = [part.lower() for part in path.parts]
    if "sgfx_outputs" in parts and "delivery-workbook" in parts:
        return SOURCE_AUTO_GENERATED_LOCALLY
    # Heuristic: filename containing `_auto_<digits>` also indicates an auto-gen.
    if re.search(r"_auto_\d{6,8}\b", path.stem, re.IGNORECASE):
        return SOURCE_AUTO_GENERATED_LOCALLY
    return SOURCE_FROM_CI


def _build_search_locations(
    profile_id: str,
    *,
    workspace: Path | None,
    bmw_root: Path | None,
) -> tuple[tuple[str, Path, str], ...]:
    """Return the directive-locked ordered list of (source_key, directory, glob) tuples."""
    ws = workspace
    br = bmw_root
    locations: list[tuple[str, Path, str]] = []
    if ws is not None:
        for profile in _candidate_profile_ids(profile_id):
            # Slots 1 + 2 share the same directory but different glob patterns.
            locations.append(("svn_size_analysis_date_stamped", ws / "Cars" / "size_analysis", f"{profile}_*.xlsx"))
            locations.append(("svn_size_analysis_version_tagged", ws / "Cars" / "size_analysis", f"{profile}_v*.xlsx"))
            locations.append(("svn_idcevo_size_analysis", ws / "Cars_IDCevo" / "BMW" / profile / "size_analysis", "*.xlsx"))
            locations.append(("svn_cars_bmw_size_analysis", ws / "Cars" / "BMW" / profile / "size_analysis", "*.xlsx"))
            locations.append(("svn_idc23_export_size_analysis", ws / "Cars" / "BMW" / profile / "export" / "size_analysis", "*.xlsx"))
    if br is not None:
        for profile in _candidate_profile_ids(profile_id):
            # Per directive: <bmw_root>/cars/BMW/<PROFILE>_EVO/export/size_analysis/*.xlsx
            # Skip the `_EVO` suffix when the profile name already carries it so we
            # do not generate spurious `G70_EVO_EVO` paths.
            evo_profile = profile if profile.endswith("_EVO") else f"{profile}_EVO"
            locations.append(("bmw_git_evo_size_analysis", br / "cars" / "BMW" / evo_profile / "export" / "size_analysis", "*.xlsx"))
            locations.append(("bmw_git_export_size_analysis", br / "cars" / "BMW" / profile / "export" / "size_analysis", "*.xlsx"))
            locations.append(("bmw_git_evo_size_analysis_dash", br / "cars" / "BMW" / evo_profile / "export" / "size-analysis", "*.xlsx"))
    # Also include the operator-local auto-gen output dir so freshly auto-generated
    # workbooks are picked up on the next finder call without restarting the dashboard.
    home = _safe_resolve(Path.home())
    if home is not None:
        for profile in _candidate_profile_ids(profile_id):
            locations.append((
                "operator_local_auto_gen",
                home / "sgfx_outputs" / profile.lower() / "delivery-workbook",
                f"{profile}_auto_*.xlsx",
            ))
    return tuple(locations)


def find_workbook_candidates(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> tuple[WorkbookCandidate, ...]:
    """Walk all eight directive locations + the operator-local auto-gen dir.

    Returns a tuple of every candidate found, in arbitrary order. Use
    `resolve_workbook` for the newest-mtime-wins selection.
    """
    profile = (profile_id or "").strip().upper()
    if not profile:
        return ()
    locations = _build_search_locations(
        profile,
        workspace=_safe_resolve(workspace),
        bmw_root=_safe_resolve(bmw_root),
    )
    seen: dict[Path, WorkbookCandidate] = {}
    for source_key, directory, glob_pattern in locations:
        for path in _glob_workbooks(directory, glob_pattern):
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if resolved in seen:
                continue
            metadata = _stat_workbook(resolved)
            if metadata is None:
                continue
            mtime_ns, size_bytes = metadata
            classification = _classification_for_path(resolved)
            workbook_format = _format_hint(resolved)
            seen[resolved] = WorkbookCandidate(
                path=resolved,
                mtime_ns=mtime_ns,
                size_bytes=size_bytes,
                source_key=source_key,
                source_classification=classification,
                workbook_format=workbook_format,
            )
    return tuple(seen.values())


def resolve_workbook(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
) -> WorkbookResolution:
    """Newest-mtime-wins resolution across all eight directive locations.

    Returns the selected candidate + the full candidate list + the search paths
    that were actually walked so the delivery-checklist surface can cite them
    verbatim. The classification field distinguishes CI-produced workbooks from
    SGFX-generated ones; never silently collapses to `passed` per `[[phase-j-automated-verdict-trajectory]]`.
    """
    profile = (profile_id or "").strip().upper()
    candidates = find_workbook_candidates(
        profile,
        workspace=workspace,
        bmw_root=bmw_root,
    )
    locations = _build_search_locations(
        profile,
        workspace=_safe_resolve(workspace),
        bmw_root=_safe_resolve(bmw_root),
    )
    search_paths = tuple(str(directory / glob_pattern) for _key, directory, glob_pattern in locations)
    if not candidates:
        return WorkbookResolution(profile_id=profile, candidates=(), selected=None, search_paths=search_paths)
    # Newest mtime wins; tie-break by lexicographic path so the choice is deterministic.
    selected = max(candidates, key=lambda c: (c.mtime_ns, str(c.path).casefold()))
    return WorkbookResolution(
        profile_id=profile,
        candidates=candidates,
        selected=selected,
        search_paths=search_paths,
    )


def render_resolution_text(resolution: WorkbookResolution) -> str:
    if resolution.selected is None:
        lines = [
            f"profile:      {resolution.profile_id or '(unknown)'}",
            "status:       unavailable",
            f"candidates:   0 (searched {len(resolution.search_paths)} locations)",
            "note:         No size-analysis workbook found in any documented location.",
        ]
        return "\n".join(lines)
    selected = resolution.selected
    lines = [
        f"profile:                {resolution.profile_id}",
        "status:                 available",
        f"workbook_path:          {selected.path}",
        f"workbook_format:        {selected.workbook_format}",
        f"source_classification:  {selected.source_classification}",
        f"source_key:             {selected.source_key}",
        f"mtime_iso:              {selected.mtime_iso}",
        f"size_bytes:             {selected.size_bytes}",
        f"candidate_count:        {len(resolution.candidates)}",
    ]
    return "\n".join(lines)

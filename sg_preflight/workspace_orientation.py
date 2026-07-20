"""Reports whether a candidate location contains the SG workspace markers used by operator paths."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _has_sg_markers(candidate: Path) -> bool:
    return (
        candidate.is_dir()
        and (candidate / ".pdx").is_dir()
        and any((candidate / name).is_dir() for name in ("Cars", "Cars_IDCevo"))
    )


def describe_sg_workspace(workspace: Path | str) -> dict[str, Any]:
    candidate = Path(workspace).resolve()
    candidate_label = candidate.name or "Local workspace"
    roots = (candidate, candidate / "repositories" / "trunk")
    resolved = next((root for root in roots if _has_sg_markers(root)), None)
    if resolved is None:
        return {
            "status": "unresolved",
            "resolved": False,
            "display_label": "Unresolved",
            "candidate_label": candidate_label,
            "summary": "No SG workspace markers were found in the selected location.",
        }
    return {
        "status": "resolved",
        "resolved": True,
        "display_label": candidate_label,
        "candidate_label": candidate_label,
        "summary": "SG workspace markers are available.",
    }

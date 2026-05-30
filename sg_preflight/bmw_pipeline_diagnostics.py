from __future__ import annotations

from importlib import resources
import json
from typing import Any


DIAGNOSTICS_DATA_PACKAGE = "sg_preflight.data"
DIAGNOSTICS_DATA_FILE = "bmw_pipeline_diagnostics.json"


def load_bmw_pipeline_diagnostics() -> dict[str, Any]:
    try:
        path = resources.files(DIAGNOSTICS_DATA_PACKAGE).joinpath(DIAGNOSTICS_DATA_FILE)
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ModuleNotFoundError, json.JSONDecodeError, OSError):
        return {"schema_version": "1.0", "patterns": []}
    return payload if isinstance(payload, dict) else {"schema_version": "1.0", "patterns": []}


def bmw_pipeline_diagnostic_patterns() -> tuple[dict[str, Any], ...]:
    payload = load_bmw_pipeline_diagnostics()
    patterns = payload.get("patterns", [])
    if not isinstance(patterns, list):
        return ()
    return tuple(pattern for pattern in patterns if isinstance(pattern, dict))


def bmw_pipeline_diagnostic_pattern(pattern_id: str) -> dict[str, Any] | None:
    needle = str(pattern_id or "").strip()
    if not needle:
        return None
    for pattern in bmw_pipeline_diagnostic_patterns():
        if str(pattern.get("pattern_id", "")).strip() == needle:
            return pattern
    return None


def diagnostic_pattern_anchors(*pattern_ids: str) -> tuple[str, ...]:
    anchors: list[str] = []
    for pattern_id in pattern_ids:
        pattern = bmw_pipeline_diagnostic_pattern(pattern_id)
        if not pattern:
            continue
        candidates: list[str] = []
        anchor = str(pattern.get("confluence_anchor", "")).strip()
        if anchor:
            candidates.append(anchor)
        causes = pattern.get("possible_causes_honest_disjunction", [])
        if isinstance(causes, list):
            for cause in causes:
                if isinstance(cause, dict):
                    candidate = str(cause.get("confluence_anchor", "")).strip()
                    if candidate:
                        candidates.append(candidate)
        for candidate in candidates:
            if candidate not in anchors:
                anchors.append(candidate)
    return tuple(anchors)

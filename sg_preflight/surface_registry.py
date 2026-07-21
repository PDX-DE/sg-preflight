"""Static registry of operator-dashboard surfaces (id, titles, navigation grouping, renderer kind), validated at import time."""

from __future__ import annotations

from dataclasses import dataclass


RENDERER_KINDS = frozenset({"overview", "matrix", "evidence", "workflow", "review", "about"})


@dataclass(frozen=True, slots=True)
class SurfaceDescriptor:
    surface_id: str
    title: str
    subtitle: str
    navigation_group: str
    renderer_kind: str
    operational: bool = True


SURFACE_DESCRIPTORS = (
    SurfaceDescriptor(
        "full-qa-pass",
        "Selected-Car Checks",
        "Run audited local checks and review evidence for the selected car.",
        "Current Session",
        "workflow",
    ),
    SurfaceDescriptor(
        "manual-review",
        "Manual Review Companion",
        "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        "Manual Review",
        "review",
    ),
    SurfaceDescriptor(
        "screenshot-test-state",
        "Screenshot Test State",
        "BMW + MINI baseline / actual / diff counts per brand.",
        "Manual Review",
        "matrix",
    ),
    SurfaceDescriptor(
        "country-variant-coverage",
        "Country Variants",
        "Country-coding test matrix with expected, actual, and diff evidence slots.",
        "Manual Review",
        "matrix",
    ),
    SurfaceDescriptor(
        "delivery-checklist",
        "Delivery documentation",
        "Read-only delivery workbook evidence for the selected profile.",
        "Evidence",
        "evidence",
    ),
    SurfaceDescriptor(
        "disabled-tests",
        "Disabled Tests",
        "Per-car disabled-test inventory from local test_config.lua files.",
        "Evidence",
        "matrix",
    ),
    SurfaceDescriptor(
        "api-version-coverage",
        "API Version",
        "Shared MainInterfaces API reference with cautious impact hints.",
        "Evidence",
        "matrix",
    ),
    SurfaceDescriptor(
        "export-size-trend",
        "Size Trend",
        "Export-size workbook trends from local size_analysis evidence.",
        "Evidence",
        "evidence",
    ),
    SurfaceDescriptor(
        "operator-handoff",
        "Operator Handoff",
        "Record the stopping point before a shift handoff.",
        "Evidence",
        "workflow",
    ),
    SurfaceDescriptor(
        "batch-full-qa-pass",
        "Batch QA Evidence",
        "Review existing sequential-run evidence across car profiles.",
        "History",
        "workflow",
    ),
    SurfaceDescriptor(
        "cross-car-comparison",
        "Comparison Evidence",
        "Read comparison evidence when a car-profile pair is available.",
        "History",
        "matrix",
    ),
    SurfaceDescriptor(
        "daily-digest",
        "Daily Digest",
        "Morning status snapshot for the SG Daily standup.",
        "History",
        "overview",
    ),
    SurfaceDescriptor(
        "team-digest-board",
        "Team Digest Board",
        "Local snapshot for standup review across selected car profiles.",
        "History",
        "overview",
    ),
    SurfaceDescriptor(
        "setup-doctor",
        "Setup Doctor",
        "Detect-only setup status for local SGFX dependencies.",
        "Tools",
        "overview",
    ),
    SurfaceDescriptor(
        "onboarding-guide",
        "Onboarding Guide",
        "New-operator path through setup, evidence pages, manual review, and handoff.",
        "Tools",
        "workflow",
    ),
    SurfaceDescriptor(
        "qa-workflows",
        "QA Workflows",
        "Local JSON workflow catalog with manual-attestation gates preserved.",
        "Tools",
        "workflow",
    ),
    SurfaceDescriptor(
        "bmw-process",
        "BMW Process",
        "Read-only workflow contracts for BMW interface, triage, and visual review paths.",
        "Tools",
        "workflow",
    ),
    SurfaceDescriptor(
        "risk-score",
        "Risk Score",
        "Per-car review focus signal with delta since latest local manual review.",
        "Tools",
        "evidence",
    ),
    SurfaceDescriptor(
        "about",
        "About",
        "Local SGFX preflight scope, evidence sources, and data-handling guardrails.",
        "Tools",
        "about",
        False,
    ),
)

_SURFACE_BY_ID = {item.surface_id: item for item in SURFACE_DESCRIPTORS}

if len(_SURFACE_BY_ID) != len(SURFACE_DESCRIPTORS):
    raise RuntimeError("Surface registry contains duplicate IDs.")
if any(item.renderer_kind not in RENDERER_KINDS for item in SURFACE_DESCRIPTORS):
    raise RuntimeError("Surface registry contains an unsupported renderer kind.")
if any(not item.subtitle.strip() or "\n" in item.subtitle or "\r" in item.subtitle for item in SURFACE_DESCRIPTORS):
    raise RuntimeError("Surface registry subtitles must be non-empty logical lines.")


def get_surface_descriptor(surface_id: str) -> SurfaceDescriptor:
    return _SURFACE_BY_ID[surface_id]


def is_registered_surface(surface_id: str) -> bool:
    return surface_id in _SURFACE_BY_ID

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
        "Full QA Pass",
        "One local pass through setup, evidence, review assist, and handoff status.",
        "Daily work",
        "workflow",
    ),
    SurfaceDescriptor(
        "batch-full-qa-pass",
        "Batch Full QA Pass",
        "Run selected profiles sequentially; one profile finishes before the next starts.",
        "Daily work",
        "workflow",
    ),
    SurfaceDescriptor(
        "delivery-checklist",
        "Delivery documentation",
        "Read-only delivery workbook evidence for the selected profile.",
        "Delivery",
        "evidence",
    ),
    SurfaceDescriptor(
        "disabled-tests",
        "Disabled Tests",
        "Per-car disabled-test inventory from local test_config.lua files.",
        "Screenshots & coverage",
        "matrix",
    ),
    SurfaceDescriptor(
        "api-version-coverage",
        "API Version",
        "Shared MainInterfaces API reference with cautious impact hints.",
        "Screenshots & coverage",
        "matrix",
    ),
    SurfaceDescriptor(
        "country-variant-coverage",
        "Country Variants",
        "Country-coding test matrix with expected, actual, and diff evidence slots.",
        "Screenshots & coverage",
        "matrix",
    ),
    SurfaceDescriptor(
        "export-size-trend",
        "Size Trend",
        "Export-size workbook trends from local size_analysis evidence.",
        "Screenshots & coverage",
        "evidence",
    ),
    SurfaceDescriptor(
        "onboarding-guide",
        "Onboarding Guide",
        "New-operator path through setup, evidence pages, manual review, and handoff.",
        "Setup & help",
        "workflow",
    ),
    SurfaceDescriptor(
        "setup-doctor",
        "Setup Doctor",
        "Detect-only setup status for local SGFX dependencies.",
        "Setup & help",
        "overview",
    ),
    SurfaceDescriptor(
        "qa-workflows",
        "QA Workflows",
        "Local JSON workflow catalog with manual-attestation gates preserved.",
        "Setup & help",
        "workflow",
    ),
    SurfaceDescriptor(
        "bmw-process",
        "BMW Process",
        "Read-only workflow contracts for BMW interface, triage, and visual review paths.",
        "Setup & help",
        "workflow",
    ),
    SurfaceDescriptor(
        "screenshot-test-state",
        "Screenshot Test State",
        "BMW + MINI baseline / actual / diff counts per brand.",
        "Screenshots & coverage",
        "matrix",
    ),
    SurfaceDescriptor(
        "risk-score",
        "Risk Score",
        "Per-car review focus signal with delta since latest local manual review.",
        "Screenshots & coverage",
        "evidence",
    ),
    SurfaceDescriptor(
        "cross-car-comparison",
        "Cross-Car Comparison",
        "Choose two profiles to compare their risk-score evidence side by side.",
        "Screenshots & coverage",
        "matrix",
    ),
    SurfaceDescriptor(
        "daily-digest",
        "Daily Digest",
        "Morning status snapshot for the SG Daily standup.",
        "Reviews & digests",
        "overview",
    ),
    SurfaceDescriptor(
        "team-digest-board",
        "Team Digest Board",
        "Local snapshot for standup review across selected car profiles.",
        "Reviews & digests",
        "overview",
    ),
    SurfaceDescriptor(
        "operator-handoff",
        "Operator Handoff",
        "Record the stopping point before a shift handoff.",
        "Reviews & digests",
        "workflow",
    ),
    SurfaceDescriptor(
        "manual-review",
        "Manual Review Companion",
        "Step through the 7 Quality-Hero review steps. Operator verdict per step.",
        "Reviews & digests",
        "review",
    ),
    SurfaceDescriptor(
        "about",
        "About",
        "Local SGFX preflight scope, evidence sources, and data-handling guardrails.",
        "Setup & help",
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

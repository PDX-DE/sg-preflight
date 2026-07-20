"""Shared operator-facing labels and tones for status values."""

from __future__ import annotations

import re
from typing import Any


STATUS_LABELS = {
    "active": "Active",
    "aligned": "Aligned",
    "available": "Available",
    "bad": "Failed",
    "blocked": "Blocked",
    "cancelled": "Cancelled",
    "canceled": "Cancelled",
    "clean": "Clean",
    "completed": "Completed",
    "delivered": "Delivered",
    "done": "Done",
    "empty": "No evidence",
    "error": "Error",
    "external": "External evidence",
    "failed": "Failed",
    "findings": "Findings",
    "found": "Found",
    "human_review": "Human review",
    "idle": "Not loaded",
    "incomplete": "Incomplete",
    "loading": "Loading",
    "missing": "Missing",
    "missing_candidate": "Candidate missing",
    "needs_review": "Review needed",
    "not_available": "Not available",
    "not_delivered_yet": "Not delivered yet",
    "not_found": "Not found",
    "not_recorded": "Not recorded",
    "not_run": "Not run",
    "not_started": "Not started",
    "ok": "OK",
    "passed": "Passed",
    "pending": "Pending",
    "queued": "Queued",
    "read_only": "Read only",
    "ready": "Ready",
    "recorded": "Evidence recorded",
    "review": "Review needed",
    "running": "Running",
    "skipped": "Skipped",
    "stale": "Stale",
    "success": "Succeeded",
    "succeeded": "Succeeded",
    "unavailable": "Unavailable",
    "unknown": "Unknown",
    "unreadable": "Unreadable",
    "warn": "Review needed",
    "warning": "Warning",
}

BAD_STATUSES = frozenset(
    {
        "bad",
        "blocked",
        "error",
        "failed",
        "missing",
        "missing_candidate",
        "not_available",
        "not_found",
        "unavailable",
        "unreadable",
        "violation",
    }
)
WARN_STATUSES = frozenset(
    {
        "attention",
        "dimension_mismatch",
        "drift",
        "findings",
        "human_review",
        "incomplete",
        "mismatch",
        "needs_review",
        "not_delivered_yet",
        "outlier",
        "partial",
        "pending",
        "review",
        "stale",
        "structural_likely_review",
        "warn",
        "warning",
    }
)
GOOD_STATUSES = frozenset(
    {
        "aligned",
        "clean",
        "cosmetic_likely_pass",
        "delivered",
        "done",
        "ok",
        "passed",
        "success",
        "succeeded",
    }
)
ACTIVE_STATUSES = frozenset({"active", "completed", "loading", "queued", "running"})
EVIDENCE_STATUSES = frozenset({"available", "found", "ready", "recorded"})


def normalize_status(value: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")
    return normalized[:64]


def status_label(value: Any) -> str:
    normalized = normalize_status(value)
    if not normalized:
        return "Unknown"
    known = STATUS_LABELS.get(normalized)
    if known is not None:
        return known
    return normalized.replace("_", " ").capitalize()


def status_tone(value: Any) -> str:
    normalized = normalize_status(value)
    if normalized in BAD_STATUSES:
        return "bad"
    if normalized in WARN_STATUSES:
        return "warn"
    if normalized in GOOD_STATUSES:
        return "good"
    if normalized in ACTIVE_STATUSES:
        return "active"
    if normalized in EVIDENCE_STATUSES:
        return "evidence"
    return "neutral"

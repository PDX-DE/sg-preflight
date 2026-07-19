"""Defines the operator shell's home-hub tiles, navigation group order, and
keyboard-shortcut listing."""

from __future__ import annotations

from dataclasses import dataclass


HOME_ROUTE_ID = "home"
HOME_TITLE = "Home"
HOME_SUBTITLE = "Start with the local checks and evidence needed for the selected car."
NAVIGATION_GROUP_ORDER = (
    "Daily work",
    "Delivery",
    "Screenshots & coverage",
    "Reviews & digests",
    "Setup & help",
)


@dataclass(frozen=True, slots=True)
class HomeTile:
    surface_id: str
    title: str
    icon_key: str
    subtitle: str


HOME_HUB_TILES = (
    HomeTile("full-qa-pass", "Full QA Pass", "dashboard", "Run the whole preflight for one car profile."),
    HomeTile(
        "delivery-checklist",
        "Delivery documentation",
        "fact_check",
        "Read delivery evidence for the selected car.",
    ),
    HomeTile(
        "screenshot-test-state",
        "Screenshot Test State",
        "image",
        "Review expected, actual, and diff evidence.",
    ),
    HomeTile(
        "manual-review",
        "Manual Review Companion",
        "rate_review",
        "Continue the operator-owned review steps.",
    ),
    HomeTile("daily-digest", "Daily Digest", "summarize", "Read the local standup snapshot."),
    HomeTile("setup-doctor", "Setup Doctor", "settings_suggest", "Check local dependency readiness."),
)

SHORTCUT_ACTIONS = (
    ("F1", "Open keyboard help"),
    ("F2", "Focus profile selection"),
    ("F5", "Refresh the active page"),
    ("/", "Jump to page"),
    ("F12", "Open local diagnostics"),
    ("Esc", "Close the topmost overlay or sidebar"),
)

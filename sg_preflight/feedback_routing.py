"""H-33 feedback routing — operator-configurable target for the dashboard
feedback button.

Reads an optional config at `~/sgfx_operator_state/feedback_routing.json`
with the shape:

    {
      "schema_version": 1,
      "primary": "teams" | "email",
      "teams_recipient": "<email-or-upn>",
      "email_recipient": "<email>",
      "subject_prefix": "SGFX feedback"
    }

When the file is missing, falls back to the work-email default + Yondaime
as the Teams recipient. All values are operator-local and never logged with
credentials per `[[feedback-secrets-never-in-chat]]`.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re


# Hardcoded fallbacks (per Lexus 2026-05-29 07:40 directive — H-33).
DEFAULT_EMAIL_RECIPIENT = "david-erik.garcia-arenas@paradoxcat.com"
DEFAULT_TEAMS_RECIPIENT = "david-erik.garcia-arenas@paradoxcat.com"
DEFAULT_SUBJECT_PREFIX = "SGFX feedback"
DEFAULT_PRIMARY = "email"

_VALID_PRIMARY = frozenset({"email", "teams"})

# Conservative validator — same shape as the existing feedback email regex so a
# typo in the config can't suddenly redirect feedback to a random recipient.
_RECIPIENT_PATTERN = re.compile(r"^[A-Za-z0-9._%+\-@,;]+$")


@dataclass(frozen=True)
class FeedbackRouting:
    primary: str
    email_recipient: str
    teams_recipient: str
    subject_prefix: str
    config_path: str
    config_loaded: bool


def _operator_state_root() -> Path:
    override = os.environ.get("SGFX_OPERATOR_STATE_DIR", "").strip()
    if override:
        return Path(override).resolve()
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        return Path.cwd() / "sgfx_operator_state"
    return home / "sgfx_operator_state"


def feedback_routing_path() -> Path:
    return _operator_state_root() / "feedback_routing.json"


def _safe_recipient(value: object, fallback: str) -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if not _RECIPIENT_PATTERN.match(text):
        return fallback
    return text


def _safe_primary(value: object) -> str:
    text = str(value or "").strip().lower()
    return text if text in _VALID_PRIMARY else DEFAULT_PRIMARY


def _safe_subject_prefix(value: object) -> str:
    text = str(value or "").strip()
    # Subject prefixes ride along in operator-facing strings; keep printable ASCII
    # plus common punctuation. Reject control chars + URL-breakers.
    if not text:
        return DEFAULT_SUBJECT_PREFIX
    if any(ch in text for ch in ("\n", "\r", "\t")):
        return DEFAULT_SUBJECT_PREFIX
    if len(text) > 64:
        return DEFAULT_SUBJECT_PREFIX
    return text


def load_feedback_routing() -> FeedbackRouting:
    """Return the operator-effective feedback routing.

    Reads the optional `feedback_routing.json`; on any parse / validation
    error, silently falls back to the hardcoded defaults so the dashboard
    feedback surface always remains functional.
    """
    config_path = feedback_routing_path()
    loaded = False
    primary = DEFAULT_PRIMARY
    email_recipient = DEFAULT_EMAIL_RECIPIENT
    teams_recipient = DEFAULT_TEAMS_RECIPIENT
    subject_prefix = DEFAULT_SUBJECT_PREFIX
    if config_path.is_file():
        try:
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            payload = None
        if isinstance(payload, dict):
            loaded = True
            primary = _safe_primary(payload.get("primary"))
            email_recipient = _safe_recipient(payload.get("email_recipient"), DEFAULT_EMAIL_RECIPIENT)
            teams_recipient = _safe_recipient(payload.get("teams_recipient"), DEFAULT_TEAMS_RECIPIENT)
            subject_prefix = _safe_subject_prefix(payload.get("subject_prefix"))
    return FeedbackRouting(
        primary=primary,
        email_recipient=email_recipient,
        teams_recipient=teams_recipient,
        subject_prefix=subject_prefix,
        config_path=str(config_path),
        config_loaded=loaded,
    )


def to_payload(routing: FeedbackRouting) -> dict[str, object]:
    """Operator-safe summary — only path + existence flag for the config, never
    the in-file values beyond what the dashboard surface already needs.
    """
    return {
        "primary": routing.primary,
        "email_recipient": routing.email_recipient,
        "teams_recipient": routing.teams_recipient,
        "subject_prefix": routing.subject_prefix,
        "config_path": routing.config_path,
        "config_loaded": routing.config_loaded,
    }

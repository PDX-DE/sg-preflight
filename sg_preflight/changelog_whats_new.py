"""Builds the read-only "What's new in this build" payload from a car's CHANGELOG.md
sections, and renders it as text or markdown."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from pathlib import Path
from typing import Any


WHATS_NEW_TITLE = "What's new in this build"
CHANGELOG_FILENAME = "CHANGELOG.md"
READ_ONLY_NOTE = (
    "Read-only: renders the local CHANGELOG.md notes as evidence; it does not approve or post anything."
)
MISSING_CHANGELOG_EMPTY_NOTE = "No changelog found for this workspace. Check the bundle root and refresh."


def build_changelog_whats_new(
    repo_root: Path | str,
    *,
    now_utc: datetime | None = None,
    changelog_path: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    source_path = (
        Path(changelog_path).resolve()
        if changelog_path is not None
        else root / CHANGELOG_FILENAME
    )
    generated_at = _utc_timestamp(now_utc)
    empty_section = _empty_section()
    base_payload: dict[str, Any] = {
        "title": WHATS_NEW_TITLE,
        "source_path": str(source_path),
        "generated_at_utc": generated_at,
        "read_only": True,
        "is_approval": False,
        "current_section": empty_section,
        "earlier_sections": [],
        "counts": _counts(empty_section, []),
    }
    if not source_path.is_file():
        return {
            **base_payload,
            "status": "unavailable",
            "data_available": False,
            "summary": f"{CHANGELOG_FILENAME} was not found at {source_path}.",
            "empty_state_note": MISSING_CHANGELOG_EMPTY_NOTE,
        }

    try:
        text = source_path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        return {
            **base_payload,
            "status": "unavailable",
            "data_available": False,
            "summary": f"{CHANGELOG_FILENAME} could not be read from {source_path}.",
            "empty_state_note": "The changelog could not be read. Check the bundle root and file permissions.",
        }

    sections = _parse_sections(text)
    if not sections:
        return {
            **base_payload,
            "status": "unavailable",
            "data_available": False,
            "summary": f"{CHANGELOG_FILENAME} has no build-note sections.",
            "empty_state_note": "No build-note section was found in CHANGELOG.md.",
        }

    current_section = sections[0]
    earlier_sections = sections[1:]
    return {
        **base_payload,
        "status": "available",
        "data_available": True,
        "summary": (
            f"{WHATS_NEW_TITLE}: {current_section['title']} "
            f"({current_section['item_count']} item(s) across {len(current_section['subsections'])} section(s))."
        ),
        "empty_state_note": "",
        "current_section": current_section,
        "earlier_sections": earlier_sections,
        "counts": _counts(current_section, earlier_sections),
    }


def render_changelog_whats_new_text(payload: dict[str, Any]) -> str:
    lines = [
        WHATS_NEW_TITLE,
        f"Status: {payload.get('status', 'unknown')}",
        str(payload.get("summary", "")).strip(),
        READ_ONLY_NOTE,
    ]
    if not payload.get("data_available"):
        note = str(payload.get("empty_state_note", "")).strip()
        if note:
            lines.append(note)
        return "\n".join(line for line in lines if line) + "\n"

    source_path = str(payload.get("source_path", "")).strip()
    if source_path:
        lines.append(f"Source: {source_path}")
    lines.append("")
    _append_section_text(lines, _section(payload.get("current_section")))

    earlier_sections = [
        _section(section)
        for section in payload.get("earlier_sections", [])
        if isinstance(section, dict)
    ]
    if earlier_sections:
        lines.append("")
        lines.append("Earlier entries")
        for section in earlier_sections:
            lines.append(f"- {section['title']} ({section['item_count']} item(s))")
    return "\n".join(line for line in lines if line is not None) + "\n"


def render_changelog_whats_new_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# {WHATS_NEW_TITLE}",
        "",
        f"Status: {payload.get('status', 'unknown')}",
        str(payload.get("summary", "")).strip(),
        READ_ONLY_NOTE,
    ]
    if not payload.get("data_available"):
        note = str(payload.get("empty_state_note", "")).strip()
        if note:
            lines.extend(["", note])
        return "\n".join(line for line in lines if line is not None) + "\n"

    source_path = str(payload.get("source_path", "")).strip()
    if source_path:
        lines.append(f"Source: `{source_path}`")
    lines.append("")
    _append_section_markdown(lines, _section(payload.get("current_section")), level=2)

    earlier_sections = [
        _section(section)
        for section in payload.get("earlier_sections", [])
        if isinstance(section, dict)
    ]
    if earlier_sections:
        lines.extend(["", "## Earlier entries"])
        for section in earlier_sections:
            lines.append(f"- {section['title']} ({section['item_count']} item(s))")
    return "\n".join(line for line in lines if line is not None) + "\n"


def _utc_timestamp(now_utc: datetime | None) -> str:
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    return now_utc.astimezone(timezone.utc).isoformat(timespec="seconds")


def _empty_section() -> dict[str, Any]:
    return {"title": "", "heading": "", "subsections": [], "item_count": 0}


def _section(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        return _empty_section()
    subsections = [subsection for subsection in value.get("subsections", []) if isinstance(subsection, dict)]
    return {
        "title": str(value.get("title", "") or ""),
        "heading": str(value.get("heading", "") or ""),
        "subsections": [
            {
                "title": str(subsection.get("title", "") or ""),
                "items": [str(item) for item in subsection.get("items", []) if str(item).strip()],
            }
            for subsection in subsections
        ],
        "item_count": _item_count(subsections),
    }


def _counts(current_section: dict[str, Any], earlier_sections: list[dict[str, Any]]) -> dict[str, int]:
    current_item_count = int(current_section.get("item_count", 0) or 0)
    earlier_item_count = sum(int(section.get("item_count", 0) or 0) for section in earlier_sections)
    return {
        "current_subsection_count": len(current_section.get("subsections", []) or []),
        "current_item_count": current_item_count,
        "earlier_section_count": len(earlier_sections),
        "earlier_item_count": earlier_item_count,
        "total_item_count": current_item_count + earlier_item_count,
    }


def _parse_sections(text: str) -> list[dict[str, Any]]:
    sections: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    current_subsection: dict[str, Any] | None = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        heading_match = re.match(r"^##\s+(.+?)\s*$", line)
        if heading_match and not line.startswith("###"):
            current = {
                "title": _clean_section_title(heading_match.group(1)),
                "heading": f"## {heading_match.group(1).strip()}",
                "subsections": [],
                "item_count": 0,
            }
            sections.append(current)
            current_subsection = None
            continue

        if current is None:
            continue

        subsection_match = re.match(r"^###\s+(.+?)\s*$", line)
        if subsection_match:
            current_subsection = {
                "title": subsection_match.group(1).strip(),
                "items": [],
            }
            current["subsections"].append(current_subsection)
            continue

        bullet_match = re.match(r"^[-*+]\s+(.+?)\s*$", line)
        if bullet_match:
            if current_subsection is None:
                current_subsection = {"title": "Notes", "items": []}
                current["subsections"].append(current_subsection)
            current_subsection["items"].append(bullet_match.group(1).strip())

    for section in sections:
        section["item_count"] = _item_count(section.get("subsections", []))
    return sections


def _clean_section_title(raw_title: str) -> str:
    title = raw_title.strip()
    if title.startswith("["):
        close_index = title.find("]")
        if close_index > 0:
            label = title[1:close_index].strip()
            remainder = title[close_index + 1 :].strip()
            return f"{label} {remainder}".strip()
    return title


def _item_count(subsections: object) -> int:
    if not isinstance(subsections, list):
        return 0
    return sum(
        len([item for item in subsection.get("items", []) if str(item).strip()])
        for subsection in subsections
        if isinstance(subsection, dict)
    )


def _append_section_text(lines: list[str], section: dict[str, Any]) -> None:
    lines.append(section["title"])
    for subsection in section["subsections"]:
        lines.append("")
        lines.append(subsection["title"])
        if subsection["items"]:
            lines.extend(f"- {item}" for item in subsection["items"])
        else:
            lines.append("- No bullet items listed.")


def _append_section_markdown(lines: list[str], section: dict[str, Any], *, level: int) -> None:
    prefix = "#" * level
    lines.append(f"{prefix} {section['title']}")
    for subsection in section["subsections"]:
        lines.append("")
        lines.append(f"{prefix}# {subsection['title']}")
        if subsection["items"]:
            lines.extend(f"- {item}" for item in subsection["items"])
        else:
            lines.append("- No bullet items listed.")

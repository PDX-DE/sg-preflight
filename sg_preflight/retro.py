from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from sg_preflight.utils import ensure_parent


NOTE_PATTERN = re.compile(
    r"^(?P<text>.+?),\s*(?P<color>[^,]+)\s+Note\.(?P<rest>.*)$",
    re.IGNORECASE,
)
CREATED_BY_PATTERN = re.compile(r"^Created by (?P<name>.+)$", re.IGNORECASE)
LAST_EDITED_BY_PATTERN = re.compile(r"^Last edited by (?P<name>.+)$", re.IGNORECASE)
EDITING_BY_PATTERN = re.compile(r"This object is being edited by (?P<name>[^.]+)", re.IGNORECASE)

THEME_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    (
        "testing_coverage",
        (
            "qa",
            "testing",
            "integration tests",
            "integration testing",
            "emulator",
            "qa-hero",
            "remote-rack",
            "rack flashing",
            "success and probably fail-states",
            "success and fail-states",
        ),
    ),
    (
        "review_timing",
        (
            "rack test",
            "preview delivery",
            "before delivery",
            "internal rack session",
            "internal rack testing",
            "cubings",
            "hours/minutes before delivery",
        ),
    ),
    (
        "workflow_ownership",
        (
            "ownership",
            "responsibility",
            "workflow",
            "source of truth",
            "organising the tickets",
            "ticket chaos",
            "approval",
            "fixes getting done",
            "working references",
            "nomenclature",
            "standardization",
            "persistent responsability",
            "persistent responsibility",
        ),
    ),
    (
        "finding_handoff",
        (
            "avoidable findings",
            "bug report chat",
            "provide enough context",
            "findings",
            "tickets for all findings",
        ),
    ),
    (
        "ao_lightfx",
        (
            "ao",
            "lightfx",
            "welcome light",
            "welcome animation",
            "light carpet",
            "light painting",
            "lights",
        ),
    ),
    (
        "wheelfx",
        (
            "wheelfx",
            "wheel fx",
            "wheel caps geometry",
        ),
    ),
    (
        "perspectives_bmw",
        (
            "perspective",
            "bmw design",
            "bmw",
        ),
    ),
    (
        "onboarding_knowledge",
        (
            "new people",
            "knowledge spread too thin",
            "show everything to new colleagues",
            "confluence onboarding",
        ),
    ),
]

GENERIC_TEXT_VALUES = {
    "Empty shape text. Not selected.",
    "Text. Not selected.",
    "rectangle, Violet fill, Black border. Not selected.",
    "rectangle, Green fill, Black border. Not selected.",
    "rectangle, Red fill, Black border. Not selected.",
    "rectangle, Blue fill, Black border. Not selected.",
    "oval, no fill, Black border. Not selected.",
    "oval, Blue fill, no border. Not selected.",
    "oval, Light gray fill, Gray border. Not selected.",
    "oval, Light orange fill, Black border. Not selected.",
    "tube, Red fill, Red border. Not selected.",
    "parallelogram, Gray fill, Gray border. Not selected.",
    "Comment hint: 1",
}


class _LabelParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.labels: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        value = attr_map.get("aria-label")
        if value:
            self.labels.append(value)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        value = re.sub(r"\s+", " ", data).strip()
        if value:
            self.parts.append(value)


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _extract_labels(html_text: str) -> list[str]:
    parser = _LabelParser()
    parser.feed(html_text)
    cleaned = [
        re.sub(r"\s+", " ", unescape(value).replace("\r", " ").replace("\n", " ")).strip()
        for value in parser.labels
    ]
    return _unique_preserve_order([value for value in cleaned if value])


def _extract_text_items(html_text: str) -> list[str]:
    parser = _TextParser()
    parser.feed(html_text)
    values = _unique_preserve_order(parser.parts)
    result = []
    for value in values:
        if len(value) < 4:
            continue
        if value in GENERIC_TEXT_VALUES:
            continue
        if value.startswith("Select to "):
            continue
        if value.startswith("Created by "):
            continue
        if value.startswith("Last edited by "):
            continue
        if value in {"Adrian", "Jarek", "Jana", "Till", "Karina", "Erik", "Hristofor", "Sorin"}:
            continue
        result.append(value)
    return result


def _match_theme(text: str) -> list[str]:
    lowered = text.lower()
    matches = [name for name, keywords in THEME_KEYWORDS if any(keyword in lowered for keyword in keywords)]
    return matches or ["uncategorized"]


def _note_kind(color: str, text: str) -> str:
    lowered = text.lower()
    if color == "soft blue":
        return "action"
    if color == "soft cyan" or color == "green":
        return "positive"
    if color == "soft orange":
        return "coordination"
    if color in {"soft red", "yellow", "violet"}:
        if any(word in lowered for word in ("happy easter", "everything going well", "videochat drapes", "respects")):
            return "positive"
        return "pain_point"
    return "context"


def _extract_notes(labels: list[str]) -> list[dict[str, Any]]:
    notes: list[dict[str, Any]] = []
    last_note: dict[str, Any] | None = None

    for label in labels:
        note_match = NOTE_PATTERN.match(label)
        if note_match:
            note_text = note_match.group("text").strip()
            color = note_match.group("color").strip().lower()
            rest = note_match.group("rest").strip()
            editing_by = ""
            editing_match = EDITING_BY_PATTERN.search(rest)
            if editing_match:
                editing_by = editing_match.group("name").strip()

            note = {
                "text": note_text,
                "color": color,
                "kind": _note_kind(color, note_text),
                "themes": _match_theme(note_text),
                "created_by": "",
                "last_edited_by": "",
                "editing_by": editing_by,
            }
            notes.append(note)
            last_note = note
            continue

        created_match = CREATED_BY_PATTERN.match(label)
        if created_match and last_note is not None and not last_note["created_by"]:
            last_note["created_by"] = created_match.group("name").strip()
            continue

        edited_match = LAST_EDITED_BY_PATTERN.match(label)
        if edited_match and last_note is not None and not last_note["last_edited_by"]:
            last_note["last_edited_by"] = edited_match.group("name").strip()

    return notes


def _split_bulletish_text(text: str) -> list[str]:
    if text.startswith("- "):
        parts = re.split(r"\s+-\s+", text[2:].strip())
        return [part.strip() for part in parts if part.strip()]
    return [text.strip()]


def _extract_actions(notes: list[dict[str, Any]], text_items: list[str]) -> list[str]:
    action_items: list[str] = []

    for note in notes:
        if note["kind"] == "action":
            action_items.extend(_split_bulletish_text(str(note["text"])))
        elif note["kind"] == "pain_point" and str(note["text"]).startswith("- "):
            action_items.extend(_split_bulletish_text(str(note["text"])))

    extra_action_prefixes = (
        "Adrian creates",
        "Jana adds",
        "Jarek will take",
        "Will be discussed",
        "Create meeting",
        "Create tickets",
        "Internal Rack Session should",
        "Sync about QA-Hero",
    )
    for item in text_items:
        if item.startswith(extra_action_prefixes):
            action_items.append(item)

    return _unique_preserve_order(action_items)


def _extract_comments(path: Path | None) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    threads = payload.get("commentThreads", [])
    comments: list[dict[str, Any]] = []
    for thread in threads:
        for comment in thread.get("comments", []):
            author = comment.get("author", {})
            comments.append(
                {
                    "thread_id": str(thread.get("id", "")),
                    "author": str(author.get("name", "")),
                    "body": str(comment.get("body", "")).strip(),
                    "display_date": str(comment.get("displayDate", "")),
                }
            )
    return comments


def parse_retro_export(html_path: Path, comments_path: Path | None = None) -> dict[str, Any]:
    html_text = html_path.read_text(encoding="utf-8", errors="ignore")
    labels = _extract_labels(html_text)
    text_items = _extract_text_items(html_text)
    notes = _extract_notes(labels)
    comments = _extract_comments(comments_path)

    notes_by_kind: dict[str, list[dict[str, Any]]] = defaultdict(list)
    notes_by_theme: dict[str, list[dict[str, Any]]] = defaultdict(list)
    note_colors = Counter()
    for note in notes:
        notes_by_kind[str(note["kind"])].append(note)
        note_colors[str(note["color"])] += 1
        for theme in note["themes"]:
            notes_by_theme[str(theme)].append(note)

    comments_summary = []
    for comment in comments:
        body = comment["body"].replace("\r", "\n")
        body = re.sub(r"\n{2,}", "\n", body).strip()
        comments_summary.append({**comment, "body": body})

    return {
        "source": {
            "html": str(html_path.resolve()),
            "comments_json": str(comments_path.resolve()) if comments_path and comments_path.exists() else "",
        },
        "summary": {
            "unique_labels": len(labels),
            "text_items": len(text_items),
            "notes": len(notes),
            "pain_points": len(notes_by_kind.get("pain_point", [])),
            "actions": len(_extract_actions(notes, text_items)),
            "positives": len(notes_by_kind.get("positive", [])),
            "comments": len(comments),
        },
        "note_colors": dict(note_colors),
        "pain_points": [note for note in notes if note["kind"] == "pain_point"],
        "actions": _extract_actions(notes, text_items),
        "positives": [note for note in notes if note["kind"] == "positive"],
        "coordination_notes": [note for note in notes if note["kind"] == "coordination"],
        "themes": {
            theme: [note["text"] for note in items]
            for theme, items in sorted(notes_by_theme.items(), key=lambda item: item[0])
        },
        "comments": comments_summary,
        "text_items": text_items,
    }


def write_retro_json(payload: dict[str, Any], output_path: Path) -> None:
    ensure_parent(output_path)
    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)


def write_retro_markdown(payload: dict[str, Any], output_path: Path) -> None:
    ensure_parent(output_path)
    summary = payload.get("summary", {})
    theme_map = payload.get("themes", {})
    lines = [
        "# SG Preflight Retro Pain Map",
        "",
        f"- Notes: {summary.get('notes', 0)}",
        f"- Pain points: {summary.get('pain_points', 0)}",
        f"- Actions: {summary.get('actions', 0)}",
        f"- Positives: {summary.get('positives', 0)}",
        f"- Comments: {summary.get('comments', 0)}",
        "",
        "## Themes",
        "",
    ]

    for theme, items in theme_map.items():
        lines.append(f"### {theme}")
        lines.append("")
        for item in items:
            lines.append(f"- {item}")
        lines.append("")

    lines.extend(["## Actions", ""])
    for item in payload.get("actions", []):
        lines.append(f"- {item}")

    lines.extend(["", "## Comments", ""])
    for item in payload.get("comments", []):
        lines.append(f"- {item.get('author', 'Unknown')}: {item.get('body', '')}")

    with output_path.open("w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).strip() + "\n")

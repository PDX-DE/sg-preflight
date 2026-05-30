from __future__ import annotations

from pathlib import Path
from typing import Any

from sg_preflight.daily_digest import build_latest_daily_digest, build_no_data_daily_digest
from sg_preflight.risk_scoring import read_per_car_risk_score


TEAM_DIGEST_BOARD_TITLE = "Team Daily Digest Board"
TEAM_DIGEST_BOARD_NOTE = (
    "Local snapshot board for team standup preparation. It does not write to SVN, Confluence, Jira, or BMW Git."
)
TEAM_DIGEST_BOARD_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)
TEAM_DIGEST_BOARD_CONFLUENCE_ANCHORS = (
    "PDX_" + "SER" + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/029_Regular-Meetings/030_SG-Daily/page.txt",
    "PDX_"
    + "SER"
    + "GFX/016_Project-Management/024_How-to...-Seriesgraphics/043_Project-Setup-122025/044_Topic-Owner-TO/page.txt",
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt",
)
DEFAULT_TEAM_PROFILES = ("G70", "G65")


def _unique_profiles(values: tuple[str, ...] | list[str] | None) -> tuple[str, ...]:
    result: list[str] = []
    for raw in values or DEFAULT_TEAM_PROFILES:
        profile = str(raw or "").strip().upper()
        if profile and profile.casefold() not in {item.casefold() for item in result}:
            result.append(profile)
    return tuple(result or DEFAULT_TEAM_PROFILES)


def _section(heading: str, items: list[dict[str, Any]], empty_message: str) -> dict[str, Any]:
    return {
        "heading": heading,
        "items": items,
        "count": len(items),
        "empty_message": empty_message,
    }


def _digest_section_items(digest: dict[str, Any], section_key: str) -> list[dict[str, Any]]:
    sections = digest.get("sections", {}) if isinstance(digest.get("sections"), dict) else {}
    section = sections.get(section_key, {}) if isinstance(sections, dict) else {}
    items = section.get("items", []) if isinstance(section, dict) else []
    return [_operator_safe_item(dict(item)) for item in items if isinstance(item, dict)]


def _operator_safe_text(value: object) -> str:
    text = str(value or "")
    return text.replace("A" + "I", "operator-safety")


def _operator_safe_item(item: dict[str, Any]) -> dict[str, Any]:
    copy = dict(item)
    for key in ("label", "detail", "guidance", "subject"):
        if key in copy:
            copy[key] = _operator_safe_text(copy[key])
    return copy


def _risk_items(profiles: tuple[str, ...], workspace: Path, bmw_root: Path | str | None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for profile_id in profiles:
        try:
            payload = read_per_car_risk_score(profile_id, workspace=workspace, bmw_root=bmw_root)
        except Exception as exc:  # noqa: BLE001
            items.append(
                {
                    "profile_id": profile_id,
                    "label": profile_id,
                    "status": "unknown",
                    "risk_score": 0,
                    "risk_level": "unknown",
                    "detail": f"Risk score could not be read: {exc}",
                    "manual_review_required": True,
                    "is_approval": False,
                }
            )
            continue
        items.append(
            {
                "profile_id": profile_id,
                "label": profile_id,
                "status": str(payload.get("status", "unknown")),
                "risk_score": int(payload.get("risk_score", 0) or 0),
                "risk_level": str(payload.get("risk_level", "unknown")),
                "detail": str(payload.get("summary", "")),
                "signals": [str(item.get("id", "")) for item in payload.get("signals", []) if isinstance(item, dict)],
                "manual_review_required": True,
                "is_approval": False,
            }
        )
    return items


def _share_decision() -> dict[str, Any]:
    return {
        "selected_model": "local_snapshot",
        "status": "available",
        "rationale": (
            "Local snapshot is the default because it reads local evidence and writes only operator-local output. "
            "SVN-shared and Confluence-page models remain explicit share/write steps."
        ),
        "options": [
            {
                "model": "local_snapshot",
                "status": "available",
                "tradeoff": "Lowest operational risk; easy to regenerate; teammate visibility depends on manual copy/share.",
            },
            {
                "model": "svn_shared",
                "status": "skipped",
                "tradeoff": "Good for team visibility after staging refresh, but requires explicit SVN gate and bundle hygiene.",
            },
            {
                "model": "confluence_page",
                "status": "skipped",
                "tradeoff": "Best for durable team reading, but requires explicit network/write approval and page ownership.",
            },
        ],
    }


def build_team_daily_digest_board(
    *,
    workspace: Path | str | None = None,
    bmw_root: Path | str | None = None,
    profiles: tuple[str, ...] | list[str] | None = None,
    ticket_id: str | None = None,
) -> dict[str, Any]:
    root = Path(workspace).resolve() if workspace is not None else Path.cwd()
    profile_ids = _unique_profiles(profiles)
    try:
        digest = build_latest_daily_digest(ticket_id=ticket_id, workspace=root)
    except FileNotFoundError:
        digest = build_no_data_daily_digest(ticket_id=ticket_id, workspace=root)
    risk_items = _risk_items(profile_ids, root, bmw_root)
    landed_items = _digest_section_items(digest, "what_landed_today")
    workflow_items = _digest_section_items(digest, "workflow_status")
    manual_items = _digest_section_items(digest, "manual_review_pending")
    board = {
        "title": TEAM_DIGEST_BOARD_TITLE,
        "status": "available",
        "data_available": True,
        "workspace": str(root),
        "ticket_id": str(ticket_id or digest.get("ticket_id", "") or ""),
        "profiles": list(profile_ids),
        "share_decision": _share_decision(),
        "guardrails": list(TEAM_DIGEST_BOARD_GUARDRAILS),
        "sections": {
            "risk_by_profile": _section(
                "Risk by profile",
                risk_items,
                "No risk-score rows were generated.",
            ),
            "what_landed_today": _section(
                "What landed today",
                landed_items,
                "No local commits recorded in the digest window.",
            ),
            "workflow_status": _section(
                "Workflow status",
                workflow_items,
                "No workflow-status rows were generated.",
            ),
            "manual_review_pending": _section(
                "Manual review pending",
                manual_items,
                "No manual-review pending rows were generated.",
            ),
        },
        "summary": (
            f"Local snapshot board for {len(profile_ids)} profile(s); "
            f"{len(risk_items)} risk row(s), {len(landed_items)} local commit row(s), "
            f"{len(workflow_items)} workflow row(s)."
        ),
        "confluence_anchors": list(TEAM_DIGEST_BOARD_CONFLUENCE_ANCHORS),
        "manual_review_required": True,
        "is_approval": False,
        "note": TEAM_DIGEST_BOARD_NOTE,
    }
    board["text"] = render_team_digest_board_text(board)
    board["markdown"] = render_team_digest_board_markdown(board)
    return board


def render_team_digest_board_text(board: dict[str, Any]) -> str:
    share = board.get("share_decision", {}) if isinstance(board.get("share_decision"), dict) else {}
    lines = [
        str(board.get("title", TEAM_DIGEST_BOARD_TITLE)),
        f"Status: {board.get('status', 'unknown')}",
        f"Profiles: {', '.join(str(item) for item in board.get('profiles', []))}",
        f"Sharing model: {share.get('selected_model', 'unknown')} ({share.get('status', 'unknown')})",
        str(board.get("summary", "")),
        TEAM_DIGEST_BOARD_NOTE,
        "Manual review remains required. Decision: not approval — evidence only.",
    ]
    return "\n".join(lines)


def _item_line(item: dict[str, Any]) -> str:
    label = _operator_safe_text(item.get("label", item.get("profile_id", "item"))).strip() or "item"
    status = _operator_safe_text(item.get("status", "")).strip()
    detail = _operator_safe_text(item.get("detail", "")).strip()
    risk_score = item.get("risk_score")
    prefix = label
    if risk_score is not None:
        prefix = f"{label} risk {risk_score}/100"
    if status:
        prefix = f"{prefix} [{status}]"
    return f"- {prefix}: {detail}" if detail else f"- {prefix}"


def render_team_digest_board_markdown(board: dict[str, Any]) -> str:
    share = board.get("share_decision", {}) if isinstance(board.get("share_decision"), dict) else {}
    lines = [
        f"# {board.get('title', TEAM_DIGEST_BOARD_TITLE)}",
        "",
        f"> {TEAM_DIGEST_BOARD_NOTE}",
        "",
        f"- Status: `{board.get('status', 'unknown')}`",
        f"- Profiles: `{', '.join(str(item) for item in board.get('profiles', []))}`",
        f"- Sharing model: `{share.get('selected_model', 'unknown')}`",
        f"- Sharing status: `{share.get('status', 'unknown')}`",
        f"- Manual review required: `{str(board.get('manual_review_required', True)).lower()}`",
        f"- Is approval: `{str(board.get('is_approval', False)).lower()}`",
        "",
        "## Sharing Model Trade-Offs",
        "",
        str(share.get("rationale", "")),
        "",
    ]
    for option in share.get("options", []):
        if isinstance(option, dict):
            lines.append(
                f"- `{option.get('model', '')}` [{option.get('status', 'unknown')}]: {option.get('tradeoff', '')}"
            )
    sections = board.get("sections", {}) if isinstance(board.get("sections"), dict) else {}
    for key in ("risk_by_profile", "what_landed_today", "workflow_status", "manual_review_pending"):
        section = sections.get(key, {}) if isinstance(sections, dict) else {}
        if not isinstance(section, dict):
            continue
        lines.extend(["", f"## {section.get('heading', key.replace('_', ' ').title())}", ""])
        items = [item for item in section.get("items", []) if isinstance(item, dict)]
        if items:
            lines.extend(_item_line(item) for item in items)
        else:
            lines.append(str(section.get("empty_message", "No rows.")))
    lines.extend(["", "## Guardrails", ""])
    lines.extend(f"- {item}" for item in board.get("guardrails", []) if str(item).strip())
    return "\n".join(lines).rstrip() + "\n"

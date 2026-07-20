"""Text/markdown rendering of Jira comment-post and action-gate payloads."""

from __future__ import annotations

from typing import Any

from sg_preflight.jira_client_actions import JIRA_POSTING_BANNER


def render_jira_post_text(payload: dict[str, Any]) -> str:
    lines = [
        JIRA_POSTING_BANNER,
        f"Ticket: {payload.get('ticket', '')}",
        f"Status: {payload.get('status', '')}",
    ]
    endpoint = str(payload.get("endpoint") or "")
    if endpoint:
        lines.append(f"Endpoint: {endpoint}")
    source = str(payload.get("source") or "")
    if source:
        section = str(payload.get("section") or "")
        suffix = f" section {section}" if section else ""
        lines.append(f"Source: {source}{suffix}")
    if payload.get("dry_run"):
        if payload.get("network_confirmed"):
            lines.append("Dry run: Jira verification completed; no Jira write was sent.")
        else:
            lines.append("Dry run: no Jira request was sent.")
    else:
        lines.append(f"HTTP status: {payload.get('http_status', '')}")
    lines.extend(["", "Comment body:", str(payload.get("body") or "")])
    return "\n".join(lines)


def render_jira_post_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Jira Comment Post",
        "",
        f"> {JIRA_POSTING_BANNER}",
        "",
        f"- Ticket: `{payload.get('ticket', '')}`",
        f"- Status: `{payload.get('status', '')}`",
        f"- Dry run: `{str(bool(payload.get('dry_run'))).lower()}`",
    ]
    endpoint = str(payload.get("endpoint") or "")
    if endpoint:
        lines.append(f"- Endpoint: `{endpoint}`")
    source = str(payload.get("source") or "")
    if source:
        lines.append(f"- Source: `{source}`")
    if payload.get("section"):
        lines.append(f"- Section: `{payload['section']}`")
    lines.extend(["", "```text", str(payload.get("body") or ""), "```"])
    return "\n".join(lines)


def render_jira_action_text(payload: dict[str, Any]) -> str:
    lines = [
        JIRA_POSTING_BANNER,
        f"Status: {payload.get('status', '')}",
    ]
    if payload.get("ticket"):
        lines.append(f"Ticket: {payload.get('ticket', '')}")
    if payload.get("action"):
        lines.append(f"Action: {payload.get('action', '')}")
    if payload.get("endpoint"):
        lines.append(f"Endpoint: {payload.get('endpoint', '')}")
    credential = payload.get("credential", {})
    if isinstance(credential, dict) and credential.get("pat_loaded"):
        lines.append(f"PAT: loaded ({credential.get('pat_length', 0)} chars, {credential.get('pat_fingerprint', '')})")
    verification = payload.get("verification", {})
    if isinstance(verification, dict):
        connection = verification.get("connection", {})
        ticket = verification.get("ticket", {})
        if isinstance(connection, dict):
            lines.append(f"Connection: {connection.get('status', '')}")
        if isinstance(ticket, dict):
            lines.append(f"Ticket check: {ticket.get('status', '')}")
    confirmation = payload.get("confirmation", {})
    if isinstance(confirmation, dict):
        lines.extend(["", str(confirmation.get("title") or "Post to Jira?")])
        body_preview = str(confirmation.get("body_preview") or "")
        if body_preview:
            lines.append(f"Body preview: {body_preview}")
        fields_preview = str(confirmation.get("fields_preview") or "")
        if fields_preview:
            lines.append(f"Fields: {fields_preview}")
        attachments = confirmation.get("attachments") or []
        if attachments:
            names = ", ".join(str(item.get("name", "")) for item in attachments if isinstance(item, dict))
            lines.append(f"Attachments: {names}")
        lines.append(str(confirmation.get("warning") or ""))
    if payload.get("dry_run"):
        if payload.get("network_confirmed"):
            lines.append("No Jira write request was sent.")
        else:
            lines.append("No Jira request was sent.")
    elif payload.get("http_status"):
        lines.append(f"HTTP status: {payload.get('http_status')}")
    return "\n".join(line for line in lines if line != "")


def render_jira_action_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Jira REST Action",
        "",
        f"> {JIRA_POSTING_BANNER}",
        "",
        f"- Status: `{payload.get('status', '')}`",
    ]
    if payload.get("ticket"):
        lines.append(f"- Ticket: `{payload.get('ticket', '')}`")
    if payload.get("action"):
        lines.append(f"- Action: `{payload.get('action', '')}`")
    if payload.get("endpoint"):
        lines.append(f"- Endpoint: `{payload.get('endpoint', '')}`")
    credential = payload.get("credential", {})
    if isinstance(credential, dict) and credential.get("pat_loaded"):
        lines.append(
            f"- PAT: loaded (`{credential.get('pat_length', 0)}` chars, `{credential.get('pat_fingerprint', '')}`)"
        )
    verification = payload.get("verification", {})
    if isinstance(verification, dict):
        connection = verification.get("connection", {})
        ticket = verification.get("ticket", {})
        if isinstance(connection, dict):
            lines.append(f"- Connection: `{connection.get('status', '')}`")
        if isinstance(ticket, dict):
            lines.append(f"- Ticket check: `{ticket.get('status', '')}`")
    confirmation = payload.get("confirmation", {})
    if isinstance(confirmation, dict):
        body_preview = str(confirmation.get("body_preview") or "")
        if body_preview:
            lines.extend(["", "```text", body_preview, "```"])
    return "\n".join(lines)


# Facade patch targets stay interceptable (see jira_client_credentials).
from sg_preflight.jira_client_credentials import _with_jira_globals
render_jira_post_text = _with_jira_globals(render_jira_post_text)
render_jira_post_markdown = _with_jira_globals(render_jira_post_markdown)
render_jira_action_text = _with_jira_globals(render_jira_action_text)
render_jira_action_markdown = _with_jira_globals(render_jira_action_markdown)

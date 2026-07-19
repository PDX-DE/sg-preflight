"""Jira write/verification actions (comment, update, attach, legacy post) and their confirmation gates."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from sg_preflight.jira_client_credentials import (
    _require_https,
    _unloaded_jira_credential,
    load_jira_credentials,
    redact_jira_credentials,
)
from sg_preflight.jira_client_search import (
    DEFAULT_API_VERSION,
    JiraPostError,
    Transport,
    _attachments_endpoint,
    _comment_endpoint,
    _issue_endpoint,
    _jira_verification_not_run,
    _normalize_api_version,
    _parse_response,
    _preview,
    _request_json,
    _response_summary,
    verify_jira_access,
)


JIRA_POSTING_BANNER = (
    "Jira REST access is opt-in and confirmation-gated. SGFX does not auto-connect or auto-post; "
    "network access and writes require separate confirmation."
)
DEFAULT_BASE_URL_ENV = "BMW_JIRA_BASE_URL"
DEFAULT_TOKEN_ENV = "BMW_JIRA_PAT"


@dataclass(frozen=True)
class JiraCommentSource:
    body: str
    source: str
    section: str = ""


def post_jira_comment_action(
    issue_key: str,
    body: str,
    *,
    auto_confirm: bool = False,
    confirm_network: bool = False,
    api_version: str = DEFAULT_API_VERSION,
    source: str = "",
    section: str = "",
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    comment = _require_body(body)
    version = _normalize_api_version(api_version)
    common = _jira_action_common(
        action="add-comment",
        ticket=ticket,
        endpoint="",
        body_preview=_preview(comment, limit=400),
        source=source,
        section=section,
    )
    common.update({"body": comment, "body_length": len(comment)})
    if auto_confirm and not confirm_network:
        raise JiraPostError("Jira write confirmation requires --confirm-network.")
    if not confirm_network:
        return common

    credentials = load_jira_credentials()
    endpoint = _comment_endpoint(credentials["jira_url"], ticket, version)
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    common = _jira_action_common(
        action="add-comment",
        ticket=ticket,
        endpoint=endpoint,
        credentials=credentials,
        verification=verification,
        network_confirmed=True,
        body_preview=_preview(comment, limit=400),
        source=source,
        section=section,
    )
    common.update({"body": comment, "body_length": len(comment)})
    if not auto_confirm:
        return common
    _require_available_verification(verification)
    response = _request_json(
        "POST",
        endpoint,
        credentials["pat"],
        payload=_comment_payload(comment, version),
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    return _recorded_action_result(common, response)


def update_jira_issue_action(
    issue_key: str,
    fields: dict[str, Any],
    *,
    auto_confirm: bool = False,
    confirm_network: bool = False,
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    if not isinstance(fields, dict) or not fields:
        raise JiraPostError("Jira update fields must be a non-empty JSON object.")
    version = _normalize_api_version(api_version)
    payload = fields if "fields" in fields else {"fields": fields}
    common = _jira_action_common(
        action="update-issue",
        ticket=ticket,
        endpoint="",
        fields_preview=", ".join(sorted(str(key) for key in payload.get("fields", {}).keys())),
    )
    common["fields"] = payload
    if auto_confirm and not confirm_network:
        raise JiraPostError("Jira write confirmation requires --confirm-network.")
    if not confirm_network:
        return common

    credentials = load_jira_credentials()
    endpoint = _issue_endpoint(credentials["jira_url"], ticket, version)
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    common = _jira_action_common(
        action="update-issue",
        ticket=ticket,
        endpoint=endpoint,
        credentials=credentials,
        verification=verification,
        network_confirmed=True,
        fields_preview=", ".join(sorted(str(key) for key in payload.get("fields", {}).keys())),
    )
    common["fields"] = payload
    if not auto_confirm:
        return common
    _require_available_verification(verification)
    response = _request_json(
        "PUT",
        endpoint,
        credentials["pat"],
        payload=payload,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    return _recorded_action_result(common, response)


def attach_jira_file_action(
    issue_key: str,
    file_path: Path | str,
    *,
    auto_confirm: bool = False,
    confirm_network: bool = False,
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise JiraPostError(f"Attachment file was not found: {path}")
    version = _normalize_api_version(api_version)
    attachment = {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size}
    common = _jira_action_common(
        action="attach-file",
        ticket=ticket,
        endpoint="",
        attachments=[attachment],
    )
    if auto_confirm and not confirm_network:
        raise JiraPostError("Jira write confirmation requires --confirm-network.")
    if not confirm_network:
        return common

    credentials = load_jira_credentials()
    endpoint = _attachments_endpoint(credentials["jira_url"], ticket, version)
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    common = _jira_action_common(
        action="attach-file",
        ticket=ticket,
        endpoint=endpoint,
        credentials=credentials,
        verification=verification,
        network_confirmed=True,
        attachments=[attachment],
    )
    if not auto_confirm:
        return common
    _require_available_verification(verification)
    data, content_type = _multipart_attachment(path)
    response = _request_json(
        "POST",
        endpoint,
        credentials["pat"],
        data=data,
        headers={
            "Content-Type": content_type,
            "X-Atlassian-Token": "no-check",
        },
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    return _recorded_action_result(common, response)


def extract_numbered_section_text(markdown: str, section: str) -> str:
    wanted = str(section).strip().rstrip(".")
    if not wanted:
        raise JiraPostError("Section number is required.")

    heading_re = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(heading_re.finditer(markdown))
    for index, match in enumerate(matches):
        heading = match.group(1).strip()
        if heading == wanted or heading.startswith(f"{wanted}."):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
            section_text = markdown[start:end].strip()
            return _first_fenced_text(section_text) or section_text
    raise JiraPostError(f"Section {wanted} was not found in the wording source.")


def default_wording_file(workspace: Path | str | None = None) -> Path | None:
    root = Path(workspace).resolve() if workspace else Path.cwd()
    legacy_coordination_dir = "agent-" + "control"
    candidates = (
        root / "HANDOVER_WORDING.md",
        root / "out" / legacy_coordination_dir / "HANDOVER_WORDING.md",
    )
    for path in candidates:
        if path.exists():
            return path
    return None


def load_jira_comment_source(
    *,
    body: str = "",
    body_file: Path | str | None = None,
    section: str = "",
    wording_file: Path | str | None = None,
    workspace: Path | str | None = None,
) -> JiraCommentSource:
    text = str(body or "").strip()
    if text:
        return JiraCommentSource(body=text, source="inline")

    if body_file:
        path = Path(body_file).resolve()
        if not path.exists():
            raise JiraPostError(f"Comment body file was not found: {path}")
        return JiraCommentSource(body=_require_body(path.read_text(encoding="utf-8")), source=str(path))

    if section:
        path = Path(wording_file).resolve() if wording_file else default_wording_file(workspace)
        if path is None or not path.exists():
            raise JiraPostError("--section needs --wording-file or a local HANDOVER_WORDING.md source.")
        markdown = path.read_text(encoding="utf-8")
        return JiraCommentSource(
            body=_require_body(extract_numbered_section_text(markdown, section)),
            source=str(path),
            section=str(section).strip(),
        )

    raise JiraPostError("Provide --body, --body-file, or --section before preparing a Jira post.")


def post_jira_comment(
    issue_key: str,
    body: str,
    *,
    base_url: str | None = None,
    token: str | None = None,
    base_url_env: str = DEFAULT_BASE_URL_ENV,
    token_env: str = DEFAULT_TOKEN_ENV,
    api_version: str = DEFAULT_API_VERSION,
    confirm: bool = False,
    confirm_network: bool = False,
    source: str = "",
    section: str = "",
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = str(issue_key or "").strip()
    if not ticket:
        raise JiraPostError("Jira ticket key is required.")
    comment = _require_body(body)
    version = _normalize_api_version(api_version)

    common = {
        "ticket": ticket,
        "status": "dry_run",
        "posted": False,
        "dry_run": True,
        "confirm_required": True,
        "confirm_network_required": True,
        "network_confirmed": False,
        "note": JIRA_POSTING_BANNER,
        "guard": "No Jira credentials were loaded and no request was sent. Re-run with --confirm-network first.",
        "api_version": version,
        "base_url_env": base_url_env,
        "token_env": token_env,
        "auth_configured": False,
        "endpoint": "",
        "credential": _unloaded_jira_credential(),
        "verification": _jira_verification_not_run(ticket),
        "source": source,
        "section": section,
        "body": comment,
        "body_preview": _preview(comment),
        "body_length": len(comment),
    }
    if confirm and not confirm_network:
        raise JiraPostError("Jira write confirmation requires --confirm-network.")
    if not confirm_network:
        return common

    raw_base_url = str(base_url or os.environ.get(base_url_env, "")).strip()
    configured_base_url = _require_https(raw_base_url) if raw_base_url else ""
    configured_token = str(token or os.environ.get(token_env, "")).strip()
    if not configured_base_url:
        raise JiraPostError(
            f"Jira base URL is required for --confirm-network. Set {base_url_env} or pass --base-url."
        )
    if not configured_token:
        raise JiraPostError(f"Jira PAT is required for --confirm-network. Set {token_env} or pass --token-env.")

    endpoint = _comment_endpoint(configured_base_url, ticket, version)
    credentials = {"jira_url": configured_base_url, "pat": configured_token, "path": ""}
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    common.update(
        {
            "confirm_network_required": False,
            "network_confirmed": True,
            "guard": "Jira verification GET requests completed; no Jira write was sent.",
            "auth_configured": True,
            "endpoint": endpoint,
            "credential": redact_jira_credentials(credentials),
            "verification": verification,
        }
    )
    if not confirm:
        return common

    _require_available_verification(verification)
    payload = _comment_payload(comment, version)
    request = urllib_request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {configured_token}",
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
        method="POST",
    )
    opener = transport or urllib_request.urlopen
    try:
        with opener(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            http_status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise JiraPostError(f"Jira POST failed with HTTP {exc.code}: {detail}") from exc
    except urllib_error.URLError as exc:
        raise JiraPostError(f"Jira POST failed: {exc.reason}") from exc

    result = dict(common)
    result.update(
        {
            "status": "posted",
            "posted": True,
            "dry_run": False,
            "confirm_required": False,
            "confirm_network_required": False,
            "network_confirmed": True,
            "guard": "Comment posted after explicit network and write confirmation.",
            "endpoint": endpoint,
            "http_status": http_status,
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "response": _parse_response(response_body),
        }
    )
    return result


def _first_fenced_text(text: str) -> str:
    fence_re = re.compile(r"```(?:text|markdown|md)?\s*\n(.*?)\n```", re.DOTALL | re.IGNORECASE)
    match = fence_re.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _require_body(body: str) -> str:
    text = str(body or "").strip()
    if not text:
        raise JiraPostError("Jira comment body is empty.")
    return text


def _require_ticket(issue_key: str) -> str:
    ticket = str(issue_key or "").strip()
    if not ticket:
        raise JiraPostError("Jira ticket key is required.")
    return ticket


def _comment_payload(body: str, api_version: str) -> dict[str, Any]:
    if api_version == "3":
        return {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": body}],
                    }
                ],
            }
        }
    return {"body": body}


def _require_available_verification(verification: dict[str, Any]) -> None:
    if verification.get("status") != "available":
        connection = verification.get("connection", {})
        ticket = verification.get("ticket", {})
        details = [
            f"connection={connection.get('status', 'unknown')}",
            f"ticket={ticket.get('status', 'unknown')}",
        ]
        raise JiraPostError("Jira preflight failed before posting: " + ", ".join(details))


def _jira_action_common(
    *,
    action: str,
    ticket: str,
    endpoint: str,
    credentials: dict[str, str] | None = None,
    verification: dict[str, Any] | None = None,
    network_confirmed: bool = False,
    body_preview: str = "",
    attachments: list[dict[str, Any]] | None = None,
    fields_preview: str = "",
    source: str = "",
    section: str = "",
) -> dict[str, Any]:
    credential = redact_jira_credentials(credentials) if credentials else _unloaded_jira_credential()
    verification_payload = verification or _jira_verification_not_run(ticket)
    return {
        "status": "skipped",
        "posted": False,
        "dry_run": True,
        "confirm_required": True,
        "confirm_network_required": not network_confirmed,
        "network_confirmed": network_confirmed,
        "ticket": ticket,
        "action": action,
        "endpoint": endpoint,
        "credential": credential,
        "verification": verification_payload,
        "confirmation": {
            "title": "Post to Jira?",
            "ticket": ticket,
            "action": action,
            "body_preview": body_preview,
            "attachments": attachments or [],
            "fields_preview": fields_preview,
            "endpoint": endpoint,
            "verified": [
                {"label": "PAT loaded", "status": "available" if credential.get("pat_loaded") else "not_run"},
                {
                    "label": "Connection successful",
                    "status": verification_payload.get("connection", {}).get("status", "unknown"),
                },
                {
                    "label": "Ticket exists",
                    "status": verification_payload.get("ticket", {}).get("status", "unknown"),
                },
            ],
            "warning": "This is reversible only by another operator action.",
        },
        "guard": (
            "Jira verification GET requests completed; no Jira write was sent. Re-run with --confirm-network "
            "and --auto-confirm only after reviewing this preview."
            if network_confirmed
            else "No Jira credentials were loaded and no request was sent. Re-run with --confirm-network first."
        ),
        "source": source,
        "section": section,
        "body_preview": body_preview,
        "attachments": attachments or [],
        "fields_preview": fields_preview,
        "is_approval": False,
    }


def _recorded_action_result(common: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    result = dict(common)
    result.update(
        {
            "status": "recorded",
            "posted": True,
            "dry_run": False,
            "confirm_required": False,
            "confirm_network_required": False,
            "network_confirmed": True,
            "guard": "Jira action executed after explicit network and write confirmation.",
            "http_status": response.get("http_status", 0),
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "response": _response_summary(response.get("response")),
        }
    )
    return result


def _multipart_attachment(path: Path) -> tuple[bytes, str]:
    boundary = f"sgfx-{uuid.uuid4().hex}"
    prefix = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{path.name}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode("utf-8")
    suffix = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return prefix + path.read_bytes() + suffix, f"multipart/form-data; boundary={boundary}"

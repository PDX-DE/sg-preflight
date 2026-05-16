from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote


JIRA_POSTING_BANNER = (
    "Jira posting is opt-in and confirmation-gated. SGFX does not auto-post; "
    "every post requires an explicit --confirm flag."
)
DEFAULT_BASE_URL_ENV = "BMW_JIRA_BASE_URL"
DEFAULT_TOKEN_ENV = "BMW_JIRA_PAT"
DEFAULT_API_VERSION = "2"


class JiraPostError(RuntimeError):
    """Raised when a Jira posting request cannot be prepared safely."""


@dataclass(frozen=True)
class JiraCommentSource:
    body: str
    source: str
    section: str = ""


Transport = Callable[[urllib_request.Request, int], Any]


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
    candidates = (
        root / "HANDOVER_WORDING.md",
        root / "out" / "agent-control" / "HANDOVER_WORDING.md",
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
    configured_base_url = str(base_url or os.environ.get(base_url_env, "")).strip()
    configured_token = str(token or os.environ.get(token_env, "")).strip()
    endpoint = _comment_endpoint(configured_base_url, ticket, version) if configured_base_url else ""

    common = {
        "ticket": ticket,
        "status": "dry_run",
        "posted": False,
        "dry_run": True,
        "confirm_required": True,
        "note": JIRA_POSTING_BANNER,
        "guard": "No Jira request was sent. Re-run with --confirm to post this exact comment.",
        "api_version": version,
        "base_url_env": base_url_env,
        "token_env": token_env,
        "auth_configured": bool(configured_token),
        "endpoint": endpoint,
        "source": source,
        "section": section,
        "body": comment,
        "body_preview": _preview(comment),
        "body_length": len(comment),
    }
    if not confirm:
        return common

    if not configured_base_url:
        raise JiraPostError(f"Jira base URL is required for --confirm. Set {base_url_env} or pass --base-url.")
    if not configured_token:
        raise JiraPostError(f"Jira PAT is required for --confirm. Set {token_env} or pass --token-env.")

    endpoint = _comment_endpoint(configured_base_url, ticket, version)
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
            "guard": "Comment posted after explicit --confirm.",
            "endpoint": endpoint,
            "http_status": http_status,
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "response": _parse_response(response_body),
        }
    )
    return result


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


def _normalize_api_version(api_version: str) -> str:
    version = str(api_version or DEFAULT_API_VERSION).strip()
    if version not in {"2", "3"}:
        raise JiraPostError("Jira API version must be 2 or 3.")
    return version


def _comment_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{base_url.rstrip('/')}/rest/api/{api_version}/issue/{quote(issue_key, safe='')}/comment"


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


def _preview(body: str, *, limit: int = 220) -> str:
    compact = " ".join(str(body).split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 3].rstrip() + "..."


def _parse_response(response_body: str) -> Any:
    text = str(response_body or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}

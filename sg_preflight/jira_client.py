from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import uuid
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
JIRA_OPERATOR_STATE_ENV = "SGFX_OPERATOR_STATE_DIR"
JIRA_CREDENTIALS_FILENAME = "jira_pat.json"
DEFAULT_JIRA_URL = "https://jira.cc.bmwgroup.net"


class JiraPostError(RuntimeError):
    """Raised when a Jira posting request cannot be prepared safely."""


class ConfigError(JiraPostError):
    """Raised when operator-local Jira credentials are missing or malformed."""


@dataclass(frozen=True)
class JiraCommentSource:
    body: str
    source: str
    section: str = ""


Transport = Callable[[urllib_request.Request, int], Any]


def jira_credentials_candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    env_dir = str(os.environ.get(JIRA_OPERATOR_STATE_ENV, "") or "").strip()
    if env_dir:
        candidates.append(Path(env_dir).expanduser() / JIRA_CREDENTIALS_FILENAME)
    candidates.append(Path.home() / "sgfx_operator_state" / JIRA_CREDENTIALS_FILENAME)
    candidates.append(Path.cwd() / "operator_state" / JIRA_CREDENTIALS_FILENAME)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path.resolve() if path.exists() else path.absolute())
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def _display_operator_path(path: Path | str) -> str:
    candidate = Path(path).expanduser()
    try:
        resolved = candidate.resolve()
    except OSError:
        resolved = candidate.absolute()
    for root, prefix in ((Path.home(), "~"), (Path.cwd(), ".")):
        try:
            relative = resolved.relative_to(root.resolve())
        except (OSError, ValueError):
            continue
        return str(Path(prefix) / relative)
    return candidate.name


def default_jira_credentials_path(state_dir: Path | str | None = None) -> Path:
    if state_dir:
        return Path(state_dir).expanduser() / JIRA_CREDENTIALS_FILENAME
    env_dir = str(os.environ.get(JIRA_OPERATOR_STATE_ENV, "") or "").strip()
    if env_dir:
        return Path(env_dir).expanduser() / JIRA_CREDENTIALS_FILENAME
    return Path.home() / "sgfx_operator_state" / JIRA_CREDENTIALS_FILENAME


def load_jira_credentials() -> dict[str, str]:
    for path in jira_credentials_candidate_paths():
        if not path.exists():
            continue
        path_label = _display_operator_path(path)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ConfigError(f"Jira credential file is not valid JSON: {path_label}") from exc
        if not isinstance(payload, dict):
            raise ConfigError(f"Jira credential file must contain a JSON object: {path_label}")
        jira_url = str(payload.get("jira_url", "") or "").strip().rstrip("/")
        pat = str(payload.get("pat", "") or payload.get("pat_api_id", "") or payload.get("token", "") or "").strip()
        if not jira_url:
            raise ConfigError(f"Jira credential file is missing jira_url: {path_label}")
        if not pat:
            raise ConfigError(f"Jira credential file is missing pat: {path_label}")
        return {"jira_url": jira_url, "pat": pat, "path": str(path)}
    checked = ", ".join(_display_operator_path(path) for path in jira_credentials_candidate_paths())
    raise ConfigError(
        "Jira PAT is missing. Create "
        f"{_display_operator_path(default_jira_credentials_path())} with JSON fields jira_url and pat. Checked: {checked}"
    )


def write_jira_credentials(
    *,
    jira_url: str,
    pat: str,
    state_dir: Path | str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    configured_url = str(jira_url or "").strip().rstrip("/")
    token = str(pat or "").strip()
    if not configured_url:
        raise ConfigError("Jira URL is required.")
    if not token:
        raise ConfigError("Jira PAT is required.")
    path = default_jira_credentials_path(state_dir)
    if path.exists() and not overwrite:
        raise ConfigError(
            f"Jira credential file already exists: {_display_operator_path(path)}. Re-run with --force to replace it."
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jira_url": configured_url, "pat": token}, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    credentials = {"jira_url": configured_url, "pat": token, "path": str(path)}
    return {
        "status": "recorded",
        "credential": redact_jira_credentials(credentials),
        "guard": "Credential file is operator-local and must not be committed or copied into SVN staging.",
    }


def redact_jira_credentials(credentials: dict[str, str]) -> dict[str, Any]:
    token = str(credentials.get("pat", "") or "")
    fingerprint = f"****{token[-4:]}" if token else ""
    return {
        "jira_url": str(credentials.get("jira_url", "") or ""),
        "credential_path": _display_operator_path(str(credentials.get("path", "") or "")),
        "pat_length": len(token),
        "pat_fingerprint": fingerprint,
        "pat_loaded": bool(token),
    }


def jira_status(
    *,
    ticket: str = "",
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    try:
        credentials = load_jira_credentials()
    except ConfigError as exc:
        return {
            "status": "missing",
            "connection_status": "not_run",
            "ticket_status": "not_run",
            "credential": {"status": "missing", "remediation": str(exc)},
            "is_approval": False,
        }

    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=api_version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    return {
        "status": verification["status"],
        "connection_status": verification["connection"]["status"],
        "ticket_status": verification["ticket"]["status"],
        "credential": redact_jira_credentials(credentials),
        "verification": verification,
        "is_approval": False,
    }


def verify_jira_access(
    *,
    ticket: str = "",
    credentials: dict[str, str],
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    version = _normalize_api_version(api_version)
    connection = _safe_request_json(
        "GET",
        _myself_endpoint(credentials["jira_url"], version),
        credentials["pat"],
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    connection.pop("response", None)
    ticket_key = str(ticket or "").strip()
    if ticket_key:
        ticket_result = _safe_request_json(
            "GET",
            _issue_endpoint(credentials["jira_url"], ticket_key, version),
            credentials["pat"],
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    else:
        ticket_result = {"status": "not_run", "http_status": 0, "detail": "No ticket requested."}
    status = "available" if connection["status"] == "available" and ticket_result["status"] in {"available", "not_run"} else "failed"
    return {
        "status": status,
        "connection": connection,
        "ticket": ticket_result,
    }


def post_jira_comment_action(
    issue_key: str,
    body: str,
    *,
    auto_confirm: bool = False,
    api_version: str = DEFAULT_API_VERSION,
    source: str = "",
    section: str = "",
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    comment = _require_body(body)
    version = _normalize_api_version(api_version)
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
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    if not isinstance(fields, dict) or not fields:
        raise JiraPostError("Jira update fields must be a non-empty JSON object.")
    version = _normalize_api_version(api_version)
    credentials = load_jira_credentials()
    endpoint = _issue_endpoint(credentials["jira_url"], ticket, version)
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    payload = fields if "fields" in fields else {"fields": fields}
    common = _jira_action_common(
        action="update-issue",
        ticket=ticket,
        endpoint=endpoint,
        credentials=credentials,
        verification=verification,
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
    api_version: str = DEFAULT_API_VERSION,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    ticket = _require_ticket(issue_key)
    path = Path(file_path).expanduser().resolve()
    if not path.is_file():
        raise JiraPostError(f"Attachment file was not found: {path}")
    version = _normalize_api_version(api_version)
    credentials = load_jira_credentials()
    endpoint = _attachments_endpoint(credentials["jira_url"], ticket, version)
    verification = verify_jira_access(
        ticket=ticket,
        credentials=credentials,
        api_version=version,
        transport=transport,
        timeout_seconds=timeout_seconds,
    )
    attachment = {"name": path.name, "path": str(path), "size_bytes": path.stat().st_size}
    common = _jira_action_common(
        action="attach-file",
        ticket=ticket,
        endpoint=endpoint,
        credentials=credentials,
        verification=verification,
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
        lines.extend(["", "Post to Jira?"])
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


def _require_ticket(issue_key: str) -> str:
    ticket = str(issue_key or "").strip()
    if not ticket:
        raise JiraPostError("Jira ticket key is required.")
    return ticket


def _api_base(base_url: str, api_version: str) -> str:
    return f"{base_url.rstrip('/')}/rest/api/{api_version}"


def _myself_endpoint(base_url: str, api_version: str) -> str:
    return f"{_api_base(base_url, api_version)}/myself"


def _issue_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_api_base(base_url, api_version)}/issue/{quote(issue_key, safe='')}"


def _comment_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_issue_endpoint(base_url, issue_key, api_version)}/comment"


def _attachments_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_issue_endpoint(base_url, issue_key, api_version)}/attachments"


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


def _request_json(
    method: str,
    endpoint: str,
    token: str,
    *,
    payload: dict[str, Any] | None = None,
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    request_data = data
    request_headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if payload is not None:
        request_data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    if headers:
        request_headers.update(headers)
    request = urllib_request.Request(endpoint, data=request_data, headers=request_headers, method=method)
    opener = transport or urllib_request.urlopen
    try:
        with opener(request, timeout=timeout_seconds) as response:
            response_body = response.read().decode("utf-8", errors="replace")
            http_status = int(getattr(response, "status", getattr(response, "code", 0)) or 0)
    except urllib_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise JiraPostError(f"Jira {method} failed with HTTP {exc.code}: {detail}") from exc
    except urllib_error.URLError as exc:
        raise JiraPostError(f"Jira {method} failed: {exc.reason}") from exc
    return {
        "status": "available" if 200 <= http_status < 300 else "failed",
        "http_status": http_status,
        "response": _parse_response(response_body),
    }


def _safe_request_json(
    method: str,
    endpoint: str,
    token: str,
    *,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    try:
        result = _request_json(
            method,
            endpoint,
            token,
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
        result["response"] = _response_summary(result.get("response"))
        return result
    except JiraPostError as exc:
        return {"status": "failed", "http_status": 0, "detail": str(exc)}


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
    credentials: dict[str, str],
    verification: dict[str, Any],
    body_preview: str = "",
    attachments: list[dict[str, Any]] | None = None,
    fields_preview: str = "",
    source: str = "",
    section: str = "",
) -> dict[str, Any]:
    return {
        "status": "skipped",
        "posted": False,
        "dry_run": True,
        "confirm_required": True,
        "ticket": ticket,
        "action": action,
        "endpoint": endpoint,
        "credential": redact_jira_credentials(credentials),
        "verification": verification,
        "confirmation": {
            "title": "Post to Jira?",
            "ticket": ticket,
            "action": action,
            "body_preview": body_preview,
            "attachments": attachments or [],
            "fields_preview": fields_preview,
            "endpoint": endpoint,
            "verified": [
                {"label": "PAT loaded", "status": "available"},
                {"label": "Connection successful", "status": verification.get("connection", {}).get("status", "unknown")},
                {"label": "Ticket exists", "status": verification.get("ticket", {}).get("status", "unknown")},
            ],
            "warning": "This is reversible only by another operator action.",
        },
        "guard": "No Jira request was sent. Re-run with --auto-confirm only after reviewing this preview.",
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
            "guard": "Jira action executed after explicit --auto-confirm.",
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


def _response_summary(response: Any) -> Any:
    if isinstance(response, list):
        return [_response_summary(item) for item in response]
    if not isinstance(response, dict):
        return response if response in ({}, None) else {}
    summary: dict[str, Any] = {}
    for key in ("id", "key", "self"):
        if key in response:
            summary[key] = response[key]
    fields = response.get("fields")
    if isinstance(fields, dict):
        if "summary" in fields:
            summary["summary"] = str(fields.get("summary") or "")
        status = fields.get("status")
        if isinstance(status, dict):
            summary["status_name"] = str(status.get("name") or "")
    if "filename" in response:
        summary["filename"] = response["filename"]
    if "size" in response:
        summary["size"] = response["size"]
    return summary

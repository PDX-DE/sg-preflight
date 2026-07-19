"""Jira JQL/search-endpoint building, GET request transport, and response parsing."""

from __future__ import annotations

import json
import re
from time import monotonic
from typing import Any, Callable
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote, urlencode

from sg_preflight.jira_client_credentials import (
    ConfigError,
    JiraPostError,
    _require_https,
    _unloaded_jira_credential,
    load_jira_credentials,
    redact_jira_credentials,
)


DEFAULT_API_VERSION = "2"
DEFAULT_JIRA_URL = "https://jira.cc.bmwgroup.net"
JIRA_PROFILE_TICKET_CACHE_SECONDS = 60.0
JIRA_PROFILE_TICKET_MAX_RESULTS = 8
JIRA_MY_TICKETS_CACHE_SECONDS = 60.0
JIRA_MY_TICKETS_MAX_RESULTS = 12
JIRA_MY_WEEKLY_TICKETS_MAX_RESULTS = 50
MY_TICKETS_UNAVAILABLE_SUMMARY = "My Tickets unavailable. Check local Jira setup before retrying."
JIRA_TICKETS_UNAVAILABLE_SUMMARY = "Jira tickets unavailable. Check local Jira setup before retrying."
_JIRA_PROFILE_TICKET_CACHE: dict[tuple[str, str, str, int], tuple[float, dict[str, Any]]] = {}
_JIRA_MY_TICKETS_CACHE: dict[tuple[str, str, int], tuple[float, dict[str, Any]]] = {}
_JIRA_MY_WEEKLY_TICKETS_CACHE: dict[tuple[str, str, str, int], tuple[float, dict[str, Any]]] = {}


Transport = Callable[[urllib_request.Request, int], Any]


def _jira_verification_not_run(ticket: str = "") -> dict[str, Any]:
    ticket_key = str(ticket or "").strip()
    return {
        "status": "not_run",
        "connection": {
            "status": "not_run",
            "http_status": 0,
            "detail": "Network confirmation was not provided.",
        },
        "ticket": {
            "status": "not_run",
            "http_status": 0,
            "detail": "Ticket verification was not requested." if not ticket_key else "Network confirmation was not provided.",
        },
    }


def jira_status(
    *,
    ticket: str = "",
    api_version: str = DEFAULT_API_VERSION,
    confirm_network: bool = False,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    if not confirm_network:
        return {
            "status": "preview",
            "connection_status": "not_run",
            "ticket_status": "not_run",
            "credential": _unloaded_jira_credential(),
            "verification": _jira_verification_not_run(ticket),
            "dry_run": True,
            "confirm_network_required": True,
            "network_confirmed": False,
            "guard": "No Jira credentials were loaded and no request was sent. Re-run with --confirm-network.",
            "is_approval": False,
        }
    try:
        credentials = load_jira_credentials()
    except ConfigError as exc:
        return {
            "status": "missing",
            "connection_status": "not_run",
            "ticket_status": "not_run",
            "credential": {"status": "missing", "remediation": str(exc)},
            "verification": _jira_verification_not_run(ticket),
            "dry_run": True,
            "confirm_network_required": False,
            "network_confirmed": True,
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
        "dry_run": True,
        "confirm_network_required": False,
        "network_confirmed": True,
        "guard": "Jira verification GET requests completed; no Jira write was sent.",
        "is_approval": False,
    }


def clear_jira_profile_ticket_cache() -> None:
    _JIRA_PROFILE_TICKET_CACHE.clear()


def clear_jira_my_tickets_cache() -> None:
    _JIRA_MY_TICKETS_CACHE.clear()
    _JIRA_MY_WEEKLY_TICKETS_CACHE.clear()


def build_profile_ticket_jql(profile_id: str) -> str:
    profile = _require_profile_id(profile_id)
    profile_lower = profile.lower()
    label_values = [profile]
    if profile_lower != profile:
        label_values.append(profile_lower)
    labels = ", ".join(_jql_quote(value) for value in label_values)
    needle = _jql_quote(profile)
    return (
        "project = IDCEVODEV AND statusCategory != Done AND "
        f"(summary ~ {needle} OR description ~ {needle} OR labels in ({labels})) "
        "ORDER BY updated DESC"
    )


def build_my_unresolved_ticket_jql() -> str:
    return "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC"


def _normalize_weekly_ticket_since(since: str) -> str:
    normalized = str(since or "startOfWeek").strip()
    if normalized.lower() == "startofweek":
        return "startOfWeek()"
    if re.fullmatch(r"-[1-9][0-9]*[dD]", normalized):
        return normalized.lower()
    raise ValueError("Weekly ticket --since must be startOfWeek or a relative day window like -7d.")


def build_my_weekly_ticket_jql(since: str = "startOfWeek") -> str:
    updated_window = _normalize_weekly_ticket_since(since)
    return f"assignee = currentUser() AND updated >= {updated_window} ORDER BY updated DESC"


def search_jira_profile_tickets(
    profile_id: str,
    *,
    api_version: str = DEFAULT_API_VERSION,
    max_results: int = JIRA_PROFILE_TICKET_MAX_RESULTS,
    cache_seconds: float = JIRA_PROFILE_TICKET_CACHE_SECONDS,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    profile = _require_profile_id(profile_id)
    version = _normalize_api_version(api_version)
    result_limit = max(1, min(int(max_results or JIRA_PROFILE_TICKET_MAX_RESULTS), 50))
    jql = build_profile_ticket_jql(profile)
    try:
        credentials = load_jira_credentials()
    except ConfigError as exc:
        return {
            "status": "missing",
            "profile_id": profile,
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": "Jira tickets unavailable. Register operator-local Jira credentials before using this card.",
            "credential": {"status": "missing", "remediation": str(exc)},
            "settings_hint": "Run sgfx-preflight.exe jira register from the operator machine.",
            "cache_status": "skipped",
            "read_only": True,
            "is_approval": False,
        }

    cache_key = (str(credentials.get("jira_url", "")), version, profile, result_limit)
    now = monotonic()
    if transport is None and cache_seconds > 0:
        cached = _JIRA_PROFILE_TICKET_CACHE.get(cache_key)
        if cached and now < cached[0]:
            payload = _copy_profile_ticket_payload(cached[1])
            payload["cache_status"] = "hit"
            payload["cache_expires_in_seconds"] = max(0, int(cached[0] - now))
            return payload

    endpoint = _search_endpoint(credentials["jira_url"], version, jql, result_limit)
    try:
        response = _request_json(
            "GET",
            endpoint,
            credentials["pat"],
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except JiraPostError as exc:
        payload = {
            "status": "failed",
            "profile_id": profile,
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": JIRA_TICKETS_UNAVAILABLE_SUMMARY,
            "diagnostic_detail": f"Jira tickets unavailable: {exc}",
            "credential": redact_jira_credentials(credentials),
            "settings_hint": "Check Jira connection from the local setup page or run sgfx-preflight.exe jira status.",
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }
    else:
        tickets = _profile_ticket_rows(response.get("response"), credentials["jira_url"])
        payload = {
            "status": "available",
            "profile_id": profile,
            "jql": jql,
            "ticket_count": len(tickets),
            "tickets": tickets,
            "summary": (
                f"{len(tickets)} active Jira ticket(s) matched {profile}."
                if tickets
                else f"No active Jira tickets matched {profile}."
            ),
            "credential": redact_jira_credentials(credentials),
            "http_status": response.get("http_status", 0),
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }

    if transport is None and cache_seconds > 0:
        expires_at = now + float(cache_seconds)
        _JIRA_PROFILE_TICKET_CACHE[cache_key] = (expires_at, _copy_profile_ticket_payload(payload))
        payload["cache_expires_in_seconds"] = int(cache_seconds)
    return payload


def search_my_unresolved_tickets(
    *,
    api_version: str = DEFAULT_API_VERSION,
    max_results: int = JIRA_MY_TICKETS_MAX_RESULTS,
    cache_seconds: float = JIRA_MY_TICKETS_CACHE_SECONDS,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    version = _normalize_api_version(api_version)
    result_limit = max(1, min(int(max_results or JIRA_MY_TICKETS_MAX_RESULTS), 50))
    jql = build_my_unresolved_ticket_jql()
    try:
        credentials = load_jira_credentials()
    except ConfigError as exc:
        return {
            "status": "missing",
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": "My Tickets unavailable. Register operator-local Jira credentials before using this page.",
            "credential": {"status": "missing", "remediation": str(exc)},
            "settings_hint": "Run sgfx-preflight.exe jira register from the operator machine.",
            "cache_status": "skipped",
            "read_only": True,
            "is_approval": False,
        }

    cache_key = (str(credentials.get("jira_url", "")), version, result_limit)
    now = monotonic()
    if transport is None and cache_seconds > 0:
        cached = _JIRA_MY_TICKETS_CACHE.get(cache_key)
        if cached and now < cached[0]:
            payload = _copy_profile_ticket_payload(cached[1])
            payload["cache_status"] = "hit"
            payload["cache_expires_in_seconds"] = max(0, int(cached[0] - now))
            return payload

    endpoint = _search_endpoint(
        credentials["jira_url"],
        version,
        jql,
        result_limit,
        fields="summary,status,priority,updated,project,assignee",
    )
    try:
        response = _request_json(
            "GET",
            endpoint,
            credentials["pat"],
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except JiraPostError as exc:
        payload = {
            "status": "failed",
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": MY_TICKETS_UNAVAILABLE_SUMMARY,
            "diagnostic_detail": f"My Tickets unavailable: {exc}",
            "credential": redact_jira_credentials(credentials),
            "settings_hint": "Check Jira connection from the local setup page or run sgfx-preflight.exe jira status.",
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }
    else:
        tickets = _my_ticket_rows(response.get("response"), credentials["jira_url"])
        payload = {
            "status": "available",
            "jql": jql,
            "ticket_count": len(tickets),
            "tickets": tickets,
            "summary": (
                f"{len(tickets)} assigned unresolved Jira ticket(s) loaded."
                if tickets
                else "No assigned unresolved Jira tickets found."
            ),
            "credential": redact_jira_credentials(credentials),
            "http_status": response.get("http_status", 0),
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }

    if transport is None and cache_seconds > 0:
        expires_at = now + float(cache_seconds)
        _JIRA_MY_TICKETS_CACHE[cache_key] = (expires_at, _copy_profile_ticket_payload(payload))
        payload["cache_expires_in_seconds"] = int(cache_seconds)
    return payload


def search_my_weekly_tickets(
    *,
    since: str = "startOfWeek",
    api_version: str = DEFAULT_API_VERSION,
    max_results: int = JIRA_MY_WEEKLY_TICKETS_MAX_RESULTS,
    cache_seconds: float = JIRA_MY_TICKETS_CACHE_SECONDS,
    confirm_network: bool = False,
    transport: Transport | None = None,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    preview_result_limit = min(max(1, int(max_results)), 50)
    jql = build_my_weekly_ticket_jql(since)
    if not confirm_network:
        return {
            "status": "not_run",
            "connection_status": "not_run",
            "credential": _unloaded_jira_credential(),
            "verification": _jira_verification_not_run(),
            "network_confirmed": False,
            "confirm_network_required": True,
            "dry_run": True,
            "ticket_count": 0,
            "cache_status": "skipped",
            "tickets": [],
            "jql": jql,
            "total_available": None,
            "result_limit": preview_result_limit,
            "read_only": True,
            "is_approval": False,
            "summary": "Jira lookup not run. Add --confirm-network to include assigned tickets.",
        }

    version = _normalize_api_version(api_version)
    result_limit = max(1, min(int(max_results or JIRA_MY_WEEKLY_TICKETS_MAX_RESULTS), 50))
    try:
        credentials = load_jira_credentials()
    except ConfigError as exc:
        return {
            "status": "missing",
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": "Weekly Tickets unavailable. Register operator-local Jira credentials before using this draft.",
            "credential": {"status": "missing", "remediation": str(exc)},
            "verification": _jira_verification_not_run(),
            "connection_status": "not_run",
            "network_confirmed": True,
            "confirm_network_required": False,
            "dry_run": True,
            "total_available": None,
            "result_limit": result_limit,
            "settings_hint": (
                "Run sgfx-preflight.exe integration jira register --confirm-local-write from the operator machine."
            ),
            "cache_status": "skipped",
            "read_only": True,
            "is_approval": False,
        }

    cache_key = (str(credentials.get("jira_url", "")), version, _normalize_weekly_ticket_since(since), result_limit)
    now = monotonic()
    if transport is None and cache_seconds > 0:
        cached = _JIRA_MY_WEEKLY_TICKETS_CACHE.get(cache_key)
        if cached and now < cached[0]:
            payload = _copy_profile_ticket_payload(cached[1])
            payload["cache_status"] = "hit"
            payload["cache_expires_in_seconds"] = max(0, int(cached[0] - now))
            return payload

    endpoint = _search_endpoint(
        credentials["jira_url"],
        version,
        jql,
        result_limit,
        fields="summary,status,priority,updated,project,assignee",
    )
    try:
        response = _request_json(
            "GET",
            endpoint,
            credentials["pat"],
            transport=transport,
            timeout_seconds=timeout_seconds,
        )
    except JiraPostError as exc:
        payload = {
            "status": "failed",
            "jql": jql,
            "ticket_count": 0,
            "tickets": [],
            "summary": "Weekly Tickets unavailable: couldn't reach Jira this time.",
            "detail": _preview(str(exc), limit=200),
            "credential": redact_jira_credentials(credentials),
            "verification": {
                "status": "failed",
                "connection": {
                    "status": "failed",
                    "http_status": 0,
                    "detail": "Jira weekly ticket GET failed.",
                },
                "ticket": {
                    "status": "not_run",
                    "http_status": 0,
                    "detail": "Ticket verification was not requested.",
                },
            },
            "connection_status": "failed",
            "network_confirmed": True,
            "confirm_network_required": False,
            "dry_run": True,
            "total_available": None,
            "result_limit": result_limit,
            "settings_hint": (
                "Run sgfx-preflight.exe integration jira status --confirm-network from the operator machine."
            ),
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }
    else:
        body = response.get("response")
        tickets = _my_ticket_rows(body, credentials["jira_url"])
        total_available = _jira_total_available(body)
        payload = {
            "status": "available",
            "jql": jql,
            "ticket_count": len(tickets),
            "total_available": total_available,
            "result_limit": result_limit,
            "tickets": tickets,
            "summary": (
                f"{len(tickets)} assigned Jira ticket(s) updated in the selected week loaded."
                if tickets
                else "No assigned Jira tickets were updated in the selected week."
            ),
            "credential": redact_jira_credentials(credentials),
            "verification": {
                "status": "available",
                "connection": {
                    "status": "available",
                    "http_status": response.get("http_status", 0),
                    "detail": "Jira weekly ticket GET completed.",
                },
                "ticket": {
                    "status": "not_run",
                    "http_status": 0,
                    "detail": "Ticket verification was not requested.",
                },
            },
            "connection_status": "available",
            "network_confirmed": True,
            "confirm_network_required": False,
            "dry_run": True,
            "http_status": response.get("http_status", 0),
            "cache_status": "miss",
            "read_only": True,
            "is_approval": False,
        }

    if transport is None and cache_seconds > 0:
        expires_at = now + float(cache_seconds)
        _JIRA_MY_WEEKLY_TICKETS_CACHE[cache_key] = (expires_at, _copy_profile_ticket_payload(payload))
        payload["cache_expires_in_seconds"] = int(cache_seconds)
    return payload


def _jira_total_available(response: Any) -> int | None:
    if not isinstance(response, dict):
        return None
    value = response.get("total")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


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


def _require_profile_id(profile_id: str) -> str:
    profile = str(profile_id or "").strip().upper()
    if not profile or not re.fullmatch(r"[A-Z0-9_-]+", profile):
        raise JiraPostError("Profile id is required for Jira ticket search.")
    return profile


def _jql_quote(value: str) -> str:
    escaped = str(value or "").replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _api_base(base_url: str, api_version: str) -> str:
    return f"{_require_https(base_url)}/rest/api/{api_version}"


def _myself_endpoint(base_url: str, api_version: str) -> str:
    return f"{_api_base(base_url, api_version)}/myself"


def _issue_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_api_base(base_url, api_version)}/issue/{quote(issue_key, safe='')}"


def _comment_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_issue_endpoint(base_url, issue_key, api_version)}/comment"


def _search_endpoint(
    base_url: str,
    api_version: str,
    jql: str,
    max_results: int,
    *,
    fields: str = "summary,status,labels,updated",
) -> str:
    query = urlencode(
        {
            "jql": jql,
            "maxResults": str(max_results),
            "fields": fields,
        }
    )
    return f"{_api_base(base_url, api_version)}/search?{query}"


def _attachments_endpoint(base_url: str, issue_key: str, api_version: str) -> str:
    return f"{_issue_endpoint(base_url, issue_key, api_version)}/attachments"


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


def _normalize_api_version(api_version: str) -> str:
    version = str(api_version or DEFAULT_API_VERSION).strip()
    if version not in {"2", "3"}:
        raise JiraPostError("Jira API version must be 2 or 3.")
    return version


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


def _copy_profile_ticket_payload(payload: dict[str, Any]) -> dict[str, Any]:
    copied = dict(payload)
    copied["tickets"] = [dict(item) for item in payload.get("tickets", []) if isinstance(item, dict)]
    credential = payload.get("credential")
    if isinstance(credential, dict):
        copied["credential"] = dict(credential)
    return copied


def _profile_ticket_rows(response: Any, base_url: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    issues = response.get("issues", [])
    if not isinstance(issues, list):
        return []
    rows: list[dict[str, Any]] = []
    browse_base = str(base_url or DEFAULT_JIRA_URL).rstrip("/")
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key", "") or "").strip().upper()
        if not key:
            continue
        fields = issue.get("fields", {}) if isinstance(issue.get("fields"), dict) else {}
        status = fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}
        labels = fields.get("labels", [])
        if not isinstance(labels, list):
            labels = []
        rows.append(
            {
                "key": key,
                "summary": _preview(str(fields.get("summary", "") or ""), limit=120),
                "status": str(status.get("name", "") or "unknown"),
                "labels": [str(label) for label in labels if str(label).strip()],
                "updated": str(fields.get("updated", "") or ""),
                "url": f"{browse_base}/browse/{quote(key, safe='')}",
            }
        )
    return rows


def _my_ticket_rows(response: Any, base_url: str) -> list[dict[str, Any]]:
    if not isinstance(response, dict):
        return []
    issues = response.get("issues", [])
    if not isinstance(issues, list):
        return []
    rows: list[dict[str, Any]] = []
    browse_base = str(base_url or DEFAULT_JIRA_URL).rstrip("/")
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        key = str(issue.get("key", "") or "").strip().upper()
        if not key:
            continue
        fields = issue.get("fields", {}) if isinstance(issue.get("fields"), dict) else {}
        status = fields.get("status", {}) if isinstance(fields.get("status"), dict) else {}
        status_category = (
            status.get("statusCategory", {}) if isinstance(status.get("statusCategory"), dict) else {}
        )
        priority = fields.get("priority", {}) if isinstance(fields.get("priority"), dict) else {}
        project = fields.get("project", {}) if isinstance(fields.get("project"), dict) else {}
        assignee = fields.get("assignee", {}) if isinstance(fields.get("assignee"), dict) else {}
        rows.append(
            {
                "key": key,
                "summary": _preview(str(fields.get("summary", "") or ""), limit=140),
                "status": str(status.get("name", "") or "unknown"),
                "status_category": str(status_category.get("name", "") or status_category.get("key", "") or ""),
                "priority": str(priority.get("name", "") or ""),
                "project": str(project.get("key", "") or project.get("name", "") or ""),
                "assignee": str(assignee.get("displayName", "") or assignee.get("name", "") or ""),
                "updated": str(fields.get("updated", "") or ""),
                "url": f"{browse_base}/browse/{quote(key, safe='')}",
            }
        )
    return rows

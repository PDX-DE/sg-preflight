"""Opt-in, confirmation-gated Jira REST client for reading and posting tickets
against the BMW Jira instance.

The implementation is split by responsibility into jira_client_credentials.py
(PAT storage, keychain access, redaction), jira_client_search.py (JQL/search
endpoint building, GET transport, response parsing), jira_client_actions.py
(write/verification actions and their confirmation gates), and
jira_client_render.py (text/markdown rendering of post and action payloads).
This module is the explicit-import facade over those four: every name this
module used to define at top level is re-exported here unchanged so existing
`from sg_preflight.jira_client import ...` call sites and `mock.patch(
"sg_preflight.jira_client...."` targets keep working.
"""

from __future__ import annotations

from urllib import request as urllib_request

from sg_preflight.jira_client_credentials import (
    ConfigError,
    JIRA_CREDENTIALS_FILENAME,
    JIRA_KEYRING_SERVICE,
    JIRA_OPERATOR_STATE_ENV,
    JiraPostError,
    _LEGACY_PAT_FIELDS,
    _LOG,
    _delete_jira_pat_from_keyring,
    _display_operator_path,
    _jira_keyring_account,
    _keyring_module,
    _legacy_pat_from_payload,
    _load_jira_pat_from_keyring,
    _migrate_legacy_jira_pat,
    _require_https,
    _store_jira_pat_in_keyring,
    _unloaded_jira_credential,
    _write_jira_url_config,
    default_jira_credentials_path,
    jira_credentials_candidate_paths,
    load_jira_credentials,
    redact_jira_credentials,
    write_jira_credentials,
)
from sg_preflight.jira_client_search import (
    DEFAULT_API_VERSION,
    DEFAULT_JIRA_URL,
    JIRA_MY_TICKETS_CACHE_SECONDS,
    JIRA_MY_TICKETS_MAX_RESULTS,
    JIRA_MY_WEEKLY_TICKETS_MAX_RESULTS,
    JIRA_PROFILE_TICKET_CACHE_SECONDS,
    JIRA_PROFILE_TICKET_MAX_RESULTS,
    JIRA_TICKETS_UNAVAILABLE_SUMMARY,
    MY_TICKETS_UNAVAILABLE_SUMMARY,
    Transport,
    _JIRA_MY_TICKETS_CACHE,
    _JIRA_MY_WEEKLY_TICKETS_CACHE,
    _JIRA_PROFILE_TICKET_CACHE,
    _api_base,
    _attachments_endpoint,
    _comment_endpoint,
    _copy_profile_ticket_payload,
    _issue_endpoint,
    _jira_total_available,
    _jira_verification_not_run,
    _jql_quote,
    _my_ticket_rows,
    _myself_endpoint,
    _normalize_api_version,
    _normalize_weekly_ticket_since,
    _parse_response,
    _preview,
    _profile_ticket_rows,
    _request_json,
    _require_profile_id,
    _response_summary,
    _safe_request_json,
    _search_endpoint,
    build_my_unresolved_ticket_jql,
    build_my_weekly_ticket_jql,
    build_profile_ticket_jql,
    clear_jira_my_tickets_cache,
    clear_jira_profile_ticket_cache,
    jira_status,
    search_jira_profile_tickets,
    search_my_unresolved_tickets,
    search_my_weekly_tickets,
    verify_jira_access,
)
from sg_preflight.jira_client_actions import (
    DEFAULT_BASE_URL_ENV,
    DEFAULT_TOKEN_ENV,
    JIRA_POSTING_BANNER,
    JiraCommentSource,
    _comment_payload,
    _first_fenced_text,
    _jira_action_common,
    _multipart_attachment,
    _recorded_action_result,
    _require_available_verification,
    _require_body,
    _require_ticket,
    attach_jira_file_action,
    default_wording_file,
    extract_numbered_section_text,
    load_jira_comment_source,
    post_jira_comment,
    post_jira_comment_action,
    update_jira_issue_action,
)
from sg_preflight.jira_client_render import (
    render_jira_action_markdown,
    render_jira_action_text,
    render_jira_post_markdown,
    render_jira_post_text,
)

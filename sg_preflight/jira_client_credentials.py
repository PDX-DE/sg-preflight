"""Jira PAT credential storage, OS-keychain access, and redaction for logs/output."""

from __future__ import annotations

from functools import wraps
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable


def _sync_jira_globals(target_globals: dict[str, Any]) -> None:
    """Refresh names this module shares with the facade before a call runs.

    Sibling modules keep their own copies of every helper they import from
    each other (Python globals are per-module). A test that does
    `mock.patch.object(jira_client, "load_jira_credentials", ...)` only
    rebinds the facade's copy, so a moved function calling it as a bare name
    would silently miss the patch. Re-syncing the calling module's globals
    from the live facade right before the call keeps every existing
    `sg_preflight.jira_client.*` mock.patch target intercepting, exactly as
    it did when everything lived in one module.

    The sync is one-directional: patch at the facade, never at a sibling —
    a sibling-level patch of a facade-shared name is silently overwritten
    here the moment any wrapped function runs.
    """
    from sg_preflight import jira_client as _jira_facade

    for name in list(target_globals.keys()):
        if name.startswith("__"):
            continue
        if hasattr(_jira_facade, name):
            target_globals[name] = getattr(_jira_facade, name)


def _with_jira_globals(func: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(func)
    def _wrapper(*args: Any, **kwargs: Any) -> Any:
        _sync_jira_globals(func.__globals__)
        return func(*args, **kwargs)

    return _wrapper


JIRA_OPERATOR_STATE_ENV = "SGFX_OPERATOR_STATE_DIR"
JIRA_CREDENTIALS_FILENAME = "jira_pat.json"
JIRA_KEYRING_SERVICE = "sgfx-quality-hero-jira"
_LEGACY_PAT_FIELDS = ("pat", "pat_api_id", "token")
_LOG = logging.getLogger(__name__)


class JiraPostError(RuntimeError):
    """Raised when a Jira posting request cannot be prepared safely."""


class ConfigError(JiraPostError):
    """Raised when operator-local Jira credentials are missing or malformed."""


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


def _require_https(url: str) -> str:
    cleaned = str(url or "").strip().rstrip("/")
    if not cleaned.lower().startswith("https://"):
        raise ConfigError(
            "Jira URL must use HTTPS. Run `sgfx-preflight.exe integration jira register "
            "--jira-url https://... --confirm-local-write`."
        )
    return cleaned


def _jira_keyring_account(jira_url: str) -> str:
    return _require_https(jira_url)


def _keyring_module():
    try:
        import keyring  # type: ignore[import-not-found]
    except Exception as exc:  # pragma: no cover - explicit backend failure tests cover the public behavior
        raise ConfigError(
            "Jira PAT keychain is unavailable. Install/repair the Windows keyring backend; "
            "plaintext PAT storage is disabled."
        ) from exc
    return keyring


def _store_jira_pat_in_keyring(jira_url: str, token: str) -> None:
    keyring = _keyring_module()
    try:
        keyring.set_password(JIRA_KEYRING_SERVICE, _jira_keyring_account(jira_url), token)
    except Exception as exc:
        raise ConfigError("Jira PAT keychain is unavailable or locked; plaintext PAT storage is disabled.") from exc


def _load_jira_pat_from_keyring(jira_url: str) -> str:
    keyring = _keyring_module()
    try:
        token = keyring.get_password(JIRA_KEYRING_SERVICE, _jira_keyring_account(jira_url))
    except Exception as exc:
        raise ConfigError("Jira PAT keychain is unavailable or locked; cannot load Jira credentials.") from exc
    token_value = str(token or "").strip()
    if not token_value:
        raise ConfigError(
            "Jira PAT is missing from the OS keychain. Run "
            "`sgfx-preflight.exe integration jira register --confirm-local-write`."
        )
    return token_value


def _delete_jira_pat_from_keyring(jira_url: str) -> None:
    keyring = _keyring_module()
    try:
        keyring.delete_password(JIRA_KEYRING_SERVICE, _jira_keyring_account(jira_url))
    except Exception as exc:
        raise ConfigError("Jira PAT keychain is unavailable or locked; cannot delete Jira credentials.") from exc


def _legacy_pat_from_payload(payload: dict[str, Any]) -> str:
    for field in _LEGACY_PAT_FIELDS:
        token = str(payload.get(field, "") or "").strip()
        if token:
            return token
    return ""


def _write_jira_url_config(path: Path, jira_url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"jira_url": jira_url}, indent=2) + "\n", encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError as exc:
        _LOG.warning("Failed to restrict Jira URL config permissions at %s: %s", path, exc)


def _migrate_legacy_jira_pat(path: Path, payload: dict[str, Any], jira_url: str) -> str:
    legacy_token = _legacy_pat_from_payload(payload)
    if not legacy_token:
        return ""
    try:
        _store_jira_pat_in_keyring(jira_url, legacy_token)
    except ConfigError:
        _write_jira_url_config(path, jira_url)
        raise
    _write_jira_url_config(path, jira_url)
    _LOG.info("Migrated Jira PAT from plaintext config into OS keychain: %s", _display_operator_path(path))
    return legacy_token


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
        configured_url = str(payload.get("jira_url", "") or "").strip()
        if not configured_url:
            raise ConfigError(f"Jira credential file is missing jira_url: {path_label}")
        jira_url = _require_https(configured_url)
        pat = _legacy_pat_from_payload(payload)
        if not pat:
            pat = _load_jira_pat_from_keyring(jira_url)
        return {"jira_url": jira_url, "pat": pat, "path": str(path)}
    checked = ", ".join(_display_operator_path(path) for path in jira_credentials_candidate_paths())
    raise ConfigError(
        "Jira PAT is missing. Run `sgfx-preflight.exe integration jira register --confirm-local-write`; "
        "the URL config is stored at "
        f"{_display_operator_path(default_jira_credentials_path())} and the PAT is stored in the OS keychain. "
        f"Checked: {checked}"
    )


def write_jira_credentials(
    *,
    jira_url: str,
    pat: str,
    state_dir: Path | str | None = None,
    overwrite: bool = False,
) -> dict[str, Any]:
    raw_url = str(jira_url or "").strip()
    token = str(pat or "").strip()
    if not raw_url:
        raise ConfigError("Jira URL is required.")
    configured_url = _require_https(raw_url)
    if not token:
        raise ConfigError("Jira PAT is required.")
    path = default_jira_credentials_path(state_dir)
    if path.exists() and not overwrite:
        try:
            existing_payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing_payload = {}
        if isinstance(existing_payload, dict):
            existing_url = str(existing_payload.get("jira_url", "") or "").strip()
            if existing_url:
                _migrate_legacy_jira_pat(path, existing_payload, _require_https(existing_url))
        raise ConfigError(
            f"Jira credential file already exists: {_display_operator_path(path)}. Re-run with --force to replace it."
        )
    _store_jira_pat_in_keyring(configured_url, token)
    _write_jira_url_config(path, configured_url)
    credentials = {"jira_url": configured_url, "pat": token, "path": str(path)}
    return {
        "status": "recorded",
        "credential": redact_jira_credentials(credentials),
        "guard": "Jira URL config is operator-local; the PAT is stored in the OS keychain and must not be committed.",
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


def _unloaded_jira_credential() -> dict[str, Any]:
    return {
        "status": "not_loaded",
        "jira_url": "",
        "credential_path": "",
        "pat_length": 0,
        "pat_fingerprint": "",
        "pat_loaded": False,
    }


# Facade patch targets stay interceptable (see jira_client_credentials).
jira_credentials_candidate_paths = _with_jira_globals(jira_credentials_candidate_paths)
_display_operator_path = _with_jira_globals(_display_operator_path)
default_jira_credentials_path = _with_jira_globals(default_jira_credentials_path)
_require_https = _with_jira_globals(_require_https)
_jira_keyring_account = _with_jira_globals(_jira_keyring_account)
_keyring_module = _with_jira_globals(_keyring_module)
_store_jira_pat_in_keyring = _with_jira_globals(_store_jira_pat_in_keyring)
_load_jira_pat_from_keyring = _with_jira_globals(_load_jira_pat_from_keyring)
_delete_jira_pat_from_keyring = _with_jira_globals(_delete_jira_pat_from_keyring)
_legacy_pat_from_payload = _with_jira_globals(_legacy_pat_from_payload)
_write_jira_url_config = _with_jira_globals(_write_jira_url_config)
_migrate_legacy_jira_pat = _with_jira_globals(_migrate_legacy_jira_pat)
load_jira_credentials = _with_jira_globals(load_jira_credentials)
write_jira_credentials = _with_jira_globals(write_jira_credentials)
redact_jira_credentials = _with_jira_globals(redact_jira_credentials)
_unloaded_jira_credential = _with_jira_globals(_unloaded_jira_credential)

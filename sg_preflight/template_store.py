from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shlex
from typing import Any


TEMPLATE_BANNER = (
    "Templates are operator-local saved command configurations. "
    "SGFX does not share templates between operators or post them anywhere."
)

_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class TemplateStoreError(ValueError):
    """Raised when an operator-local template cannot be read or written safely."""


def template_store_dir(workspace: Path | str) -> Path:
    return Path(workspace).resolve() / "templates"


def template_path(workspace: Path | str, name: str) -> Path:
    return template_store_dir(workspace) / f"{_validate_name(name)}.json"


def parse_template_args(value: str) -> list[str]:
    text = str(value or "").strip()
    if not text:
        return []
    try:
        return [_strip_matching_quotes(item) for item in shlex.split(text, posix=False)]
    except ValueError as exc:
        raise TemplateStoreError(f"Could not parse template args: {exc}") from exc


def save_template(
    workspace: Path | str,
    name: str,
    *,
    command: str,
    args: tuple[str, ...] | list[str] = (),
    description: str = "",
    replace: bool = False,
) -> dict[str, Any]:
    safe_name = _validate_name(name)
    safe_command = _validate_command(command)
    safe_args = [str(item) for item in args]
    path = template_path(workspace, safe_name)
    if path.exists() and not replace:
        raise TemplateStoreError(f"Template '{safe_name}' already exists; use --replace to overwrite it")
    now = _utc_now()
    created_at = now
    if path.exists():
        try:
            created_at = str(load_template(workspace, safe_name).get("created_at") or now)
        except TemplateStoreError:
            created_at = now
    payload = {
        "name": safe_name,
        "command": safe_command,
        "args": safe_args,
        "description": str(description or ""),
        "created_at": created_at,
        "updated_at": now,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return payload


def load_template(workspace: Path | str, name: str) -> dict[str, Any]:
    safe_name = _validate_name(name)
    path = template_path(workspace, safe_name)
    if not path.exists():
        raise TemplateStoreError(f"Template '{safe_name}' was not found")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise TemplateStoreError(f"Malformed template '{safe_name}': {exc}") from exc
    return _validate_payload(raw, safe_name)


def list_templates(workspace: Path | str) -> list[dict[str, Any]]:
    root = template_store_dir(workspace)
    if not root.exists():
        return []
    templates = [load_template(workspace, item.stem) for item in root.glob("*.json")]
    return sorted(templates, key=lambda item: str(item["name"]).lower())


def delete_template(workspace: Path | str, name: str) -> dict[str, Any]:
    safe_name = _validate_name(name)
    payload = load_template(workspace, safe_name)
    template_path(workspace, safe_name).unlink()
    return payload


def template_cli_args(template: dict[str, Any], *, args_override: str = "") -> list[str]:
    payload = _validate_payload(template, str(template.get("name") or "template"))
    args = parse_template_args(args_override) if str(args_override or "").strip() else list(payload["args"])
    return [str(payload["command"]), *args]


def _validate_name(name: str) -> str:
    safe_name = str(name or "").strip()
    if not _SAFE_NAME.match(safe_name):
        raise TemplateStoreError(
            "Template name must start with a letter or number and contain only letters, numbers, '.', '_', or '-'"
        )
    return safe_name


def _validate_command(command: str) -> str:
    safe_command = str(command or "").strip()
    if not safe_command or any(char.isspace() for char in safe_command):
        raise TemplateStoreError("Template command must be a single SGFX CLI command name")
    if safe_command == "run-action-worker":
        raise TemplateStoreError("Template command cannot target internal worker commands")
    return safe_command


def _validate_payload(raw: object, expected_name: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise TemplateStoreError(f"Malformed template '{expected_name}': expected JSON object")
    name = raw.get("name")
    command = raw.get("command")
    args = raw.get("args")
    description = raw.get("description", "")
    created_at = raw.get("created_at")
    updated_at = raw.get("updated_at")
    if name != expected_name:
        raise TemplateStoreError(f"Malformed template '{expected_name}': name does not match file")
    if not isinstance(command, str) or not command.strip():
        raise TemplateStoreError(f"Malformed template '{expected_name}': command must be a string")
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise TemplateStoreError(f"Malformed template '{expected_name}': args must be a list of strings")
    if not isinstance(description, str):
        raise TemplateStoreError(f"Malformed template '{expected_name}': description must be a string")
    if not isinstance(created_at, str) or not isinstance(updated_at, str):
        raise TemplateStoreError(f"Malformed template '{expected_name}': timestamps must be strings")
    return {
        "name": _validate_name(name),
        "command": _validate_command(command),
        "args": list(args),
        "description": description,
        "created_at": created_at,
        "updated_at": updated_at,
    }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _strip_matching_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value

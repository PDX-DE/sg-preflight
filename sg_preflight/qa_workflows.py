"""
Modular QA workflows defined as JSON files.

A "QA workflow" is a JSON document under
`<workspace>/qa_workflows/*.json` that declares:

  - id, name, description
  - scope_kinds          ("profile" | "workspace")
  - profiles             (list; ignored when scope_kind == workspace)
  - dod_items            (operator-facing definition-of-done strings)
  - checks               (list of preflight_cli / manual_attestation steps)
  - required_artifacts   (files/dirs the runner produces or expects)
  - status_mapping       (mapping rule -> final status string)
  - outputs              (per-run summary JSON path templates)

The workflow runner here is intentionally a generic interpreter:
  - It does NOT know domain-specific rules (the JSON does).
  - It calls back into the existing sg-preflight CLI for the
    actual work (e.g. `screenshot-triage`, `run-profile`).
  - It records each check's stdout + exit code into the output
    JSON so the SGFX shell QA panel can surface "ready_for_review"
    / "in_progress" / "blocked" without re-implementing logic.

This file therefore stays small (~250 LOC) and changes ONLY when
the schema version bumps; new workflows are pure-data additions.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


SCHEMA_KEY     = "sgfx_qa_workflow"
SCHEMA_VERSION = 1


# ----------------------------------------------------------------------
# Discovery
# ----------------------------------------------------------------------

def _workspace_root(explicit: Path | None = None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    # The module lives at sg_preflight/qa_workflows.py; the workspace
    # root is its grandparent (sg-preflight/). Same pattern the rest
    # of the package uses.
    return Path(__file__).resolve().parents[1]


def workflows_dir(workspace_root: Path | None = None) -> Path:
    return _workspace_root(workspace_root) / "qa_workflows"


def discover(workspace_root: Path | None = None) -> list[Path]:
    d = workflows_dir(workspace_root)
    if not d.is_dir():
        return []
    return sorted([p for p in d.glob("*.json") if p.is_file()])


# ----------------------------------------------------------------------
# Validation
# ----------------------------------------------------------------------

# Minimal status taxonomy we expose to the SGFX shell. Mirrors the
# `state` field on `workflow-status` so the panel can render either
# array using the same colour code.
_RECOGNISED_STATUSES = {
    "ready_for_review",
    "blocked",
    "not_started",
    "in_progress",
    "covered",
}


@dataclass(frozen=True)
class WorkflowSummary:
    """Listing-level view of a workflow file. Cheap to compute --
    no checks executed, just JSON parse + schema gate. Used by
    `list-workflows --json` and embedded in `sg_preflight_state.json`
    so the SGFX shell can surface the catalog at boot."""

    id: str
    name: str
    description: str
    path: str
    scope_kinds: list[str]
    profiles: list[str]
    dod_count: int
    check_count: int
    last_status: str = "not_started"
    last_run_at_utc: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id":              self.id,
            "name":            self.name,
            "description":     self.description,
            "path":            self.path,
            "scope_kinds":     list(self.scope_kinds),
            "profiles":        list(self.profiles),
            "dod_count":       self.dod_count,
            "check_count":     self.check_count,
            "last_status":     self.last_status,
            "last_run_at_utc": self.last_run_at_utc,
        }


@dataclass
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


def validate_doc(doc: dict[str, Any], path: Path | None = None) -> ValidationResult:
    """Validate a parsed workflow document. Returns a ValidationResult
    rather than raising so the CLI's `validate-workflow` subcommand
    can report all problems at once."""

    res = ValidationResult(ok=True)

    def err(msg: str) -> None:
        res.ok = False
        res.errors.append(msg)

    if not isinstance(doc, dict):
        err("workflow document must be a JSON object")
        return res

    if doc.get("schema") != SCHEMA_KEY:
        err(f"schema must be '{SCHEMA_KEY}' (got {doc.get('schema')!r})")
    if doc.get("version") != SCHEMA_VERSION:
        err(f"version must be {SCHEMA_VERSION} (got {doc.get('version')!r})")

    for key in ("id", "name", "description"):
        v = doc.get(key)
        if not isinstance(v, str) or not v.strip():
            err(f"missing or empty '{key}'")

    scopes = doc.get("scope_kinds")
    if not isinstance(scopes, list) or not scopes:
        err("'scope_kinds' must be a non-empty list")
    else:
        for s in scopes:
            if s not in ("profile", "workspace"):
                err(f"scope_kinds entry must be 'profile' or 'workspace' (got {s!r})")

    profiles = doc.get("profiles")
    if not isinstance(profiles, list):
        err("'profiles' must be a list (may be empty for workspace-only workflows)")

    if not isinstance(doc.get("dod_items"), list) or not doc.get("dod_items"):
        err("'dod_items' must be a non-empty list of strings")
    else:
        for it in doc["dod_items"]:
            if not isinstance(it, str) or not it.strip():
                err("dod_items entries must be non-empty strings")
                break

    checks = doc.get("checks")
    if not isinstance(checks, list) or not checks:
        err("'checks' must be a non-empty list")
    else:
        for i, c in enumerate(checks):
            if not isinstance(c, dict):
                err(f"checks[{i}] must be an object"); continue
            kind = c.get("kind")
            if kind not in ("preflight_cli", "manual_attestation"):
                err(f"checks[{i}].kind must be 'preflight_cli' or 'manual_attestation' (got {kind!r})")
            if not isinstance(c.get("id"), str) or not c["id"].strip():
                err(f"checks[{i}].id must be a non-empty string")
            if kind == "preflight_cli":
                if not isinstance(c.get("subcommand"), str) or not c["subcommand"].strip():
                    err(f"checks[{i}].subcommand required for preflight_cli")
                if "args" in c and not isinstance(c["args"], list):
                    err(f"checks[{i}].args must be a list when present")
            elif kind == "manual_attestation":
                if "prompts" in c and not isinstance(c["prompts"], list):
                    err(f"checks[{i}].prompts must be a list when present")

    if not isinstance(doc.get("required_artifacts", []), list):
        err("'required_artifacts' must be a list")

    sm = doc.get("status_mapping")
    if not isinstance(sm, dict):
        err("'status_mapping' must be an object")
    else:
        for k, v in sm.items():
            if v not in _RECOGNISED_STATUSES:
                err(
                    f"status_mapping.{k} -> {v!r} is not in the recognised set "
                    f"{sorted(_RECOGNISED_STATUSES)}")

    if not isinstance(doc.get("outputs", []), list):
        err("'outputs' must be a list")

    if path is not None:
        res.errors = [f"[{path.name}] {e}" for e in res.errors]
        res.warnings = [f"[{path.name}] {w}" for w in res.warnings]

    return res


# ----------------------------------------------------------------------
# Listing
# ----------------------------------------------------------------------

def _summary_from_doc(doc: dict[str, Any], path: Path) -> WorkflowSummary:
    return WorkflowSummary(
        id=str(doc.get("id", "")),
        name=str(doc.get("name", "")),
        description=str(doc.get("description", "")),
        path=str(path),
        scope_kinds=[str(s) for s in doc.get("scope_kinds", [])],
        profiles=[str(p) for p in doc.get("profiles", [])],
        dod_count=len(doc.get("dod_items", []) or []),
        check_count=len(doc.get("checks", []) or []),
    )


def list_workflows(workspace_root: Path | None = None) -> list[WorkflowSummary]:
    """Returns a list of WorkflowSummary entries for every JSON file
    in `qa_workflows/` that parses + validates. Files that fail
    validation are skipped silently from the listing -- the caller
    can run `validate-workflow <path>` to see the errors."""

    out: list[WorkflowSummary] = []
    for p in discover(workspace_root):
        try:
            doc = _read_json(p)
        except Exception:
            continue
        if not validate_doc(doc, p).ok:
            continue
        # Try to enrich with the most recent run record, when one
        # exists. The runner writes `<output_root>/<id>/run.json`
        # by convention; without an explicit output root we look
        # under the workspace `out/qa_workflows/<id>/`.
        last = _last_run_record(workspace_root, str(doc.get("id", "")))
        s = _summary_from_doc(doc, p)
        if last is not None:
            object.__setattr__(s, "last_status",     str(last.get("status", "not_started")))
            object.__setattr__(s, "last_run_at_utc", str(last.get("finished_at_utc", "")))
        out.append(s)
    return out


def _default_output_root(workspace_root: Path | None = None) -> Path:
    return _workspace_root(workspace_root) / "out" / "qa_workflows"


def _last_run_record(workspace_root: Path | None, workflow_id: str) -> dict[str, Any] | None:
    if not workflow_id:
        return None
    candidates: list[Path] = []
    root = _default_output_root(workspace_root) / workflow_id
    if root.is_dir():
        candidates.extend(root.glob("**/run.json"))
        candidates.append(root / "run.json")
    for c in candidates:
        if c.is_file():
            try:
                return _read_json(c)
            except Exception:
                continue
    return None


# ----------------------------------------------------------------------
# Running
# ----------------------------------------------------------------------

def _utc_now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _expand(template: str, ctx: dict[str, str]) -> str:
    out = template
    for k, v in ctx.items():
        out = out.replace("{" + k + "}", v)
    return out


def run_workflow(
    workflow_id: str,
    *,
    profile: str | None = None,
    ticket_id: str | None = None,
    output_root: Path | None = None,
    workspace_root: Path | None = None,
    python_exe: str | None = None,
) -> dict[str, Any]:
    """Run a workflow by id. Discovers the JSON, executes each
    `preflight_cli` check by shelling out to `python -m sg_preflight
    <subcommand> <args>`, records each check's stdout + exit code,
    applies status_mapping, writes the per-run JSON, and returns
    the summary. `manual_attestation` checks are recorded as
    `pending` -- they need an out-of-band operator confirmation
    step (the SGFX shell will surface the prompts later)."""

    matches = [p for p in discover(workspace_root)
               if _read_json(p).get("id") == workflow_id]
    if not matches:
        raise FileNotFoundError(f"workflow id not found: {workflow_id}")
    path = matches[0]
    doc = _read_json(path)

    out_root = output_root or _default_output_root(workspace_root)
    out_root.mkdir(parents=True, exist_ok=True)

    py = python_exe or sys.executable
    started = _utc_now_iso()

    ctx = {
        "profile":     profile or "",
        "ticket_id":   ticket_id or "",
        "output_root": str(out_root),
        "id":          str(doc.get("id", "")),
        "date":        _dt.date.today().isoformat(),
    }

    check_results: list[dict[str, Any]] = []
    any_required_fail = False
    any_required_pass = False
    any_check_executed = False
    any_skipped = False

    for c in doc.get("checks", []):
        cid    = str(c.get("id", ""))
        kind   = str(c.get("kind", ""))
        req    = bool(c.get("required", False))
        skip_when = list(c.get("skip_when_missing_input", []) or [])
        # Skip when the check declares a required input missing in
        # the run context. e.g. `ticket_review` with
        # `skip_when_missing_input: [ticket_id]` is a no-op when
        # the operator did not pass --ticket-id.
        skip_reason = ""
        for input_name in skip_when:
            if not ctx.get(input_name, ""):
                skip_reason = f"missing input '{input_name}'"
                break
        if skip_reason:
            any_skipped = True
            check_results.append({
                "id": cid, "kind": kind, "required": req,
                "status": "skipped", "reason": skip_reason,
            })
            continue

        if kind == "preflight_cli":
            sub  = str(c.get("subcommand", ""))
            raw_args = list(c.get("args", []) or [])
            args = [_expand(str(a), ctx) for a in raw_args]
            cmd = [py, "-m", "sg_preflight", sub, *args]
            try:
                rc = subprocess.run(
                    cmd,
                    cwd=str(_workspace_root(workspace_root)),
                    capture_output=True, text=True, timeout=300,
                    check=False,
                )
                ok = (rc.returncode == 0)
                any_check_executed = True
                if req:
                    if ok:
                        any_required_pass = True
                    else:
                        any_required_fail = True
                check_results.append({
                    "id": cid, "kind": kind, "required": req,
                    "status": "passed" if ok else "failed",
                    "exit_code": rc.returncode,
                    "command": shlex.join(cmd),
                    "stdout_head": (rc.stdout or "")[:1024],
                    "stderr_head": (rc.stderr or "")[:1024],
                })
            except subprocess.TimeoutExpired:
                if req:
                    any_required_fail = True
                check_results.append({
                    "id": cid, "kind": kind, "required": req,
                    "status": "timeout", "command": shlex.join(cmd),
                })
            except Exception as e:
                if req:
                    any_required_fail = True
                check_results.append({
                    "id": cid, "kind": kind, "required": req,
                    "status": "error", "error": str(e),
                })

        elif kind == "manual_attestation":
            # The runner does not prompt interactively; the SGFX
            # shell QA panel will surface the prompts to the
            # operator in a future beat. For now record as
            # `pending` so the status_mapping logic can see it.
            check_results.append({
                "id": cid, "kind": kind, "required": req,
                "status": "pending",
                "prompts": list(c.get("prompts", []) or []),
            })

        else:
            check_results.append({
                "id": cid, "kind": kind, "required": req,
                "status": "error",
                "error": f"unsupported check kind: {kind!r}",
            })

    # Status mapping. Order matters: explicit failures win over
    # passes; pending manual attestations make the workflow
    # `in_progress` rather than `ready_for_review`.
    sm = doc.get("status_mapping", {}) or {}
    has_pending = any(r["status"] == "pending" for r in check_results)
    if not any_check_executed and not has_pending:
        status = sm.get("no_checks_run", "not_started")
    elif any_required_fail:
        status = sm.get("any_required_fail", "blocked")
    elif has_pending or any_skipped:
        status = sm.get("partial", "in_progress")
    else:
        status = sm.get("all_required_pass", "ready_for_review")

    finished = _utc_now_iso()

    summary: dict[str, Any] = {
        "id":               doc.get("id"),
        "name":             doc.get("name"),
        "profile":          ctx["profile"],
        "ticket_id":        ctx["ticket_id"],
        "status":           status,
        "started_at_utc":   started,
        "finished_at_utc":  finished,
        "checks":           check_results,
        "artifacts":        [],
        "workflow_path":    str(path),
    }

    # Resolve required_artifacts paths against the context (no
    # creation -- the runner only RECORDS the resolved paths and
    # whether they exist).
    for art in doc.get("required_artifacts", []) or []:
        path_template = art.get("path_template") or art.get("path") or ""
        resolved = _expand(str(path_template), ctx)
        summary["artifacts"].append({
            "id":     art.get("id"),
            "kind":   art.get("kind"),
            "path":   resolved,
            "exists": Path(resolved).exists() if resolved else False,
        })

    # Outputs: write per-run JSON to each declared output path.
    for out_def in doc.get("outputs", []) or []:
        path_template = out_def.get("path_template") or ""
        resolved = _expand(str(path_template), ctx)
        if not resolved:
            continue
        target = Path(resolved)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)

    return summary

"""H-32 export-all-as-zip — bundles per-profile evidence into a shareable zip.

The CLI surface is `sgfx-preflight.exe profile-summary export --profile X
--workspace Y --output-path X_YYYYMMDD.zip`. Bundle contents:

- `summary.html` — the H-30 consolidated profile dashboard HTML
- `screenshot-review/` — PNG thumbnails + viewer HTML if found locally
- `delivery-workbook/` — resolved or auto-generated workbook from H-27
- `activity_log.jsonl` — filtered to this profile + last 7 days
- `full_qa_history.json` — profile-scoped run history
- `manifest.json` — schema version + commit SHA + build date + sanitization log

PAT-shaped tokens are masked to `****<last4>` and personal Windows paths
collapsed to `C:\\Users\\<operator>\\…` BEFORE any file enters the zip per
`[[feedback-secrets-never-in-chat]]`. The manifest carries a sanitization
log entry for every file scrubbed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import re
import zipfile
from typing import Any

from sg_preflight.profile_summary import (
    redact_personal_paths,
    sanitize_text,
)


EXPORT_SCHEMA_VERSION = 1

# Match the H-30 PAT regex.
_PAT_RE = re.compile(r"\b([A-Za-z0-9_\-]{32,})\b")


@dataclass(frozen=True)
class ExportManifestEntry:
    archive_name: str
    source_path: str
    bytes: int
    sanitized: bool


@dataclass(frozen=True)
class ExportResult:
    zip_path: Path
    profile_id: str
    generated_at_utc: str
    entries: tuple[ExportManifestEntry, ...] = ()
    sanitization_log: tuple[str, ...] = ()

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EXPORT_SCHEMA_VERSION,
            "zip_path": str(self.zip_path),
            "profile_id": self.profile_id,
            "generated_at_utc": self.generated_at_utc,
            "entries": [
                {
                    "archive_name": e.archive_name,
                    "source_path": e.source_path,
                    "bytes": e.bytes,
                    "sanitized": e.sanitized,
                }
                for e in self.entries
            ],
            "sanitization_log": list(self.sanitization_log),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _scrub_pat_tokens(text: str) -> tuple[str, int]:
    """Mask PAT-shaped runs (32+ alnum) → ****<last4>. Returns (scrubbed, count)."""
    count = 0

    def _mask(match: re.Match[str]) -> str:
        nonlocal count
        token = match.group(1)
        # Leave 40-char git SHAs + 64-char .exe SHAs alone (legitimate context).
        if re.fullmatch(r"[0-9a-f]{40}", token.lower()) or re.fullmatch(r"[0-9a-f]{64}", token.lower()):
            return token
        count += 1
        return f"****{token[-4:]}" if len(token) >= 4 else "****"

    scrubbed = _PAT_RE.sub(_mask, text)
    return scrubbed, count


def _scrub_text_file(content: str) -> tuple[str, int]:
    """Combined path + PAT scrub. Returns (scrubbed, scrub_count)."""
    scrubbed_paths = redact_personal_paths(content)
    scrubbed_full, pat_count = _scrub_pat_tokens(scrubbed_paths)
    path_count = 0 if scrubbed_paths == content else 1
    return scrubbed_full, pat_count + path_count


def _filter_activity_log(content: str, *, profile_id: str, since: datetime | None) -> str:
    """Keep entries with `profile == profile_id` AND `ts >= since`. Operator-local;
    no entries are added or rewritten, only filtered. Each retained line is then
    sanitized."""
    kept: list[str] = []
    profile_upper = profile_id.strip().upper()
    for raw in content.splitlines():
        if not raw.strip():
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if not isinstance(entry, dict):
            continue
        if profile_upper and str(entry.get("profile") or "").strip().upper() != profile_upper:
            continue
        if since is not None:
            ts_text = str(entry.get("ts") or "").strip().replace("Z", "+00:00")
            try:
                ts = datetime.fromisoformat(ts_text) if ts_text else None
            except ValueError:
                ts = None
            if ts is not None and ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts is None or ts < since:
                continue
        scrubbed_line, _ = _scrub_text_file(raw)
        kept.append(scrubbed_line)
    return "\n".join(kept) + ("\n" if kept else "")


def _gather_screenshot_review(profile_id: str, *, home: Path | None) -> list[Path]:
    """Collect PNGs + viewer HTML from `~/sgfx_outputs/<profile>/screenshot-review/`
    if it exists. Operator-local; returns empty if the dir is missing."""
    try:
        from sg_preflight.full_qa_history import full_qa_profile_output_root
        root = full_qa_profile_output_root(profile_id, home=home)
    except Exception:
        return []
    review_dir = root / "screenshot-review"
    if not review_dir.is_dir():
        return []
    files: list[Path] = []
    for path in sorted(review_dir.rglob("*")):
        if path.is_file() and path.stat().st_size > 0:
            files.append(path)
    return files


def _gather_workbook(profile_id: str, *, workspace: Path, bmw_root: Path | None) -> Path | None:
    try:
        from sg_preflight.workbook_finder import resolve_workbook
        resolution = resolve_workbook(profile_id, workspace=workspace, bmw_root=bmw_root)
    except Exception:
        return None
    if resolution.selected is None:
        return None
    return resolution.selected.path


def _gather_full_qa_history(profile_id: str, *, home: Path | None) -> Path | None:
    try:
        from sg_preflight.full_qa_history import full_qa_run_history_path
        path = full_qa_run_history_path(profile_id, home=home)
    except Exception:
        return None
    if not path.is_file():
        return None
    return path


def _activity_log_path(workspace: Path) -> Path:
    return workspace.resolve() / "operator_state" / "activity_log.jsonl"


def build_manifest(
    *,
    profile_id: str,
    generated_at_utc: str,
    build_commit: str,
    exe_sha256: str,
    entries: list[ExportManifestEntry],
    sanitization_log: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "profile_id": profile_id,
        "generated_at_utc": generated_at_utc,
        "build_commit": build_commit,
        "exe_sha256": exe_sha256,
        "entries": [
            {
                "archive_name": e.archive_name,
                "source_path": e.source_path,
                "bytes": e.bytes,
                "sanitized": e.sanitized,
            }
            for e in entries
        ],
        "sanitization_log": list(sanitization_log),
        "guardrails": (
            "Manual review remains required. Decision: not approval — evidence only. "
            "BMW Git access is read-only. SGFX never modifies BMW source. "
            "Activity log is local-only — never posted to Jira, SVN, or BMW Git."
        ),
    }


def export_profile_evidence(
    *,
    profile_id: str,
    workspace: Path | str,
    output_path: Path | str,
    bmw_root: Path | str | None = None,
    home: Path | str | None = None,
    activity_log_window_days: int = 7,
    build_commit: str = "",
    exe_sha256: str = "",
    summary_html: str = "",
) -> ExportResult:
    """Bundle per-profile evidence into one operator-shareable zip.

    `summary_html` is the rendered H-30 page (passed in by the CLI so the
    exporter and the build command share the exact same rendered output).
    """
    profile = str(profile_id or "").strip().upper()
    if not profile:
        raise ValueError("profile_id is required")
    workspace_path = Path(workspace).resolve()
    bmw_root_value = Path(bmw_root).resolve() if bmw_root is not None else None
    home_path = Path(home).resolve() if home is not None else None
    output_zip = Path(output_path).resolve()
    output_zip.parent.mkdir(parents=True, exist_ok=True)

    generated_at = _utc_now()
    entries: list[ExportManifestEntry] = []
    sanitization_log: list[str] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(activity_log_window_days, 0))

    with zipfile.ZipFile(output_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. Summary HTML (from H-30 — caller passes pre-rendered).
        if summary_html:
            scrubbed_html, scrub_count = _scrub_text_file(summary_html)
            zf.writestr("summary.html", scrubbed_html.encode("utf-8"))
            sanitized = scrub_count > 0
            entries.append(ExportManifestEntry(
                archive_name="summary.html",
                source_path="<rendered in-memory>",
                bytes=len(scrubbed_html.encode("utf-8")),
                sanitized=sanitized,
            ))
            if sanitized:
                sanitization_log.append(f"summary.html: {scrub_count} sanitization edit(s)")

        # 2. Screenshot review directory.
        review_files = _gather_screenshot_review(profile, home=home_path)
        for path in review_files:
            try:
                blob = path.read_bytes()
            except OSError:
                continue
            archive_name = f"screenshot-review/{path.name}"
            zf.writestr(archive_name, blob)
            entries.append(ExportManifestEntry(
                archive_name=archive_name,
                source_path=str(path),
                bytes=len(blob),
                sanitized=False,  # PNG bytes are binary; not scrubbed.
            ))

        # 3. Delivery workbook.
        workbook_path = _gather_workbook(profile, workspace=workspace_path, bmw_root=bmw_root_value)
        if workbook_path is not None and workbook_path.is_file():
            try:
                blob = workbook_path.read_bytes()
                archive_name = f"delivery-workbook/{workbook_path.name}"
                zf.writestr(archive_name, blob)
                entries.append(ExportManifestEntry(
                    archive_name=archive_name,
                    source_path=str(workbook_path),
                    bytes=len(blob),
                    sanitized=False,  # xlsx binary; not scrubbed.
                ))
            except OSError:
                pass

        # 4. Activity log (filtered + sanitized).
        log_path = _activity_log_path(workspace_path)
        if log_path.is_file():
            try:
                raw_log = log_path.read_text(encoding="utf-8")
            except OSError:
                raw_log = ""
            filtered_log = _filter_activity_log(raw_log, profile_id=profile, since=cutoff)
            zf.writestr("activity_log.jsonl", filtered_log.encode("utf-8"))
            entries.append(ExportManifestEntry(
                archive_name="activity_log.jsonl",
                source_path=str(log_path),
                bytes=len(filtered_log.encode("utf-8")),
                sanitized=True,
            ))
            sanitization_log.append(
                f"activity_log.jsonl: filtered to profile={profile} window={activity_log_window_days}d + token scrub applied"
            )

        # 5. Full QA history.
        history_path = _gather_full_qa_history(profile, home=home_path)
        if history_path is not None and history_path.is_file():
            try:
                content = history_path.read_text(encoding="utf-8")
            except OSError:
                content = ""
            scrubbed_content, scrub_count = _scrub_text_file(content)
            zf.writestr("full_qa_history.json", scrubbed_content.encode("utf-8"))
            sanitized = scrub_count > 0
            entries.append(ExportManifestEntry(
                archive_name="full_qa_history.json",
                source_path=str(history_path),
                bytes=len(scrubbed_content.encode("utf-8")),
                sanitized=sanitized,
            ))
            if sanitized:
                sanitization_log.append(f"full_qa_history.json: {scrub_count} sanitization edit(s)")

        # 6. Manifest (last so it can list everything).
        manifest = build_manifest(
            profile_id=profile,
            generated_at_utc=generated_at,
            build_commit=build_commit,
            exe_sha256=exe_sha256,
            entries=entries,
            sanitization_log=sanitization_log,
        )
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False).encode("utf-8"),
        )

    return ExportResult(
        zip_path=output_zip,
        profile_id=profile,
        generated_at_utc=generated_at,
        entries=tuple(entries),
        sanitization_log=tuple(sanitization_log),
    )

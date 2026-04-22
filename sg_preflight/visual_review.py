from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any

from sg_preflight.profiles import DEFAULT_REFERENCE_REPO_ROOT, resolve_source_repo_root


_DEFAULT_PRIORITY_ORDER = (
    "default.png",
    "default_rear.png",
    "cameraView.png",
    "groundFloor.png",
    "groundFloor_with_reflection.png",
    "highlighting_Hood.png",
    "highlighting_Doors.png",
    "highlighting_Trunk.png",
    "highlighting_Tires.png",
    "lights_drl_front.png",
    "lights_drl_rear.png",
    "lights_LowBeam.png",
    "lights_HighBeam.png",
    "lights_rear.png",
)

_KEYWORD_ALIASES = {
    "animation": ("motion", "glow", "default"),
    "beam": ("beam", "lights", "front", "rear"),
    "bumper": ("default", "default_rear", "front", "rear"),
    "camera": ("camera",),
    "carpet": ("glow",),
    "door": ("doors", "door"),
    "doors": ("doors", "door"),
    "fog": ("fog", "lights"),
    "front": ("front", "default", "lights"),
    "fuel": ("fuel",),
    "glow": ("glow", "light", "lights"),
    "ground": ("ground", "reflection", "shadow"),
    "grill": ("front", "lights", "default"),
    "highlight": ("highlighting",),
    "hood": ("hood",),
    "iconic": ("glow", "light", "lights", "parking"),
    "indicator": ("indicator", "lights"),
    "indicators": ("indicator", "lights"),
    "light": ("lights", "drl", "beam", "rear", "front", "fog", "parking", "indicator", "position"),
    "lights": ("lights", "drl", "beam", "rear", "front", "fog", "parking", "indicator", "position"),
    "mapping": ("position", "parking", "glow", "light"),
    "parking": ("parking", "lights", "sensor"),
    "pivot": ("constants", "position", "mapping"),
    "position": ("position", "parking", "light"),
    "rear": ("rear", "default_rear", "lights"),
    "reflection": ("reflection", "ground"),
    "rim": ("rim", "wheel", "tire"),
    "seat": ("seat",),
    "seats": ("seat",),
    "sensor": ("sensor",),
    "shadow": ("shadow", "ground", "reflection"),
    "stage": ("default", "motion", "camera"),
    "staging": ("default", "motion", "camera"),
    "tire": ("tire", "wheel"),
    "trunk": ("trunk",),
    "welcomefx": ("glow", "motion", "lights"),
    "wheel": ("wheel", "tire", "rim"),
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "all",
    "too",
    "issue",
    "fixed",
    "added",
    "updated",
    "adjusted",
    "implementation",
    "where",
    "would",
    "into",
    "combined",
    "between",
    "from",
    "this",
    "that",
    "types",
    "type",
    "file",
    "files",
    "removed",
    "migrated",
    "need",
    "needs",
    "there",
    "latest",
}

_SVN_EXE_CANDIDATES = (
    Path(r"C:\Program Files\TortoiseSVN\bin\svn.exe"),
    Path(r"C:\Program Files\Subversion\bin\svn.exe"),
)


@dataclass(frozen=True)
class VisualReviewTask:
    key: str
    label: str
    state: str
    detail: str
    path: str = ""


@dataclass(frozen=True)
class VisualReviewPrep:
    profile_id: str
    project_root: str
    source_root: str
    source_mode: str
    generated_at_utc: str
    changelog_path: str = ""
    changelog_heading: str = ""
    changelog_focus_lines: tuple[str, ...] = ()
    project_readme_paths: tuple[str, ...] = ()
    screenshot_root: str = ""
    screenshot_count: int = 0
    screenshot_files: tuple[str, ...] = ()
    priority_screenshots: tuple[str, ...] = ()
    constants_readme_path: str = ""
    screenshot_test_config_path: str = ""
    raco_scene_path: str = ""
    blender_workfile_path: str = ""
    shared_root: str = ""
    shared_doc_paths: tuple[str, ...] = ()
    project_svn_info_lines: tuple[str, ...] = ()
    project_svn_log_lines: tuple[str, ...] = ()
    shared_svn_log_lines: tuple[str, ...] = ()
    delivery_tasks: tuple[VisualReviewTask, ...] = ()
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VisualReviewPrepBundle:
    prep: VisualReviewPrep
    json_path: Path
    markdown_path: Path
    html_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _resolve_repo_root(project_root: Path, repo_root: Path | None) -> Path:
    if repo_root is not None:
        return repo_root.resolve()

    for candidate in project_root.resolve().parents:
        if candidate.name.lower() == "trunk":
            return candidate
    return resolve_source_repo_root(Path(__file__).resolve().parents[1])


def _find_changelog(project_root: Path) -> Path:
    candidate = project_root / "CHANGELOG.md"
    if candidate.exists():
        return candidate
    return Path()


def _parse_latest_changelog(path: Path) -> tuple[str, tuple[str, ...]]:
    if not path.exists():
        return "", ()
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    heading = ""
    focus: list[str] = []
    active = False
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("## "):
            if active:
                break
            heading = line[3:].strip()
            active = True
            continue
        if not active:
            continue
        match = re.match(r"^[*-]\s+(.*)$", line)
        if match:
            focus.append(match.group(1).strip())
    return heading, tuple(focus[:10])


def _find_project_readmes(project_root: Path) -> tuple[str, ...]:
    matches = []
    for path in sorted(project_root.rglob("README*.md")):
        if any(part.lower() in {"_workfiles", "_workfiles"} for part in path.parts):
            continue
        matches.append(str(path))
    return tuple(matches[:10])


def _find_screenshot_root(project_root: Path) -> Path:
    candidate = project_root / "export" / "tests" / "expected"
    if candidate.exists():
        return candidate
    return Path()


def _find_constants_readme(profile_id: str, project_root: Path) -> Path:
    candidate = project_root / "_Common" / "constants" / f"README_constants_{profile_id}.md"
    if candidate.exists():
        return candidate
    constants_root = project_root / "_Common" / "constants"
    if constants_root.exists():
        matches = sorted(constants_root.glob("README*.md"))
        if matches:
            return matches[0]
    return Path()


def _find_test_config(project_root: Path) -> Path:
    candidate = project_root / "export" / "tests" / "test_config.lua"
    return candidate if candidate.exists() else Path()


def _find_representative_scene(profile_id: str, project_root: Path) -> Path:
    preferred = project_root / "main" / f"Main_{profile_id}.rca"
    if preferred.exists():
        return preferred
    main_root = project_root / "main"
    if main_root.exists():
        matches = sorted(main_root.glob("*.rca"))
        if matches:
            return matches[0]
    all_matches = sorted(project_root.rglob("*.rca"))
    return all_matches[0] if all_matches else Path()


def _find_representative_blend(project_root: Path) -> Path:
    workfiles_root = project_root / "_Workfiles"
    matches = sorted(workfiles_root.rglob("*.blend")) if workfiles_root.exists() else []
    if not matches:
        matches = sorted(project_root.rglob("*.blend"))
    if not matches:
        return Path()

    def score(path: Path) -> tuple[int, str]:
        name = path.name.lower()
        return (
            int("main" in name) + int("master" in name) + int("basis" in name),
            name,
        )

    return sorted(matches, key=score, reverse=True)[0]


def _priority_keywords(lines: tuple[str, ...]) -> list[str]:
    tokens: list[str] = []
    for line in lines:
        for token in re.findall(r"[a-z0-9_]+", line.lower()):
            if len(token) < 3 or token in _STOPWORDS:
                continue
            aliases = _KEYWORD_ALIASES.get(token)
            if aliases:
                tokens.extend(aliases)
            else:
                tokens.append(token)
    return tokens


def _priority_screenshots(screenshot_files: tuple[str, ...], keyword_lines: tuple[str, ...]) -> tuple[str, ...]:
    if not screenshot_files:
        return ()

    keyword_hits = _priority_keywords(keyword_lines)
    scored: list[tuple[int, str]] = []
    for name in screenshot_files:
        lowered = name.lower()
        score = 0
        for token in keyword_hits:
            if token and token in lowered:
                score += 1
        if score > 0:
            scored.append((score, name))

    if scored:
        ordered = [name for _, name in sorted(scored, key=lambda item: (-item[0], item[1].lower()))]
        seen: list[str] = []
        for name in ordered:
            if name not in seen:
                seen.append(name)
        return tuple(seen[:12])

    preferred: list[str] = []
    lowered_files = {name.lower(): name for name in screenshot_files}
    for name in _DEFAULT_PRIORITY_ORDER:
        found = lowered_files.get(name.lower())
        if found:
            preferred.append(found)
    if preferred:
        return tuple(preferred[:12])
    return tuple(screenshot_files[:12])


def _find_shared_root(project_root: Path) -> Path:
    brand_root = project_root.parent
    if not brand_root.exists():
        return Path()

    preferred_names = ("_Shared_IDCevo", "_Shared") if "Cars_IDCevo" in project_root.parts else ("_Shared", "_Shared_IDCevo")
    for name in preferred_names:
        candidate = brand_root / name
        if candidate.exists():
            return candidate

    matches = sorted(candidate for candidate in brand_root.glob("_Shared*") if candidate.is_dir())
    return matches[0] if matches else Path()


def _priority_doc_paths(paths: tuple[Path, ...], keyword_lines: tuple[str, ...], root: Path) -> tuple[str, ...]:
    if not paths:
        return ()

    keyword_hits = _priority_keywords(keyword_lines)
    scored: list[tuple[int, str, Path]] = []
    for path in paths:
        try:
            relative = str(path.relative_to(root)).replace("\\", "/")
        except ValueError:
            relative = path.name
        lowered = relative.lower()
        score = 0
        for token in keyword_hits:
            if token and token in lowered:
                score += 1
        if path.name.lower() == "changelog.md":
            score += 1
        scored.append((score, lowered, path))

    if any(score > 0 for score, _, _ in scored):
        ordered = [path for _, _, path in sorted(scored, key=lambda item: (-item[0], item[1]))]
    else:
        ordered = [path for _, _, path in sorted(scored, key=lambda item: item[1])]
    return tuple(str(path) for path in ordered[:12])


def _find_shared_docs(shared_root: Path, keyword_lines: tuple[str, ...]) -> tuple[str, ...]:
    if not shared_root.exists():
        return ()

    matches: list[Path] = []
    for path in sorted(shared_root.rglob("CHANGELOG.md")):
        matches.append(path)
    for path in sorted(shared_root.rglob("README*.md")):
        if path not in matches:
            matches.append(path)
    return _priority_doc_paths(tuple(matches), keyword_lines, shared_root)


def _svn_executable() -> Path | None:
    for command in ("svn.exe", "svn"):
        resolved = shutil.which(command)
        if resolved:
            return Path(resolved)
    for candidate in _SVN_EXE_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def _run_svn(args: list[str], target: Path) -> str:
    svn_executable = _svn_executable()
    if svn_executable is None or not target.exists():
        return ""
    try:
        completed = subprocess.run(
            [str(svn_executable), *args, str(target)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=18,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _svn_info_lines(target: Path) -> tuple[str, ...]:
    raw = _run_svn(["info"], target)
    if not raw:
        return ()
    wanted = ("URL", "Revision", "Last Changed Rev", "Last Changed Author", "Last Changed Date")
    mapping: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key in wanted and value:
            mapping[key] = value
    return tuple(f"{key}: {mapping[key]}" for key in wanted if key in mapping)


def _svn_log_lines(target: Path, *, limit: int = 8) -> tuple[str, ...]:
    raw = _run_svn(["log", "-l", str(limit)], target)
    if not raw:
        return ()

    lines: list[str] = []
    for chunk in re.split(r"-{20,}\r?\n", raw):
        chunk_lines = [line.rstrip() for line in chunk.splitlines()]
        content = [line for line in chunk_lines if line.strip()]
        if not content:
            continue
        header = content[0].strip()
        match = re.match(r"^(r\d+)\s+\|\s+([^|]+)\|\s+([^|]+)\|", header)
        if not match:
            continue
        revision = match.group(1).strip()
        author = match.group(2).strip()
        date = match.group(3).strip().split(" (", 1)[0]
        message_lines = [
            line.strip()
            for line in content[1:]
            if line.strip() and not re.fullmatch(r"\d+\s+line[s]?", line.strip())
        ]
        if message_lines:
            message = " ".join(message_lines[:2])
        else:
            message = "(no message)"
        lines.append(f"{revision} | {date} | {author} | {message}")
    return tuple(lines[:limit])


def _delivery_tasks(
    *,
    profile_id: str,
    project_root: Path,
    changelog_path: Path,
    project_readme_paths: tuple[str, ...],
    screenshot_root: Path,
    screenshot_count: int,
    raco_scene_path: Path,
    shared_root: Path,
    shared_doc_paths: tuple[str, ...],
    project_svn_log_lines: tuple[str, ...],
    shared_svn_log_lines: tuple[str, ...],
) -> tuple[VisualReviewTask, ...]:
    tasks = [
        VisualReviewTask(
            key="format_checker_svn",
            label="Format checker SVN",
            state="ready" if project_root.exists() else "blocked",
            detail=f"Use the repo-checker action on the live SVN path for {profile_id}: {project_root}",
            path=str(project_root) if project_root.exists() else "",
        ),
        VisualReviewTask(
            key="check_changelogs_cars_bmw",
            label="Check changelogs cars bmw",
            state="ready" if changelog_path.exists() or project_svn_log_lines else "blocked",
            detail=(
                f"Project changelog and {len(project_svn_log_lines)} recent SVN log entrie(s) are ready for review."
                if changelog_path.exists() or project_svn_log_lines
                else "No project changelog or SVN log data was found locally."
            ),
            path=str(changelog_path) if changelog_path.exists() else str(project_root),
        ),
        VisualReviewTask(
            key="check_readme_cars_bmw",
            label="Check readme cars bmw",
            state="ready" if project_readme_paths else "blocked",
            detail=(
                f"{len(project_readme_paths)} project README file(s) were found under the live car root."
                if project_readme_paths
                else "No car-local README file was found under the live project root."
            ),
            path=project_readme_paths[0] if project_readme_paths else "",
        ),
        VisualReviewTask(
            key="screenshot_tests_bmws",
            label="Screenshot tests bmws",
            state="ready" if screenshot_count > 0 else "blocked",
            detail=(
                f"{screenshot_count} screenshot baseline image(s) are available under export/tests/expected."
                if screenshot_count > 0
                else "No screenshot baseline folder was detected under export/tests/expected."
            ),
            path=str(screenshot_root) if screenshot_root.exists() else "",
        ),
        VisualReviewTask(
            key="asset_review_in_raco_bmws",
            label="Asset review in RaCo (bmws)",
            state="ready" if raco_scene_path.exists() else "blocked",
            detail=(
                "A representative `.rca` scene is ready for the manual asset review step."
                if raco_scene_path.exists()
                else "No representative `.rca` scene was found for the current car."
            ),
            path=str(raco_scene_path) if raco_scene_path.exists() else "",
        ),
        VisualReviewTask(
            key="check_readme_changelogs_cars_shared_bmw",
            label="Check readme/changelogs cars shared bmw",
            state="ready" if shared_doc_paths or shared_svn_log_lines else "blocked",
            detail=(
                f"Shared BMW root {shared_root.name} is present with {len(shared_doc_paths)} doc(s) and {len(shared_svn_log_lines)} recent SVN log entrie(s)."
                if shared_root.exists() and (shared_doc_paths or shared_svn_log_lines)
                else "No shared BMW README/CHANGELOG context was found locally."
            ),
            path=shared_doc_paths[0] if shared_doc_paths else str(shared_root) if shared_root.exists() else "",
        ),
    ]
    return tuple(tasks)


def build_visual_review_prep(
    profile_id: str,
    project_root: Path,
    *,
    repo_root: Path | None = None,
) -> VisualReviewPrep:
    resolved_project_root = project_root.resolve()
    resolved_repo_root = _resolve_repo_root(resolved_project_root, repo_root)
    changelog_path = _find_changelog(resolved_project_root)
    changelog_heading, changelog_focus_lines = _parse_latest_changelog(changelog_path)
    project_svn_info_lines = _svn_info_lines(resolved_project_root)
    project_svn_log_lines = _svn_log_lines(resolved_project_root)
    shared_root = _find_shared_root(resolved_project_root)
    shared_svn_log_lines = _svn_log_lines(shared_root) if shared_root.exists() else ()
    keyword_lines = changelog_focus_lines + project_svn_log_lines + shared_svn_log_lines
    project_readme_paths = _find_project_readmes(resolved_project_root)
    screenshot_root = _find_screenshot_root(resolved_project_root)
    screenshot_files = (
        tuple(
            path.name
            for path in sorted(screenshot_root.iterdir())
            if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        )
        if screenshot_root.exists()
        else ()
    )
    priority = _priority_screenshots(screenshot_files, keyword_lines or changelog_focus_lines)
    shared_doc_paths = _find_shared_docs(shared_root, keyword_lines) if shared_root.exists() else ()
    constants_readme = _find_constants_readme(profile_id, resolved_project_root)
    raco_scene = _find_representative_scene(profile_id, resolved_project_root)
    blender_workfile = _find_representative_blend(resolved_project_root)

    notes = [
        "This is local visual-review prep, not automated visual approval.",
        "The prep now reads the live Seriengrafik SVN checkout when it is available locally.",
        "Start from recent SVN log entries, then confirm the matching screenshot baselines and open the representative RaCo scene.",
    ]
    if priority:
        notes.append("Start with the priority screenshot shortlist before browsing the full baseline set.")
    if shared_doc_paths:
        notes.append("Shared BMW README and CHANGELOG files were prioritized from the latest shared SVN log context.")

    delivery_tasks = _delivery_tasks(
        profile_id=profile_id,
        project_root=resolved_project_root,
        changelog_path=changelog_path,
        project_readme_paths=project_readme_paths,
        screenshot_root=screenshot_root,
        screenshot_count=len(screenshot_files),
        raco_scene_path=raco_scene,
        shared_root=shared_root,
        shared_doc_paths=shared_doc_paths,
        project_svn_log_lines=project_svn_log_lines,
        shared_svn_log_lines=shared_svn_log_lines,
    )

    test_config = _find_test_config(resolved_project_root)

    return VisualReviewPrep(
        profile_id=profile_id,
        project_root=str(resolved_project_root),
        source_root=str(resolved_repo_root),
        source_mode="real_svn_checkout" if _is_within(resolved_project_root, DEFAULT_REFERENCE_REPO_ROOT) else "local_svn_mirror",
        generated_at_utc=_utc_now(),
        changelog_path=str(changelog_path) if changelog_path.exists() else "",
        changelog_heading=changelog_heading,
        changelog_focus_lines=changelog_focus_lines,
        project_readme_paths=project_readme_paths,
        screenshot_root=str(screenshot_root) if screenshot_root.exists() else "",
        screenshot_count=len(screenshot_files),
        screenshot_files=screenshot_files,
        priority_screenshots=priority,
        constants_readme_path=str(constants_readme) if constants_readme.exists() else "",
        screenshot_test_config_path=str(test_config) if test_config.exists() else "",
        raco_scene_path=str(raco_scene) if raco_scene.exists() else "",
        blender_workfile_path=str(blender_workfile) if blender_workfile.exists() else "",
        shared_root=str(shared_root) if shared_root.exists() else "",
        shared_doc_paths=shared_doc_paths,
        project_svn_info_lines=project_svn_info_lines,
        project_svn_log_lines=project_svn_log_lines,
        shared_svn_log_lines=shared_svn_log_lines,
        delivery_tasks=delivery_tasks,
        notes=tuple(notes),
    )


def _gallery_markup(prep: VisualReviewPrep) -> str:
    screenshot_root = Path(prep.screenshot_root) if prep.screenshot_root else Path()
    priority = list(prep.priority_screenshots)
    all_names = list(prep.screenshot_files)
    other_names = [name for name in all_names if name not in priority]

    def image_card(name: str) -> str:
        image_path = (screenshot_root / name).resolve()
        return (
            '<article class="shot">'
            f'<a href="{escape(image_path.as_uri())}" target="_blank" rel="noreferrer">'
            f'<img src="{escape(image_path.as_uri())}" alt="{escape(name)}">'
            "</a>"
            f'<div class="caption">{escape(name)}</div>'
            "</article>"
        )

    def section(title: str, names: list[str]) -> str:
        if not names:
            return ""
        cards = "\n".join(image_card(name) for name in names)
        return f"<section><h2>{escape(title)}</h2><div class=\"grid\">{cards}</div></section>"

    def bullet_list(items: tuple[str, ...], empty: str) -> str:
        if not items:
            return f"<li>{escape(empty)}</li>"
        return "".join(f"<li>{escape(line)}</li>" for line in items)

    task_items = "".join(
        f"<li><strong>{escape(task.label)}</strong> [{escape(task.state)}]: {escape(task.detail)}</li>"
        for task in prep.delivery_tasks
    )
    notes = "".join(f"<li>{escape(line)}</li>" for line in prep.notes)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Visual review gallery - {escape(prep.profile_id)}</title>
  <style>
    body {{
      background: #09110d;
      color: #e7eee9;
      font: 16px/1.5 "Segoe UI", sans-serif;
      margin: 0;
      padding: 24px;
    }}
    h1, h2 {{ color: #ffd36a; margin: 0 0 12px; }}
    section {{ margin-bottom: 28px; max-width: 1160px; }}
    .meta {{ margin-bottom: 24px; max-width: 1160px; }}
    .grid {{
      display: grid;
      gap: 16px;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      margin-bottom: 28px;
    }}
    .shot {{
      background: rgba(16, 36, 23, 0.92);
      border: 1px solid rgba(122, 210, 133, 0.25);
      border-radius: 10px;
      overflow: hidden;
    }}
    .shot img {{
      display: block;
      width: 100%;
      height: auto;
      background: #000;
    }}
    .caption {{
      padding: 10px 12px;
      font-size: 13px;
      color: #cedbd2;
      word-break: break-word;
    }}
    code {{
      color: #8fe4a4;
      font-family: Consolas, monospace;
    }}
    ul {{ margin-top: 6px; }}
  </style>
</head>
<body>
  <div class="meta">
    <h1>Visual review gallery - {escape(prep.profile_id)}</h1>
    <p>This is local visual-review prep. It helps compare the latest SVN/changelog context against the current screenshot baselines, but it is not automated visual approval.</p>
    <p><strong>Source mode:</strong> {escape(prep.source_mode)}</p>
    <p><strong>Project root:</strong> <code>{escape(prep.project_root)}</code></p>
    <p><strong>Source root:</strong> <code>{escape(prep.source_root)}</code></p>
    <p><strong>Latest changelog section:</strong> {escape(prep.changelog_heading or "Not found")}</p>
    <p><strong>Screenshot baseline folder:</strong> <code>{escape(prep.screenshot_root or "Not found")}</code></p>
    <p><strong>Detected baselines:</strong> {prep.screenshot_count}</p>
    <h2>Project SVN info</h2>
    <ul>{bullet_list(prep.project_svn_info_lines, "No SVN info was captured.")}</ul>
    <h2>Project delivery focus</h2>
    <ul>{bullet_list(prep.changelog_focus_lines, "No changelog focus lines were detected.")}</ul>
    <h2>Project SVN log shortlist</h2>
    <ul>{bullet_list(prep.project_svn_log_lines, "No project SVN log entries were detected.")}</ul>
    <h2>Shared BMW SVN log shortlist</h2>
    <ul>{bullet_list(prep.shared_svn_log_lines, "No shared BMW SVN log entries were detected.")}</ul>
    <h2>Jana checklist mapping</h2>
    <ul>{task_items}</ul>
    <ul>{notes}</ul>
  </div>
  {section("Priority screenshot shortlist", priority)}
  {section("Full screenshot baseline set", other_names if priority else all_names)}
</body>
</html>
"""


def _markdown(prep: VisualReviewPrep) -> str:
    lines = [
        f"# Visual review prep - {prep.profile_id}",
        "",
        f"Generated at: {prep.generated_at_utc}",
        f"Source mode: {prep.source_mode}",
        f"Project root: `{prep.project_root}`",
        f"Source root: `{prep.source_root}`",
        "",
        "This is local visual-review prep, not automated visual approval.",
        "",
        "## Project SVN info",
    ]
    if prep.project_svn_info_lines:
        lines.extend(f"- {line}" for line in prep.project_svn_info_lines)
    else:
        lines.append("- No SVN info was captured.")

    lines.extend(
        [
            "",
            "## Delivery focus from changelog",
            f"- Changelog: `{prep.changelog_path}`" if prep.changelog_path else "- Changelog: not found",
            f"- Latest section: {prep.changelog_heading}" if prep.changelog_heading else "- Latest section: not found",
        ]
    )
    if prep.changelog_focus_lines:
        lines.extend(f"- {line}" for line in prep.changelog_focus_lines)
    else:
        lines.append("- No changelog focus lines were detected.")

    lines.extend(["", "## Project SVN log shortlist"])
    if prep.project_svn_log_lines:
        lines.extend(f"- {line}" for line in prep.project_svn_log_lines)
    else:
        lines.append("- No project SVN log entries were detected.")

    lines.extend(["", "## Screenshot baseline review"])
    lines.append(f"- Screenshot root: `{prep.screenshot_root}`" if prep.screenshot_root else "- Screenshot root: not found")
    lines.append(f"- Detected files: {prep.screenshot_count}")
    if prep.priority_screenshots:
        lines.append("- Priority shortlist:")
        lines.extend(f"  - {name}" for name in prep.priority_screenshots)

    lines.extend(["", "## Project README files"])
    if prep.project_readme_paths:
        lines.extend(f"- `{path}`" for path in prep.project_readme_paths)
    else:
        lines.append("- No project README file was found under the live car root.")

    lines.extend(["", "## Shared BMW review context"])
    lines.append(f"- Shared root: `{prep.shared_root}`" if prep.shared_root else "- Shared root: not found")
    if prep.shared_doc_paths:
        lines.append("- Prioritized shared README / CHANGELOG files:")
        lines.extend(f"  - `{path}`" for path in prep.shared_doc_paths)
    else:
        lines.append("- No prioritized shared README / CHANGELOG files were detected.")
    if prep.shared_svn_log_lines:
        lines.append("- Shared SVN log shortlist:")
        lines.extend(f"  - {line}" for line in prep.shared_svn_log_lines)
    else:
        lines.append("- No shared SVN log entries were detected.")

    lines.extend(
        [
            "",
            "## Open in tools",
            f"- Representative RaCo scene: `{prep.raco_scene_path}`" if prep.raco_scene_path else "- Representative RaCo scene: not found",
            f"- Representative Blender workfile: `{prep.blender_workfile_path}`" if prep.blender_workfile_path else "- Representative Blender workfile: not found",
            f"- Screenshot test config: `{prep.screenshot_test_config_path}`" if prep.screenshot_test_config_path else "- Screenshot test config: not found",
            f"- Constants README: `{prep.constants_readme_path}`" if prep.constants_readme_path else "- Constants README: not found",
        ]
    )

    lines.extend(["", "## Jana delivery checklist mapping"])
    if prep.delivery_tasks:
        for task in prep.delivery_tasks:
            lines.append(f"- {task.label} [{task.state}]")
            lines.append(f"  - {task.detail}")
            if task.path:
                lines.append(f"  - Path: `{task.path}`")
    else:
        lines.append("- No delivery checklist tasks were generated.")

    lines.extend(
        [
            "",
            "## Review checklist",
            "- Project changelog reviewed: [ ]",
            "- Project SVN log reviewed: [ ]",
            "- Shared BMW README / CHANGELOG reviewed: [ ]",
            "- Screenshot baseline set reviewed: [ ]",
            "- Representative RaCo scene opened: [ ]",
            "- Representative Blender workfile opened: [ ]",
            "- Priority screenshots checked first: [ ]",
            "- Findings documented with evidence: [ ]",
            "- Notes:",
            "  - ",
        ]
    )
    return "\n".join(lines).strip() + "\n"


def materialize_visual_review_prep(
    profile_id: str,
    project_root: Path,
    output_root: Path,
    *,
    repo_root: Path | None = None,
) -> VisualReviewPrepBundle:
    output_root.mkdir(parents=True, exist_ok=True)
    prep = build_visual_review_prep(profile_id, project_root, repo_root=repo_root)
    json_path = output_root / "visual-review-prep.json"
    markdown_path = output_root / "visual-review-prep.md"
    html_path = output_root / "visual-review-gallery.html"
    json_path.write_text(json.dumps(prep.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    markdown_path.write_text(_markdown(prep), encoding="utf-8")
    html_path.write_text(_gallery_markup(prep), encoding="utf-8")
    return VisualReviewPrepBundle(
        prep=prep,
        json_path=json_path,
        markdown_path=markdown_path,
        html_path=html_path,
    )

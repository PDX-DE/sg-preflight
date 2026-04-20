from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path
import re
from typing import Any


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
    "ground": ("ground", "reflection", "shadow"),
    "grill": ("front", "lights", "default"),
    "highlight": ("highlighting",),
    "hood": ("hood",),
    "indicator": ("indicator", "lights"),
    "indicators": ("indicator", "lights"),
    "light": ("lights", "drl", "beam", "rear", "front", "fog", "parking", "indicator", "position"),
    "lights": ("lights", "drl", "beam", "rear", "front", "fog", "parking", "indicator", "position"),
    "parking": ("parking", "lights", "sensor"),
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
}


@dataclass(frozen=True)
class VisualReviewPrep:
    profile_id: str
    project_root: str
    generated_at_utc: str
    changelog_path: str = ""
    changelog_heading: str = ""
    changelog_focus_lines: tuple[str, ...] = ()
    screenshot_root: str = ""
    screenshot_count: int = 0
    screenshot_files: tuple[str, ...] = ()
    priority_screenshots: tuple[str, ...] = ()
    constants_readme_path: str = ""
    screenshot_test_config_path: str = ""
    raco_scene_path: str = ""
    blender_workfile_path: str = ""
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


def _priority_keywords(changelog_focus_lines: tuple[str, ...]) -> list[str]:
    tokens: list[str] = []
    for line in changelog_focus_lines:
        for token in re.findall(r"[a-z0-9_]+", line.lower()):
            if len(token) < 3 or token in _STOPWORDS:
                continue
            aliases = _KEYWORD_ALIASES.get(token)
            if aliases:
                tokens.extend(aliases)
            else:
                tokens.append(token)
    return tokens


def _priority_screenshots(screenshot_files: tuple[str, ...], changelog_focus_lines: tuple[str, ...]) -> tuple[str, ...]:
    if not screenshot_files:
        return ()

    keyword_hits = _priority_keywords(changelog_focus_lines)
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


def build_visual_review_prep(profile_id: str, project_root: Path) -> VisualReviewPrep:
    changelog_path = _find_changelog(project_root)
    changelog_heading, changelog_focus_lines = _parse_latest_changelog(changelog_path)
    screenshot_root = _find_screenshot_root(project_root)
    screenshot_files = tuple(
        path.name
        for path in sorted(screenshot_root.iterdir())
        if path.is_file() and path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ) if screenshot_root.exists() else ()
    priority = _priority_screenshots(screenshot_files, changelog_focus_lines)

    notes = [
        "This is local visual-review prep, not automated visual approval.",
        "Check the latest changelog items against the screenshot baselines before delivery handoff.",
    ]
    if priority:
        notes.append("Start with the priority screenshot shortlist before browsing the full baseline set.")

    return VisualReviewPrep(
        profile_id=profile_id,
        project_root=str(project_root),
        generated_at_utc=_utc_now(),
        changelog_path=str(changelog_path) if changelog_path.exists() else "",
        changelog_heading=changelog_heading,
        changelog_focus_lines=changelog_focus_lines,
        screenshot_root=str(screenshot_root) if screenshot_root.exists() else "",
        screenshot_count=len(screenshot_files),
        screenshot_files=screenshot_files,
        priority_screenshots=priority,
        constants_readme_path=str(_find_constants_readme(profile_id, project_root)),
        screenshot_test_config_path=str(_find_test_config(project_root)),
        raco_scene_path=str(_find_representative_scene(profile_id, project_root)),
        blender_workfile_path=str(_find_representative_blend(project_root)),
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

    changelog_lines = "".join(f"<li>{escape(line)}</li>" for line in prep.changelog_focus_lines)
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
    .meta {{ margin-bottom: 24px; max-width: 1100px; }}
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
    <p>This is local visual-review prep. It helps compare the latest changelog against the mirrored screenshot baselines, but it is not automated visual approval.</p>
    <p><strong>Project root:</strong> <code>{escape(prep.project_root)}</code></p>
    <p><strong>Latest changelog section:</strong> {escape(prep.changelog_heading or "Not found")}</p>
    <p><strong>Screenshot baseline folder:</strong> <code>{escape(prep.screenshot_root or "Not found")}</code></p>
    <p><strong>Detected baselines:</strong> {prep.screenshot_count}</p>
    <ul>{changelog_lines or '<li>No changelog focus lines were detected.</li>'}</ul>
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
        f"Project root: `{prep.project_root}`",
        "",
        "This is local visual-review prep, not automated visual approval.",
        "",
        "## Delivery focus from changelog",
        f"- Changelog: `{prep.changelog_path}`" if prep.changelog_path else "- Changelog: not found",
        f"- Latest section: {prep.changelog_heading}" if prep.changelog_heading else "- Latest section: not found",
    ]
    if prep.changelog_focus_lines:
        lines.extend(f"- {line}" for line in prep.changelog_focus_lines)
    else:
        lines.append("- No changelog focus lines were detected.")

    lines.extend(
        [
            "",
            "## Screenshot baseline review",
            f"- Screenshot root: `{prep.screenshot_root}`" if prep.screenshot_root else "- Screenshot root: not found",
            f"- Detected files: {prep.screenshot_count}",
        ]
    )
    if prep.priority_screenshots:
        lines.append("- Priority shortlist:")
        lines.extend(f"  - {name}" for name in prep.priority_screenshots)
    if prep.screenshot_files:
        lines.append("- Full baseline set:")
        lines.extend(f"  - {name}" for name in prep.screenshot_files)

    lines.extend(
        [
            "",
            "## Open in tools",
            f"- Representative RaCo scene: `{prep.raco_scene_path}`" if prep.raco_scene_path else "- Representative RaCo scene: not found",
            f"- Representative Blender workfile: `{prep.blender_workfile_path}`" if prep.blender_workfile_path else "- Representative Blender workfile: not found",
            f"- Screenshot test config: `{prep.screenshot_test_config_path}`" if prep.screenshot_test_config_path else "- Screenshot test config: not found",
            f"- Constants README: `{prep.constants_readme_path}`" if prep.constants_readme_path else "- Constants README: not found",
            "",
            "## Review checklist",
            "- Project changelog reviewed: [ ]",
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
) -> VisualReviewPrepBundle:
    output_root.mkdir(parents=True, exist_ok=True)
    prep = build_visual_review_prep(profile_id, project_root)
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

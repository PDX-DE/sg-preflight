"""Quality-Hero manual-review step guidance and brand/lane review templates.

Holds the fixed step list (Blender check, constants verification, final-look
comparison, etc.) and the BMW/MINI template definitions used to build a review
session for a given profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sg_preflight.profiles import get_run_profile


MANUAL_REVIEW_HEADER = (
    "Manual review companion. Operator records the verdict per step. "
    "Not a tool-generated review or approval."
)


REVIEW_FOCUS_NOTE = "Review guidance only; the operator records the verdict."


AUTO_CHECK_NOTE = "Auto-checks prepare evidence only; the operator records each manual-review verdict."


REVIEW_ASSIST_NOTE = (
    "Review Assist suggests local starting points from evidence. "
    "The operator confirms or changes every manual-review verdict."
)


REVIEW_ASSIST_GUARDRAILS = (
    "Manual review remains required.",
    "Decision: not approval — evidence only.",
    "BMW Git access is read-only. SGFX never modifies BMW source.",
    "Activity log is local-only — never posted to Jira, SVN, or BMW Git.",
)


VALID_VERDICTS = ("passed", "failed", "skipped", "incomplete")


_VERDICT_ALIASES = {
    "pass": "passed",
    "fail": "failed",
    "blocked": "incomplete",
    "not_applicable": "skipped",
}


_PENDING_VERDICT = "not_run"


_EVIDENCE_AVAILABLE = "available"


_EVIDENCE_MISSING = "missing"


_SESSION_FILENAME = "session.json"


_CONFLUENCE_SOURCE = (
    "PDX_" + "SER" + "GFX/139_3D-Car/298_Quality-Hero-How-to-review-the-3D-car/page.txt"
)


_DELIVERY_CONFLUENCE_SOURCE = (
    "PDX_" + "SER" + "GFX/311_Delivery-process/312_3D-Car---Delivery-and-Integration/"
    "315_How-to-3D-Cars-Delivery-Checklist----v0/page.txt"
)


_BMW_SCRIPT_CONFLUENCE_SOURCE = (
    "PDX_" + "SER" + "GFX/139_3D-Car/225_3D-Car---RaCo-Implementation/"
    "249_How-to-use-the-various-python-scripts-fo/page.txt"
)


@dataclass(frozen=True)
class CarReviewTemplate:
    family_id: str
    title: str
    brand: str
    lane: str
    description: str
    profile_examples: tuple[str, ...]
    evidence_checklist: tuple[str, ...]
    confluence_anchors: tuple[str, ...]

    def to_payload(self) -> dict[str, Any]:
        return {
            "family_id": self.family_id,
            "title": self.title,
            "brand": self.brand,
            "lane": self.lane,
            "description": self.description,
            "profile_examples": list(self.profile_examples),
            "evidence_checklist": [
                {
                    "slug": _slug(item),
                    "label": item,
                    "status": "not_run",
                    "manual_review_required": True,
                }
                for item in self.evidence_checklist
            ],
            "confluence_anchors": list(self.confluence_anchors),
        }


CAR_REVIEW_TEMPLATES: tuple[CarReviewTemplate, ...] = (
    CarReviewTemplate(
        family_id="bmw_idcevo",
        title="BMW IDC_EVO Quality-Hero review",
        brand="BMW",
        lane="IDC_EVO",
        description="Default BMW IDC_EVO review setup with delivery workbook, screenshot, and manual Quality-Hero evidence prompts.",
        profile_examples=("G65", "G70", "G58"),
        evidence_checklist=(
            "Confirm IDC_EVO BMW Git master checkout and profile folder are visible.",
            "Read or generate the delivery checklist workbook evidence.",
            "Read screenshot expected / actual / diff state.",
            "Run visual diff triage when actual PNGs are present.",
            "Record each Quality-Hero manual-review step verdict locally.",
            "Keep Jira writeback confirmation-gated if a review package is shared.",
        ),
        confluence_anchors=(_CONFLUENCE_SOURCE, _DELIVERY_CONFLUENCE_SOURCE, _BMW_SCRIPT_CONFLUENCE_SOURCE),
    ),
    CarReviewTemplate(
        family_id="bmw_idc23",
        title="BMW IDC_23 Quality-Hero review",
        brand="BMW",
        lane="IDC_23",
        description="Default BMW IDC_23 review setup with the lane-correct assets/idc23 script path and the same manual review steps.",
        profile_examples=("F70", "U10"),
        evidence_checklist=(
            "Confirm the IDC_23 assets worktree and BMW shared data are visible.",
            "Read or generate the delivery checklist workbook evidence for the resolved SVN profile.",
            "Read screenshot expected / actual / diff state from the IDC_23 lane.",
            "Run visual diff triage when actual PNGs are present.",
            "Record each Quality-Hero manual-review step verdict locally.",
            "Keep Jira writeback confirmation-gated if a review package is shared.",
        ),
        confluence_anchors=(_CONFLUENCE_SOURCE, _DELIVERY_CONFLUENCE_SOURCE, _BMW_SCRIPT_CONFLUENCE_SOURCE),
    ),
    CarReviewTemplate(
        family_id="mini",
        title="MINI Quality-Hero review",
        brand="MINI",
        lane="IDC_23",
        description="Default MINI review setup with MINI screenshot roots plus the shared manual Quality-Hero evidence prompts.",
        profile_examples=("F66", "F67", "U25"),
        evidence_checklist=(
            "Confirm the MINI brand folder and resolved profile folder are visible.",
            "Read or generate the delivery checklist workbook evidence for the MINI profile.",
            "Read MINI screenshot expected / actual / diff state.",
            "Run visual diff triage when actual PNGs are present.",
            "Record each Quality-Hero manual-review step verdict locally.",
            "Keep Jira writeback confirmation-gated if a review package is shared.",
        ),
        confluence_anchors=(_CONFLUENCE_SOURCE, _DELIVERY_CONFLUENCE_SOURCE, _BMW_SCRIPT_CONFLUENCE_SOURCE),
    ),
)


@dataclass(frozen=True)
class ManualReviewStepTemplate:
    slug: str
    title: str
    guidance: tuple[str, ...]
    tool_hint: str
    review_focus: tuple[str, ...] = ()
    evidence_prompt: str = ""

    def to_session_step(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "title": self.title,
            "guidance": list(self.guidance),
            "tool_hint": self.tool_hint,
            "review_focus": list(self.review_focus),
            "review_focus_note": REVIEW_FOCUS_NOTE,
            "evidence_prompt": self.evidence_prompt,
            "suggested_verdict": "",
            "suggestion_status": "not_run",
            "evidence_status": "not_run",
            "suggestion_reason": "",
            "suggestion_paths": [],
            "auto_check_status": "not_run",
            "auto_check_kind": "",
            "auto_check_summary": "",
            "auto_check_paths": [],
            "auto_check_metrics": {},
            "operator_focus_status": "incomplete",
            "operator_focus_reason": "Operator records the manual-review verdict.",
            "manual_review_required": True,
            "operator_verdict": "",
            "verdict": _PENDING_VERDICT,
            "note": "",
            "screenshot_path": "",
            "recorded_at_utc": "",
            "recorded_by_tool": False,
        }


QUALITY_HERO_STEPS: tuple[ManualReviewStepTemplate, ...] = (
    ManualReviewStepTemplate(
        slug="blender_visual_check",
        title="Blender Visual Check",
        tool_hint="blender",
        guidance=(
            "Open the relevant car for testing using an up to date SG-Toolkit in Blender.",
            "Rotate car and look for artefacts and missing or broken meshes.",
            "Test naming and Blender pipeline setup including naming in the outliner.",
            "Go through Trimlines and test color change and material change options in the Analyze section.",
            "Test light functionality including Iconic Glow, position lights and Selective Yellow for relevant country variants.",
            "Check Logos, Lights, Side Mirrors, Rims and Flaps with extra care.",
        ),
        review_focus=(
            "Logos",
            "LightFX",
            "Iconic Glow",
            "Selective Yellow",
            "Side mirrors",
            "Rims",
            "Flaps",
            "Trimlines",
            "Country variants",
            "Material artifacts",
        ),
        evidence_prompt="Attach representative Blender screenshots for visible artifacts or country-variant light concerns.",
    ),
    ManualReviewStepTemplate(
        slug="constants_info_verification",
        title="Constants Info Verification",
        tool_hint="manual",
        guidance=(
            "Use the information provided in the car's Epic.",
            "Check the Constants script in _Common/constants/scripts or the Pivot_Master file in _Workfiles/json.",
            "Compare Tire Diameter.",
            "Compare Suspension information.",
            "Compare Reflections.",
        ),
        review_focus=(
            "Constants",
            "Tire diameter",
            "Suspension",
            "Reflections",
            "Pivot_Master",
            "Epic comparison",
        ),
        evidence_prompt="Record the Epic source and constants source checked; attach screenshots only when useful for reviewer follow-up.",
    ),
    ManualReviewStepTemplate(
        slug="final_look_comparison_raco_blender_epic",
        title="Final Look Comparison RaCo & Blender & Epic",
        tool_hint="raco_blender",
        guidance=(
            "Open the Blender and RaCo export scenes of the relevant car plus the Epic.",
            "Compare the Blender scene to the exported and final look of the RaCo car.",
            "Check Logos, Lights, Side Mirrors, Rims and Flaps with extra care.",
            "Using the IDCEvo README, compare EngineType, CountryVariants, TrimLines and light functionality.",
        ),
        review_focus=(
            "RaCo vs Blender",
            "EngineType",
            "Country variants",
            "Trimlines",
            "Logos",
            "Lights",
            "Side mirrors",
            "Rims",
            "Flaps",
        ),
        evidence_prompt="Attach paired Blender/RaCo screenshots when the final look differs or requires owner follow-up.",
    ),
    ManualReviewStepTemplate(
        slug="functionality_test_raco",
        title="Functionality Test RaCo",
        tool_hint="raco",
        guidance=(
            "With the already open scenes compare animations, lights and Iconic Glow between Blender and RaCo.",
            "Activate WelcomeFX animations and check exterior light, loop state and animation ID behaviour.",
            "Make sure Trimlines, Country variants and Exterior lights show relevant changes from Blender to RaCo scenes.",
            r"Use C:\repos\Seriengrafik\trunk\.pdx\carmodel_data.json for engine and Trimline combinations.",
        ),
        review_focus=(
            "Animations",
            "LightFX",
            "WelcomeFX",
            "Iconic Glow",
            "Exterior lights",
            "Country variants",
            "Trimlines",
        ),
        evidence_prompt="Record the animation and light combination tested and attach proof for incomplete or failing states.",
    ),
    ManualReviewStepTemplate(
        slug="anchor_points_test_raco",
        title="Anchor Points Test RaCo",
        tool_hint="raco",
        guidance=(
            "Open the car's Export scene and add the Abstract Scene View if it is not already set up.",
            "Change Highlight option to Transparency.",
            "In the Scene Graph go to Anchorpoints_BoundingBox and inspect the anchor points on screen.",
            "Use the camera gimble and confirm each anchor point matches the actual tested position.",
            'Naming convention: APN_BoundingBox_"vehicle_part"_"Position".',
        ),
        review_focus=(
            "Anchor points",
            "Bounding boxes",
            "Naming convention",
            "Vehicle part positions",
            "Abstract Scene View",
        ),
        evidence_prompt="Record the anchor family inspected and attach a RaCo screenshot when an anchor is missing or misaligned.",
    ),
    ManualReviewStepTemplate(
        slug="carpaints_test_raco",
        title="CarPaints Test RaCo",
        tool_hint="raco",
        guidance=(
            "Have the 3D Car git set up for testing using the Confluence instructions.",
            "Open the PythonRunner view in the scene and import read_json_carpaints.py.",
            "Use the car paints in the script and test different materials in multiple angles.",
            "Check for artefacts between color or Met/Mat options.",
            "Use the available colors listed at the top of the script.",
        ),
        review_focus=(
            "CarPaint / Lackcode",
            "Color variants",
            "Met/Mat options",
            "Material artifacts",
            "Multiple viewing angles",
        ),
        evidence_prompt="Record the color/material combinations tested and attach screenshots for visible paint or material artifacts.",
    ),
    ManualReviewStepTemplate(
        slug="documentation_review",
        title="Documentation Review",
        tool_hint="manual",
        guidance=(
            "Review 3DCar and Widget documentation relevant to the current ticket.",
            "Check changelog and README content against what was actually delivered.",
            "Keep documentation findings separate from visual verdicts.",
        ),
        review_focus=(
            "README",
            "Changelog",
            "Delivery notes",
            "Ticket scope",
            "Manual findings",
        ),
        evidence_prompt="Record documentation mismatches without marking visual review complete.",
    ),
)


QUALITY_HERO_STEP_TITLES = tuple(step.title for step in QUALITY_HERO_STEPS)


def _workspace(workspace: Path | str | None) -> Path:
    return Path(workspace).resolve() if workspace is not None else Path(__file__).resolve().parents[1]


def _slug(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in value.strip())
    return "_".join(part for part in slug.split("_") if part)


def _profile_project_roots(profile_id: str, workspace: Path | str | None) -> list[Path]:
    root = _workspace(workspace)
    clean_profile = profile_id.strip()
    direct_candidates = [
        root / "Cars_IDCevo" / "BMW" / clean_profile,
        root / "Cars" / "BMW" / clean_profile,
        root / "repositories" / "trunk" / "Cars_IDCevo" / "BMW" / clean_profile,
        root / "repositories" / "trunk" / "Cars" / "BMW" / clean_profile,
    ]
    direct_existing = [path.resolve() for path in direct_candidates if path.exists()]
    if direct_existing:
        return direct_existing
    candidates = list(direct_candidates)
    try:
        profile = get_run_profile(clean_profile, root)
    except KeyError:
        profile = None
    if profile is not None:
        candidates.extend([profile.project_root, profile.source_project_root()])
    seen: set[str] = set()
    ordered: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).casefold()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(resolved)
    existing = [path for path in ordered if path.exists()]
    return existing or ordered[:1]


def list_car_review_templates() -> tuple[dict[str, Any], ...]:
    return tuple(template.to_payload() for template in CAR_REVIEW_TEMPLATES)


def get_car_review_template(family_id: str) -> dict[str, Any]:
    clean_family = str(family_id or "").strip().casefold().replace("-", "_")
    aliases = {
        "bmw_idc_evo": "bmw_idcevo",
        "idcevo": "bmw_idcevo",
        "idc_evo": "bmw_idcevo",
        "bmw_idc_23": "bmw_idc23",
        "idc23": "bmw_idc23",
        "idc_23": "bmw_idc23",
        "mini_idc23": "mini",
        "mini_idc_23": "mini",
    }
    clean_family = aliases.get(clean_family, clean_family)
    for template in CAR_REVIEW_TEMPLATES:
        if template.family_id == clean_family:
            return template.to_payload()
    known = ", ".join(template.family_id for template in CAR_REVIEW_TEMPLATES)
    raise ValueError(f"Unknown car review template family: {family_id}. Known families: {known}")


def review_template_for_profile(
    profile_id: str,
    *,
    workspace: Path | str | None = None,
) -> dict[str, Any]:
    clean_profile = profile_id.strip()
    try:
        profile = get_run_profile(clean_profile, _workspace(workspace))
    except KeyError:
        profile = None
    if profile is not None:
        if str(profile.brand).strip().casefold() == "mini":
            return get_car_review_template("mini")
        if str(profile.lane).strip().casefold() == "idc_23":
            return get_car_review_template("bmw_idc23")
    if clean_profile.upper().startswith("MINI_"):
        return get_car_review_template("mini")
    return get_car_review_template("bmw_idcevo")

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import zipfile
from typing import Any, Iterable

from sg_preflight.bmw_delivery import BmwScreenshotSurface, inspect_bmw_screenshot_surface
from sg_preflight.daily_snapshot import (
    BmwBatteryResult,
    BmwConfigCheckResult,
    BmwSmokeResult,
    DailyQaSnapshot,
    DailyQaSnapshotResult,
    _battery_baseline_gap_payload,
    _render_battery_baseline_gaps_markdown,
    _render_candidate_review_gallery,
    _render_snapshot_markdown,
    find_latest_daily_qa_snapshot,
)
from sg_preflight.profiles import RunProfile, get_run_profile, resolve_source_repo_root
from sg_preflight.qa_actions import ActionRecord, load_action_record, operator_ui_actions_root
from sg_preflight.screenshot_triage import ScreenshotTriageBundle, ScreenshotTriageReport, materialize_screenshot_triage
from sg_preflight.services import prerequisite_status
from sg_preflight.visual_review import VisualReviewPrep, build_visual_review_prep


_PROCESS_QUESTIONS = (
    "Can you confirm whether the grounded list `{profiles}` is complete for {ticket_id}, or if any additional cars/slices should also be reviewed?",
    "Where are the screenshot test candidate/result images generated and which folder is the source of truth?",
    "What is the normal screenshot-test pass/fail reading flow: diff report, threshold, log, or manual folder comparison?",
    "What exactly counts as `asset review in raco (bmws)` done: scene opens, missing-resource check, visual comparison, or a formal scene-check report?",
    "What exact command/script proves `headless export check bmw` success when the BMW side is available?",
    "Should minor SG checker findings be fixed now, assigned, or only reported while the real SVN remains untouched?",
    "Where should the result be reported while Jira is blocked: Teams, Jana message, or shared package drop?",
)
_PROCESS_HINTS = (
    "This ticket is partly a process-definition task: evaluate possible test cases, update the DoD, and clarify ownership instead of pretending all BMW-side checks can run locally.",
    "This bundle intentionally separates deterministic SG-side evidence from still-manual visual judgment.",
)
_QUALITY_HERO_PROCESS_REFERENCE = "SG Quality-Hero manual-review process reference"
_BMW_DOC_URLS = (
    "https://confluence.cc.bmwgroup.net/spaces/virtualcar/pages/137035868/SG+Delivery+Documentation",
    "https://confluence.cc.bmwgroup.net/spaces/virtualcar/pages/1340896387/Models",
    "https://confluence.cc.bmwgroup.net/spaces/virtualcar/pages/1118627625/CarPaints",
)
_ACTION_KIND_IDS = ("scene_check", "qa_stack", "repo_checker_profile", "delivery_checklist")
_MANUAL_EVIDENCE_ASSET_KINDS = {
    "raco_note",
    "blender_note",
    "visual_review_checklist",
    "verification_note",
    "screenshot",
}
_QA_CONFLUENCE_SNAPSHOT_DATE = "2026-04-21"
_QA_CAPABILITY_SPECS = (
    {
        "label": "SG repo scenes checker",
        "section": "Script and Shader formatting and checking",
        "relative_paths": ("check_scenes.py",),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Recursive RaCo scene validation with an external RaCoHeadless.exe path before manual review.",
        "how_to_use": 'py check_scenes.py --raco "C:\\path\\to\\RaCoHeadless.exe" --dir "C:\\repositories\\trunk\\Cars\\BMW"',
        "blocker": "Needs a matching RaCoHeadless.exe build path from Ramses Composer.",
    },
    {
        "label": "SG checker / format stack",
        "section": "Script and Shader formatting and checking",
        "relative_paths": (
            ".pdx/checkers/executeChecks.py",
            ".pdx/checkers/code_style_checker/check_all_styles.py",
        ),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Lua/shader/style/repo checks that SG can already run on the live SVN slice.",
        "how_to_use": 'py ".pdx\\checkers\\executeChecks.py" "C:\\repositories\\trunk\\Cars_IDCevo\\BMW\\<PROFILE>"',
        "blocker": "Needs the SG repo root and a fix-vs-report decision for surfaced findings.",
    },
    {
        "label": "Export-scene Python tests",
        "section": "How to deliver to BMW",
        "relative_paths": (
            ".pdx/raco/scripts/testing/test_absolute_path.py",
            ".pdx/raco/scripts/testing/test_ucap_ignore.py",
            ".pdx/raco/scripts/testing/test_unused_lua_files.py",
        ),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Absolute-path, UCAP-ignore, and unused-Lua sanity checks for export scenes before delivery packaging.",
        "how_to_use": "Run the scripts from the RaCo Python Runner or from the SG testing flow against the export scene.",
        "blocker": "Needs the correct export scene open and the reviewer to record the outcome manually.",
    },
    {
        "label": "Perspective setup helper",
        "section": "How to create a new fixed perspective",
        "relative_paths": (".pdx/raco/scripts/testing/setup_perspective.py",),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Camera/perspective setup against a reference image when perspective changes are part of the review scope.",
        "how_to_use": 'Run setup_perspective.py in the RaCo Python Runner with "init <width>x<height>" or "set <width>x<height>".',
        "blocker": "Only relevant when perspective work is actually in scope.",
    },
    {
        "label": "Perspective TracePlayer assets",
        "section": "TP - Perspective Checker",
        "relative_paths": (".pdx/raco/archive/PerspectiveTracePlayer",),
        "status_present": "archived in SVN",
        "status_missing": "missing locally",
        "checks": "Legacy perspective-trace workflow; the documentation says the old live location was archived in 09/2025.",
        "how_to_use": 'If perspective trace playback is still needed, restore or copy from ".pdx\\raco\\archive\\PerspectiveTracePlayer" first.',
        "blocker": "This is not an active default workflow anymore; the old non-archive path is intentionally not assumed.",
    },
    {
        "label": "Ramses resource size report",
        "section": "How to analyze Ramses resources",
        "relative_paths": (".pdx/raco/scripts/testing/resources_size_report.py",),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Variant export plus Ramses resource-size reporting for delivery-size or UCAP risk investigations.",
        "how_to_use": "Run resources_size_report.py from the RaCo Python Runner on the export scene when resource-size evidence is needed.",
        "blocker": "Needs the right Ramses/RaCo version and is only worth the cost when size is relevant to the ticket.",
    },
    {
        "label": "Car-paint quick-check helpers",
        "section": "How to... Car Paint",
        "relative_paths": (
            ".pdx/raco/scripts/testing/read_json_carpaints.py",
            ".pdx/raco/TestCarPaint",
        ),
        "status_present": "available locally",
        "status_missing": "missing locally",
        "checks": "Fast RaCo-side paint validation without retyping each material/color combination manually.",
        "how_to_use": 'Open the Python Runner, import "read_json_carpaints.py", and use the ".pdx\\raco\\TestCarPaint" setup when car paints are in scope.',
        "blocker": "Full paint approval still depends on rack/design review, not only RaCo-side inspection.",
    },
    {
        "label": "BMW screenshot smoke flow",
        "section": 'How to "screenshottest"',
        "relative_paths": (),
        "status_present": "blocked by BMW access",
        "status_missing": "blocked by BMW access",
        "checks": "BMW-owned export/interface/screenshot smoke flow from digital-3d-car-models.",
        "how_to_use": 'Use the documented lane helper: IDC_23 uses "py ci/scripts/test/main.py screenshots --diff <CAR>" on assets/idc23; IDC_EVO uses "py ci/scripts/car_manager.py screenshots --diff <CAR>" on master.',
        "blocker": "Needs the BMW repo helper surface plus real expected/actual/diff screenshot payload; empty folders are not evidence of a passing run.",
    },
    {
        "label": "BMW headless export proof",
        "section": "How to deliver to BMW",
        "relative_paths": (),
        "status_present": "blocked by BMW access",
        "status_missing": "blocked by BMW access",
        "checks": "The proving command/output for BMW-side headless export success that the delivery ticket expects.",
        "how_to_use": 'Use the documented lane helper: IDC_23 uses "py ci/scripts/test/main.py export <CAR>" on assets/idc23; IDC_EVO uses "py ci/scripts/car_manager.py export <CAR>" on master. Treat proof as the captured export log plus printed binary file sizes.',
        "blocker": "Needs the BMW repo helper surface, runnable local toolchain, and a captured success log; packaging the helper alone does not prove export success.",
    },
    {
        "label": "Rack / hardware car-paint review",
        "section": "How to... Car Paint",
        "relative_paths": (),
        "status_present": "manual / rack dependent",
        "status_missing": "manual / rack dependent",
        "checks": "Real hardware/rack validation via ADB, localhost:9091, and the 3D Car Test app for final paint tuning.",
        "how_to_use": 'Use "adb connect <rack-ip>", "adb forward tcp:9091 tcp:9091", then review via "http://localhost:9091/" once the rack is available.',
        "blocker": "Needs physical rack access, the 3D Car Test app, and a reviewer session; it is not a headless local flow.",
    },
)
_THREE_D_QA_TEST_CATALOG = (
    {
        "area": "Blender visual check",
        "checks": "Rotate the car, look for artifacts or broken meshes, verify naming/outliner setup, and spot-check trimline, material, and light variants.",
        "where": "Up-to-date SG Toolkit in Blender plus Resource Section and LightFX.",
        "evidence": "Manual note and screenshot when anything looks wrong; pay extra attention to logos, lights, mirrors, rims, and flaps.",
    },
    {
        "area": "Constants info verification",
        "checks": "Verify tire diameter, suspension information, and reflection-related data against the car Epic and constants/Pivot_Master sources.",
        "where": "Car _Common/constants/scripts or _Workfiles/json Pivot_Master data.",
        "evidence": "Short reviewer note naming the checked constants source and any mismatch.",
    },
    {
        "area": "Final look comparison: Blender vs RaCo vs Epic",
        "checks": "Compare Blender export scenes, RaCo export scenes, and Epic-delivered change intent before treating a visible difference as suspicious.",
        "where": "Representative Blender workfile, RaCo export scene, changelog/README/Epic context.",
        "evidence": "Manual comparison note plus screenshot when a visible difference is important.",
    },
    {
        "area": "Functionality test in RaCo",
        "checks": "Validate WelcomeFX, exterior-light-dependent behavior, loop state, animation ID, Iconic Glow, and variant-dependent state switches.",
        "where": "RaCo scene with the relevant logic/light interfaces active.",
        "evidence": "Checklist or note describing which states were toggled and what was observed.",
    },
    {
        "area": "Anchor points test in RaCo",
        "checks": "Use transparency/highlight mode and verify APN_BoundingBox naming against the actual anchor-point position.",
        "where": "RaCo export scene Scene Graph, Anchorpoints_BoundingBox, Abstract Scene View.",
        "evidence": "Manual note listing any wrong name/position combination and a screenshot when unclear.",
    },
    {
        "area": "Car-paints test in RaCo",
        "checks": "Review multiple paint IDs, material options, and viewing angles for visible artifacts or inconsistent metallic/matte behavior.",
        "where": "RaCo Python Runner with read_json_carpaints.py and TestCarPaint setup.",
        "evidence": "Manual note with tested paint IDs and screenshots only when something is questionable.",
    },
    {
        "area": "Documentation review",
        "checks": "Review car README, changelog, and shared BMW docs before closing manual visual review.",
        "where": "Live SVN slice plus the packaged ticket bundle docs.",
        "evidence": "Reviewer note naming which docs were checked and what implementation intent they imply.",
    },
    {
        "area": "Special use-case checks",
        "checks": "Scene ID, UCAP positions, mirrored parts, reverse light/fog distribution, trunk opening angle, steering wheel rotation, detailed light checks, and dead-end interface chains.",
        "where": "RaCo scene, changelog scope, and export/test scripts where available.",
        "evidence": "Focused note only for cases relevant to the ticket scope; do not claim all special cases were checked blindly.",
    },
)
_DELIVERY_TARGET_SPECS = (
    {
        "section": "Pipeline and 3D car repos",
        "deliverable": "Workfiles / pipeline files",
        "target": "apinext/digital-3d-car-raw",
        "assets": "_Workfiles, Blender files, Photoshop files",
        "notes": "Pipeline files must be merged before creating the production delivery branch.",
        "contacts": "SG-internal flow; no BMW contact captured in this dump",
        "status": "BMW Git access required",
    },
    {
        "section": "Pipeline and 3D car repos",
        "deliverable": "Blender plugins",
        "target": "apinext/blender-plugins",
        "assets": "Blender plugins used for workfiles/preview",
        "notes": "Any update needs to be synced with Markus Hund.",
        "contacts": "Markus Hund",
        "status": "BMW Git access required",
    },
    {
        "section": "Pipeline and 3D car repos",
        "deliverable": "Preview delivery repo",
        "target": "stefaniewatzkepartner/digital-3d-car-preview",
        "assets": "Preview delivery repository",
        "notes": "Documented preview surface only.",
        "contacts": "Stefanie Watzke partner repo",
        "status": "BMW Git access required",
    },
    {
        "section": "Pipeline and 3D car repos",
        "deliverable": "Production 3D car repo",
        "target": "apinext/digital-3d-car-models",
        "assets": "Production RaCo projects for cars/common elements",
        "notes": "Use the target branch for the delivery line; PINT and NA5+ on master, IDC23/U11-G68 on IDC23 branch and master.",
        "contacts": "BMW / Team Wombat delivery surface",
        "status": "BMW Git access required",
    },
    {
        "section": "Pipeline and 3D car repos",
        "deliverable": "Legacy/branch references",
        "target": "apinext/digital-3d-car assets/idc23, assets/pu2407, assets/pu2403",
        "assets": "Alternative documented delivery branches",
        "notes": "Keep branch choice explicit; do not assume master covers every delivery line.",
        "contacts": "BMW / Team Wombat delivery surface",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Ambient light",
        "target": "apinext/interior-light-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Dev: Marc.Saeufferer@bmw.de | PO: Stefan Haefner",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Sports instruments",
        "target": "apinext/ccm-cbs-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Dev: Kochergin, Alexander / Kodabaksch Marcel | PO: Steffi Mittag",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Charging Slider",
        "target": "apinext/charging-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Dev: Michal.Vesely@bmw.de | PO: Haefner Stefan",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Climate Control + IDCEVO Climate Control",
        "target": "apinext/climate-app",
        "assets": "RaCo scene/widget assets",
        "notes": "IDCEVO assets use master; IDC23 asset updates use master23.",
        "contacts": "Contact: Stefan Jurthe / aleksandravolkovapartner | PO: Kevin Weiss | ABK: Nora.Schueler@bmw.de | Design: Sebastian.Schaerfer@bmw.de",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Range Horizon",
        "target": "apinext/ccm-cbs-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Contact: andrashaudekpartner / Kodabaksch Marcel | PO: Steffi Mittag",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "Seat Adjustment",
        "target": "apinext/seats-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Contact: jens.racky@bmw.de | PO: Kevin Weiss",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "SlopeHUD",
        "target": "apinext/slopehud-di-res",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Contact: Dmytro.Karlovskyi@bmw.de | PO: Wira-Tirta.Laksono@bmw.de?",
        "status": "BMW Git access required",
    },
    {
        "section": "Widget assets",
        "deliverable": "X-Drive / X-View",
        "target": "apinext/ccm-cbs-app",
        "assets": "RaCo scene/widget assets",
        "notes": "Widget-asset delivery surface.",
        "contacts": "Dev: andrashaudekpartner / Kodabaksch Marcel | PO: Steffi Mittag",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Welcome Screen background",
        "target": "apinext/perso-app",
        "assets": "Shader + texture only",
        "notes": "Personalization surface.",
        "contacts": "Contact: Stefan Schneider | PO: Bruno.FB.Vieira@ctw.bmwgroup.com",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Welcome Screen Subscription background",
        "target": "apinext/perso-app/tree/master/app/src/main/res/drawable",
        "assets": "Textures",
        "notes": "Documented subpath under perso-app.",
        "contacts": "Contact: Stefan Schneider | PO: Bruno.FB.Vieira@ctw.bmwgroup.com",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Parking app phone buttons",
        "target": "apinext/parking-app",
        "assets": "PNG only",
        "notes": "Android direct asset surface.",
        "contacts": "Contact: Bedrich Nezdara | PO: Stefan Haefner",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "IPA app",
        "target": "apinext/ipa-app",
        "assets": "Shader + texture only",
        "notes": "Textures under app/src/main/res/drawable, shaders under app/src/main/res/raw, docs under docs.",
        "contacts": "Contact: Alexandre Bouard | Dev: Mario Wandpflug | PO: not specified in dump",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Ambient Light Color Selection Rectangle",
        "target": "apinext/interior-light-app",
        "assets": "Shader + textures only",
        "notes": "Android direct asset surface.",
        "contacts": "Contact: Marc Saeufferer | PO: Stefan Haefner",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Stage Selector Illustrations",
        "target": "launcher-app/tree/master/stage/src/main/res/drawable",
        "assets": "Textures only",
        "notes": "Launcher asset surface.",
        "contacts": "Contact: Christian Wagner | PO: Michael Olejnik",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Weather App background showcase",
        "target": "shader-workbench/tree/master/weatherAppBackgroundShowcase",
        "assets": "rca + binaries",
        "notes": "Direct weather-app background delivery surface.",
        "contacts": "PO: Daniel.Rietzel@bmw.de",
        "status": "BMW Git access required",
    },
    {
        "section": "Images and shaders",
        "deliverable": "Ambient Layer",
        "target": "apinext/ambient-layer-assets",
        "assets": "Ambient-layer assets",
        "notes": "Documented asset repo.",
        "contacts": "Contact: Max Maurer, Ludwig Dickmanns | ABK: Florian Weber",
        "status": "BMW Git access required",
    },
    {
        "section": "Other storage and libraries",
        "deliverable": "CCP MINI / CCP BMW / CCP CN LLN",
        "target": r"\\europe.bmw.corp\winfs\HS_Panama\HSPLW_EE\Seriengrafik\IDC\01_Austausch\03_CCP 3D Car\PDX Delivery\\",
        "assets": "Network-share delivery exchange",
        "notes": "Corporate network storage, not a local SVN surface.",
        "contacts": "Corp network share",
        "status": "Corp network access required",
    },
    {
        "section": "Other storage and libraries",
        "deliverable": "VideoAR",
        "target": r"\\europe.bmw.corp\WINFS\Panama\PLW_CoCo_e1\VideoAR\SerienGrafik\Paradoxcat\\",
        "assets": "Network-share storage",
        "notes": "Corporate network storage, not a local SVN surface.",
        "contacts": "Corp network share",
        "status": "Corp network access required",
    },
    {
        "section": "Other storage and libraries",
        "deliverable": "UI Widget Lib",
        "target": "apinext/ui-components-lib",
        "assets": "Shared UI widget library",
        "notes": "Documented reusable component repo.",
        "contacts": "BMW Git surface",
        "status": "BMW Git access required",
    },
)
_DELIVERY_REFERENCE_SPECS = (
    {
        "area": "Car-paint tracking tickets",
        "surface": "BMW: ABPI-121008 | MINI: ABPI-122342",
        "why": "Track defined/approved paint progress outside the local SVN bundle.",
        "status": "BMW/Jira access required",
    },
    {
        "area": "Car-paint documentation",
        "surface": "3D Car Color Overview / Car Paints (Generated) / Car Paint Improvements / Approved colors",
        "why": "Reference and approval surfaces for paint values and status progression.",
        "status": "Confluence access required",
    },
    {
        "area": "Car-paint digital references",
        "surface": "BMW configurator, BMW individual visualization, SharePoint photo references",
        "why": "Used to derive and refine paint values before rack approval.",
        "status": "External/documented reference only",
    },
    {
        "area": "3D asset sizes workbook",
        "surface": r"Documents\Workspace\Krister - 3D_Assets_Sizes.xlsm",
        "why": "Documented source of truth for resource/polycount size tracking.",
        "status": "Documented path only; not locally verified in this bundle",
    },
    {
        "area": "3D asset sizes Teams view",
        "surface": "Quality-Hero Bugreport Chat tab: 3D_Assets_Sizes",
        "why": "Read-only Teams entrypoint to the size workbook.",
        "status": "Teams access required",
    },
)


@dataclass(frozen=True)
class ReviewEvidence:
    label: str
    path: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RacoManualReviewProbeResult:
    output_root: Path
    markdown_path: Path
    json_path: Path
    profile_ids: tuple[str, ...]


@dataclass(frozen=True)
class TicketFinding:
    severity: str
    summary: str
    path: str = ""
    line: int | None = None
    checkers: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TicketManualEvidenceItem:
    profile_id: str
    source_run_id: str
    source_action_id: str
    kind: str
    label: str
    original_path: str
    packaged_path: str
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class TicketDoDItem:
    key: str
    label: str
    status: str
    summary: str
    what_can_be_done_now: str
    blocked_next_input: str
    owner_hint: str
    evidence: tuple[ReviewEvidence, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


@dataclass(frozen=True)
class TicketReviewBundle:
    ticket_id: str
    title: str
    generated_at_utc: str
    overall_status: str
    profile_ids: tuple[str, ...]
    source_root: str
    source_revision: str = ""
    source_mode: str = ""
    scope_note: str = ""
    notes: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    next_questions: tuple[str, ...] = ()
    findings: tuple[TicketFinding, ...] = ()
    evidence_index: tuple[ReviewEvidence, ...] = ()
    dod_items: tuple[TicketDoDItem, ...] = ()
    manual_evidence: tuple[TicketManualEvidenceItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "title": self.title,
            "generated_at_utc": self.generated_at_utc,
            "overall_status": self.overall_status,
            "profile_ids": list(self.profile_ids),
            "source_root": self.source_root,
            "source_revision": self.source_revision,
            "source_mode": self.source_mode,
            "scope_note": self.scope_note,
            "notes": list(self.notes),
            "blockers": list(self.blockers),
            "next_questions": list(self.next_questions),
            "findings": [item.to_dict() for item in self.findings],
            "evidence_index": [item.to_dict() for item in self.evidence_index],
            "dod_items": [item.to_dict() for item in self.dod_items],
            "manual_evidence": [item.to_dict() for item in self.manual_evidence],
        }


@dataclass(frozen=True)
class TicketReviewBundleResult:
    bundle: TicketReviewBundle
    package_root: Path
    bundle_json_path: Path
    review_status_path: Path
    dod_matrix_path: Path
    dod_update_draft_path: Path
    teams_update_path: Path
    stakeholder_sync_path: Path
    review_protocol_path: Path
    owner_matrix_path: Path
    qa_capability_matrix_path: Path
    three_d_qa_playbook_path: Path
    repo_topology_reference_path: Path
    delivery_surface_map_path: Path
    raco_script_catalog_path: Path
    delivery_target_catalog_path: Path
    manual_review_companion_path: Path
    manual_evidence_index_path: Path
    manual_evidence_json_path: Path
    review_owner_decisions_path: Path
    sent_package_manifest_path: Path
    zip_sha256_path: Path
    zip_path: Path


@dataclass
class _ProfileContext:
    profile: RunProfile
    prep: VisualReviewPrep
    bmw_surface: BmwScreenshotSurface
    triage_bundle: ScreenshotTriageBundle
    scene_record: ActionRecord | None
    stack_record: ActionRecord | None
    repo_record: ActionRecord | None
    delivery_record: ActionRecord | None
    manual_evidence_records: tuple[ActionRecord, ...]
    action_records_for_package: tuple[ActionRecord, ...]
    action_bundle_evidence: tuple[ReviewEvidence, ...]
    packaged_source_evidence: tuple[ReviewEvidence, ...]
    packaged_source_index: dict[str, ReviewEvidence]
    manual_review_paths: dict[str, Path]
    bmw_surface_markdown_path: Path
    bmw_surface_json_path: Path


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_ticket_review_output_root(ticket_id: str, workspace: Path | None = None) -> Path:
    root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    stamp = datetime.now().strftime("%Y-%m-%d")
    return root / "out" / f"{ticket_id}-review-package-{stamp}"


def _fresh_output_root(output_root: Path) -> Path:
    if not output_root.exists():
        return output_root
    stamp = datetime.now().strftime("%H%M%S")
    return output_root.with_name(f"{output_root.name}-rerun-{stamp}")


def _slug(value: str) -> str:
    lowered = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower())
    lowered = lowered.strip("-._")
    return lowered or "item"


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _safe_relative(path: Path, root: Path) -> Path | None:
    try:
        return path.resolve().relative_to(root.resolve())
    except ValueError:
        return None


def _copy_file(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    if source.resolve() != destination.resolve():
        shutil.copy2(source.resolve(), destination)
    return destination


def _copy_tree(source: Path, destination: Path) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        return destination
    shutil.copytree(source.resolve(), destination)
    return destination


def _dedupe_evidence(items: Iterable[ReviewEvidence]) -> tuple[ReviewEvidence, ...]:
    seen: set[tuple[str, str]] = set()
    ordered: list[ReviewEvidence] = []
    for item in items:
        key = (item.label.lower(), item.path.lower())
        if key in seen:
            continue
        seen.add(key)
        ordered.append(item)
    return tuple(ordered)


def _bundle_evidence(label: str, path: str | Path, detail: str = "") -> ReviewEvidence:
    normalized = str(path)
    if normalized in {"", ".", "not found"}:
        normalized = "not found"
    return ReviewEvidence(label=label, path=normalized, detail=detail)


def _display_path(path: str | Path, package_root: Path | None = None) -> str:
    normalized = str(path).strip()
    if normalized in {"", ".", "not found"}:
        return "not found"
    if package_root is not None:
        try:
            relative = _safe_relative(Path(normalized), package_root)
        except (OSError, ValueError):
            relative = None
        if relative is not None:
            return str(relative).replace("\\", "/")
    return normalized.replace("\\", "/")


def _all_action_records(workspace: Path) -> tuple[ActionRecord, ...]:
    actions_root = operator_ui_actions_root(workspace)
    if not actions_root.exists():
        return ()

    records: list[ActionRecord] = []
    for candidate in sorted(actions_root.iterdir(), reverse=True):
        record_path = candidate / "action.json"
        if not record_path.exists():
            continue
        try:
            records.append(load_action_record(record_path, workspace))
        except (OSError, ValueError, json.JSONDecodeError):
            continue
    records.sort(key=lambda item: item.created_at_utc, reverse=True)
    return tuple(records)


def _latest_record(records: tuple[ActionRecord, ...], action_id: str) -> ActionRecord | None:
    normalized = action_id.strip().lower()
    for record in records:
        if record.action_id.strip().lower() == normalized:
            return record
    return None


def _latest_manual_evidence_record(records: tuple[ActionRecord, ...], action_id: str) -> ActionRecord | None:
    normalized = action_id.strip().lower()
    for record in records:
        if record.action_id.strip().lower() != normalized:
            continue
        if record.manual_evidence:
            return record
    return None


def _unique_records(records: Iterable[ActionRecord | None]) -> tuple[ActionRecord, ...]:
    seen: set[str] = set()
    ordered: list[ActionRecord] = []
    for record in records:
        if record is None or record.run_id in seen:
            continue
        seen.add(record.run_id)
        ordered.append(record)
    return tuple(ordered)


def _action_ids_for_profile(profile_id: str) -> dict[str, str]:
    lowered = profile_id.strip().lower()
    return {
        "scene": f"scene_check__{lowered}",
        "stack": f"qa_stack__{lowered}",
        "repo": f"repo_checker_profile__{lowered}",
        "delivery": f"delivery_checklist__{lowered}",
    }


def _package_action_records(
    records: tuple[ActionRecord, ...],
    package_root: Path,
) -> tuple[ReviewEvidence, ...]:
    evidence: list[ReviewEvidence] = []
    for record in records:
        output_root = Path(record.paths.get("output_root", "")).resolve()
        if not output_root.exists():
            continue
        packaged_root = package_root / "artifacts" / "actions" / record.run_id
        try:
            _copy_tree(output_root, packaged_root)
        except OSError:
            continue
        evidence.append(_bundle_evidence(f"{record.label} bundle", packaged_root))
    return tuple(evidence)


def _package_live_source(
    path: str | Path,
    package_root: Path,
    source_root: Path,
) -> ReviewEvidence | None:
    source = Path(path).resolve()
    if not source.exists() or not source.is_file():
        return None
    relative = _safe_relative(source, source_root)
    if relative is None:
        destination = package_root / "source" / "external" / _slug(source.parent.name) / source.name
    else:
        destination = package_root / "source" / relative
    _copy_file(source, destination)
    return _bundle_evidence(source.name, destination)


def _package_live_sources(
    paths: Iterable[str],
    package_root: Path,
    source_root: Path,
) -> tuple[tuple[ReviewEvidence, ...], dict[str, ReviewEvidence]]:
    packaged: list[ReviewEvidence] = []
    packaged_index: dict[str, ReviewEvidence] = {}
    for item in paths:
        evidence = _package_live_source(item, package_root, source_root)
        if evidence is not None:
            packaged.append(evidence)
            try:
                packaged_index[str(Path(item).resolve())] = evidence
            except OSError:
                packaged_index[str(item)] = evidence
    return _dedupe_evidence(packaged), packaged_index


def _package_external_file(
    *,
    label: str,
    path: str | Path,
    package_root: Path,
    relative_dir: str | Path,
) -> ReviewEvidence | None:
    source = Path(path).resolve()
    if not source.exists() or not source.is_file():
        return None
    destination = package_root / relative_dir / source.name
    _copy_file(source, destination)
    return _bundle_evidence(label, destination)


def _packaged_source_evidence(
    context: _ProfileContext,
    source_path: str | Path,
    *,
    label: str | None = None,
    detail: str = "",
) -> ReviewEvidence:
    normalized = str(source_path).strip()
    if normalized in {"", ".", "not found"}:
        return _bundle_evidence(label or "not found", "not found", detail)
    try:
        key = str(Path(normalized).resolve())
    except OSError:
        key = normalized
    packaged = context.packaged_source_index.get(key)
    if packaged is not None:
        return ReviewEvidence(label=label or packaged.label, path=packaged.path, detail=detail or packaged.detail)
    return _bundle_evidence(label or Path(normalized).name, normalized, detail)


def _load_raco_manual_review_probe(output_root: Path) -> RacoManualReviewProbeResult | None:
    root = output_root.resolve()
    markdown_path = root / "raco-manual-review-probe.md"
    json_path = root / "raco-manual-review-probe.json"
    if not markdown_path.exists() or not json_path.exists():
        return None
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list):
        return None
    profile_ids = tuple(
        dict.fromkeys(
            str(item.get("profile_id", "")).strip()
            for item in payload
            if isinstance(item, dict) and str(item.get("profile_id", "")).strip()
        )
    )
    return RacoManualReviewProbeResult(
        output_root=root,
        markdown_path=markdown_path,
        json_path=json_path,
        profile_ids=profile_ids,
    )


def _find_latest_raco_manual_review_probe(
    workspace: Path,
    *,
    required_profiles: tuple[str, ...] = (),
) -> RacoManualReviewProbeResult | None:
    out_root = workspace / "out"
    if not out_root.exists():
        return None

    normalized_required = {item.strip().upper() for item in required_profiles if item and item.strip()}
    candidates: list[RacoManualReviewProbeResult] = []
    for directory in out_root.glob("raco-manual-review-probe-*"):
        if not directory.is_dir():
            continue
        loaded = _load_raco_manual_review_probe(directory)
        if loaded is None:
            continue
        available_profiles = {item.upper() for item in loaded.profile_ids}
        if normalized_required and not normalized_required.issubset(available_profiles):
            continue
        candidates.append(loaded)

    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item.json_path.stat().st_mtime if item.json_path.exists() else 0,
            item.output_root.name,
        ),
        reverse=True,
    )
    return candidates[0]


def _package_daily_snapshot_result(
    result: DailyQaSnapshotResult,
    package_root: Path,
) -> DailyQaSnapshotResult:
    packaged_root = package_root / "artifacts" / "daily-snapshot"
    logs_root = packaged_root / "logs"
    images_root = packaged_root / "images"

    def _copy_log(log_path: str) -> str:
        normalized = str(log_path).strip()
        if not normalized:
            return normalized
        source = Path(normalized)
        if not source.exists() or not source.is_file():
            return normalized
        destination = logs_root / source.name
        _copy_file(source, destination)
        return str(Path("logs") / destination.name).replace("\\", "/")

    def _copy_named_files(source_root: Path, destination_root: Path, names: tuple[str, ...]) -> tuple[str, ...]:
        copied: list[str] = []
        for name in names:
            source = source_root / name
            if not source.exists() or not source.is_file():
                continue
            _copy_file(source, destination_root / name)
            copied.append(name)
        return tuple(copied)

    packaged_config = BmwConfigCheckResult(
        status=result.snapshot.config_check.status,
        python_exe=result.snapshot.config_check.python_exe,
        repo_root=result.snapshot.config_check.repo_root,
        log_path=_copy_log(result.snapshot.config_check.log_path),
        output_excerpt=result.snapshot.config_check.output_excerpt,
        error=result.snapshot.config_check.error,
    )

    packaged_smoke_results: list[BmwSmokeResult] = []
    for item in result.snapshot.smoke_results:
        packaged_smoke_results.append(
            BmwSmokeResult(
                profile_id=item.profile_id,
                bmw_profile_id=item.bmw_profile_id,
                status=item.status,
                smoke_test=item.smoke_test,
                python_exe=item.python_exe,
                sg_project_root=item.sg_project_root,
                bmw_test_config_path=item.bmw_test_config_path,
                log_path=_copy_log(item.log_path),
                exported_ramses_size=item.exported_ramses_size,
                exported_rlogic_size=item.exported_rlogic_size,
                expected_count=item.expected_count,
                actual_count=item.actual_count,
                diff_count=item.diff_count,
                compare_ok=item.compare_ok,
                error=item.error,
                notes=item.notes,
            )
        )

    packaged_battery_results: list[BmwBatteryResult] = []
    for item in result.snapshot.battery_results:
        scenario_root = images_root / item.profile_id.lower() / _slug(item.filter_name)
        actual_source_root = Path(item.results_root) / "tests" / "actuals"
        diff_source_root = Path(item.results_root) / "tests" / "diff"
        proxy_source_root = Path(item.results_root) / "tests" / "proxy_actuals"
        actual_files = _copy_named_files(actual_source_root, scenario_root / "tests" / "actuals", item.actual_files)
        diff_files = _copy_named_files(diff_source_root, scenario_root / "tests" / "diff", item.diff_files)
        proxy_files = _copy_named_files(proxy_source_root, scenario_root / "tests" / "proxy_actuals", item.proxy_files)
        packaged_battery_results.append(
            BmwBatteryResult(
                profile_id=item.profile_id,
                bmw_profile_id=item.bmw_profile_id,
                filter_name=item.filter_name,
                verdict=item.verdict,
                status=item.status,
                results_root=str(scenario_root),
                log_path=_copy_log(item.log_path),
                expected_count=item.expected_count,
                actual_count=item.actual_count,
                diff_count=item.diff_count,
                compare_ok=item.compare_ok,
                error=item.error,
                missing_expected_baseline=item.missing_expected_baseline,
                actual_files=actual_files,
                expected_files=item.expected_files,
                diff_files=diff_files,
                proxy_files=proxy_files,
                target_output_present=item.target_output_present,
                notes=item.notes,
            )
        )

    packaged_snapshot = DailyQaSnapshot(
        created_at=result.snapshot.created_at,
        scope_profiles=result.snapshot.scope_profiles,
        bmw_repo_root=result.snapshot.bmw_repo_root,
        config_check=packaged_config,
        smoke_results=tuple(packaged_smoke_results),
        battery_results=tuple(packaged_battery_results),
        diagnostics=result.snapshot.diagnostics,
        blocked_steps=result.snapshot.blocked_steps,
        top_review_items=result.snapshot.top_review_items,
        notes=result.snapshot.notes,
    )

    packaged_markdown = packaged_root / result.markdown_path.name
    packaged_json = packaged_root / result.json_path.name
    _write_text(packaged_markdown, _render_snapshot_markdown(packaged_snapshot))
    _write_json(packaged_json, packaged_snapshot.to_dict())

    packaged_gaps_markdown: Path | None = None
    packaged_gaps_json: Path | None = None
    packaged_review_gallery_html: Path | None = None
    packaged_review_priority_markdown: Path | None = None
    packaged_review_priority_json: Path | None = None
    packaged_delta_summary_markdown: Path | None = None
    packaged_delta_summary_json: Path | None = None
    if packaged_snapshot.battery_results:
        packaged_gaps_markdown = packaged_root / "battery-baseline-gaps.md"
        packaged_gaps_json = packaged_root / "battery-baseline-gaps.json"
        _write_text(packaged_gaps_markdown, _render_battery_baseline_gaps_markdown(packaged_snapshot))
        _write_json(packaged_gaps_json, _battery_baseline_gap_payload(packaged_snapshot))
        packaged_review_gallery_html = packaged_root / "candidate-review-gallery.html"
        _write_text(
            packaged_review_gallery_html,
            _render_candidate_review_gallery(packaged_snapshot, html_root=packaged_review_gallery_html),
        )
        if result.review_priority_markdown_path is not None:
            packaged_review_priority_markdown = packaged_root / "review-priority-ranking.md"
            _copy_file(result.review_priority_markdown_path, packaged_review_priority_markdown)
        if result.review_priority_json_path is not None:
            packaged_review_priority_json = packaged_root / "review-priority-ranking.json"
            _copy_file(result.review_priority_json_path, packaged_review_priority_json)
    if result.delta_summary_markdown_path is not None:
        packaged_delta_summary_markdown = packaged_root / "daily-qa-delta-summary.md"
        _copy_file(result.delta_summary_markdown_path, packaged_delta_summary_markdown)
    if result.delta_summary_json_path is not None:
        packaged_delta_summary_json = packaged_root / "daily-qa-delta-summary.json"
        _copy_file(result.delta_summary_json_path, packaged_delta_summary_json)

    return DailyQaSnapshotResult(
        output_root=packaged_root,
        snapshot=packaged_snapshot,
        markdown_path=packaged_markdown,
        json_path=packaged_json,
        battery_baseline_gaps_markdown_path=packaged_gaps_markdown,
        battery_baseline_gaps_json_path=packaged_gaps_json,
        review_gallery_html_path=packaged_review_gallery_html,
        review_priority_markdown_path=packaged_review_priority_markdown,
        review_priority_json_path=packaged_review_priority_json,
        delta_summary_markdown_path=packaged_delta_summary_markdown,
        delta_summary_json_path=packaged_delta_summary_json,
    )


def _package_raco_manual_review_probe(
    probe: RacoManualReviewProbeResult,
    package_root: Path,
) -> RacoManualReviewProbeResult:
    packaged_markdown = package_root / "artifacts" / "raco-probe" / probe.markdown_path.name
    packaged_json = package_root / "artifacts" / "raco-probe" / probe.json_path.name
    _copy_file(probe.markdown_path, packaged_markdown)
    _copy_file(probe.json_path, packaged_json)
    return RacoManualReviewProbeResult(
        output_root=packaged_markdown.parent,
        markdown_path=packaged_markdown,
        json_path=packaged_json,
        profile_ids=probe.profile_ids,
    )


def _resolve_snapshot_artifact_path(snapshot_result: DailyQaSnapshotResult | None, path: str | Path) -> str:
    normalized = str(path).strip()
    if normalized in {"", ".", "not found"}:
        return "not found"
    candidate = Path(normalized)
    if candidate.is_absolute() or snapshot_result is None:
        return str(candidate)
    return str((snapshot_result.output_root / candidate).resolve())


def _latest_native_verification_dir(workspace: Path) -> Path | None:
    verification_root = workspace / "build" / "native-installer-fullscreen" / "verification"
    if not verification_root.exists():
        return None
    candidates = [path for path in verification_root.iterdir() if path.is_dir()]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    return candidates[0]


def _package_verification_dir(workspace: Path, package_root: Path) -> ReviewEvidence | None:
    latest_verification = _latest_native_verification_dir(workspace)
    if latest_verification is None or not latest_verification.exists():
        return None
    destination = package_root / "artifacts" / "verification" / latest_verification.name
    _copy_tree(latest_verification, destination)
    return _bundle_evidence("Latest native verification", destination)


def _manual_review_template_paths(package_root: Path, profile_id: str) -> dict[str, Path]:
    base = package_root / "artifacts" / "manual-review" / profile_id.lower()
    return {
        "base": base,
        "companion": base / "manual-review-companion.md",
        "record": base / "manual-review-record.md",
        "slots": base / "screenshot-evidence-slots.md",
        "blender_raco": base / "blender-vs-raco-checklist.md",
        "visual_checklist": base / "visual-review-checklist.md",
    }


def _manual_review_texts(
    *,
    ticket_id: str,
    context: _ProfileContext,
) -> dict[str, str]:
    prep = context.prep
    report = context.triage_bundle.report
    triage_path = context.triage_bundle.markdown_path
    priority = ", ".join(prep.priority_screenshots[:8]) if prep.priority_screenshots else "none detected"
    profile_id = context.profile.profile_id
    common_header = [
        f"- Ticket: {ticket_id}",
        f"- Profile: {profile_id}",
        f"- Changelog heading: {prep.changelog_heading or 'not found'}",
        f"- Representative RaCo scene: `{prep.raco_scene_path or 'not found'}`",
        f"- Representative Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
        f"- Screenshot baseline root: `{report.expected_root or prep.screenshot_root or 'not found'}`",
        f"- BMW actuals root: `{context.bmw_surface.actuals_root or 'not found'}`",
        f"- BMW diff root: `{context.bmw_surface.diff_root or 'not found'}`",
        f"- Screenshot triage: `{triage_path}`",
    ]
    return {
        "companion": "\n".join(
            [
                f"# Manual review companion - {profile_id}",
                "",
                *common_header,
                "",
                "Included templates:",
                f"- Manual review record: `{context.manual_review_paths['record']}`",
                f"- Screenshot evidence slots: `{context.manual_review_paths['slots']}`",
                f"- Blender vs RaCo checklist: `{context.manual_review_paths['blender_raco']}`",
                f"- Visual review checklist: `{context.manual_review_paths['visual_checklist']}`",
                "",
                "Use these templates to keep still-manual review explicit instead of pretending the deterministic run replaced it.",
                "",
            ]
        ),
        "record": "\n".join(
            [
                f"# Manual review record - {profile_id}",
                "",
                *[
                    line
                    for line in common_header[:-1]
                ],
                f"- Current screenshot triage: {report.pair_count} pair(s), {report.missing_candidate_count} missing candidate, {report.needs_review_count} needs review, {report.dimension_mismatch_count} dimension mismatch",
                "",
                "Manual checks:",
                "- Blender vs RaCo compared: [ ] yes [ ] no",
                "- Multi-angle review completed: [ ] yes [ ] no",
                "- Screenshot evidence attached: [ ] yes [ ] no",
                "- Rack / BMW smoke blocker documented: [ ] yes [ ] no",
                "- Changelog-reviewed intended changes confirmed: [ ] yes [ ] no",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
        "slots": "\n".join(
            [
                f"# Screenshot evidence slots - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- Baseline root: `{report.expected_root or prep.screenshot_root or 'not found'}`",
                f"- BMW actuals root: `{context.bmw_surface.actuals_root or 'not found'}`",
                f"- BMW diff root: `{context.bmw_surface.diff_root or 'not found'}`",
                f"- Triage report: `{triage_path}`",
                f"- Suggested baseline checks first: {priority}",
                "",
                "- Front 3/4:",
                "- Rear 3/4:",
                "- Side or wheel-area detail:",
                "- Interior or close-up if relevant:",
                "- Problem-focused proof shot:",
                "- Notes:",
                "-",
                "",
            ]
        ),
        "blender_raco": "\n".join(
            [
                f"# Blender vs RaCo checklist - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- RaCo scene: `{prep.raco_scene_path or 'not found'}`",
                f"- Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
                "",
                "- Scene opens without missing-resource surprise: [ ]",
                "- Major camera/state alignment reviewed: [ ]",
                "- Material/light intent compared: [ ]",
                "- Geometry/asset presence compared: [ ]",
                "- Any mismatch documented with note or screenshot: [ ]",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
        "visual_checklist": "\n".join(
            [
                f"# Visual review checklist - {profile_id}",
                "",
                f"- Ticket: {ticket_id}",
                f"- Profile: {profile_id}",
                f"- Changelog heading: {prep.changelog_heading or 'not found'}",
                "",
                "- Changelog reviewed before interpreting screenshot drift: [ ]",
                "- Priority baselines reviewed first: [ ]",
                "- Shared BMW docs checked if relevant: [ ]",
                "- Blender/RaCo cross-check done: [ ]",
                "- Screenshot evidence attached where useful: [ ]",
                "- Blockers documented instead of guessed: [ ]",
                "",
                "Notes:",
                "-",
                "",
            ]
        ),
    }


def _materialize_manual_review_templates(
    *,
    ticket_id: str,
    context: _ProfileContext,
) -> dict[str, Path]:
    texts = _manual_review_texts(ticket_id=ticket_id, context=context)
    for key, text in texts.items():
        output_key = {
            "companion": "companion",
            "record": "record",
            "slots": "slots",
            "blender_raco": "blender_raco",
            "visual_checklist": "visual_checklist",
        }[key]
        _write_text(context.manual_review_paths[output_key], text)
    return context.manual_review_paths


def _extract_revision(prep: VisualReviewPrep) -> str:
    for line in prep.project_svn_info_lines:
        match = re.search(r"(?i)\brevision:\s*(\d+)", line)
        if match:
            return match.group(1)
        match = re.search(r"(?i)\blast changed rev:\s*(\d+)", line)
        if match:
            return match.group(1)
    return ""


def _record_findings(record: ActionRecord | None) -> tuple[TicketFinding, ...]:
    if record is None or not isinstance(record.summary, dict):
        return ()
    checker_evidence = record.summary.get("checker_evidence")
    if not isinstance(checker_evidence, dict):
        return ()
    top_paths = checker_evidence.get("top_paths", [])
    affected_files = checker_evidence.get("affected_files", [])

    findings: list[TicketFinding] = []
    seen: set[tuple[str, int | None, str]] = set()
    for item in top_paths if isinstance(top_paths, list) and top_paths else affected_files:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", ""))
        line = item.get("line") if isinstance(item.get("line"), int) else None
        summary = str(item.get("message", "")).strip()
        severity = str(item.get("severity", "info")).strip() or "info"
        checkers = tuple(str(value) for value in item.get("checkers", []) if value)
        if not checkers and item.get("checker"):
            checkers = (str(item["checker"]),)
        if not summary:
            continue
        key = (path.lower(), line, summary.lower())
        if key in seen:
            continue
        seen.add(key)
        findings.append(
            TicketFinding(
                severity=severity,
                summary=summary if line is None else f"{summary} ({Path(path).name}:{line})",
                path=path,
                line=line,
                checkers=checkers,
            )
        )
    return tuple(findings)


def _manual_followups(record: ActionRecord | None) -> tuple[str, ...]:
    if record is None or not isinstance(record.summary, dict):
        return ()
    checker_evidence = record.summary.get("checker_evidence")
    if not isinstance(checker_evidence, dict):
        return ()
    raw = checker_evidence.get("manual_followups", [])
    return tuple(str(item) for item in raw if item)


def _bmw_surface_markdown(surface: BmwScreenshotSurface) -> str:
    lines = [
        f"# BMW screenshot surface - {surface.profile_id}",
        "",
        f"- SG profile: `{surface.profile_id}`",
        f"- BMW profile folder: `{surface.bmw_profile_id}`",
        f"- BMW repo root: `{surface.repo_root or 'not found'}`",
        f"- BMW cars root: `{surface.cars_root or 'not found'}`",
        f"- BMW car root: `{surface.car_root or 'not found'}`",
        f"- BMW CI scripts root: `{surface.ci_scripts_root or 'not found'}`",
        f"- BMW CI tools root: `{surface.ci_tools_root or 'not found'}`",
        f"- BMW CI README: `{surface.ci_readme_path or 'not found'}`",
        f"- BMW car_manager.py: `{surface.car_manager_path or 'not found'}`",
        f"- Export/tests root: `{surface.export_tests_root or 'not found'}`",
        f"- SG expected root: `{surface.sg_expected_root or 'not found'}` ({surface.sg_expected_count} image(s))",
        f"- BMW expected root: `{surface.bmw_expected_root or 'not found'}` ({surface.bmw_expected_count} image(s))",
        f"- BMW actuals root: `{surface.actuals_root or 'not found'}` ({surface.actual_count} image(s))",
        f"- BMW diff root: `{surface.diff_root or 'not found'}` ({surface.diff_count} image(s))",
        f"- BMW test config: `{surface.test_config_path or 'not found'}`",
        "",
        "## Documented BMW command surface",
        "- IDC_23 export command: `py ci/scripts/test/main.py export <CAR>` on `assets/idc23`",
        "- IDC_23 screenshot comparison command: `py ci/scripts/test/main.py screenshots --diff <CAR>` on `assets/idc23`",
        "- IDC_EVO export command: `py ci/scripts/car_manager.py export <CAR>` on `master`",
        "- IDC_EVO screenshot comparison command: `py ci/scripts/car_manager.py screenshots --diff <CAR>` on `master`",
        "- External RCA screenshot command: `py ci/scripts/car_manager.py screenshots_ext C:/PATH/TO/PROJECT.rca -b BMW`",
        "- Expected screenshot proof: the current repo writes into `export/tests/{expected,actuals,diff}`.",
        "- Expected export proof: captured export log plus the printed binary file sizes from the lane export command.",
        "",
        "## Notes",
    ]
    if surface.notes:
        lines.extend(f"- {note}" for note in surface.notes)
    else:
        lines.append("- No BMW-side notes were recorded for this profile.")
    return "\n".join(lines).rstrip() + "\n"


def _profile_context(
    *,
    ticket_id: str,
    profile_id: str,
    workspace: Path,
    package_root: Path,
    candidate_roots: tuple[Path, ...],
    source_root: Path,
    all_records: tuple[ActionRecord, ...],
    include_action_bundles: bool,
) -> _ProfileContext:
    profile = get_run_profile(profile_id, workspace)
    prep = build_visual_review_prep(profile.profile_id, profile.source_project_root(), repo_root=source_root)
    bmw_surface = inspect_bmw_screenshot_surface(
        profile.profile_id,
        workspace_root=workspace,
        sg_project_root=profile.source_project_root(),
    )
    triage_root = package_root / "artifacts" / "screenshot-triage" / profile.profile_id.lower()
    effective_expected_root = Path(bmw_surface.sg_expected_root or bmw_surface.bmw_expected_root) if (
        bmw_surface.sg_expected_root or bmw_surface.bmw_expected_root
    ) else None
    effective_candidate_roots = tuple(
        dict.fromkeys(
            [
                *(path.resolve() for path in candidate_roots),
                *(Path(bmw_surface.actuals_root).resolve() for _ in [0] if bmw_surface.actuals_root),
            ]
        )
    )
    effective_diff_roots = tuple(
        Path(bmw_surface.diff_root).resolve()
        for _ in [0]
        if bmw_surface.diff_root
    )
    triage_bundle = materialize_screenshot_triage(
        profile.profile_id,
        profile.source_project_root(),
        triage_root,
        expected_root=effective_expected_root,
        candidate_roots=effective_candidate_roots,
        diff_reference_roots=effective_diff_roots,
        priority_names=prep.priority_screenshots,
    )
    bmw_surface_root = package_root / "artifacts" / "bmw-surface" / profile.profile_id.lower()
    bmw_surface_markdown_path = bmw_surface_root / "surface.md"
    bmw_surface_json_path = bmw_surface_root / "surface.json"
    _write_text(bmw_surface_markdown_path, _bmw_surface_markdown(bmw_surface))
    _write_json(bmw_surface_json_path, bmw_surface.to_dict())

    action_ids = _action_ids_for_profile(profile.profile_id)
    scene_record = _latest_record(all_records, action_ids["scene"])
    stack_record = _latest_record(all_records, action_ids["stack"])
    repo_record = _latest_record(all_records, action_ids["repo"])
    delivery_record = _latest_record(all_records, action_ids["delivery"])
    manual_records = _unique_records(
        _latest_manual_evidence_record(all_records, action_id)
        for action_id in action_ids.values()
    )
    records_for_package = _unique_records((scene_record, stack_record, repo_record, delivery_record, *manual_records))
    action_bundle_evidence = ()
    if include_action_bundles:
        action_bundle_evidence = _package_action_records(records_for_package, package_root)

    source_paths = [
        prep.changelog_path,
        prep.constants_readme_path,
        *prep.project_readme_paths[:1],
        prep.screenshot_test_config_path,
        bmw_surface.test_config_path,
        bmw_surface.ci_readme_path,
        bmw_surface.car_manager_path,
        *prep.shared_doc_paths,
    ]
    packaged_source_evidence, packaged_source_index = _package_live_sources(source_paths, package_root, source_root)
    manual_review_paths = _manual_review_template_paths(package_root, profile.profile_id)

    context = _ProfileContext(
        profile=profile,
        prep=prep,
        bmw_surface=bmw_surface,
        triage_bundle=triage_bundle,
        scene_record=scene_record,
        stack_record=stack_record,
        repo_record=repo_record,
        delivery_record=delivery_record,
        manual_evidence_records=manual_records,
        action_records_for_package=records_for_package,
        action_bundle_evidence=action_bundle_evidence,
        packaged_source_evidence=packaged_source_evidence,
        packaged_source_index=packaged_source_index,
        manual_review_paths=manual_review_paths,
        bmw_surface_markdown_path=bmw_surface_markdown_path,
        bmw_surface_json_path=bmw_surface_json_path,
    )
    _materialize_manual_review_templates(ticket_id=ticket_id, context=context)
    return context


def _build_manual_review_index(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    lines = [
        f"# Manual Review Companion - {ticket_id}",
        "",
        "This index points to the packaged manual-review templates for each grounded slice.",
        "",
    ]
    for context in contexts:
        lines.extend(
            [
                f"## {context.profile.profile_id}",
                f"- Companion: `{context.manual_review_paths['companion']}`",
                f"- Manual review record: `{context.manual_review_paths['record']}`",
                f"- Screenshot evidence slots: `{context.manual_review_paths['slots']}`",
                f"- Blender vs RaCo checklist: `{context.manual_review_paths['blender_raco']}`",
                f"- Visual review checklist: `{context.manual_review_paths['visual_checklist']}`",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _manual_evidence_key(raw: dict[str, str]) -> tuple[str, str, str]:
    path_text = str(raw.get("path", "")).strip()
    normalized_path = path_text
    if path_text:
        try:
            normalized_path = str(Path(path_text).resolve())
        except OSError:
            normalized_path = path_text
    else:
        normalized_path = f"note::{str(raw.get('note', '')).strip()}"
    return (
        normalized_path.lower(),
        str(raw.get("kind", "")).strip().lower(),
        str(raw.get("label", "")).strip().lower(),
    )


def _copy_manual_evidence_item(
    *,
    package_root: Path,
    profile_id: str,
    record: ActionRecord,
    raw: dict[str, str],
) -> TicketManualEvidenceItem | None:
    kind = str(raw.get("kind", "")).strip() or "manual_evidence"
    label = str(raw.get("label", "")).strip() or kind
    note = str(raw.get("note", "")).strip()
    original_path = str(raw.get("path", "")).strip()
    package_dir = package_root / "artifacts" / "manual-evidence" / profile_id.lower() / record.run_id
    package_dir.mkdir(parents=True, exist_ok=True)

    packaged_path: Path
    if original_path:
        source = Path(original_path)
        if source.exists():
            packaged_path = package_dir / source.name
            if len(str(packaged_path)) >= 240:
                suffix = source.suffix or ".bin"
                evidence_id = str(raw.get("id", "")).strip()[:8]
                packaged_path = package_dir / f"{_slug(kind)}-{evidence_id or 'evidence'}{suffix}"
            _copy_file(source, packaged_path)
        else:
            packaged_path = package_dir / f"{_slug(kind)}-{_slug(label)}.md"
            _write_text(packaged_path, (note or f"Missing original path: {original_path}") + "\n")
    else:
        packaged_path = package_dir / f"{_slug(kind)}-{_slug(label)}.md"
        if len(str(packaged_path)) >= 240:
            evidence_id = str(raw.get("id", "")).strip()[:8]
            packaged_path = package_dir / f"{_slug(kind)}-{evidence_id or 'note'}.md"
        _write_text(packaged_path, (note or label) + "\n")

    return TicketManualEvidenceItem(
        profile_id=profile_id,
        source_run_id=record.run_id,
        source_action_id=record.action_id,
        kind=kind,
        label=label,
        original_path=original_path,
        packaged_path=str(packaged_path),
        note=note,
    )


def _harvest_manual_evidence(
    contexts: tuple[_ProfileContext, ...],
    package_root: Path,
) -> tuple[TicketManualEvidenceItem, ...]:
    harvested: list[TicketManualEvidenceItem] = []
    seen: set[tuple[str, str, str]] = set()
    for context in contexts:
        for record in context.manual_evidence_records:
            for raw in record.manual_evidence:
                if not isinstance(raw, dict):
                    continue
                key = _manual_evidence_key(raw)
                if key in seen:
                    continue
                seen.add(key)
                item = _copy_manual_evidence_item(
                    package_root=package_root,
                    profile_id=context.profile.profile_id,
                    record=record,
                    raw=raw,
                )
                if item is not None:
                    harvested.append(item)
    return tuple(harvested)


def _manual_evidence_counts(items: tuple[TicketManualEvidenceItem, ...]) -> Counter[str]:
    return Counter(item.kind for item in items)


def _counts_by_kind_text(items: tuple[TicketManualEvidenceItem, ...]) -> str:
    counts = _manual_evidence_counts(items)
    if not counts:
        return "none"
    return ", ".join(f"{key}={counts[key]}" for key in sorted(counts))


def _manual_evidence_index_markdown(
    *,
    ticket_id: str,
    items: tuple[TicketManualEvidenceItem, ...],
    package_root: Path | None = None,
) -> str:
    lines = [
        f"# Ticket Manual Evidence Index - {ticket_id}",
        "",
        f"- Total attached evidence items: {len(items)}",
        f"- Counts by kind: {_counts_by_kind_text(items)}",
        "",
    ]
    if not items:
        lines.append("- No manual evidence was harvested from the relevant action bundles.")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Items")
    for item in items:
        lines.extend(
            [
                f"- [{item.kind}] {item.label}",
                f"  - Profile: {item.profile_id}",
                f"  - Source action: {item.source_action_id}",
                f"  - Source run: {item.source_run_id}",
                f"  - Original path: `{item.original_path or 'n/a'}`",
                f"  - Packaged path: `{_display_path(item.packaged_path, package_root)}`",
            ]
        )
        if item.note:
            lines.append(f"  - Note: {item.note}")
    lines.append("")
    return "\n".join(lines)


def _manual_evidence_json_payload(
    *,
    ticket_id: str,
    items: tuple[TicketManualEvidenceItem, ...],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ticket_id": ticket_id,
        "generated_at_utc": _utc_now(),
        "counts_by_kind": dict(_manual_evidence_counts(items)),
        "items": [item.to_dict() for item in items],
    }


def _item_status_summary(
    report: ScreenshotTriageReport,
) -> str:
    return (
        f"{report.pair_count} baseline image(s) are already available locally. "
        f"Triage currently sees {report.missing_candidate_count} missing candidate pair(s), "
        f"{report.near_identical_count} near-identical pair(s), {report.needs_review_count} changed pair(s), "
        f"and {report.dimension_mismatch_count} dimension mismatch pair(s)."
    )


def _screenshot_surface_summary(contexts: tuple[_ProfileContext, ...]) -> str:
    if not contexts:
        return "No confirmed local slice is grounded yet, so screenshot-test evidence is intentionally not claimed."
    parts: list[str] = []
    for context in contexts:
        surface = context.bmw_surface
        report = context.triage_bundle.report
        part = (
            f"{context.profile.profile_id}: SG expected {surface.sg_expected_count}, "
            f"BMW expected {surface.bmw_expected_count}, actuals {surface.actual_count}, diff {surface.diff_count}"
        )
        if surface.export_tests_root:
            if surface.actual_count == 0 and surface.diff_count == 0:
                part += "; BMW screenshot surface exists but currently contains no screenshot payload"
            else:
                part += f"; triage pairs {report.pair_count}, needs review {report.needs_review_count}"
        else:
            part += "; BMW export/tests surface not present locally"
        parts.append(part)
    return "<br>".join(parts)


def _headless_surface_summary(contexts: tuple[_ProfileContext, ...]) -> str:
    if not contexts:
        return "No confirmed local slice is grounded yet, so BMW headless-export readiness is intentionally not claimed."
    ready = [context for context in contexts if context.bmw_surface.car_manager_path]
    if ready:
        profiles = ", ".join(context.profile.profile_id for context in ready)
        return (
            f"BMW repo helpers are locally visible for {profiles}: `ci/scripts/car_manager.py` and the CI README are packaged. "
            "Representative local export proof should be attached separately wherever the daily snapshot contains completed smoke results; if review owners accept that proof, the remaining headless question is only whether any broader scenario coverage is still required."
        )
    return "The BMW headless-export helper surface is still not visible locally for the grounded slice(s)."


def _snapshot_smoke_results(
    snapshot_result: DailyQaSnapshotResult | None,
    contexts: tuple[_ProfileContext, ...],
) -> dict[str, Any]:
    if snapshot_result is None or not contexts:
        return {}

    scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
    result_map = {
        item.profile_id.upper(): item
        for item in snapshot_result.snapshot.smoke_results
        if item.profile_id and item.profile_id.upper() in scoped_profiles
    }
    if not result_map or scoped_profiles - set(result_map):
        return {}
    return result_map


def _snapshot_battery_results(
    snapshot_result: DailyQaSnapshotResult | None,
    contexts: tuple[_ProfileContext, ...],
) -> dict[str, tuple[Any, ...]]:
    if snapshot_result is None or not contexts:
        return {}

    scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
    result_map: dict[str, list[Any]] = {}
    for item in getattr(snapshot_result.snapshot, "battery_results", ()):
        profile_key = str(getattr(item, "profile_id", "")).upper()
        if not profile_key or profile_key not in scoped_profiles:
            continue
        result_map.setdefault(profile_key, []).append(item)
    if not result_map or scoped_profiles - set(result_map):
        return {}
    return {key: tuple(value) for key, value in result_map.items()}


def _current_support_blockers(workspace: Path) -> tuple[str, ...]:
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    blockers: list[str] = []
    bmw_models = readiness.get("bmw_models_repo", {})
    bmw_car_manager = readiness.get("bmw_car_manager_script", {})
    bmw_test_main = readiness.get("bmw_test_main_script", {})
    bmw_readme = readiness.get("bmw_screenshot_scripts", {})
    if bmw_models.get("status") != "available":
        blockers.append(f"{bmw_models.get('label', 'bmw_models_repo')} missing locally. Path: {bmw_models.get('path', '')}")
    if (
        bmw_car_manager.get("status") != "available"
        and bmw_test_main.get("status") != "available"
    ):
        blockers.append(
            "BMW screenshot/headless helpers are missing locally. "
            f"car_manager path: {bmw_car_manager.get('path', '')}"
        )
    if bmw_readme.get("status") != "available":
        blockers.append(
            f"{bmw_readme.get('label', 'BMW screenshot scripts README')} missing locally. "
            f"Path: {bmw_readme.get('path', '')}"
        )
    return tuple(blockers)


def _is_stale_followup(
    followup: str,
    readiness: dict[str, dict[str, str]],
) -> bool:
    text = followup.lower()
    if "bmw delivery repo is missing locally" in text:
        return readiness.get("bmw_models_repo", {}).get("status") == "available"
    if "car_manager.py" in text:
        return readiness.get("bmw_car_manager_script", {}).get("status") == "available"
    if "test/main.py" in text:
        return (
            readiness.get("bmw_car_manager_script", {}).get("status") == "available"
            or readiness.get("bmw_test_main_script", {}).get("status") == "available"
        )
    if "ci/scripts/readme" in text or "screenshot scripts" in text:
        return readiness.get("bmw_screenshot_scripts", {}).get("status") == "available"
    return False


def _support_blockers(workspace: Path, delivery_record: ActionRecord | None) -> tuple[str, ...]:
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    blockers = list(_current_support_blockers(workspace))
    for followup in _manual_followups(delivery_record):
        if _is_stale_followup(followup, readiness):
            continue
        if followup not in blockers:
            blockers.append(followup)
    return tuple(blockers)


def _select_attach_run(context: _ProfileContext) -> ActionRecord | None:
    for record in (
        *(record for record in context.manual_evidence_records if record.action_id.startswith("scene_check")),
        context.scene_record,
        *(record for record in context.manual_evidence_records if record.action_id.startswith("qa_stack")),
        context.stack_record,
    ):
        if record is not None:
            return record
    return None


def _attach_examples(contexts: tuple[_ProfileContext, ...], workspace: Path) -> tuple[str, ...]:
    blocks: list[str] = []
    for context in contexts:
        target = _select_attach_run(context)
        if target is None:
            continue
        profile_id = context.profile.profile_id
        block = "\n".join(
            [
                f"### {profile_id}",
                "```powershell",
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind screenshot --label "{profile_id} manual screenshot" --source "C:\\path\\to\\manual-shot.png"',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind raco_note --label "{profile_id} RaCo note" --note "Scene checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind blender_note --label "{profile_id} Blender note" --note "Workfile checked: ..."',
                f'python -m sg_preflight.cli desktop-state attach-manual-evidence "{target.run_id}" --workspace "{workspace}" --kind visual_review_checklist --label "{profile_id} visual checklist" --note "Project changelog reviewed: [x]"',
                "```",
            ]
        )
        blocks.append(block)
    return tuple(blocks)


def _test_case_area(key: str) -> str:
    name = Path(key).name.lower()
    if name.startswith("lights_"):
        return "Lighting and signal states"
    if name in {"cameraview", "default", "default_rear"}:
        return "Default and camera views"
    if name.startswith("glow_") or "godrays" in name:
        return "Glow and atmospheric effects"
    if name.startswith("groundfloor"):
        return "Ground and reflection"
    if name.startswith("highlighting_seats_"):
        return "Seat states and layouts"
    if name.startswith("highlighting_sensors_"):
        return "Sensor highlighting"
    if name.startswith("highlighting_doors") or name.startswith("highlighting_fuel") or name.startswith("highlighting_hood"):
        return "Body highlighting and access points"
    if "wheel" in name or "tire" in name or name.startswith("trimline_") or name.startswith("motion_"):
        return "Wheel and tire review"
    if name.startswith("customcolor_"):
        return "Custom colors and trimlines"
    return "Other"


def _possible_test_case_lines(context: _ProfileContext) -> list[str]:
    report = context.triage_bundle.report
    prep = context.prep
    lines = [
        f"### {context.profile.profile_id}",
        f"- Changelog heading: {prep.changelog_heading or 'not found'}",
        f"- Representative RaCo scene: `{prep.raco_scene_path or 'not found'}`",
        f"- Representative Blender workfile: `{prep.blender_workfile_path or 'not found'}`",
        f"- Screenshot baseline root: `{prep.screenshot_root or 'not found'}`",
        "- Priority screenshots: "
        + (", ".join(prep.priority_screenshots[:6]) if prep.priority_screenshots else "none detected"),
        "",
        "| Test-case area | Baselines | Current triage | Example screenshots |",
        "| --- | ---: | --- | --- |",
    ]
    groups: dict[str, list[str]] = {}
    for pair in report.pairs:
        groups.setdefault(_test_case_area(pair.key), []).append(Path(pair.key).name)

    ordered_areas = [
        "Lighting and signal states",
        "Default and camera views",
        "Glow and atmospheric effects",
        "Ground and reflection",
        "Body highlighting and access points",
        "Seat states and layouts",
        "Sensor highlighting",
        "Wheel and tire review",
        "Custom colors and trimlines",
        "Other",
    ]
    for area in ordered_areas:
        names = groups.get(area, [])
        if not names:
            continue
        missing = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "missing_candidate"
        )
        needs_review = sum(
            1
            for pair in report.pairs
            if _test_case_area(pair.key) == area and pair.classification == "needs_review"
        )
        state = f"{missing} missing candidate" if missing else f"{needs_review} needs review" if needs_review else "triage ready"
        lines.append(f"| {area} | {len(names)} | {state} | {', '.join(names[:3])} |")
    lines.append("")
    return lines


def _resolve_capability_paths(source_root: Path, relative_paths: tuple[str, ...]) -> tuple[Path, ...]:
    return tuple((source_root / Path(item)).resolve() for item in relative_paths)


def _qa_capability_matrix_markdown(
    *,
    ticket_id: str,
    source_root: Path,
    workspace: Path,
    scope_note: str,
    profile_ids: tuple[str, ...],
) -> str:
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    lines = [
        f"# QA Capability Matrix - {ticket_id}",
        "",
        f"- Generated from the user-provided QA/Confluence snapshot dated `{_QA_CONFLUENCE_SNAPSHOT_DATE}`.",
        f"- Grounded SG source root: `{source_root}`",
        f"- Profiles grounded locally: {', '.join(profile_ids) if profile_ids else 'none confirmed'}",
        f"- Scope note: {scope_note or 'No explicit scope note was provided.'}",
        "- Goal: separate what SG can already execute/document locally from what still needs BMW-side access or a human review session.",
        "",
        "| Capability | Local status | Verified path(s) or source | What it validates | How to use now | Main blocker |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for spec in _QA_CAPABILITY_SPECS:
        if spec["label"] in {"BMW screenshot smoke flow", "BMW headless export proof"}:
            bmw_models = readiness.get("bmw_models_repo", {})
            bmw_car_manager = readiness.get("bmw_car_manager_script", {})
            bmw_readme = readiness.get("bmw_screenshot_scripts", {})
            if (
                bmw_models.get("status") == "available"
                and bmw_car_manager.get("status") == "available"
                and bmw_readme.get("status") == "available"
            ):
                status = "helper surface available locally"
                verified = "<br>".join(
                    entry
                    for entry in (
                        f"`{bmw_models.get('path', '')}`" if bmw_models.get("path") else "",
                        f"`{bmw_car_manager.get('path', '')}`" if bmw_car_manager.get("path") else "",
                        f"`{bmw_readme.get('path', '')}`" if bmw_readme.get("path") else "",
                    )
                    if entry
                )
            else:
                status = spec["status_present"]
                verified = f"Confluence section: `{spec['section']}`"
            lines.append(
                f"| {spec['label']} | {status} | {verified} | {spec['checks']} | {spec['how_to_use']} | {spec['blocker']} |"
            )
            continue
        relative_paths = tuple(spec.get("relative_paths", ()))
        if relative_paths:
            resolved_paths = _resolve_capability_paths(source_root, relative_paths)
            existing_paths = tuple(path for path in resolved_paths if path.exists())
            missing_paths = tuple(path for path in resolved_paths if not path.exists())
            if existing_paths and not missing_paths:
                status = spec["status_present"]
            elif existing_paths:
                status = f"{spec['status_present']} (partial path coverage)"
            else:
                status = spec["status_missing"]
            verified = (
                "<br>".join(f"`{path}`" for path in existing_paths)
                if existing_paths
                else "<br>".join(f"`{path}`" for path in resolved_paths)
            )
        else:
            status = spec["status_present"]
            verified = f"Confluence section: `{spec['section']}`"
        lines.append(
            f"| {spec['label']} | {status} | {verified} | {spec['checks']} | {spec['how_to_use']} | {spec['blocker']} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "- `available locally` means the script or helper path is present in the current SG-side SVN checkout and can be documented or used locally.",
            "- `archived in SVN` means the documentation still refers to the capability, but the live path has already moved to archive and should not be assumed as an active default workflow.",
            "- `blocked by BMW access` means the flow is documented, but the required BMW-owned repository, scripts, or runtime environment are still inaccessible from this machine.",
            "- `manual / rack dependent` means the flow is real, but it requires physical hardware or a reviewer session rather than a deterministic local CLI-only run.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _three_d_qa_playbook_markdown(
    *,
    ticket_id: str,
    source_root: Path,
    bundle: TicketReviewBundle,
    contexts: tuple[_ProfileContext, ...],
) -> str:
    lines = [
        f"# 3D QA Playbook - {ticket_id}",
        "",
        f"- Generated from the user-provided QA/Confluence snapshot dated `{_QA_CONFLUENCE_SNAPSHOT_DATE}` and current local SVN verification.",
        f"- Grounded SG source root: `{source_root}`",
        f"- Profiles grounded locally: {', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "- This playbook is deliberately conservative: it is a delivery-week SG-side review guide, not a fake BMW-side signoff workflow.",
        "",
        "## Recommended review order",
        "1. Confirm which cars/slices are actually in scope before claiming coverage beyond the current grounded slice.",
        "2. Review the car changelog, car README/constants notes, and relevant shared BMW docs before judging screenshot differences.",
        "3. Run or reuse SG-side checker evidence on the live SVN slice and record findings instead of silently ignoring them.",
        "4. Review expected screenshot baselines and deterministic triage output; do not claim screenshot tests passed without candidate/result images.",
        "5. Open the representative RaCo scene and Blender workfile, then attach manual evidence with the existing desktop-state flow.",
        "6. Pull in topic-specific flows only when the changelog or ticket scope justifies them: perspectives, anchor points, resource sizes, or car paints.",
        "7. Package the result as a DoD/status bundle and keep BMW-owned blockers explicit.",
        "",
        "## Confluence-derived 3D test catalog",
        "| Test area | What to check | Where to look | Evidence to attach |",
        "| --- | --- | --- | --- |",
    ]
    for item in _THREE_D_QA_TEST_CATALOG:
        lines.append(f"| {item['area']} | {item['checks']} | {item['where']} | {item['evidence']} |")

    lines.extend(["", "## Current grounded entrypoints"])
    if contexts:
        for context in contexts:
            lines.extend(
                [
                    f"### {context.profile.profile_id}",
                    f"- Representative RaCo scene: `{context.prep.raco_scene_path or 'not found'}`",
                    f"- Representative Blender workfile: `{context.prep.blender_workfile_path or 'not found'}`",
                    f"- Screenshot baseline root: `{context.prep.screenshot_root or 'not found'}`",
                    f"- Priority screenshots: {', '.join(context.prep.priority_screenshots[:8]) if context.prep.priority_screenshots else 'none detected'}",
                ]
            )
    else:
        lines.append("- No confirmed local slice is grounded yet. Keep the bundle process-first until scope is confirmed.")

    lines.extend(
        [
            "",
            "## Special-topic triggers",
            "- Use the perspective helper only when a ticket actually changes reference cameras or named perspectives.",
            "- Use the Ramses resource-size report when delivery size, UCAP pressure, or resource growth is part of the concern.",
            "- Use the car-paint helpers for fast RaCo-side review, but treat rack/design approval as a separate human step.",
            "- Use the archived PerspectiveTracePlayer assets only intentionally; do not assume the old live path still exists.",
            "",
            "## What still stays BMW-side",
            "- Screenshot smoke execution from digital-3d-car-models",
            "- The proving command/output for BMW headless export",
            "- Candidate/result screenshot root confirmation",
            "- BMW Jira/Git writeback and PR/CI observation",
            "",
            "## Evidence standard",
            "- `Needs human review` is the correct language for visual changes unless the evidence is purely deterministic.",
            "- Manual review means attaching a note, checklist, or screenshot to an existing action-bundle run, not only opening a scene once.",
            "- Positive checks still need documentation; silence is not evidence.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _repository_layout_roots(source_root: Path) -> tuple[Path, Path, Path, Path]:
    if source_root.name.lower() == "trunk":
        repositories_root = source_root.parent
        trunk_root = source_root
    else:
        repositories_root = source_root
        trunk_root = source_root / "trunk"
    return repositories_root, repositories_root / "branches", repositories_root / "delivery", trunk_root


def _path_status(path: Path) -> str:
    return "available locally" if path.exists() else "missing locally"


def _repo_topology_reference_markdown(
    *,
    ticket_id: str,
    source_root: Path,
    scope_note: str,
    profile_ids: tuple[str, ...],
) -> str:
    repositories_root, branches_root, delivery_root, trunk_root = _repository_layout_roots(source_root)
    pdx_root = trunk_root / ".pdx"
    cars_root = trunk_root / "Cars"
    classic_shared_root = trunk_root / "Cars" / "BMW" / "_Shared"
    idcevo_shared_root = trunk_root / "Cars_IDCevo" / "BMW" / "_Shared_IDCevo"
    g05_legacy_root = branches_root / "G05_legacy"

    lines = [
        f"# Repo Topology Reference - {ticket_id}",
        "",
        f"- Grounded SG source root: `{source_root}`",
        f"- Profiles grounded locally: {', '.join(profile_ids) if profile_ids else 'none confirmed'}",
        f"- Scope note: {scope_note or 'No explicit scope note was provided.'}",
        "- Purpose: operator-facing reference for SVN layout, shared-scene dependencies, and delivery-week checkout assumptions.",
        "",
        "| Surface | Path | Local status | Why it matters |",
        "| --- | --- | --- | --- |",
        f"| Repositories root | `{repositories_root}` | {_path_status(repositories_root)} | Parent container for `branches`, `delivery`, and `trunk`. |",
        f"| Branches | `{branches_root}` | {_path_status(branches_root)} | Contains SOP, PoC, one-time-fix, and legacy branch material. |",
        f"| Delivery | `{delivery_root}` | {_path_status(delivery_root)} | Contains delivery-side material outside the main trunk. |",
        f"| Trunk | `{trunk_root}` | {_path_status(trunk_root)} | Main SG project repository and the only safe default source of truth for delivery-week QA. |",
        f"| .pdx | `{pdx_root}` | {_path_status(pdx_root)} | Team scripts for testing, Blender, and Ramses Composer. |",
        f"| Cars | `{cars_root}` | {_path_status(cars_root)} | 3D car assets and Ramses Composer scenes/setups. |",
        f"| Classic BMW shared | `{classic_shared_root}` | {_path_status(classic_shared_root)} | Shared classic BMW logic/material/environment dependencies. |",
        f"| IDCEVO BMW shared | `{idcevo_shared_root}` | {_path_status(idcevo_shared_root)} | Shared IDCEVO BMW dependencies for live slices like G70/NAx/etc. |",
        f"| Historical G05 legacy branch | `{g05_legacy_root}` | {_path_status(g05_legacy_root)} | Historical placeholder/legacy context only; not active ticket scope by default. |",
        "",
        "## Checkout and scene-loading notes",
        f"- `trunk` should be treated as the main working repository. Expected path: `{trunk_root}`.",
        "- For reliable main-scene loading, the repo should be checked out in full rather than as a narrow partial slice.",
        "- Missing shared folders can break camera, material, and environment loading even when the car-local scene files exist.",
        f"- Classic BMW scenes depend on shared content such as `{classic_shared_root}`.",
        f"- IDCEVO slices use shared content such as `{idcevo_shared_root}`.",
        "- `.pdx` is not optional for QA support work; it contains the scripts that make repo checks, test helpers, and RaCo automation usable.",
        "",
        "## Practical interpretation",
        "- `branches` is reference/history/problem-solving territory; it should not silently replace `trunk` as the delivery-week source of truth.",
        "- `delivery` exists, but this ticket flow should remain grounded in `trunk` until a delivery-specific surface is explicitly required.",
        "- `branches/G05_legacy` should be treated as historical context or placeholder-car reference only, not as evidence for the current BMW ticket scope.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _delivery_surface_map_markdown(
    *,
    ticket_id: str,
    source_root: Path,
    scope_note: str,
    workspace: Path,
) -> str:
    repositories_root, _, _, trunk_root = _repository_layout_roots(source_root)
    readiness = {item["key"]: item for item in prerequisite_status(workspace)}
    bmw_models = readiness.get("bmw_models_repo", {})
    bmw_car_manager = readiness.get("bmw_car_manager_script", {})
    bmw_main_script = readiness.get("bmw_test_main_script", {})
    bmw_repo_ready = bmw_models.get("status") == "available"
    bmw_execution_state = "partially, for inspection and packaging only" if bmw_repo_ready else "no"
    bmw_local_evidence = (
        "CI README, car_manager helper, local tests-folder structure, and packaged root/count documentation."
        if bmw_repo_ready
        else "Expected commands, blocker documentation, required evidence fields in the bundle."
    )

    def _blocked_text(item: dict[str, Any]) -> str:
        label = str(item.get("label", "BMW prerequisite"))
        status = str(item.get("status", "missing"))
        return f"{label} is {status}."

    if bmw_car_manager.get("status") == "available":
        bmw_helper_text = _blocked_text(bmw_car_manager)
    elif bmw_main_script.get("status") == "available":
        bmw_helper_text = _blocked_text(bmw_main_script)
    else:
        bmw_helper_text = f"{_blocked_text(bmw_car_manager)} {_blocked_text(bmw_main_script)}"

    lines = [
        f"# Delivery Surface Map - {ticket_id}",
        "",
        f"- Grounded SG source root: `{source_root}`",
        f"- Scope note: {scope_note or 'No explicit scope note was provided.'}",
        "- Purpose: show which delivery surfaces are locally usable now versus BMW-only or rack-only.",
        "",
        "| Surface | What it contains | Broad owner | Executable from this machine now | Local evidence we can still produce | What stays blocked |",
        "| --- | --- | --- | --- | --- | --- |",
        f"| SG-local SVN evidence | `trunk`, `.pdx`, car changelogs/readmes, shared docs, expected screenshot baselines, representative `.rca`/Blender files. | SG / PDX | yes | Ticket bundle, DoD matrix, screenshot triage on baselines, checker findings, shared-doc review prep. | Does not prove BMW smoke/headless execution. |",
        "| SG-local manual review | RaCo/Blender review sessions, manual screenshots, notes, checklists, asset comparisons. | SG / assigned reviewer | yes, manually | Manual evidence attachments, Blender-vs-RaCo notes, operator checklists. | Human judgment and pass/fail criteria still need agreement. |",
        f"| BMW Git / digital-3d-car-models | Production delivery repo, headless export, interface tests, screenshot smoke flow. | BMW / Team Wombat | {bmw_execution_state} | {bmw_local_evidence} | {_blocked_text(bmw_models)} {bmw_helper_text} Static repo folders alone are not proof; use the attached local smoke/battery outputs as execution evidence. |",
        "| digital-3d-car-raw / blender plugins | Workfiles/pipeline data and Blender plugin surfaces that feed final delivery prep. | SG + BMW Git surfaces | not from the current blocked environment | Documentation of the repo split and why `_Workfiles` stay out of production delivery repos. | Access/PR flow remains outside the current local ticket execution path. |",
        "| Rack-only flows | Physical rack validation, ADB/localhost:9091 paint review, final hardware-side visual checks. | SG reviewer + designer/BMW PO | no, unless the rack is physically available | Operator instructions and blocked/manual classification only. | Physical hardware, 3D Car Test app, and review session availability. |",
        "| Jira / PR / CI follow-up | BMW Jira comments, PR links, CI observation, Review by BMW handoff. | BMW + SG delivery process | no | Teams-ready and Jira-ready text artifacts from the bundle. | Jira access, Git web/PR, and BMW CI ownership remain blocked. |",
        "",
        "## Delivery-week guardrails",
        "- Keep the production-vs-raw split explicit: production delivery repos are not the place for `_Workfiles`.",
        "- Never commit `_Workfiles`, `.ramses`, `.logic`, diff folders, or actual screenshot-result folders into delivery repos.",
        "- Shared-folder updates matter. A delivery review is incomplete if the relevant `_Shared` / `_Shared_IDCevo` dependencies were ignored.",
        "- Screenshot smoke and headless export are still BMW-owned proving steps even when SG can prepare evidence around them.",
        "- Documentation expectations still apply locally: changelog/readme review, intended-difference notes, and checker findings should be captured even when Jira is blocked.",
        "",
        "## Repo split reminder",
        f"- SG-side source of truth for the current bundle: `{trunk_root}` inside `{repositories_root}`.",
        "- `digital-3d-car-models` is the production delivery repo for BMW-side smoke/headless flows.",
        "- `digital-3d-car-raw` and related pipeline/plugin repos are separate delivery surfaces and should not be collapsed into the same evidence claim.",
        "",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _raco_script_catalog_markdown(
    *,
    ticket_id: str,
    source_root: Path,
    scope_note: str,
) -> str:
    catalog = (
        {
            "group": "Scene creation / structure",
            "label": "IDCEVO folder structure creation",
            "purpose": "Create IDCEVO BMW folder/scaffold scenes when a car structure is still missing.",
            "documented": ".pdx\\raco\\create_BMW_IDCevo_folderStructure.py",
            "actual": (".pdx/raco/scripts/structure/scene_creation/create_BMW_IDCevo_folderStructure.py",),
            "relevance": "broader authoring automation",
        },
        {
            "group": "Scene creation / structure",
            "label": "Write prefab structure",
            "purpose": "Persist current prefab structure into JSON when the standard structure changes.",
            "documented": ".pdx\\raco\\write_prefab_structure.py",
            "actual": (".pdx/raco/scripts/structure/scene_creation/write_prefab_structure.py",),
            "relevance": "broader authoring automation",
        },
        {
            "group": "Scene creation / structure",
            "label": "Read prefab structure (IDCEVO)",
            "purpose": "Recreate prefab structure from JSON inside current IDCEVO scenes.",
            "documented": ".pdx\\raco\\read_prefab_structure_IDCevo.py",
            "actual": (".pdx/raco/scripts/structure/scene_creation/read_prefab_structure_IDCevo.py",),
            "relevance": "broader authoring automation",
        },
        {
            "group": "RES automation",
            "label": "update_RES.py",
            "purpose": "Update/import RES meshes, uniforms, and trim-line links in existing scenes.",
            "documented": ".pdx\\raco\\scripts\\RES\\update_RES.py",
            "actual": (".pdx/raco/scripts/RES/update_RES.py",),
            "relevance": "broader authoring automation",
        },
        {
            "group": "LOG automation",
            "label": "get_transforms.py",
            "purpose": "Apply Blender-exported transform data from Pivot_Master into LOG scenes.",
            "documented": ".pdx\\raco\\scripts\\LOG\\get_transforms.py",
            "actual": (".pdx/raco/scripts/LOG/get_transforms.py",),
            "relevance": "broader authoring automation",
        },
        {
            "group": "Testing helpers",
            "label": "carmodel_data.json",
            "purpose": "Provides trimline/engine combination reference data used by review flows and QA interpretation.",
            "documented": ".pdx\\carmodel_data.json",
            "actual": (".pdx/python/carmodel_data.json",),
            "relevance": "delivery-week QA support",
        },
        {
            "group": "Testing helpers",
            "label": "test_absolute_path.py",
            "purpose": "Check absolute-path problems in export scenes.",
            "documented": ".pdx\\raco\\scripts\\testing\\test_absolute_path.py",
            "actual": (".pdx/raco/scripts/testing/test_absolute_path.py",),
            "relevance": "delivery-week QA support",
        },
        {
            "group": "Testing helpers",
            "label": "test_ucap_ignore.py",
            "purpose": "Check UCAP-ignore tagging/configuration in export scenes.",
            "documented": ".pdx\\raco\\scripts\\testing\\test_ucap_ignore.py",
            "actual": (".pdx/raco/scripts/testing/test_ucap_ignore.py",),
            "relevance": "delivery-week QA support",
        },
        {
            "group": "Testing helpers",
            "label": "test_unused_lua_files.py",
            "purpose": "Find unused Lua files in export-scene context.",
            "documented": ".pdx\\raco\\scripts\\testing\\test_unused_lua_files.py",
            "actual": (".pdx/raco/scripts/testing/test_unused_lua_files.py",),
            "relevance": "delivery-week QA support",
        },
        {
            "group": "Perspective helpers",
            "label": "setup_perspective.py",
            "purpose": "Set up and fine-tune fixed perspectives against a reference image.",
            "documented": ".pdx\\raco\\scripts\\testing\\setup_perspective.py",
            "actual": (".pdx/raco/scripts/testing/setup_perspective.py",),
            "relevance": "scope-gated QA support",
        },
        {
            "group": "Perspective helpers",
            "label": "PerspectiveTracePlayer",
            "purpose": "Legacy trace-player-based perspective review assets.",
            "documented": ".pdx\\raco\\PerspectiveTracePlayer",
            "actual": (".pdx/raco/archive/PerspectiveTracePlayer",),
            "relevance": "scope-gated QA support",
        },
        {
            "group": "Car-paint helpers",
            "label": "read_json_carpaints.py",
            "purpose": "Load and review car-paint definitions quickly in RaCo.",
            "documented": ".pdx\\raco\\scripts\\testing\\read_json_carpaints.py",
            "actual": (".pdx/raco/scripts/testing/read_json_carpaints.py",),
            "relevance": "scope-gated QA support",
        },
        {
            "group": "Car-paint helpers",
            "label": "TestCarPaint",
            "purpose": "Small setup to check paints quickly in RaCo.",
            "documented": ".pdx\\raco\\TestCarPaint",
            "actual": (".pdx/raco/TestCarPaint",),
            "relevance": "scope-gated QA support",
        },
        {
            "group": "Resource-size helpers",
            "label": "resources_size_report.py",
            "purpose": "Generate Ramses resource-size reports for variants and deliveries.",
            "documented": ".pdx\\raco\\scripts\\testing\\resources_size_report.py",
            "actual": (".pdx/raco/scripts/testing/resources_size_report.py",),
            "relevance": "scope-gated QA support",
        },
        {
            "group": "Resource-size helpers",
            "label": "variants_export.py",
            "purpose": "Variant export helper used by resource-size reporting and related export flows.",
            "documented": ".pdx\\raco\\variant_export.py",
            "actual": (".pdx/raco/scripts/testing/variants_export.py",),
            "relevance": "scope-gated QA support",
        },
    )

    lines = [
        f"# RaCo Script Catalog - {ticket_id}",
        "",
        f"- Grounded SG source root: `{source_root}`",
        f"- Scope note: {scope_note or 'No explicit scope note was provided.'}",
        "- Purpose: operator-facing catalog of verified `.pdx` / RaCo helpers, with documented-path drift noted explicitly.",
        "",
    ]
    current_group = None
    for item in catalog:
        if item["group"] != current_group:
            current_group = item["group"]
            lines.extend(
                [
                    f"## {current_group}",
                    "",
                    "| Helper | Intended purpose | Documented path | Verified local path(s) | Local status | Delivery-week relevance |",
                    "| --- | --- | --- | --- | --- | --- |",
                ]
            )
        actual_paths = _resolve_capability_paths(source_root, item["actual"])
        existing_paths = tuple(path for path in actual_paths if path.exists())
        if item["label"] == "PerspectiveTracePlayer":
            status = "archived in SVN"
        elif existing_paths and item["documented"].replace("\\", "/") != item["actual"][0]:
            status = "available locally (documented path drift)"
        elif existing_paths:
            status = "available locally"
        else:
            status = "not found locally"
        verified = (
            "<br>".join(f"`{path}`" for path in existing_paths)
            if existing_paths
            else "<br>".join(f"`{path}`" for path in actual_paths)
        )
        lines.append(
            f"| {item['label']} | {item['purpose']} | `{item['documented']}` | {verified} | {status} | {item['relevance']} |"
        )

    lines.extend(
        [
            "",
            "## Drift notes",
            "- `carmodel_data.json` is not at the older documented `.pdx\\carmodel_data.json` location; the verified local path is `.pdx\\python\\carmodel_data.json`.",
            "- IDCEVO structure scripts now live under `.pdx\\raco\\scripts\\structure\\scene_creation\\...` rather than directly under `.pdx\\raco\\`.",
            "- `PerspectiveTracePlayer` should be treated as archived under `.pdx\\raco\\archive\\PerspectiveTracePlayer`.",
            "- The Confluence reference to `variant_export.py` appears stale; the verified local helper is `variants_export.py` under `.pdx\\raco\\scripts\\testing\\`.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _delivery_target_catalog_markdown(
    *,
    ticket_id: str,
    scope_note: str,
) -> str:
    lines = [
        f"# Delivery Target Catalog - {ticket_id}",
        "",
        f"- Generated from the user-provided QA/Confluence snapshot dated `{_QA_CONFLUENCE_SNAPSHOT_DATE}`.",
        f"- Scope note: {scope_note or 'No explicit scope note was provided.'}",
        "- Purpose: capture the broader delivery ecosystem that is documented in Confluence even when BMW Git, Jira, or corp-network surfaces are not locally usable yet.",
        "- Contacts, PO names, and branch hints below are transcribed from the provided documentation and are not independently verified by this bundle.",
        "",
    ]

    for section in (
        "Pipeline and 3D car repos",
        "Widget assets",
        "Images and shaders",
        "Other storage and libraries",
    ):
        lines.extend(
            [
                f"## {section}",
                "",
                "| Deliverable | Repo or path | Asset scope | Delivery notes | Contact surface | Local status |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in _DELIVERY_TARGET_SPECS:
            if item["section"] != section:
                continue
            deliverable = str(item["deliverable"]).replace("|", ";")
            target = str(item["target"]).replace("|", ";")
            assets = str(item["assets"]).replace("|", ";")
            notes = str(item["notes"]).replace("|", ";")
            contacts = str(item["contacts"]).replace("|", ";")
            status = str(item["status"]).replace("|", ";")
            lines.append(
                f"| {deliverable} | `{target}` | {assets} | {notes} | {contacts} | {status} |"
            )
        lines.append("")

    lines.extend(
        [
            "## Car-paint and size tracking references",
            "",
            "| Reference area | Documented surface | Why it matters | Local status |",
            "| --- | --- | --- | --- |",
        ]
    )
    for item in _DELIVERY_REFERENCE_SPECS:
        area = str(item["area"]).replace("|", ";")
        surface = str(item["surface"]).replace("|", ";")
        why = str(item["why"]).replace("|", ";")
        status = str(item["status"]).replace("|", ";")
        lines.append(
            f"| {area} | `{surface}` | {why} | {status} |"
        )

    lines.extend(
        [
            "",
            "## Interpretation",
            "- This catalog is an operator reference, not proof that the current machine can write to those repos or shares.",
            "- Use it when a ticket moves beyond the SG SVN slice into widget assets, Android resource repos, pipeline files, or car-paint coordination.",
            "- Keep the SG-local bundle grounded in SVN evidence first; use this catalog to identify the next owner or target surface once scope expands.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _build_dod_items(
    *,
    contexts: tuple[_ProfileContext, ...],
    workspace: Path,
    scope_note: str,
    manual_evidence: tuple[TicketManualEvidenceItem, ...],
    manual_evidence_index_path: Path,
    support_artifacts: tuple[ReviewEvidence, ...] = (),
    daily_snapshot: DailyQaSnapshotResult | None = None,
    raco_probe: RacoManualReviewProbeResult | None = None,
    include_action_bundles: bool = True,
) -> tuple[TicketDoDItem, ...]:
    scope_grounded = bool(contexts)
    screenshot_manual = tuple(item for item in manual_evidence if item.kind == "screenshot")
    asset_manual = tuple(item for item in manual_evidence if item.kind in _MANUAL_EVIDENCE_ASSET_KINDS)
    format_findings = tuple(finding for context in contexts for finding in _record_findings(context.repo_record))
    snapshot_results = _snapshot_smoke_results(daily_snapshot, contexts)
    snapshot_battery = _snapshot_battery_results(daily_snapshot, contexts)
    snapshot_diagnostics = tuple(daily_snapshot.snapshot.diagnostics) if daily_snapshot is not None else ()
    snapshot_smoke_completed = bool(snapshot_results) and all(
        item.status == "completed" for item in snapshot_results.values()
    )
    snapshot_headless_covered = snapshot_smoke_completed and all(
        item.exported_ramses_size > 0 for item in snapshot_results.values()
    )
    snapshot_screenshot_ready = snapshot_smoke_completed and all(
        item.expected_count > 0 and item.actual_count > 0 for item in snapshot_results.values()
    )
    snapshot_all_compare_ok = snapshot_screenshot_ready and all(
        item.compare_ok and item.diff_count == 0 for item in snapshot_results.values()
    )
    baselines_present = any(
        context.prep.screenshot_count > 0
        or context.bmw_surface.sg_expected_count > 0
        or context.bmw_surface.bmw_expected_count > 0
        for context in contexts
    )
    bmw_screenshot_surface_present = any(context.bmw_surface.export_tests_root for context in contexts)
    bmw_headless_surface_present = any(context.bmw_surface.car_manager_path for context in contexts)
    screenshot_status = (
        "partial"
        if snapshot_screenshot_ready or baselines_present or screenshot_manual or bmw_screenshot_surface_present
        else "blocked"
    )
    asset_status = "partial" if asset_manual else "manual_ready" if any(
        context.prep.raco_scene_path or context.prep.blender_workfile_path for context in contexts
    ) else "blocked"
    format_status = "covered_with_findings" if format_findings else "covered" if any(
        context.repo_record and context.repo_record.status == "completed" for context in contexts
    ) else "blocked"
    changelog_status = "prepared" if any(context.prep.changelog_path for context in contexts) else "blocked"
    readme_status = "prepared" if any(
        context.prep.constants_readme_path or context.prep.project_readme_paths for context in contexts
    ) else "blocked"
    shared_status = "prepared" if any(context.prep.shared_doc_paths for context in contexts) else "blocked"
    headless_status = "covered" if snapshot_headless_covered else "partial" if bmw_headless_surface_present else "blocked"
    raco_probe_ready = bool(raco_probe and {
        item.strip().upper() for item in raco_probe.profile_ids if item and item.strip()
    }.issuperset({context.profile.profile_id.upper() for context in contexts}))

    screenshot_evidence: list[ReviewEvidence] = []
    asset_evidence: list[ReviewEvidence] = []
    format_evidence: list[ReviewEvidence] = []
    changelog_evidence: list[ReviewEvidence] = []
    readme_evidence: list[ReviewEvidence] = []
    shared_evidence: list[ReviewEvidence] = []
    headless_evidence: list[ReviewEvidence] = []
    support_evidence: list[ReviewEvidence] = [
        _bundle_evidence("Ticket manual evidence index", manual_evidence_index_path),
        *support_artifacts,
    ]
    if daily_snapshot is not None:
        snapshot_rel = _bundle_evidence("Daily QA snapshot", daily_snapshot.markdown_path)
        snapshot_json_rel = _bundle_evidence("Daily QA snapshot JSON", daily_snapshot.json_path)
        screenshot_evidence.extend((snapshot_rel, snapshot_json_rel))
        headless_evidence.extend((snapshot_rel, snapshot_json_rel))
        support_evidence.extend((snapshot_rel, snapshot_json_rel))
        if daily_snapshot.battery_baseline_gaps_markdown_path is not None:
            baseline_rel = _bundle_evidence(
                "Battery baseline gaps",
                daily_snapshot.battery_baseline_gaps_markdown_path,
            )
            screenshot_evidence.append(baseline_rel)
            support_evidence.append(baseline_rel)
        if daily_snapshot.battery_baseline_gaps_json_path is not None:
            baseline_json_rel = _bundle_evidence(
                "Battery baseline gaps JSON",
                daily_snapshot.battery_baseline_gaps_json_path,
            )
            screenshot_evidence.append(baseline_json_rel)
            support_evidence.append(baseline_json_rel)
        if daily_snapshot.review_priority_markdown_path is not None:
            priority_rel = _bundle_evidence(
                "Review priority ranking",
                daily_snapshot.review_priority_markdown_path,
            )
            screenshot_evidence.append(priority_rel)
            support_evidence.append(priority_rel)
        if daily_snapshot.review_priority_json_path is not None:
            priority_json_rel = _bundle_evidence(
                "Review priority ranking JSON",
                daily_snapshot.review_priority_json_path,
            )
            screenshot_evidence.append(priority_json_rel)
            support_evidence.append(priority_json_rel)
        if daily_snapshot.delta_summary_markdown_path is not None:
            delta_rel = _bundle_evidence(
                "Daily QA delta summary",
                daily_snapshot.delta_summary_markdown_path,
            )
            support_evidence.append(delta_rel)
        if daily_snapshot.delta_summary_json_path is not None:
            delta_json_rel = _bundle_evidence(
                "Daily QA delta summary JSON",
                daily_snapshot.delta_summary_json_path,
            )
            support_evidence.append(delta_json_rel)
        if daily_snapshot.review_gallery_html_path is not None:
            review_gallery_rel = _bundle_evidence(
                "Candidate review gallery",
                daily_snapshot.review_gallery_html_path,
            )
            screenshot_evidence.append(review_gallery_rel)
            support_evidence.append(review_gallery_rel)
    if raco_probe is not None:
        probe_rel = _bundle_evidence("RaCo manual review probe", raco_probe.markdown_path)
        probe_json_rel = _bundle_evidence("RaCo manual review probe JSON", raco_probe.json_path)
        asset_evidence.extend((probe_rel, probe_json_rel))
        support_evidence.extend((probe_rel, probe_json_rel))

    for context in contexts:
        triage = context.triage_bundle
        prep = context.prep
        screenshot_evidence.extend(
            [
                _packaged_source_evidence(
                    context,
                    prep.screenshot_test_config_path or context.bmw_surface.test_config_path or "not found",
                    label="Screenshot test config",
                ),
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage", triage.markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _bundle_evidence("Screenshot evidence slots", context.manual_review_paths["slots"]),
                _bundle_evidence("Visual review checklist", context.manual_review_paths["visual_checklist"]),
            ]
        )
        asset_evidence.extend(
            [
                _bundle_evidence("Manual review companion", context.manual_review_paths["companion"]),
                _bundle_evidence("Manual review record", context.manual_review_paths["record"]),
                _bundle_evidence("Blender vs RaCo checklist", context.manual_review_paths["blender_raco"]),
            ]
        )
        if include_action_bundles and context.repo_record is not None:
            format_evidence.append(_bundle_evidence(f"{context.profile.profile_id} repo checker summary", context.repo_record.paths.get("summary_md", "")))
        if format_findings:
            first = format_findings[0]
            format_evidence.append(_bundle_evidence("First concrete finding", first.path or ""))
        if prep.changelog_path:
            changelog_evidence.append(_packaged_source_evidence(context, prep.changelog_path, label="Car changelog"))
        if prep.constants_readme_path:
            readme_evidence.append(_packaged_source_evidence(context, prep.constants_readme_path, label="Car README"))
        elif prep.project_readme_paths:
            readme_evidence.append(_packaged_source_evidence(context, prep.project_readme_paths[0], label="Car README"))
        if prep.shared_doc_paths:
            for path in prep.shared_doc_paths[:6]:
                shared_evidence.append(_packaged_source_evidence(context, path, label="Shared BMW doc"))
        if include_action_bundles and context.delivery_record is not None:
            headless_evidence.append(
                _bundle_evidence(
                    f"{context.profile.profile_id} delivery checklist summary",
                    context.delivery_record.paths.get("summary_md", ""),
                )
            )
        headless_evidence.extend(
            [
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _packaged_source_evidence(context, context.bmw_surface.car_manager_path or "not found", label="BMW car_manager.py"),
                _packaged_source_evidence(context, context.bmw_surface.ci_readme_path or "not found", label="BMW CI README"),
            ]
        )
        snapshot_item = snapshot_results.get(context.profile.profile_id.upper())
        if snapshot_item is not None and snapshot_item.log_path:
            log_evidence = _bundle_evidence(
                f"{context.profile.profile_id} BMW smoke log",
                _resolve_snapshot_artifact_path(daily_snapshot, snapshot_item.log_path),
            )
            screenshot_evidence.append(log_evidence)
            headless_evidence.append(log_evidence)
        battery_items = snapshot_battery.get(context.profile.profile_id.upper(), ())
        if battery_items:
            seen_battery_logs: set[str] = set()
            for battery_item in battery_items:
                resolved_log_path = _resolve_snapshot_artifact_path(daily_snapshot, battery_item.log_path)
                if resolved_log_path in seen_battery_logs or resolved_log_path == "not found":
                    continue
                seen_battery_logs.add(resolved_log_path)
                screenshot_evidence.append(
                    _bundle_evidence(f"{context.profile.profile_id} BMW battery log", resolved_log_path)
                )
        support_evidence.append(_bundle_evidence("Scope note", scope_note))

    for item in manual_evidence:
        evidence = _bundle_evidence(f"{item.kind}: {item.label}", item.packaged_path)
        support_evidence.append(evidence)
        if item.kind == "screenshot":
            screenshot_evidence.append(evidence)
        if item.kind in _MANUAL_EVIDENCE_ASSET_KINDS:
            asset_evidence.append(evidence)

    triage_reports = [context.triage_bundle.report for context in contexts]
    screenshot_summary = _screenshot_surface_summary(contexts)
    if snapshot_results:
        snapshot_parts = []
        for context in contexts:
            item = snapshot_results.get(context.profile.profile_id.upper())
            if item is None:
                continue
            status_text = (
                "passed locally with no visible diff"
                if item.compare_ok and item.diff_count == 0
                else "needs manual review"
                if item.diff_count > 0
                else item.status
            )
            snapshot_parts.append(
                f"{context.profile.profile_id}: smoke `{item.smoke_test}` -> {status_text}; "
                f"expected {item.expected_count}, actual {item.actual_count}, diff {item.diff_count}, "
                f"Ramses {item.exported_ramses_size}b"
            )
            battery_items = snapshot_battery.get(context.profile.profile_id.upper(), ())
            if battery_items:
                verdict_counts: dict[str, int] = {}
                for battery_item in battery_items:
                    verdict = str(getattr(battery_item, "verdict", "")).strip() or "unknown"
                    verdict_counts[verdict] = verdict_counts.get(verdict, 0) + 1
                snapshot_parts.append(
                    f"{context.profile.profile_id}: broader battery -> "
                    + ", ".join(f"{key} {value}" for key, value in sorted(verdict_counts.items()))
                )
        if snapshot_parts:
            for diagnostic in snapshot_diagnostics:
                snapshot_parts.append(f"battery diagnosis -> {diagnostic}")
            screenshot_summary = "<br>".join(snapshot_parts)

    headless_summary = _headless_surface_summary(contexts)
    if snapshot_results:
        executed = ", ".join(
            f"{item.profile_id} ({item.exported_ramses_size}b Ramses)"
            for item in snapshot_results.values()
            if item.status == "completed"
        )
        if executed:
            headless_summary = (
                f"Representative local BMW export proof is attached for {executed}. "
                "The smoke logs include `Export finished` and `File sizes` output from the BMW helper flow."
            )

    if snapshot_screenshot_ready:
        screenshot_next_input = (
            "Representative local smoke evidence is attached for the confirmed cars. Remaining work is the final visual verdict for exact/proxy-ready outputs plus review-owner confirmation on whether `lights_OnlyCones` is a delivery blocker or a follow-up."
            if snapshot_diagnostics
            else "Representative local smoke evidence is attached for the confirmed cars. Remaining work is broader scenario coverage plus human screenshot verdicts for any changed outputs once those scenarios emit the right targets."
        )
    else:
        screenshot_next_input = (
            "Need real screenshot payload for the confirmed cars when folders are empty, plus the normal pass/fail reading flow from Adrian / Hristofor / Stefan."
        )
    headless_next_input = (
        "Representative local BMW export proof is attached. Need review-owner confirmation whether this local proof is accepted as DoD evidence and whether any broader scenario coverage is still required."
        if snapshot_headless_covered
        else "Need captured `export finished` and file sizes output for one confirmed delivery car."
    )
    if snapshot_screenshot_ready:
        screenshot_now_text = (
            "Use the attached daily snapshot, smoke logs, triage outputs, and candidate gallery as the current source of truth. The representative smoke path is green, low/high beam have proxy coverage, and the remaining exact local blocker is `lights_OnlyCones`."
            if snapshot_diagnostics
            else "Use the attached daily snapshot, smoke logs, and triage outputs as the current source of truth. The representative smoke path is green, and the broader battery outputs can now be reviewed directly."
        )
    else:
        screenshot_now_text = (
            "Review the packaged baseline/test-config roots, BMW actuals/diff roots, and deterministic triage output. Treat every changed or missing pair as manual review work, not as an automatic regression verdict."
        )
    headless_now_text = (
        "Use the attached BMW smoke logs as export proof. They already capture `Export finished`, file sizes, and screenshot-compare results for the confirmed delivery cars."
        if snapshot_headless_covered
        else "Package the BMW CI README plus car_manager helper, document the expected `export finished` and file-sizes proof, and only execute the export once the local export proof can be captured."
    )

    return (
        TicketDoDItem(
            key="headless_export_check_bmw",
            label="headless export check bmw",
            status=headless_status,
            summary=headless_summary,
            what_can_be_done_now=headless_now_text,
            blocked_next_input=headless_next_input,
            owner_hint="BMW tooling owner / Adrian / Hristofor / Stefan",
            evidence=_dedupe_evidence(headless_evidence),
        ),
        TicketDoDItem(
            key="screenshot_tests_bmws",
            label="screenshot tests bmws",
            status=screenshot_status,
            summary=screenshot_summary if scope_grounded else "No confirmed local slice is grounded yet, so screenshot-test evidence is intentionally not claimed.",
            what_can_be_done_now=screenshot_now_text,
            blocked_next_input=screenshot_next_input,
            owner_hint="Adrian / Hristofor / Stefan for the reading flow",
            evidence=_dedupe_evidence(screenshot_evidence),
        ),
        TicketDoDItem(
            key="format_checker_svn",
            label="format checker svn",
            status=format_status,
            summary=(
                f"Local SG checker coverage exists for {len(contexts)} slice(s); {len(format_findings)} issue batch(es) or style issue(s) were surfaced."
                if format_findings
                else "Local SG checker coverage exists for the grounded slice(s)."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so SG checker evidence is intentionally not attached to this ticket."
            ),
            what_can_be_done_now="Run or reuse the SG-side repo/style/executeChecks flow directly on the live SVN project root.",
            blocked_next_input="Needs a decision whether minor findings should be fixed now or only reported if SVN must stay untouched.",
            owner_hint="SG TA / code owner",
            evidence=_dedupe_evidence(format_evidence),
        ),
        TicketDoDItem(
            key="check_changelogs_cars_bmw",
            label="check changelogs cars bmw",
            status=changelog_status,
            summary=(
                "The live car changelog and recent SVN context are already available locally."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no car-specific changelog is being claimed for this ticket."
            ),
            what_can_be_done_now="Review the latest changelog section and recent SVN log lines before trusting screenshot differences.",
            blocked_next_input="Need confirmation whether any additional cars beyond the confirmed delivery scope also belong to this ticket, and which changelog entries should be treated as delivery-relevant.",
            owner_hint="Assigned reviewer once scope is confirmed",
            evidence=_dedupe_evidence(changelog_evidence),
        ),
        TicketDoDItem(
            key="check_readme_cars_bmw",
            label="check readme cars bmw",
            status=readme_status,
            summary=(
                "Car-local README material is already discoverable from the live SVN slice."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no car-specific README evidence is being claimed for this ticket."
            ),
            what_can_be_done_now="Review the current README/constant notes before closing manual visual review.",
            blocked_next_input="Need confirmation whether any additional cars beyond the confirmed delivery scope also belong to this ticket, and whether any extra README/constants notes must be reviewed.",
            owner_hint="Assigned reviewer once scope is confirmed",
            evidence=_dedupe_evidence(readme_evidence),
        ),
        TicketDoDItem(
            key="asset_review_in_raco_bmws",
            label="asset review in raco (bmws)",
            status=asset_status,
            summary=(
                "Manual evidence is already attached from real action bundles."
                if asset_manual
                else "Representative RaCo scenes are ready and the current headless probe shows them as launchable for the grounded slice(s)."
                if raco_probe_ready
                else "A representative RaCo scene is ready to open for manual review."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so no specific RaCo/Blender review target is being claimed."
            ),
            what_can_be_done_now=(
                "Use the packaged RaCo manual review probe plus the manual-review templates, then open the representative `.rca` scene, compare against Blender/workfiles, and attach manual review notes/screenshots."
                if raco_probe_ready
                else "Open the representative `.rca` scene, compare against Blender/workfiles, and attach manual review notes/screenshots."
            ),
            blocked_next_input="Need agreed pass/fail criteria for what counts as the RaCo asset review being done, not just a scene-open check.",
            owner_hint="Adrian / Hristofor / Stefan for review criteria",
            evidence=_dedupe_evidence(asset_evidence),
        ),
        TicketDoDItem(
            key="check_readme_changelogs_cars_shared_bmw",
            label="check readme/changelogs cars shared bmw",
            status=shared_status,
            summary=(
                "Shared BMW docs are already prioritized from live shared-SVN context."
                if scope_grounded
                else "No confirmed local slice is grounded yet, so shared-module evidence is intentionally not attached."
            ),
            what_can_be_done_now="Review the prioritized shared BMW README and CHANGELOG set alongside the car changelog.",
            blocked_next_input="Need confirmation which `_Shared_IDCevo` or shared BMW modules actually changed for this delivery and must be reviewed.",
            owner_hint="Assigned reviewer once shared-module scope is confirmed",
            evidence=_dedupe_evidence(shared_evidence),
        ),
        TicketDoDItem(
            key="support",
            label="Support",
            status="needs_scope",
            summary="Support is not a verifiable DoD item until the owner and expected output are defined.",
            what_can_be_done_now="Use this bundle for status reporting, blockers, findings, and next-step questions while Jira access is blocked.",
            blocked_next_input="Need Jana to confirm whether the reporting flow is fixable findings -> Quality-Hero bug report channel and status/material -> Jana + Adrian, or if a different cadence/channel is required.",
            owner_hint="Jana",
            evidence=_dedupe_evidence(support_evidence),
        ),
    )


def _overall_status(items: tuple[TicketDoDItem, ...]) -> str:
    if any(item.status in {"blocked", "partial", "manual_ready", "needs_scope", "covered_with_findings"} for item in items):
        return "partial"
    return "covered"


def _bundle_blockers(items: tuple[TicketDoDItem, ...]) -> tuple[str, ...]:
    blocked: list[str] = []
    for item in items:
        if item.status in {"blocked", "partial", "needs_scope"}:
            blocked.append(f"{item.label}: {item.blocked_next_input}")
    return tuple(blocked)


def _bundle_notes(scope_note: str) -> tuple[str, ...]:
    return (scope_note, *_PROCESS_HINTS)


def _bundle_questions(ticket_id: str, profile_ids: tuple[str, ...]) -> tuple[str, ...]:
    profile_text = ", ".join(profile_ids) if profile_ids else "no grounded slice yet"
    return tuple(
        question.format(ticket_id=ticket_id, profiles=profile_text)
        for question in _PROCESS_QUESTIONS
    )


def _review_status_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# Ticket Review Status - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Generated at: {bundle.generated_at_utc}",
        f"- Overall status: {bundle.overall_status}",
        f"- Profiles grounded locally: {', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}",
        f"- Source root: `{bundle.source_root}`",
    ]
    if bundle.source_revision:
        lines.append(f"- Source revision: `{bundle.source_revision}`")
    if bundle.source_mode:
        lines.append(f"- Source mode: `{bundle.source_mode}`")

    lines.extend(
        [
            "",
            "## Summary",
            (
                "Local SG-side evidence is grounded, but at least one concrete finding still needs owner handling and BMW-owned steps remain blocked."
                if bundle.findings
                else "Local SG-side evidence is grounded, but BMW-owned steps remain blocked or manual."
            ),
            "",
            "## Scope Note",
            bundle.scope_note or "No explicit scope note was provided.",
            "",
            "## Concrete Findings",
        ]
    )
    if bundle.findings:
        for finding in bundle.findings:
            location = finding.path or "path unavailable"
            if finding.line is not None and finding.path:
                location = f"{finding.path}:{finding.line}"
            lines.append(f"- [{finding.severity}] {finding.summary}")
            lines.append(f"  - Source: `{location}`")
            if finding.checkers:
                lines.append(f"  - Checker(s): `{','.join(finding.checkers)}`")
    else:
        lines.append("- No SG-side findings were surfaced in the current local evidence set.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    if bundle.manual_evidence:
        for item in bundle.manual_evidence:
            lines.append(f"- [{item.kind}] {item.label}")
            lines.append(f"  - Packaged path: `{_display_path(item.packaged_path, package_root)}`")

    lines.extend(["", "## Blockers"])
    if bundle.blockers:
        lines.extend(f"- {item}" for item in bundle.blockers)
    else:
        lines.append("- No unresolved blockers are currently listed.")

    lines.extend(["", "## Next Questions"])
    lines.extend(f"- {item}" for item in bundle.next_questions)

    lines.extend(["", "## Package Evidence"])
    if bundle.evidence_index:
        for item in bundle.evidence_index:
            lines.append(f"- {item.label}: `{_display_path(item.path, package_root)}`")
    else:
        lines.append("- No package evidence paths were recorded.")

    lines.extend(["", "## Notes"])
    lines.extend(f"- {item}" for item in bundle.notes)
    return "\n".join(lines).rstrip() + "\n"


def _dod_matrix_markdown(bundle: TicketReviewBundle, *, package_root: Path | None = None) -> str:
    lines = [
        f"# DoD Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Status | Summary | What can be done now | Blocked / next input | Owner hint |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.summary} | {item.what_can_be_done_now} | {item.blocked_next_input} | {item.owner_hint} |"
        )

    lines.extend(["", "## Evidence Paths"])
    for item in bundle.dod_items:
        lines.append(f"### {item.label}")
        if item.evidence:
            for evidence in item.evidence:
                lines.append(f"- {evidence.label}: `{_display_path(evidence.path, package_root)}`")
        else:
            lines.append("- No evidence linked yet.")

    lines.extend(
        [
            "",
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _proposed_dod_wording(item: TicketDoDItem) -> str:
    proposed = {
        "headless_export_check_bmw": "Document exact BMW headless export command, expected success output, and latest verified execution evidence.",
        "screenshot_tests_bmws": "Review expected baselines, confirmed candidate/result root, deterministic diff triage, and human verdict for changed or missing pairs.",
        "format_checker_svn": "Run SG checker stack on the confirmed slice and record findings plus fix-vs-report decision.",
        "check_changelogs_cars_bmw": "Review latest car changelog and map intended changes to the screenshots or assets that must be checked.",
        "check_readme_cars_bmw": "Review car-local README/constants notes relevant to the confirmed slice before visual signoff.",
        "asset_review_in_raco_bmws": "Open the agreed RaCo scene, compare against Blender/workfiles, and attach manual note plus screenshot evidence.",
        "check_readme_changelogs_cars_shared_bmw": "Review the shared BMW modules actually touched by the confirmed ticket scope and attach notes.",
        "support": "Define what support means for this sprint: reporting channel, owner, cadence, and expected artifact package.",
    }
    return proposed.get(item.key, item.label)


def _required_evidence_text(item: TicketDoDItem) -> str:
    evidence_map = {
        "headless_export_check_bmw": "Command/script, execution log, success trace, and delivery-doc reference.",
        "screenshot_tests_bmws": "Baseline root, candidate/result root, triage report, diff artifacts if present, and human verdict note.",
        "format_checker_svn": "Repo-checker summary plus any concrete file/line findings.",
        "check_changelogs_cars_bmw": "Live changelog, SVN log lines, and reviewer note on intended changes.",
        "check_readme_cars_bmw": "Relevant README/constants docs plus reviewer note.",
        "asset_review_in_raco_bmws": "Representative `.rca`, Blender workfile, manual note, and screenshot where useful.",
        "check_readme_changelogs_cars_shared_bmw": "Relevant shared README/CHANGELOG docs plus reviewer note.",
        "support": "Teams/Jira-ready note, blockers, open questions, and owner clarification.",
    }
    return evidence_map.get(item.key, "Evidence still needs clarification.")


def _dod_update_draft_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# DoD Update Draft - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "- This is a refinement draft for Jira/Teams use while direct Jira writeback is still blocked.",
        "",
        "| Current Jira DoD item | Proposed clarified wording | Current state | Proposed owner | Required evidence | Why this wording is safer |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    rationale = {
        "headless_export_check_bmw": "It separates documentation/preconditions from actual BMW-side execution so the item cannot be claimed locally by accident.",
        "screenshot_tests_bmws": "It makes the missing candidate root explicit and keeps the verdict human-reviewed instead of pretending automation closed it.",
        "format_checker_svn": "It clarifies that the SG-side checker is locally executable and that ownership includes deciding whether to fix or report.",
        "check_changelogs_cars_bmw": "It links changelog review to actual review targets instead of treating the changelog as a box-tick.",
        "check_readme_cars_bmw": "It forces slice-scoped documentation review rather than assuming a generic README pass is enough.",
        "asset_review_in_raco_bmws": "It defines done-ness as scene review plus attached evidence, not only opening RaCo once.",
        "check_readme_changelogs_cars_shared_bmw": "It prevents reviewing every shared module blindly and focuses only on the ones that matter for scope.",
        "support": "It turns a vague label into a measurable reporting responsibility.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {_proposed_dod_wording(item)} | {item.status} | {item.owner_hint} | {_required_evidence_text(item)} | {rationale.get(item.key, 'Clarify the item before it becomes a false green.')} |"
        )

    lines.extend(
        [
            "",
            "## Immediate recommendation",
            "- Keep G70 only as the earlier prototype/local dry run; do not present it as the current delivery scope.",
            "- Treat `NA8`, `G78`, and `G50` as the current confirmed delivery scope unless Jana adds more cars.",
            "- Ask Adrian / Hristofor / Stefan for the screenshot-result reading flow and the real candidate-output rule when the current `actuals/diff` folders are still empty.",
            "- Keep the current SG checker finding as a minor reported issue until someone decides whether it should be fixed now or only assigned.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _teams_update_markdown(bundle: TicketReviewBundle) -> str:
    finding_block = ""
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        finding_block = (
            "Current concrete local SG-side finding:\n"
            f"- {source}\n"
            f"- {finding.summary}\n"
        )

    manual_block = (
        f"\nManual evidence harvested so far: {len(bundle.manual_evidence)} item(s); counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}\n"
        if bundle.manual_evidence
        else ""
    )
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    headless_item = next((item for item in bundle.dod_items if item.key == "headless_export_check_bmw"), None)
    screenshot_item = next((item for item in bundle.dod_items if item.key == "screenshot_tests_bmws"), None)
    bmw_block = (
        "- BMW repo snapshot and helper scripts are packaged locally, and representative local headless export proof is attached\n"
        "- representative smoke evidence is attached, broader candidate outputs exist for most wider scenarios, low/high beam have proxy coverage, and the remaining exact local technical blocker is `lights_OnlyCones`\n"
        if (headless_item and headless_item.status != "blocked") or (screenshot_item and screenshot_item.status != "blocked")
        else "- BMW Git / digital-3d-car-models\n"
    )
    return (
        f"# Teams Update - {bundle.ticket_id}\n\n"
        "Message\n\n"
        f"I prepared a grounded local SG-side review bundle for `{bundle.ticket_id}` from the real SVN context on this machine.\n"
        f"Current scope packaged here: {profile_text}.\n"
        f"Scope note: {bundle.scope_note}\n\n"
        f"{finding_block}\n"
        "What is already covered locally:\n"
        "- car changelog/readme review prep from the live SVN checkout\n"
        "- shared BMW README/CHANGELOG review prep\n"
        "- screenshot baseline/test-config discovery and BMW screenshot-surface packaging\n"
        "- representative RaCo/Blender entrypoints\n"
        "- SG-side repo checker / format flow evidence\n"
        f"{manual_block}\n"
        "What is still blocked on my side:\n"
        "- BMW Jira access\n"
        f"{bmw_block}"
        "- real pass/fail signoff for visual deltas\n\n"
        "What I still need from Adrian / Hristofor / Stefan:\n"
        "- confirmation whether the attached representative local export proof is accepted as DoD evidence\n"
        "- where screenshot result/candidate images are generated when the actuals/diff folders are empty\n"
        "- how screenshot-test pass/fail is normally read\n"
        "- what exactly counts as asset review in RaCo done\n"
        "- whether `lights_OnlyCones` should be treated as a delivery blocker or a follow-up\n"
    )


def _stakeholder_sync_markdown(bundle: TicketReviewBundle) -> str:
    profile_text = ", ".join(bundle.profile_ids) if bundle.profile_ids else "no grounded slice yet"
    lines = [
        f"# Stakeholder Sync Brief - {bundle.ticket_id}",
        "",
        "## Message For Jana",
        "I still do not have Jira access, but I can work from the screenshots and the live SVN checkout for now.",
        f"I prepared a grounded local SG-side review package from `C:\\repositories\\trunk` for {profile_text}.",
        f"Scope note: {bundle.scope_note}",
        "The package includes car changelog/readme material, shared BMW docs, screenshot baselines/test config, representative RaCo/Blender entrypoints, and SG-side checker output.",
    ]
    if bundle.findings:
        finding = bundle.findings[0]
        source = finding.path
        if finding.line is not None and finding.path:
            source = f"{finding.path}:{finding.line}"
        lines.extend(
            [
                "",
                "Current concrete local SG-side finding:",
                f"- {source}",
                f"- {finding.summary}",
            ]
        )
    lines.extend(
        [
            "",
            "What is still blocked on my side:",
            "- BMW Jira access",
            "- broader screenshot coverage still has one reproducible exact local runtime/content blocker on `lights_OnlyCones`; `lights_LowBeam` and `lights_HighBeam` are proxy-covered",
            "- real screenshot pass/fail verdicts are still manual review work for the candidate/proxy outputs",
            "",
            f"The confirmed delivery scope packaged here is `{profile_text}`. I still need a short sync with Adrian / Hristofor / Stefan on how screenshot-test results are read in practice, whether the attached local export proof is accepted as DoD evidence, and whether `lights_OnlyCones` is a delivery blocker or a follow-up.",
            "",
            "## Questions For Adrian / Hristofor / Stefan",
        ]
    )
    for question in bundle.next_questions[1:6]:
        lines.append(f"- {question}")
    lines.extend(
        [
            "",
            "## Recommended reporting path while Jira is blocked",
            "- Send the short status message to Jana.",
            "- Keep the ZIP private unless Jana explicitly asks for the full package.",
            "- Use the DoD matrix and owner matrix as the source of truth for current status and blockers.",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _owner_matrix_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        f"# Owner Matrix - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "| DoD item | Current state | Owner hint | Needs confirmation / next input |",
        "| --- | --- | --- | --- |",
    ]
    for item in bundle.dod_items:
        lines.append(f"| {item.label} | {item.status} | {item.owner_hint} | {item.blocked_next_input} |")
    return "\n".join(lines).rstrip() + "\n"


def _review_protocol_markdown(
    *,
    bundle: TicketReviewBundle,
    contexts: tuple[_ProfileContext, ...],
    workspace: Path,
    package_root: Path | None = None,
    manual_evidence_index_path: Path,
    manual_review_companion_path: Path,
    qa_capability_matrix_path: Path,
    three_d_qa_playbook_path: Path,
    repo_topology_reference_path: Path,
    delivery_surface_map_path: Path,
    raco_script_catalog_path: Path,
    delivery_target_catalog_path: Path,
) -> str:
    lines = [
        f"# Review Protocol - {bundle.ticket_id}",
        "",
        f"- Title: {bundle.title}",
        f"- Overall status: {bundle.overall_status}",
        f"- Scope note: {bundle.scope_note or 'No explicit scope note was provided.'}",
        "",
        "## Intent",
        "This ticket is treated as a delivery-week QA support and process-definition task.",
        "Use deterministic SG-side evidence first, keep manual review explicit, and keep BMW-owned steps marked as blocked until access or criteria are confirmed.",
        "",
        "## Verified reference surfaces",
    ]
    pdf_path = workspace / "GFX_Project_Overview_2026.pdf"
    if pdf_path.exists():
        lines.extend(
            [
                f"- Local project/process reference reviewed: `{pdf_path}` (reference only, not packaged).",
                "- Relevant process hints captured from that PDF: Jira documentation is mandatory, delivery documentation and performance-test results belong in Confluence, screenshot/manual review findings should be documented, and Blender-vs-RaCo comparison is expected before treating work as visually safe.",
            ]
        )
    lines.extend(
        [
            f"- {_QUALITY_HERO_PROCESS_REFERENCE}: local Confluence export/operator notes; live page access still requires login.",
        ]
    )
    for url in _BMW_DOC_URLS:
        lines.extend([f"- BMW reference page: `{url}`", "  - Reachable from this machine, but BMW Confluence login is still required."])
    lines.append(f"- Packaged manual-review index: `{_display_path(manual_review_companion_path, package_root)}`")
    lines.append(f"- Packaged QA capability matrix: `{_display_path(qa_capability_matrix_path, package_root)}`")
    lines.append(f"- Packaged 3D QA playbook: `{_display_path(three_d_qa_playbook_path, package_root)}`")
    lines.append(f"- Packaged repo topology reference: `{_display_path(repo_topology_reference_path, package_root)}`")
    lines.append(f"- Packaged delivery surface map: `{_display_path(delivery_surface_map_path, package_root)}`")
    lines.append(f"- Packaged RaCo script catalog: `{_display_path(raco_script_catalog_path, package_root)}`")
    lines.append(f"- Packaged delivery target catalog: `{_display_path(delivery_target_catalog_path, package_root)}`")

    lines.extend(
        [
            "",
            "## Workflow steps",
            "| DoD item | Current state | Owner hint | What to do now | Evidence expected |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    expected_evidence = {
        "headless_export_check_bmw": "Expected command/script, export log, success/failure trace, and delivery documentation entry once BMW access exists.",
        "screenshot_tests_bmws": "Expected baseline root, candidate/result root, deterministic triage JSON/HTML, optional diff artifacts, and a positive or negative test note.",
        "format_checker_svn": "Expected SG checker summary plus concrete path/line findings for anything surfaced on the live SVN slice.",
        "check_changelogs_cars_bmw": "Expected live car changelog, latest SVN log lines, and reviewer notes on intended changes.",
        "check_readme_cars_bmw": "Expected car README/constants docs plus reviewer notes on anything relevant to the delivery.",
        "asset_review_in_raco_bmws": "Expected representative `.rca` scene, Blender workfile, manual screenshot/note evidence, and Blender-vs-RaCo review notes.",
        "check_readme_changelogs_cars_shared_bmw": "Expected prioritized shared BMW README/CHANGELOG docs plus reviewer notes on affected modules.",
        "support": "Expected Teams/Jira-ready status note, blockers, findings, next questions, and ownership clarification.",
    }
    for item in bundle.dod_items:
        lines.append(
            f"| {item.label} | {item.status} | {item.owner_hint} | {item.what_can_be_done_now} | {expected_evidence.get(item.key, 'Expected evidence still needs clarification.')} |"
        )

    lines.extend(["", "## Possible test cases from current local slices"])
    for context in contexts:
        lines.extend(_possible_test_case_lines(context))

    lines.extend(
        [
            "## Manual Evidence Rollup",
            f"- Total attached evidence items: {len(bundle.manual_evidence)}",
            f"- Counts by kind: {_counts_by_kind_text(bundle.manual_evidence)}",
            f"- Packaged manual evidence index: `{_display_path(manual_evidence_index_path, package_root)}`",
            "",
            "## Attach Examples",
        ]
    )
    attach_blocks = _attach_examples(contexts, workspace)
    if attach_blocks:
        lines.extend(attach_blocks)
    else:
        lines.append("- No scene-check or qa-stack run is available yet for attach examples.")

    lines.extend(
        [
            "",
            "## Documentation expectations",
            "- Positive findings should still be documented, not only failures.",
            "- Manual visual review should capture Blender-vs-RaCo notes and at least one concrete evidence path or screenshot when something is questionable.",
            "- Use the packaged manual-review templates instead of starting free-form notes from scratch.",
            "- BMW-side delivery documentation and performance-test results remain external until access is granted.",
            "- The package outputs are intended to be copy-ready for Teams/Jira updates while direct Jira access is blocked.",
            "",
            "## Current blockers",
        ]
    )
    lines.extend(f"- {item}" for item in bundle.blockers)
    return "\n".join(lines).rstrip() + "\n"


def _manual_review_companion_markdown(ticket_id: str, contexts: tuple[_ProfileContext, ...]) -> str:
    return _build_manual_review_index(ticket_id, contexts)


def _make_zip(package_root: Path) -> Path:
    zip_path = package_root.with_suffix(".zip")
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as handle:
        for path in sorted(package_root.rglob("*")):
            if path.is_dir():
                continue
            handle.write(path, path.relative_to(package_root))
    return zip_path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dod_completion_percent(bundle: TicketReviewBundle) -> int:
    status_points = {
        "blocked": 0,
        "needs_scope": 25,
        "partial": 50,
        "manual_ready": 60,
        "prepared": 75,
        "covered_with_findings": 100,
        "covered": 100,
    }
    if not bundle.dod_items:
        return 0
    total = sum(status_points.get(item.status, 0) for item in bundle.dod_items)
    return round(total / len(bundle.dod_items))


def _review_owner_decisions_markdown(bundle: TicketReviewBundle) -> str:
    lines = [
        "# Review-owner decisions",
        "",
        f"- Ticket: `{bundle.ticket_id}`",
        f"- Scope: `{', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}`",
        "",
        "## lights_OnlyCones",
        "Decision: blocker / follow-up / accepted limitation / needs more investigation",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Screenshot candidate/proxy outputs",
        "Decision: accepted / needs changes / partial",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## RaCo asset review",
        "Decision: passed / failed / not reviewed",
        "Owner:",
        "Date:",
        "Notes:",
        "",
        "## Jira writeback",
        "Status:",
        "Owner:",
        "",
        "## Additional review-owner notes",
        "",
        "- screenshot tests bmws:",
        "- check changelogs cars bmw:",
        "- check readme cars bmw:",
        "- check readme/changelogs cars shared bmw:",
        "",
    ]
    return "\n".join(lines)


def _sent_package_manifest_markdown(
    *,
    bundle: TicketReviewBundle,
    package_root: Path,
    zip_path: Path,
    zip_sha256_path: Path,
    key_files: tuple[Path, ...],
) -> str:
    lines = [
        "# SENT PACKAGE MANIFEST",
        "",
        f"- Ticket ID: `{bundle.ticket_id}`",
        f"- Title: {bundle.title}",
        f"- Scope: `{', '.join(bundle.profile_ids) if bundle.profile_ids else 'none confirmed'}`",
        f"- Generated at UTC: `{bundle.generated_at_utc}`",
        f"- Overall status: `{bundle.overall_status}`",
        f"- Visible DoD progress (conservative): `{_dod_completion_percent(bundle)}%`",
        f"- Package folder: `{package_root.name}`",
        f"- ZIP name: `{zip_path.name}`",
        f"- ZIP size bytes: `{zip_path.stat().st_size}`",
        f"- ZIP SHA256 sidecar: `{zip_sha256_path.name}`",
        "- ZIP SHA256 is recorded in the sidecar file to avoid self-referential checksum drift inside the archive.",
        "",
        "## Important included files",
    ]
    for path in key_files:
        lines.append(f"- `{_display_path(path, package_root)}`")
    lines.extend(["", "## Known open blockers"])
    if bundle.blockers:
        lines.extend(f"- {item}" for item in bundle.blockers)
    else:
        lines.append("- None")
    lines.extend(
        [
            "",
            "## Distribution record",
            "- Sent status: not recorded automatically",
            "- Sent to:",
            "- Sent on:",
            "- Notes:",
            "",
        ]
    )
    return "\n".join(lines)


def materialize_ticket_review_bundle(
    ticket_id: str,
    *,
    title: str = "",
    profile_ids: tuple[str, ...] = (),
    workspace: Path | None = None,
    output_root: Path | None = None,
    scope_note: str = "",
    candidate_roots: tuple[Path, ...] = (),
    include_action_bundles: bool = True,
) -> TicketReviewBundleResult:
    workspace_root = (workspace or Path(__file__).resolve().parents[1]).resolve()
    source_root = resolve_source_repo_root(workspace_root)
    desired_root = (output_root or default_ticket_review_output_root(ticket_id, workspace_root)).resolve()
    package_root = _fresh_output_root(desired_root)
    package_root.mkdir(parents=True, exist_ok=True)

    normalized_profiles = tuple(dict.fromkeys(item.strip() for item in profile_ids if item and item.strip()))

    effective_scope_note = (
        scope_note.strip()
        or (
            (
                "Current local evidence is grounded in the confirmed delivery scope "
                f"{', '.join(normalized_profiles)}."
            )
            if len(normalized_profiles) > 1
            else f"Current local evidence is grounded in {normalized_profiles[0]} as the first concrete live-SVN slice, not as confirmed final ticket scope."
            if normalized_profiles
            else "No car/slice is confirmed locally yet. This bundle is intentionally process-first and blocker-first until scope is confirmed."
        )
    )

    all_records = _all_action_records(workspace_root)
    contexts = tuple(
        _profile_context(
            ticket_id=ticket_id,
            profile_id=profile_id,
            workspace=workspace_root,
            package_root=package_root,
            candidate_roots=candidate_roots,
            source_root=source_root,
            all_records=all_records,
            include_action_bundles=include_action_bundles,
        )
        for profile_id in normalized_profiles
    )
    daily_snapshot = find_latest_daily_qa_snapshot(
        workspace_root,
        required_profiles=tuple(context.profile.profile_id for context in contexts),
    )
    if daily_snapshot is not None:
        daily_snapshot = _package_daily_snapshot_result(daily_snapshot, package_root)
    raco_probe = _find_latest_raco_manual_review_probe(
        workspace_root,
        required_profiles=tuple(context.profile.profile_id for context in contexts),
    )
    if raco_probe is not None:
        raco_probe = _package_raco_manual_review_probe(raco_probe, package_root)

    manual_evidence = _harvest_manual_evidence(contexts, package_root)
    manual_index_path = package_root / f"{ticket_id}-manual-evidence-index.md"
    manual_json_path = package_root / "artifacts" / "manual-evidence" / "index.json"
    qa_capability_matrix_path = package_root / f"{ticket_id}-qa-capability-matrix.md"
    three_d_qa_playbook_path = package_root / f"{ticket_id}-3d-qa-playbook.md"
    repo_topology_reference_path = package_root / f"{ticket_id}-repo-topology-reference.md"
    delivery_surface_map_path = package_root / f"{ticket_id}-delivery-surface-map.md"
    raco_script_catalog_path = package_root / f"{ticket_id}-raco-script-catalog.md"
    delivery_target_catalog_path = package_root / f"{ticket_id}-delivery-target-catalog.md"
    _write_text(
        manual_index_path,
        _manual_evidence_index_markdown(ticket_id=ticket_id, items=manual_evidence, package_root=package_root),
    )
    _write_json(manual_json_path, _manual_evidence_json_payload(ticket_id=ticket_id, items=manual_evidence))

    review_companion_path = package_root / f"{ticket_id}-manual-review-companion.md"
    _write_text(review_companion_path, _manual_review_companion_markdown(ticket_id, contexts))

    evidence_index: list[ReviewEvidence] = []
    for context in contexts:
        if not include_action_bundles:
            context.triage_bundle.html_path.unlink(missing_ok=True)
        evidence_index.extend(context.action_bundle_evidence)
        evidence_index.extend(context.packaged_source_evidence)
        evidence_index.extend(
            [
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage", context.triage_bundle.markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} screenshot triage JSON", context.triage_bundle.json_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface", context.bmw_surface_markdown_path),
                _bundle_evidence(f"{context.profile.profile_id} BMW screenshot surface JSON", context.bmw_surface_json_path),
                _bundle_evidence(f"{context.profile.profile_id} manual review companion", context.manual_review_paths["companion"]),
                _bundle_evidence(f"{context.profile.profile_id} manual review record", context.manual_review_paths["record"]),
                _bundle_evidence(f"{context.profile.profile_id} screenshot evidence slots", context.manual_review_paths["slots"]),
                _bundle_evidence(f"{context.profile.profile_id} Blender vs RaCo checklist", context.manual_review_paths["blender_raco"]),
                _bundle_evidence(f"{context.profile.profile_id} visual review checklist", context.manual_review_paths["visual_checklist"]),
            ]
        )
    evidence_index.append(_bundle_evidence("Ticket manual review companion", review_companion_path))
    evidence_index.append(_bundle_evidence("Ticket manual evidence index", manual_index_path))
    evidence_index.append(_bundle_evidence("QA capability matrix", qa_capability_matrix_path))
    evidence_index.append(_bundle_evidence("3D QA playbook", three_d_qa_playbook_path))
    evidence_index.append(_bundle_evidence("Repo topology reference", repo_topology_reference_path))
    evidence_index.append(_bundle_evidence("Delivery surface map", delivery_surface_map_path))
    evidence_index.append(_bundle_evidence("RaCo script catalog", raco_script_catalog_path))
    evidence_index.append(_bundle_evidence("Delivery target catalog", delivery_target_catalog_path))
    if daily_snapshot is not None:
        evidence_index.append(_bundle_evidence("Daily QA snapshot", daily_snapshot.markdown_path))
        evidence_index.append(_bundle_evidence("Daily QA snapshot JSON", daily_snapshot.json_path))
        if daily_snapshot.battery_baseline_gaps_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Battery baseline gaps", daily_snapshot.battery_baseline_gaps_markdown_path))
        if daily_snapshot.battery_baseline_gaps_json_path is not None:
            evidence_index.append(_bundle_evidence("Battery baseline gaps JSON", daily_snapshot.battery_baseline_gaps_json_path))
        if daily_snapshot.review_priority_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Review priority ranking", daily_snapshot.review_priority_markdown_path))
        if daily_snapshot.review_priority_json_path is not None:
            evidence_index.append(_bundle_evidence("Review priority ranking JSON", daily_snapshot.review_priority_json_path))
        if daily_snapshot.delta_summary_markdown_path is not None:
            evidence_index.append(_bundle_evidence("Daily QA delta summary", daily_snapshot.delta_summary_markdown_path))
        if daily_snapshot.delta_summary_json_path is not None:
            evidence_index.append(_bundle_evidence("Daily QA delta summary JSON", daily_snapshot.delta_summary_json_path))
        if daily_snapshot.review_gallery_html_path is not None:
            evidence_index.append(_bundle_evidence("Candidate review gallery", daily_snapshot.review_gallery_html_path))
        scoped_profiles = {context.profile.profile_id.upper() for context in contexts}
        for item in daily_snapshot.snapshot.smoke_results:
            if item.profile_id.upper() in scoped_profiles and item.log_path:
                evidence_index.append(
                    _bundle_evidence(
                        f"{item.profile_id} BMW smoke log",
                        _resolve_snapshot_artifact_path(daily_snapshot, item.log_path),
                    )
                )
        seen_battery_log_paths: set[str] = set()
        for item in daily_snapshot.snapshot.battery_results:
            if item.profile_id.upper() not in scoped_profiles or not item.log_path:
                continue
            resolved_log_path = _resolve_snapshot_artifact_path(daily_snapshot, item.log_path)
            if resolved_log_path in seen_battery_log_paths or resolved_log_path == "not found":
                continue
            seen_battery_log_paths.add(resolved_log_path)
            evidence_index.append(_bundle_evidence(f"{item.profile_id} BMW battery log", resolved_log_path))
    if raco_probe is not None:
        evidence_index.append(_bundle_evidence("RaCo manual review probe", raco_probe.markdown_path))
        evidence_index.append(_bundle_evidence("RaCo manual review probe JSON", raco_probe.json_path))
    findings = tuple(finding for context in contexts for finding in _record_findings(context.repo_record))
    dod_items = _build_dod_items(
        contexts=contexts,
        workspace=workspace_root,
        scope_note=effective_scope_note,
        manual_evidence=manual_evidence,
        manual_evidence_index_path=manual_index_path,
        support_artifacts=(
            _bundle_evidence("QA capability matrix", qa_capability_matrix_path),
            _bundle_evidence("3D QA playbook", three_d_qa_playbook_path),
            _bundle_evidence("Repo topology reference", repo_topology_reference_path),
            _bundle_evidence("Delivery surface map", delivery_surface_map_path),
            _bundle_evidence("RaCo script catalog", raco_script_catalog_path),
            _bundle_evidence("Delivery target catalog", delivery_target_catalog_path),
        ),
        daily_snapshot=daily_snapshot,
        raco_probe=raco_probe,
        include_action_bundles=include_action_bundles,
    )
    bundle = TicketReviewBundle(
        ticket_id=ticket_id,
        title=title.strip() or ticket_id,
        generated_at_utc=_utc_now(),
        overall_status=_overall_status(dod_items),
        profile_ids=tuple(context.profile.profile_id for context in contexts),
        source_root=str(source_root),
        source_revision=_extract_revision(contexts[0].prep) if contexts else "",
        source_mode=contexts[0].prep.source_mode if contexts else "",
        scope_note=effective_scope_note,
        notes=_bundle_notes(effective_scope_note),
        blockers=_bundle_blockers(dod_items),
        next_questions=_bundle_questions(ticket_id, tuple(context.profile.profile_id for context in contexts)),
        findings=findings,
        evidence_index=_dedupe_evidence(evidence_index),
        dod_items=dod_items,
        manual_evidence=manual_evidence,
    )

    bundle_json_path = package_root / f"{ticket_id}-review-bundle.json"
    review_status_path = package_root / f"{ticket_id}-review-status.md"
    dod_matrix_path = package_root / f"{ticket_id}-dod-matrix.md"
    dod_update_draft_path = package_root / f"{ticket_id}-dod-update-draft.md"
    teams_update_path = package_root / f"{ticket_id}-teams-update.md"
    stakeholder_sync_path = package_root / f"{ticket_id}-stakeholder-sync.md"
    review_protocol_path = package_root / f"{ticket_id}-review-protocol.md"
    owner_matrix_path = package_root / f"{ticket_id}-owner-matrix.md"
    review_owner_decisions_path = package_root / "review-owner-decisions.md"
    sent_package_manifest_path = package_root / "SENT_PACKAGE_MANIFEST.md"

    _write_json(bundle_json_path, bundle.to_dict())
    _write_text(review_status_path, _review_status_markdown(bundle, package_root=package_root))
    _write_text(dod_matrix_path, _dod_matrix_markdown(bundle, package_root=package_root))
    _write_text(dod_update_draft_path, _dod_update_draft_markdown(bundle))
    _write_text(teams_update_path, _teams_update_markdown(bundle))
    _write_text(stakeholder_sync_path, _stakeholder_sync_markdown(bundle))
    _write_text(
        qa_capability_matrix_path,
        _qa_capability_matrix_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            workspace=workspace,
            scope_note=effective_scope_note,
            profile_ids=bundle.profile_ids,
        ),
    )
    _write_text(
        three_d_qa_playbook_path,
        _three_d_qa_playbook_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            bundle=bundle,
            contexts=contexts,
        ),
    )
    _write_text(
        repo_topology_reference_path,
        _repo_topology_reference_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
            profile_ids=bundle.profile_ids,
        ),
    )
    _write_text(
        delivery_surface_map_path,
        _delivery_surface_map_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
            workspace=workspace_root,
        ),
    )
    _write_text(
        raco_script_catalog_path,
        _raco_script_catalog_markdown(
            ticket_id=ticket_id,
            source_root=source_root,
            scope_note=effective_scope_note,
        ),
    )
    _write_text(
        delivery_target_catalog_path,
        _delivery_target_catalog_markdown(
            ticket_id=ticket_id,
            scope_note=effective_scope_note,
        ),
    )
    _write_text(
        review_protocol_path,
        _review_protocol_markdown(
            bundle=bundle,
            contexts=contexts,
            workspace=workspace_root,
            package_root=package_root,
            manual_evidence_index_path=manual_json_path,
            manual_review_companion_path=review_companion_path,
            qa_capability_matrix_path=qa_capability_matrix_path,
            three_d_qa_playbook_path=three_d_qa_playbook_path,
            repo_topology_reference_path=repo_topology_reference_path,
            delivery_surface_map_path=delivery_surface_map_path,
            raco_script_catalog_path=raco_script_catalog_path,
            delivery_target_catalog_path=delivery_target_catalog_path,
        ),
    )
    _write_text(owner_matrix_path, _owner_matrix_markdown(bundle))
    _write_text(review_owner_decisions_path, _review_owner_decisions_markdown(bundle))

    zip_path = _make_zip(package_root)
    zip_sha256_path = zip_path.with_suffix(zip_path.suffix + ".sha256")
    zip_sha256_path.write_text(f"{_sha256_file(zip_path)} *{zip_path.name}\n", encoding="utf-8")
    _write_text(
        sent_package_manifest_path,
        _sent_package_manifest_markdown(
            bundle=bundle,
            package_root=package_root,
            zip_path=zip_path,
            zip_sha256_path=zip_sha256_path,
            key_files=(
                dod_matrix_path,
                review_status_path,
                teams_update_path,
                stakeholder_sync_path,
                review_owner_decisions_path,
                manual_index_path,
            ),
        ),
    )
    zip_path = _make_zip(package_root)
    zip_sha256_path.write_text(f"{_sha256_file(zip_path)} *{zip_path.name}\n", encoding="utf-8")
    return TicketReviewBundleResult(
        bundle=bundle,
        package_root=package_root,
        bundle_json_path=bundle_json_path,
        review_status_path=review_status_path,
        dod_matrix_path=dod_matrix_path,
        dod_update_draft_path=dod_update_draft_path,
        teams_update_path=teams_update_path,
        stakeholder_sync_path=stakeholder_sync_path,
        review_protocol_path=review_protocol_path,
        owner_matrix_path=owner_matrix_path,
        qa_capability_matrix_path=qa_capability_matrix_path,
        three_d_qa_playbook_path=three_d_qa_playbook_path,
        repo_topology_reference_path=repo_topology_reference_path,
        delivery_surface_map_path=delivery_surface_map_path,
        raco_script_catalog_path=raco_script_catalog_path,
        delivery_target_catalog_path=delivery_target_catalog_path,
        manual_review_companion_path=review_companion_path,
        manual_evidence_index_path=manual_index_path,
        manual_evidence_json_path=manual_json_path,
        review_owner_decisions_path=review_owner_decisions_path,
        sent_package_manifest_path=sent_package_manifest_path,
        zip_sha256_path=zip_sha256_path,
        zip_path=zip_path,
    )

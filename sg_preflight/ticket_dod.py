from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from sg_preflight.services import prerequisite_status

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

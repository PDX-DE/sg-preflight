from __future__ import annotations

from copy import deepcopy
from typing import Any


def normalize_lackcode(value: str) -> str:
    """Normalize BMW Lackcode values for Car Paints lookup.

    BMW process notes call out that a value such as `0C5A` from CheckIn or DLT
    evidence should be searched as `C5A` in the car-paint reference pages.
    """

    normalized = "".join(str(value).strip().split()).upper()
    if not normalized:
        return ""
    stripped = normalized.lstrip("0")
    return stripped or "0"


def bmw_interface_smoke_commands(
    target: str = "<target>",
    *,
    python_executable: str = "python",
    script: str = "ci/scripts/car_manager.py",
) -> tuple[str, ...]:
    target_value = target.strip() if target.strip() else "<target>"
    return (
        f"{python_executable} {script} test -c {target_value} -ns",
        f"{python_executable} {script} export {target_value}",
        f"{python_executable} {script} screenshots --diff {target_value}",
    )


def country_variant_lightfx_expectations(car: str = "G50") -> dict[str, Any]:
    car_key = str(car or "").strip().upper() or "<car>"
    expectations: dict[str, dict[str, Any]] = {
        "G50": {
            "car": "G50",
            "feature": "Selective Yellow / LightFX country variants",
            "expected_selective_yellow_country_variants": ("ECE", "US"),
            "known_bad_signal": "CN-only selective yellow is not sufficient for the current delivery expectation.",
            "evidence": (
                "country-variant source/config evidence",
                "RaCo/Blender screenshot or visual note per relevant variant",
                "expected versus actual country variants",
                "Jira/Teams reference when reported by a teammate",
            ),
        }
    }
    return deepcopy(
        expectations.get(
            car_key,
            {
                "car": car_key,
                "feature": "Country-variant LightFX",
                "expected_selective_yellow_country_variants": (),
                "known_bad_signal": "",
                "evidence": (
                    "country-variant source/config evidence",
                    "RaCo/Blender screenshot or visual note per relevant variant",
                    "expected versus actual country variants",
                ),
            },
        )
    )


def jira_field_link_templates() -> dict[str, dict[str, Any]]:
    return deepcopy(
        {
            "sgfx_defect": {
                "issue_types": ("Bug", "TAEE Defect"),
                "team": "APINEXT: Seriesgraphics",
                "component": "UI Toolkit: Seriesgraphics",
                "domain": "UI Toolkit",
                "variant3": "TK_Seriesgraphics",
                "labels": ("Seriesgraphics", "3DCar"),
                "link_types": ("relates to", "blocked by"),
                "required_evidence": (
                    "affected car/profile and trimline",
                    "visual/screenshot/log evidence",
                    "asset service or delivery source version when known",
                    "expected versus actual result",
                    "retest note when the asset hash changes",
                ),
            },
            "asset_update_ready": {
                "issue_types": ("Task", "Story"),
                "team": "APINEXT: Wombat",
                "component": "3D Car",
                "domain": "UI Toolkit",
                "variant3": "TK_3D_Car",
                "labels": ("3DCarAssetIntegration",),
                "link_types": ("blocked by", "relates to"),
                "required_evidence": (
                    "BMW repo branch or delivery line",
                    "asset hash / retest trigger",
                    "delivery package or PR link",
                    "screenshot or smoke-test summary when available",
                ),
            },
        }
    )


def workflow_contracts() -> tuple[dict[str, Any], ...]:
    return deepcopy(
        (
            {
                "key": "manual_visual_review",
                "label": "Manual visual review companion",
                "source": "PDX Confluence: Quality-Hero / 3D Car Asset Test overview",
                "steps": (
                    "Open the relevant car in Blender/RaCo with current SG Toolkit or matching RaCo setup.",
                    "Rotate and inspect exterior/interior for missing meshes, broken meshes, material or texture artefacts.",
                    "Check logos, lights, glass/plastic light covers, side mirrors, rims, flaps, doors, hood, and tailgate.",
                    "Check trimlines, color/material changes, country variants, IconicGlow, WelcomeFX, and Selective Yellow where relevant.",
                    "Record method, coverage, findings, screenshots, and remaining open items; do not mark approval done from headless checks alone.",
                ),
                "evidence": (
                    "method: Blender, RaCo, rack, emulator, or not yet",
                    "car/profile and relevant trimline/country variant",
                    "coverage note for logos/lights/mirrors/rims/flaps/doors/hood/tailgate",
                    "screenshot/contact sheet or manual visual note",
                    "findings and owner/open item if anything is off",
                ),
            },
            {
                "key": "bmw_interface_screenshot_smoke",
                "label": "BMW interface / screenshot smoke adapter",
                "source": "BMW Confluence: SG Delivery Documentation / interface test flow",
                "steps": (
                    "Run interface smoke without screenshots when only interface/runtime sanity is needed.",
                    "Run BMW export for the mapped delivery target.",
                    "Run BMW screenshot diff when expected/actual/diff payloads are available.",
                    "Treat empty actual/diff folders as missing evidence, not a pass.",
                ),
                "commands": bmw_interface_smoke_commands(),
                "evidence": (
                    "interface smoke exit code and log",
                    "export exit code and file-size output",
                    "screenshot diff exit code and expected/actual/diff counts",
                ),
            },
            {
                "key": "defect_triage",
                "label": "Defect triage workflow",
                "source": "BMW delivery/process notes",
                "steps": (
                    "Identify affected car/profile, trimline, function, and delivery line.",
                    "Capture expected versus actual result with screenshot/log/source evidence.",
                    "Separate SG local findings from BMW integration or asset-service findings.",
                    "Link blockers and retest notes instead of closing by assumption.",
                ),
                "evidence": (
                    "affected car/profile",
                    "function or asset family",
                    "screenshot/log/source path",
                    "owner/team and blocker link",
                    "retest trigger or asset hash when available",
                ),
            },
            {
                "key": "carpaint_lackcode_dlt",
                "label": "Carpaint Lackcode / DLT workflow",
                "source": "BMW Confluence: Check car color / Car Paints",
                "steps": (
                    "Read Lackcode from CheckIn file when present.",
                    "If CheckIn is missing, search DLT logs for the coding/color value.",
                    "Normalize by stripping the leading zero before Car Paints lookup.",
                    "Compare reference pictures cautiously because exposure can make colors look darker.",
                ),
                "evidence": (
                    "CheckIn file path and Lackcode",
                    "DLT log excerpt when CheckIn is not available",
                    "normalized Lackcode used for lookup",
                    "Car Paints reference page/status",
                    "visual comparison note or screenshot",
                ),
            },
            {
                "key": "country_variant_lightfx",
                "label": "Country-variant LightFX check",
                "source": "PDX/BMW QA notes and current G50 selective-yellow finding",
                "steps": (
                    "Identify affected car, LightFX function, and country/region variants.",
                    "Compare expected country variants against source/config/readme evidence.",
                    "For G50 selective yellow, treat CN-only evidence as a finding because ECE and US are expected.",
                    "Capture visual/source proof and route it as a delivery issue rather than hiding it under tool work.",
                ),
                "evidence": (
                    "car/profile and LightFX function",
                    "expected country variants",
                    "actual country variants found",
                    "visual/source screenshot or config path",
                    "defect/Jira/Teams reference when available",
                ),
                "expectations": {"G50": country_variant_lightfx_expectations("G50")},
            },
            {
                "key": "performance_kpi",
                "label": "Performance / KPI lane",
                "source": "BMW Confluence: performance, Macrobenchmark, Perfetto, KPI notes",
                "steps": (
                    "Keep performance evidence separate from visual QA approval.",
                    "Use BMW/Android performance surfaces when the target app/device is available.",
                    "Capture CPU load, trace, macrobenchmark, or KPI result links as external evidence.",
                    "Do not claim performance pass/fail from SG local preflight alone.",
                ),
                "evidence": (
                    "performance test result or KPI link",
                    "Perfetto or macrobenchmark artifact",
                    "CPU/load note",
                    "target device/app/build context",
                ),
            },
            {
                "key": "jira_field_link_templates",
                "label": "Jira field and link templates",
                "source": "BMW Confluence: delivery/ticket routing notes",
                "steps": (
                    "Use Seriesgraphics fields for SG-owned defects.",
                    "Use Wombat / 3DCarAssetIntegration fields for asset integration handoff.",
                    "Add blocked-by and retest/asset-hash links explicitly.",
                    "Keep copy-ready text local until Jira write access is confirmed.",
                ),
                "evidence": (
                    "issue type",
                    "team/component/domain/Variant3",
                    "labels",
                    "blocked-by or relates-to links",
                    "retest note and asset hash when available",
                ),
            },
        )
    )

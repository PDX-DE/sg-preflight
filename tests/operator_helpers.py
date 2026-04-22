from __future__ import annotations

import json
import hashlib
import zipfile
from pathlib import Path

from sg_preflight.profiles import RunProfile


ROOT = Path(__file__).resolve().parents[1]


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_minimal_rca(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    json_name = path.name + ".json"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(json_name, json.dumps(payload, indent=2))


def create_temp_g65_profile(temp_root: Path) -> RunProfile:
    repo_root = temp_root / "repositories" / "trunk"
    project_root = repo_root / "Cars_IDCevo" / "BMW" / "G65"
    carpaint_path = repo_root / "Cars" / "BMW" / "CarPaint.json"
    delivery_checklist_root = repo_root / ".pdx" / "checkers" / "deliveryChecklist"

    (project_root / "logic").mkdir(parents=True)
    (project_root / "resources" / "RES_G65_AnchorPoints").mkdir(parents=True)

    anchor_names = []
    for part in ("Hood", "Roof", "Trunk"):
        for depth in ("B", "F"):
            for vertical in ("D", "U"):
                for lateral in ("L", "R"):
                    anchor_names.append(f"APN_BoundingBox_{part}_{depth}_{vertical}_{lateral}")

    instances = [
        {
            "typeName": "Node",
            "properties": {
                "objectID": "root-id",
                "objectName": "root",
                "children": ["anchors-id"],
                "translation": {
                    "x": {"value": 0.0},
                    "y": {"value": 0.0},
                    "z": {"value": 0.0},
                },
            },
        },
        {
            "typeName": "Node",
            "properties": {
                "objectID": "anchors-id",
                "objectName": "Anchorpoints_BoundingBox",
                "children": [],
                "translation": {
                    "x": {"value": 0.0},
                    "y": {"value": 0.0},
                    "z": {"value": 0.0},
                },
            },
        },
    ]
    for index, name in enumerate(anchor_names, start=1):
        child_id = f"anchor-{index}"
        instances[1]["properties"]["children"].append(child_id)
        instances.append(
            {
                "typeName": "Node",
                "properties": {
                    "objectID": child_id,
                    "objectName": name,
                    "translation": {
                        "x": {"value": float(index)},
                        "y": {"value": float(index)},
                        "z": {"value": float(index)},
                    },
                },
            }
        )

    write_minimal_rca(
        project_root / "resources" / "RES_G65_AnchorPoints" / "RES_G65_AnchorPoints.rca",
        {"instances": instances},
    )
    write_json(
        project_root / "_WorkFiles" / "json" / "G65_Pivot_Master.json",
        {
            "TRANSFORMS": {"Static": {"pos": [0, 0, 0], "rot": [0, 0, 0]}},
            "SUSPENSION": {
                "Wheelbase": 3.03,
                "Origin_Offset": [-0.0749, 0.0, -0.0537],
                "Tire_Diameter": {
                    "TRIM_Basis": 79.4,
                    "TRIM_MSP": 79.4,
                    "TRIM_MPP": 79.4,
                    "TRIM_MPA": 77.9,
                },
                "Rim_Diameter": {
                    "TRIM_Basis": 21.5,
                    "TRIM_MSP": 21.5,
                    "TRIM_MPP": 21.5,
                    "TRIM_MPA": 22.5,
                },
                "Tire_Width": {
                    "TRIM_Basis": [29.5, 29.5],
                    "TRIM_MSP": [29.5, 29.5],
                    "TRIM_MPP": [29.5, 29.5],
                    "TRIM_MPA": [30.5, 30.5],
                },
                "Wheel_Outer_Distance": {
                    "TRIM_Basis": [69.3, 69.3],
                    "TRIM_MSP": [69.3, 69.3],
                    "TRIM_MPP": [69.5, 69.5],
                    "TRIM_MPA": [69.5, 69.5],
                },
            },
            "REFLECTION": {
                "Car_Height": 1.76,
                "Car_Length": 5.0,
                "Hood_Height": 1.2,
                "Hood_Length": 1.45,
                "Trunk_Height": 1.5,
                "Trunk_Length": 0.56,
                "X_Offset": -0.964,
            },
        },
    )
    write_text(
        project_root / "_Common" / "constants" / "scripts" / "Module_constants_G65.lua",
        """
local constants = {}
constants.WHEELBASE = 3.03
constants.SUSPENSION_OFFSET = {-0.0749, -0.0537, 0.0}
local wheels = {
    Tire_Diameter = 79.4,
    Tire_Diameter_Rim = 21.5,
    Tire_Width = 29.5
}
constants.WHEELS_SIZE_BASIS = wheels
wheels = {
    Tire_Diameter = 79.4,
    Tire_Diameter_Rim = 21.5,
    Tire_Width = 29.5
}
constants.WHEELS_SIZE_MSP = wheels
wheels = {
    Tire_Diameter = 79.4,
    Tire_Diameter_Rim = 21.5,
    Tire_Width = 29.5
}
constants.WHEELS_SIZE_MPP = wheels
wheels = {
    Tire_Diameter = 77.9,
    Tire_Diameter_Rim = 22.5,
    Tire_Width = 30.5
}
constants.WHEELS_SIZE_MPA = wheels
local wheelDistance = {
    Basis = {0.693, 0.693},
    MSP = {0.693, 0.693},
    MPP = {0.695, 0.695},
    MPA = {0.695, 0.695}
}
constants.WHEEL_DISTANCE = wheelDistance
constants.CAR_HEIGHT = 1.76
constants.CAR_LENGTH = 5.0
constants.HOOD_HEIGHT = 1.2
constants.HOOD_LENGTH = 1.45
constants.TRUNK_HEIGHT = 1.5
constants.TRUNK_LENGTH = 0.56
constants.X_OFFSET = 0.964
return constants
""".strip(),
    )
    write_json(
        carpaint_path,
        {
            "VELVET_BLUE": {
                "StyleID": 1,
                "Code": "WC9G",
                "BaseColor": [0.2, 0.3, 0.5],
                "HalftoneColor": [0.2, 0.3, 0.5],
                "HighlightTint": [1.0, 1.0, 1.0],
                "ShadowTint": [0.1, 0.1, 0.1],
                "ClearCoatIntensity": 1.0,
                "ClearCoatRoughness": 0.55,
                "UnderCoatIntensity": 0.4,
                "UnderCoatRoughness": 0.35,
                "OriginBrand": "BMW",
            }
        },
    )
    write_text(
        project_root / "main.rca",
        "logic=logic/car_logic.lua\nconstants=_Common/constants/scripts/Module_constants_G65.lua\n",
    )
    write_text(project_root / "logic" / "car_logic.lua", "-- referenced\n")
    write_text(delivery_checklist_root / "README.md", "delivery checklist fixture\n")
    write_text(delivery_checklist_root / "deliveryChecklist.py", "print('delivery checklist fixture')\n")
    write_text(delivery_checklist_root / "deliveryChecklist.exe", "fixture exe placeholder\n")
    write_text(delivery_checklist_root / "cameraCrane.lua", "-- fixture camera crane\n")

    return RunProfile(
        profile_id="G65",
        label="BMW G65 test slice",
        repo_root=repo_root,
        project_root=project_root,
        project_relative=Path("Cars_IDCevo/BMW/G65"),
        config_path=ROOT / "config" / "sg_rules_live_g65.json",
        default_context={
            "car_model": "G65",
            "trim_line": "Basis",
            "delivery_phase": "svn_live_preflight",
            "review_target": "g65_end_to_end",
            "evidence_source": "integration-test live sg",
        },
        description="Synthetic G65 fixture for operator tests.",
        operator_goal="Surface constants drift and low-noise project sanity evidence for the G65 slice.",
        workflow_value="Use this fixture when testing the operator flow around constants mismatches and evidence drilldown.",
        friendly_task="Check engineering constants",
        friendly_summary="Use this fixture when you want the simplest constants-focused operator flow.",
        focus_points=(
            "Constants drift between Pivot_Master and Module_constants",
            "Project-sanity evidence drilldown",
            "Operator-run persistence and evidence links",
        ),
        mirror_audit_targets=("Cars_IDCevo/BMW/G65", "Cars/BMW/CarPaint.json"),
        reference_repo_root=repo_root,
    )


def create_review_package_fixture(temp_root: Path, ticket_id: str = "IDCEVODEV-960073") -> dict[str, Path]:
    out_root = temp_root / "out"
    package_root = out_root / f"{ticket_id}-review-package-2026-04-22"
    snapshot_root = out_root / "daily-3d-car-qa-summary-2026-04-22-163526"
    package_snapshot_root = package_root / "artifacts" / "daily-snapshot"

    daily_payload = {
        "created_at": "2026-04-22T16:50:52",
        "scope_profiles": ["NA8", "G78", "G50"],
        "smoke_results": [
            {"profile_id": "NA8", "status": "completed"},
            {"profile_id": "G78", "status": "completed"},
            {"profile_id": "G50", "status": "completed"},
        ],
        "battery_results": [
            {"profile_id": "NA8", "filter_name": "default", "verdict": "baseline_candidate_ready"},
            {"profile_id": "NA8", "filter_name": "lights_LowBeam", "verdict": "proxy_candidate_ready"},
            {"profile_id": "NA8", "filter_name": "lights_OnlyCones", "verdict": "runtime_crash"},
        ],
        "top_review_items": [
            "NA8: `default` generated a candidate output; baseline approval can be done quickly.",
            "NA8: `lights_LowBeam` has a proxy lamp-state screenshot ready; exact cone effect is still blocked locally.",
        ],
        "blocked_steps": [
            "Jira writeback remains external to this local snapshot.",
            "NA8: `lights_OnlyCones` crashes the local BMW viewer; this is a runtime/content issue.",
        ],
    }

    review_priority_payload = {
        "created_at": "2026-04-22T16:50:52",
        "scope_profiles": ["NA8", "G78", "G50"],
        "ranked_items": [
            {
                "profile_id": "NA8",
                "filter_name": "default",
                "verdict": "baseline_candidate_ready",
                "priority_score": 80,
                "reason": "Exact candidate output exists; baseline approval can be done quickly.",
                "recommendation": "Candidate output exists; quick baseline-approval pass is possible.",
                "log_path": str((snapshot_root / "na8-bmw-battery.log").resolve()),
            },
            {
                "profile_id": "NA8",
                "filter_name": "lights_OnlyCones",
                "verdict": "runtime_crash",
                "priority_score": 10,
                "reason": "Viewer crashes locally.",
                "recommendation": "Treat as technical blocker, not human review.",
                "log_path": str((snapshot_root / "na8-bmw-battery.log").resolve()),
            },
        ],
    }

    delta_payload = {
        "current_created_at": "2026-04-22T16:50:52",
        "previous_created_at": "2026-04-22T10:50:33",
        "new_failures": [],
        "resolved_failures": [],
        "new_screenshot_diffs": [],
        "unchanged_blockers": [
            "Jira writeback remains external to this local snapshot.",
        ],
        "changed_counts": {
            "current": {
                "baseline_candidate_ready": 1,
                "proxy_candidate_ready": 1,
                "runtime_crash": 1,
                "smoke_completed": 3,
            },
            "previous": {
                "baseline_candidate_ready": 1,
                "proxy_candidate_ready": 1,
                "runtime_crash": 1,
                "smoke_completed": 3,
            },
        },
        "top_five_to_review": [
            "NA8: `default` generated a candidate output; baseline approval can be done quickly.",
        ],
    }

    review_bundle = {
        "ticket_id": ticket_id,
        "title": ticket_id,
        "generated_at_utc": "2026-04-22T14:35:37.106276+00:00",
        "overall_status": "partial",
        "profile_ids": ["NA8", "G78", "G50"],
        "scope_note": "Confirmed delivery scope from Jana is NA8, G78, and G50.",
        "blockers": [
            "screenshot tests bmws: Representative local smoke evidence is attached for the confirmed cars.",
            "Support: Need Jana to confirm reporting cadence.",
        ],
        "next_questions": [
            "Should lights_OnlyCones be treated as a blocker or a follow-up?",
        ],
    }

    write_json(package_root / f"{ticket_id}-review-bundle.json", review_bundle)
    write_text(
        package_root / "SENT_PACKAGE_MANIFEST.md",
        "\n".join(
            [
                "# SENT PACKAGE MANIFEST",
                "",
                f"- Ticket ID: `{ticket_id}`",
                "- Visible DoD progress (conservative): `70%`",
            ]
        )
        + "\n",
    )
    write_text(
        package_root / "review-owner-decisions.md",
        "\n".join(
            [
                "# Review-owner decisions",
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
            ]
        )
        + "\n",
    )
    write_text(package_root / f"{ticket_id}-dod-matrix.md", "# DoD Matrix\n")
    write_text(package_root / f"{ticket_id}-review-status.md", "# Review Status\n")
    write_text(package_root / f"{ticket_id}-teams-update.md", "# Teams Update\n")
    write_text(package_snapshot_root / "daily-3d-car-qa-summary.md", "# Daily Summary\n")
    write_json(package_snapshot_root / "daily-3d-car-qa-summary.json", daily_payload)
    write_text(
        package_snapshot_root / "candidate-review-gallery.html",
        "<html><body><img src=\"images/na8/default/default.png\" /></body></html>",
    )
    write_text(package_snapshot_root / "logs" / "na8-bmw-smoke.log", "Export finished\nFile sizes: Ramses=123456b RLogic=0b\n")
    write_text(package_snapshot_root / "logs" / "na8-bmw-battery.log", "battery fixture\n")
    write_text(package_snapshot_root / "images" / "na8" / "default" / "default.png", "png fixture\n")

    write_text(snapshot_root / "daily-3d-car-qa-summary.md", "# Daily Summary\n")
    write_json(snapshot_root / "daily-3d-car-qa-summary.json", daily_payload)
    write_text(snapshot_root / "review-priority-ranking.md", "# Review Priority Ranking\n")
    write_json(snapshot_root / "review-priority-ranking.json", review_priority_payload)
    write_text(snapshot_root / "daily-qa-delta-summary.md", "# Daily Delta Summary\n")
    write_json(snapshot_root / "daily-qa-delta-summary.json", delta_payload)
    write_text(snapshot_root / "na8-bmw-battery.log", "battery fixture\n")

    zip_path = package_root.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("placeholder.txt", "fixture\n")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    write_text(zip_path.with_suffix(zip_path.suffix + ".sha256"), f"{digest} *{zip_path.name}\n")

    return {
        "package_root": package_root,
        "zip_path": zip_path,
        "snapshot_root": snapshot_root,
    }

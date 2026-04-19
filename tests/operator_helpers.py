from __future__ import annotations

import json
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

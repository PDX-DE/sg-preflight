from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest

from sg_preflight.bundle import Bundle
from sg_preflight.validators.anchors import validate_anchors


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_minimal_rca(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    json_name = path.name + ".json"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(json_name, json.dumps(payload, indent=2))


class TestLiveProfiles(unittest.TestCase):
    def test_validate_anchors_keeps_legacy_single_group_behavior(self) -> None:
        scene = {
            "name": "ExportScene",
            "children": [
                {
                    "name": "Anchorpoints_BoundingBox",
                    "children": [
                        {
                            "name": "APN_BoundingBox_Hood_F_U_L",
                            "metadata": {"bbox_position": ["F", "U", "L"]},
                            "children": [],
                        },
                        {
                            "name": "APN_BoundingBox_Hood_F_U_R",
                            "metadata": {"bbox_position": ["F", "U", "R"]},
                            "children": [],
                        },
                    ],
                }
            ],
        }
        bundle = Bundle(
            root=ROOT,
            scene_hierarchy=scene,
            constants_expected=None,
            constants_exported=None,
            carpaints=None,
            project_manifest=None,
            bundle_metadata=None,
        )

        result = validate_anchors(
            bundle,
            {
                "anchors": {
                    "root_name": "Anchorpoints_BoundingBox",
                    "prefix": "APN_BoundingBox_",
                    "allowed_parts": ["Hood"],
                    "expected_anchor_names": [
                        "APN_BoundingBox_Hood_F_U_L",
                        "APN_BoundingBox_Hood_F_U_R",
                    ],
                }
            },
        )

        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.warning_count, 0)

    def test_validate_anchors_supports_multiple_rule_groups(self) -> None:
        scene = {
            "name": "ExportScene",
            "children": [
                {
                    "name": "RES_G45_ScaleAnchors",
                    "children": [
                        {"name": "DEBUG_Link_Anchorpoints", "children": []},
                        {"name": "APN_Scale_Top", "children": []},
                        {"name": "APN_Scale_Bottom", "children": []},
                    ],
                },
                {
                    "name": "RES_G45_TirePressAnchors",
                    "children": [
                        {"name": "APN_TirePress_FL", "children": []},
                        {"name": "APN_TirePress_FR", "children": []},
                        {"name": "APN_TirePress_BL", "children": []},
                        {"name": "APN_TirePress_BR", "children": []},
                    ],
                },
                {
                    "name": "RES_G45_SensorAnchors",
                    "children": [
                        {"name": "APN_Sensor_front_camera", "children": []},
                        {"name": "APN_Sensor_front_radar", "children": []},
                        {"name": "APN_Sensor_rear_camera", "children": []},
                    ],
                },
            ],
        }
        bundle = Bundle(
            root=ROOT,
            scene_hierarchy=scene,
            constants_expected=None,
            constants_exported=None,
            carpaints=None,
            project_manifest=None,
            bundle_metadata=None,
        )

        result = validate_anchors(
            bundle,
            {
                "anchors": {
                    "rule_groups": [
                        {
                            "name": "scale",
                            "root_name": "RES_G45_ScaleAnchors",
                            "prefix": "APN_Scale_",
                            "node_name_prefix": "APN_",
                            "expected_anchor_names": ["APN_Scale_Top", "APN_Scale_Bottom"],
                        },
                        {
                            "name": "tire_pressure",
                            "root_name": "RES_G45_TirePressAnchors",
                            "prefix": "APN_TirePress_",
                            "node_name_prefix": "APN_",
                            "expected_anchor_names": [
                                "APN_TirePress_FL",
                                "APN_TirePress_FR",
                                "APN_TirePress_BL",
                                "APN_TirePress_BR",
                            ],
                        },
                        {
                            "name": "sensor",
                            "root_name": "RES_G45_SensorAnchors",
                            "prefix": "APN_Sensor_",
                            "node_name_prefix": "APN_",
                            "expected_anchor_names": [
                                "APN_Sensor_front_camera",
                                "APN_Sensor_front_radar",
                                "APN_Sensor_rear_camera",
                            ],
                        },
                    ]
                }
            },
        )

        self.assertEqual(result.error_count, 0)
        self.assertEqual(result.warning_count, 0)

    def test_materialize_bundle_autodiscovers_live_g65_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repositories" / "trunk"
            project_root = repo_root / "Cars_IDCevo" / "BMW" / "G65"
            carpaint_path = repo_root / "Cars" / "BMW" / "CarPaint.json"

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
                                "z": {"value": {"ignored": True}},
                            },
                        },
                    }
                )
                instances[-1]["properties"]["translation"]["z"] = {"value": float(index)}

            _write_minimal_rca(
                project_root / "resources" / "RES_G65_AnchorPoints" / "RES_G65_AnchorPoints.rca",
                {"instances": instances},
            )
            _write_json(
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
            _write_text(
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
            _write_json(
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
            _write_text(
                project_root / "main.rca",
                "logic=logic/car_logic.lua\n"
                "constants=_Common/constants/scripts/Module_constants_G65.lua\n",
            )
            _write_text(project_root / "logic" / "car_logic.lua", "-- referenced\n")

            bundle_root = temp_root / "bundle"
            materialize = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "materialize",
                    "--output-bundle",
                    str(bundle_root),
                    "--repo-root",
                    str(repo_root),
                    "--project-root",
                    str(project_root),
                    "--raco-version",
                    "2.3.1",
                    "--env",
                    f"SG-Repo={repo_root}",
                    "--env",
                    f"SG-CarModels-Repo={repo_root}",
                    "--context",
                    "car_model=G65",
                    "--context",
                    "trim_line=Basis",
                    "--context",
                    "delivery_phase=svn_live_preflight",
                    "--context",
                    "review_target=g65_end_to_end",
                    "--context",
                    "evidence_source=integration-test live sg",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(materialize.returncode, 0, msg=materialize.stdout + "\n" + materialize.stderr)

            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "run",
                    "--bundle",
                    str(bundle_root),
                    "--config",
                    str(ROOT / "config" / "sg_rules_live_g65.json"),
                    "--json-out",
                    str(temp_root / "report.json"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(run_result.returncode, 0, msg=run_result.stdout + "\n" + run_result.stderr)
            report = json.loads((temp_root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["errors"], 0)
            self.assertEqual(report["summary"]["warnings"], 2)
            codes = {
                finding["code"]
                for pack in report["packs"]
                for finding in pack["findings"]
            }
            self.assertEqual(codes, {"project_sanity.unused_lua"})


if __name__ == "__main__":
    unittest.main()

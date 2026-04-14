from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest
from xml.sax.saxutils import escape

from sg_preflight.bundle import Bundle
from sg_preflight.adapters.anchors import normalize_scene_hierarchy_source
from sg_preflight.adapters.project_sanity import _extract_absolute_paths, build_project_manifest
from sg_preflight.adapters.carpaints import normalize_carpaints_source
from sg_preflight.adapters.constants import normalize_constants_source
from sg_preflight.validators.project_sanity import validate_project_sanity


ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_minimal_xlsx(path: Path, sheets: list[tuple[str, list[dict[str, object]]]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    def cell_xml(reference: str, value: object) -> str:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return f'<c r="{reference}"><v>{value}</v></c>'
        return f'<c r="{reference}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>'

    def sheet_xml(rows: list[dict[str, object]]) -> str:
        xml_rows = []
        row_number = 14
        for row in rows:
            cells = "".join(cell_xml(f"{column}{row_number}", value) for column, value in row.items())
            xml_rows.append(f'<row r="{row_number}">{cells}</row>')
            row_number += 1
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f"<sheetData>{''.join(xml_rows)}</sheetData>"
            "</worksheet>"
        )

    workbook_sheets = []
    workbook_rels = []
    content_type_overrides = []
    for index, (name, _rows) in enumerate(sheets, start=1):
        workbook_sheets.append(
            f'<sheet name="{escape(name)}" sheetId="{index}" '
            f'r:id="rId{index}"/>'
        )
        workbook_rels.append(
            f'<Relationship Id="rId{index}" '
            f'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
            f'Target="worksheets/sheet{index}.xml"/>'
        )
        content_type_overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" '
            f'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{''.join(content_type_overrides)}"
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(workbook_sheets)}</sheets>"
        "</workbook>"
    )
    workbook_relationships = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(workbook_rels)}"
        "</Relationships>"
    )

    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_relationships)
        for index, (_name, rows) in enumerate(sheets, start=1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(rows))


def _write_minimal_rca(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    json_name = path.name + ".json"
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(json_name, json.dumps(payload, indent=2))


class TestAdapters(unittest.TestCase):
    def test_extract_absolute_paths_ignores_urls_and_keeps_real_paths(self) -> None:
        text = (
            "Read https://github.com/GENIVI/ramses-composer-docs and "
            "[manual](../best_practices/manual.md). "
            "Keep /../../G65/_Common/interfaces/Link_Common_Variants.lua as a repo-relative SG reference. "
            "Use C:\\repos\\Seriengrafik\\trunk\\.pdx\\raco\\TestCarPaint\\read_json_carpaints.py "
            "and /Lua_Interface/ADASAssistMode.lua."
        )

        paths = _extract_absolute_paths(text)

        self.assertEqual(
            paths,
            [
                "/Lua_Interface/ADASAssistMode.lua",
                "C:\\repos\\Seriengrafik\\trunk\\.pdx\\raco\\TestCarPaint\\read_json_carpaints.py",
            ],
        )

    def test_project_manifest_detects_rca_version_and_cross_car_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repositories" / "trunk"
            project_root = repo_root / "Cars_IDCevo" / "BMW" / "G70"
            sibling_root = repo_root / "Cars_IDCevo" / "BMW" / "G65"

            (project_root / "logic").mkdir(parents=True)
            sibling_root.mkdir(parents=True)

            _write_minimal_rca(
                project_root / "main.rca",
                {
                    "racoVersion": [2, 3, 1],
                    "instances": [
                        {
                            "properties": {
                                "objectID": "scene-id",
                                "objectName": "MainScene",
                                "uri": "/../../G65/_Common/interfaces/Link_Common_Variants.lua",
                            }
                        }
                    ],
                },
            )
            _write_text(
                project_root / "logic" / "main.lua",
                'scene = "/../../G65/_Common/interfaces/Link_Common_Variants.lua"\n',
            )

            manifest = build_project_manifest(repo_root=repo_root, project_root=project_root)

            self.assertEqual(manifest["raco_version"], "2.3.1")
            references = [
                entry
                for entry in manifest["path_references"]
                if isinstance(entry, dict)
                and entry.get("value") == "/../../G65/_Common/interfaces/Link_Common_Variants.lua"
            ]
            self.assertTrue(references)
            lua_reference = next(
                entry
                for entry in references
                if entry.get("source_path") == str((project_root / "logic" / "main.lua").resolve())
            )
            self.assertEqual(
                lua_reference["source_path"],
                str((project_root / "logic" / "main.lua").resolve()),
            )
            self.assertEqual(lua_reference["line_number"], 1)
            self.assertIn("Link_Common_Variants.lua", lua_reference["line_text"])
            bundle = Bundle(
                root=project_root,
                scene_hierarchy=None,
                constants_expected=None,
                constants_exported=None,
                carpaints=None,
                project_manifest=manifest,
                bundle_metadata=None,
            )

            result = validate_project_sanity(bundle, {"project_sanity": {}})
            codes = {finding.code for finding in result.findings}
            self.assertIn("project_sanity.cross_car_reference", codes)
            self.assertNotIn("project_sanity.suspicious_absolute_path", codes)
            finding = next(
                item for item in result.findings if item.code == "project_sanity.cross_car_reference"
            )
            self.assertEqual(
                finding.details["source_path"],
                str((project_root / "logic" / "main.lua").resolve()),
            )
            self.assertEqual(finding.details["line_number"], 1)
            self.assertIn("Link_Common_Variants.lua", finding.details["line_text"])

    def test_project_sanity_unused_lua_includes_file_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo_root = Path(temp_dir) / "repositories" / "trunk"
            project_root = repo_root / "Cars_IDCevo" / "BMW" / "G70"

            (project_root / "logic").mkdir(parents=True)

            _write_text(
                project_root / "main.rca",
                "logic = logic/main.lua\n",
            )
            _write_text(project_root / "logic" / "main.lua", "-- referenced by main.rca\n")
            _write_text(project_root / "logic" / "unused_debug.lua", "-- intentionally unused\n")

            manifest = build_project_manifest(repo_root=repo_root, project_root=project_root)
            bundle = Bundle(
                root=project_root,
                scene_hierarchy=None,
                constants_expected=None,
                constants_exported=None,
                carpaints=None,
                project_manifest=manifest,
                bundle_metadata=None,
            )

            result = validate_project_sanity(bundle, {"project_sanity": {}})

            finding = next(item for item in result.findings if item.code == "project_sanity.unused_lua")
            self.assertEqual(finding.location, "logic/unused_debug.lua")
            self.assertEqual(
                finding.details["source_path"],
                str((project_root / "logic" / "unused_debug.lua").resolve()),
            )
            self.assertEqual(finding.details["referenced_by"], [])

    def test_normalize_carpaints_source_from_legacy_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "carpaints.json"
            _write_json(
                source,
                {
                    "blazing_blue": {
                        "Code": "WC6K",
                        "StyleID": 2,
                        "ClearCoatIntensity": 1.0,
                        "ClearCoatRoughness": 0.67,
                        "UnderCoatIntensity": 0.25,
                        "UnderCoatRoughness": 0.67,
                        "BaseColor": [15.0, 55.0, 120.0],
                        "HalftoneColor": [40.0, 80.0, 120.0],
                        "ShadowTint": [40.0, 15.0, 45.0],
                        "HighlightTint": [75.0, 165.0, 255.0],
                        "OriginBrand": "BMW",
                    }
                },
            )

            payload, note = normalize_carpaints_source(source)

            self.assertIn("Legacy SG-style carpaint JSON was normalized", note or "")
            self.assertEqual(len(payload["carpaints"]), 1)
            entry = payload["carpaints"][0]
            self.assertEqual(entry["id"], "WC6K")
            self.assertEqual(entry["name"], "blazing_blue")
            self.assertEqual(entry["finish"], "frozen")
            self.assertEqual(entry["clearcoat"], 1.0)
            self.assertEqual(entry["roughness"], 0.67)
            self.assertEqual(entry["metallic"], 0.25)
            self.assertEqual(entry["origin_brand"], "BMW")
            self.assertEqual(entry["base_color"], [0.058824, 0.215686, 0.470588])

    def test_normalize_carpaints_source_from_xlsx_workbook(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "Carpaints.xlsx"
            _write_minimal_xlsx(
                workbook,
                [
                    (
                        "BMW",
                        [
                            {
                                "A": "WC4F",
                                "B": "arctic_race_blue_metallic",
                                "G": "BMW",
                                "K": 20,
                                "L": 25,
                                "M": 40,
                                "N": 35,
                                "O": 25,
                                "P": 35,
                                "Q": 28,
                                "R": 32,
                                "S": 25,
                                "T": 45,
                                "U": 55,
                                "V": 80,
                                "W": 1,
                            }
                        ],
                    )
                ],
            )

            payload, note = normalize_carpaints_source(workbook)

            self.assertIn("built-in XLSX adapter", note or "")
            self.assertEqual(len(payload["carpaints"]), 1)
            entry = payload["carpaints"][0]
            self.assertEqual(entry["id"], "WC4F")
            self.assertEqual(entry["brand"], "BMW")
            self.assertEqual(entry["finish"], "metallic")
            self.assertEqual(entry["sheet"], "BMW")
            self.assertEqual(entry["base_color"], [0.078431, 0.098039, 0.156863])

    def test_normalize_carpaints_source_from_compact_xlsx_layout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workbook = Path(temp_dir) / "Carpaints_edited.xlsx"
            _write_minimal_xlsx(
                workbook,
                [
                    (
                        "BMW",
                        [
                            {
                                "A": "0R29",
                                "B": "arctic_white",
                                "C": 1.0,
                                "D": 0.0,
                                "E": 1.0,
                                "F": 1.0,
                                "G": 0.0,
                                "H": 1.0,
                                "I": 1.0,
                                "J": 1.0,
                                "K": 1.0,
                                "L": 0.0,
                                "M": 0.0,
                                "N": 0.0,
                                "O": 0,
                            }
                        ],
                    )
                ],
            )

            payload, _note = normalize_carpaints_source(workbook)

            self.assertEqual(len(payload["carpaints"]), 1)
            entry = payload["carpaints"][0]
            self.assertEqual(entry["id"], "0R29")
            self.assertEqual(entry["name"], "arctic_white")
            self.assertEqual(entry["finish"], "solid")
            self.assertEqual(entry["base_color"], [1.0, 0.0, 1.0])

    def test_normalize_scene_hierarchy_source_from_rca(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            rca_path = Path(temp_dir) / "RES_G70_AnchorPoints.rca"
            _write_minimal_rca(
                rca_path,
                {
                    "instances": [
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
                                "children": ["hood-id"],
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
                                "objectID": "hood-id",
                                "objectName": "APN_BoundingBox_Hood_F_U_L",
                                "translation": {
                                    "x": {"value": -1.0},
                                    "y": {"value": 1.0},
                                    "z": {"value": 1.0},
                                },
                            },
                        },
                    ]
                },
            )

            payload = normalize_scene_hierarchy_source(rca_path)

            self.assertEqual(payload["name"], "root")
            anchors_root = payload["children"][0]
            self.assertEqual(anchors_root["name"], "Anchorpoints_BoundingBox")
            self.assertEqual(anchors_root["children"][0]["name"], "APN_BoundingBox_Hood_F_U_L")
            self.assertEqual(
                anchors_root["children"][0]["metadata"]["translation"],
                [-1.0, 1.0, 1.0],
            )

    def test_normalize_constants_source_from_pivot_master_and_module_constants(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            project_root = (
                Path(temp_dir) / "trunk" / "Cars_IDCevo" / "BMW" / "G70"
            )
            pivot_path = project_root / "_Workfiles" / "json" / "G70_Pivot_Master.json"
            module_path = project_root / "_Common" / "constants" / "scripts" / "Module_constants_G70.lua"

            _write_json(
                pivot_path,
                {
                    "TRANSFORMS": {"Static": {"pos": [0, 0, 0], "rot": [0, 0, 0]}},
                    "SUSPENSION": {
                        "Wheelbase": 3.21,
                        "Origin_Offset": [-0.06, 0.0, -0.019],
                        "Tire_Diameter": {"TRIM_Basis": 74.5, "TRIM_MPP": 73.5},
                        "Rim_Diameter": {"TRIM_Basis": 21, "TRIM_MPP": 22},
                        "Tire_Width": {"TRIM_Basis": [26.5, 26.5], "TRIM_MPP": [26.5, 26.5]},
                        "Wheel_Outer_Distance": {
                            "TRIM_Basis": [68.9, 68.9],
                            "TRIM_MPP": [69.5, 69.5],
                        },
                    },
                    "REFLECTION": {
                        "Car_Height": 1.59,
                        "Car_Length": 5.42,
                        "Hood_Height": 1.07,
                        "Hood_Length": 1.58,
                        "Trunk_Height": 1.38,
                        "Trunk_Length": 1.26,
                        "X_Offset": -1.0,
                    },
                },
            )
            _write_text(
                module_path,
                """
local constants = {}
constants.WHEELBASE = 3.21
constants.SUSPENSION_OFFSET = {-0.06, -0.019, 0.0}
local wheels = {
    Tire_Diameter = 74.5,
    Tire_Diameter_Rim = 21.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_BASIS = wheels
wheels = {
    Tire_Diameter = 73.5,
    Tire_Diameter_Rim = 22.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_MPP = wheels
local wheelDistance = {
    Basis = {0.689, 0.689},
    MPP = {0.695, 0.695}
}
constants.WHEEL_DISTANCE = wheelDistance
constants.CAR_HEIGHT = 1.59
constants.CAR_LENGTH = 5.42
constants.HOOD_HEIGHT = 1.07
constants.HOOD_LENGTH = 1.58
constants.TRUNK_HEIGHT = 1.38
constants.TRUNK_LENGTH = 1.26
constants.X_OFFSET = 1.0
return constants
""".strip(),
            )

            expected = normalize_constants_source(pivot_path)
            exported = normalize_constants_source(module_path)

            self.assertEqual(expected["schema"], "sg_pivot_master")
            self.assertEqual(exported["schema"], "sg_module_constants")
            self.assertEqual(expected["car_model"], "G70")
            self.assertEqual(exported["brand"], "BMW")
            self.assertEqual(expected["wheelbase_m"], 3.21)
            self.assertEqual(expected["suspension_offset_m"]["y"], -0.019)
            self.assertEqual(expected["reflection"]["x_offset_m"], 1.0)
            self.assertEqual(exported["tire_diameter_cm"]["Basis"]["front"], 74.5)
            self.assertEqual(exported["wheel_distance_m"]["MPP"]["rear"], 0.695)

    def test_materialize_bundle_autodiscovers_live_sg_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "repositories" / "trunk"
            project_root = repo_root / "Cars_IDCevo" / "BMW" / "G70"
            carpaint_path = repo_root / "Cars" / "BMW" / "CarPaint.json"

            (project_root / "logic").mkdir(parents=True)
            (project_root / "resources" / "RES_G70_AnchorPoints").mkdir(parents=True)

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

            _write_minimal_rca(
                project_root / "resources" / "RES_G70_AnchorPoints" / "RES_G70_AnchorPoints.rca",
                {"instances": instances},
            )
            _write_json(
                project_root / "_Workfiles" / "json" / "G70_Pivot_Master.json",
                {
                    "TRANSFORMS": {"Static": {"pos": [0, 0, 0], "rot": [0, 0, 0]}},
                    "SUSPENSION": {
                        "Wheelbase": 3.21,
                        "Origin_Offset": [-0.06, 0.0, -0.019],
                        "Tire_Diameter": {
                            "TRIM_Basis": 74.5,
                            "TRIM_MSP": 74.5,
                            "TRIM_MPP": 73.5,
                            "TRIM_MPA": 73.5,
                        },
                        "Rim_Diameter": {
                            "TRIM_Basis": 21,
                            "TRIM_MSP": 21,
                            "TRIM_MPP": 22,
                            "TRIM_MPA": 22,
                        },
                        "Tire_Width": {
                            "TRIM_Basis": [26.5, 26.5],
                            "TRIM_MSP": [26.5, 26.5],
                            "TRIM_MPP": [26.5, 26.5],
                            "TRIM_MPA": [26.5, 26.5],
                        },
                        "Wheel_Outer_Distance": {
                            "TRIM_Basis": [68.9, 68.9],
                            "TRIM_MSP": [69.5, 69.5],
                            "TRIM_MPP": [69.5, 69.5],
                            "TRIM_MPA": [69.5, 69.5],
                        },
                    },
                    "REFLECTION": {
                        "Car_Height": 1.59,
                        "Car_Length": 5.42,
                        "Hood_Height": 1.07,
                        "Hood_Length": 1.58,
                        "Trunk_Height": 1.38,
                        "Trunk_Length": 1.26,
                        "X_Offset": -1.0,
                    },
                },
            )
            _write_text(
                project_root / "_Common" / "constants" / "scripts" / "Module_constants_G70.lua",
                """
local constants = {}
constants.WHEELBASE = 3.21
constants.SUSPENSION_OFFSET = {-0.06, -0.019, 0.0}
local wheels = {
    Tire_Diameter = 74.5,
    Tire_Diameter_Rim = 21.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_BASIS = wheels
wheels = {
    Tire_Diameter = 74.5,
    Tire_Diameter_Rim = 21.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_MSP = wheels
wheels = {
    Tire_Diameter = 73.5,
    Tire_Diameter_Rim = 22.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_MPP = wheels
wheels = {
    Tire_Diameter = 73.5,
    Tire_Diameter_Rim = 22.0,
    Tire_Width = 26.5
}
constants.WHEELS_SIZE_MPA = wheels
local wheelDistance = {
    Basis = {0.689, 0.689},
    MSP = {0.695, 0.695},
    MPP = {0.695, 0.695},
    MPA = {0.695, 0.695}
}
constants.WHEEL_DISTANCE = wheelDistance
constants.CAR_HEIGHT = 1.59
constants.CAR_LENGTH = 5.42
constants.HOOD_HEIGHT = 1.07
constants.HOOD_LENGTH = 1.58
constants.TRUNK_HEIGHT = 1.38
constants.TRUNK_LENGTH = 1.26
constants.X_OFFSET = 1.0
return constants
""".strip(),
            )
            _write_json(
                carpaint_path,
                {
                    "ADRIATIC_BLUE_2": {
                        "StyleID": 2,
                        "Code": "0KRP",
                        "BaseColor": [0.4, 0.4, 0.4],
                        "HalftoneColor": [0.4, 0.4, 0.4],
                        "HighlightTint": [1.0, 1.0, 1.0],
                        "ShadowTint": [0.6, 0.8, 1.0],
                        "ClearCoatIntensity": 1.0,
                        "ClearCoatRoughness": 0.67,
                        "UnderCoatIntensity": 0.25,
                        "UnderCoatRoughness": 0.67,
                        "OriginBrand": "BMW",
                    }
                },
            )
            _write_text(
                project_root / "main.rca",
                "logic=logic/car_logic.lua\n"
                "constants=_Common/constants/scripts/Module_constants_G70.lua\n",
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
                    "car_model=G70",
                    "--context",
                    "trim_line=Basis",
                    "--context",
                    "delivery_phase=svn_live_preflight",
                    "--context",
                    "review_target=g70_end_to_end",
                    "--context",
                    "evidence_source=integration-test live sg",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(materialize.returncode, 0, msg=materialize.stdout + "\n" + materialize.stderr)
            self.assertTrue((bundle_root / "scene_hierarchy.json").exists())
            self.assertTrue((bundle_root / "constants_expected.json").exists())
            self.assertTrue((bundle_root / "constants_exported.json").exists())
            self.assertTrue((bundle_root / "carpaints.json").exists())

            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "run",
                    "--bundle",
                    str(bundle_root),
                    "--config",
                    str(ROOT / "config" / "sg_rules_live.json"),
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

    def test_probe_discovers_sg_style_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "Seriengrafik" / "trunk"
            (repo_root / "Cars" / "BMW" / "_Shared").mkdir(parents=True)
            (repo_root / ".pdx" / "raco" / "TestCarPaint").mkdir(parents=True)
            _write_text(
                repo_root / ".pdx" / "raco" / "TestCarPaint" / "read_json_carpaints.py",
                "print('ok')\n",
            )

            out_json = temp_root / "probe.json"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "probe",
                    "--search-root",
                    str(temp_root),
                    "--json-out",
                    str(out_json),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            payload = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["repo_candidates"]), 1)
            candidate = payload["repo_candidates"][0]
            self.assertEqual(candidate["path"], str(repo_root.resolve()))
            self.assertTrue(candidate["known_assets"]["read_json_carpaints"])

    def test_materialize_bundle_from_sg_shaped_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            repo_root = temp_root / "Seriengrafik" / "trunk"
            project_root = repo_root / "Cars" / "BMW" / "G70"
            helper_path = repo_root / ".pdx" / "raco" / "TestCarPaint" / "read_json_carpaints.py"
            carmodels_root = temp_root / "digital-3d-car-models"

            (project_root / "logic").mkdir(parents=True)
            (project_root / "_Workfiles" / "json").mkdir(parents=True)
            (project_root / "exports").mkdir(parents=True)
            (repo_root / ".pdx" / "raco" / "TestCarPaint").mkdir(parents=True)
            carmodels_root.mkdir(parents=True)

            _write_text(
                helper_path,
                "from pathlib import Path\n"
                "import json\n"
                "import sys\n"
                "payload = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))\n"
                "print(json.dumps(payload))\n",
            )
            _write_json(repo_root / ".pdx" / "carmodel_data.json", {"models": ["G70"]})
            _write_text(repo_root / "raco_version.txt", "2.3.1\n")
            _write_text(
                project_root / "main.rca",
                "lua_script=logic/car_logic.lua\n"
                "shared=C:\\work\\shared\\materials.rca\n",
            )
            _write_text(project_root / "logic" / "car_logic.lua", "-- referenced by main.rca\n")
            _write_text(project_root / "logic" / "unused_debug.lua", "-- intentionally unreferenced\n")

            scene_dump = project_root / "exports" / "scene_dump.json"
            _write_json(
                scene_dump,
                {
                    "nodes": [
                        {"id": "root", "name": "ExportScene"},
                        {"id": "anchors", "name": "Anchorpoints_BoundingBox", "parent": "root"},
                        {
                            "id": "a1",
                            "name": "APN_BoundingBox_Hood_F_U_L",
                            "parent": "anchors",
                            "bbox_position": ["F", "U", "L"],
                        },
                        {
                            "id": "a2",
                            "name": "APN_BoundingBox_Hood_F_U_R",
                            "parent": "anchors",
                            "bbox_position": ["F", "U", "R"],
                        },
                        {
                            "id": "a3",
                            "name": "APN_BoundingBox_Trunk_B_U_L",
                            "parent": "anchors",
                            "bbox_position": ["B", "U", "L"],
                        },
                        {
                            "id": "a4",
                            "name": "APN_BoundingBox_Trunk_B_U_R",
                            "parent": "anchors",
                            "bbox_position": ["B", "U", "R"],
                        },
                    ]
                },
            )

            constants_expected = project_root / "_Workfiles" / "json" / "Pivot_Master_G70.json"
            _write_json(
                constants_expected,
                {
                    "Pivot_Master": [
                        {"path": "trim_line", "value": "Sport"},
                        {"path": "engine_type", "value": "BEV"},
                        {"path": "tire_diameter_mm.front", "value": 720.0},
                        {"path": "tire_diameter_mm.rear", "value": 720.0},
                        {"path": "suspension_mm.front", "value": 150.0},
                        {"path": "suspension_mm.rear", "value": 152.0},
                        {"path": "reflections.intensity", "value": 0.82},
                    ]
                },
            )

            constants_exported = project_root / "exports" / "constants_exported.json"
            _write_json(
                constants_exported,
                {
                    "constants": [
                        {"path": "trim_line", "value": "Sport"},
                        {"path": "engine_type", "value": "BEV"},
                        {"path": "tire_diameter_mm.front", "value": 720.0},
                        {"path": "tire_diameter_mm.rear", "value": 720.0},
                        {"path": "suspension_mm.front", "value": 150.0},
                        {"path": "suspension_mm.rear", "value": 152.0},
                        {"path": "reflections.intensity", "value": 0.82},
                    ]
                },
            )

            carpaints_source = project_root / "exports" / "carpaints_payload.json"
            _write_json(
                carpaints_source,
                {
                    "paints": [
                        {
                            "id": "cp_001",
                            "name": "Frozen Silver",
                            "finish": "matte",
                            "roughness": 0.75,
                            "metallic": 0.2,
                            "base_color": [0.74, 0.75, 0.77],
                            "clearcoat": 0.15,
                        }
                    ]
                },
            )

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
                    "--scene-source",
                    str(scene_dump),
                    "--constants-expected-source",
                    str(constants_expected),
                    "--constants-exported-source",
                    str(constants_exported),
                    "--carpaints-source",
                    str(carpaints_source),
                    "--carpaints-helper",
                    str(helper_path),
                    "--env",
                    f"SG_REPO={repo_root}",
                    "--env",
                    f"SP_REPO={repo_root}",
                    "--env",
                    f"SG_CARMODELS_REPO={carmodels_root}",
                    "--context",
                    "car_model=G70",
                    "--context",
                    "trim_line=Sport",
                    "--context",
                    "delivery_phase=preview",
                    "--context",
                    "review_target=internal_rack",
                    "--context",
                    "evidence_source=integration-test materialize",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(
                materialize.returncode,
                0,
                msg=materialize.stdout + "\n" + materialize.stderr,
            )
            self.assertTrue((bundle_root / "scene_hierarchy.json").exists())
            self.assertTrue((bundle_root / "project_manifest.json").exists())
            manifest = json.loads((bundle_root / "project_manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["report_context"]["car_model"], "G70")

            run_result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sg_preflight",
                    "run",
                    "--bundle",
                    str(bundle_root),
                    "--config",
                    str(ROOT / "config" / "sg_rules.json"),
                    "--json-out",
                    str(temp_root / "report.json"),
                    "--html-out",
                    str(temp_root / "report.html"),
                    "--md-out",
                    str(temp_root / "report.md"),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(run_result.returncode, 0, msg=run_result.stdout + "\n" + run_result.stderr)
            report = json.loads((temp_root / "report.json").read_text(encoding="utf-8"))
            self.assertEqual(report["summary"]["errors"], 0)
            self.assertGreaterEqual(report["summary"]["warnings"], 1)
            markdown = (temp_root / "report.md").read_text(encoding="utf-8")
            self.assertIn("Workflow Context", markdown)
            self.assertIn("Car Model: G70", markdown)


if __name__ == "__main__":
    unittest.main()

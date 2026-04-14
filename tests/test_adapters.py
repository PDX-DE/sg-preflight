from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
import unittest
from xml.sax.saxutils import escape

from sg_preflight.adapters.project_sanity import _extract_absolute_paths
from sg_preflight.adapters.carpaints import normalize_carpaints_source


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


class TestAdapters(unittest.TestCase):
    def test_extract_absolute_paths_ignores_urls_and_keeps_real_paths(self) -> None:
        text = (
            "Read https://github.com/GENIVI/ramses-composer-docs and "
            "[manual](../best_practices/manual.md). "
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

    def test_normalize_carpaints_source_from_legacy_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "carpaints.json"
            _write_json(
                source,
                {
                    "blazing_blue": {
                        "Code": "WC6K",
                        "StyleID": 0,
                        "BaseColor": [15.0, 55.0, 120.0],
                        "HalftoneColor": [40.0, 80.0, 120.0],
                        "ShadowTint": [40.0, 15.0, 45.0],
                        "HighlightTint": [75.0, 165.0, 255.0],
                    }
                },
            )

            payload, note = normalize_carpaints_source(source)

            self.assertIn("Legacy SG-style carpaint JSON was normalized", note or "")
            self.assertEqual(len(payload["carpaints"]), 1)
            entry = payload["carpaints"][0]
            self.assertEqual(entry["id"], "WC6K")
            self.assertEqual(entry["name"], "blazing_blue")
            self.assertEqual(entry["finish"], "solid")
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
                                "O": 1,
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

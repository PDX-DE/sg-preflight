from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from sg_preflight.api_version_coverage import (
    EVIDENCE_ONLY_BANNER,
    IMPACT_REVIEW_LABEL,
    build_api_version_coverage_board,
)
from sg_preflight.cli import main


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_changelog(path: Path) -> None:
    _write_text(path, "## [1.0.0] - NOT YET DELIVERED\n")


def _api_fixture(root: Path) -> tuple[Path, Path]:
    repo = root / "repositories" / "trunk"
    bmw_repo = root / "digital-3d-car-models"
    shared_body = "\n".join(
        (
            "# Shared API",
            "",
            "---",
            "## API VERSION: [30] - 09.03.2026",
            "",
            "* Renamed property `Hood_isOpen` in [Interface_Doors](./Interface_Doors.lua) to `Hood_1_isOpen`",
            "",
            "* Added new properties to Doors interface in [Interface_Doors](./Interface_Doors.lua):",
            "  * `Hood_1_PreciseAngle` - __Float__",
            "",
            "---",
            "## API VERSION: [29] - 29.10.2025",
            "",
            "* Added new properties to Highlighting interface in [Interface_Highlighting](./Interface_Highlighting.lua):",
            "  * `Radar_Side_M_F_L_StateID` - __Int32__",
            "",
        )
    )
    for brand, shared_name in (
        ("BMW", "_Shared_IDCevo"),
        ("Alpina", "_Shared_Alpina"),
        ("MGmbH", "_Shared_MGmbH"),
        ("RollsRoyce", "_Shared_RollsRoyce"),
    ):
        _write_text(repo / "Cars_IDCevo" / brand / shared_name / "MainInterfaces" / "CHANGELOG.md", shared_body)

    _write_changelog(repo / "Cars_IDCevo" / "BMW" / "G50" / "CHANGELOG.md")
    _write_text(
        repo / "Cars_IDCevo" / "BMW" / "G50" / "main" / "interfaces" / "Link_Doors.lua",
        "INOUT.Hood_isOpen = Type:Bool()\n",
    )
    _write_changelog(repo / "Cars_IDCevo" / "RollsRoyce" / "PINT_RR" / "CHANGELOG.md")
    _write_text(
        repo / "Cars_IDCevo" / "RollsRoyce" / "PINT_RR" / "main" / "interfaces" / "Link_Doors.lua",
        "INOUT.Hood_1_isOpen = Type:Bool()\n",
    )
    _write_changelog(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md")

    _write_text(bmw_repo / "cars" / "version_info.json", '{"supportedVersions": [24, 12]}')
    _write_text(
        bmw_repo / "ci" / "scripts" / "common" / "models_build_config.yaml",
        "\n".join(
            (
                "---",
                "- name: F70",
                "  brand: BMW",
                "  type: build",
                "  hmi:",
                "    source_folder: F70",
                "    interface_version: 12",
                "  additional_build:",
                "    interface_version: 24",
                "- name: G50_EVO",
                "  brand: BMW",
                "  type: build",
                "  hmi:",
                "    source_folder: G50",
                "    interface_version: 24",
                "- name: PINT_RR",
                "  brand: RR",
                "  type: build",
                "  hmi:",
                "    source_folder: PINT_RR",
                "    interface_version: 24",
                "",
            )
        ),
    )
    return repo, bmw_repo


class TestApiVersionCoverage(unittest.TestCase):
    def test_board_reports_shared_api_family_and_cautious_impact(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo, bmw_repo = _api_fixture(Path(temp_dir))

            board = build_api_version_coverage_board(repo, workspace_root=Path(temp_dir), bmw_repo_root=bmw_repo)

        payload = board.to_dict()
        self.assertEqual(payload["manual_review_banner"], EVIDENCE_ONLY_BANNER)
        self.assertEqual(payload["counts"]["shared_brand_ready"], 4)
        self.assertEqual(payload["shared_api_references"][0]["current_version"], "30")
        self.assertEqual(payload["counts"]["interface_family_counts"], {"12": 1, "24": 2})
        g50 = next(entry for entry in payload["interface_family_entries"] if entry["model_id"] == "G50")
        self.assertEqual(g50["hmi_interface_version"], 24)
        self.assertIn("HMI export family", g50["hmi_family_label"])
        self.assertNotIn("outdated", json.dumps(payload).lower())
        scans = payload["impact_scans"]
        self.assertTrue(scans)
        hood_scan = next(scan for scan in scans if scan["change"]["old_name"] == "Hood_isOpen")
        self.assertEqual(hood_scan["review_label"], IMPACT_REVIEW_LABEL)
        self.assertEqual(hood_scan["matched_car_count"], 1)
        self.assertEqual(hood_scan["matched_cars"][0]["model_id"], "G50")

    def test_cli_writes_json_and_markdown_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo, bmw_repo = _api_fixture(root)
            output_root = root / "out" / "api-version"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "api-version-coverage",
                        "--workspace",
                        str(root),
                        "--repo-root",
                        str(repo),
                        "--bmw-repo-root",
                        str(bmw_repo),
                        "--output-root",
                        str(output_root),
                        "--json",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["counts"]["impact_review_car_count"], 1)
            self.assertTrue((output_root / "api-version-coverage.json").exists())
            self.assertTrue((output_root / "api-version-coverage.md").exists())


if __name__ == "__main__":
    unittest.main()

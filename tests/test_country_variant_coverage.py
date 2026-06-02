from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from sg_preflight.cli import main
from sg_preflight.country_variant_coverage import (
    MAPPING_REVIEW_LABEL,
    MISSING_EXPECTED_LABEL,
    build_country_variant_coverage_board,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x89PNG\r\n\x1a\n")


def _write_changelog(path: Path) -> None:
    _write_text(path, "## [1.0.0] - NOT YET DELIVERED\n")


def _country_fixture(root: Path) -> tuple[Path, Path]:
    repo = root / "repositories" / "trunk"
    bmw_repo = root / "digital-3d-car-models"
    _write_text(
        repo / "Cars" / "BMW" / "README.md",
        "\n".join(
            (
                "## Country Variant IDs",
                "",
                "| ID | Country | U11 | PINT_SUV |",
                "|---:|---|---:|---:|",
                "|  3 | China | &check; | &check; |",
                "|  6 | Japan | &check; | &check; |",
                "| 10 | US | &check; | &check; |",
                "",
            )
        ),
    )
    _write_changelog(repo / "Cars" / "BMW" / "U11" / "CHANGELOG.md")
    _write_text(
        repo / "Cars" / "BMW" / "U11" / "export" / "tests" / "test_config.lua",
        "\n".join(
            (
                'addTest("countryCoding_China", function(time_ms) reset();',
                "  configuration(true, false, 0, 3);",
                "  waitOnRendering(1000) end)",
                'addTest("countryCoding_Japan", function(time_ms) reset(); cameraView(45, 0, 90); configuration(true, false, 0, 6); waitOnRendering(1000) end)',
                'addTest("countryCoding_US", function(time_ms) reset(); cameraView(7, 0, 90); configuration(false, false, 0, 10); waitOnRendering(1000) end)',
                "",
            )
        ),
    )
    _write_png(repo / "Cars" / "BMW" / "U11" / "export" / "tests" / "expected" / "countryCoding_China.png")
    _write_png(repo / "Cars" / "BMW" / "U11" / "export" / "tests" / "expected" / "countryCoding_US.png")

    _write_changelog(repo / "Cars" / "BMW" / "PINT_SUV" / "CHANGELOG.md")
    _write_text(
        repo / "Cars" / "BMW" / "PINT_SUV" / "export" / "tests" / "test_config.lua",
        'addTest("countryCoding_US", function(time_ms) reset(); configuration(false, false, 0, 9); waitOnRendering(1000) end)\n',
    )
    _write_png(repo / "Cars" / "BMW" / "PINT_SUV" / "export" / "tests" / "expected" / "countryCoding_US.png")

    _write_changelog(repo / "Cars_IDCevo" / "BMW" / "G50" / "CHANGELOG.md")
    _write_text(repo / "Cars_IDCevo" / "BMW" / "G50" / "export" / "scripts" / "Logic_Charging.lua", "x\n")

    _write_text(
        bmw_repo / "cars" / "BMW" / "G50_EVO" / "export" / "tests" / "test_config.lua",
        'addTest("countryCoding_US", function(time_ms) reset(); configuration(false, false, 0, 10); waitOnRendering(1000) end)\n',
    )
    _write_png(bmw_repo / "cars" / "BMW" / "G50_EVO" / "export" / "tests" / "expected" / "countryCoding_US.png")
    return repo, bmw_repo


class TestCountryVariantCoverage(unittest.TestCase):
    def test_board_parses_country_rows_and_cautious_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo, bmw_repo = _country_fixture(root)

            board = build_country_variant_coverage_board(repo, workspace_root=root, bmw_repo_root=bmw_repo)

        payload = board.to_dict()
        self.assertEqual(payload["source_state"], "ready")
        self.assertEqual(payload["counts"]["row_total"], 4)
        self.assertEqual(payload["counts"]["car_with_rows_count"], 2)
        self.assertEqual(payload["counts"]["expected_present_count"], 3)
        self.assertEqual(payload["counts"]["expected_missing_count"], 1)
        self.assertEqual(payload["counts"]["actual_present_count"], 0)
        self.assertEqual(payload["counts"]["diff_present_count"], 0)
        self.assertEqual(payload["counts"]["no_runtime_row_count"], 4)
        self.assertEqual(payload["counts"]["mapping_review_count"], 1)
        self.assertEqual(payload["counts"]["review_row_count"], 2)
        self.assertNotIn("failed", json.dumps(payload).lower())

        japan = next(entry for entry in payload["entries"] if entry["test_name"] == "countryCoding_Japan")
        self.assertEqual(japan["country_variant_id"], "6")
        self.assertIn(MISSING_EXPECTED_LABEL, japan["review_flags"])
        self.assertFalse(japan["has_runtime_evidence"])

        pint = next(entry for entry in payload["entries"] if entry["relative_path"] == "Cars/BMW/PINT_SUV")
        self.assertEqual(pint["country_variant_id"], "9")
        self.assertEqual(pint["reference_country_id"], "10")
        self.assertIn(MAPPING_REVIEW_LABEL, pint["review_flags"])

        expectations = payload["expectations"]
        self.assertEqual(expectations[0]["car"], "G50")
        self.assertEqual(expectations[0]["expected_variants"], ["ECE", "US"])
        self.assertEqual(expectations[0]["observed_rows"], ["countryCoding_US"])
        self.assertIn("G50_EVO", expectations[0]["source_path"])

    def test_cli_writes_country_variant_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo, bmw_repo = _country_fixture(root)
            output_root = root / "out" / "country-variant"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "country-variant-coverage",
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
            self.assertEqual(payload["counts"]["row_total"], 4)
            self.assertTrue((output_root / "country-variant-coverage.json").exists())
            self.assertTrue((output_root / "country-variant-coverage.md").exists())


if __name__ == "__main__":
    unittest.main()

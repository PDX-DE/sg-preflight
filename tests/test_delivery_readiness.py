from __future__ import annotations

import io
import json
import os
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from sg_preflight.cli import main
from sg_preflight.delivery_readiness import (
    STATUS_DELIVERED,
    STATUS_NOT_DELIVERED_YET,
    STATUS_UNKNOWN,
    build_delivery_readiness_board,
    classify_changelog_text,
)
from sg_preflight.ui import create_app


def _write_changelog(path: Path, header: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{header}\n\n- fixture entry\n", encoding="utf-8")


def _write_catalog(root: Path) -> Path:
    bmw_repo = root / "digital-3d-car-models"
    catalog = bmw_repo / "ci" / "scripts" / "common" / "models_build_config.yaml"
    catalog.parent.mkdir(parents=True, exist_ok=True)
    catalog.write_text(
        "\n".join(
            (
                "- name: F70",
                "  brand: BMW",
                "  type: build",
                "  hmi:",
                "    source_folder: F70",
                "- name: G65_EVO",
                "  brand: BMW",
                "  type: build",
                "  hmi:",
                "    source_folder: G65",
                "- name: G58_EVO",
                "  brand: BMW",
                "  type: retarget",
                "  target: PINT",
                "- name: ZA0_EVO",
                "  brand: BMW",
                "  type: retarget",
                "  target: PINT",
                "- name: ZA1_EVO",
                "  brand: BMW",
                "  type: retarget",
                "  target: PINT",
                "- name: MISSING_EVO",
                "  brand: BMW",
                "  type: retarget",
                "  target: PINT",
                "",
            )
        ),
        encoding="utf-8",
    )
    return bmw_repo


def _delivery_fixture(root: Path) -> Path:
    repo = root / "repositories" / "trunk"
    _write_changelog(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md", "## [3.4.0] - 2026-05-29")
    _write_changelog(repo / "Cars" / "BMW" / "F71" / "CHANGELOG.md", "## [3.4.1] 20260530")
    _write_changelog(repo / "Cars_IDCevo" / "BMW" / "G65" / "CHANGELOG.md", "## [2.0.6] - NOT YET DELIVERED")
    _write_changelog(repo / "Cars" / "MINI" / "F65" / "CHANGELOG.md", "## [1.0.0] - The be delviered")
    _write_changelog(repo / "Cars" / "BMW" / "G00" / "CHANGELOG.md", "## [0.1.0] - waiting for process call")
    _write_changelog(repo / "Cars" / "BMW" / "_Shared" / "MainInterfaces" / "CHANGELOG.md", "## API VERSION: [42] - fixture")
    _write_changelog(repo / "Cars" / "BMW" / "MainInterfaces" / "CHANGELOG.md", "## API VERSION: [42] - fixture")
    for name in ("export", "logic", "main", "resources"):
        (repo / "Cars_IDCevo" / "BMW" / "G58" / name).mkdir(parents=True, exist_ok=True)
    (repo / "Cars_IDCevo" / "MGmbH" / "ZA0" / "_WorkFiles").mkdir(parents=True, exist_ok=True)
    (repo / "Cars_IDCevo" / "MGmbH" / "ZA1").mkdir(parents=True, exist_ok=True)
    (repo / "Cars_IDCevo" / "BMW" / "NOISE").mkdir(parents=True, exist_ok=True)
    return repo


class TestDeliveryReadiness(unittest.TestCase):
    def test_classify_latest_changelog_header_handles_real_variants(self) -> None:
        cases = [
            ("## [3.4.0] - 2026-05-29\n", STATUS_DELIVERED, "2026-05-29"),
            ("## [3.4.0] 20260529\n", STATUS_DELIVERED, "20260529"),
            ("## [3.4.0] - To be delivered\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - TO BE DELIVERED\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - YET TO BE DELIVERED\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - NOT YET DELIVERED\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - NOT YET RELEASED\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - The be delviered\n", STATUS_NOT_DELIVERED_YET, ""),
            ("## [3.4.0] - waiting for process call\n", STATUS_UNKNOWN, ""),
        ]
        for text, expected_status, expected_date in cases:
            with self.subTest(text=text):
                classification = classify_changelog_text(text)
                self.assertEqual(classification.status, expected_status)
                self.assertEqual(classification.delivered_date, expected_date)

    def test_board_scans_car_changelogs_and_excludes_shared_components(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _delivery_fixture(root)
            bmw_repo = _write_catalog(root)
            board = build_delivery_readiness_board(repo, bmw_repo_root=bmw_repo)

        payload = board.to_dict()
        rows = {(item["source_root"], item["brand"], item["model_id"]): item for item in payload["entries"]}
        self.assertEqual(payload["source_state"], "ready")
        self.assertEqual(payload["counts"]["total"], 8)
        self.assertEqual(payload["counts"][STATUS_DELIVERED], 2)
        self.assertEqual(payload["counts"][STATUS_NOT_DELIVERED_YET], 2)
        self.assertEqual(payload["counts"][STATUS_UNKNOWN], 4)
        self.assertEqual(payload["skipped_count"], 2)
        self.assertIn(("Cars", "BMW", "F70"), rows)
        self.assertIn(("Cars_IDCevo", "BMW", "G65"), rows)
        self.assertIn(("Cars_IDCevo", "BMW", "G58"), rows)
        self.assertIn(("Cars_IDCevo", "MGmbH", "ZA0"), rows)
        self.assertIn(("Cars_IDCevo", "MGmbH", "ZA1"), rows)
        self.assertNotIn(("Cars_IDCevo", "BMW", "NOISE"), rows)
        self.assertNotIn(("Cars", "BMW", "_Shared"), rows)
        self.assertNotIn(("Cars", "BMW", "MainInterfaces"), rows)
        self.assertEqual(rows[("Cars", "MINI", "F65")]["status"], STATUS_NOT_DELIVERED_YET)
        self.assertFalse(rows[("Cars_IDCevo", "BMW", "G58")]["has_changelog"])
        self.assertEqual(rows[("Cars_IDCevo", "BMW", "G58")]["status_label"], "No changelog")
        self.assertEqual(rows[("Cars_IDCevo", "MGmbH", "ZA0")]["catalog_targets"], ["ZA0_EVO"])
        self.assertEqual(payload["catalog"]["catalog_target_count"], 6)
        self.assertEqual(payload["catalog"]["catalog_targets_mapped_count"], 5)
        self.assertEqual(payload["catalog"]["catalog_targets_missing_dir_count"], 1)
        self.assertEqual(payload["catalog"]["dirs_without_catalog_count"], 3)

    def test_cli_writes_json_and_markdown_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _delivery_fixture(root)
            bmw_repo = _write_catalog(root)
            output_root = root / "out" / "delivery-readiness"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main([
                    "delivery-readiness",
                    "--workspace",
                    str(root),
                    "--repo-root",
                    str(repo),
                    "--bmw-repo-root",
                    str(bmw_repo),
                    "--output-root",
                    str(output_root),
                    "--json",
                ])

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["counts"]["total"], 8)
            self.assertEqual(payload["catalog"]["catalog_targets_mapped_count"], 5)
            self.assertTrue((output_root / "delivery-readiness.json").exists())
            self.assertTrue((output_root / "delivery-readiness.md").exists())

    def test_ui_page_and_api_render_delivery_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _delivery_fixture(root)
            bmw_repo = _write_catalog(root)
            with mock.patch.dict(
                os.environ,
                {"SG_SOURCE_REPO_ROOT": str(repo), "Digital-3D-Car-Repo": str(bmw_repo)},
                clear=False,
            ):
                client = TestClient(create_app(root=root, profiles=[]))
                page = client.get("/ui/delivery-readiness")
                api = client.get("/ui/api/delivery-readiness")

        self.assertEqual(page.status_code, 200)
        self.assertIn("Delivery Readiness", page.text)
        self.assertIn("CHANGELOG status board", page.text)
        self.assertIn("Evidence only", page.text)
        self.assertIn("Cars/BMW/F70", page.text)
        self.assertIn("No CHANGELOG.md found", page.text)
        self.assertIn("BMW Catalog Reconciliation", page.text)
        self.assertEqual(api.status_code, 200)
        self.assertEqual(api.json()["counts"]["total"], 8)


if __name__ == "__main__":
    unittest.main()

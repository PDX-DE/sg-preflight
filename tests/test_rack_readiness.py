from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from sg_preflight.rack_readiness import (
    build_rack_readiness_board,
    rack_readiness_markdown,
    write_rack_readiness_board,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_car_changelog(
    path: Path,
    header: str,
    *,
    ramses: str = "28.16",
    raco_headless: str = "2.9.0",
) -> None:
    _write_text(
        path,
        "\n".join(
            (
                header,
                "",
                f"> _Ramses Composer / Headless: {raco_headless}_",
                f"> _Ramses: {ramses}_",
                "> _Ramses Logic: 1.18.0_",
                "> _Feature Level: 2026.2_",
                "> _API version: 14_",
                "",
            )
        ),
    )


def _rack_fixture(root: Path) -> Path:
    repo = root / "repositories" / "trunk"
    _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "G70" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")
    _write_text(repo / "Cars_IDCevo" / "BMW" / "G70" / "export" / "G70.rca", "asset\n")

    _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "G71" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")

    _write_car_changelog(
        repo / "Cars_IDCevo" / "BMW" / "G72" / "CHANGELOG.md",
        "## [3.4.0] - To be delivered",
    )
    _write_text(repo / "Cars_IDCevo" / "BMW" / "G72" / "export" / "G72.rca", "asset\n")

    _write_car_changelog(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")
    _write_text(repo / "Cars" / "BMW" / "F70" / "export" / "F70.rca", "asset\n")
    return repo


class TestRackReadiness(unittest.TestCase):
    def test_board_reports_idcevo_asset_readiness_without_claiming_flash_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _rack_fixture(root)
            board = build_rack_readiness_board(
                repo,
                workspace_root=root,
                bmw_repo_root=root / "missing-bmw-repo",
                now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        entries = {entry["model_id"]: entry for entry in payload["entries"]}

        self.assertEqual(payload["source_state"], "ready")
        self.assertEqual(payload["generated_at_utc"], "2026-06-19T11:00:00+00:00")
        self.assertTrue(payload["read_only"])
        self.assertTrue(payload["manual_review_required"])
        self.assertFalse(payload["is_approval"])
        self.assertIn("asset side", payload["manual_review_banner"])
        self.assertNotIn("flash success", payload["manual_review_banner"].casefold())

        self.assertEqual(set(entries), {"G70", "G71", "G72"})
        self.assertEqual(payload["counts"]["entry_total"], 3)
        self.assertEqual(payload["counts"]["asset_ready_count"], 1)
        self.assertEqual(payload["counts"]["asset_blocked_count"], 2)
        self.assertEqual(payload["counts"]["exported_count"], 2)
        self.assertEqual(payload["counts"]["delivered_count"], 2)
        self.assertEqual(payload["counts"]["version_ok_count"], 3)
        self.assertEqual(payload["counts"]["operator_checklist_count"], len(payload["operator_checklist"]))

        ready = entries["G70"]
        self.assertTrue(ready["asset_ready"])
        self.assertEqual(ready["asset_status"], "asset_ready")
        self.assertEqual(ready["blockers"], [])
        self.assertEqual(ready["expected_svt_filename"], "SVT_IDCEVO-WITHOUT_SWITCH_G70_EVO.xml")
        self.assertEqual(ready["expected_svt_status"], "operator_staged_required")
        self.assertFalse(ready["expected_svt_auto_checked"])
        self.assertEqual(ready["raco_pin_status"], "ok")
        self.assertTrue(all(item["operator_confirmed"] for item in ready["operator_checklist"]))
        self.assertTrue(all(not item["auto_checked"] for item in ready["operator_checklist"]))

        no_export = entries["G71"]
        self.assertFalse(no_export["asset_ready"])
        self.assertIn("No RCA export found for this IDCevo car.", no_export["blockers"])

        not_delivered = entries["G72"]
        self.assertFalse(not_delivered["asset_ready"])
        self.assertIn("Latest CHANGELOG entry is not delivered.", not_delivered["blockers"])

    def test_missing_repo_root_returns_empty_read_only_board(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = build_rack_readiness_board(
                root / "missing-trunk",
                workspace_root=root,
                now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        self.assertEqual(payload["source_state"], "missing")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["entry_total"], 0)
        self.assertTrue(payload["operator_checklist"])
        self.assertFalse(payload["is_approval"])

    def test_writes_json_and_markdown_with_expected_svt_and_operator_checklist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _rack_fixture(root)
            board = build_rack_readiness_board(
                repo,
                workspace_root=root,
                bmw_repo_root=root / "missing-bmw-repo",
                now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            )
            output_root = root / "out" / "rack"

            artifacts = write_rack_readiness_board(board, output_root)

            json_payload = json.loads(Path(artifacts["json_path"]).read_text(encoding="utf-8"))
            markdown = Path(artifacts["markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(json_payload["counts"]["entry_total"], 3)
        self.assertEqual(markdown, rack_readiness_markdown(board))
        self.assertIn("# Rack Pre-Flash Readiness", markdown)
        self.assertIn("SVT_IDCEVO-WITHOUT_SWITCH_G70_EVO.xml", markdown)
        self.assertIn("operator-confirmed", markdown)
        self.assertNotIn("flash success", markdown.casefold())


if __name__ == "__main__":
    unittest.main()

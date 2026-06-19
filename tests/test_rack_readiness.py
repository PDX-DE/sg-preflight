from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from sg_preflight.rack_readiness import (
    build_rack_readiness_board,
    expected_svt_filename,
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

    _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "G58" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")

    _write_car_changelog(
        repo / "Cars_IDCevo" / "BMW" / "G78" / "CHANGELOG.md",
        "## [3.4.0] - To be delivered",
    )
    _write_text(repo / "Cars_IDCevo" / "BMW" / "G78" / "export" / "G78.rca", "asset\n")

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

        self.assertEqual(set(entries), {"G70", "G58", "G78"})
        self.assertEqual(payload["counts"]["entry_total"], 3)
        self.assertEqual(payload["counts"]["asset_ready_count"], 2)
        self.assertEqual(payload["counts"]["asset_blocked_count"], 1)
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

        no_export = entries["G58"]
        self.assertFalse(no_export["asset_ready"])
        self.assertIn("No RCA export found for this IDCevo car.", no_export["blockers"])

        not_delivered = entries["G78"]
        self.assertTrue(not_delivered["asset_ready"])
        self.assertEqual(not_delivered["asset_status"], "asset_ready")
        self.assertEqual(not_delivered["blockers"], [])
        self.assertFalse(not_delivered["delivery_context"]["blocking"])
        self.assertEqual(not_delivered["delivery_context"]["status"], "not_delivered_yet")
        self.assertIn("Latest CHANGELOG entry is not delivered", not_delivered["context_notes"][0])
        self.assertNotIn("Latest CHANGELOG entry is not delivered.", not_delivered["blockers"])

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
        self.assertIn("reference only", markdown.casefold())
        self.assertIn("Delivery Context", markdown)
        self.assertIn("operator-confirmed", markdown)
        self.assertNotIn("flash success", markdown.casefold())

    def test_authoritative_idcevo_profiles_are_targets_and_decoys_are_visible_out_of_scope(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "PINT" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")
            _write_text(repo / "Cars_IDCevo" / "BMW" / "PINT" / "export" / "PINT.rca", "asset\n")
            _write_car_changelog(
                repo / "Cars_IDCevo" / "BMW" / "PINT_RUEKO" / "CHANGELOG.md",
                "## [3.4.0] - 2026-06-01",
            )
            _write_text(repo / "Cars_IDCevo" / "BMW" / "PINT_RUEKO" / "export" / "PINT_RUEKO.rca", "asset\n")
            _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "Generic" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")
            _write_text(repo / "Cars_IDCevo" / "BMW" / "Generic" / "export" / "Generic.rca", "asset\n")

            board = build_rack_readiness_board(
                repo,
                workspace_root=root,
                bmw_repo_root=root / "missing-bmw-repo",
                now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        entries = {entry["model_id"]: entry for entry in payload["entries"]}
        self.assertIn("documented profile list", payload["target_scope_note"])
        self.assertEqual(set(entries), {"PINT", "PINT_RUEKO"})
        self.assertNotIn("Generic", entries)
        self.assertEqual(payload["counts"]["out_of_scope_idcevo_dir_count"], 1)
        self.assertEqual(payload["out_of_scope_idcevo_dirs"][0]["relative_path"], "Cars_IDCevo/BMW/Generic")

    def test_expected_svt_filename_normalizes_profile_tokens(self) -> None:
        cases = {
            "G70": "SVT_IDCEVO-WITHOUT_SWITCH_G70_EVO.xml",
            "NA5": "SVT_IDCEVO-WITHOUT_SWITCH_NA5_EVO.xml",
            "PINT": "SVT_IDCEVO-WITHOUT_SWITCH_PINT_EVO.xml",
            "G70_EVO": "SVT_IDCEVO-WITHOUT_SWITCH_G70_EVO.xml",
            "na8_evo": "SVT_IDCEVO-WITHOUT_SWITCH_NA8_EVO.xml",
        }
        for model_id, expected in cases.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(expected_svt_filename(model_id), expected)

    def test_missing_authoritative_rack_target_is_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_car_changelog(repo / "Cars_IDCevo" / "BMW" / "PINT" / "CHANGELOG.md", "## [3.4.0] - 2026-06-01")
            _write_text(repo / "Cars_IDCevo" / "BMW" / "PINT" / "export" / "PINT.rca", "asset\n")

            board = build_rack_readiness_board(
                repo,
                workspace_root=root,
                bmw_repo_root=root / "missing-bmw-repo",
                now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        missing_paths = {entry["relative_path"] for entry in payload["missing_rack_target_dirs"]}
        self.assertIn("Cars_IDCevo/BMW/PINT_RUEKO", missing_paths)
        self.assertEqual(
            payload["counts"]["missing_rack_target_dir_count"],
            len(payload["missing_rack_target_dirs"]),
        )

    def test_missing_cross_domain_entry_still_emits_visible_rack_row(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _rack_fixture(root)
            with mock.patch(
                "sg_preflight.rack_readiness.build_cross_domain_delivery_board",
                return_value=SimpleNamespace(entries=()),
            ):
                board = build_rack_readiness_board(
                    repo,
                    workspace_root=root,
                    bmw_repo_root=root / "missing-bmw-repo",
                    now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
                )

        payload = board.to_dict()
        entries = {entry["model_id"]: entry for entry in payload["entries"]}
        self.assertIn("G70", entries)
        self.assertFalse(entries["G70"]["asset_ready"])
        self.assertIn("Missing version metadata: Ramses, RaCo Headless.", entries["G70"]["blockers"])

    def test_unexpected_build_failure_degrades_to_error_board(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _rack_fixture(root)
            with mock.patch(
                "sg_preflight.rack_readiness.build_delivery_readiness_board",
                side_effect=PermissionError("locked working copy"),
            ):
                board = build_rack_readiness_board(
                    repo,
                    workspace_root=root,
                    bmw_repo_root=root / "missing-bmw-repo",
                    now=datetime(2026, 6, 19, 11, 0, tzinfo=timezone.utc),
                )

        payload = board.to_dict()
        self.assertEqual(payload["source_state"], "error")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["entry_total"], 0)


if __name__ == "__main__":
    unittest.main()

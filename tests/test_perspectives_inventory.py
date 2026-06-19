from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from sg_preflight.perspectives_inventory import (
    build_perspectives_inventory_board,
    perspectives_inventory_markdown,
    write_perspectives_inventory_board,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write_text(path, json.dumps(payload))


def _scene(*, core: bool = True) -> dict[str, object]:
    payload: dict[str, object] = {
        "CraneGimbal": {"Distance": 1},
        "Frustum": {"Near": 0.1},
        "Viewport": {"Width": 1920},
    }
    if not core:
        payload.pop("CraneGimbal")
    return payload


def _perspectives_fixture(root: Path) -> Path:
    repo = root / "repositories" / "trunk"
    _write_text(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_json(
        repo / "Cars" / "BMW" / "F70" / "perspectives_CID_2to1.json",
        {
            "Home": _scene(),
            "Charge": _scene(),
            "Service": _scene(),
            "F70Only": _scene(),
        },
    )

    _write_text(repo / "Cars" / "BMW" / "F71" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_json(
        repo / "Cars" / "BMW" / "F71" / "perspectives_CID_2to1.json",
        {
            "Home": _scene(),
            "Charge": _scene(),
        },
    )

    _write_text(repo / "Cars" / "BMW" / "F72" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_json(
        repo / "Cars" / "BMW" / "F72" / "perspectives_CID_2to1.json",
        {
            "Home": _scene(),
            "Service": _scene(core=False),
        },
    )

    _write_text(repo / "Cars" / "BMW" / "F73" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_json(
        repo / "Cars" / "BMW" / "F73" / "perspectives_IC_high.json",
        {
            "Cluster": _scene(),
        },
    )

    _write_text(repo / "Cars" / "BMW" / "F74" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_json(
        repo / "Cars" / "BMW" / "F74" / "perspectives_IC_high.json",
        {
            "Cluster": _scene(),
        },
    )

    _write_text(repo / "Cars" / "BMW" / "F75" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    _write_text(repo / "Cars" / "BMW" / "F75" / "perspectives_CDD_high.json", "{not json")

    _write_text(repo / "Cars_IDCevo" / "MINI" / "J01" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
    return repo


class TestPerspectivesInventory(unittest.TestCase):
    def test_board_inventory_peer_comparison_and_tolerant_buckets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _perspectives_fixture(root)
            board = build_perspectives_inventory_board(
                repo,
                workspace_root=root,
                now=datetime(2026, 6, 19, 3, 30, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        entries = {(entry["model_id"], entry["display_type"]): entry for entry in payload["entries"]}
        no_perspectives = {entry["relative_path"] for entry in payload["no_perspectives_entries"]}

        self.assertEqual(payload["source_state"], "ready")
        self.assertEqual(payload["generated_at_utc"], "2026-06-19T03:30:00+00:00")
        self.assertEqual(payload["counts"]["car_total"], 7)
        self.assertEqual(payload["counts"]["file_total"], 6)
        self.assertEqual(payload["counts"]["display_type_group_count"], 3)
        self.assertEqual(payload["counts"]["peer_outlier_count"], 3)
        self.assertEqual(payload["counts"]["malformed_file_count"], 1)
        self.assertEqual(payload["counts"]["structural_issue_count"], 1)
        self.assertEqual(payload["counts"]["no_perspectives_count"], 1)
        self.assertIn("Cars_IDCevo/MINI/J01", no_perspectives)
        self.assertFalse(payload["is_approval"])
        self.assertIn("Evidence only", payload["manual_review_banner"])

        cid_group = payload["display_type_groups"]["CID_2to1"]
        self.assertEqual(cid_group["car_count"], 3)
        self.assertEqual(cid_group["comparison_status"], "compared")
        self.assertEqual(cid_group["common_scene_threshold"], 2)
        self.assertEqual(cid_group["common_scenes"], ["Charge", "Home", "Service"])

        f71 = entries[("F71", "CID_2to1")]
        self.assertEqual(f71["scene_count"], 2)
        self.assertEqual(f71["missing_common_scenes"], ["Service"])
        self.assertIn("Service (present in 2/3 CID_2to1 cars)", f71["peer_flags"])
        self.assertEqual(f71["unique_scenes"], [])

        f70 = entries[("F70", "CID_2to1")]
        self.assertEqual(f70["unique_scenes"], ["F70Only"])
        self.assertIn("F70Only unique to this car among CID_2to1 peers", f70["peer_flags"])

        f72 = entries[("F72", "CID_2to1")]
        self.assertEqual(f72["scenes_missing_core_fields"][0]["scene_id"], "Service")
        self.assertEqual(f72["scenes_missing_core_fields"][0]["missing_fields"], ["CraneGimbal"])

        ic_group = payload["display_type_groups"]["IC_high"]
        self.assertEqual(ic_group["comparison_status"], "too_few_peers")
        self.assertEqual(ic_group["comparison_note"], "too few peers to compare (2)")
        self.assertEqual(entries[("F73", "IC_high")]["comparison_note"], "too few peers to compare (2)")

        malformed = entries[("F75", "CDD_high")]
        self.assertTrue(malformed["malformed_json"])
        self.assertEqual(malformed["scene_count"], 0)
        self.assertIn("Malformed JSON", malformed["notes"][0])

    def test_missing_repo_root_returns_empty_read_only_board(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = build_perspectives_inventory_board(
                root / "missing-trunk",
                workspace_root=root,
                now=datetime(2026, 6, 19, 3, 30, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        self.assertEqual(payload["source_state"], "missing")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["car_total"], 0)
        self.assertIn("Evidence only", payload["manual_review_banner"])

    def test_brand_level_perspectives_files_are_references_not_peer_cars(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_json(
                repo / "Cars" / "BMW" / "perspectives_CID_2to1.json",
                {
                    "Home": _scene(),
                    "BrandOnly": _scene(),
                },
            )
            _write_text(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
            _write_json(
                repo / "Cars" / "BMW" / "F70" / "perspectives_CID_2to1.json",
                {
                    "Home": _scene(),
                    "Charge": _scene(),
                },
            )
            _write_text(repo / "Cars" / "BMW" / "F71" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
            _write_json(
                repo / "Cars" / "BMW" / "F71" / "perspectives_CID_2to1.json",
                {
                    "Home": _scene(),
                    "Charge": _scene(),
                },
            )
            _write_text(repo / "Cars" / "BMW" / "F72" / "CHANGELOG.md", "## [1.0.0] - 2026-01-01\n")
            _write_json(
                repo / "Cars" / "BMW" / "F72" / "perspectives_CID_2to1.json",
                {
                    "Home": _scene(),
                },
            )
            board = build_perspectives_inventory_board(
                repo,
                workspace_root=root,
                now=datetime(2026, 6, 19, 3, 30, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        self.assertEqual(payload["counts"]["car_total"], 3)
        self.assertEqual(payload["counts"]["file_total"], 3)
        self.assertEqual(payload["counts"]["brand_reference_count"], 1)
        self.assertEqual(payload["counts"]["no_perspectives_count"], 0)
        self.assertNotIn(("BMW", "CID_2to1"), {
            (entry["model_id"], entry["display_type"]) for entry in payload["entries"]
        })
        cid_group = payload["display_type_groups"]["CID_2to1"]
        self.assertEqual(cid_group["car_count"], 3)
        self.assertEqual(cid_group["common_scene_threshold"], 2)
        self.assertEqual(cid_group["common_scenes"], ["Charge", "Home"])
        f72 = next(entry for entry in payload["entries"] if entry["model_id"] == "F72")
        self.assertIn("Charge (present in 2/3 CID_2to1 cars)", f72["peer_flags"])

        reference = payload["brand_reference_entries"][0]
        self.assertEqual(reference["relative_path"], "Cars/BMW")
        self.assertEqual(reference["brand"], "BMW")
        self.assertEqual(reference["display_type"], "CID_2to1")
        self.assertEqual(reference["scene_count"], 2)
        self.assertEqual(reference["scenes"], ["BrandOnly", "Home"])

    def test_writes_json_and_markdown_with_peer_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _perspectives_fixture(root)
            board = build_perspectives_inventory_board(
                repo,
                workspace_root=root,
                now=datetime(2026, 6, 19, 3, 30, tzinfo=timezone.utc),
            )
            output_root = root / "out" / "perspectives"

            artifacts = write_perspectives_inventory_board(board, output_root)

            json_payload = json.loads(Path(artifacts["json_path"]).read_text(encoding="utf-8"))
            markdown = Path(artifacts["markdown_path"]).read_text(encoding="utf-8")

        self.assertEqual(json_payload["counts"]["file_total"], 6)
        self.assertEqual(markdown, perspectives_inventory_markdown(board))
        self.assertIn("# Perspectives Inventory & Consistency Board", markdown)
        self.assertIn("CID_2to1", markdown)
        self.assertIn("Service (present in 2/3 CID_2to1 cars)", markdown)
        self.assertIn("Cars_IDCevo/MINI/J01", markdown)


if __name__ == "__main__":
    unittest.main()

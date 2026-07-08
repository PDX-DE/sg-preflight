from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.authoring_assets import (
    authoring_asset_board_markdown,
    build_authoring_asset_board,
    write_authoring_asset_board,
)


def _special(root: Path, profile: str, filename: str) -> None:
    d = root / "cars" / "BMW" / profile / "_WorkFiles" / "blender" / "special"
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_bytes(b"BLENDER-fake")


class AuthoringAssetTests(unittest.TestCase):
    def test_inventory_groups_assets_across_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _special(root, "F70", "F70_Helper.blend")
            _special(root, "F70", "F70_Wheel_Pivots.blend")
            _special(root, "G45", "G45_Wheel_Pivots.blend")
            board = build_authoring_asset_board(root)
        self.assertEqual(board["state"], "ok")
        self.assertEqual(board["profiles_with_special"], 2)
        self.assertEqual(board["special_files"], 3)
        wheels = next(a for a in board["assets"] if a["asset"] == "Wheel_Pivots")
        self.assertEqual(wheels["present_in"], ["F70", "G45"])
        self.assertEqual(wheels["count"], 2)

    def test_noexport_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _special(root, "U11", "U11_LightFX_Boolean_NOEXPORT.blend")
            board = build_authoring_asset_board(root)
        self.assertEqual(len(board["noexport"]), 1)
        self.assertEqual(board["noexport"][0]["profile"], "U11")

    def test_mismatched_prefix_detects_donor_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _special(root, "G45", "G45_Wheel_Pivots.blend")
            _special(root, "PINT", "G45_Wheel_Pivots.blend")  # donor copy not renamed
            _special(root, "PINT", "PINT_Helper.blend")  # correctly owned
            board = build_authoring_asset_board(root)
        mism = board["mismatched_prefix"]
        self.assertEqual(len(mism), 1)
        self.assertEqual(mism[0]["profile"], "PINT")
        self.assertEqual(mism[0]["file"], "G45_Wheel_Pivots.blend")
        self.assertEqual(mism[0]["looks_copied_from"], "G45")

    def test_multi_token_profile_name_not_false_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _special(root, "PINT_SUV", "PINT_SUV_Helper.blend")  # correct, despite underscore in profile
            board = build_authoring_asset_board(root)
        self.assertEqual(board["mismatched_prefix"], [])

    def test_no_special_found(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            board = build_authoring_asset_board(tmp)
        self.assertEqual(board["state"], "no_special_found")

    def test_markdown_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _special(root, "PINT", "U11_Helper.blend")
            _special(root, "U11", "U11_LightFX_NOEXPORT.blend")
            board = build_authoring_asset_board(root)
            text = authoring_asset_board_markdown(board)
            out = write_authoring_asset_board(board, root / "out" / "authoring.md")
            self.assertIn("mismatched profile prefix", text)
            self.assertIn("NOEXPORT-marked files", text)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest
from unittest import mock

from sg_preflight.checker_catalog import list_checker_catalog
from tests.operator_helpers import create_temp_g65_profile, write_text


def _create_catalog_files(root: Path) -> None:
    mirror_root = root / "repositories" / "trunk"
    write_text(mirror_root / ".pdx" / "checkers" / "checkall.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "checkcars_IDCevo.bat", "@echo off\n")
    write_text(mirror_root / ".pdx" / "checkers" / "executeChecks.py", "print('checker stub')\n")
    write_text(
        mirror_root / ".pdx" / "checkers" / "code_style_checker" / "check_all_styles.py",
        "print('style stub')\n",
    )
    write_text(
        mirror_root / ".pdx" / "checkers" / "printNotUsedResources.py",
        "print('unused stub')\n",
    )
    write_text(mirror_root / "check_scenes.py", "print('scene stub')\n")
    (mirror_root / "Cars").mkdir(parents=True, exist_ok=True)


class TestCheckerCatalog(unittest.TestCase):
    def test_checker_catalog_captures_direct_wrapped_and_reference_layers(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = create_temp_g65_profile(root)
            _create_catalog_files(root)

            with mock.patch.dict(
                os.environ,
                {
                    "SG_RACO_HEADLESS": str(root / "missing" / "RaCoHeadless.exe"),
                    "SG_CARMODELS_REPO": str(root / "missing" / "digital-3d-car-models"),
                },
                clear=False,
            ):
                with mock.patch("sg_preflight.checker_catalog.shutil.which", return_value=None):
                    items = list_checker_catalog(root, profiles=[profile])

        item_map = {item.key: item for item in items}
        self.assertEqual(item_map["style_checker"].coverage, "direct")
        self.assertEqual(item_map["execute_checks"].coverage, "direct")
        self.assertEqual(item_map["checkall_bat"].coverage, "reference")
        self.assertIn("repo_checker_all", item_map["checkall_bat"].operator_surface)
        self.assertEqual(item_map["delivery_checklist"].state, "partial")
        self.assertEqual(item_map["bmw_smoke"].state, "blocked")
        self.assertEqual(item_map["check_scenes"].state, "partial")


if __name__ == "__main__":
    unittest.main()

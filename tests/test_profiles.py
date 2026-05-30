from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.profiles import PROFILE_SCOPE_DEFAULT, list_run_profiles
from tests.operator_helpers import write_text


ROOT = Path(__file__).resolve().parents[1]
MIRROR_ROOT = ROOT / "repositories" / "trunk"


@unittest.skipUnless(MIRROR_ROOT.exists(), "Live SG mirror is required for profile coverage assertions")
class TestProfiles(unittest.TestCase):
    def test_live_profile_registry_includes_verified_extended_bmw_slices(self) -> None:
        profile_ids = {profile.profile_id for profile in list_run_profiles(ROOT)}

        self.assertTrue({"G70", "G65", "G45"}.issubset(profile_ids))
        self.assertTrue({"G50", "G58", "G78", "NA5", "PINT", "PINT_RUEKO", "F70", "PINT_SUV", "U10", "G68"}.issubset(profile_ids))


class TestDynamicProfiles(unittest.TestCase):
    def test_dynamic_registry_exposes_full_set_while_default_view_keeps_active_builds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bmw_root = root / "digital-3d-car-models"
            records = []
            for name in ["F70", *[f"B{index:02d}" for index in range(16)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 12
""".strip()
                )
            for name in ["G50_EVO", *[f"E{index:02d}_EVO" for index in range(8)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: build
  hmi:
    interface_version: 24
""".strip()
                )
            for name in ["U25", "F66"]:
                records.append(
                    f"""
- name: {name}
  brand: MINI
  type: build
  hmi:
    interface_version: 12
""".strip()
                )
            for name in ["G58_EVO", *[f"R{index:02d}_EVO" for index in range(47)]]:
                records.append(
                    f"""
- name: {name}
  brand: BMW
  type: retarget
  target: PINT
""".strip()
                )
            write_text(bmw_root / "ci" / "scripts" / "common" / "models_build_config.yaml", "\n\n".join(records) + "\n")

            all_profiles = list_run_profiles(root, bmw_root=bmw_root)
            default_profiles = list_run_profiles(root, bmw_root=bmw_root, profile_scope=PROFILE_SCOPE_DEFAULT)

        all_ids = {profile.profile_id for profile in all_profiles}
        default_ids = {profile.profile_id for profile in default_profiles}
        self.assertEqual(len(all_profiles), 76)
        self.assertEqual(len(default_profiles), 28)
        self.assertIn("G58", all_ids)
        self.assertNotIn("G58", default_ids)
        self.assertIn("MINI_U25", default_ids)
        self.assertTrue(all(profile.active_build for profile in default_profiles))


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

from pathlib import Path
import unittest

from sg_preflight.profiles import list_run_profiles


ROOT = Path(__file__).resolve().parents[1]
MIRROR_ROOT = ROOT / "repositories" / "trunk"


@unittest.skipUnless(MIRROR_ROOT.exists(), "Live SG mirror is required for profile coverage assertions")
class TestProfiles(unittest.TestCase):
    def test_live_profile_registry_includes_verified_extended_bmw_slices(self) -> None:
        profile_ids = {profile.profile_id for profile in list_run_profiles(ROOT)}

        self.assertTrue({"G70", "G65", "G45"}.issubset(profile_ids))
        self.assertTrue({"G50", "G58", "G78", "NA5", "PINT", "PINT_RUEKO", "F70", "PINT_SUV", "U10", "G68"}.issubset(profile_ids))


if __name__ == "__main__":
    unittest.main()

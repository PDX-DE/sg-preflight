from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from sg_preflight.delivery_support_package import materialize_delivery_support_package
from tests.test_ticket_review import (
    _create_checker_files,
    _create_native_verification,
    _create_profile,
    _create_visual_review_files,
)


class TestDeliverySupportPackage(unittest.TestCase):
    def test_materialize_delivery_support_package_packages_messages_and_nested_ticket_bundles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile = _create_profile(root)
            _create_checker_files(root)
            _create_visual_review_files(root, profile.project_root)
            _create_native_verification(root)

            result = materialize_delivery_support_package(
                workspace=root,
                output_root=root / "out" / "delivery-support-package",
                grounded_profile_id="G65",
                grounded_scope_note="G65 is only the first concrete live-SVN slice, not confirmed final scope.",
                coordinator_name="Jana",
                review_owner_group="Adrian / Hristofor / Stefan",
            )

            self.assertTrue(result.package_root.exists())
            self.assertTrue(result.zip_path.exists())
            self.assertTrue(result.brief_path.exists())
            self.assertTrue(result.progress_path.exists())
            self.assertTrue(result.coordinator_update_path.exists())
            self.assertTrue(result.review_owners_update_path.exists())
            self.assertTrue(result.next_steps_path.exists())
            self.assertTrue(result.continuation_path.exists())
            self.assertTrue(result.grounded_bundle.package_root.exists())
            self.assertTrue(result.scope_bundle.package_root.exists())
            self.assertFalse((result.grounded_bundle.package_root / "artifacts" / "actions").exists())
            self.assertFalse((result.scope_bundle.package_root / "artifacts" / "actions").exists())

            brief_text = result.brief_path.read_text(encoding="utf-8")
            progress_text = result.progress_path.read_text(encoding="utf-8")
            coordinator_text = result.coordinator_update_path.read_text(encoding="utf-8")
            review_owner_text = result.review_owners_update_path.read_text(encoding="utf-8")
            continuation_text = result.continuation_path.read_text(encoding="utf-8")

            self.assertIn("What The Coordinator Asked For", brief_text)
            self.assertIn("headless export check bmw", brief_text)
            self.assertIn("IDCEVODEV-960073", brief_text)
            self.assertIn("IDCEVODEV-977874", brief_text)
            self.assertIn("Current Progress", progress_text)
            self.assertIn("BMW-side end-to-end execution", progress_text)
            self.assertIn("Suggested Teams update", coordinator_text)
            self.assertIn("BMW status right now", coordinator_text)
            self.assertIn("exact screenshot-test reading flow", review_owner_text)
            self.assertIn("keep improving `sg-preflight`", continuation_text)
            self.assertEqual("05_continuation_brief.md", result.continuation_path.name)
            self.assertNotIn("Co" + "dex", continuation_text)

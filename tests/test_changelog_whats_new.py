from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from sg_preflight.changelog_whats_new import (
    build_changelog_whats_new,
    render_changelog_whats_new_markdown,
    render_changelog_whats_new_text,
)
from tests.operator_helpers import write_text


NOW_UTC = datetime(2026, 6, 27, 20, 30, 0, tzinfo=timezone.utc)


class ChangelogWhatsNewTests(unittest.TestCase):
    def test_real_changelog_top_section_is_current_build(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]

        payload = build_changelog_whats_new(repo_root, now_utc=NOW_UTC)

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["data_available"])
        self.assertTrue(payload["read_only"])
        self.assertFalse(payload["is_approval"])
        self.assertEqual(payload["generated_at_utc"], "2026-06-27T20:30:00+00:00")
        self.assertEqual(payload["title"], "What's new in this build")
        self.assertEqual(payload["current_section"]["title"], "Unreleased - local alpha")
        self.assertEqual(payload["current_section"]["heading"], "## [Unreleased - local alpha]")
        subsection_titles = [section["title"] for section in payload["current_section"]["subsections"]]
        self.assertIn("Added", subsection_titles)
        self.assertIn("Data handling", subsection_titles)
        self.assertIn("Fixed", subsection_titles)
        self.assertGreater(payload["counts"]["current_item_count"], 0)
        self.assertEqual(payload["counts"]["earlier_section_count"], 0)
        self.assertTrue(str(payload["source_path"]).endswith("CHANGELOG.md"))

    def test_multisection_changelog_uses_topmost_section_and_preserves_earlier_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            changelog_path = root / "CHANGELOG.md"
            before = (
                "\ufeff# Changelog\n"
                "\n"
                "## [2.0.0] - 2026-06-27\n"
                "\n"
                "### Added\n"
                "- What's new page\n"
                "- Welcome card link\n"
                "\n"
                "### Fixed\n"
                "- Empty state wording\n"
                "\n"
                "## [1.0.0] - 2026-06-01\n"
                "\n"
                "### Added\n"
                "- First local alpha\n"
            )
            write_text(changelog_path, before)

            payload = build_changelog_whats_new(root, now_utc=NOW_UTC)

            self.assertEqual(payload["current_section"]["title"], "2.0.0 - 2026-06-27")
            self.assertEqual(payload["earlier_sections"][0]["title"], "1.0.0 - 2026-06-01")
            self.assertEqual(payload["counts"]["current_subsection_count"], 2)
            self.assertEqual(payload["counts"]["current_item_count"], 3)
            self.assertEqual(payload["counts"]["earlier_section_count"], 1)
            self.assertEqual(payload["counts"]["earlier_item_count"], 1)
            self.assertEqual(changelog_path.read_text(encoding="utf-8"), before)

    def test_missing_changelog_returns_honest_unavailable_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            payload = build_changelog_whats_new(root, now_utc=NOW_UTC)

            self.assertEqual(payload["status"], "unavailable")
            self.assertFalse(payload["data_available"])
            self.assertTrue(payload["read_only"])
            self.assertEqual(payload["current_section"]["subsections"], [])
            self.assertEqual(payload["counts"]["current_item_count"], 0)
            self.assertIn("CHANGELOG.md was not found", payload["summary"])
            self.assertIn("No changelog found", payload["empty_state_note"])

    def test_renderers_preserve_honest_whats_new_framing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_text(
                root / "CHANGELOG.md",
                "# Changelog\n\n"
                "## [2.0.0] - 2026-06-27\n\n"
                "### Added\n"
                "- What's new page\n",
            )

            payload = build_changelog_whats_new(root, now_utc=NOW_UTC)
            text = render_changelog_whats_new_text(payload)
            markdown = render_changelog_whats_new_markdown(payload)

            self.assertIn("What's new in this build", text)
            self.assertIn("2.0.0 - 2026-06-27", text)
            self.assertIn("- What's new page", text)
            self.assertIn("Read-only", text)
            self.assertIn("# What's new in this build", markdown)
            self.assertIn("## 2.0.0 - 2026-06-27", markdown)
            self.assertNotIn("since last version", text.lower())
            self.assertNotIn("approved", markdown.lower())


if __name__ == "__main__":
    unittest.main()

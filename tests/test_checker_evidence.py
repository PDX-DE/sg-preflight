from __future__ import annotations

from pathlib import Path
import unittest

from sg_preflight.checker_evidence import parse_repo_checker_log, parse_scene_check_output


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "checkers"


def _fixture(name: str) -> str:
    return (FIXTURE_ROOT / name).read_text(encoding="utf-8")


class TestCheckerEvidence(unittest.TestCase):
    def test_repo_checker_clean_output_is_summary_only_and_clean(self) -> None:
        evidence = parse_repo_checker_log(_fixture("repo_checker_clean.log"), raw_log_path="out/repo-clean.log")

        self.assertEqual(evidence["source_kind"], "repo_checker")
        self.assertEqual(evidence["raw_log_path"], "out/repo-clean.log")
        self.assertTrue(evidence["summary_only"])
        self.assertEqual(evidence["affected_files"], [])
        self.assertEqual(evidence["top_paths"], [])
        checker_names = {item["name"] for item in evidence["checkers"]}
        self.assertEqual(
            checker_names,
            {"binarycheck", "luacheck", "newlinecheck", "style_checker", "tabbingcheck"},
        )
        self.assertTrue(all(item["status"] == "clean" for item in evidence["checkers"]))

    def test_repo_checker_issue_output_extracts_file_backed_hits(self) -> None:
        evidence = parse_repo_checker_log(_fixture("repo_checker_issue.log"))

        self.assertFalse(evidence["summary_only"])
        self.assertGreaterEqual(len(evidence["affected_files"]), 4)
        self.assertEqual(
            evidence["top_paths"][0]["path"],
            r"C:\repo\repositories\trunk\Cars_IDCevo\RollsRoyce\PINT_RR\_Placeholders\scripts\Logic_Placeholder_Hood.lua",
        )
        self.assertEqual(evidence["top_paths"][0]["issue_count"], 4)
        self.assertEqual(evidence["top_paths"][0]["line"], 16)
        self.assertIn("luacheck", evidence["top_paths"][0]["checkers"])
        self.assertIn("style_checker", evidence["top_paths"][0]["checkers"])
        self.assertIn("tabbingcheck", evidence["top_paths"][0]["checkers"])
        checker_map = {item["name"]: item for item in evidence["checkers"]}
        self.assertEqual(checker_map["style_checker"]["issues"], 1)
        self.assertEqual(checker_map["luacheck"]["issues"], 2)
        self.assertEqual(checker_map["tabbingcheck"]["issues"], 2)
        self.assertTrue(any("Logic_Placeholder_Hood.lua line 16 first" in item for item in evidence["manual_followups"]))

    def test_scene_check_clean_output_tracks_checked_scene_without_hits(self) -> None:
        evidence = parse_scene_check_output(_fixture("scene_check_clean.log"))

        self.assertTrue(evidence["summary_only"])
        self.assertEqual(evidence["checked_scenes"], 1)
        self.assertEqual(evidence["scenes_with_errors"], 0)
        self.assertEqual(evidence["affected_files"], [])
        self.assertEqual(evidence["checkers"][0]["status"], "clean")

    def test_scene_check_error_output_extracts_scene_error_block(self) -> None:
        evidence = parse_scene_check_output(
            _fixture("scene_check_error.log"),
            raw_log_path="out/scene-error.log",
            workbook_path="out/scene-error.xlsx",
        )

        self.assertFalse(evidence["summary_only"])
        self.assertEqual(evidence["raw_log_path"], "out/scene-error.log")
        self.assertEqual(evidence["workbook_path"], "out/scene-error.xlsx")
        self.assertEqual(evidence["checked_scenes"], 1)
        self.assertEqual(evidence["scenes_with_errors"], 1)
        self.assertEqual(
            evidence["top_paths"][0]["path"],
            r"C:\repo\out\tmp-checker-fixtures\broken_scene.rca",
        )
        self.assertIn("File Load Error", evidence["affected_files"][0]["message"])
        self.assertIn("File Load Error", evidence["affected_files"][0]["excerpt"])
        self.assertEqual(evidence["checkers"][0]["status"], "error")

    def test_malformed_or_partial_output_falls_back_to_summary_only(self) -> None:
        repo_evidence = parse_repo_checker_log("garbled checker output")
        scene_evidence = parse_scene_check_output("[E] orphan error without scene header")

        self.assertTrue(repo_evidence["summary_only"])
        self.assertEqual(repo_evidence["affected_files"], [])
        self.assertTrue(scene_evidence["summary_only"])
        self.assertEqual(scene_evidence["checked_scenes"], 0)
        self.assertEqual(scene_evidence["scenes_with_errors"], 0)


if __name__ == "__main__":
    unittest.main()

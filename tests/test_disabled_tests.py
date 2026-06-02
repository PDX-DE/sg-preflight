from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest

from sg_preflight.cli import main
from sg_preflight.disabled_tests import (
    CAUTIOUS_BASELINE_LABEL,
    build_disabled_tests_board,
    extract_lua_test_calls,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_changelog(path: Path) -> None:
    _write_text(path, "## [1.0.0] - NOT YET DELIVERED\n")


def _disabled_tests_fixture(root: Path) -> Path:
    repo = root / "repositories" / "trunk"
    _write_changelog(repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md")
    _write_changelog(repo / "Cars_IDCevo" / "BMW" / "G65" / "CHANGELOG.md")
    for name in ("export", "logic", "main", "resources"):
        (repo / "Cars_IDCevo" / "BMW" / "G58" / name).mkdir(parents=True, exist_ok=True)

    f70_tests = repo / "Cars" / "BMW" / "F70" / "export" / "tests"
    _write_text(
        f70_tests / "test_config_tmp.lua",
        "\n".join(
            (
                'addTest("knownBaseline", function(time_ms) reset() end)',
                'addInterfaceTest("interfaceBaseline", function(time_ms) reset() end)',
                'disableTest("knownBaseline")',
                'addTest("carSpecificAfterDisable", function(time_ms) reset() end)',
                "",
            )
        ),
    )
    _write_text(f70_tests / "expected" / "expectedOnly.png", "fixture")
    _write_text(
        f70_tests / "test_config.lua",
        "\n".join(
            (
                "--[[",
                'disableTest("commentedDisable")',
                "]]--",
                "--addTest(\"commentedAdd\", function(time_ms) reset() end)",
                'disableTest("knownBaseline")',
                'disableTest("reviewMe")',
                'disableTest("reviewMe")',
                'disableTest("expectedOnly")',
                'addTest("countryCoding_US",',
                "  function(time_ms) reset(); waitOnRendering(1000) end)",
                "",
            )
        ),
    )
    _write_text(
        repo / "Cars_IDCevo" / "BMW" / "G65" / "export" / "tests" / "test_config.lua",
        "\n".join(
            (
                '--[[disableTest("knownBaseline")]]--',
                'addTest("lights_iconicGlow", function(time_ms) reset() end)',
                "",
            )
        ),
    )
    return repo


class TestDisabledTests(unittest.TestCase):
    def test_extract_lua_test_calls_ignores_line_and_block_comments(self) -> None:
        text = "\n".join(
            (
                '--addTest("commented", function(time_ms) reset() end)',
                '--[[disableTest("blocked")]]--',
                'disableTest("active")',
                'addTest("multiLine",',
                "  function(time_ms) reset() end)",
                "",
            )
        )

        calls = extract_lua_test_calls(text)

        self.assertEqual([(call.function, call.name) for call in calls], [("disableTest", "active"), ("addTest", "multiLine")])

    def test_board_reports_no_config_duplicates_and_cautious_baseline_flags(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repo = _disabled_tests_fixture(Path(temp_dir))

            board = build_disabled_tests_board(repo)

        payload = board.to_dict()
        rows = {entry["relative_path"]: entry for entry in payload["entries"]}
        self.assertEqual(payload["counts"]["total"], 3)
        self.assertEqual(payload["counts"]["configured"], 2)
        self.assertEqual(payload["counts"]["no_config"], 1)
        self.assertEqual(payload["counts"]["disabled_call_total"], 4)
        self.assertEqual(payload["counts"]["duplicate_entry_count"], 1)
        self.assertEqual(payload["counts"]["baseline_review_entry_count"], 1)
        self.assertEqual(payload["baseline"]["state"], "available")
        self.assertIn("knownBaseline", payload["baseline"]["test_names"])
        self.assertIn("expectedOnly", payload["baseline"]["test_names"])
        self.assertEqual(rows["Cars_IDCevo/BMW/G58"]["config_status"], "no_config")
        self.assertEqual(rows["Cars/BMW/F70"]["commented_call_count"], 2)
        self.assertEqual(rows["Cars/BMW/F70"]["duplicate_disabled_tests"], ["reviewMe"])
        self.assertEqual(rows["Cars/BMW/F70"]["baseline_review_disabled_tests"], ["reviewMe"])
        self.assertEqual(rows["Cars_IDCevo/BMW/G65"]["disabled_count"], 0)

    def test_cli_writes_json_and_markdown_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _disabled_tests_fixture(root)
            output_root = root / "out" / "disabled-tests"
            stdout = io.StringIO()

            with redirect_stdout(stdout):
                result = main(
                    [
                        "disabled-tests",
                        "--workspace",
                        str(root),
                        "--repo-root",
                        str(repo),
                        "--output-root",
                        str(output_root),
                        "--json",
                    ]
                )

            self.assertEqual(result, 0)
            payload = json.loads(stdout.getvalue())
            self.assertEqual(payload["counts"]["no_config"], 1)
            self.assertEqual(payload["cautious_baseline_label"], CAUTIOUS_BASELINE_LABEL)
            self.assertTrue((output_root / "disabled-tests.json").exists())
            self.assertTrue((output_root / "disabled-tests.md").exists())


if __name__ == "__main__":
    unittest.main()

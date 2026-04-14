from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from sg_preflight.retro import parse_retro_export, write_retro_json, write_retro_markdown


class TestRetro(unittest.TestCase):
    def test_parse_retro_export_extracts_pain_points_actions_and_comments(self) -> None:
        html = """
        <html>
          <body>
            <div aria-label="Too many avoidable findings, Soft red Note."></div>
            <div aria-label="Created by Jana"></div>
            <div aria-label="Adrian creates meeting for QA-Hero sync, Soft blue Note."></div>
            <div aria-label="Created by Adrian"></div>
            <div aria-label="Earlier internal rack testing would help, Soft orange Note."></div>
            <div aria-label="Created by PC"></div>
          </body>
        </html>
        """
        comments = {
            "commentThreads": [
                {
                    "id": "thread-1",
                    "comments": [
                        {
                            "author": {"name": "David"},
                            "body": "Need clearer ownership and earlier checks.",
                            "displayDate": "2026-04-14",
                        }
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            html_path = temp_root / "retro.html"
            comments_path = temp_root / "retro-comments.json"
            json_out = temp_root / "retro.json"
            md_out = temp_root / "retro.md"
            html_path.write_text(html, encoding="utf-8")
            comments_path.write_text(json.dumps(comments), encoding="utf-8")

            payload = parse_retro_export(html_path, comments_path)
            write_retro_json(payload, json_out)
            write_retro_markdown(payload, md_out)

            markdown = md_out.read_text(encoding="utf-8")
            written_json = json.loads(json_out.read_text(encoding="utf-8"))

        self.assertEqual(payload["summary"]["notes"], 3)
        self.assertEqual(payload["summary"]["pain_points"], 1)
        self.assertEqual(payload["summary"]["actions"], 1)
        self.assertEqual(payload["summary"]["comments"], 1)
        self.assertIn("Too many avoidable findings", payload["themes"]["finding_handoff"])
        self.assertIn("Adrian creates meeting for QA-Hero sync", payload["actions"])
        self.assertEqual(written_json["summary"]["notes"], 3)
        self.assertIn("# SG Preflight Retro Pain Map", markdown)
        self.assertIn("Need clearer ownership and earlier checks.", markdown)


if __name__ == "__main__":
    unittest.main()

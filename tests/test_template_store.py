from __future__ import annotations

import json
import tempfile
from pathlib import Path
import unittest

from sg_preflight.template_store import (
    TEMPLATE_BANNER,
    TemplateStoreError,
    delete_template,
    list_templates,
    load_template,
    parse_template_args,
    record_template_run,
    save_template,
)


class TestTemplateStore(unittest.TestCase):
    def test_save_load_list_delete_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            saved = save_template(
                root,
                "morning-digest",
                command="daily-digest",
                args=("latest", "--format", "markdown"),
                description="Morning digest for SG Daily",
            )

            self.assertEqual(saved["name"], "morning-digest")
            self.assertEqual(saved["command"], "daily-digest")
            self.assertEqual(saved["args"], ["latest", "--format", "markdown"])
            self.assertEqual(saved["description"], "Morning digest for SG Daily")
            self.assertIn("created_at", saved)
            self.assertIn("updated_at", saved)
            self.assertEqual(load_template(root, "morning-digest")["name"], "morning-digest")
            self.assertEqual([item["name"] for item in list_templates(root)], ["morning-digest"])

            deleted = delete_template(root, "morning-digest")

            self.assertEqual(deleted["name"], "morning-digest")
            self.assertEqual(list_templates(root), [])

    def test_duplicate_save_requires_replace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            save_template(root, "profiles", command="list-profiles", args=("--format", "json"))

            with self.assertRaisesRegex(TemplateStoreError, "already exists"):
                save_template(root, "profiles", command="list-profiles")

            replaced = save_template(root, "profiles", command="list-actions", replace=True)

            self.assertEqual(replaced["command"], "list-actions")
            self.assertEqual(replaced["args"], [])

    def test_malformed_template_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "templates" / "broken.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"name": "broken", "args": "not-a-list"}', encoding="utf-8")

            with self.assertRaisesRegex(TemplateStoreError, "Malformed template"):
                load_template(Path(temp_dir), "broken")

    def test_template_name_must_be_file_safe(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(TemplateStoreError, "Template name"):
                save_template(Path(temp_dir), "../escape", command="list-profiles")

    def test_parse_template_args_uses_operator_style_quoting(self) -> None:
        self.assertEqual(
            parse_template_args('read --profile G65 --format markdown --note "manual review"'),
            ["read", "--profile", "G65", "--format", "markdown", "--note", "manual review"],
        )

    def test_parse_template_args_preserves_windows_paths(self) -> None:
        self.assertEqual(
            parse_template_args(r'read --workspace C:\repositories\trunk --workbook "C:\data files\size.xlsx"'),
            ["read", "--workspace", r"C:\repositories\trunk", "--workbook", r"C:\data files\size.xlsx"],
        )

    def test_payload_shape_is_json_serializable_and_has_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = save_template(Path(temp_dir), "profiles", command="list-profiles")

            text = json.dumps({"note": TEMPLATE_BANNER, "template": payload})

            self.assertIn("Templates are operator-local saved command configurations", text)

    def test_template_run_metadata_records_last_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            save_template(workspace, "profiles", command="list-profiles")

            payload = record_template_run(workspace, "profiles", outcome="ok")

            self.assertEqual(payload["name"], "profiles")
            self.assertEqual(payload["last_run_outcome"], "ok")
            self.assertIn("last_run_at", payload)
            self.assertEqual(list_templates(workspace)[0]["last_run_outcome"], "ok")

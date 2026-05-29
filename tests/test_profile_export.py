"""H-32 tests for the export-all-as-zip surface."""
from __future__ import annotations

import json
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

from sg_preflight.profile_export import (
    EXPORT_SCHEMA_VERSION,
    ExportManifestEntry,
    _filter_activity_log,
    _scrub_pat_tokens,
    _scrub_text_file,
    build_manifest,
    export_profile_evidence,
)


class ScrubbingTests(unittest.TestCase):
    def test_pat_tokens_mask_to_last_four(self) -> None:
        scrubbed, count = _scrub_pat_tokens("token=abcdef1234567890abcdef1234567890XYZW")
        self.assertEqual(count, 1)
        self.assertNotIn("abcdef1234567890abcdef1234567890XYZW", scrubbed)
        self.assertIn("****XYZW", scrubbed)

    def test_git_sha_is_left_alone(self) -> None:
        sha = "0123456789abcdef0123456789abcdef01234567"
        scrubbed, count = _scrub_pat_tokens(sha)
        self.assertEqual(count, 0)
        self.assertEqual(scrubbed, sha)

    def test_text_file_scrub_redacts_paths_and_tokens(self) -> None:
        sample = (
            r"Token: abcdef1234567890abcdef1234567890XYZW "
            r"Path: C:\Users\realname\repos\foo.txt"
        )
        scrubbed, count = _scrub_text_file(sample)
        self.assertGreaterEqual(count, 1)
        self.assertNotIn("realname", scrubbed)
        self.assertIn("<operator>", scrubbed)
        self.assertNotIn("abcdef1234567890abcdef1234567890XYZW", scrubbed)


class ActivityLogFilterTests(unittest.TestCase):
    def test_filter_keeps_only_matching_profile_and_recent_window(self) -> None:
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        recent_ts = (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
        old_ts = (now - timedelta(days=14)).isoformat().replace("+00:00", "Z")
        log = "\n".join([
            json.dumps({"ts": recent_ts, "profile": "F70", "verb": "ran", "surface": "full-qa-pass:run"}),
            json.dumps({"ts": recent_ts, "profile": "G70", "verb": "ran", "surface": "full-qa-pass:run"}),
            json.dumps({"ts": old_ts, "profile": "F70", "verb": "ran", "surface": "full-qa-pass:run"}),
            json.dumps({"ts": recent_ts, "profile": "f70", "verb": "ran", "surface": "full-qa-pass:run"}),
        ])
        cutoff = now - timedelta(days=7)
        kept = _filter_activity_log(log, profile_id="F70", since=cutoff).strip().split("\n")
        # Recent F70 + recent f70 (case-insensitive); old F70 dropped; G70 dropped.
        self.assertEqual(len(kept), 2)
        for line in kept:
            entry = json.loads(line)
            self.assertEqual(str(entry.get("profile")).strip().upper(), "F70")

    def test_filter_returns_empty_when_no_match(self) -> None:
        kept = _filter_activity_log("", profile_id="F70", since=None)
        self.assertEqual(kept, "")


class ExportRoundTripTests(unittest.TestCase):
    def _build_workspace(self, tmp: Path, profile: str = "G70") -> dict:
        """Seed a workspace + home so the exporter has something to pack."""
        from sg_preflight.full_qa_history import record_full_qa_run_history

        ws = tmp / "workspace"
        bmw_root = tmp / "bmw"
        home = tmp / "home"
        for path in (ws, bmw_root, home):
            path.mkdir(parents=True, exist_ok=True)
        (ws / "operator_state").mkdir(parents=True, exist_ok=True)

        # Activity log with one matching + one non-matching entry.
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        log_lines = [
            json.dumps({"ts": now_iso, "profile": profile, "verb": "ran", "surface": "full-qa-pass:run", "outcome": "ok", "note": ""}),
            json.dumps({"ts": now_iso, "profile": "OTHER", "verb": "ran", "surface": "full-qa-pass:run", "outcome": "ok", "note": ""}),
        ]
        (ws / "operator_state" / "activity_log.jsonl").write_text(
            "\n".join(log_lines) + "\n", encoding="utf-8"
        )

        # Run history with two runs.
        for index in range(2):
            record_full_qa_run_history(
                profile,
                {"status": "incomplete", "summary": f"run {index}", "steps": [{"status": "passed"}], "risk_score": 20 + index},
                home=home,
                completed_at_utc=f"2026-05-29T0{index}:00:00Z",
            )

        # Workbook in the date-stamped slot.
        wb_dir = ws / "Cars" / "size_analysis"
        wb_dir.mkdir(parents=True, exist_ok=True)
        wb_path = wb_dir / f"{profile}_20260529.xlsx"
        wb_path.write_bytes(b"PK\x03\x04 synthetic xlsx bytes for tests")

        # Screenshot review dir.
        review_dir = home / "sgfx_outputs" / profile.lower() / "screenshot-review"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "01-front.png").write_bytes(b"\x89PNG\r\n\x1a\n synthetic png 1")
        (review_dir / "02-side.png").write_bytes(b"\x89PNG\r\n\x1a\n synthetic png 2")

        return {"workspace": ws, "bmw_root": bmw_root, "home": home}

    def test_export_writes_all_expected_archive_members(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = self._build_workspace(Path(tmp), profile="G70")
            zip_path = Path(tmp) / "export.zip"
            result = export_profile_evidence(
                profile_id="G70",
                workspace=seed["workspace"],
                bmw_root=seed["bmw_root"],
                output_path=zip_path,
                home=seed["home"],
                build_commit="abcd123",
                exe_sha256="dead" * 16,
                summary_html='<html><body><h1>SGFX profile summary — G70</h1></body></html>',
            )
            self.assertTrue(zip_path.is_file())
            with zipfile.ZipFile(zip_path, "r") as zf:
                names = set(zf.namelist())
                self.assertIn("summary.html", names)
                self.assertIn("activity_log.jsonl", names)
                self.assertIn("full_qa_history.json", names)
                self.assertIn("manifest.json", names)
                # Workbook lands under delivery-workbook/.
                self.assertTrue(any(n.startswith("delivery-workbook/") for n in names))
                # Screenshots land under screenshot-review/.
                self.assertTrue(any(n.startswith("screenshot-review/") for n in names))
                manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
                self.assertEqual(manifest["schema_version"], EXPORT_SCHEMA_VERSION)
                self.assertEqual(manifest["profile_id"], "G70")
                # Activity log filter only kept G70 entries.
                log = zf.read("activity_log.jsonl").decode("utf-8")
                self.assertIn('"profile":', log)
                self.assertIn("G70", log)
                self.assertNotIn("OTHER", log)
                # Manifest sanitization log mentions activity_log filter.
                self.assertTrue(
                    any("activity_log" in entry for entry in manifest["sanitization_log"]),
                    manifest["sanitization_log"],
                )

    def test_export_sanitizes_pat_tokens_in_summary_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = self._build_workspace(Path(tmp))
            zip_path = Path(tmp) / "export.zip"
            html = (
                "<html><body>"
                "<p>Token=abcdef1234567890abcdef1234567890XYZW</p>"
                r"<p>C:\Users\someuser\repos</p>"
                "</body></html>"
            )
            result = export_profile_evidence(
                profile_id="G70",
                workspace=seed["workspace"],
                output_path=zip_path,
                home=seed["home"],
                summary_html=html,
            )
            with zipfile.ZipFile(zip_path, "r") as zf:
                scrubbed_html = zf.read("summary.html").decode("utf-8")
            self.assertNotIn("abcdef1234567890abcdef1234567890XYZW", scrubbed_html)
            self.assertIn("****XYZW", scrubbed_html)
            self.assertNotIn("someuser", scrubbed_html)
            self.assertIn("<operator>", scrubbed_html)

    def test_export_manifest_records_each_member_with_byte_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            seed = self._build_workspace(Path(tmp))
            zip_path = Path(tmp) / "export.zip"
            result = export_profile_evidence(
                profile_id="G70",
                workspace=seed["workspace"],
                output_path=zip_path,
                home=seed["home"],
                summary_html="<html><body>x</body></html>",
            )
            payload = result.to_payload()
            self.assertEqual(payload["profile_id"], "G70")
            archive_names = {e["archive_name"] for e in payload["entries"]}
            self.assertIn("summary.html", archive_names)
            self.assertIn("activity_log.jsonl", archive_names)
            # Every entry has a non-negative byte count.
            for entry in payload["entries"]:
                self.assertGreaterEqual(entry["bytes"], 0)

    def test_profile_export_zip_manifest_redacts_personal_paths(self) -> None:
        manifest = build_manifest(
            profile_id="G70",
            generated_at_utc="2026-05-29T21:30:00Z",
            build_commit="abcd123",
            exe_sha256="dead" * 16,
            entries=[
                ExportManifestEntry(
                    archive_name="full_qa_history.json",
                    source_path=r"C:\Users\someoperator\sgfx_outputs\g70\run_history.json",
                    bytes=128,
                    sanitized=False,
                ),
                ExportManifestEntry(
                    archive_name="notes.txt",
                    source_path=r"C:\Users\someoperator\Documents\notes.txt",
                    bytes=64,
                    sanitized=False,
                ),
            ],
            sanitization_log=[],
        )
        manifest_text = json.dumps(manifest)
        self.assertIsNone(re.search(r"(?i)[A-Z]:\\Users\\[^\\]+\\", manifest_text))
        source_paths = [entry["source_path"] for entry in manifest["entries"]]
        self.assertIn(r"~\sgfx_outputs\g70\run_history.json", source_paths)
        self.assertIn(r"<operator-home>\Documents\notes.txt", source_paths)


if __name__ == "__main__":
    unittest.main()

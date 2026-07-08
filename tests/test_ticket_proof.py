from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from sg_preflight.ticket_proof import PROOF_THEMES, build_ticket_proof, render_proof_html


def _make_rca(path: Path, external_projects: dict | None) -> None:
    payload: dict = {"racoVersion": "2.9.0", "instances": []}
    if external_projects is not None:
        payload["externalProjects"] = external_projects
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("project.json", json.dumps(payload))


def _make_ramses(path: Path, version: str, level: str) -> None:
    header = (
        f"[RamsesVersion:{version}]".encode("ascii")
        + b"\x00\x01"
        + b"[GitHash:abc123]"
        + b"\x00\x02"
        + f"[FeatureLevel:{level}]".encode("ascii")
        + b"\x00" * 16
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header)


class TestTicketProof(unittest.TestCase):
    def test_render_proof_html_is_self_contained_and_interactive(self) -> None:
        payload = {
            "title": "Delivery preflight evidence",
            "ticket": "IDCEVODEV-000000",
            "generated_at_utc": "2026-07-08T02:00:00+00:00",
            "intro": "Collected live.",
            "sections": [
                {
                    "heading": "Board <state>",
                    "note": "One row per item.",
                    "keyvals": [("Items scanned", 2), ("Connection", "available")],
                    "table": {
                        "columns": ["Item", "Status"],
                        "tone_columns": ["Status"],
                        "rows": [
                            {"Item": "F70 & friends", "Status": "Delivered"},
                            {"Item": "G65", "Status": "Not delivered yet"},
                        ],
                    },
                    "pre": "line one\nline two",
                }
            ],
            "provenance": {"Workspace": r"C:\somewhere"},
        }

        html_text = render_proof_html(payload)

        self.assertIn("Board &lt;state&gt;", html_text)
        self.assertIn("F70 &amp; friends", html_text)
        self.assertIn("chip good", html_text)
        self.assertIn("chip warn", html_text)
        self.assertIn("table.sortable", html_text)
        self.assertIn("input.filter", html_text)
        self.assertIn("does not replace reviewer sign-off", html_text)
        self.assertNotIn("src='http", html_text)
        self.assertNotIn("href='http", html_text)

    def test_build_ticket_proof_writes_html_and_json_for_manual_review_theme(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            output_root = Path(temp_dir) / "proofs"

            result = build_ticket_proof(
                "manual-review",
                ticket="IDCEVODEV-000000",
                workspace=workspace,
                output_root=output_root,
            )

            html_path = Path(result["html_path"])
            json_path = Path(result["json_path"])
            self.assertTrue(html_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("IDCEVODEV-000000", html_path.name)
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["theme"], "manual-review")
            headings = [section["heading"] for section in payload["sections"]]
            self.assertIn("Reviewer toolchain readiness", headings)

    def test_build_ticket_proof_rejects_unknown_theme(self) -> None:
        with self.assertRaises(ValueError):
            build_ticket_proof("nonsense", ticket="IDCEVODEV-000000")

    def test_delivery_proof_includes_reference_integrity_sections(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir) / "workspace"
            repo = workspace / "digital-3d-car-models"
            _make_rca(repo / "_Shared" / "Cam" / "Cam.rca", None)
            _make_rca(repo / "cars" / "A" / "A.rca", {"u1": {"name": "Cam", "path": "../../_Shared/Cam/Cam.rca"}})
            _make_rca(repo / "cars" / "B" / "B.rca", {"u2": {"name": "Gone", "path": "../../_Shared/Gone/Gone.rca"}})
            _make_ramses(repo / "cars" / "A" / "export" / "exported.ramses", "28.15.1", "1")
            _make_ramses(repo / "cars" / "B" / "export" / "exported.ramses", "28.15.1", "2")

            result = build_ticket_proof("delivery", ticket="IDCEVODEV-977874", workspace=workspace)

        sections = {s["heading"]: s for s in result["payload"]["sections"]}
        self.assertIn("RaCo external-project references", sections)
        self.assertIn("RAMSES export consistency", sections)

        rca = dict(sections["RaCo external-project references"]["keyvals"])
        self.assertEqual(rca["References broken"], 1)
        self.assertEqual(rca["References resolved"], 1)
        self.assertEqual(len(sections["RaCo external-project references"]["table"]["rows"]), 1)

        ramses = dict(sections["RAMSES export consistency"]["keyvals"])
        self.assertEqual(ramses["Feature levels"], "1, 2")

    def test_all_registered_themes_have_titles(self) -> None:
        for theme, (title, builder) in PROOF_THEMES.items():
            self.assertTrue(title)
            self.assertTrue(callable(builder), theme)


if __name__ == "__main__":
    unittest.main()

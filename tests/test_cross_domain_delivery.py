from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from sg_preflight.cross_domain_delivery import (
    build_cross_domain_delivery_board,
    cross_domain_delivery_markdown,
    write_cross_domain_delivery_board,
)
from sg_preflight.delivery_readiness import STATUS_DELIVERED, STATUS_NOT_DELIVERED_YET, STATUS_UNKNOWN


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _changelog(header: str, *, ramses: str = "", raco: str = "", logic: str = "", feature: str = "", api: str = "") -> str:
    metadata = []
    if raco:
        metadata.append(f"> _Ramses Composer / Headless: {raco}_")
    if ramses:
        metadata.append(f"> _Ramses: {ramses}_")
    if logic:
        metadata.append(f"> _Ramses Logic: {logic}_")
    if feature:
        metadata.append(f"> _Feature Level: {feature}_")
    if api:
        metadata.append(f"> _API version: {api}_")
    return "\n".join([header, "", *metadata, "", "- fixture entry", ""])


def _cross_domain_fixture(root: Path) -> Path:
    repo = root / "repositories" / "trunk"
    _write_text(
        repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md",
        _changelog(
            "## [3.4.0] - 2026-06-01",
            ramses="28.0.0",
            raco="2.9.0",
            logic="1.18.0",
            feature="2026.2",
            api="14",
        ),
    )
    _write_text(
        repo / "Cars" / "BMW" / "F70" / "README.md",
        "\n".join(
            (
                "# F70",
                "",
                "## Interfaces Overview",
                "- DoorsInterface",
                "- LightsInterface",
                "",
                "## Notes",
                "- not counted",
            )
        ),
    )
    _write_bytes(repo / "Cars" / "BMW" / "F70" / "export" / "Export_F70.rca", b"car-rca")

    _write_text(
        repo / "Widgets" / "BMW" / "ClockWidget" / "Main" / "CHANGELOG.md",
        _changelog(
            "## [1.5.0] - To be delivered",
            ramses="27.0.0",
            raco="2.8.0",
            logic="1.17.0",
            feature="2025.4",
            api="13",
        ),
    )
    _write_text(
        repo / "Widgets" / "BMW" / "ClockWidget" / "Main" / "README.md",
        "## Interfaces Overview\n- ClockIn\n",
    )
    _write_bytes(repo / "Widgets" / "BMW" / "ClockWidget" / "Main" / "ClockWidget.rca", b"widget")

    (repo / "Widgets" / "MINI" / "NoLogWidget" / "Main").mkdir(parents=True)
    _write_bytes(repo / "Widgets" / "MINI" / "NoLogWidget" / "Main" / "NoLogWidget.rca", b"nolog")

    _write_text(
        repo / "AmbientLayer" / "BMW_Default" / "CHANGELOG.md",
        _changelog(
            "## [4.0.0] - NOT YET DELIVERED",
            ramses="28.0.0",
            raco="2.9.0",
            logic="1.18.0",
            feature="2026.2",
            api="14",
        ),
    )
    _write_text(
        repo / "AmbientLayer" / "BMW_Default" / "README.md",
        "## Interfaces Overview\n- AmbientColor\n- AmbientIntensity\n",
    )
    _write_bytes(repo / "AmbientLayer" / "BMW_Default" / "export_ECE" / "ambient_ece.rca", b"ece")
    _write_bytes(repo / "AmbientLayer" / "BMW_Default" / "export_US" / "ambient_us.rca", b"usdata")

    return repo


class TestCrossDomainDelivery(unittest.TestCase):
    def test_board_scans_cars_widgets_and_ambient_with_version_drift_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _cross_domain_fixture(root)
            board = build_cross_domain_delivery_board(
                repo,
                workspace_root=root,
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        entries = {entry["relative_path"]: entry for entry in payload["entries"]}
        self.assertEqual(payload["source_state"], "ready")
        self.assertEqual(payload["generated_at_utc"], "2026-06-18T20:45:00+00:00")
        self.assertEqual(payload["domains"], ["cars", "widgets", "ambient"])
        self.assertEqual(payload["counts"]["total"], 4)
        self.assertEqual(payload["counts"]["by_domain"]["cars"]["total"], 1)
        self.assertEqual(payload["counts"]["by_domain"]["widgets"]["total"], 2)
        self.assertEqual(payload["counts"]["by_domain"]["ambient"]["total"], 1)
        self.assertEqual(payload["counts"]["by_domain"]["widgets"]["unknown"], 1)
        self.assertEqual(payload["counts"][STATUS_DELIVERED], 1)
        self.assertEqual(payload["counts"][STATUS_NOT_DELIVERED_YET], 2)
        self.assertEqual(payload["counts"][STATUS_UNKNOWN], 1)

        car = entries["Cars/BMW/F70"]
        self.assertEqual(car["domain"], "cars")
        self.assertEqual(car["brand"], "BMW")
        self.assertEqual(car["item_id"], "F70")
        self.assertEqual(car["delivery_status"], STATUS_DELIVERED)
        self.assertEqual(car["delivery_status_label"], "Delivered")
        self.assertEqual(car["version"], "3.4.0")
        self.assertEqual(car["delivered_date"], "2026-06-01")
        self.assertEqual(car["ramses"], "28.0.0")
        self.assertEqual(car["raco_headless"], "2.9.0")
        self.assertEqual(car["ramses_logic"], "1.18.0")
        self.assertEqual(car["feature_level"], "2026.2")
        self.assertEqual(car["api_version"], "14")
        self.assertEqual(car["rca_total_bytes"], len(b"car-rca"))
        self.assertEqual(car["interfaces_summary"], "2 interface bullet(s) under Interfaces Overview.")

        widget = entries["Widgets/BMW/ClockWidget"]
        self.assertEqual(widget["delivery_status"], STATUS_NOT_DELIVERED_YET)
        self.assertEqual(widget["ramses"], "27.0.0")
        self.assertEqual(widget["raco_headless"], "2.8.0")
        self.assertEqual(widget["interfaces_summary"], "1 interface bullet(s) under Interfaces Overview.")

        no_changelog = entries["Widgets/MINI/NoLogWidget"]
        self.assertFalse(no_changelog["has_changelog"])
        self.assertEqual(no_changelog["delivery_status"], STATUS_UNKNOWN)
        self.assertEqual(no_changelog["delivery_status_label"], "No changelog")
        self.assertIn("No CHANGELOG.md", no_changelog["notes"])

        ambient = entries["AmbientLayer/BMW_Default"]
        self.assertEqual(ambient["domain"], "ambient")
        self.assertEqual(ambient["brand"], "")
        self.assertEqual(ambient["item_id"], "BMW_Default")
        self.assertEqual(ambient["delivery_status"], STATUS_NOT_DELIVERED_YET)
        self.assertEqual(ambient["rca_total_bytes"], len(b"ece") + len(b"usdata"))
        self.assertEqual(len(ambient["rca_paths"]), 2)

        drift = payload["counts"]["version_drift"]
        self.assertEqual(drift["max_ramses"], "28.0.0")
        self.assertEqual(drift["max_raco_headless"], "2.9.0")
        self.assertEqual(drift["ramses_drift_count"], 1)
        self.assertEqual(drift["raco_headless_drift_count"], 1)
        self.assertEqual(drift["items"][0]["relative_path"], "Widgets/BMW/ClockWidget")

    def test_version_metadata_falls_back_to_newest_section_with_a_block(self) -> None:
        changelog = "\n".join(
            (
                "# [BMW] Ambient Layer Default - CHANGELOG",
                "",
                "## [9.0.1] - NOT YET DELIVERED",
                "",
                "### Fixed",
                "",
                "* Updated Scene ID Numbers in Export Scenes",
                "",
                "## [9.0.0] - 2026-04-29",
                "",
                "### Changed",
                "",
                "* Upgraded the project to RaCo 2.9.0 and Feature Level 4",
                "",
                "> _Ramses Composer / Headless: 2.9.0_  ",
                "> _Ramses: 28.15.1_  ",
                "> _Ramses Logic: 28.15.1_  ",
                ">",
                "> _Feature Level: 4_  ",
                "",
                "---",
                "## [8.0.0] - 2026-01-16",
                "",
                "> _Ramses Composer / Headless: 2.8.0_  ",
                "> _Ramses: 28.14.0_  ",
                "",
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_text(repo / "AmbientLayer" / "BMW_Default" / "CHANGELOG.md", changelog)
            board = build_cross_domain_delivery_board(
                repo,
                workspace_root=root,
                domains=("ambient",),
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        ambient = {entry["relative_path"]: entry for entry in payload["entries"]}["AmbientLayer/BMW_Default"]
        # latest [9.0.1] hotfix has no version block; metadata must come from the newest
        # section that carries one ([9.0.0]) - not [8.0.0], and the blank `>` line must not truncate it.
        self.assertEqual(ambient["delivery_status"], STATUS_NOT_DELIVERED_YET)
        self.assertEqual(ambient["ramses"], "28.15.1")
        self.assertEqual(ambient["raco_headless"], "2.9.0")
        self.assertEqual(ambient["ramses_logic"], "28.15.1")
        self.assertEqual(ambient["feature_level"], "4")
        # recovered version must feed the drift evidence, not be silently excluded from scope max
        self.assertEqual(payload["counts"]["version_drift"]["max_ramses"], "28.15.1")
        self.assertEqual(payload["counts"]["version_drift"]["max_raco_headless"], "2.9.0")

    def test_empty_value_metadata_line_does_not_block_the_version_fallback(self) -> None:
        changelog = "\n".join(
            (
                "## [9.0.1] - NOT YET DELIVERED",
                "",
                "> _Ramses:_",
                "",
                "## [9.0.0] - 2026-04-29",
                "",
                "> _Ramses Composer / Headless: 2.9.0_",
                "> _Ramses: 28.15.1_",
                "",
            )
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_text(repo / "AmbientLayer" / "BMW_Default" / "CHANGELOG.md", changelog)
            board = build_cross_domain_delivery_board(
                repo,
                workspace_root=root,
                domains=("ambient",),
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        ambient = {entry["relative_path"]: entry for entry in payload["entries"]}["AmbientLayer/BMW_Default"]
        # the empty `> _Ramses:_` placeholder must not count as a version; fall through to the real block
        self.assertEqual(ambient["ramses"], "28.15.1")
        self.assertEqual(ambient["raco_headless"], "2.9.0")
        self.assertEqual(payload["counts"]["version_drift"]["max_ramses"], "28.15.1")

    def test_cosmetic_version_string_variance_is_not_flagged_as_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "repositories" / "trunk"
            _write_text(
                repo / "Cars" / "BMW" / "F70" / "CHANGELOG.md",
                _changelog("## [1.0.0] - 2026-01-01", ramses="28.0.0", raco="2.9.0"),
            )
            _write_text(
                repo / "Cars" / "BMW" / "F80" / "CHANGELOG.md",
                _changelog("## [1.0.0] - 2026-01-01", ramses="28.00.0", raco="2.9.0"),
            )
            board = build_cross_domain_delivery_board(
                repo,
                workspace_root=root,
                domains=("cars",),
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )

        drift = board.to_dict()["counts"]["version_drift"]
        # 28.0.0 and 28.00.0 are the same version; neither item should be flagged against the max
        self.assertEqual(drift["ramses_drift_count"], 0)
        self.assertEqual(drift["raco_headless_drift_count"], 0)

    def test_board_survives_an_unreadable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _cross_domain_fixture(root)
            real_iterdir = Path.iterdir

            def guarded_iterdir(self):  # type: ignore[no-untyped-def]
                if self.name == "MINI":
                    raise PermissionError("access denied")
                return real_iterdir(self)

            with mock.patch.object(Path, "iterdir", guarded_iterdir):
                board = build_cross_domain_delivery_board(
                    repo,
                    workspace_root=root,
                    now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
                )

        payload = board.to_dict()
        # the unreadable MINI dir is skipped, the rest of the board still builds
        self.assertEqual(payload["source_state"], "ready")
        relative_paths = {entry["relative_path"] for entry in payload["entries"]}
        self.assertIn("Cars/BMW/F70", relative_paths)
        self.assertNotIn("Widgets/MINI/NoLogWidget", relative_paths)

    def test_missing_repo_root_returns_empty_read_only_board(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            board = build_cross_domain_delivery_board(
                root / "missing-trunk",
                workspace_root=root,
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )

        payload = board.to_dict()
        self.assertEqual(payload["source_state"], "missing")
        self.assertEqual(payload["entries"], [])
        self.assertEqual(payload["counts"]["total"], 0)
        self.assertFalse(payload["counts"]["version_drift"]["items"])
        self.assertIn("Evidence only", payload["manual_review_banner"])

    def test_writes_json_and_markdown_with_all_domains_and_drift_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _cross_domain_fixture(root)
            board = build_cross_domain_delivery_board(
                repo,
                workspace_root=root,
                now=datetime(2026, 6, 18, 20, 45, tzinfo=timezone.utc),
            )
            output_root = root / "out" / "cross-domain"

            artifacts = write_cross_domain_delivery_board(board, output_root)

            json_payload = json.loads(Path(artifacts["json_path"]).read_text(encoding="utf-8"))
            markdown = Path(artifacts["markdown_path"]).read_text(encoding="utf-8")
            json_exists = (output_root / "cross-domain-delivery.json").exists()
            markdown_exists = (output_root / "cross-domain-delivery.md").exists()

        self.assertEqual(json_payload["counts"]["total"], 4)
        self.assertTrue(json_exists)
        self.assertTrue(markdown_exists)
        self.assertEqual(markdown, cross_domain_delivery_markdown(board))
        self.assertIn("# Cross-Domain Delivery & Version Board", markdown)
        self.assertIn("Cars/BMW/F70", markdown)
        self.assertIn("Widgets/BMW/ClockWidget", markdown)
        self.assertIn("AmbientLayer/BMW_Default", markdown)
        self.assertIn("Widgets/MINI/NoLogWidget", markdown)
        self.assertIn("Version Drift Evidence", markdown)
        self.assertIn("Ramses max: 28.0.0", markdown)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from sg_preflight.bmw_git_readiness import (
    BMW_GIT_READINESS_BANNER,
    bmw_git_readiness_digest_items,
    read_bmw_git_readiness,
    render_bmw_git_readiness_markdown,
)
from sg_preflight.daily_digest import build_daily_digest
from tests.operator_helpers import write_text


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


def _init_bmw_repo(root: Path, *, brand: str = "BMW", profile: str = "G65_EVO") -> Path:
    repo = root / "digital-3d-car-models"
    car_root = repo / "cars" / brand / profile
    write_text(repo / "cars" / brand / "README_IDCevo.md", "brand readme\n")
    write_text(car_root / "README.md", "profile readme\n")
    write_text(car_root / "_Workfiles" / ".keep", "\n")
    main_stem = profile[:-4] if profile.endswith("_EVO") else profile
    write_text(car_root / "main" / f"Main_{main_stem}.rca", "scene\n")
    write_text(car_root / "export" / "tests" / "test_config.lua", "-- screenshot config\n")
    write_text(car_root / "perspectives_CID180_LHD.json", "{}\n")
    write_text(car_root / "CHANGELOG.md", "# Changelog\n")
    write_text(car_root / "lids.json", "{}\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    _git(repo, "config", "user.name", "David Erik Garcia Arena")
    _git(repo, "config", "user.email", "88119698+Hawaiiiiii@users.noreply.github.com")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture profile")
    return repo


class TestBmwGitReadiness(unittest.TestCase):
    def test_read_bmw_git_readiness_reports_profile_checks_and_latest_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _init_bmw_repo(root)

            payload = read_bmw_git_readiness("G65", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["data_available"])
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertEqual(payload["brand"], "BMW")
        self.assertEqual(Path(payload["repo_root"]), repo.resolve())
        self.assertTrue(payload["readme_present"])
        self.assertTrue(payload["workfiles_present"])
        self.assertTrue(payload["main_scene_present"])
        self.assertTrue(payload["test_config_present"])
        self.assertTrue(payload["perspectives_present"])
        self.assertTrue(payload["changelog_present"])
        self.assertTrue(payload["lids_json_present"])
        self.assertTrue(payload["latest_commit"]["sha"])
        self.assertTrue(payload["latest_commit"]["short_sha"])
        self.assertIn("read-only", payload["note"].lower())
        self.assertFalse(payload["is_approval"])
        self.assertNotIn("approved", payload["note"].lower())

    def test_read_bmw_git_readiness_resolves_mini_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_bmw_repo(root, brand="MINI", profile="F66")

            payload = read_bmw_git_readiness("F66", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["brand"], "MINI")
        self.assertEqual(payload["matched_profile_id"], "F66")
        self.assertTrue(payload["main_scene_present"])
        self.assertFalse(payload["is_approval"])

    def test_read_bmw_git_readiness_reports_missing_root_without_throwing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_root = Path(temp_dir) / "missing-digital-3d-car-models"
            payload = read_bmw_git_readiness("G65", workspace=Path(temp_dir), bmw_root=missing_root)

        self.assertEqual(payload["status"], "no_bmw_root")
        self.assertFalse(payload["data_available"])
        self.assertEqual(payload["latest_commit"]["sha"], "")
        self.assertIn("not found", payload["summary"].lower())
        self.assertFalse(payload["is_approval"])

    def test_read_bmw_git_readiness_reports_missing_profile_without_hiding_repo(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_bmw_repo(root, profile="G65_EVO")

            payload = read_bmw_git_readiness("G70", workspace=root)

        self.assertEqual(payload["status"], "no_profile_folder")
        self.assertFalse(payload["data_available"])
        self.assertTrue(payload["repo_root"])
        self.assertIn("profile folder", payload["summary"].lower())

    def test_read_bmw_git_readiness_does_not_treat_empty_path_as_present(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = root / "digital-3d-car-models"
            write_text(repo / "cars" / "MINI" / "F67" / ".keep", "\n")
            subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
            _git(repo, "config", "user.name", "David Erik Garcia Arena")
            _git(repo, "config", "user.email", "88119698+Hawaiiiiii@users.noreply.github.com")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "fixture minimal profile")

            payload = read_bmw_git_readiness("F67", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["brand"], "MINI")
        self.assertFalse(payload["readme_present"])
        self.assertFalse(payload["main_scene_present"])
        self.assertFalse(payload["test_config_present"])
        self.assertFalse(payload["perspectives_present"])
        self.assertEqual(payload["main_scene_path"], "")
        checks = {item["key"]: item for item in payload["readiness_checks"]}
        self.assertEqual(checks["readme"]["status"], "missing")
        self.assertEqual(checks["main_scene"]["status"], "missing")

    def test_bmw_git_readiness_markdown_starts_with_read_only_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _init_bmw_repo(root)
            payload = read_bmw_git_readiness("G65", workspace=root)

        markdown = render_bmw_git_readiness_markdown(payload)

        self.assertTrue(markdown.startswith(BMW_GIT_READINESS_BANNER))
        self.assertIn("SGFX does not write to BMW Git or fetch from the remote.", markdown)
        self.assertIn("Main scene", markdown)
        self.assertIn("Manual review remains required.", markdown)
        self.assertNotIn("approved", markdown.lower())

    def test_daily_digest_surfaces_bmw_git_readiness_as_distinct_evidence_source(self) -> None:
        readiness_payload = {
            "profile_id": "G65",
            "matched_profile_id": "G65_EVO",
            "brand": "BMW",
            "status": "available",
            "data_available": True,
            "repo_root": "C:/3D Car git/digital-3d-car-models",
            "profile_path": "C:/3D Car git/digital-3d-car-models/cars/BMW/G65_EVO",
            "available_check_count": 7,
            "check_count": 8,
            "summary": "G65_EVO readiness: 7 of 8 checks present.",
            "note": "Read-only BMW Git per-profile readiness surface. SGFX does not write to BMW Git or fetch from the remote.",
            "is_approval": False,
        }

        digest = build_daily_digest(
            {
                "ticket_id": "IDCEVODEV-977874",
                "scope": ["G65"],
                "daily_snapshot_summary": {"smoke_completed": 0, "smoke_total": 0},
                "screenshot_battery_counts": {"total": 0},
                "daily_delta_summary": {},
                "daily_delta": {},
                "review_owner_decisions": {"sections": []},
                "manual_review_profiles": [],
                "bmw_git_readiness": [readiness_payload],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
            }
        )

        evidence_items = digest["sections"]["evidence_prepared"]["items"]
        readiness_items = [item for item in evidence_items if item.get("source") == "bmw_git_readiness"]

        self.assertEqual(len(readiness_items), 1)
        self.assertEqual(readiness_items[0]["label"], "BMW Git readiness G65_EVO")
        self.assertIn("7 of 8", readiness_items[0]["detail"])
        self.assertIn("BMW Git readiness G65_EVO", digest["markdown"])
        self.assertFalse(readiness_items[0]["is_approval"])
        self.assertNotIn("approved", readiness_items[0]["note"].lower())
        self.assertEqual(
            bmw_git_readiness_digest_items({"bmw_git_readiness": [readiness_payload]})[0]["source"],
            "bmw_git_readiness",
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sg_preflight.daily_digest import build_daily_digest
from sg_preflight.qa_hero_readiness import (
    QA_HERO_READINESS_BANNER,
    QA_HERO_READINESS_NOTE,
    qa_hero_readiness_digest_items,
    read_qa_hero_readiness,
    render_qa_hero_readiness_markdown,
)
from tests.operator_helpers import write_text


def _write_full_profile_fixture(root: Path, *, brand: str = "BMW", profile: str = "G65_EVO") -> Path:
    repo = root / "digital-3d-car-models"
    brand_root = repo / "cars" / brand
    car_root = brand_root / profile
    stem = profile[:-4] if profile.endswith("_EVO") else profile
    write_text(brand_root / "CarPaint.json", '{"paints": [{"id": "black"}, {"id": "white"}]}\n')
    write_text(car_root / "resources" / f"RES_{stem}_LightFX" / f"RES_{stem}_LightFX.rca", "lightfx\n")
    write_text(car_root / "resources" / f"RES_{stem}_LightFX" / "meshes" / "O_light.glb", "mesh\n")
    write_text(car_root / "resources" / f"RES_{stem}_WelcomeFX" / f"RES_{stem}_WelcomeFX.rca", "welcomefx\n")
    write_text(car_root / "resources" / f"RES_{stem}_WelcomeFX" / "meshes" / "O_welcome.glb", "mesh\n")
    write_text(car_root / "resources" / f"RES_{stem}_ShadesFX" / f"RES_{stem}_ShadesFX.rca", "shadesfx\n")
    write_text(car_root / "resources" / f"RES_{stem}_ShadesFX" / "meshes" / "O_shade.glb", "mesh\n")
    write_text(car_root / "resources" / f"RES_{stem}_AnchorPoints" / f"RES_{stem}_AnchorPoints.rca", "anchors\n")
    write_text(car_root / "resources" / f"RES_{stem}_AnchorPoints" / "meshes" / "O_common_Gizmo.gltf", "mesh\n")
    write_text(car_root / "_Common" / "constants" / f"README_constants_{stem}.md", "# constants\n")
    write_text(car_root / "_Common" / "constants" / "scripts" / f"Module_constants_{stem}.lua", "constants = {}\n")
    write_text(car_root / "perspectives_CID180_LHD.json", "{}\n")
    write_text(car_root / "perspectives_CID180_RHD.json", "{}\n")
    return repo


class TestQaHeroReadiness(unittest.TestCase):
    def test_read_qa_hero_readiness_reports_subsystem_presence_counts_and_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            repo = _write_full_profile_fixture(root)

            payload = read_qa_hero_readiness("G65", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["data_available"])
        self.assertEqual(payload["profile_id"], "G65")
        self.assertEqual(payload["matched_profile_id"], "G65_EVO")
        self.assertEqual(payload["brand"], "BMW")
        self.assertEqual(Path(payload["repo_root"]), repo.resolve())
        self.assertEqual(payload["available_count"], 7)
        self.assertEqual(payload["total_count"], 7)
        self.assertFalse(payload["is_approval"])
        self.assertEqual(payload["note"], QA_HERO_READINESS_NOTE)
        self.assertNotIn("approved", payload["note"].lower())
        subsystems = {item["key"]: item for item in payload["subsystems"]}
        self.assertEqual(subsystems["lightfx"]["status"], "present")
        self.assertEqual(subsystems["lightfx"]["file_count"], 2)
        self.assertEqual(subsystems["welcomefx"]["status"], "present")
        self.assertEqual(subsystems["shadesfx"]["status"], "present")
        self.assertEqual(subsystems["anchor_points"]["status"], "present")
        self.assertEqual(subsystems["anchor_points"]["file_count"], 2)
        self.assertEqual(subsystems["constants"]["status"], "present")
        self.assertEqual(subsystems["perspectives"]["count"], 2)
        self.assertEqual(subsystems["carpaint"]["paint_count"], 2)

    def test_read_qa_hero_readiness_reports_missing_subsystems_without_hiding_profile_folder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            car_root = root / "digital-3d-car-models" / "cars" / "BMW" / "G70_EVO"
            car_root.mkdir(parents=True)

            payload = read_qa_hero_readiness("G70", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertTrue(payload["data_available"])
        self.assertEqual(payload["matched_profile_id"], "G70_EVO")
        self.assertEqual(payload["available_count"], 0)
        self.assertEqual(payload["total_count"], 7)
        self.assertTrue(payload["profile_path"])
        self.assertTrue(all(item["status"] == "missing" for item in payload["subsystems"]))
        self.assertFalse(payload["is_approval"])

    def test_read_qa_hero_readiness_resolves_mini_profiles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_full_profile_fixture(root, brand="MINI", profile="F66")

            payload = read_qa_hero_readiness("F66", workspace=root)

        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["brand"], "MINI")
        self.assertEqual(payload["matched_profile_id"], "F66")
        self.assertEqual(payload["available_count"], 7)
        self.assertFalse(payload["is_approval"])

    def test_read_qa_hero_readiness_reports_missing_bmw_root_and_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            missing_root = root / "missing-digital-3d-car-models"

            missing_root_payload = read_qa_hero_readiness("G65", workspace=root, bmw_root=missing_root)
            repo = root / "digital-3d-car-models"
            (repo / "cars" / "BMW").mkdir(parents=True)
            missing_profile_payload = read_qa_hero_readiness("G65", workspace=root)

        self.assertEqual(missing_root_payload["status"], "no_bmw_root")
        self.assertFalse(missing_root_payload["data_available"])
        self.assertIn("not found", missing_root_payload["summary"].lower())
        self.assertEqual(missing_profile_payload["status"], "no_profile_folder")
        self.assertFalse(missing_profile_payload["data_available"])
        self.assertIn("profile folder", missing_profile_payload["summary"].lower())

    def test_qa_hero_readiness_markdown_starts_with_read_only_banner(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_full_profile_fixture(root)
            payload = read_qa_hero_readiness("G65", workspace=root)

        markdown = render_qa_hero_readiness_markdown(payload)

        self.assertTrue(markdown.startswith(QA_HERO_READINESS_BANNER))
        self.assertIn("Manual review remains required.", markdown)
        self.assertIn("LightFX resources", markdown)
        self.assertIn("WelcomeFX resources", markdown)
        self.assertIn("ShadesFX resources", markdown)
        self.assertNotIn("approved", markdown.lower())
        self.assertNotIn("validated", markdown.lower())

    def test_daily_digest_surfaces_qa_hero_readiness_as_distinct_evidence_source(self) -> None:
        payload = {
            "profile_id": "G65",
            "matched_profile_id": "G65_EVO",
            "brand": "BMW",
            "status": "available",
            "data_available": True,
            "profile_path": "C:/3D Car git/digital-3d-car-models/cars/BMW/G65_EVO",
            "available_count": 6,
            "total_count": 7,
            "summary": "G65_EVO QA Hero readiness: 6 of 7 subsystems present.",
            "note": QA_HERO_READINESS_NOTE,
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
                "qa_hero_readiness": [payload],
                "artifact_references": {},
                "top_review_priority_items": [],
                "open_items": [],
            }
        )

        evidence_items = digest["sections"]["evidence_prepared"]["items"]
        readiness_items = [item for item in evidence_items if item.get("source") == "qa_hero_readiness"]

        self.assertEqual(len(readiness_items), 1)
        self.assertEqual(readiness_items[0]["label"], "QA Hero readiness G65_EVO")
        self.assertIn("6 of 7", readiness_items[0]["detail"])
        self.assertIn("QA Hero readiness G65_EVO", digest["markdown"])
        self.assertIn("presence and counts only", readiness_items[0]["guidance"])
        self.assertFalse(readiness_items[0]["is_approval"])
        self.assertEqual(
            qa_hero_readiness_digest_items({"qa_hero_readiness": [payload]})[0]["source"],
            "qa_hero_readiness",
        )
        self.assertNotIn("approved", digest["markdown"].lower())
        self.assertNotIn("validated", digest["markdown"].lower())


if __name__ == "__main__":
    unittest.main()

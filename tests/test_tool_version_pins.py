from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest import mock

import sg_preflight.tool_version_pins as tool_version_pins
from sg_preflight.tool_version_pins import (
    RAMSES_PIPELINE_PIN,
    compare_python_requirement,
    compare_version,
    load_raco_pins,
    python_requirement,
)


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class TestToolVersionPins(unittest.TestCase):
    def test_load_raco_pins_reads_interface_versions_yaml(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _write_text(
                root / "ci" / "scripts" / "common" / "interface_versions.yaml",
                "\n".join(
                    (
                        "---",
                        "12:",
                        "  type: RamsesComposer",
                        "  raco_version: 2.3.0",
                        "23:",
                        "  type: RamsesComposer",
                        "  raco_version: 2.9.0",
                        "24:",
                        "  type: RamsesComposer",
                        "  raco_version: 2.9.0",
                        "",
                    )
                ),
            )

            pins = load_raco_pins(root)

        self.assertEqual(pins["versions"], {"2.3.0": [12], "2.9.0": [23, 24]})
        self.assertIn("interface_versions.yaml", pins["source"])
        self.assertFalse(pins["fallback"])

    def test_load_raco_pins_uses_embedded_fallback_when_file_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pins = load_raco_pins(Path(temp_dir) / "missing")

        self.assertEqual(pins["versions"], {"2.3.0": [12], "2.9.0": [23, 24]})
        self.assertIn("embedded fallback", pins["source"])
        self.assertTrue(pins["fallback"])

    def test_compare_version_reports_ok_drift_unknown_and_not_pinned(self) -> None:
        pins = {"2.3.0": [12], "2.9.0": [23, 24]}

        ok_status, ok_detail = compare_version("RaCo Headless 2.9.0", pins)
        drift_status, drift_detail = compare_version("RaCo Headless 2.5.0", pins)
        unknown_status, unknown_detail = compare_version("RaCo Headless preview", pins)
        not_pinned_status, not_pinned_detail = compare_version("Blender 4.5.8", None)

        self.assertEqual(ok_status, "ok")
        self.assertIn("IDCevo", ok_detail)
        self.assertEqual(drift_status, "drift")
        self.assertIn("2.3.0", drift_detail)
        self.assertIn("2.9.0", drift_detail)
        self.assertNotIn("wrong", drift_detail.casefold())
        self.assertNotIn("invalid", drift_detail.casefold())
        self.assertEqual(unknown_status, "unknown")
        self.assertIn("could not parse", unknown_detail)
        self.assertEqual(not_pinned_status, "not_pinned")
        self.assertIn("No pinned version documented", not_pinned_detail)

    def test_python_requirement_comes_from_pyproject_and_can_be_compared(self) -> None:
        specifier, source = python_requirement()

        self.assertEqual(specifier, ">=3.10")
        self.assertEqual(source, "pyproject requires-python")
        self.assertEqual(compare_python_requirement("Python 3.13.13", specifier)[0], "ok")
        self.assertEqual(compare_python_requirement("Python 3.9.18", specifier)[0], "drift")
        self.assertEqual(compare_python_requirement("Python preview", specifier)[0], "unknown")
        self.assertEqual(RAMSES_PIPELINE_PIN, "28.16")

    def test_python_requirement_unknown_when_specifier_needs_packaging(self) -> None:
        # Without the packaging library, a compound specifier cannot be evaluated;
        # report an honest "unknown" rather than a false "drift".
        with mock.patch.object(tool_version_pins, "SpecifierSet", None):
            with mock.patch.object(tool_version_pins, "Version", None):
                simple = compare_python_requirement("Python 3.13.13", ">=3.10")
                compound = compare_python_requirement("Python 3.13.13", ">=3.10,<4.0")

        self.assertEqual(simple[0], "ok")
        self.assertEqual(compound[0], "unknown")
        self.assertNotIn("drift", compound[1].casefold())


if __name__ == "__main__":
    unittest.main()

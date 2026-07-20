from __future__ import annotations

from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _workflow_step(source: str, name: str) -> str:
    match = re.search(
        rf"(?ms)^      - name: {re.escape(name)}\n.*?(?=^      - name: |\Z)",
        source,
    )
    if match is None:
        raise AssertionError(f"Workflow step is missing: {name}")
    return match.group(0)


class TestCiWorkflow(unittest.TestCase):
    def test_windows_ci_exercises_the_shipped_qt_quick_default_offscreen(self) -> None:
        source = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

        self.assertIn("runs-on: windows-latest", source)
        install_step = _workflow_step(source, "Install package")
        self.assertIn('python -m pip install -e ".[desktop]"', install_step)

        qt_step = _workflow_step(source, "Run shipped-default Qt Quick tests")
        for setting in (
            "QT_QPA_PLATFORM: offscreen",
            "QSG_RHI_BACKEND: software",
            "QT_QUICK_CONTROLS_STYLE: Basic",
        ):
            self.assertIn(setting, qt_step)
        for selector in (
            "tests.test_cli.TestCLI.test_frozen_exe_entry_defaults_to_qt_quick_dashboard_when_double_clicked",
            "tests.test_qt_quick_core",
            "tests.test_qt_quick_capabilities",
            "tests.test_qt_quick_presenters",
            "tests.test_qt_quick_host",
            "tests.test_qt_quick_grafiks",
            "tests.test_qt_quick_preview",
            "tests.test_qt_quick_benchmark",
            "tests.test_qml_format",
        ):
            self.assertIn(selector, qt_step)
        self.assertNotIn("continue-on-error", qt_step)
        self.assertNotRegex(qt_step, r"(?m)^\s+if:")

        discovery_step = _workflow_step(source, "Run unit tests")
        self.assertIn("python -m unittest discover -s tests -v", discovery_step)


if __name__ == "__main__":
    unittest.main()

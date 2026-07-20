from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class TestOperatorUiLauncher(unittest.TestCase):
    def test_browser_launch_waits_for_bounded_http_readiness(self) -> None:
        source = (ROOT / "scripts" / "run_operator_ui.ps1").read_text(encoding="utf-8")

        self.assertIn("function Wait-OperatorUiReady", source)
        self.assertIn("Invoke-WebRequest", source)
        self.assertIn("Browser was not opened", source)
        self.assertIn("$serverProcess.HasExited", source)
        server_start = source.index("$serverProcess = Start-Process")
        readiness_wait = source.index("Wait-OperatorUiReady -Url $url", server_start)
        browser_start = source.index("Start-Process $url", readiness_wait)
        self.assertLess(server_start, readiness_wait)
        self.assertLess(readiness_wait, browser_start)

    def test_no_browser_path_keeps_the_server_in_the_foreground(self) -> None:
        source = (ROOT / "scripts" / "run_operator_ui.ps1").read_text(encoding="utf-8")

        self.assertIn("if (-not $OpenBrowser)", source)
        self.assertIn("& python @serverArguments", source)


if __name__ == "__main__":
    unittest.main()

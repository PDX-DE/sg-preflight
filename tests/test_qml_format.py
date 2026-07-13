from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load_script():
    path = ROOT / "scripts" / "check_qml_format.py"
    spec = importlib.util.spec_from_file_location("check_qml_format_for_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("check_qml_format.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestQmlFormatCheck(unittest.TestCase):
    def test_control_center_qml_has_no_infinite_or_protected_asset_motion(self) -> None:
        qml_root = ROOT / "sg_preflight" / "desktop" / "qml"
        source = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(qml_root.rglob("*.qml"))
        )
        lowered = source.casefold()

        self.assertNotIn("animation.infinite", lowered)
        self.assertNotRegex(lowered, r"loops\s*:\s*-1")
        self.assertNotIn("fontloader", lowered)
        self.assertNotIn("http://", lowered)
        self.assertNotIn("https://", lowered)
        for token in ("dynafont", "rodin", "sonic", "sega"):
            self.assertNotIn(token, lowered)

    def test_each_qml_file_is_checked_without_inplace_mutation_and_newlines_are_normalized(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "qml"
            nested = root / "components"
            nested.mkdir(parents=True)
            first = root / "Main.qml"
            second = nested / "Panel.qml"
            first.write_bytes(b"import QtQuick\r\nItem {\r\n}\r\n")
            second.write_bytes(b"import QtQuick\nItem {\n}\n")
            before = {path: path.read_bytes() for path in (first, second)}

            def run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
                source = Path(command[-1]).read_bytes().replace(b"\r\n", b"\n")
                return subprocess.CompletedProcess(command, 0, stdout=source, stderr=b"")

            runner = mock.Mock(side_effect=run)
            mismatches = module.check_qml_format(
                root,
                formatter=Path("formatter.exe"),
                runner=runner,
            )

            self.assertEqual(mismatches, ())
            self.assertEqual({path: path.read_bytes() for path in (first, second)}, before)

        self.assertEqual(runner.call_count, 2)
        commands = [call.args[0] for call in runner.call_args_list]
        self.assertEqual([Path(command[-1]).name for command in commands], ["Main.qml", "Panel.qml"])
        for command in commands:
            self.assertEqual(command[0], str(Path("formatter.exe")))
            self.assertNotIn("-i", command)
            self.assertNotIn("--inplace", command)
        self.assertTrue(all(call.kwargs["capture_output"] for call in runner.call_args_list))
        self.assertTrue(all("text" not in call.kwargs for call in runner.call_args_list))
        self.assertTrue(all("encoding" not in call.kwargs for call in runner.call_args_list))

    def test_mismatches_and_formatter_failures_are_relative_sorted_and_non_mutating(self) -> None:
        module = _load_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "private-user" / "qml"
            root.mkdir(parents=True)
            alpha = root / "Alpha.qml"
            beta = root / "Beta.qml"
            alpha.write_text("Item {}\n", encoding="utf-8")
            beta.write_text("Item {}\n", encoding="utf-8")
            before = {path: path.read_bytes() for path in (alpha, beta)}

            results = iter(
                (
                    subprocess.CompletedProcess([], 0, stdout=b"Item { }\n", stderr=b""),
                    subprocess.CompletedProcess([], 2, stdout=b"", stderr=str(root / "private.log").encode()),
                )
            )
            mismatches = module.check_qml_format(
                root,
                formatter=Path("formatter.exe"),
                runner=mock.Mock(side_effect=lambda *_args, **_kwargs: next(results)),
            )

            self.assertEqual(mismatches, ("Alpha.qml", "Beta.qml"))
            self.assertEqual({path: path.read_bytes() for path in (alpha, beta)}, before)

    def test_main_returns_nonzero_and_lists_only_relative_mismatches(self) -> None:
        module = _load_script()
        with mock.patch.object(module, "check_qml_format", return_value=("Main.qml", "components/Panel.qml")):
            with mock.patch("builtins.print") as printer:
                self.assertEqual(module.main([]), 1)

        rendered = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("Main.qml", rendered)
        self.assertIn("components/Panel.qml", rendered)
        self.assertNotIn(str(ROOT), rendered)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def _load_build_script():
    path = ROOT / "scripts" / "build_sgfx_exe.py"
    spec = importlib.util.spec_from_file_location("build_sgfx_exe_task10_test", path)
    if spec is None or spec.loader is None:
        raise AssertionError("build_sgfx_exe.py could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestQmlImportScanner(unittest.TestCase):
    def test_scanner_uses_exact_roots_and_persists_only_module_plugin_names(self) -> None:
        from sg_preflight.bundle_manifest import QmlImport, scan_qml_imports

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            qml_root = root / "private-user" / "qml"
            qt_qml_root = root / "private-qt" / "qml"
            scanner = root / "bin" / "pyside6-qmlimportscanner.exe"
            for path in (qml_root, qt_qml_root, scanner.parent):
                path.mkdir(parents=True, exist_ok=True)
            scanner.write_bytes(b"fixture")
            payload = [
                {
                    "name": "QtQuick.Controls",
                    "plugin": "qtquickcontrols2plugin",
                    "path": str(qt_qml_root / "QtQuick" / "Controls"),
                    "components": [str(qt_qml_root / "QtQuick" / "Controls" / "Button.qml")],
                    "type": "module",
                },
                {
                    "name": "QtQuick",
                    "plugin": "qtquick2plugin",
                    "path": str(qt_qml_root / "QtQuick"),
                    "type": "module",
                },
                {"name": "QtQml", "plugin": "qmlplugin", "type": "module"},
                {"name": "SGFX", "type": "module"},
                {"name": "components", "path": str(qml_root / "components"), "type": "directory"},
            ]
            runner = mock.Mock(
                return_value=subprocess.CompletedProcess([], 0, stdout=json.dumps(payload), stderr="")
            )

            imports = scan_qml_imports(
                qml_root,
                scanner_executable=scanner,
                qt_qml_root=qt_qml_root,
                runner=runner,
            )

        self.assertEqual(
            imports,
            (
                QmlImport("QtQml", "qmlplugin"),
                QmlImport("QtQuick", "qtquick2plugin"),
                QmlImport("QtQuick.Controls", "qtquickcontrols2plugin"),
                QmlImport("SGFX", ""),
            ),
        )
        command = runner.call_args.args[0]
        self.assertEqual(
            command,
            [
                str(scanner.resolve()),
                "-rootPath",
                str(qml_root.resolve()),
                "-importPath",
                str(qt_qml_root.resolve()),
            ],
        )
        self.assertNotIn("shell", runner.call_args.kwargs)
        self.assertTrue(runner.call_args.kwargs["capture_output"])
        self.assertTrue(runner.call_args.kwargs["text"])
        rendered = json.dumps([item.as_manifest_entry() for item in imports])
        self.assertNotIn(str(root), rendered)
        self.assertNotIn("components", rendered)
        self.assertNotIn("path", rendered.casefold())

    def test_scanner_fails_closed_on_process_json_and_required_module_errors(self) -> None:
        from sg_preflight.bundle_manifest import BundleManifestError, scan_qml_imports

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            qml_root = root / "qml"
            qt_qml_root = root / "qt-qml"
            scanner = root / "scanner.exe"
            qml_root.mkdir()
            qt_qml_root.mkdir()
            scanner.write_bytes(b"fixture")
            cases = (
                subprocess.CompletedProcess([], 2, stdout="", stderr=str(root / "private")),
                subprocess.CompletedProcess([], 0, stdout="not-json", stderr=""),
                subprocess.CompletedProcess(
                    [],
                    0,
                    stdout=json.dumps([{"name": "SGFX", "type": "module"}]),
                    stderr="",
                ),
            )
            for completed in cases:
                with self.subTest(returncode=completed.returncode, stdout=completed.stdout):
                    with self.assertRaises(BundleManifestError) as captured:
                        scan_qml_imports(
                            qml_root,
                            scanner_executable=scanner,
                            qt_qml_root=qt_qml_root,
                            runner=mock.Mock(return_value=completed),
                        )
                    self.assertNotIn(str(root), str(captured.exception))


class TestBundleManifest(unittest.TestCase):
    def test_product_fonts_are_exact_audited_assets_with_both_ofl_records(self) -> None:
        module = _load_build_script()
        approved = module.product_font_package_inputs()
        self.assertEqual(
            [path.name for path in approved],
            ["Fredoka.ttf", "Inter.ttf", "OFL-Fredoka.txt", "OFL-Inter.txt"],
        )
        arguments = module.build_pyinstaller_args()
        rendered = "\n".join(arguments)
        for name in ("Fredoka.ttf", "Inter.ttf", "OFL-Fredoka.txt", "OFL-Inter.txt"):
            self.assertIn(name, rendered)

        with tempfile.TemporaryDirectory() as temp_dir:
            font_root = Path(temp_dir) / "fonts"
            shutil.copytree(ROOT / "cpp" / "assets" / "fonts", font_root)
            (font_root / "Sonic-Rodin.ttf").write_bytes(b"protected font")
            with self.assertRaises(RuntimeError):
                module.product_font_package_inputs(font_root)
            (font_root / "Sonic-Rodin.ttf").unlink()
            (font_root / "Inter.ttf").write_bytes(b"changed font")
            with self.assertRaises(RuntimeError):
                module.product_font_package_inputs(font_root)

    def test_source_commit_requires_an_exact_clean_worktree(self) -> None:
        from sg_preflight.bundle_manifest import BundleManifestError, source_commit

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            clean_runner = mock.Mock(
                side_effect=(
                    subprocess.CompletedProcess([], 0, stdout="1" * 40 + "\n", stderr=""),
                    subprocess.CompletedProcess([], 0, stdout="", stderr=""),
                )
            )
            self.assertEqual(source_commit(root, runner=clean_runner), "1" * 40)
            self.assertEqual(
                clean_runner.call_args_list[1].args[0],
                ["git", "-C", str(root.resolve()), "status", "--porcelain", "--untracked-files=all"],
            )

            dirty_runner = mock.Mock(
                side_effect=(
                    subprocess.CompletedProcess([], 0, stdout="1" * 40 + "\n", stderr=""),
                    subprocess.CompletedProcess(
                        [],
                        0,
                        stdout=f"?? {root / 'private-user-file'}\n",
                        stderr="",
                    ),
                )
            )
            with self.assertRaises(BundleManifestError) as captured:
                source_commit(root, runner=dirty_runner)

        self.assertNotIn(str(root), str(captured.exception))

    def test_manifest_is_exact_sanitized_and_records_optional_grafiks_digests(self) -> None:
        from sg_preflight.bundle_manifest import QmlImport, create_bundle_manifest

        imports = (
            QmlImport("QtQml", "qmlplugin"),
            QmlImport("QtQuick", "qtquick2plugin"),
            QmlImport("QtQuick.Controls", "qtquickcontrols2plugin"),
            QmlImport("SGFX", ""),
        )
        grafiks = {
            "sha256": "a" * 64,
            "notice_sha256": "b" * 64,
            "license_manifest_sha256": "c" * 64,
            "dependency_inventory_sha256": "d" * 64,
        }

        manifest = create_bundle_manifest(
            source_commit="1" * 40,
            sgfx_version="0.1.1",
            python_version="3.13.13",
            pyside6_version="6.9.1",
            qt_version="6.9.1",
            qml_imports=imports,
            grafiks_reference=grafiks,
            ramses_preview_helper="included",
        )

        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["source_commit"], "1" * 40)
        self.assertEqual(manifest["qml_contract_version"], 1)
        self.assertEqual(manifest["ui_capability_count"], 8)
        self.assertEqual(manifest["surface_descriptor_count"], 19)
        self.assertEqual(manifest["qa_hub_schema_version"], 1)
        self.assertTrue(manifest["control_center_qml_present"])
        self.assertTrue(manifest["product_fonts_licensed"])
        self.assertEqual(manifest["ramses_preview_helper"], "included")
        self.assertEqual(manifest["presentation_modes"], ["clean", "grafiks", "qt-quick"])
        self.assertEqual(manifest["qml_imports"][0], {"module": "QtQml", "plugin": "qmlplugin"})
        self.assertEqual(manifest["grafiks"], grafiks)
        rendered = json.dumps(manifest, sort_keys=True)
        for forbidden in ("C:\\", "/home/", "credential", "telemetry", "username", "operator_path"):
            self.assertNotIn(forbidden, rendered.casefold())

        without_grafiks = create_bundle_manifest(
            source_commit="2" * 40,
            sgfx_version="0.1.1",
            python_version="3.13.13",
            pyside6_version="6.9.1",
            qt_version="6.9.1",
            qml_imports=imports,
        )
        self.assertEqual(without_grafiks["presentation_modes"], ["clean", "qt-quick"])
        self.assertNotIn("grafiks", without_grafiks)
        self.assertEqual(without_grafiks["ramses_preview_helper"], "unavailable")

    def test_optional_preview_runtime_copy_is_all_or_nothing(self) -> None:
        module = _load_build_script()
        runtime_names = (
            "ramses-shared-lib-headless.dll",
            "ramses-shared-lib-renderer.dll",
            "ramses-shared-lib.dll",
            "SDL3.dll",
            "sgfx_cine_ramses_preview_cli.exe",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            bundle = root / "bundle"
            source.mkdir()
            bundle.mkdir()
            self.assertFalse(module.copy_preview_runtime(bundle, source))
            self.assertFalse((bundle / "_internal" / "cpp" / "bin").exists())

            for name in runtime_names:
                (source / name).write_bytes((name + " fixture").encode("utf-8"))
            self.assertTrue(module.copy_preview_runtime(bundle, source))
            target = bundle / "_internal" / "cpp" / "bin"
            self.assertEqual(tuple(sorted(path.name for path in target.iterdir())), tuple(sorted(runtime_names)))

            (source / "unexpected.dll").write_bytes(b"not audited")
            self.assertFalse(module.copy_preview_runtime(bundle, source))
            self.assertFalse(target.exists())

    def test_private_editable_install_metadata_is_removed_only_from_dist_info(self) -> None:
        module = _load_build_script()
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "bundle"
            private_metadata = bundle / "_internal" / "sg_preflight-0.1.0.dist-info" / "direct_url.json"
            unrelated = bundle / "_internal" / "application" / "direct_url.json"
            private_metadata.parent.mkdir(parents=True)
            unrelated.parent.mkdir(parents=True)
            private_metadata.write_text('{"url":"file:///Users/private/source"}', encoding="utf-8")
            unrelated.write_text("{}", encoding="utf-8")

            removed = module.remove_private_install_metadata(bundle)

            self.assertEqual(removed, (private_metadata,))
            self.assertFalse(private_metadata.exists())
            self.assertTrue(unrelated.is_file())

    def test_control_center_verifier_is_bounded_machine_readable_and_external_write_free(self) -> None:
        script = ROOT / "scripts" / "verify_control_center_c0.ps1"
        self.assertTrue(script.is_file())
        source = script.read_text(encoding="utf-8")
        lowered = source.casefold()

        for token in (
            "control-center-c0-verification.json",
            "control-center-c0-verification.md",
            "--staged-only",
            "1280",
            "720",
            "1024",
            "640",
            "OPEN_LOADED_WORKSTATION",
            "Get-TrackedFingerprint",
            "256 * 1024 * 1024",
            "frame-*.png",
        ):
            self.assertIn(token.casefold(), lowered)
        for forbidden in (
            "invoke-restmethod",
            "invoke-webrequest",
            "start-bitstransfer",
            "svn commit",
            "git push",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_manifest_rejects_noncanonical_values_and_writes_stable_json(self) -> None:
        from sg_preflight.bundle_manifest import (
            BundleManifestError,
            QmlImport,
            create_bundle_manifest,
            write_bundle_manifest,
        )

        imports = (
            QmlImport("QtQml", "qmlplugin"),
            QmlImport("QtQuick", "qtquick2plugin"),
            QmlImport("QtQuick.Controls", "qtquickcontrols2plugin"),
        )
        invalid_inputs = (
            {"source_commit": r"C:\private\commit"},
            {"sgfx_version": r"C:\private\version"},
            {"python_version": "3.13\nsecret"},
            {"ramses_preview_helper": "unknown"},
        )
        defaults = {
            "source_commit": "1" * 40,
            "sgfx_version": "0.1.1",
            "python_version": "3.13.13",
            "pyside6_version": "6.9.1",
            "qt_version": "6.9.1",
            "qml_imports": imports,
        }
        for overrides in invalid_inputs:
            with self.subTest(overrides=overrides):
                with self.assertRaises(BundleManifestError):
                    create_bundle_manifest(**(defaults | overrides))

        manifest = create_bundle_manifest(**defaults)
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "bundle"
            bundle.mkdir()
            path = write_bundle_manifest(bundle, manifest)
            raw = path.read_bytes()

        self.assertEqual(path.name, "bundle-manifest.json")
        self.assertEqual(json.loads(raw), manifest)
        self.assertTrue(raw.endswith(b"\n"))
        self.assertEqual(raw, (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"))

    def test_staged_content_validation_requires_every_runtime_module_and_plugin(self) -> None:
        from sg_preflight.bundle_manifest import (
            BundleManifestError,
            CONTROL_CENTER_QML_FILES,
            PRODUCT_FONT_SHA256,
            QmlImport,
            create_bundle_manifest,
            validate_staged_bundle_contents,
            write_bundle_manifest,
        )

        imports = (
            QmlImport("QtQml", "qmlplugin"),
            QmlImport("QtQuick", "qtquick2plugin"),
            QmlImport("QtQuick.Controls", "qtquickcontrols2plugin"),
            QmlImport("SGFX", ""),
        )
        manifest = create_bundle_manifest(
            source_commit="1" * 40,
            sgfx_version="0.1.1",
            python_version="3.13.13",
            pyside6_version="6.9.1",
            qt_version="6.9.1",
            qml_imports=imports,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = Path(temp_dir) / "sgfx-preflight"
            controls_plugin = (
                bundle
                / "_internal"
                / "PySide6"
                / "Qt"
                / "qml"
                / "QtQuick"
                / "Controls"
                / "qtquickcontrols2plugin.dll"
            )
            files = (
                bundle / "sgfx-preflight.exe",
                bundle / "_internal" / "PySide6" / "Qt" / "bin" / "Qt6Qml.dll",
                bundle / "_internal" / "PySide6" / "Qt" / "bin" / "Qt6Quick.dll",
                bundle / "_internal" / "PySide6" / "Qt" / "plugins" / "platforms" / "qwindows.dll",
                bundle / "_internal" / "sg_preflight" / "desktop" / "qml" / "Main.qml",
                bundle / "_internal" / "PySide6" / "Qt" / "qml" / "QtQml" / "qmldir",
                bundle / "_internal" / "PySide6" / "Qt" / "qml" / "QtQml" / "qmlplugin.dll",
                bundle / "_internal" / "PySide6" / "Qt" / "qml" / "QtQuick" / "qmldir",
                bundle / "_internal" / "PySide6" / "Qt" / "qml" / "QtQuick" / "qtquick2plugin.dll",
                bundle / "_internal" / "PySide6" / "Qt" / "qml" / "QtQuick" / "Controls" / "qmldir",
                controls_plugin,
                bundle / "_internal" / "sg_preflight" / "desktop" / "qml" / "SGFX" / "qmldir",
            )
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
            qml_components = (
                bundle / "_internal" / "sg_preflight" / "desktop" / "qml" / "components"
            )
            for name in CONTROL_CENTER_QML_FILES:
                target = qml_components / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"fixture")
            packaged_fonts = bundle / "_internal" / "cpp" / "assets" / "fonts"
            packaged_fonts.mkdir(parents=True, exist_ok=True)
            source_fonts = ROOT / "cpp" / "assets" / "fonts"
            for name in PRODUCT_FONT_SHA256:
                shutil.copy2(source_fonts / name, packaged_fonts / name)
            write_bundle_manifest(bundle, manifest)

            validate_staged_bundle_contents(bundle, imports)
            included_manifest = create_bundle_manifest(
                source_commit="1" * 40,
                sgfx_version="0.1.1",
                python_version="3.13.13",
                pyside6_version="6.9.1",
                qt_version="6.9.1",
                qml_imports=imports,
                ramses_preview_helper="included",
            )
            write_bundle_manifest(bundle, included_manifest)
            with self.assertRaises(BundleManifestError):
                validate_staged_bundle_contents(bundle, imports)
            write_bundle_manifest(bundle, manifest)
            forbidden_frame = bundle / "_internal" / "preview-cache" / "frame-000.png"
            forbidden_frame.parent.mkdir(parents=True)
            forbidden_frame.write_bytes(b"fixture")
            with self.assertRaises(BundleManifestError):
                validate_staged_bundle_contents(bundle, imports)
            forbidden_frame.unlink()
            unexpected_runtime = bundle / "_internal" / "cpp" / "bin" / "unexpected.dll"
            unexpected_runtime.parent.mkdir(parents=True)
            unexpected_runtime.write_bytes(b"fixture")
            with self.assertRaises(BundleManifestError):
                validate_staged_bundle_contents(bundle, imports)
            unexpected_runtime.unlink()
            missing = controls_plugin
            decoy = bundle / "unrelated" / missing.name
            decoy.parent.mkdir()
            decoy.write_bytes(b"fixture")
            missing.unlink()
            with self.assertRaises(BundleManifestError) as captured:
                validate_staged_bundle_contents(bundle, imports)

        self.assertNotIn(str(bundle), str(captured.exception))
        self.assertIn("QtQuick.Controls", str(captured.exception))


class TestGrafiksProvenance(unittest.TestCase):
    def _approved_fixture(self, root: Path):
        from sg_preflight.grafiks_provenance import GrafiksProvenance, sha256_file

        executable = root / "grafiks" / "sgfx_screens.exe"
        notice = root / "evidence" / "NOTICE.txt"
        license_manifest = root / "evidence" / "licenses.json"
        dependency_inventory = root / "evidence" / "dependencies.json"
        executable.parent.mkdir(parents=True)
        notice.parent.mkdir(parents=True)
        executable.write_bytes(b"approved executable")
        notice.write_text("Redistribution notices", encoding="utf-8")
        license_manifest.write_text(
            json.dumps(
                {
                    "entries": [
                        {
                            "path": "sgfx_screens.exe",
                            "license_reference": "LicenseRef-ParadoxCat-Internal",
                            "redistributable": True,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        dependency_inventory.write_text(
            json.dumps(
                {
                    "dependencies": [
                        {"name": "example", "license": "MIT", "redistributable": True}
                    ]
                }
            ),
            encoding="utf-8",
        )
        record = GrafiksProvenance(
            sha256=sha256_file(executable),
            notice_path=str(notice),
            notice_sha256=sha256_file(notice),
            license_manifest_path=str(license_manifest),
            license_manifest_sha256=sha256_file(license_manifest),
            dependency_inventory_path=str(dependency_inventory),
            dependency_inventory_sha256=sha256_file(dependency_inventory),
            permissive_dependencies_verified=True,
            converted_layouts_absent=True,
            protected_fonts_absent=True,
            protected_assets_absent=True,
            derived_shaders_absent=True,
            approved_for_distribution=True,
        )
        return executable, notice, license_manifest, dependency_inventory, record

    def test_exact_digest_and_all_distribution_evidence_are_required(self) -> None:
        from dataclasses import replace

        from sg_preflight.grafiks_provenance import accept_grafiks_bundle

        with tempfile.TemporaryDirectory() as temp_dir:
            executable, _notice, _licenses, _dependencies, record = self._approved_fixture(Path(temp_dir))
            self.assertTrue(accept_grafiks_bundle(executable, record))
            self.assertFalse(accept_grafiks_bundle(executable, None))
            for field in (
                "permissive_dependencies_verified",
                "converted_layouts_absent",
                "protected_fonts_absent",
                "protected_assets_absent",
                "derived_shaders_absent",
                "approved_for_distribution",
            ):
                with self.subTest(field=field):
                    self.assertFalse(accept_grafiks_bundle(executable, replace(record, **{field: False})))
            self.assertFalse(accept_grafiks_bundle(executable, replace(record, sha256="0" * 64)))
            executable.write_bytes(b"changed after approval")
            self.assertFalse(accept_grafiks_bundle(executable, record))

    def test_dependency_and_license_manifests_fail_closed(self) -> None:
        from dataclasses import replace

        from sg_preflight.grafiks_provenance import accept_grafiks_bundle, sha256_file

        with tempfile.TemporaryDirectory() as temp_dir:
            executable, _notice, licenses, dependencies, record = self._approved_fixture(Path(temp_dir))
            dependencies.write_text(
                json.dumps(
                    {
                        "dependencies": [
                            {"name": "unknown", "license": "GPL-3.0-only", "redistributable": True}
                        ]
                    }
                ),
                encoding="utf-8",
            )
            record = replace(
                record,
                dependency_inventory_sha256=sha256_file(dependencies),
            )
            self.assertFalse(accept_grafiks_bundle(executable, record))

            licenses.write_text(
                json.dumps(
                    {"entries": [{"path": "sgfx_screens.exe", "redistributable": True}]}
                ),
                encoding="utf-8",
            )
            record = replace(
                record,
                license_manifest_sha256=sha256_file(licenses),
            )
            self.assertFalse(accept_grafiks_bundle(executable, record))

    def test_license_manifest_must_cover_every_file_selected_for_copy(self) -> None:
        from sg_preflight.grafiks_provenance import (
            license_manifest_allows_distribution,
            license_manifest_covers_files,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            _executable, _notice, licenses, _dependencies, _record = self._approved_fixture(
                Path(temp_dir)
            )

            self.assertTrue(license_manifest_covers_files(licenses, ("sgfx_screens.exe",)))
            self.assertFalse(
                license_manifest_covers_files(
                    licenses,
                    ("sgfx_screens.exe", "unlisted-runtime.dll"),
                )
            )
            for invalid_path in (
                r"C:\private\sgfx_screens.exe",
                "C:private.exe",
                "sgfx_screens.exe:alternate-stream",
                "../sgfx_screens.exe",
            ):
                with self.subTest(invalid_path=invalid_path):
                    licenses.write_text(
                        json.dumps(
                            {
                                "entries": [
                                    {
                                        "path": invalid_path,
                                        "license_reference": "LicenseRef-Invalid",
                                        "redistributable": True,
                                    }
                                ]
                            }
                        ),
                        encoding="utf-8",
                    )
                    self.assertFalse(license_manifest_allows_distribution(licenses))
                    self.assertFalse(
                        license_manifest_covers_files(licenses, ("sgfx_screens.exe",))
                    )

    def test_record_loading_is_strict_and_manifest_reference_omits_paths(self) -> None:
        from dataclasses import asdict

        from sg_preflight.grafiks_provenance import (
            GrafiksProvenanceError,
            grafiks_manifest_reference,
            load_grafiks_provenance,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _executable, _notice, _licenses, _dependencies, record = self._approved_fixture(root)
            record_path = root / "record.json"
            record_path.write_text(json.dumps(asdict(record)), encoding="utf-8")
            loaded = load_grafiks_provenance(record_path)
            reference = grafiks_manifest_reference(loaded)
            self.assertEqual(reference["sha256"], record.sha256)
            rendered = json.dumps(reference)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("path", rendered.casefold())

            record_path.write_text(json.dumps({**asdict(record), "unexpected": True}), encoding="utf-8")
            with self.assertRaises(GrafiksProvenanceError):
                load_grafiks_provenance(record_path)

    def test_copied_provenance_evidence_is_rehashed_and_mismatch_is_removed(self) -> None:
        from sg_preflight.grafiks_provenance import (
            GrafiksProvenanceError,
            copy_grafiks_provenance_evidence,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            _executable, _notice, _licenses, _dependencies, record = self._approved_fixture(root)
            target = root / "staged-evidence"
            copied = copy_grafiks_provenance_evidence(record, target)
            self.assertEqual(
                {path.name for path in copied},
                {"NOTICE.txt", "license-manifest.json", "dependency-inventory.json"},
            )

            mismatch = root / "mismatch"

            def corrupt_copy(_source: Path, destination: Path) -> None:
                Path(destination).write_bytes(b"changed during copy")

            with mock.patch(
                "sg_preflight.grafiks_provenance.shutil.copy2",
                side_effect=corrupt_copy,
            ):
                with self.assertRaises(GrafiksProvenanceError):
                    copy_grafiks_provenance_evidence(record, mismatch)

            self.assertEqual(list(mismatch.glob("*")), [])


if __name__ == "__main__":
    unittest.main()

class TestHeldStagingDirectories(unittest.TestCase):
    def test_held_but_empty_directory_skeleton_is_tolerated(self) -> None:
        import ctypes

        module = _load_build_script()
        kernel32 = ctypes.windll.kernel32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "staging"
            held = root / "sgfx-preflight"
            held.mkdir(parents=True)
            (held / "artifact.txt").write_text("stale", encoding="utf-8")
            # GENERIC_READ, FILE_SHARE_READ only (no FILE_SHARE_DELETE), OPEN_EXISTING,
            # FILE_FLAG_BACKUP_SEMANTICS - the exact Explorer-style hold that blocks rmdir.
            handle = kernel32.CreateFileW(str(held), 0x80000000, 0x1, None, 3, 0x02000000, None)
            self.assertNotEqual(handle, -1)
            try:
                module._rmtree_tolerating_held_dirs(root)
                self.assertTrue(held.exists())
                self.assertEqual(list(held.iterdir()), [])
            finally:
                kernel32.CloseHandle(handle)

    def test_undeletable_file_still_fails_the_clean(self) -> None:
        module = _load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "staging"
            held = root / "sgfx-preflight"
            held.mkdir(parents=True)
            blocker = held / "locked.bin"
            blocker.write_text("held", encoding="utf-8")
            with blocker.open("rb"):
                with self.assertRaises(OSError):
                    module._rmtree_tolerating_held_dirs(root)

    def test_fresh_bundle_relocates_into_held_destination(self) -> None:
        import ctypes

        module = _load_build_script()
        kernel32 = ctypes.windll.kernel32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fresh" / "sgfx-preflight"
            (source / "_internal").mkdir(parents=True)
            (source / "sgfx-preflight.exe").write_text("exe", encoding="utf-8")
            (source / "_internal" / "base_library.zip").write_text("zip", encoding="utf-8")
            dest = root / "b" / "sgfx-preflight"
            dest.mkdir(parents=True)
            handle = kernel32.CreateFileW(str(dest), 0x80000000, 0x1, None, 3, 0x02000000, None)
            self.assertNotEqual(handle, -1)
            try:
                result = module.relocate_fresh_bundle(source, dest)
                self.assertEqual(result, dest)
                self.assertTrue((dest / "sgfx-preflight.exe").is_file())
                self.assertTrue((dest / "_internal" / "base_library.zip").is_file())
                # The destination directory itself is reused, so its contents must not nest under
                # a second sgfx-preflight/.
                self.assertFalse((dest / "sgfx-preflight").exists())
                # The helper moves contents; the emptied source directory is the caller's to remove.
                self.assertEqual(list(source.iterdir()), [])
            finally:
                kernel32.CloseHandle(handle)

    def test_fresh_bundle_merges_into_held_nested_subdirectory(self) -> None:
        import ctypes

        module = _load_build_script()
        kernel32 = ctypes.windll.kernel32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "fresh" / "sgfx-preflight"
            (source / "_internal").mkdir(parents=True)
            (source / "_internal" / "base_library.zip").write_text("zip", encoding="utf-8")
            dest = root / "b" / "sgfx-preflight"
            (dest / "_internal").mkdir(parents=True)
            handle = kernel32.CreateFileW(
                str(dest / "_internal"), 0x80000000, 0x1, None, 3, 0x02000000, None
            )
            self.assertNotEqual(handle, -1)
            try:
                module.relocate_fresh_bundle(source, dest)
                self.assertTrue((dest / "_internal" / "base_library.zip").is_file())
                # A held destination subdirectory is merged into, not nested under.
                self.assertFalse((dest / "_internal" / "_internal").exists())
            finally:
                kernel32.CloseHandle(handle)

    def test_merge_move_resolves_file_vs_directory_type_mismatch(self) -> None:
        module = _load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src"
            (source / "widget").mkdir(parents=True)
            (source / "widget" / "inner.txt").write_text("fresh-dir", encoding="utf-8")
            (source / "plain.txt").write_text("fresh-file", encoding="utf-8")
            dest = root / "dst"
            dest.mkdir()
            (dest / "widget").write_text("stale-file-where-dir-belongs", encoding="utf-8")
            (dest / "plain.txt").mkdir()  # stale dir where a file belongs
            (dest / "plain.txt" / "leftover.txt").write_text("stale", encoding="utf-8")
            # The fresh build output is authoritative; both mismatches resolve without crashing.
            module.relocate_fresh_bundle(source, dest)
            self.assertTrue((dest / "widget" / "inner.txt").is_file())
            self.assertTrue((dest / "plain.txt").is_file())
            self.assertEqual((dest / "plain.txt").read_text(encoding="utf-8"), "fresh-file")

    def test_fresh_staging_distpath_stays_short(self) -> None:
        module = _load_build_script()
        distpath = module._fresh_staging_distpath()
        try:
            # Much shorter than the earlier 19-char "sgfx-stage-<8 random>" name, preserving
            # Windows MAX_PATH headroom during the PyInstaller assembly phase.
            self.assertLessEqual(len(distpath.name), 10)
            self.assertTrue(distpath.name.startswith(module.FRESH_DISTPATH_PREFIX))
            self.assertTrue(distpath.is_dir())
        finally:
            distpath.rmdir()

    def test_clean_staging_outputs_sweeps_leftover_fresh_distpaths(self) -> None:
        module = _load_build_script()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            saved = module.STAGING_DIST_PATH
            module.STAGING_DIST_PATH = root / "b"
            try:
                leftover = root / f"{module.FRESH_DISTPATH_PREFIX}old1234"
                (leftover / "sgfx-preflight").mkdir(parents=True)
                (leftover / "sgfx-preflight" / "stale.dll").write_text("x", encoding="utf-8")
                unrelated = root / "cine-c0"
                unrelated.mkdir()
                (unrelated / "keep.txt").write_text("keep", encoding="utf-8")
                module.clean_staging_outputs()
                self.assertFalse(leftover.exists())
                self.assertTrue((unrelated / "keep.txt").is_file())
            finally:
                module.STAGING_DIST_PATH = saved

    def test_swap_failure_recovers_migrated_content_and_old_bundle(self) -> None:
        import ctypes

        module = _load_build_script()
        kernel32 = ctypes.windll.kernel32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "b" / "sgfx-preflight"
            (staged / "_internal").mkdir(parents=True)
            (staged / "_internal" / "new.dll").write_text("fresh build content", encoding="utf-8")
            # 'zz-locked.exe' sorts after '_internal' so the directory migrates first, then the
            # locked file fails the merge partway through.
            locked = staged / "zz-locked.exe"
            locked.write_text("exe", encoding="utf-8")
            saved = (module.DIST_PATH, module.WORK_PATH,
                     module.BACKUP_BUNDLE_PATH, module.BACKUP_SINGLE_FILE_PATH)
            module.DIST_PATH = root / "dist"
            module.WORK_PATH = root / "work"
            module.BACKUP_BUNDLE_PATH = root / "p"
            module.BACKUP_SINGLE_FILE_PATH = root / "p.exe"
            old_bundle = root / "dist" / "sgfx-preflight"
            old_bundle.mkdir(parents=True)
            (old_bundle / "old.txt").write_text("accepted bundle", encoding="utf-8")
            # No FILE_SHARE_DELETE: the file can be read but not moved/deleted.
            handle = kernel32.CreateFileW(str(locked), 0x80000000, 0x1, None, 3, 0x80, None)
            self.assertNotEqual(handle, -1)
            try:
                with self.assertRaises(OSError):
                    module.swap_staged_bundle(staged)
                # The already-migrated fresh content must be recoverable in the staged bundle,
                # and the previously accepted bundle must survive (in place or at the backup).
                self.assertTrue((staged / "_internal" / "new.dll").is_file())
                old_recovered = (old_bundle / "old.txt").is_file() or \
                    (root / "p" / "old.txt").is_file()
                self.assertTrue(old_recovered)
            finally:
                kernel32.CloseHandle(handle)
                (module.DIST_PATH, module.WORK_PATH,
                 module.BACKUP_BUNDLE_PATH, module.BACKUP_SINGLE_FILE_PATH) = saved

    def test_swap_staged_bundle_tolerates_held_staged_source(self) -> None:
        import ctypes

        module = _load_build_script()
        kernel32 = ctypes.windll.kernel32
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            staged = root / "b" / "sgfx-preflight"
            (staged / "_internal").mkdir(parents=True)
            (staged / "sgfx-preflight.exe").write_text("exe", encoding="utf-8")
            (staged / "_internal" / "base_library.zip").write_text("zip", encoding="utf-8")
            saved = (module.DIST_PATH, module.WORK_PATH,
                     module.BACKUP_BUNDLE_PATH, module.BACKUP_SINGLE_FILE_PATH)
            module.DIST_PATH = root / "dist"
            module.WORK_PATH = root / "work"
            module.BACKUP_BUNDLE_PATH = root / "p"
            module.BACKUP_SINGLE_FILE_PATH = root / "p.exe"
            handle = kernel32.CreateFileW(str(staged), 0x80000000, 0x1, None, 3, 0x02000000, None)
            self.assertNotEqual(handle, -1)
            try:
                module.swap_staged_bundle(staged)
                final = root / "dist" / "sgfx-preflight"
                self.assertTrue((final / "sgfx-preflight.exe").is_file())
                self.assertTrue((final / "_internal" / "base_library.zip").is_file())
            finally:
                kernel32.CloseHandle(handle)
                (module.DIST_PATH, module.WORK_PATH,
                 module.BACKUP_BUNDLE_PATH, module.BACKUP_SINGLE_FILE_PATH) = saved

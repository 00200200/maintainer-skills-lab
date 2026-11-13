"""Packaging and strict native-CI guard regressions without building an extension."""

from __future__ import annotations

import io
import tarfile
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from tools import native_ci


class NativeCIGuardTests(unittest.TestCase):
    def test_missing_or_partial_native_apis_fail_preflight(self):
        api = types.SimpleNamespace(
            minify_markdown=str,
            walk_project=list,
            count_tokens=int,
            extract_ast_symbols=list,
            blake3_hash=str,
            Symbol=type,
            DisallowedSpecialTokenError=ValueError,
        )
        native_ci.validate_api(api)
        for name in vars(api):
            incomplete = types.SimpleNamespace(**vars(api))
            delattr(incomplete, name)
            with self.subTest(name=name), self.assertRaises(RuntimeError):
                native_ci.validate_api(incomplete)

    def test_empty_or_missing_required_test_groups_fail(self):
        with self.assertRaisesRegex(RuntimeError, "not discovered"):
            native_ci.require_groups([])
        tests = [
            types.SimpleNamespace(id=lambda group=group: group + ".test_example")
            for group in native_ci.REQUIRED_GROUPS
        ]
        native_ci.require_groups(tests)
        with self.assertRaisesRegex(RuntimeError, "not discovered"):
            native_ci.require_groups(tests[:-1])

    def test_missing_extension_and_parity_skips_are_never_allowed(self):
        for group in native_ci.REQUIRED_GROUPS:
            for system in ("linux", "darwin", "win32"):
                with self.subTest(group=group, system=system):
                    self.assertFalse(
                        native_ci.skip_allowed(
                            group + ".test_example", "Optional native backend unavailable", system
                        )
                    )
        test = "test_native_walk.NativeWalkTests.test_special_files_are_not_opened"
        self.assertFalse(native_ci.skip_allowed(test, "Optional extension not installed", "win32"))
        self.assertFalse(native_ci.skip_allowed(test, "Requires POSIX special files", "linux"))
        self.assertTrue(native_ci.skip_allowed(test, "Requires POSIX special files", "win32"))
        test = next(iter(native_ci.PERMISSION_TESTS)) + " (path='fixture')"
        self.assertTrue(
            native_ci.skip_allowed(
                test, "Current user can read paths regardless of mode bits", "linux"
            )
        )

    def test_runner_rejects_successful_result_containing_native_skips(self):
        cases = []
        for group in native_ci.REQUIRED_GROUPS:
            case = unittest.FunctionTestCase(lambda: None)
            case.id = Mock(return_value=group + ".test_example")
            cases.append(case)
        result = types.SimpleNamespace(
            skipped=[(cases[0], "Optional extension is not installed")],
            wasSuccessful=lambda: True,
        )
        with (
            patch.object(native_ci, "smoke"),
            patch.object(native_ci.importlib, "import_module", return_value=Mock()),
            patch.object(
                unittest.defaultTestLoader, "discover", return_value=unittest.TestSuite(cases)
            ),
            patch.object(unittest, "TextTestRunner") as runner,
            patch.object(native_ci.sys, "path", list(native_ci.sys.path)),
        ):
            runner.return_value.run.return_value = result
            with self.assertRaisesRegex(RuntimeError, "unexpected skipped"):
                native_ci.run_tests("x86_64")


class NativePackageValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def wheel(self, platform="manylinux_2_28_x86_64", *, binary=True):
        path = self.root / f"msl_core-0.1.0-cp311-abi3-{platform}.whl"
        prefix = "msl_core-0.1.0.dist-info/"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                prefix + "WHEEL",
                f"Wheel-Version: 1.0\nRoot-Is-Purelib: false\nTag: cp311-abi3-{platform}\n",
            )
            archive.writestr(
                prefix + "METADATA", "Metadata-Version: 2.4\nName: msl-core\nVersion: 0.1.0\n"
            )
            archive.writestr(prefix + "RECORD", "")
            if binary:
                archive.writestr("msl_core/msl_core.abi3.so", b"fixture")
        return path

    def test_wheel_tags_and_native_payload_are_required(self):
        path = self.wheel()
        native_ci.validate_wheel(path, "manylinux_2_28_x86_64")
        with self.assertRaisesRegex(ValueError, "ABI/platform"):
            native_ci.validate_wheel(path, "musllinux_1_2_x86_64")
        with self.assertRaisesRegex(ValueError, "no native extension"):
            native_ci.validate_wheel(self.wheel(binary=False), "manylinux_2_28_x86_64")

    def test_wheel_paths_are_checked(self):
        path = self.wheel()
        with zipfile.ZipFile(path, "a") as archive:
            archive.writestr("../escaped", "invalid")
        with self.assertRaisesRegex(ValueError, "paths"):
            native_ci.validate_wheel(path, "manylinux_2_28_x86_64")

    def sdist(self, *, missing=None, unsafe=False):
        path = self.root / "msl_core-0.1.0.tar.gz"
        files = {
            "Cargo.toml",
            "Cargo.lock",
            "pyproject.toml",
            "README.md",
            "PKG-INFO",
            "src/lib.rs",
            "src/symbols.rs",
            "src/tokenizer.rs",
            "src/walker.rs",
        }
        with tarfile.open(path, "w:gz") as archive:
            for name in sorted(files - {missing}):
                info = tarfile.TarInfo("msl_core-0.1.0/" + name)
                info.size = 7
                archive.addfile(info, io.BytesIO(b"fixture"))
            if unsafe:
                archive.addfile(tarfile.TarInfo("../outside"), io.BytesIO())
        return path

    def test_sdist_requires_sources_and_lockfile_and_safe_paths(self):
        native_ci.validate_sdist(self.sdist())
        for missing in ("Cargo.lock", "pyproject.toml", "src/symbols.rs"):
            with self.subTest(missing=missing), self.assertRaisesRegex(ValueError, "Incomplete"):
                native_ci.validate_sdist(self.sdist(missing=missing))
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            native_ci.validate_sdist(self.sdist(unsafe=True))

    def test_missing_or_multiple_artifacts_fail(self):
        with self.assertRaises(ValueError):
            native_ci.one_artifact(self.root, "*.whl")
        first = self.wheel()
        self.assertEqual(native_ci.one_artifact(self.root, "*.whl"), first)
        self.wheel("musllinux_1_2_x86_64")
        with self.assertRaises(ValueError):
            native_ci.one_artifact(self.root, "*.whl")


if __name__ == "__main__":
    unittest.main()

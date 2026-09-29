import importlib.util
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("smart_ignore", ROOT / "tools/smart_ignore.py")
smart_ignore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smart_ignore)


class SmartIgnoreTests(unittest.TestCase):
    def test_all_common_lockfiles_are_ignorable(self):
        for name in (
            "package-lock.json",
            "yarn.lock",
            "pnpm-lock.yaml",
            "Cargo.lock",
            "poetry.lock",
            "uv.lock",
            "Pipfile.lock",
        ):
            with self.subTest(name=name):
                self.assertTrue(smart_ignore.is_ignorable_for_context(name))
                self.assertTrue(smart_ignore.is_ignorable_for_context(Path("vendor") / name))

    def test_minified_compiled_and_media_patterns(self):
        cases = (
            "assets/app.min.js",
            "styles/theme.min.css",
            "bundle.js.map",
            "module.pyc",
            "runtime.wasm",
            "dist/index.js",
            "build/output.js",
            "weights.bin",
            "model.pt",
            "encoder.onnx",
            "data.parquet",
            "cache.sqlite",
        )
        for path in cases:
            with self.subTest(path=path):
                self.assertTrue(smart_ignore.is_ignorable_for_context(path))

    def test_source_and_manifests_are_kept(self):
        for path in (
            "package.json",
            "pyproject.toml",
            "Cargo.toml",
            "src/main.py",
            "skills/mkl-review-pr/SKILL.md",
            "tools/smart_ignore.py",
            "README.md",
        ):
            with self.subTest(path=path):
                self.assertFalse(smart_ignore.is_ignorable_for_context(path))

    def test_mklignore_file_loads_default_patterns(self):
        patterns = smart_ignore.load_patterns()
        self.assertIn("package-lock.json", patterns)
        self.assertIn("*.min.js", patterns)
        self.assertIn("dist/**", patterns)
        self.assertIn("*.onnx", patterns)

    def test_custom_ignore_file_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".mklignore"
            path.write_text("# comment\ncustom.lock\n*.generated.ts\n", encoding="utf-8")
            patterns = smart_ignore.load_patterns(path)
            self.assertEqual(patterns, ("custom.lock", "*.generated.ts"))
            self.assertTrue(
                smart_ignore.is_ignorable_for_context("schema.generated.ts", patterns=patterns)
            )
            self.assertFalse(
                smart_ignore.is_ignorable_for_context("package-lock.json", patterns=patterns)
            )

    def test_omission_message_for_lockfile(self):
        with tempfile.TemporaryDirectory() as temporary:
            lockfile = Path(temporary) / "package-lock.json"
            lockfile.write_text("{\n}\n" + ("  \"a\": 1,\n" * 3), encoding="utf-8")
            message = smart_ignore.omission_message(lockfile)
            self.assertIn("package-lock.json", message)
            self.assertIn("lockfile", message)
            self.assertIn("Omitted to preserve token budget", message)
            self.assertIn("npm list", message)
            self.assertRegex(message, r"\d+ lines")

    def test_filter_paths_skips_ignorables(self):
        kept = smart_ignore.filter_paths(
            [
                "src/app.py",
                "package-lock.json",
                "dist/bundle.js",
                "README.md",
                "app.min.js",
            ]
        )
        self.assertEqual(kept, ["src/app.py", "README.md"])


if __name__ == "__main__":
    unittest.main()

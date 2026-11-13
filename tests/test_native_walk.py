"""Optional native project walker contract; no integration with kit.source_files."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

try:
    import msl_core
except ModuleNotFoundError as error:
    if error.name != "msl_core":
        raise
    msl_core = None


@unittest.skipIf(msl_core is None, "Optional msl_core extension is not installed")
class NativeWalkTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "project"
        self.root.mkdir()

    def write(self, name: str, content: str | bytes = "text\n") -> Path:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return path

    def walk(self, patterns: list[str] | None = None) -> list[str]:
        # An installed M1-only extension must fail visibly, not skip M2 tests.
        return msl_core.walk_project(str(self.root), patterns or [])

    def symlink(self, link: Path, target: Path):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlinks are not supported here: {error}")

    def test_empty_tree_and_sorted_nested_unicode_posix_paths(self):
        self.assertEqual(self.walk(), [])
        expected = ["z.txt", "src/漢字/żółć.md", "src/a.py", "space dir/🙂.txt", ".hidden"]
        for name in expected:
            self.write(name)
        actual = self.walk()
        self.assertEqual(actual, sorted(expected))
        for name in actual:
            self.assertFalse(Path(name).is_absolute())
            self.assertNotIn("..", name.split("/"))
        self.assertEqual(msl_core.walk_project(str(self.root) + os.sep + ".", []), actual)

    def test_gitignore_without_git_repository_and_nested_rules(self):
        self.write(".gitignore", "*.log\n/cache/\n!keep.log\n")
        self.write("src/.gitignore", "private.txt\n")
        for name in ["drop.log", "src/drop.log", "cache/item.txt", "src/private.txt"]:
            self.write(name)
        for name in ["keep.log", "src/keep.log", "src/public.txt", "src/cache/item.txt"]:
            self.write(name)
        self.assertEqual(
            self.walk(),
            sorted(
                [
                    ".gitignore",
                    "src/.gitignore",
                    "keep.log",
                    "src/keep.log",
                    "src/public.txt",
                    "src/cache/item.txt",
                ]
            ),
        )

    def test_mklignore_priority_and_nested_patterns(self):
        self.write(".gitignore", "*.md\n")
        self.write(".mklignore", "!keep.md\n*.secret\n")
        self.write("src/.mklignore", "local.txt\n")
        for name in ["drop.md", "hidden.secret", "src/local.txt", "src/hidden.secret"]:
            self.write(name)
        self.write("keep.md")
        self.write("src/visible.txt")
        self.assertEqual(
            self.walk(),
            sorted(
                [
                    ".gitignore",
                    ".mklignore",
                    "keep.md",
                    "src/.mklignore",
                    "src/visible.txt",
                ]
            ),
        )

    def test_additional_rules_are_root_relative_and_subtractive(self):
        self.write(".gitignore", "ignored/\n")
        for name in ["root.txt", "src/root.txt", "drop.tmp", "keep.tmp", "ignored/a.txt"]:
            self.write(name)
        self.assertEqual(
            self.walk(["/root.txt", "*.tmp", "!keep.tmp", "!ignored/a.txt"]),
            [
                ".gitignore",
                "keep.tmp",
                "src/root.txt",
            ],
        )

    def test_ancestor_dot_ignore_and_git_exclude_rules_are_not_inputs(self):
        (self.base / ".gitignore").write_text("*.txt\n", encoding="utf-8")
        self.write(".ignore", "*.txt\n")
        self.write(".git/info/exclude", "*.txt\n")
        self.write("visible.txt")
        self.assertEqual(self.walk(), [".ignore", "visible.txt"])

    def test_binary_detection_uses_content_and_handles_utf8_boundary(self):
        self.write("binary.txt", b"text\0data")
        self.write("invalid.txt", b"\xff\xfe")
        self.write("truncated.txt", b"\xf0\x9f")
        self.write("utf16.txt", "hello".encode("utf-16-le"))
        self.write("plain.bin", "still text")
        self.write("empty", b"")
        self.write("boundary.txt", "a" * 8191 + "🙂" + "tail")
        self.assertEqual(self.walk(), ["boundary.txt", "empty", "plain.bin"])

    def test_symlink_files_directories_and_broken_links_are_skipped(self):
        outside = self.base / "outside"
        outside.mkdir()
        (outside / "secret.txt").write_text("secret", encoding="utf-8")
        self.write("visible.txt")
        self.symlink(self.root / "file-link", outside / "secret.txt")
        self.symlink(self.root / "dir-link", outside)
        self.symlink(self.root / "loop", self.root)
        self.symlink(self.root / "broken", outside / "absent")
        self.assertEqual(self.walk(), ["visible.txt"])

    def test_symlink_root_and_root_components_are_rejected(self):
        link = self.base / "link"
        self.symlink(link, self.root)
        self.write("sub/a.txt")
        for root in [str(link), str(link) + os.sep, str(link / "sub")]:
            with self.subTest(root=root), self.assertRaises(OSError):
                msl_core.walk_project(root, [])

    def test_symlink_ignore_files_are_rejected_before_loading(self):
        external = self.base / "rules"
        external.write_text("*\n", encoding="utf-8")
        for name in [".gitignore", ".mklignore", "sub/.gitignore", "sub/.mklignore"]:
            with self.subTest(name=name):
                link = self.root / name
                link.parent.mkdir(exist_ok=True)
                self.symlink(link, external)
                try:
                    with self.assertRaises(OSError):
                        self.walk()
                finally:
                    link.unlink()

    def test_missing_and_file_roots_and_empty_root(self):
        for root in [self.root / "missing", self.write("file.txt")]:
            with self.subTest(root=root), self.assertRaises(OSError):
                msl_core.walk_project(str(root), [])
        with self.assertRaises(ValueError):
            msl_core.walk_project("", [])

    def test_invalid_rules_and_argument_types(self):
        for pattern in ["one\ntwo", "one\rtwo", "one\0two", "[z-a]"]:
            with self.subTest(pattern=pattern), self.assertRaises(ValueError):
                self.walk([pattern])
        with self.assertRaises(TypeError):
            msl_core.walk_project(str(self.root), [123])
        with self.assertRaises(TypeError):
            msl_core.walk_project(None, [])

    def test_malformed_local_rules_do_not_produce_partial_results(self):
        self.write("visible.txt")
        for name in [".gitignore", ".mklignore", "sub/.gitignore", "sub/.mklignore"]:
            with self.subTest(name=name):
                path = self.write(name, "[z-a]\n")
                try:
                    with self.assertRaises(OSError):
                        self.walk()
                finally:
                    path.unlink()

    def test_ignore_file_names_cannot_be_directories(self):
        for name in [".gitignore", ".mklignore"]:
            with self.subTest(name=name):
                path = self.root / name
                path.mkdir()
                try:
                    with self.assertRaises(OSError):
                        self.walk()
                finally:
                    path.rmdir()

    @unittest.skipUnless(hasattr(os, "mkfifo"), "Requires POSIX special files")
    def test_special_files_are_not_opened(self):
        os.mkfifo(self.root / "pipe")
        self.write("normal.txt")
        self.assertEqual(self.walk(), ["normal.txt"])

    @unittest.skipUnless(os.name == "posix", "Requires POSIX permissions")
    def test_unreadable_file_fails_instead_of_returning_partial_results(self):
        self.write("normal.txt")
        path = self.write("unreadable.txt")
        path.chmod(0)
        try:
            if os.access(path, os.R_OK):
                self.skipTest("Current user can read files regardless of mode bits")
            with self.assertRaises(OSError):
                self.walk()
        finally:
            path.chmod(0o600)

    @unittest.skipUnless(os.name == "posix", "Requires POSIX permissions")
    def test_unreadable_directory_and_rule_file_fail(self):
        self.write("visible.txt")
        directory = self.root / "private"
        directory.mkdir()
        rule = self.write(".mklignore", "*.log\n")
        for path in [directory, rule]:
            with self.subTest(path=path):
                original_mode = path.stat().st_mode
                path.chmod(0)
                try:
                    if os.access(path, os.R_OK):
                        self.skipTest("Current user can read paths regardless of mode bits")
                    with self.assertRaises(OSError):
                        self.walk()
                finally:
                    path.chmod(original_mode)

    @unittest.skipUnless(os.name == "posix", "Requires byte-valued filenames")
    def test_non_utf8_filename_is_rejected_without_lossy_conversion(self):
        with open(os.fsencode(self.root) + b"/bad-\xff.txt", "wb") as stream:
            stream.write(b"text")
        with self.assertRaises(ValueError):
            self.walk()

    def test_parallel_results_are_deterministic(self):
        expected = [f"dir-{index % 7}/file-{index:03}.txt" for index in range(100)]
        for name in reversed(expected):
            self.write(name)
        for _ in range(8):
            self.assertEqual(self.walk(), sorted(expected))


if __name__ == "__main__":
    unittest.main()

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools import publish_marketplace as publisher


class PublishMarketplaceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        # Exercise kit's stdlib fallback regardless of optional local packages.
        counter = patch.object(
            publisher.kit,
            "count_tokens",
            side_effect=(
                lambda text, encoding="cl100k_base": (
                    publisher.kit.approximate_tokens(text) if text else 0
                )
            ),
        )
        counter.start()
        self.addCleanup(counter.stop)
        self.write("README.md", "# Fixture library\n")
        self.write("LICENSE", "MIT fixture license\n")
        self.write(
            "skills/mkl-example/SKILL.md",
            (
                '---\nname: "mkl-example"\ndescription: "Review a change."\n'
                'globs: ["*.py"]\n---\n\nReview the change carefully.\n'
            ),
        )
        self.write("skills/mkl-example/references/guide.md", "A supporting guide.\n")
        self.write("skills/mkl-example/scripts/helper.py", "print('helper')\n")
        self.write(
            "agents/mkl-reviewer.toml",
            (
                'name = "mkl-reviewer"\ndescription = "Review changes."\n'
                'instructions = "Read the change."\nskills = ["mkl-example"]\n'
            ),
        )
        self.marketplace = {
            "name": "maintainer-skills-lab",
            "owner": {"name": "maintainer"},
            "plugins": [
                {
                    "name": "maintainer-skills-lab",
                    "description": "All workflows.",
                    "source": "./providers/claude/.claude",
                    "strict": False,
                },
                {
                    "name": "mkl-example",
                    "description": "One workflow.",
                    "source": "./skills/mkl-example",
                    "strict": False,
                },
            ],
        }
        self.save_metadata()
        self.export()

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def save_metadata(self):
        self.write(publisher.MARKETPLACE, json.dumps(self.marketplace))

    def export(self):
        for target in ("claude", "cursor"):
            for name, data in publisher.kit.export_files(target, root=self.root).items():
                path = self.root / "providers" / target / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)

    def snapshot(self, directory):
        return {
            path.relative_to(directory).as_posix(): path.read_bytes()
            for path in directory.rglob("*")
            if path.is_file()
        }

    def test_validate_without_pyproject_is_read_only_and_reuses_kit(self):
        before = self.snapshot(self.root)
        with (
            patch.object(
                publisher.kit, "check_library", wraps=publisher.kit.check_library
            ) as check,
            patch.object(publisher.kit, "export_files", wraps=publisher.kit.export_files) as export,
        ):
            report = publisher.validate(self.root)
        check.assert_called_once_with(root=self.root)
        self.assertEqual({call.args[0] for call in export.call_args_list}, {"claude", "cursor"})
        self.assertTrue(report["valid"])
        self.assertEqual(report["skills_checked"], 1)
        self.assertEqual(report["agents_checked"], 1)
        self.assertFalse((self.root / "pyproject.toml").exists())
        self.assertEqual(before, self.snapshot(self.root))

    def test_soft_budget_over_800_is_advisory(self):
        path = self.root / "skills/mkl-example/SKILL.md"
        path.write_text(path.read_text() + "x" * 3300, encoding="utf-8")
        self.export()
        report = publisher.validate(self.root)
        self.assertTrue(report["valid"])
        self.assertTrue(report["warnings"])
        self.assertTrue(publisher.build("1.0.0", root=self.root)["warnings"])

    def test_hard_budget_and_description_budget_are_enforced(self):
        path = self.root / "skills/mkl-example/SKILL.md"
        original = path.read_text()
        for text in (original + "x" * 5000, original.replace("Review a change.", "x" * 300)):
            with self.subTest(text_length=len(text)):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(publisher.kit.KitError):
                    publisher.build("1.0.0", root=self.root)
                self.assertFalse((self.root / "dist").exists())

    def test_unknown_agent_dependency_is_rejected(self):
        path = self.root / "agents/mkl-reviewer.toml"
        path.write_text(path.read_text().replace("mkl-example", "mkl-missing"), encoding="utf-8")
        with self.assertRaisesRegex(publisher.kit.KitError, "unknown skill"):
            publisher.validate(self.root)

    def test_missing_required_files_produce_no_artifacts(self):
        for relative in (
            publisher.MARKETPLACE,
            "LICENSE",
            "README.md",
            "providers/cursor/.cursor/skills/mkl-example/SKILL.md",
        ):
            with self.subTest(path=relative):
                path = self.root / relative
                content = path.read_bytes()
                path.unlink()
                try:
                    with self.assertRaises(publisher.PublishError):
                        publisher.build("1.2.3", root=self.root)
                    self.assertFalse((self.root / "dist").exists())
                finally:
                    path.write_bytes(content)

    def test_stale_and_extra_exports_are_rejected_for_both_targets(self):
        for target in ("claude", "cursor"):
            relative = f"providers/{target}/.{target}/skills/mkl-example/SKILL.md"
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(b"stale")
            with self.assertRaisesRegex(publisher.PublishError, f"{target} exports"):
                publisher.validate(self.root)
            path.write_bytes(original)
            extra = f"providers/{target}/.{target}/skills/unmanaged.md"
            self.write(extra, "Unexpected file")
            with self.assertRaises(publisher.PublishError):
                publisher.validate(self.root)
            (self.root / extra).unlink()

    def test_bad_metadata_shapes_names_sources_and_duplicates(self):
        original = json.dumps(self.marketplace)
        variants = [
            [],
            {},
            {"name": "bad name"},
            {"owner": []},
            {"plugins": []},
            {"plugins": [None]},
            {"plugins": [{"name": "bad name"}]},
        ]
        for fields in variants:
            with self.subTest(fields=fields):
                value = json.loads(original)
                if isinstance(fields, dict) and fields:
                    value.update(fields)
                else:
                    value = fields
                self.write(publisher.MARKETPLACE, json.dumps(value))
                with self.assertRaises(publisher.PublishError):
                    publisher.validate(self.root)
        for source in (
            "../escape",
            "./../escape",
            "/absolute",
            "./",
            "./skills/../agents",
            "./skills\\escape",
            "https://example.com/plugin",
            "./missing",
        ):
            with self.subTest(source=source):
                self.marketplace = json.loads(original)
                self.marketplace["plugins"][0]["source"] = source
                self.save_metadata()
                with self.assertRaises(publisher.PublishError):
                    publisher.validate(self.root)
        self.marketplace = json.loads(original)
        self.marketplace["plugins"].append(self.marketplace["plugins"][0])
        self.save_metadata()
        with self.assertRaisesRegex(publisher.PublishError, "Duplicate"):
            publisher.validate(self.root)

    def test_missing_required_metadata_fields_are_rejected(self):
        original = json.dumps(self.marketplace)
        cases = (
            ((), ("name", "owner", "plugins")),
            (("owner",), ("name",)),
            (("plugins", 0), ("name", "source", "description")),
        )
        for path, fields in cases:
            for field in fields:
                with self.subTest(path=path, field=field):
                    value = json.loads(original)
                    item = value
                    for key in path:
                        item = item[key]
                    del item[field]
                    self.write(publisher.MARKETPLACE, json.dumps(value))
                    with self.assertRaisesRegex(
                        publisher.PublishError, f"missing required fields: {field}"
                    ):
                        publisher.validate(self.root)

    def test_invalid_json_and_missing_plugin_description(self):
        self.write(publisher.MARKETPLACE, "{broken")
        with self.assertRaisesRegex(publisher.PublishError, "Invalid JSON"):
            publisher.validate(self.root)
        del self.marketplace["plugins"][0]["description"]
        self.save_metadata()
        with self.assertRaisesRegex(publisher.PublishError, "description"):
            publisher.validate(self.root)

    def test_duplicate_json_fields_and_malformed_optional_metadata_are_rejected(self):
        self.write(publisher.MARKETPLACE, '{"name": "one", "name": "two"}')
        with self.assertRaisesRegex(publisher.PublishError, "duplicate field"):
            publisher.validate(self.root)
        self.marketplace["plugins"][0]["keywords"] = "not-a-list"
        self.save_metadata()
        with self.assertRaisesRegex(publisher.PublishError, "keywords"):
            publisher.validate(self.root)

    def test_versions_are_optional_but_must_be_valid_and_consistent(self):
        for value in ("", "v1.2.3", "1.2", "01.2.3", "1.2.3-01", "../1.2.3", "1.2.3\n"):
            with self.subTest(version=value), self.assertRaises(publisher.PublishError):
                publisher.build(value, root=self.root)
        self.marketplace["metadata"] = {"version": "1.2.3-rc.1+local"}
        self.marketplace["plugins"][0]["version"] = "1.2.3-rc.1+local"
        self.save_metadata()
        publisher.validate(self.root)
        publisher.build("1.2.3-rc.1+local", root=self.root)
        with self.assertRaisesRegex(publisher.PublishError, "Inconsistent versions"):
            publisher.build("1.2.4", root=self.root)
        self.marketplace["plugins"][1]["version"] = "2.0.0"
        self.save_metadata()
        with self.assertRaisesRegex(publisher.PublishError, "Inconsistent versions"):
            publisher.validate(self.root)

    def test_strict_plugin_manifest_is_required_and_validated(self):
        self.marketplace["plugins"][1]["strict"] = True
        self.save_metadata()
        with self.assertRaisesRegex(publisher.PublishError, "missing .claude-plugin/plugin.json"):
            publisher.validate(self.root)
        manifest = "skills/mkl-example/.claude-plugin/plugin.json"
        self.write(manifest, json.dumps({"name": "wrong", "version": "1.0.0"}))
        with self.assertRaisesRegex(publisher.PublishError, "name mismatch"):
            publisher.validate(self.root)
        self.write(manifest, json.dumps({"name": "mkl-example", "version": "1.0.0"}))
        self.export()
        publisher.build("1.0.0", root=self.root)
        with self.assertRaisesRegex(publisher.PublishError, "Inconsistent versions"):
            publisher.build("2.0.0", root=self.root)

    def test_bundle_structure_and_marketplace_sources_survive_extraction(self):
        self.write(".cursorrules", "Fixture rules\n")
        result = publisher.build("1.2.3", root=self.root)
        self.assertEqual(len(result["artifacts"]), 3)
        for target in ("claude", "cursor"):
            archive_path = self.root / "dist" / f"maintainer-skills-lab-{target}-v1.2.3.zip"
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                self.assertEqual(names, sorted(names))
                self.assertIn("LICENSE", names)
                self.assertIn("README.md", names)
                for name, data in publisher.kit.export_files(target, root=self.root).items():
                    self.assertEqual(archive.read(f"providers/{target}/{name}"), data)
                for entry in archive.infolist():
                    self.assertEqual(entry.date_time, (1980, 1, 1, 0, 0, 0))
                    self.assertEqual(entry.external_attr >> 16, 0o100644)
                    self.assertEqual(entry.create_system, 3)
                if target == "cursor":
                    self.assertIn(".cursorrules", names)
                    self.assertIn("providers/cursor/.cursor/rules/mkl-example.mdc", names)
                else:
                    self.assertIn("agents/mkl-reviewer.toml", names)
                    self.assertIn("skills/mkl-example/references/guide.md", names)
                    self.assertIn("skills/mkl-example/scripts/helper.py", names)
                    destination = self.root / "extracted"
                    archive.extractall(destination)
                    metadata = json.loads((destination / publisher.MARKETPLACE).read_text())
                    for plugin in metadata["plugins"]:
                        self.assertTrue((destination / plugin["source"]).is_dir())
                        self.assertTrue(any((destination / plugin["source"]).rglob("SKILL.md")))

    def test_optional_cursorrules_absence_is_supported(self):
        publisher.build("1.0.0", root=self.root)
        with zipfile.ZipFile(self.root / "dist/maintainer-skills-lab-cursor-v1.0.0.zip") as archive:
            self.assertNotIn(".cursorrules", archive.namelist())

    def test_deterministic_bytes_and_sha256_despite_mtime_permissions_and_order(self):
        first = self.root / "first"
        second = self.root / "second"
        publisher.build("1.2.3", first, root=self.root)
        for directory in ("skills", "agents", "providers", ".claude-plugin"):
            for path in (self.root / directory).rglob("*"):
                if path.is_file():
                    os.utime(path, (1700000000, 1700000000))
                    path.chmod(0o755)
        publisher.build("1.2.3", second, root=self.root)
        self.assertEqual(self.snapshot(first), self.snapshot(second))
        self.assertEqual(
            publisher._zip({"z": b"z", "a": b"a"}), publisher._zip({"a": b"a", "z": b"z"})
        )
        checksums = (first / "checksums.txt").read_text().splitlines()
        self.assertEqual(len(checksums), 2)
        for line in checksums:
            digest, name = line.split("  ")
            self.assertEqual(hashlib.sha256((first / name).read_bytes()).hexdigest(), digest)

    def test_symlink_source_and_artifact_destinations_are_rejected(self):
        source = self.root / "skills/mkl-example/link.md"
        source.symlink_to(self.root / "LICENSE")
        with self.assertRaises(publisher.kit.KitError):
            publisher.validate(self.root)
        source.unlink()
        output = self.root / "dist"
        output.mkdir()
        (output / "checksums.txt").symlink_to(self.root / "LICENSE")
        with self.assertRaises(publisher.kit.KitError):
            publisher.build("1.0.0", root=self.root)
        self.assertEqual((self.root / "LICENSE").read_text(), "MIT fixture license\n")
        self.assertEqual(len(list(output.iterdir())), 1)

    def test_archive_failure_leaves_existing_output_untouched(self):
        output = self.root / "dist"
        self.write("dist/keep.txt", "Keep this file.")
        before = self.snapshot(output)
        with patch.object(publisher, "_zip", side_effect=[b"first", OSError("zip failure")]):
            with self.assertRaisesRegex(OSError, "zip failure"):
                publisher.build("1.0.0", root=self.root)
        self.assertEqual(before, self.snapshot(output))

    def test_failed_commit_rolls_back_old_and_new_artifacts(self):
        output = self.root / "dist"
        self.write("dist/keep.txt", "Unrelated artifact")
        self.write("dist/maintainer-skills-lab-claude-v1.0.0.zip", "Previous archive")
        self.write("dist/checksums.txt", "Previous checksums")
        before = self.snapshot(output)
        replace = os.replace
        calls = 0

        def fail_checksums(source, destination):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("commit failure")
            return replace(source, destination)

        with patch.object(publisher.os, "replace", side_effect=fail_checksums):
            with self.assertRaisesRegex(OSError, "commit failure"):
                publisher.build("1.0.0", root=self.root)
        self.assertEqual(before, self.snapshot(output))
        self.assertFalse(any(path.name.startswith(".marketplace-") for path in output.iterdir()))

    def test_failed_first_write_leaves_no_output_directory(self):
        with patch.object(publisher.os, "replace", side_effect=OSError("disk error")):
            with self.assertRaisesRegex(OSError, "disk error"):
                publisher.build("1.0.0", root=self.root)
        self.assertFalse((self.root / "dist").exists())

    def test_cli_validation_build_and_errors(self):
        with (
            patch.object(publisher, "validate", return_value={"valid": True}) as validate,
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
        ):
            self.assertEqual(publisher.main(["validate"]), 0)
            self.assertTrue(json.loads(stdout.getvalue())["valid"])
        validate.assert_called_once_with()
        with (
            patch.object(publisher, "build", return_value={"artifacts": []}) as build,
            patch("sys.stdout", new_callable=io.StringIO),
        ):
            self.assertEqual(
                publisher.main(["build", "--version", "1.0.0", "--output-dir", "out"]), 0
            )
        build.assert_called_once_with("1.0.0", Path("out"))
        for error in (
            publisher.PublishError("bad metadata"),
            publisher.kit.KitError("bad skill"),
            OSError("permission denied"),
        ):
            with (
                self.subTest(error=error),
                patch.object(publisher, "validate", side_effect=error),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(publisher.main(["validate"]), 1)
                self.assertIn(str(error), stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

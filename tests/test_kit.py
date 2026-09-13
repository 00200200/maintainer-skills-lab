import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kit", ROOT / "tools/kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


def snapshot(directory):
    return {
        path.relative_to(directory).as_posix(): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def copy_library(destination):
    for name in ("skills", "agents", "grok-bot"):
        shutil.copytree(ROOT / name, destination / name)
    shutil.copyfile(ROOT / "LICENSE", destination / "LICENSE")


class LibraryTests(unittest.TestCase):
    def test_native_agents_embed_their_workflows(self):
        skills, agents = kit.load_library()
        self.assertEqual(len(skills), 6)
        self.assertEqual(len(agents), 3)
        for target in kit.TARGETS:
            files = kit.export_files(target)
            skill_dir, agent_dir, extension = kit.TARGETS[target]
            for name, skill in skills.items():
                self.assertEqual(files[f"{skill_dir}/{name}/SKILL.md"], skill["files"]["SKILL.md"])
            for name, agent in agents.items():
                content = files[f"{agent_dir}/{name}{extension}"].decode()
                if target == "codex":
                    parsed = tomllib.loads(content)
                    self.assertEqual(set(parsed), {"name", "description", "developer_instructions"})
                    body = parsed["developer_instructions"]
                else:
                    _, header, body = content.split("---", 2)
                    parsed = {
                        line.split(":", 1)[0]: json.loads(line.split(":", 1)[1])
                        for line in header.strip().splitlines()
                    }
                self.assertEqual(parsed["name"], name)
                for dependency in agent["skills"]:
                    self.assertIn(skills[dependency]["body"], body)

    def test_unknown_dependency_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            path = root / "agents/mkl-bug-investigator.toml"
            path.write_text(path.read_text().replace('"mkl-triage-issue"', '"mkl-absent"'))
            with self.assertRaisesRegex(kit.KitError, "unknown skill dependency"):
                kit.load_library(root)

    def test_name_must_match_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            path = root / "skills/mkl-review-pr/SKILL.md"
            path.write_text(path.read_text().replace('name: "mkl-review-pr"', 'name: "mkl-other"'))
            with self.assertRaisesRegex(kit.KitError, "mismatch"):
                kit.load_library(root)

    def test_unsupported_frontmatter_is_explicit(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "mkl-example/SKILL.md"
            path.parent.mkdir()
            path.write_text('---\nname: "mkl-example"\ndescription: |\n  multiline\n---\nBody\n')
            with self.assertRaisesRegex(kit.KitError, "double-quoted"):
                kit.skill_metadata(path)

    def test_source_symlinks_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            (root / "skills/mkl-review-pr/external.txt").symlink_to(root / "LICENSE")
            with self.assertRaisesRegex(kit.KitError, "symlinks"):
                kit.load_library(root)

    def test_archives_are_reproducible_and_contained(self):
        with tempfile.TemporaryDirectory() as temporary:
            for target in [*kit.TARGETS, "grok-bot"]:
                archive = kit.build(target, Path(temporary))
                initial = archive.read_bytes()
                kit.build(target, Path(temporary))
                self.assertEqual(initial, archive.read_bytes())
                with zipfile.ZipFile(archive) as handle:
                    self.assertIsNone(handle.testzip())
                    for name in handle.namelist():
                        self.assertTrue(name.startswith(f"maintainer-skills-lab-{target}/"))
                        self.assertNotIn("..", Path(name).parts)
                    self.assertIn(f"maintainer-skills-lab-{target}/LICENSE", handle.namelist())


class InstallationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.project = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def test_each_target_installs_and_uninstalls(self):
        for target in kit.TARGETS:
            with self.subTest(target=target):
                result = kit.install(target, self.project)
                self.assertEqual(len(result["written"]), 9)
                self.assertEqual(len(snapshot(self.project)), 10)
                kit.uninstall(target, self.project)
                self.assertEqual(snapshot(self.project), {})

    def test_dry_run_has_no_side_effects(self):
        result = kit.install("codex", self.project, dry_run=True)
        self.assertEqual(len(result["written"]), 9)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_second_install_is_noop_and_keeps_configuration(self):
        config = self.project / ".codex/config.toml"
        config.parent.mkdir()
        config.write_text('model = "user-selected-model"\n')
        kit.install("codex", self.project)
        initial = snapshot(self.project)
        mtimes = {
            str(path): path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()
        }
        result = kit.install("codex", self.project)
        self.assertEqual(result["written"], [])
        self.assertFalse(result["manifest_changed"])
        self.assertEqual(initial, snapshot(self.project))
        self.assertEqual(
            mtimes,
            {
                str(path): path.stat().st_mtime_ns
                for path in self.project.rglob("*")
                if path.is_file()
            },
        )
        kit.uninstall("codex", self.project)
        self.assertEqual(
            snapshot(self.project), {".codex/config.toml": b'model = "user-selected-model"\n'}
        )

    def test_unmanaged_conflict_is_detected_before_any_write(self):
        relative = max(kit.export_files("claude"))
        path = self.project / relative
        path.parent.mkdir(parents=True)
        path.write_text("My existing skill")
        initial = snapshot(self.project)
        with self.assertRaisesRegex(kit.KitError, "conflicts"):
            kit.install("claude", self.project)
        self.assertEqual(initial, snapshot(self.project))
        self.assertFalse((self.project / ".maintainer-skills-lab").exists())

    def test_identical_unmanaged_file_is_not_claimed_or_removed(self):
        files = kit.export_files("cursor")
        relative = next(iter(files))
        path = self.project / relative
        path.parent.mkdir(parents=True)
        path.write_bytes(files[relative])
        result = kit.install("cursor", self.project)
        self.assertIn(relative, result["identical_unmanaged"])
        kit.uninstall("cursor", self.project)
        self.assertEqual(snapshot(self.project), {relative: files[relative]})

    def test_local_edits_block_install_and_uninstall(self):
        kit.install("codex", self.project)
        relative = next(iter(kit.export_files("codex")))
        path = self.project / relative
        path.write_text("Locally edited instructions")
        initial = snapshot(self.project)
        for action in (kit.install, kit.uninstall):
            with self.assertRaises(kit.KitError):
                action("codex", self.project)
            self.assertEqual(initial, snapshot(self.project))

    def test_upgrade_removes_only_owned_unchanged_resources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            extra = root / "skills/mkl-review-pr/assets/note.txt"
            extra.parent.mkdir()
            extra.write_text("Old resource")
            kit.install("claude", self.project, root)
            extra.unlink()
            skill = root / "skills/mkl-review-pr/SKILL.md"
            skill.write_text(skill.read_text() + "\nNew workflow detail.\n")
            result = kit.install("claude", self.project, root)
            self.assertEqual(result["removed"], [".claude/skills/mkl-review-pr/assets/note.txt"])
            self.assertIn(".claude/skills/mkl-review-pr/SKILL.md", result["written"])
            kit.uninstall("claude", self.project)
            self.assertEqual(snapshot(self.project), {})

    def test_modified_obsolete_resource_blocks_whole_upgrade(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            copy_library(root)
            extra = root / "skills/mkl-review-pr/note.txt"
            extra.write_text("Old resource")
            kit.install("codex", self.project, root)
            (self.project / ".agents/skills/mkl-review-pr/note.txt").write_text("User edits")
            extra.unlink()
            initial = snapshot(self.project)
            with self.assertRaisesRegex(kit.KitError, "refusing removal"):
                kit.install("codex", self.project, root)
            self.assertEqual(initial, snapshot(self.project))

    def test_symlink_parent_cannot_redirect_install(self):
        with tempfile.TemporaryDirectory() as outside:
            (self.project / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(kit.KitError, "symlink"):
                kit.install("codex", self.project)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def test_symlink_owned_file_is_not_removed(self):
        kit.install("codex", self.project)
        relative = next(iter(kit.export_files("codex")))
        path = self.project / relative
        path.unlink()
        outside = self.project / "keep.txt"
        outside.write_text("Do not remove")
        path.symlink_to(outside)
        with self.assertRaisesRegex(kit.KitError, "symlink"):
            kit.uninstall("codex", self.project)
        self.assertEqual(outside.read_text(), "Do not remove")

    def test_tampered_manifest_rejected(self):
        kit.install("codex", self.project)
        path = self.project / ".maintainer-skills-lab/codex.json"
        state = json.loads(path.read_text())
        state["files"]["../../keep.txt"] = "0" * 64
        path.write_text(json.dumps(state))
        initial = snapshot(self.project)
        with self.assertRaisesRegex(kit.KitError, "Invalid owned file"):
            kit.uninstall("codex", self.project)
        self.assertEqual(initial, snapshot(self.project))

    def test_uninstall_dry_run_preserves_everything(self):
        kit.install("claude", self.project)
        initial = snapshot(self.project)
        self.assertEqual(len(kit.uninstall("claude", self.project, dry_run=True)["removed"]), 9)
        self.assertEqual(initial, snapshot(self.project))

    def test_cli_input_error_is_concise_and_nonzero(self):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/kit.py"),
                "install",
                "--target",
                "codex",
                "--project",
                str(self.project / "missing"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("does not exist", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()

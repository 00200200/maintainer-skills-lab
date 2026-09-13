import importlib.util
import json
import re
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
        self.assertTrue(skills)
        self.assertTrue(agents)
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
            for target in kit.EXPORT_TARGETS:
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


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        copy_library(self.root)

    def tearDown(self):
        self.temporary.cleanup()

    def test_grok_recipes_embed_source_and_agent_dependencies(self):
        skills, agents = kit.load_library(self.root)
        files = kit.export_files("grok-bot", self.root)
        for kind, items in (("skills", skills), ("agents", agents)):
            for name, item in items.items():
                content = files[f"{kind}/{name}.md"].decode()
                if kind == "skills":
                    self.assertIn(item["body"], content)
                else:
                    self.assertIn(item["instructions"], content)
                    for dependency in item["skills"]:
                        self.assertIn(skills[dependency]["body"], content)
        self.assertNotIn("groq", kit.EXPORT_TARGETS)

    def test_retired_groq_exports_removed_only_when_unchanged(self):
        kit.sync_providers(self.root)
        old_files = {
            "groq/README.md": b"Old Groq guide",
            "groq/skills/mkl-humanize.json": b'{"messages": []}',
            "groq/agents/mkl-writing-editor.json": b'{"messages": []}',
        }
        manifest = self.root / "providers/.manifest.json"
        state = json.loads(manifest.read_text())
        for name, data in old_files.items():
            path = self.root / "providers" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            state["files"][name] = kit.digest(data)
        manifest.write_text(json.dumps(state))
        changed = self.root / "providers/groq/skills/mkl-humanize.json"
        changed.write_text("User changes")
        before = snapshot(self.root)
        with self.assertRaisesRegex(kit.KitError, "Edited or unmanaged"):
            kit.sync_providers(self.root)
        self.assertEqual(snapshot(self.root), before)
        changed.write_bytes(old_files["groq/skills/mkl-humanize.json"])
        preview = kit.sync_providers(self.root, check=True)
        self.assertEqual(set(preview["removed"]), set(old_files))
        self.assertTrue(changed.exists())
        result = kit.sync_providers(self.root)
        self.assertEqual(set(result["removed"]), set(old_files))
        self.assertTrue(all(not (self.root / "providers" / name).exists() for name in old_files))

    def test_sync_check_is_read_only_and_repeated_sync_keeps_mtimes(self):
        initial = snapshot(self.root)
        self.assertFalse(kit.sync_providers(self.root, check=True)["up_to_date"])
        self.assertEqual(snapshot(self.root), initial)
        kit.sync_providers(self.root)
        generated = snapshot(self.root / "providers")
        manifest = json.loads(generated.pop(".manifest.json"))
        self.assertEqual(generated, kit.provider_files(self.root))
        self.assertEqual(
            manifest["files"], {name: kit.digest(data) for name, data in generated.items()}
        )
        initial = snapshot(self.root)
        mtimes = {p: p.stat().st_mtime_ns for p in self.root.rglob("*") if p.is_file()}
        for check in (True, False):
            result = kit.sync_providers(self.root, check=check)
            self.assertTrue(result["up_to_date"])
            self.assertEqual(result["written"], [])
            self.assertEqual(snapshot(self.root), initial)
            self.assertEqual(mtimes, {p: p.stat().st_mtime_ns for p in mtimes})

    def test_one_source_edit_updates_four_providers_and_dependent_agents(self):
        kit.sync_providers(self.root)
        before = snapshot(self.root / "providers")
        source = self.root / "skills/mkl-humanize/SKILL.md"
        detail = "\nPreserve the exact quotation: „Żółć, 2 MB”.\n"
        source.write_text(source.read_text() + detail)
        preview = kit.sync_providers(self.root, check=True)
        self.assertFalse(preview["up_to_date"])
        self.assertEqual(snapshot(self.root / "providers"), before)
        result = kit.sync_providers(self.root)
        expected = {
            "codex/.agents/skills/mkl-humanize/SKILL.md",
            "codex/.codex/agents/mkl-writing-editor.toml",
            "claude/.claude/skills/mkl-humanize/SKILL.md",
            "claude/.claude/agents/mkl-writing-editor.md",
            "cursor/.cursor/skills/mkl-humanize/SKILL.md",
            "cursor/.cursor/agents/mkl-writing-editor.md",
            "grok-bot/skills/mkl-humanize.md",
            "grok-bot/agents/mkl-writing-editor.md",
        }
        self.assertEqual(set(result["written"]), expected)
        after = snapshot(self.root / "providers")
        self.assertEqual(
            {name for name in before if before[name] != after[name]},
            expected | {".manifest.json"},
        )
        native = tomllib.loads(after["codex/.codex/agents/mkl-writing-editor.toml"].decode())
        self.assertIn(detail.strip(), native["developer_instructions"])
        grok = after["grok-bot/agents/mkl-writing-editor.md"].decode()
        self.assertIn(detail.strip(), grok)

    def test_removed_source_cleans_only_owned_exports(self):
        kit.sync_providers(self.root)
        note = self.root / "providers/local-notes.txt"
        note.write_text("Keep this unrelated file")
        shutil.rmtree(self.root / "skills/mkl-write-tutorial")
        result = kit.sync_providers(self.root)
        self.assertEqual(
            set(result["removed"]),
            {
                "codex/.agents/skills/mkl-write-tutorial/SKILL.md",
                "claude/.claude/skills/mkl-write-tutorial/SKILL.md",
                "cursor/.cursor/skills/mkl-write-tutorial/SKILL.md",
                "grok-bot/skills/mkl-write-tutorial.md",
            },
        )
        self.assertEqual(note.read_text(), "Keep this unrelated file")
        self.assertNotIn("mkl-write-tutorial", (self.root / "providers/README.md").read_text())

    def test_local_provider_edits_block_writes_and_obsolete_removal(self):
        kit.sync_providers(self.root)
        path = self.root / "providers/grok-bot/skills/mkl-write-tutorial.md"
        path.write_text("My edited prompt")
        for remove_source in (False, True):
            if remove_source:
                shutil.rmtree(self.root / "skills/mkl-write-tutorial")
            before = snapshot(self.root)
            with self.assertRaisesRegex(kit.KitError, "Edited or unmanaged"):
                kit.sync_providers(self.root)
            self.assertEqual(snapshot(self.root), before)

    def test_symlink_destination_and_tampered_manifest_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            destination = self.root / "providers"
            destination.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(kit.KitError, "symlink"):
                kit.sync_providers(self.root)
            self.assertEqual(list(Path(outside).iterdir()), [])
            destination.unlink()
        kit.sync_providers(self.root)
        path = self.root / "providers/.manifest.json"
        state = json.loads(path.read_text())
        state["files"]["../LICENSE"] = kit.digest((self.root / "LICENSE").read_bytes())
        path.write_text(json.dumps(state))
        before = snapshot(self.root)
        with self.assertRaisesRegex(kit.KitError, "Invalid provider manifest"):
            kit.sync_providers(self.root)
        self.assertEqual(snapshot(self.root), before)

    def test_catalogue_links_resolve_to_sources_and_exports(self):
        kit.sync_providers(self.root)
        for relative in ["README.md", *(f"{target}/README.md" for target in kit.EXPORT_TARGETS)]:
            path = self.root / "providers" / relative
            for link in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if "://" not in link:
                    self.assertTrue((path.parent / link).is_file(), (path, link))

    def test_cli_check_fails_on_drift_without_writing(self):
        script = self.root / "tools/kit.py"
        script.parent.mkdir()
        shutil.copyfile(ROOT / "tools/kit.py", script)
        command = [sys.executable, str(script), "sync", "--check"]
        before = snapshot(self.root)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertFalse(json.loads(result.stdout)["up_to_date"])
        self.assertEqual(snapshot(self.root), before)
        kit.sync_providers(self.root)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.root / "skills/mkl-humanize/SKILL.md"
        source.write_text(source.read_text() + "\nKeep the original meaning.\n")
        before = snapshot(self.root)
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(snapshot(self.root), before)


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
                exported = kit.export_files(target)
                self.assertEqual(set(result["written"]), set(exported))
                installed = snapshot(self.project)
                manifest = installed.pop(f".maintainer-skills-lab/{target}.json")
                self.assertEqual(installed, exported)
                self.assertEqual(
                    json.loads(manifest)["files"],
                    {name: kit.digest(content) for name, content in exported.items()},
                )
                kit.uninstall(target, self.project)
                self.assertEqual(snapshot(self.project), {})

    def test_dry_run_has_no_side_effects(self):
        result = kit.install("codex", self.project, dry_run=True)
        self.assertEqual(set(result["written"]), set(kit.export_files("codex")))
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
        self.assertEqual(
            set(kit.uninstall("claude", self.project, dry_run=True)["removed"]),
            set(kit.export_files("claude")),
        )
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

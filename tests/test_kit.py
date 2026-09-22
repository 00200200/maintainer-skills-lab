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


def humanizer_files(prefix):
    """Installed paths for every file in the Humanizer source folder, sorted like the kit."""
    return sorted(f"{prefix}/{name}" for name in kit.source_files(ROOT / "skills/mkl-humanize"))


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
                if target == "opencode":
                    self.assertEqual(set(parsed), {"description", "mode"})
                    self.assertEqual(parsed["mode"], "subagent")
                    self.assertEqual(parsed["description"], agent["description"])
                else:
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

    def test_sync_accepts_git_line_ending_conversion(self):
        kit.sync_providers(self.root)
        for path in (self.root / "providers").rglob("*"):
            if path.is_file():
                data = path.read_bytes().replace(b"\r\n", b"\n")
                path.write_bytes(data.replace(b"\n", b"\r\n"))
        result = kit.sync_providers(self.root, check=True)
        self.assertTrue(result["up_to_date"])
        self.assertEqual(result["written"], [])

    def test_one_source_edit_updates_all_providers_and_dependent_agents(self):
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
            "opencode/.opencode/skills/mkl-humanize/SKILL.md",
            "opencode/.opencode/agents/mkl-writing-editor.md",
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
                "opencode/.opencode/skills/mkl-write-tutorial/SKILL.md",
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

    def test_opencode_cli_preserves_config_and_unowned_agent(self):
        config = self.project / "opencode.json"
        config.write_text('{"permission":{"edit":"ask"}}\n')
        own_agent = self.project / ".opencode/agents/custom.md"
        own_agent.parent.mkdir(parents=True)
        own_agent.write_text("User-owned agent")
        original = snapshot(self.project)
        command = [sys.executable, str(ROOT / "tools/kit.py")]
        options = ["--target", "opencode", "--project", str(self.project)]
        for action in ("install", "uninstall"):
            result = subprocess.run(
                [*command, action, *options], capture_output=True, text=True, check=False
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            if action == "install":
                self.assertTrue((self.project / ".opencode/skills/mkl-humanize/SKILL.md").is_file())
                self.assertTrue((self.project / ".opencode/agents/mkl-writing-editor.md").is_file())
            self.assertEqual(config.read_bytes(), original["opencode.json"])
            self.assertEqual(own_agent.read_bytes(), original[".opencode/agents/custom.md"])
        self.assertEqual(snapshot(self.project), original)

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


class SelectedInstallationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "source"
        self.project = Path(temporary.name) / "project"
        self.root.mkdir()
        self.project.mkdir()
        copy_library(self.root)

    def test_one_skill_includes_resources_without_installing_agents_for_each_target(self):
        resource = self.root / "skills/mkl-humanize/references/style.txt"
        resource.parent.mkdir(exist_ok=True)
        resource.write_text("A supporting reference")
        for target, (skill_dir, agent_dir, _) in kit.TARGETS.items():
            with self.subTest(target=target):
                result = kit.install(target, self.project, self.root, skill_names=["mkl-humanize"])
                expected = {
                    *humanizer_files(f"{skill_dir}/mkl-humanize"),
                    f"{skill_dir}/mkl-humanize/references/style.txt",
                }
                self.assertEqual(set(result["written"]), expected)
                self.assertFalse((self.project / agent_dir).exists())
                manifest = json.loads(
                    (self.project / f".maintainer-skills-lab/{target}.json").read_text()
                )
                self.assertEqual(set(manifest["files"]), expected)
                kit.uninstall(target, self.project, skill_names=["mkl-humanize"])
                self.assertEqual(list(self.project.iterdir()), [])

    def test_adding_a_skill_preserves_other_owned_edits_and_hashes(self):
        kit.install("codex", self.project, self.root, skill_names=["mkl-humanize"])
        first = self.project / ".agents/skills/mkl-humanize/SKILL.md"
        first.write_text("My local Humanizer changes")
        mtime = first.stat().st_mtime_ns
        _, before = kit.installed_state(self.project, "codex")
        result = kit.install("codex", self.project, self.root, skill_names=["mkl-match-voice"])
        self.assertEqual(result["removed"], [])
        self.assertEqual(result["written"], [".agents/skills/mkl-match-voice/SKILL.md"])
        self.assertEqual(first.read_text(), "My local Humanizer changes")
        self.assertEqual(first.stat().st_mtime_ns, mtime)
        _, after = kit.installed_state(self.project, "codex")
        self.assertTrue(before.items() <= after.items())
        # Retaining an old hash must not hide these edits from a later full operation.
        with self.assertRaisesRegex(kit.KitError, "Locally modified"):
            kit.uninstall("codex", self.project)

    def test_selected_update_removes_obsolete_resources_but_preserves_agent_and_other_skills(self):
        resource = self.root / "skills/mkl-humanize/old.txt"
        resource.write_text("An obsolete resource")
        kit.install("claude", self.project, self.root)
        source = self.root / "skills/mkl-humanize/SKILL.md"
        source.write_text(source.read_text() + "\nA new writing constraint.\n")
        resource.unlink()
        other = self.project / ".claude/skills/mkl-match-voice/SKILL.md"
        other.write_text("Local voice guidance")
        before = snapshot(self.project)
        result = kit.install("claude", self.project, self.root, skill_names=["mkl-humanize"])
        self.assertEqual(result["removed"], [".claude/skills/mkl-humanize/old.txt"])
        self.assertEqual(result["written"], [".claude/skills/mkl-humanize/SKILL.md"])
        after = snapshot(self.project)
        for name, data in before.items():
            if not name.startswith((".claude/skills/mkl-humanize/", ".maintainer-skills-lab/")):
                self.assertEqual(after[name], data, name)
        self.assertEqual(
            (self.project / ".claude/skills/mkl-humanize/SKILL.md").read_bytes(),
            source.read_bytes(),
        )

    def test_selected_dry_runs_and_repeated_install_preserve_files_and_mtimes(self):
        names = ["mkl-humanize", "mkl-match-voice", "mkl-humanize"]
        result = kit.install("cursor", self.project, self.root, dry_run=True, skill_names=names)
        self.assertEqual(
            len(result["written"]), len(humanizer_files("")) + 1
        )  # Humanizer's files plus mkl-match-voice/SKILL.md.
        self.assertEqual(result["selected_skills"], ["mkl-humanize", "mkl-match-voice"])
        self.assertEqual(list(self.project.iterdir()), [])
        kit.install("cursor", self.project, self.root, skill_names=names)
        before = snapshot(self.project)
        mtimes = {
            path: path.stat().st_mtime_ns for path in self.project.rglob("*") if path.is_file()
        }
        result = kit.install("cursor", self.project, self.root, skill_names=names)
        self.assertEqual(result["written"], [])
        self.assertFalse(result["manifest_changed"])
        preview = kit.uninstall("cursor", self.project, dry_run=True, skill_names=["mkl-humanize"])
        self.assertEqual(preview["removed"], humanizer_files(".cursor/skills/mkl-humanize"))
        self.assertEqual(snapshot(self.project), before)
        self.assertEqual({path: path.stat().st_mtime_ns for path in mtimes}, mtimes)

    def test_selected_conflict_prevents_all_writes(self):
        conflict = self.project / ".agents/skills/mkl-match-voice/SKILL.md"
        conflict.parent.mkdir(parents=True)
        conflict.write_text("An unowned skill")
        before = snapshot(self.project)
        with self.assertRaisesRegex(kit.KitError, "conflicts"):
            kit.install(
                "codex", self.project, self.root, skill_names=["mkl-humanize", "mkl-match-voice"]
            )
        self.assertEqual(snapshot(self.project), before)
        self.assertFalse((self.project / ".maintainer-skills-lab").exists())

    def test_selected_modified_file_and_obsolete_resource_block_changes(self):
        source = self.root / "skills/mkl-humanize/old.txt"
        source.write_text("Original")
        kit.install("codex", self.project, self.root, skill_names=["mkl-humanize"])
        (self.project / ".agents/skills/mkl-humanize/old.txt").write_text("Local edits")
        source.unlink()
        before = snapshot(self.project)
        for action in (kit.install, kit.uninstall):
            with (
                self.subTest(action=action.__name__),
                self.assertRaisesRegex(kit.KitError, "refusing removal"),
            ):
                if action is kit.install:
                    action("codex", self.project, self.root, skill_names=["mkl-humanize"])
                else:
                    action("codex", self.project, skill_names=["mkl-humanize"])
            self.assertEqual(snapshot(self.project), before)

    def test_selected_uninstall_preserves_other_workflows_and_can_remove_retired_skill(self):
        similar = self.root / "skills/mkl-humanize-extra/SKILL.md"
        similar.parent.mkdir()
        similar.write_text(
            '---\nname: "mkl-humanize-extra"\ndescription: "Adjacent name fixture"\n---\nKeep me.\n'
        )
        kit.install("codex", self.project, self.root)
        shutil.rmtree(self.root / "skills/mkl-humanize")
        other = self.project / ".agents/skills/mkl-match-voice/SKILL.md"
        other.write_text("Local voice edits")
        before = snapshot(self.project)
        result = kit.uninstall("codex", self.project, skill_names=["mkl-humanize"])
        humanizer = humanizer_files(".agents/skills/mkl-humanize")
        self.assertEqual(result["removed"], humanizer)
        after = snapshot(self.project)
        for name, data in before.items():
            if name not in (*humanizer, ".maintainer-skills-lab/codex.json"):
                self.assertEqual(after[name], data, name)
        _, owned = kit.installed_state(self.project, "codex")
        self.assertNotIn(".agents/skills/mkl-humanize/SKILL.md", owned)
        self.assertIn(".agents/skills/mkl-humanize-extra/SKILL.md", owned)
        self.assertTrue(any(name.startswith(".codex/agents/") for name in owned))
        again = kit.uninstall("codex", self.project, skill_names=["mkl-humanize"])
        self.assertEqual(again["removed"], [])
        self.assertFalse(again["manifest_changed"])
        self.assertEqual(snapshot(self.project), after)

    def test_selected_identical_unmanaged_file_is_not_adopted_or_removed(self):
        destination = self.project / ".cursor/skills/mkl-humanize/SKILL.md"
        destination.parent.mkdir(parents=True)
        destination.write_bytes((self.root / "skills/mkl-humanize/SKILL.md").read_bytes())
        before = snapshot(self.project)
        result = kit.install("cursor", self.project, self.root, skill_names=["mkl-humanize"])
        self.assertEqual(result["identical_unmanaged"], [".cursor/skills/mkl-humanize/SKILL.md"])
        kit.uninstall("cursor", self.project, skill_names=["mkl-humanize"])
        self.assertEqual(snapshot(self.project), before)

    def test_invalid_and_unknown_selections_make_no_changes(self):
        for names in (
            [],
            ["../escape"],
            ["mkl-humanize/../../escape"],
            ["humanize"],
            ["mkl-missing"],
        ):
            with self.subTest(names=names), self.assertRaises(kit.KitError):
                kit.install("codex", self.project, self.root, skill_names=names)
            self.assertEqual(list(self.project.iterdir()), [])
        with self.assertRaises(kit.KitError):
            kit.uninstall("codex", self.project, skill_names=["../escape"])

    def test_full_install_after_selection_expands_to_complete_library(self):
        kit.install("claude", self.project, self.root, skill_names=["mkl-humanize"])
        kit.install("claude", self.project, self.root)
        installed = snapshot(self.project)
        installed.pop(".maintainer-skills-lab/claude.json")
        self.assertEqual(installed, kit.export_files("claude", self.root))
        kit.uninstall("claude", self.project)
        self.assertEqual(list(self.project.iterdir()), [])

    def test_cli_can_install_two_skills_then_remove_just_one(self):
        def run(action, *options):
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "tools/kit.py"),
                    action,
                    "--target",
                    "codex",
                    "--project",
                    str(self.project),
                    *options,
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)

        run("install", "--skill", "mkl-humanize", "--skill", "mkl-match-voice")
        result = run("uninstall", "--skill", "mkl-humanize")
        self.assertEqual(result["removed"], humanizer_files(".agents/skills/mkl-humanize"))
        self.assertTrue((self.project / ".agents/skills/mkl-match-voice/SKILL.md").exists())
        self.assertFalse((self.project / ".codex/agents").exists())


class MarketplaceTests(unittest.TestCase):
    """The Claude Code marketplace points at checked-in exports; it is not a client run."""

    def setUp(self):
        self.marketplace = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text())
        self.plugins = {plugin["name"]: plugin for plugin in self.marketplace["plugins"]}

    def test_plugins_use_generated_exports_and_existing_sources(self):
        self.assertEqual(set(self.plugins), {"maintainer-skills-lab", "mkl-humanize"})
        self.assertEqual(len(self.plugins), len(self.marketplace["plugins"]))
        for plugin in self.plugins.values():
            self.assertTrue(plugin["source"].startswith("./"), plugin)
            self.assertIs(plugin["strict"], False)
            self.assertTrue((ROOT / plugin["source"]).is_dir(), plugin)
        library = ROOT / self.plugins["maintainer-skills-lab"]["source"]
        self.assertEqual(library, ROOT / "providers/claude/.claude")
        self.assertEqual(
            snapshot(library),
            {
                name.removeprefix(".claude/"): data
                for name, data in kit.export_files("claude").items()
            },
        )
        humanizer = ROOT / self.plugins["mkl-humanize"]["source"]
        self.assertEqual(humanizer, ROOT / "skills/mkl-humanize")
        self.assertTrue((humanizer / "SKILL.md").is_file())

    def test_library_description_counts_match_the_source(self):
        skills, agents = kit.load_library()
        description = self.plugins["maintainer-skills-lab"]["description"]
        counts = f"{len(skills)} maintainer skills and {len(agents)} agent profiles"
        self.assertIn(counts, description)


class SkillsCliWorkflowTests(unittest.TestCase):
    """Linux CI must run the pinned Skills CLI diagnostic; this is not a client run."""

    def test_linux_ci_runs_the_pinned_skills_cli_diagnostic(self):
        workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "skills_cli_check", ROOT / "examples/skills-cli/check.py"
        )
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        self.assertIn(f"skills@{check.VERSION}", workflow)
        self.assertIn("python examples/skills-cli/check.py", workflow)
        self.assertIn("skills-cli-install-linux", workflow)


if __name__ == "__main__":
    unittest.main()

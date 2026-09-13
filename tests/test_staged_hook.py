import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class StagedHookTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="mkl hook test ")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        # A test repo must not inherit the calling hook's repository or alternate index.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull})
        for name in ("skills", "agents", "grok-bot", "providers", "hooks"):
            shutil.copytree(ROOT / name, self.root / name)
        (self.root / "tools").mkdir()
        for name in ("kit.py", "check_staged.py"):
            shutil.copyfile(ROOT / "tools" / name, self.root / "tools" / name)
        self.git("init", "-q")
        self.git("config", "user.name", "Hook fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "core.hooksPath", "hooks")
        self.git("add", ".")
        self.git("commit", "-qm", "Initial fixture")

    def run_command(self, args, *, input=None, check=True, env=None):
        return subprocess.run(
            args,
            cwd=self.root,
            env=self.env if env is None else env,
            input=input,
            capture_output=True,
            check=check,
            timeout=30,
        )

    def git(self, *args, **kwargs):
        return self.run_command(["git", *args], **kwargs).stdout

    def sync(self):
        self.run_command([sys.executable, "tools/kit.py", "sync"])

    def hook(self, *, env=None):
        return self.run_command(
            [sys.executable, "-B", "tools/check_staged.py"], check=False, env=env
        )

    def edit_source(self):
        path = self.root / "skills/mkl-humanize/SKILL.md"
        path.write_text(path.read_text() + "\nKeep the exact number 2 MB and wording „Żółć”.\n")
        return path

    def unchanged_state(self):
        return (
            (self.root / ".git/index").read_bytes(),
            {
                p.relative_to(self.root).as_posix(): p.read_bytes()
                for folder in ("skills", "agents", "providers", "grok-bot")
                for p in (self.root / folder).rglob("*")
                if p.is_file()
            },
        )

    def test_real_git_commit_blocks_unstaged_exports_then_accepts_synced_index(self):
        head = self.git("rev-parse", "HEAD")
        self.edit_source()
        self.git("add", "skills")
        self.sync()  # Working tree is correct; index is deliberately stale.
        before = self.unchanged_state()
        self.assertNotEqual(self.hook().returncode, 0)
        self.assertEqual(self.unchanged_state(), before)
        staged_before = self.git("ls-files", "--stage", "-z")
        result = self.run_command(["git", "commit", "-m", "Incomplete fixture"], check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"Staged provider exports do not match", result.stderr)
        self.assertEqual(self.git("rev-parse", "HEAD"), head)
        # Git itself refreshes index caches during commit; staged blobs and modes must stay put.
        self.assertEqual(self.git("ls-files", "--stage", "-z"), staged_before)
        self.assertEqual(self.unchanged_state()[1], before[1])
        self.git("add", "providers")
        self.git("commit", "-qm", "Complete fixture")
        self.assertNotEqual(self.git("rev-parse", "HEAD"), head)

    def test_unstaged_broken_source_does_not_override_valid_staged_content(self):
        path = self.edit_source()
        self.sync()
        self.git("add", "skills", "providers")
        path.write_text("Unstaged, unfinished frontmatter")
        before = self.unchanged_state()
        self.assertEqual(self.hook().returncode, 0)
        self.assertEqual(self.unchanged_state(), before)

    def test_deleted_skill_requires_removing_exports_and_updating_manifest(self):
        self.git("rm", "-qr", "skills/mkl-write-tutorial")
        self.assertNotEqual(self.hook().returncode, 0)
        self.sync()
        self.git("add", "providers")
        self.assertEqual(self.hook().returncode, 0)

    def test_alternate_index_is_respected_and_preserved(self):
        alternate = self.root / ".git/fixture-index"
        shutil.copyfile(self.root / ".git/index", alternate)
        env = {**self.env, "GIT_INDEX_FILE": str(alternate)}
        self.edit_source()
        self.git("add", "skills", env=env)
        before = alternate.read_bytes()
        self.assertEqual(self.hook().returncode, 0)  # Real index has no change.
        self.assertNotEqual(self.hook(env=env).returncode, 0)
        self.assertEqual(alternate.read_bytes(), before)

    def test_symlinks_and_unmerged_entries_are_rejected(self):
        path = self.root / "skills/mkl-humanize/link"
        path.symlink_to("SKILL.md")
        self.git("add", "skills")
        self.assertIn(b"regular library files", self.hook().stderr)
        self.git("reset", "-q")
        oid = self.git("rev-parse", "HEAD:skills/mkl-humanize/SKILL.md").strip()
        self.git(
            "update-index",
            "--index-info",
            input=(
                b"0 "
                + b"0" * 40
                + b"\tskills/mkl-humanize/SKILL.md\n"
                + b"100644 "
                + oid
                + b" 1\tskills/mkl-humanize/SKILL.md\n"
                + b"100644 "
                + oid
                + b" 2\tskills/mkl-humanize/SKILL.md\n"
            ),
        )
        self.assertIn(b"merge conflict", self.hook().stderr)

    def test_staged_generator_must_match_running_code(self):
        self.edit_source()
        self.git("add", "skills")
        path = self.root / "tools/kit.py"
        path.write_text(path.read_text() + "\n# Unstaged exporter edit\n")
        self.assertIn(b"differs from the running exporter", self.hook().stderr)

    def test_documentation_only_commit_skips_unstaged_library_work(self):
        self.edit_source().write_text("Unfinished")
        (self.root / "README.md").write_text("Documentation change")
        self.git("add", "README.md")
        result = self.hook()
        self.assertEqual(result.returncode, 0)
        self.assertIn(b"No library changes staged", result.stdout)

    def test_generated_manifest_is_checked_from_index(self):
        path = self.root / "providers/.manifest.json"
        state = json.loads(path.read_text())
        state["files"]["../outside"] = "a" * 64
        path.write_text(json.dumps(state))
        self.git("add", "providers/.manifest.json")
        self.assertIn(b"Invalid provider manifest", self.hook().stderr)

    def test_staged_resources_with_spaces_and_unicode_round_trip(self):
        (self.root / "skills/mkl-humanize/voice Żółć.txt").write_bytes(b"example\x00resource\n")
        self.sync()
        self.git("add", "skills", "providers")
        self.assertEqual(self.hook().returncode, 0)


if __name__ == "__main__":
    unittest.main()

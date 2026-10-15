import importlib.util
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("bump_version", ROOT / "tools/bump_version.py")
bump_version = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bump_version)


class BumpVersionUnitTests(unittest.TestCase):
    def test_semver_pattern(self):
        match = bump_version.SEMVER_PATTERN.match("v1.2.3")
        self.assertIsNotNone(match)
        self.assertEqual(match.group("major"), "1")
        self.assertEqual(match.group("minor"), "2")
        self.assertEqual(match.group("patch"), "3")

        match_no_v = bump_version.SEMVER_PATTERN.match("0.4.1")
        self.assertIsNotNone(match_no_v)
        self.assertEqual(match_no_v.group("major"), "0")
        self.assertEqual(match_no_v.group("minor"), "4")
        self.assertEqual(match_no_v.group("patch"), "1")

        self.assertIsNone(bump_version.SEMVER_PATTERN.match("invalid-tag"))

    def test_classify_commit(self):
        self.assertEqual(bump_version.classify_commit("feat: add new exporter"), "feat")
        self.assertEqual(bump_version.classify_commit("feat(skills): add mkl-bump-version"), "feat")
        self.assertEqual(bump_version.classify_commit("fix: resolve off-by-one error"), "fix")
        self.assertEqual(bump_version.classify_commit("chore: update dependencies"), "chore")
        self.assertEqual(bump_version.classify_commit("docs: update README"), "chore")
        self.assertEqual(bump_version.classify_commit("feat!: redesign CLI arguments"), "breaking")
        self.assertEqual(bump_version.classify_commit("refactor: rename core\n\nBREAKING CHANGE: api changed"), "breaking")
        self.assertEqual(bump_version.classify_commit("fix: patch bug\n\nBREAKING-CHANGE: config format"), "breaking")

    def test_calculate_bump_type(self):
        summary_breaking = {"breaking": 1, "feat": 2, "fix": 3, "chore": 1, "total_commits": 7}
        self.assertEqual(bump_version.calculate_bump_type(summary_breaking), "major")

        summary_feat = {"breaking": 0, "feat": 2, "fix": 3, "chore": 1, "total_commits": 6}
        self.assertEqual(bump_version.calculate_bump_type(summary_feat), "minor")

        summary_fix = {"breaking": 0, "feat": 0, "fix": 3, "chore": 1, "total_commits": 4}
        self.assertEqual(bump_version.calculate_bump_type(summary_fix), "patch")

        summary_empty = {"breaking": 0, "feat": 0, "fix": 0, "chore": 0, "total_commits": 0}
        self.assertIsNone(bump_version.calculate_bump_type(summary_empty))

        # Override level
        self.assertEqual(bump_version.calculate_bump_type(summary_fix, override_level="major"), "major")

    def test_bump_semver(self):
        self.assertEqual(bump_version.bump_semver("1.2.3", "major"), "2.0.0")
        self.assertEqual(bump_version.bump_semver("1.2.3", "minor"), "1.3.0")
        self.assertEqual(bump_version.bump_semver("1.2.3", "patch"), "1.2.4")
        self.assertEqual(bump_version.bump_semver("1.2.3", None), "1.2.3")
        with self.assertRaises(ValueError):
            bump_version.bump_semver("invalid", "minor")
        with self.assertRaises(ValueError):
            bump_version.bump_semver("1.2.3", "invalid-bump")

    def test_format_next_tag(self):
        self.assertEqual(bump_version.format_next_tag("1.3.0", "v1.2.0"), "v1.3.0")
        self.assertEqual(bump_version.format_next_tag("1.3.0", "1.2.0"), "1.3.0")
        self.assertEqual(bump_version.format_next_tag("1.3.0", None), "v1.3.0")

    def test_update_version_files_dry_run_and_apply(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)
            pyproject = repo_path / "pyproject.toml"
            pyproject.write_text('[project]\nname = "pkg"\nversion = "0.1.0"\ndescription = "test"\n', encoding="utf-8")

            src_init = repo_path / "src" / "pkg" / "__init__.py"
            src_init.parent.mkdir(parents=True)
            src_init.write_text('"""Init."""\n__version__ = "0.1.0"\n', encoding="utf-8")

            # Dry run: files list returned but not modified on disk
            updated = bump_version.update_version_files(repo_path, "0.2.0", apply=False)
            self.assertEqual(sorted(updated), ["pyproject.toml", "src/pkg/__init__.py"])
            self.assertIn('"0.1.0"', pyproject.read_text(encoding="utf-8"))
            self.assertIn('"0.1.0"', src_init.read_text(encoding="utf-8"))

            # Apply: files updated on disk
            updated_applied = bump_version.update_version_files(repo_path, "0.2.0", apply=True)
            self.assertEqual(sorted(updated_applied), ["pyproject.toml", "src/pkg/__init__.py"])
            self.assertIn('"0.2.0"', pyproject.read_text(encoding="utf-8"))
            self.assertIn('"0.2.0"', src_init.read_text(encoding="utf-8"))


class BumpVersionGitIntegrationTests(unittest.TestCase):
    def test_git_repo_evaluation_and_cli(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo_path = Path(tmpdir)

            # Initialize git repo
            subprocess.run(["git", "init", "-b", "main"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo_path, check=True, capture_output=True)

            pyproject = repo_path / "pyproject.toml"
            pyproject.write_text('[project]\nversion = "0.1.0"\n', encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "chore: initial commit"], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "tag", "-a", "v0.1.0", "-m", "Release v0.1.0"], cwd=repo_path, check=True, capture_output=True)

            # Add feat commit
            (repo_path / "feature.txt").write_text("feature content\n", encoding="utf-8")
            subprocess.run(["git", "add", "."], cwd=repo_path, check=True, capture_output=True)
            subprocess.run(["git", "commit", "-m", "feat: add awesome feature"], cwd=repo_path, check=True, capture_output=True)

            res = bump_version.evaluate_version_bump(repo_path, apply=False)
            self.assertEqual(res["previous_version"], "0.1.0")
            self.assertEqual(res["previous_tag"], "v0.1.0")
            self.assertEqual(res["bump_type"], "minor")
            self.assertEqual(res["next_version"], "0.2.0")
            self.assertEqual(res["next_tag"], "v0.2.0")
            self.assertEqual(res["summary"]["feat"], 1)

            # Test CLI dry run
            exit_code = bump_version.main(["--repo", str(repo_path), "--dry-run", "--json"])
            self.assertEqual(exit_code, 0)

            # Test CLI apply
            exit_code = bump_version.main(["--repo", str(repo_path), "--apply", "--json"])
            self.assertEqual(exit_code, 0)
            self.assertIn('"0.2.0"', pyproject.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

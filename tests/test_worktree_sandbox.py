"""tests/test_worktree_sandbox.py - Unit and integration tests for tools/worktree_sandbox.py."""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.worktree_sandbox import (
    apply_patch_to_worktree,
    execute_speculative_run,
    get_git_repo_root,
    is_worktree_supported,
    main,
    prune_stale_worktrees,
    shadow_worktree,
)


class TestWorktreeSandbox(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = get_git_repo_root()
        assert cls.repo_root is not None, "Tests must run inside a git repository."

    def test_git_repo_detection_and_support(self) -> None:
        self.assertIsNotNone(self.repo_root)
        assert self.repo_root is not None
        self.assertTrue(is_worktree_supported(self.repo_root))

    def test_shadow_worktree_isolation_and_cleanup(self) -> None:
        assert self.repo_root is not None
        saved_path = None
        with shadow_worktree(self.repo_root) as sandbox:
            saved_path = sandbox
            self.assertTrue(sandbox.exists())
            self.assertTrue((sandbox / ".git").exists())
            # Create a file inside worktree
            test_file = sandbox / "speculative_canary.txt"
            test_file.write_text("isolated content", encoding="utf-8")
            self.assertTrue(test_file.exists())
            # File must NOT exist in the host repository
            self.assertFalse((self.repo_root / "speculative_canary.txt").exists())

        # Once context exits, sandbox directory must be purged
        self.assertFalse(saved_path.exists())

    def test_execute_speculative_run_success(self) -> None:
        assert self.repo_root is not None
        res = execute_speculative_run(
            repo_root=self.repo_root,
            command="echo 'speculative verification passed'",
        )
        self.assertEqual(res.status, "passed")
        self.assertEqual(res.exit_code, 0)
        self.assertIn("speculative verification passed", res.stdout)
        self.assertFalse(res.patch_applied)
        self.assertFalse(Path(res.sandbox_path).exists())

    def test_execute_speculative_run_failure(self) -> None:
        assert self.repo_root is not None
        res = execute_speculative_run(
            repo_root=self.repo_root,
            command="sh -c 'exit 19'",
        )
        self.assertEqual(res.status, "failed")
        self.assertEqual(res.exit_code, 19)

    def test_execute_speculative_run_with_valid_patch(self) -> None:
        assert self.repo_root is not None
        patch_text = """--- a/.mklignore
+++ b/.mklignore
@@ -1,3 +1,4 @@
+# Speculative test canary line
 # Default context-ignore patterns for Maintainer Skills Lab.
 # Used by tools/smart_ignore.py to keep lockfiles and generated blobs out of agent context.
 
"""
        res = execute_speculative_run(
            repo_root=self.repo_root,
            command="grep 'Speculative test canary line' .mklignore",
            patch=patch_text,
        )
        self.assertEqual(res.status, "passed")
        self.assertEqual(res.exit_code, 0)
        self.assertTrue(res.patch_applied)

        # Host .mklignore must be 100% clean
        host_content = (self.repo_root / ".mklignore").read_text(encoding="utf-8")
        self.assertNotIn("Speculative test canary line", host_content)

    def test_execute_speculative_run_with_invalid_patch(self) -> None:
        assert self.repo_root is not None
        invalid_patch = """--- a/non_existent_file.xyz
+++ b/non_existent_file.xyz
@@ -1,1 +1,1 @@
-old line
+new line
"""
        res = execute_speculative_run(
            repo_root=self.repo_root,
            command="echo should not reach here",
            patch=invalid_patch,
        )
        self.assertEqual(res.status, "patch_failed")
        self.assertFalse(res.patch_applied)

    def test_execute_speculative_run_timeout(self) -> None:
        assert self.repo_root is not None
        res = execute_speculative_run(
            repo_root=self.repo_root,
            command="python3 -c 'import time; time.sleep(5)'",
            timeout=1,
        )
        self.assertEqual(res.status, "timeout")
        self.assertEqual(res.exit_code, -1)
        self.assertIn("timed out", res.stderr)

    def test_cli_run_json_output(self) -> None:
        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["run", "--cmd", "echo test_json", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertEqual(parsed["status"], "passed")
        self.assertEqual(parsed["exit_code"], 0)

    def test_cli_clean_command(self) -> None:
        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["clean", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertEqual(parsed["status"], "cleaned")

    def test_prune_stale_worktrees_direct(self) -> None:
        assert self.repo_root is not None
        pruned_result = prune_stale_worktrees(self.repo_root)
        self.assertIsNone(pruned_result)

    def test_apply_patch_to_worktree_direct(self) -> None:
        assert self.repo_root is not None
        with shadow_worktree(repo_root=self.repo_root) as sb:
            success, msg = apply_patch_to_worktree(sb, "invalid diff format")
            self.assertFalse(success)
            self.assertIn("rejected", msg.lower())


if __name__ == "__main__":
    unittest.main()

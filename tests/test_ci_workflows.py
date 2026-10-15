"""
Unit tests for GitHub Actions workflow configurations.
"""

from __future__ import annotations

import unittest
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None


WORKFLOWS_DIR = Path(__file__).resolve().parents[1] / ".github" / "workflows"


class CIWorkflowTests(unittest.TestCase):
    def test_onboarding_workflow_structure(self):
        onboarding_file = WORKFLOWS_DIR / "onboarding.yml"
        self.assertTrue(onboarding_file.exists(), "onboarding.yml should exist")

        content = onboarding_file.read_text(encoding="utf-8")
        self.assertIn("pull_request_target", content)
        self.assertIn("types: [opened]", content)
        self.assertIn("actions/github-script@v9", content)
        self.assertIn("python3 tools/kit.py check", content)
        self.assertIn("python3 tools/kit.py tokens", content)
        self.assertIn("python3 tools/kit.py sync", content)

        if yaml is not None:
            data = yaml.safe_load(content)
            self.assertIn("pull_request_target", data[True] if True in data else data["on"])
            jobs = data["jobs"]
            self.assertIn("welcome", jobs)
            welcome_job = jobs["welcome"]
            self.assertEqual(welcome_job["runs-on"], "ubuntu-latest")
            perms = welcome_job.get("permissions", {})
            self.assertEqual(perms.get("pull-requests"), "write")
            self.assertEqual(perms.get("issues"), "write")


if __name__ == "__main__":
    unittest.main()

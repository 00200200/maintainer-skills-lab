"""tests/test_pre_review_security_lint.py - Unit tests for tools/pre_review_security_lint.py."""

from __future__ import annotations

import json
import unittest

from tools.pre_review_security_lint import (
    format_compact_xml,
    is_high_entropy_secret,
    main,
    parse_unified_diff,
    scan_diff,
    scan_file_content,
    shannon_entropy,
)


class TestSecretAndEntropyDetection(unittest.TestCase):
    def test_known_secret_signatures(self) -> None:
        sample_code = """
GITHUB_TOKEN = "ghp_111122223333444455556666777788889999"
OPENAI_KEY = "sk-abcdef1234567890abcdef1234567890"
ANTHROPIC_KEY = "sk-ant-api03-abcdef1234567890abcdef1234567890"
AWS_KEY = "AKIA1234567890ABCDEF"
"""
        findings = scan_file_content("test_secrets.py", sample_code)
        rules = {f.rule for f in findings}
        self.assertIn("SEC_SECRET_GH", rules)
        self.assertIn("SEC_SECRET_OAI", rules)
        self.assertIn("SEC_SECRET_ANT", rules)
        self.assertIn("SEC_SECRET_AWS", rules)

    def test_safe_placeholder_strings_not_flagged(self) -> None:
        sample_code = """
TEST_KEY = "your-api-key-here"
DUMMY = "example_placeholder_token_for_tests"
ALL_X = "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
"""
        findings = scan_file_content("test_safe.py", sample_code)
        self.assertEqual(len(findings), 0)

    def test_shannon_entropy_calculation(self) -> None:
        low_entropy = "aaaaaaaaaaaaaaaaaaaaaaaa"
        high_entropy = "4kL9zP2wQ8mX1vR7bN3cY0tJ"
        self.assertLess(shannon_entropy(low_entropy), 1.0)
        self.assertGreater(shannon_entropy(high_entropy), 4.2)
        self.assertTrue(is_high_entropy_secret(high_entropy))
        self.assertFalse(is_high_entropy_secret(low_entropy))


class TestASTVulnerabilities(unittest.TestCase):
    def test_command_injection_subprocess_shell_true(self) -> None:
        vulnerable = """
import subprocess
def run_cmd(user_arg):
    subprocess.run("ping " + user_arg, shell=True)
"""
        safe = """
import subprocess
def run_cmd(user_arg):
    subprocess.run(["ping", user_arg], shell=False)
"""
        vuln_findings = scan_file_content("vuln.py", vulnerable)
        safe_findings = scan_file_content("safe.py", safe)

        self.assertEqual(len(vuln_findings), 1)
        self.assertEqual(vuln_findings[0].rule, "SEC001")
        self.assertEqual(len(safe_findings), 0)

    def test_os_system_injection(self) -> None:
        code = """
import os
os.system("ls -la " + path)
"""
        findings = scan_file_content("app.py", code)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "SEC002")

    def test_insecure_deserialization(self) -> None:
        code = """
import pickle, yaml
data = pickle.loads(raw_bytes)
config = yaml.load(raw_text)
"""
        findings = scan_file_content("deserial.py", code)
        rules = [f.rule for f in findings]
        self.assertEqual(rules.count("SEC003"), 2)

    def test_safe_yaml_safe_loader(self) -> None:
        code = """
import yaml
config = yaml.load(raw_text, Loader=yaml.SafeLoader)
"""
        findings = scan_file_content("safe_yaml.py", code)
        self.assertEqual(len(findings), 0)

    def test_dynamic_eval_exec(self) -> None:
        code = """
eval(user_expression)
exec(dynamic_code)
"""
        findings = scan_file_content("dynamic.py", code)
        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0].rule, "SEC004")

    def test_sql_injection_detection(self) -> None:
        vulnerable = """
def get_user(db, user_id):
    db.execute(f"SELECT * FROM users WHERE id = {user_id}")
"""
        safe = """
def get_user(db, user_id):
    db.execute("SELECT * FROM users WHERE id = ?", (user_id,))
"""
        vuln_findings = scan_file_content("db.py", vulnerable)
        safe_findings = scan_file_content("db_safe.py", safe)

        self.assertEqual(len(vuln_findings), 1)
        self.assertEqual(vuln_findings[0].rule, "SEC005")
        self.assertEqual(len(safe_findings), 0)

    def test_insecure_mktemp(self) -> None:
        code = """
import tempfile
tmp = tempfile.mktemp()
"""
        findings = scan_file_content("tmp.py", code)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "SEC006")

    def test_weak_prng_in_credential_assignment(self) -> None:
        code = """
import random
auth_token = random.choice("abcdef123456")
"""
        findings = scan_file_content("auth.py", code)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "SEC007")


class TestDiffInspection(unittest.TestCase):
    def test_parse_unified_diff(self) -> None:
        diff = """
--- a/app.py
+++ b/app.py
@@ -10,3 +10,4 @@ def handler():
     x = 1
+    subprocess.run("ls", shell=True)
     return x
"""
        parsed = parse_unified_diff(diff)
        self.assertIn("app.py", parsed)
        added_lines = parsed["app.py"]
        self.assertEqual(len(added_lines), 1)
        self.assertEqual(added_lines[0][0], 11)
        self.assertIn("shell=True", added_lines[0][1])

    def test_diff_scans_only_added_lines(self) -> None:
        diff = """
--- a/app.py
+++ b/app.py
@@ -1,5 +1,6 @@
 def existing_safe_code():
     return 42
+    gh_key = "ghp_111122223333444455556666777788889999"
"""
        findings = scan_diff(diff)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].rule, "SEC_SECRET_GH")
        self.assertEqual(findings[0].line, 3)


class TestFormattingAndCLI(unittest.TestCase):
    def test_format_compact_xml_clean(self) -> None:
        xml = format_compact_xml([])
        self.assertEqual(xml, '<security_preflight status="CLEAN" findings="0"/>')

    def test_format_compact_xml_flagged(self) -> None:
        findings = scan_file_content("sec.py", "subprocess.run('cmd', shell=True)")
        xml = format_compact_xml(findings)
        self.assertIn('<security_preflight status="FLAGGED" findings="1">', xml)
        self.assertIn('rule="SEC001"', xml)

    def test_cli_json_output(self) -> None:
        import io
        from unittest.mock import patch

        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["--file", "tools/pre_review_security_lint.py", "--json"])
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertIsInstance(parsed, list)


if __name__ == "__main__":
    unittest.main()

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/mkl-humanize/scripts/check_facts.py"
spec = importlib.util.spec_from_file_location("check_facts", SCRIPT)
check_facts = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_facts)


def changes(source, rewrite):
    return [
        (item["kind"], item["change"], item["value"])
        for item in check_facts.compare(source, rewrite)
    ]


class FactCheckTests(unittest.TestCase):
    def test_skill_worked_example_is_preserved(self):
        skill = (ROOT / "skills/mkl-humanize/SKILL.md").read_text(encoding="utf-8")
        source = re.search(r'^Source: "(.+)"$', skill, re.M)[1]
        edit = re.search(r'^One suitable edit: "(.+)"$', skill, re.M)[1]
        self.assertEqual(changes(source, edit), [])

    def test_overclaiming_rewrite_loses_numbers_and_limits(self):
        source = (
            "In our 20-file fixture on Linux, a repeated install wrote 0 files. We have not "
            "tested Windows, and this result does not measure installation speed."
        )
        natural = (
            "In our 20-file fixture on Linux, running the installer again wrote 0 files. "
            "We have not tested Windows. This result does not measure installation speed."
        )
        self.assertEqual(changes(source, natural), [])
        self.assertEqual(
            changes(source, "The installer now offers instant installation on every platform."),
            [
                ("number", "dropped", "0"),
                ("number", "dropped", "20"),
                ("negation", "dropped", "not"),
            ],
        )

    def test_code_urls_placeholders_and_quotations_are_exact(self):
        source = (
            'Run `kit.py sync`, then read https://example.org/docs. The "Save" button '
            "fails above {max_mb} MB in 50% of runs.\n\n```sh\npython3 -B tools/kit.py\n```\n"
        )
        rewrite = (
            "Read https://example.org/docs and run `kit.py  sync`. “Save” fails above "
            "{max_size} MB in half of our runs.\n\n```sh\npython3 -B tools/kit.py\n```\n"
        )
        self.assertEqual(
            changes(source, rewrite),
            [
                ("code", "added", "`kit.py  sync`"),
                ("code", "dropped", "`kit.py sync`"),
                ("placeholder", "dropped", "{max_mb}"),
                ("placeholder", "added", "{max_size}"),
                ("number", "dropped", "50%"),
            ],
        )

    def test_added_statistics_and_changed_uncertainty_are_reported(self):
        self.assertEqual(
            changes("The cache may help large projects.", "The cache makes builds 3 times faster."),
            [("number", "added", "3"), ("hedge", "dropped", "may")],
        )
        self.assertEqual(
            changes("To prawdopodobnie nie zadziała.", "To zadziała."),
            [("negation", "dropped", "nie"), ("hedge", "dropped", "prawdopodobnie")],
        )

    def test_scientific_and_leading_decimal_changes_are_reported(self):
        for before, after in (
            ("1e3", "1e6"),
            ("1.5E-3", "1.5E+3"),
            (".5", ".8"),
            ("-.5", ".5"),
            ("0,5", "0,8"),
        ):
            with self.subTest(before=before, after=after):
                self.assertCountEqual(
                    changes(f"Value: {before}.", f"Value: {after}."),
                    [("number", "dropped", before), ("number", "added", after)],
                )
                self.assertEqual(changes(f"Value: {before}.", f"The value is {before}."), [])

    def test_word_boundaries_and_apostrophes(self):
        self.assertEqual(
            changes("We don’t cache notable files.", "We don't cache notable files."), []
        )
        self.assertEqual(changes("Nothing is cached.", "Nothing gets cached."), [])
        self.assertEqual(
            changes("It cannot run offline.", "It runs offline."),
            [("negation", "dropped", "cannot")],
        )

    def test_plain_long_options_are_preserved_and_changes_are_reported(self):
        self.assertEqual(
            changes("Run installer --dry-run.", "Run installer --force."),
            [("flag", "dropped", "--dry-run"), ("flag", "added", "--force")],
        )
        self.assertEqual(changes("Try --dry-run.", "Use --dry-run to preview."), [])
        self.assertEqual(
            changes("Set --limit=20.", "Set --limit=30."),
            [("number", "dropped", "20"), ("number", "added", "30")],
        )
        self.assertEqual(
            changes("Pass --dry-run twice: --dry-run.", "Pass --dry-run twice."),
            [("flag", "dropped", "--dry-run")],
        )

    def test_long_options_do_not_double_count_code_urls_or_prose_words(self):
        self.assertEqual(
            changes("Use `--dry-run`.", "Use `--force`."),
            [("code", "dropped", "`--dry-run`"), ("code", "added", "`--force`")],
        )
        evidence = check_facts.evidence(
            "Read https://example.org/--flag and `--code`. word--suffix ---rule /--path"
        )
        self.assertEqual(evidence["flag"], {})
        self.assertEqual(check_facts.evidence("Use --only --no-cache.")["hedge"], {})

    def test_cli_exit_status_and_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / "source.md").write_text("Tested on 2 systems; Windows is not tested.")
            (directory / "same.md").write_text("We tested 2 systems. Windows is not tested.")
            (directory / "lost.md").write_text("Tested everywhere.")

            def run(*args):
                return subprocess.run(
                    [sys.executable, str(SCRIPT), *args],
                    cwd=directory,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )

            self.assertEqual(run("source.md", "same.md").returncode, 0)
            lost = run("source.md", "lost.md", "--json")
            self.assertEqual(lost.returncode, 1, lost.stderr)
            report = json.loads(lost.stdout)
            self.assertEqual(report["status"], "review")
            self.assertEqual(
                [(item["kind"], item["value"]) for item in report["differences"]],
                [("number", "2"), ("negation", "not")],
            )
            missing = run("missing.md", "same.md")
            self.assertEqual(missing.returncode, 2)
            self.assertIn("check_facts:", missing.stderr)


if __name__ == "__main__":
    unittest.main()

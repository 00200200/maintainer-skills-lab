"""tests/test_gh_compact_fetch.py - Unit tests for tools/gh_compact_fetch.py."""

from __future__ import annotations

import json
import unittest

from tools.gh_compact_fetch import (
    format_markdown,
    is_bot_user,
    parse_target,
    process_thread_data,
    run_compact_fetch,
    strip_quoted_replies,
    strip_signatures,
)


class TestTargetParsing(unittest.TestCase):
    def test_parse_hash_syntax(self) -> None:
        owner, repo, num, kind = parse_target("00200200/maintainer-skills-lab#128")
        self.assertEqual(owner, "00200200")
        self.assertEqual(repo, "maintainer-skills-lab")
        self.assertEqual(num, 128)
        self.assertEqual(kind, "issue")

    def test_parse_space_syntax(self) -> None:
        owner, repo, num, kind = parse_target("owner/repo 42", kind="pr")
        self.assertEqual(owner, "owner")
        self.assertEqual(repo, "repo")
        self.assertEqual(num, 42)
        self.assertEqual(kind, "pr")

    def test_parse_issue_url(self) -> None:
        owner, repo, num, kind = parse_target("https://github.com/facebook/react/issues/1000")
        self.assertEqual(owner, "facebook")
        self.assertEqual(repo, "react")
        self.assertEqual(num, 1000)
        self.assertEqual(kind, "issue")

    def test_parse_pr_url(self) -> None:
        owner, repo, num, kind = parse_target("https://github.com/psf/requests/pull/2000")
        self.assertEqual(owner, "psf")
        self.assertEqual(repo, "requests")
        self.assertEqual(num, 2000)
        self.assertEqual(kind, "pr")

    def test_parse_invalid(self) -> None:
        with self.assertRaises(ValueError):
            parse_target("invalid_target_without_number")


class TestBotDetection(unittest.TestCase):
    def test_known_bots(self) -> None:
        self.assertTrue(is_bot_user("codecov[bot]"))
        self.assertTrue(is_bot_user("dependabot"))
        self.assertTrue(is_bot_user("dependabot[bot]"))
        self.assertTrue(is_bot_user("app/dependabot"))
        self.assertTrue(is_bot_user("github-actions[bot]"))
        self.assertTrue(is_bot_user("stale[bot]"))
        self.assertTrue(is_bot_user("custom-ci-bot"))

    def test_human_users(self) -> None:
        self.assertFalse(is_bot_user("alice"))
        self.assertFalse(is_bot_user("bob_developer"))
        self.assertFalse(is_bot_user("maintainer123"))
        self.assertFalse(is_bot_user(None))


class TestTextCompaction(unittest.TestCase):
    def test_strip_quoted_replies(self) -> None:
        text = (
            "I agree with the proposed fix.\n\n"
            "On Mon, Oct 15, 2026, John Doe wrote:\n"
            "> Here is the original message that is being quoted.\n"
            "> It goes on for multiple lines.\n"
        )
        cleaned = strip_quoted_replies(text)
        self.assertIn("I agree with the proposed fix.", cleaned)
        self.assertNotIn("Here is the original message", cleaned)
        self.assertNotIn("On Mon, Oct 15", cleaned)

    def test_strip_blockquotes_outside_code_blocks(self) -> None:
        text = (
            "> Some email quote\nActual content\n```python\n# code block\n> not a blockquote\n```"
        )
        cleaned = strip_quoted_replies(text)
        self.assertNotIn("Some email quote", cleaned)
        self.assertIn("Actual content", cleaned)
        self.assertIn("> not a blockquote", cleaned)

    def test_strip_signatures(self) -> None:
        text = "Thanks for reviewing!\n\nSent from my iPhone\n"
        cleaned = strip_signatures(text)
        self.assertIn("Thanks for reviewing!", cleaned)
        self.assertNotIn("Sent from my iPhone", cleaned)

    def test_strip_dash_delimiter_signature(self) -> None:
        text = (
            "Here is the log output.\n-- \nJane Smith\nSenior Infrastructure Architect\nACME Corp\n"
        )
        cleaned = strip_signatures(text)
        self.assertIn("Here is the log output.", cleaned)
        self.assertNotIn("Senior Infrastructure Architect", cleaned)


class TestThreadProcessing(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_issue_response = {
            "data": {
                "repository": {
                    "issue": {
                        "title": "Fix memory leak in parser",
                        "state": "OPEN",
                        "createdAt": "2026-10-15T12:00:00Z",
                        "author": {"login": "alice"},
                        "authorAssociation": "CONTRIBUTOR",
                        "body": "When parsing deep trees, memory increases monotonically.\n\nSent from my iPhone",
                        "labels": {"nodes": [{"name": "bug"}, {"name": "perf"}]},
                        "comments": {
                            "nodes": [
                                {
                                    "createdAt": "2026-10-15T12:05:00Z",
                                    "author": {"login": "codecov[bot]"},
                                    "authorAssociation": "NONE",
                                    "body": "## Coverage Report\n| File | Coverage |\n| --- | --- |\n| parser.py | 88% |",
                                },
                                {
                                    "createdAt": "2026-10-15T12:10:00Z",
                                    "author": {"login": "bob"},
                                    "authorAssociation": "MEMBER",
                                    "body": (
                                        "Reproduced. The cycle is in `Node.parent`.\n\n"
                                        "On Mon, Oct 15, 2026 at 12:00 PM alice wrote:\n"
                                        "> When parsing deep trees..."
                                    ),
                                },
                            ]
                        },
                    }
                }
            }
        }

    def test_process_issue_filters_bot_and_quotes(self) -> None:
        processed = process_thread_data(
            self.mock_issue_response,
            kind="issue",
            owner="org",
            repo="repo",
            number=42,
            exclude_bots=True,
            strip_quotes=True,
            strip_sigs=True,
        )

        self.assertEqual(processed["title"], "Fix memory leak in parser")
        self.assertEqual(processed["author"], "alice")
        self.assertNotIn("Sent from my iPhone", processed["body"])
        self.assertEqual(processed["labels"], ["bug", "perf"])
        self.assertEqual(len(processed["comments"]), 1)
        self.assertEqual(processed["comments"][0]["author"], "bob")
        self.assertIn(
            "Reproduced. The cycle is in `Node.parent`.", processed["comments"][0]["body"]
        )
        self.assertNotIn("On Mon, Oct 15", processed["comments"][0]["body"])
        self.assertEqual(processed["omitted_bots"], ["@codecov[bot]"])

    def test_format_markdown_output(self) -> None:
        processed = process_thread_data(
            self.mock_issue_response,
            kind="issue",
            owner="org",
            repo="repo",
            number=42,
            exclude_bots=True,
        )
        md = format_markdown(processed)
        self.assertIn("# [Issue #42] Fix memory leak in parser", md)
        self.assertIn("**Author**: @alice (CONTRIBUTOR)", md)
        self.assertIn("**Labels**: bug, perf", md)
        self.assertIn("1 human comments, 1 bot comments omitted: @codecov[bot]", md)
        self.assertIn("**@bob** (MEMBER)", md)

    def test_run_compact_fetch_with_mock_and_stats(self) -> None:
        output_str, stats = run_compact_fetch(
            target="org/repo#42",
            mock_data=self.mock_issue_response,
            show_stats=True,
        )
        self.assertIsNotNone(stats)
        assert stats is not None
        self.assertGreater(stats["raw_tokens"], stats["compact_tokens"])
        self.assertIn("Token Efficiency Stats", output_str)

    def test_run_compact_fetch_json(self) -> None:
        output_str, _ = run_compact_fetch(
            target="org/repo#42",
            mock_data=self.mock_issue_response,
            as_json=True,
        )
        parsed = json.loads(output_str)
        self.assertEqual(parsed["number"], 42)
        self.assertEqual(parsed["author"], "alice")
        self.assertEqual(len(parsed["comments"]), 1)


if __name__ == "__main__":
    unittest.main()

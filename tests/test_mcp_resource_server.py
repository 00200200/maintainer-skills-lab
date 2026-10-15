"""tests/test_mcp_resource_server.py - Unit tests for tools/mcp_resource_server.py."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.mcp_resource_server import (
    McpResourceServer,
    generate_client_config,
    index_skills,
    main,
    parse_skill_file,
    resolve_doc_resource,
)


class TestMcpResourceServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.repo_root = Path(__file__).resolve().parent.parent

    def setUp(self) -> None:
        self.server = McpResourceServer(self.repo_root)

    def test_index_skills_finds_repo_skills(self) -> None:
        skills = index_skills(self.repo_root)
        self.assertGreaterEqual(len(skills), 20)
        self.assertIn("mkl-review-pr", skills)
        self.assertIn("mkl-fix-type-errors", skills)
        self.assertIn("mkl-humanize", skills)

        review_pr = skills["mkl-review-pr"]
        self.assertEqual(review_pr.uri, "mkl://skills/mkl-review-pr")
        self.assertIn("review", review_pr.description.lower())
        self.assertTrue(len(review_pr.body) > 50)

    def test_parse_skill_file(self) -> None:
        skill_path = self.repo_root / "skills" / "mkl-humanize" / "SKILL.md"
        res = parse_skill_file(skill_path)
        self.assertIsNotNone(res)
        assert res is not None
        self.assertEqual(res.name, "mkl-humanize")
        self.assertEqual(res.uri, "mkl://skills/mkl-humanize")

    def test_handle_initialize(self) -> None:
        resp = self.server.dispatch(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertEqual(resp["id"], 1)
        res = resp["result"]
        self.assertEqual(res["protocolVersion"], "2024-11-05")
        self.assertEqual(res["serverInfo"]["name"], "maintainer-skills-lab")
        self.assertTrue(res["capabilities"]["resources"])
        self.assertTrue(res["capabilities"]["prompts"])

    def test_handle_ping(self) -> None:
        resp = self.server.dispatch({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertEqual(resp["id"], 2)
        self.assertEqual(resp["result"], {})

    def test_handle_resources_list(self) -> None:
        resp = self.server.dispatch(
            {"jsonrpc": "2.0", "id": 3, "method": "resources/list", "params": {}}
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        resources = resp["result"]["resources"]
        self.assertGreaterEqual(len(resources), 20)
        uris = [r["uri"] for r in resources]
        self.assertIn("mkl://skills/mkl-review-pr", uris)
        self.assertIn("mkl://skills/mkl-triage-issue", uris)
        self.assertIn("mkl://skills/mkl-fix-type-errors", uris)

    def test_handle_resources_read_valid(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "resources/read",
            "params": {"uri": "mkl://skills/mkl-review-pr"},
        }
        resp = self.server.dispatch(req)
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertNotIn("error", resp)
        contents = resp["result"]["contents"]
        self.assertEqual(len(contents), 1)
        self.assertEqual(contents[0]["uri"], "mkl://skills/mkl-review-pr")
        self.assertEqual(contents[0]["mimeType"], "text/markdown")
        self.assertIn("Review a pull request", contents[0]["text"])

    def test_handle_resources_read_unknown_skill(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "resources/read",
            "params": {"uri": "mkl://skills/non-existent-skill-xyz"},
        }
        resp = self.server.dispatch(req)
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertIn("error", resp)
        self.assertEqual(resp["error"]["code"], -32602)

    def test_handle_resources_read_path_traversal_guarded(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "resources/read",
            "params": {"uri": "mkl://docs/../../etc/passwd"},
        }
        resp = self.server.dispatch(req)
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertIn("error", resp)

    def test_handle_prompts_list(self) -> None:
        resp = self.server.dispatch(
            {"jsonrpc": "2.0", "id": 7, "method": "prompts/list", "params": {}}
        )
        self.assertIsNotNone(resp)
        assert resp is not None
        prompts = resp["result"]["prompts"]
        self.assertGreaterEqual(len(prompts), 20)
        names = [p["name"] for p in prompts]
        self.assertIn("mkl-review-pr", names)

    def test_handle_prompts_get(self) -> None:
        req = {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "prompts/get",
            "params": {
                "name": "mkl-fix-type-errors",
                "arguments": {"context": "src/processor.py:42 error union-attr"},
            },
        }
        resp = self.server.dispatch(req)
        self.assertIsNotNone(resp)
        assert resp is not None
        result = resp["result"]
        messages = result["messages"]
        self.assertEqual(len(messages), 1)
        text = messages[0]["content"]["text"]
        self.assertIn("Fix static type checker errors", text)
        self.assertIn("src/processor.py:42 error union-attr", text)

    def test_dispatch_unknown_method(self) -> None:
        req = {"jsonrpc": "2.0", "id": 9, "method": "unknown/method", "params": {}}
        resp = self.server.dispatch(req)
        self.assertIsNotNone(resp)
        assert resp is not None
        self.assertEqual(resp["error"]["code"], -32601)

    def test_dispatch_notification_returns_none(self) -> None:
        # Notifications do not have 'id'
        req = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
        resp = self.server.dispatch(req)
        self.assertIsNone(resp)

    def test_generate_client_config(self) -> None:
        for target in ("claude", "cursor", "zed"):
            cfg_str = generate_client_config(target, self.repo_root)
            parsed = json.loads(cfg_str)
            self.assertIsInstance(parsed, dict)

    def test_resolve_doc_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            docs_dir = temp_root / "docs"
            docs_dir.mkdir()
            test_doc = docs_dir / "architecture.md"
            test_doc.write_text("# Architecture Guide\n\nContent here.", encoding="utf-8")

            res = resolve_doc_resource(temp_root, "architecture.md")
            self.assertIsNotNone(res)
            assert res is not None
            self.assertEqual(res[0], "Architecture")
            self.assertIn("Content here.", res[1])

            # Traversal attempt
            self.assertIsNone(resolve_doc_resource(temp_root, "../secret.txt"))

    def test_cli_generate_config(self) -> None:
        f = io.StringIO()
        with patch("sys.stdout", f):
            code = main(["--generate-config", "claude"])
        self.assertEqual(code, 0)
        parsed = json.loads(f.getvalue())
        self.assertIn("mcpServers", parsed)
        self.assertIn("maintainer-skills-lab", parsed["mcpServers"])


if __name__ == "__main__":
    unittest.main()

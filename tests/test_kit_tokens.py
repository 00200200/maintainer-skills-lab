import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("kit", ROOT / "tools/kit.py")
kit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(kit)


class KitTokensTests(unittest.TestCase):
    def test_count_tokens_empty_and_text(self):
        self.assertEqual(kit.count_tokens(""), 0)
        self.assertGreater(kit.count_tokens("hello world"), 0)

    def test_profile_tokens_structure(self):
        profile = kit.profile_tokens()
        self.assertIn("encoding", profile)
        self.assertIn("skills", profile)
        self.assertIn("agents", profile)
        self.assertIn("targets", profile)
        self.assertIn("summary", profile)

        # Check skills structure
        self.assertGreater(len(profile["skills"]), 0)
        first_skill = profile["skills"][0]
        self.assertIn("name", first_skill)
        self.assertIn("tokens", first_skill)
        self.assertIn("body_tokens", first_skill)
        self.assertIn("desc_tokens", first_skill)
        self.assertIn("desc_characters", first_skill)
        self.assertIn("warnings", first_skill)

        # Check summary metrics (Tony Dzi's floor and ceiling)
        sm = profile["summary"]
        self.assertIn("names_only_floor_tokens", sm)
        self.assertIn("descriptions_ceiling_tokens", sm)
        self.assertIn("skills_total_tokens", sm)
        self.assertGreater(sm["skills_total_tokens"], sm["descriptions_ceiling_tokens"])
        self.assertGreater(sm["descriptions_ceiling_tokens"], sm["names_only_floor_tokens"])

    def test_profile_tokens_sorting(self):
        by_desc = kit.profile_tokens(sort_by="desc-tokens")
        desc_tokens = [s["desc_tokens"] for s in by_desc["skills"]]
        self.assertEqual(desc_tokens, sorted(desc_tokens, reverse=True))

        by_tokens = kit.profile_tokens(sort_by="tokens")
        tokens = [s["tokens"] for s in by_tokens["skills"]]
        self.assertEqual(tokens, sorted(tokens, reverse=True))

        by_name = kit.profile_tokens(sort_by="name")
        names = [s["name"] for s in by_name["skills"]]
        self.assertEqual(names, sorted(names))

    def test_profile_tokens_target_filter(self):
        profile_claude = kit.profile_tokens(target="claude")
        self.assertEqual(list(profile_claude["targets"].keys()), ["claude"])

    def test_format_tokens_table(self):
        profile = kit.profile_tokens()
        formatted = kit.format_tokens_table(profile)
        self.assertIn("Maintainer Skills Lab — Token Profiler", formatted)
        self.assertIn("Floor Context (names only):", formatted)
        self.assertIn("Target Export Bundles:", formatted)

    def test_cli_tokens_subcommand_stdout_and_json(self):
        import io
        from unittest.mock import patch

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = kit.main(["tokens"])
            self.assertEqual(code, 0)
            output = mock_out.getvalue()
            self.assertIn("Maintainer Skills Lab — Token Profiler", output)

        with patch("sys.stdout", new_callable=io.StringIO) as mock_out:
            code = kit.main(["tokens", "--json", "--target", "cursor"])
            self.assertEqual(code, 0)
            parsed = json.loads(mock_out.getvalue())
            self.assertIn("skills", parsed)
            self.assertEqual(list(parsed["targets"].keys()), ["cursor"])


if __name__ == "__main__":
    unittest.main()

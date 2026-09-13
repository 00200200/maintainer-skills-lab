import importlib.util
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "repo_stats", Path(__file__).resolve().parents[1] / "tools/repo_stats.py"
)
stats = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stats)


class RepositoryStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.repo = {"stargazers_count": 0, "forks_count": 0, "created_at": "2026-09-13T00:00:00Z"}
        self.traffic = {
            "count": 0,
            "uniques": 0,
            "views": [{"timestamp": "2026-09-13T00:00:00Z", "count": 0, "uniques": 0}],
        }

    def test_zero_traffic_and_no_stars_render_without_invented_activity(self):
        result = stats.aggregate(self.repo, [[]], self.traffic, "2026-09-13")
        self.assertEqual(result["views"]["count"], 0)
        self.assertEqual(result["current_stargazers_by_date"], {})
        svg = ET.fromstring(stats.render(result))
        self.assertEqual(svg.findall(".//{http://www.w3.org/2000/svg}circle"), [])

    def test_missing_traffic_is_not_treated_as_zero(self):
        for traffic in ({}, {"count": 0, "uniques": 0, "views": []}):
            with self.assertRaises(ValueError):
                stats.aggregate(self.repo, [[]], traffic, "2026-09-13")

    def test_all_star_pages_aggregate_without_retaining_identities(self):
        self.repo["stargazers_count"] = 3
        pages = [
            [{"starred_at": "2026-09-13T01:00:00Z", "user": {"login": "private-name"}}],
            [{"starred_at": "2026-09-13T02:00:00Z"}, {"starred_at": "2026-09-14T02:00:00Z"}],
        ]
        result = stats.aggregate(self.repo, pages, self.traffic, "2026-09-14")
        self.assertEqual(result["current_stargazers_by_date"], {"2026-09-13": 2, "2026-09-14": 1})
        self.assertNotIn("private-name", str(result))
        ET.fromstring(stats.render(result))
        self.repo["stargazers_count"] = 4
        with self.assertRaisesRegex(ValueError, "changed during collection"):
            stats.aggregate(self.repo, pages, self.traffic, "2026-09-14")


if __name__ == "__main__":
    unittest.main()

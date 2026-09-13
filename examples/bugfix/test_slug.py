import unittest

from slug import slugify


class SlugRegression(unittest.TestCase):
    def test_reported_title(self):
        self.assertEqual(slugify("Hello,   World!"), "hello-world")

    def test_public_behavior(self):
        for title, expected in [
            ("Already", "already"),
            ("  Two\twords\n", "two-words"),
            ("Version 2.0", "version-20"),
            ("", ""),
        ]:
            with self.subTest(title=title):
                self.assertEqual(slugify(title), expected)

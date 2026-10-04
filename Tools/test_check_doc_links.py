"""Unit tests for check_doc_links.py.  python Tools/test_check_doc_links.py"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_doc_links as cdl  # noqa: E402


class SlugTests(unittest.TestCase):
    def test_slug_matches_github(self):
        cases = [
            ("Auto-Translation", "auto-translation"),
            ("Option A — Batch file launcher (recommended for most users)",
             "option-a--batch-file-launcher-recommended-for-most-users"),
            ("`Ctrl+Del` key", "ctrldel-key"),
            ("Latviešu valoda", "latviešu-valoda"),
        ]
        for heading, slug in cases:
            with self.subTest(heading=heading):
                self.assertEqual(cdl.github_slug(heading), slug)


class AnchorTests(unittest.TestCase):
    def test_repeated_heading_gets_numbered_anchor(self):
        self.assertEqual(cdl.anchors("## Backup\n\n### Backup\n"), {"backup", "backup-1"})

    def test_heading_inside_code_fence_is_ignored(self):
        self.assertEqual(cdl.anchors("## Real\n```\n## Fake\n```\n"), {"real"})


class CheckFileTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "docs").mkdir()
        (self.root / "docs" / "FEATURES.md").write_text("# F\n\n## Backup\n", encoding="utf-8")
        (self.root / "img.png").write_bytes(b"x")

    def tearDown(self):
        self._tmp.cleanup()

    def _check(self, body):
        readme = self.root / "README.md"
        readme.write_text("# R\n\n## Here\n\n" + body + "\n", encoding="utf-8")
        return cdl.check_file(readme)

    def test_valid_links_pass(self):
        body = ('[a](docs/FEATURES.md#backup) [b](#here) <img src="img.png"> '
                '[c](https://example.invalid/nope)')
        self.assertEqual(self._check(body), [])

    def test_each_broken_target_is_reported(self):
        cases = [
            ("[a](docs/NOPE.md)", "README.md: missing file docs/NOPE.md"),
            ("[a](docs/FEATURES.md#nope)", "README.md: missing anchor docs/FEATURES.md#nope"),
            ("[a](#nope)", "README.md: missing anchor #nope"),
            ('<source srcset="gone.png">', "README.md: missing file gone.png"),
        ]
        for body, expected in cases:
            with self.subTest(body=body):
                self.assertEqual(self._check(body), [expected])

    def test_link_in_code_span_is_ignored(self):
        self.assertEqual(self._check("`[a](docs/NOPE.md)`"), [])


class MissingHeadingTests(unittest.TestCase):
    def test_table_of_contents_is_not_required(self):
        old = "## Table of Contents\n## Backup\n"
        self.assertEqual(cdl.missing_headings(old, ["## Backup\n"]), [])

    def test_missing_heading_is_reported(self):
        old = "## Backup\n## Themes\n"
        self.assertEqual(cdl.missing_headings(old, ["## Backup\n"]), ["Themes"])


if __name__ == "__main__":
    unittest.main()

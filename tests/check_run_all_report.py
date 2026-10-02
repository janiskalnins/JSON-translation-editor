"""Check for tests/run_all.py's saved report: the Markdown text built from check results, the
timestamped file plus latest.md in tests/reports/, pruning to the newest REPORTS_KEEP, and a
failed write that never changes the runner's exit code. Uses made-up results, so it never runs
the real checks.

Run:  python tests/check_run_all_report.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: scratch working folder, isolated caches

import io
import sys
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest import mock

import run_all

META = {"time": "2026-09-27 14:05:33", "trigger": "pre-commit", "selection": "all checks",
        "branch": "core-tests", "commit": "1421aef docs: core suites", "uncommitted": "no",
        "python": "3.14.3", "pyside6": "6.11.2"}
PASSING = run_all.CheckResult("check_core_xml", "PASS", 0.52, "54 test(s) run\nPASSED: 0 failure(s)\n")
FAILING = run_all.CheckResult("check_scrollbar", "FAIL", 1.25,
                              "noise\nFAIL handle overlaps arrow\nFAILED: 1 failure(s)\n")
NOW = datetime(2026, 9, 27, 14, 5, 33)


def _report(results) -> str:
    return run_all.build_report(results, META, 25.4)


class TestsRunTests(unittest.TestCase):
    def test_count_is_read_from_the_output(self):
        self.assertEqual(run_all.tests_run(PASSING.output), 54)

    def test_count_is_read_from_crlf_output(self):
        # A check's print() reaches the runner's pipe as CRLF on Windows.
        self.assertEqual(run_all.tests_run("54 test(s) run\r\nPASSED: 0 failure(s)\r\n"), 54)

    def test_output_without_a_count_gives_none(self):
        self.assertIsNone(run_all.tests_run(FAILING.output))


class BuildReportTests(unittest.TestCase):
    def test_header_names_the_trigger(self):
        self.assertIn("- **Trigger:** pre-commit", _report([PASSING]))

    def test_header_names_the_commit(self):
        self.assertIn("- **Commit:** 1421aef docs: core suites", _report([PASSING]))

    def test_summary_counts_passed_and_failed(self):
        self.assertIn("**1 passed, 1 failed** (25.4 s)", _report([PASSING, FAILING]))

    def test_table_row_holds_result_time_and_test_count(self):
        self.assertIn("| check_core_xml | PASS | 0.5 s | 54 |", _report([PASSING]))

    def test_check_without_a_count_shows_a_dash(self):
        self.assertIn("| check_scrollbar | FAIL | 1.2 s | — |", _report([FAILING]))

    def test_all_passed_has_no_failures_section(self):
        self.assertNotIn("## Failures", _report([PASSING]))

    def test_notes_section_lists_each_note_under_its_check(self):
        noted = run_all.CheckResult("check_core_corpus", "PASS", 2.0,
                                    "NOTE big.xml: 11024 strings\r\n6 test(s) run\r\n")
        self.assertIn("## Notes\n\n### check_core_corpus\n\n- big.xml: 11024 strings\n",
                      _report([PASSING, noted]))

    def test_no_notes_means_no_notes_section(self):
        self.assertNotIn("## Notes", _report([PASSING]))

    def test_failures_section_holds_the_failure_lines(self):
        self.assertIn("### check_scrollbar\n\n```\nFAIL handle overlaps arrow\n```",
                      _report([PASSING, FAILING]))


class WriteReportTests(unittest.TestCase):
    def test_report_is_written_under_a_timestamped_name(self):
        path = run_all.write_report("text", cs.temp_dir(), NOW)
        self.assertEqual(path.name, "run_2026-09-27_14-05-33.md")

    def test_report_file_holds_the_text(self):
        path = run_all.write_report("text", cs.temp_dir(), NOW)
        self.assertEqual(path.read_text(encoding="utf-8"), "text")

    def test_latest_holds_the_newest_report(self):
        folder = cs.temp_dir()
        run_all.write_report("old", folder, NOW.replace(minute=1))
        run_all.write_report("new", folder, NOW)
        self.assertEqual((folder / "latest.md").read_text(encoding="utf-8"), "new")

    def test_only_the_newest_reports_are_kept(self):
        folder = cs.temp_dir()
        for minute in range(1, 6):
            run_all.write_report(str(minute), folder, NOW.replace(minute=minute), keep=3)
        self.assertEqual(sorted(p.name for p in folder.glob("run_*.md")),
                         ["run_2026-09-27_14-03-33.md", "run_2026-09-27_14-04-33.md",
                          "run_2026-09-27_14-05-33.md"])


def _main(reports_dir: Path, argv=("core_xml",)) -> int:
    """run_all.main() with the checks and git faked: one passing check, reports in *reports_dir*."""
    with mock.patch.object(run_all, "discover", lambda: [Path("check_core_xml.py")]), \
            mock.patch.object(run_all, "run_check", lambda script: ("PASS", 0.5, PASSING.output)), \
            mock.patch.object(run_all, "collect_meta", lambda trigger, selection: dict(META)), \
            mock.patch.object(run_all, "REPORTS_DIR", reports_dir), \
            redirect_stdout(io.TextIOWrapper(io.BytesIO())):   # main() calls reconfigure()
        return run_all.main(list(argv))


class MainTests(unittest.TestCase):
    def test_run_writes_latest(self):
        folder = cs.temp_dir() / "reports"
        _main(folder)
        self.assertTrue((folder / "latest.md").is_file())

    def test_failed_report_write_keeps_the_exit_code(self):
        blocker = cs.write_exact(cs.temp_dir() / "reports", b"a file, not a folder")
        self.assertEqual(_main(blocker), 0)

    def test_trigger_flag_is_not_read_as_a_check_name(self):
        self.assertEqual(_main(cs.temp_dir() / "reports", ("--trigger", "pre-commit", "core_xml")), 0)


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

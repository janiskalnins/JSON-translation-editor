"""Core tests: settings. Loading with backfill of missing sub-keys, the BOM, the atomic save, the
daily .backups.zip archive (one per day, newest ten, future-dated entries, damaged files and
archives), and recovery from a damaged settings file.

Run:  python tests/check_core_settings.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import json
import os
import re
import sys
import unittest
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Iterator, List, Optional, Union
from unittest import mock

xte = cs.xte
DAY_5 = datetime(2026, 1, 5, 9, 0, 0)
DAY_6 = datetime(2026, 1, 6, 9, 0, 0)


@contextmanager
def settings_file(content: Optional[Union[str, bytes]] = None) -> Iterator[Path]:
    """xte.SETTINGS_FILE pointed at a file in a folder of its own, holding *content* if given."""
    path = cs.temp_dir() / "translation_editor_settings.json"
    if content is not None:
        cs.write_exact(path, content)
    with mock.patch.object(xte, "SETTINGS_FILE", path):
        yield path


def _archive_dates(settings_path: Path) -> List[str]:
    with zipfile.ZipFile(xte._settings_archive_path(settings_path)) as zf:
        return [re.search(r"\d{4}-\d{2}-\d{2}", name).group(0) for name in zf.namelist()]


class LoadTests(unittest.TestCase):
    def test_missing_sub_key_is_backfilled_on_disk(self):
        with settings_file(json.dumps({"search": {"mode": "contains"}})) as path:
            xte.Settings()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["search"]["debounce_ms"], 150)

    def test_backfill_writes_the_file_once(self):
        written: List[Path] = []
        real_write = xte._atomic_write_bytes

        def recording_write(target: Path, data: bytes) -> None:
            written.append(target)
            real_write(target, data)
        with settings_file(json.dumps({"search": {"mode": "contains"}})) as path, \
                mock.patch.object(xte, "_atomic_write_bytes", recording_write):
            xte.Settings()
        self.assertEqual(written, [path])

    def test_loaded_value_wins_over_the_default(self):
        with settings_file(json.dumps({"search": {"mode": "contains"}})):
            self.assertEqual(xte.Settings().data["search"]["mode"], "contains")

    def test_up_to_date_file_is_not_rewritten(self):
        content = json.dumps(xte.Settings.DEFAULTS, indent=4)
        with settings_file(content) as path:
            xte.Settings()
            self.assertEqual(path.read_text(encoding="utf-8"), content)

    def test_file_with_a_bom_loads(self):
        with settings_file("\ufeff" + json.dumps({"theme": "light"})):
            self.assertEqual(xte.Settings().data["theme"], "light")

    def test_file_with_a_bom_is_not_treated_as_damaged(self):
        with settings_file("\ufeff" + json.dumps({"theme": "light"})):
            self.assertEqual(xte.Settings().recovery_notice, "")


class SaveTests(unittest.TestCase):
    def test_save_writes_the_data(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            settings = xte.Settings()
            settings.data["theme"] = "light"
            settings.save()
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["theme"], "light")

    def test_failed_save_leaves_the_file_intact(self):
        content = json.dumps(xte.Settings.DEFAULTS, indent=4)
        with settings_file(content) as path:
            settings = xte.Settings()
            settings.data["theme"] = "light"
            with mock.patch.object(os, "replace", side_effect=OSError("locked")):
                settings.save()
            self.assertEqual(path.read_text(encoding="utf-8"), content)


class DailyArchiveTests(unittest.TestCase):
    def test_one_snapshot_per_day(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            xte.backup_settings_daily(path, now=DAY_5)
            xte.backup_settings_daily(path, now=DAY_5.replace(hour=17))
            self.assertEqual(_archive_dates(path), ["2026-01-05"])

    def test_snapshot_holds_the_exact_bytes(self):
        content = '{"theme":   "dark"}'
        with settings_file(content) as path:
            xte.backup_settings_daily(path, now=DAY_5)
            with zipfile.ZipFile(xte._settings_archive_path(path)) as zf:
                self.assertEqual(zf.read(zf.namelist()[0]), content.encode("utf-8"))

    def test_archive_keeps_the_newest_ten_days(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            for day in range(1, 13):
                xte.backup_settings_daily(path, now=datetime(2026, 1, day, 9, 0, 0))
            self.assertEqual(_archive_dates(path), [f"2026-01-{d:02d}" for d in range(3, 13)])

    def test_future_dated_snapshot_does_not_block_today(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            xte.backup_settings_daily(path, now=datetime(2030, 1, 1, 9, 0, 0))
            xte.backup_settings_daily(path, now=DAY_5)
            self.assertEqual(_archive_dates(path), ["2030-01-01", "2026-01-05"])

    def test_damaged_settings_file_is_not_archived(self):
        with settings_file('{"theme": ') as path:
            xte.backup_settings_daily(path, now=DAY_5)
            self.assertFalse(xte._settings_archive_path(path).exists())

    def test_damaged_archive_is_moved_aside(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            archive = cs.write_exact(xte._settings_archive_path(path), b"not a zip")
            xte.backup_settings_daily(path, now=DAY_5)
            self.assertEqual(archive.with_name(archive.name + ".corrupt").read_bytes(), b"not a zip")

    def test_damaged_archive_is_rebuilt_with_today(self):
        with settings_file(json.dumps({"theme": "dark"})) as path:
            cs.write_exact(xte._settings_archive_path(path), b"not a zip")
            xte.backup_settings_daily(path, now=DAY_5)
            self.assertEqual(_archive_dates(path), ["2026-01-05"])


DAMAGED = '{"theme": '


def _archive_then_damage(path: Path) -> None:
    """Archive two good snapshots (API key k5 on day 5, k6 on day 6), then damage the file."""
    for key, day in (("k5", DAY_5), ("k6", DAY_6)):
        cs.write_exact(path, json.dumps({"translation": {"claude_api_key": key}}))
        xte.backup_settings_daily(path, now=day)
    cs.write_exact(path, DAMAGED)


class RecoveryTests(unittest.TestCase):
    def test_damaged_file_is_restored_from_the_newest_snapshot(self):
        with settings_file() as path:
            _archive_then_damage(path)
            self.assertEqual(xte.Settings().data["translation"]["claude_api_key"], "k6")

    def test_damaged_file_is_kept_aside(self):
        with settings_file() as path:
            _archive_then_damage(path)
            xte.Settings()
            kept = list(path.parent.glob("translation_editor_settings.json.corrupt-*"))
            self.assertEqual([p.read_text(encoding="utf-8") for p in kept], [DAMAGED])

    def test_recovery_notice_names_the_snapshot_date(self):
        with settings_file() as path:
            _archive_then_damage(path)
            self.assertIn("2026-01-06", xte.Settings().recovery_notice)

    def test_damaged_file_without_an_archive_gives_the_defaults(self):
        with settings_file(DAMAGED):
            self.assertEqual(xte.Settings().data, deepcopy(xte.Settings.DEFAULTS))

    def test_missing_file_is_not_recovered_from_the_archive(self):
        with settings_file(json.dumps({"theme": "light"})) as path:
            xte.backup_settings_daily(path, now=DAY_5)
            path.unlink()
            self.assertEqual(xte.Settings().data["theme"], "dark")


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

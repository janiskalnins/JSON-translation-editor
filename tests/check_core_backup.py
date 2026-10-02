"""Core tests: backups. _sanitize_path_component, _atomic_write_bytes, _write_backup_slot
(manifest, gzip, glossary, same-second suffix, pruning), _newest_slot_age_seconds, and
BackupThread.run() in every location mode with the min-interval throttle and the root fallback.

Run:  python tests/check_core_backup.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import gzip
import hashlib
import json
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

xte = cs.xte

RAW = cs.xml_doc([cs.row("Save", "Saglabāt")]).encode("utf-8")
KEY = "Latvian__v4.1.1140"
STAMP = "%Y-%m-%d_%H-%M-%S"


class SanitizeTests(unittest.TestCase):
    def test_path_components_are_made_safe(self):
        cases = {"a<b>:c": "a_b__c", "CON": "_CON", "///": "_", "4.1.": "4.1", "x" * 100: "x" * 60}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(xte._sanitize_path_component(value), expected)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_replaces_the_content(self):
        path = cs.write_exact(cs.temp_dir() / "f.bin", b"old")
        xte._atomic_write_bytes(path, b"new")
        self.assertEqual(path.read_bytes(), b"new")

    def test_atomic_write_leaves_no_temp_file(self):
        path = cs.temp_dir() / "f.bin"
        xte._atomic_write_bytes(path, b"new")
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["f.bin"])


def _write_slot(root: Path, ts: str = "2025-01-01_00-00-00", compress: bool = True,
                glossary: bytes = None, max_count: int = 5) -> Path:
    source = root.parent / "Latvian.xml"
    return xte._write_backup_slot(
        root_dir=root, location_id="root", backup_key=KEY, ts=ts, source_path=source,
        raw_bytes=RAW, md5=hashlib.md5(RAW).hexdigest(),
        glossary_source=xte.glossary_path_for(source) if glossary is not None else None,
        glossary_bytes=glossary,
        glossary_md5=hashlib.md5(glossary).hexdigest() if glossary is not None else None,
        compress=compress, max_count=max_count, trigger="file_open", culture="lv-LV",
        display_language="Latviešu", version="4.1.1140", is_fallback=False)


def _manifest(slot: Path) -> dict:
    return json.loads((slot / "backup_info.json").read_text(encoding="utf-8"))


class WriteSlotTests(unittest.TestCase):
    def test_manifest_describes_the_slot(self):
        info = _manifest(_write_slot(cs.temp_dir() / "bk"))
        keys = ("backup_file", "compressed", "md5_checksum", "trigger", "version", "location",
                "backup_key", "is_fallback", "glossary_backed_up")
        self.assertEqual({k: info[k] for k in keys},
                         {"backup_file": "Latvian.xml.gz", "compressed": True,
                          "md5_checksum": hashlib.md5(RAW).hexdigest(), "trigger": "file_open",
                          "version": "4.1.1140", "location": "root", "backup_key": KEY,
                          "is_fallback": False, "glossary_backed_up": False})

    def test_compressed_slot_holds_the_source_bytes(self):
        slot = _write_slot(cs.temp_dir() / "bk")
        self.assertEqual(gzip.decompress((slot / "Latvian.xml.gz").read_bytes()), RAW)

    def test_plain_slot_holds_the_source_bytes(self):
        slot = _write_slot(cs.temp_dir() / "bk", compress=False)
        self.assertEqual((slot / "Latvian.xml").read_bytes(), RAW)

    def test_glossary_is_backed_up_with_the_xml(self):
        slot = _write_slot(cs.temp_dir() / "bk", compress=False, glossary=b"term,translation\n")
        self.assertEqual((slot / "Latvian.glossary.csv").read_bytes(), b"term,translation\n")

    def test_second_slot_in_the_same_second_gets_a_suffix(self):
        root = cs.temp_dir() / "bk"
        _write_slot(root)
        _write_slot(root)
        self.assertEqual(sorted(d.name for d in (root / KEY).iterdir()),
                         ["2025-01-01_00-00-00", "2025-01-01_00-00-00_001"])

    def test_pruning_keeps_the_newest_slots(self):
        root = cs.temp_dir() / "bk"
        for day in range(1, 6):
            _write_slot(root, ts=f"2025-01-0{day}_00-00-00", max_count=3)
        self.assertEqual(sorted(d.name for d in (root / KEY).iterdir()),
                         ["2025-01-03_00-00-00", "2025-01-04_00-00-00", "2025-01-05_00-00-00"])


class SlotAgeTests(unittest.TestCase):
    def test_age_comes_from_the_newest_slot_name(self):
        root = cs.temp_dir()
        (root / KEY / "notes").mkdir(parents=True)
        (root / KEY / ((datetime.now() - timedelta(seconds=120)).strftime(STAMP) + "_001")).mkdir()
        age = xte._newest_slot_age_seconds(root, KEY)
        self.assertTrue(110 <= age < 300, age)

    def test_junk_folders_only_give_none(self):
        root = cs.temp_dir()
        (root / KEY / "notes").mkdir(parents=True)
        self.assertIsNone(xte._newest_slot_age_seconds(root, KEY))

    def test_missing_key_folder_gives_none(self):
        self.assertIsNone(xte._newest_slot_age_seconds(cs.temp_dir(), KEY))


class BackupRun:
    """A source file in <tmp>/docs and an app folder in <tmp>/app, as BackupThread sees them."""

    def __init__(self):
        folder = cs.temp_dir()
        self.docs = folder / "docs"
        self.docs.mkdir()
        self.source = cs.write_exact(self.docs / "Latvian.xml", RAW)
        self.app_dir = folder / "app"
        self.next_to_file = self.docs / xte.BACKUP_DIR_NAME
        self.root = self.app_dir / xte.BACKUP_DIR_NAME

    def run(self, trigger: str = "file_open", **cfg) -> Tuple[List[Tuple[str, str]], object]:
        got = []
        thread = xte.BackupThread(self.source, trigger, dict(cfg), self.app_dir)
        thread.finished.connect(lambda notices, root: got.append((notices, root)))
        thread.run()
        return got[0]

    @staticmethod
    def slots(backup_root: Path) -> List[str]:
        key_dir = backup_root / KEY
        return sorted(d.name for d in key_dir.iterdir()) if key_dir.exists() else []

    @staticmethod
    def add_recent_slot(backup_root: Path) -> None:
        (backup_root / KEY / datetime.now().strftime(STAMP)).mkdir(parents=True)

    def block_next_to_file(self) -> None:
        """A file where the next-to-file backup folder should be: every write there fails."""
        cs.write_exact(self.next_to_file, b"not a folder")


def _labels(notices: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """(text before the first ':', level) per notice: the location and the outcome's level."""
    return [(text.split(":")[0], level) for text, level in notices]


class BackupThreadTests(unittest.TestCase):
    def test_both_mode_writes_a_slot_at_each_location(self):
        b = BackupRun()
        b.run(location_mode="both")
        self.assertEqual((len(b.slots(b.next_to_file)), len(b.slots(b.root))), (1, 1))

    def test_both_mode_reports_each_location(self):
        notices, _ = BackupRun().run(location_mode="both")
        self.assertEqual(_labels(notices), [("Backup next to file", "info"), ("Backup in root", "info")])

    def test_next_to_file_mode_writes_only_next_to_the_file(self):
        b = BackupRun()
        b.run(location_mode="next_to_file")
        self.assertEqual((len(b.slots(b.next_to_file)), b.slots(b.root)), (1, []))

    def test_root_mode_writes_only_in_the_root(self):
        b = BackupRun()
        b.run(location_mode="root")
        self.assertEqual((b.slots(b.next_to_file), len(b.slots(b.root))), ([], 1))

    def test_written_next_to_file_folder_is_reported(self):
        b = BackupRun()
        _, next_to_file_root = b.run(location_mode="next_to_file")
        self.assertEqual(next_to_file_root, b.next_to_file)

    def test_recent_slots_skip_a_file_open_backup(self):
        b = BackupRun()
        b.add_recent_slot(b.next_to_file)
        b.add_recent_slot(b.root)
        notices, _ = b.run(location_mode="both", min_interval_minutes=5)
        self.assertEqual([text.split(" — ")[0] for text, _ in notices],
                         ["Backup next to file: skipped", "Backup in root: skipped"])

    def test_skipped_backup_writes_nothing(self):
        b = BackupRun()
        b.add_recent_slot(b.root)
        b.run(location_mode="root", min_interval_minutes=5)
        self.assertEqual(len(b.slots(b.root)), 1)

    def test_pre_restore_safety_is_never_throttled(self):
        b = BackupRun()
        b.add_recent_slot(b.root)
        b.run(trigger="pre_restore_safety", location_mode="root", min_interval_minutes=5)
        self.assertEqual(len(b.slots(b.root)), 2)

    def test_zero_interval_never_throttles(self):
        b = BackupRun()
        b.add_recent_slot(b.root)
        b.run(location_mode="root", min_interval_minutes=0)
        self.assertEqual(len(b.slots(b.root)), 2)

    def test_next_to_file_failure_falls_back_to_the_root(self):
        b = BackupRun()
        b.block_next_to_file()
        notices, _ = b.run(location_mode="next_to_file")
        self.assertEqual(_labels(notices), [("Backup next to file", "error"),
                                            ("Backup in root (fallback)", "warning")])

    def test_fallback_slot_is_marked_as_a_fallback(self):
        b = BackupRun()
        b.block_next_to_file()
        b.run(location_mode="next_to_file")
        slot = b.root / KEY / b.slots(b.root)[0]
        self.assertTrue(_manifest(slot)["is_fallback"])

    def test_fallback_is_skipped_when_the_root_is_recent(self):
        b = BackupRun()
        b.block_next_to_file()
        b.add_recent_slot(b.root)
        notices, _ = b.run(location_mode="next_to_file", min_interval_minutes=5)
        self.assertEqual(notices, [("Backup next to file: failed — could not write the backup folder",
                                    "error")])

    def test_unreadable_source_reports_one_error(self):
        b = BackupRun()
        b.source.unlink()
        notices, _ = b.run(location_mode="both")
        self.assertEqual(notices, [("Backup failed — could not read source file", "error")])


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

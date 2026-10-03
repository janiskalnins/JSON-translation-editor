"""Core tests: Export and Import packages. The export ZIP and its export_info.json, the suggested
names and the info-bar summary; the package reader's refusals and checksums; the glossary diff and
the glossary it produces.

Run:  python tests/check_core_export.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import hashlib
import io
import json
import sys
import unittest
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Dict
from unittest import mock

jte = cs.jte

PAIRS = {"Save": "Guardar", "Lane": "Carril"}
META = {"Save": ("Complete", "Jane", "2025-02-01")}
GLOSSARY = "term,translation,note\r\nLane,Carril,\r\n".encode("utf-8-sig")
HEADER = jte.FileHeader(language="es", language_name="Español", version="1.0.0")
NOW = datetime(2026, 10, 2, 21, 30, 0)


def _source(meta: bool = True, glossary: bool = True) -> Path:
    """es.json in a folder of its own, with its sidecar and glossary unless told otherwise."""
    path = cs.write_pair(cs.temp_dir(), "es", PAIRS, meta=META if meta else None)
    if glossary:
        cs.write_exact(jte.glossary_path_for(path), GLOSSARY)
    return path


def _unzip(data: bytes) -> Dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {name: zf.read(name) for name in zf.namelist()}


def _manifest(data: bytes) -> dict:
    return json.loads(_unzip(data)[jte.EXPORT_INFO_NAME].decode("utf-8"))


class ExportZipTests(unittest.TestCase):
    def test_package_holds_the_three_files_and_the_manifest(self):
        data, _ = jte.build_export_zip(_source(), HEADER, NOW)
        self.assertEqual(sorted(_unzip(data)),
                         ["es.glossary.csv", "es.json", "es.json.meta", "export_info.json"])

    def test_files_are_stored_byte_for_byte(self):
        path = _source()
        files = [path, jte.meta_path_for(path), jte.glossary_path_for(path)]
        data, _ = jte.build_export_zip(path, HEADER, NOW)
        self.assertEqual([_unzip(data)[p.name] for p in files], [p.read_bytes() for p in files])

    def test_entries_are_deflated(self):
        data, _ = jte.build_export_zip(_source(), HEADER, NOW)
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            self.assertEqual({i.compress_type for i in zf.infolist()}, {zipfile.ZIP_DEFLATED})

    def test_returned_names_are_the_packed_files(self):
        _, names = jte.build_export_zip(_source(), HEADER, NOW)
        self.assertEqual(names, ["es.json", "es.json.meta", "es.glossary.csv"])

    def test_missing_companions_are_left_out(self):
        _, names = jte.build_export_zip(_source(meta=False, glossary=False), HEADER, NOW)
        self.assertEqual(names, ["es.json"])

    def test_missing_language_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            jte.build_export_zip(cs.temp_dir() / "es.json", HEADER, NOW)


class ManifestTests(unittest.TestCase):
    def test_header_fields(self):
        manifest = _manifest(jte.build_export_zip(_source(), HEADER, NOW)[0])
        manifest.pop("files")
        self.assertEqual(manifest, {"format": 1, "app": "JSON Translation Editor",
                                    "app_version": jte.APP_VERSION,
                                    "exported": "2026-10-02T21:30:00", "language": "es",
                                    "language_name": "Español", "version": "1.0.0"})

    def test_files_list_names_and_roles_in_order(self):
        manifest = _manifest(jte.build_export_zip(_source(), HEADER, NOW)[0])
        self.assertEqual([(f["name"], f["role"]) for f in manifest["files"]],
                         [("es.json", "translation"), ("es.json.meta", "metadata"),
                          ("es.glossary.csv", "glossary")])

    def test_sizes_and_md5s_match_the_files(self):
        path = _source()
        manifest = _manifest(jte.build_export_zip(path, HEADER, NOW)[0])
        on_disk = {p.name: p.read_bytes()
                   for p in (path, jte.meta_path_for(path), jte.glossary_path_for(path))}
        self.assertEqual({f["name"]: (f["size"], f["md5"]) for f in manifest["files"]},
                         {n: (len(b), hashlib.md5(b).hexdigest()) for n, b in on_disk.items()})

    def test_language_is_guessed_from_the_name_without_a_sidecar_code(self):
        header = jte.FileHeader(language="", language_name="", version="")
        manifest = _manifest(jte.build_export_zip(_source(), header, NOW)[0])
        self.assertEqual(manifest["language"], "es")


class ExportNamingTests(unittest.TestCase):
    def test_summary(self):
        path = Path("C:/work/es.json")
        cases = [
            (["es.json", "es.json.meta", "es.glossary.csv"], "(3 files)"),
            (["es.json", "es.json.meta"], "(2 files, no glossary)"),
            (["es.json", "es.glossary.csv"], "(2 files, no metadata)"),
            (["es.json"], "(1 file, no metadata or glossary)"),
        ]
        for names, want in cases:
            with self.subTest(names=names):
                self.assertEqual(jte.export_summary(path, names), want)

    def test_suggested_names(self):
        path, day = Path("C:/work/es.json"), date(2026, 10, 2)
        cases = [
            ("1.0.0", "zip", "es_v1.0.0_2026-10-02.zip"),
            ("", "zip", "es_2026-10-02.zip"),
            ("4.1/x", "zip", "es_v4.1_x_2026-10-02.zip"),
            ("1.0.0", "json", "es.json"),
        ]
        for version, mode, want in cases:
            with self.subTest(version=version, mode=mode):
                self.assertEqual(jte.suggested_export_name(path, version, day, mode), want)


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

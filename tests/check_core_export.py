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


def _zip_path(files: Dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> Path:
    """A ZIP of *files* (name -> bytes, in order) in a folder of its own."""
    path = cs.temp_dir() / "package.zip"
    with zipfile.ZipFile(path, "w", compression) as zf:
        for name, raw in files.items():
            zf.writestr(name, raw)
    return path


def _zip_path_with_raw_names(items: list) -> Path:
    """A ZIP with entries where filenames may have backslashes or other characters.
    Items are (name_to_write, bytes) tuples. If zipfile normalizes the name, patches
    the archive bytes to restore it."""
    path = cs.temp_dir() / "package.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in items:
            # Try using ZipInfo to preserve the exact name
            zi = zipfile.ZipInfo("placeholder.json")
            zi.filename = name
            zf.writestr(zi, raw)

    # Verify what names are visible and patch if needed
    with zipfile.ZipFile(path) as zf:
        stored_names = zf.namelist()

    # If any name was normalized (e.g., backslash -> forward slash),
    # patch the archive bytes to restore the original
    for i, (orig_name, _) in enumerate(items):
        if orig_name not in stored_names and i < len(stored_names):
            # Patch the archive bytes
            stored_name = stored_names[i]
            with open(path, "rb") as f:
                data = bytearray(f.read())

            # Replace stored name with original in the ZIP file
            # This happens in central directory and local file headers
            data = data.replace(stored_name.encode("utf-8"), orig_name.encode("utf-8", errors="surrogateescape"))

            with open(path, "wb") as f:
                f.write(data)

    return path


def _exported_files() -> Dict[str, bytes]:
    """The files of a real export of _source(), manifest included."""
    return _unzip(jte.build_export_zip(_source(), HEADER, NOW)[0])


def _read(path: Path) -> "jte.IncomingPackage":
    return jte.read_translation_package(path, cs.temp_dir())


class PackageRefusalTests(unittest.TestCase):
    def test_refused_packages(self):
        doc = cs.json_doc(PAIRS)
        cases = [
            ({"sub/es.json": doc}, "not a plain file name"),
            ({"../es.json": doc}, "not a plain file name"),
            ({"C:es.json": doc}, "not a plain file name"),
            ({"/es.json": doc}, "not a plain file name"),
            ({"CON.json": doc}, "not a plain file name"),
            ({"es.json": doc, "readme.txt": b"x"}, "unexpected file readme.txt"),
            ({"es.json": doc, "it.json": doc}, "more than one .json file"),
            ({"es.json.meta": b"{}"}, "no .json file"),
            ({"es.json": doc, "it.glossary.csv": b""}, "unexpected file it.glossary.csv"),
        ]
        for files, reason in cases:
            with self.subTest(names=list(files)):
                with self.assertRaisesRegex(jte.PackageError, reason):
                    _read(_zip_path(files))

    def test_refused_packages_with_backslash_and_dotted_paths(self):
        doc = cs.json_doc(PAIRS)
        cases = [
            ([("a\\es.json", doc)], "not a plain file name"),
            ([("a/../es.json", doc)], "not a plain file name"),
        ]
        for items, reason in cases:
            with self.subTest(names=[name for name, _ in items]):
                with self.assertRaisesRegex(jte.PackageError, reason):
                    _read(_zip_path_with_raw_names(items))

    def test_over_the_size_limit_is_refused_before_reading(self):
        path = _zip_path({"es.json": cs.json_doc(PAIRS)})
        with mock.patch.object(jte, "IMPORT_MAX_BYTES", 10), \
                mock.patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("read")):
            with self.assertRaisesRegex(jte.PackageError, "MB unpacked"):
                _read(path)

    def test_bad_crc_is_refused_as_damaged(self):
        doc = cs.json_doc(PAIRS)
        raw = _zip_path({"es.json": doc}, zipfile.ZIP_STORED).read_bytes()
        at = raw.index(doc) + 3
        broken = cs.write_exact(cs.temp_dir() / "broken.zip",
                                raw[:at] + bytes([raw[at] ^ 0x01]) + raw[at + 1:])
        with self.assertRaisesRegex(jte.PackageError, "damaged"):
            _read(broken)

    def test_not_a_zip_is_refused_as_damaged(self):
        with self.assertRaisesRegex(jte.PackageError, "damaged"):
            _read(cs.write_exact(cs.temp_dir() / "x.zip", b"not a zip"))


class PackageReadTests(unittest.TestCase):
    def test_files_are_unpacked_byte_for_byte(self):
        files = _exported_files()
        package = _read(_zip_path(files))
        self.assertEqual([package.json_path.read_bytes(), package.meta_path.read_bytes(),
                          package.glossary_path.read_bytes()],
                         [files["es.json"], files["es.json.meta"], files["es.glossary.csv"]])

    def test_files_land_in_the_temporary_folder_named_from_the_stem(self):
        temp = cs.temp_dir()
        package = jte.read_translation_package(_zip_path(_exported_files()), temp)
        self.assertEqual([package.json_path, package.meta_path, package.glossary_path],
                         [temp / "es.json", temp / "es.json.meta", temp / "es.glossary.csv"])

    def test_missing_companions_are_none(self):
        package = _read(_zip_path({"es.json": cs.json_doc(PAIRS)}))
        self.assertEqual((package.meta_path, package.glossary_path), (None, None))

    def test_exported_package_has_no_mismatches(self):
        self.assertEqual(_read(_zip_path(_exported_files())).mismatches, [])

    def test_changed_file_is_a_mismatch(self):
        files = _exported_files()
        files["es.json.meta"] = cs.sidecar_doc({})
        self.assertEqual(_read(_zip_path(files)).mismatches, ["es.json.meta"])

    def test_file_not_in_the_manifest_is_a_mismatch(self):
        files = _unzip(jte.build_export_zip(_source(glossary=False), HEADER, NOW)[0])
        files["es.glossary.csv"] = GLOSSARY
        self.assertEqual(_read(_zip_path(files)).mismatches, ["es.glossary.csv"])

    def test_listed_file_missing_from_the_zip_is_a_mismatch(self):
        files = _exported_files()
        del files["es.glossary.csv"]
        self.assertEqual(_read(_zip_path(files)).mismatches, ["es.glossary.csv"])

    def test_unreadable_manifest_mismatches_every_file(self):
        files = _exported_files()
        files[jte.EXPORT_INFO_NAME] = b"{"
        self.assertEqual(sorted(_read(_zip_path(files)).mismatches),
                         ["es.glossary.csv", "es.json", "es.json.meta"])

    def test_package_without_a_manifest_is_unverified(self):
        files = _exported_files()
        del files[jte.EXPORT_INFO_NAME]
        package = _read(_zip_path(files))
        self.assertEqual((package.has_manifest, package.mismatches), (False, []))

    def test_loose_json_brings_its_companions(self):
        path = _source()
        package = _read(path)
        self.assertEqual((package.json_path, package.meta_path, package.glossary_path,
                          package.is_zip),
                         (path, jte.meta_path_for(path), jte.glossary_path_for(path), False))

    def test_loose_json_without_companions(self):
        package = _read(_source(meta=False, glossary=False))
        self.assertEqual((package.meta_path, package.glossary_path), (None, None))


class SameLanguageTests(unittest.TestCase):
    def test_codes(self):
        cases = [("pt-BR", "pt_br", True), ("es", "ES", True), ("es", "es-AR", False),
                 ("", "", False), ("es", "", False)]
        for a, b, want in cases:
            with self.subTest(a=a, b=b):
                self.assertEqual(jte.same_language(a, b), want)


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

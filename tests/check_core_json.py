"""Core checks for the JSON language file: reading (refusals included), style detection and
writing back byte for byte. Later tasks add the sidecar and the load/save pair."""

import core_support as cs  # first: offscreen platform, scratch folder, sys.argv[0]

import json
import sys
import unittest
from datetime import date
from pathlib import Path

jte = cs.jte

PAIRS = [("Save", "Guardar"), ("Path {n}", "Trazado {n}"), ("Ā", "Ā")]


def _parse(data: bytes):
    return jte.parse_json_bytes(data)


class ParseTests(unittest.TestCase):
    def test_pairs_keep_file_order(self):
        pairs, _style = _parse(cs.json_doc([("b", "B"), ("a", "A")]))
        self.assertEqual(pairs, [("b", "B"), ("a", "A")])

    def test_refused_files(self):
        cases = {
            "invalid JSON": b'{"a": "A",}',
            "not an object": b'["a"]',
            "a value that is not text": b'{"a": 1}',
            "a nested object": b'{"a": {"b": "c"}}',
            "a duplicate key": b'{"a": "A", "a": "B"}',
            "not UTF-8": b'{"a": "\xff"}',
            "empty": b"",
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(jte.JsonFormatError):
                    _parse(data)

    def test_invalid_json_names_the_line(self):
        with self.assertRaises(jte.JsonFormatError) as ctx:
            _parse(b'{\n "a": "A"\n "b": "B"\n}')
        self.assertIn("(line 3,", str(ctx.exception))

    def test_duplicate_key_is_named(self):
        with self.assertRaises(jte.JsonFormatError) as ctx:
            _parse(b'{"Save": "A", "Save": "B"}')
        self.assertIn("'Save'", str(ctx.exception))

    def test_empty_object_reads_as_no_pairs(self):
        self.assertEqual(_parse(b"{}\n")[0], [])


class StyleTests(unittest.TestCase):
    def test_detected_indent(self):
        cases = {
            "one space": (cs.json_doc(PAIRS), " "),
            "four spaces": (cs.json_doc(PAIRS, indent="    "), "    "),
            "tab": (cs.json_doc(PAIRS, indent="\t"), "\t"),
            "one line": (json.dumps(dict(PAIRS), ensure_ascii=False).encode("utf-8"), None),
        }
        for label, (data, indent) in cases.items():
            with self.subTest(label):
                self.assertEqual(_parse(data)[1].indent, indent)

    def test_crlf_is_detected(self):
        self.assertEqual(_parse(cs.json_doc(PAIRS, newline="\r\n"))[1].newline, "\r\n")

    def test_bom_is_detected(self):
        self.assertTrue(_parse(cs.json_doc(PAIRS, bom=True))[1].bom)

    def test_missing_trailing_newline_is_detected(self):
        self.assertFalse(_parse(cs.json_doc(PAIRS)[:-1])[1].trailing_newline)

    def test_escaped_non_ascii_is_detected(self):
        data = json.dumps(dict(PAIRS), indent=1).encode("ascii") + b"\n"
        self.assertTrue(_parse(data)[1].ensure_ascii)

    def test_literal_non_ascii_is_detected(self):
        self.assertFalse(_parse(cs.json_doc(PAIRS))[1].ensure_ascii)


class WriteTests(unittest.TestCase):
    def test_unchanged_files_write_back_byte_for_byte(self):
        cases = {
            "the frozen es.json": (cs.DATA / "es.json").read_bytes(),
            "CRLF": cs.json_doc(PAIRS, newline="\r\n"),
            "BOM": cs.json_doc(PAIRS, bom=True),
            "escaped non-ASCII": json.dumps(dict(PAIRS), indent=1).encode("ascii") + b"\n",
            "four-space indent": cs.json_doc(PAIRS, indent="    "),
            "tab indent": cs.json_doc(PAIRS, indent="\t"),
            "one line": json.dumps(dict(PAIRS), ensure_ascii=False).encode("utf-8"),
            "no trailing newline": cs.json_doc(PAIRS)[:-1],
            "quotes, backslashes, line breaks": cs.json_doc(
                [("a\nb", 'say "hi"\\n'), ("tab\there", "{name}\n\n{n}")]),
            "empty object": b"{}\n",
        }
        for label, data in cases.items():
            with self.subTest(label):
                pairs, style = _parse(data)
                self.assertEqual(jte.dump_json_pairs(pairs, style), data)

    def test_one_changed_value_changes_one_line(self):
        original = (cs.DATA / "es.json").read_bytes()
        pairs, style = _parse(original)
        pairs[1] = (pairs[1][0], "CAMBIADO")
        written = jte.dump_json_pairs(pairs, style)
        changed = [i for i, (a, b) in enumerate(zip(original.splitlines(), written.splitlines()))
                   if a != b]
        self.assertEqual(changed, [2])

    def test_two_pairs_with_one_key_are_refused(self):
        with self.assertRaises(ValueError):
            jte.dump_json_pairs([("a", "A"), ("a", "B")], jte.DEFAULT_JSON_STYLE)

    def test_written_file_is_intact(self):
        path = cs.temp_dir() / "es.json"
        path.write_bytes(jte.dump_json_pairs(PAIRS, jte.DEFAULT_JSON_STYLE))
        cs.assert_json_intact(self, path, [k for k, _v in PAIRS])


ISO = "2026-10-02"
SHOWN = jte.format_date_for_storage(date(2026, 10, 2))


class SidecarParseTests(unittest.TestCase):
    def test_header_is_read(self):
        header, _meta = jte.parse_sidecar_bytes(
            cs.sidecar_doc(language="es-AR", language_name="Español (Argentina)", version="1.2.3"))
        self.assertEqual(header, jte.FileHeader("es-AR", "Español (Argentina)", "1.2.3"))

    def test_missing_fields_default(self):
        self.assertEqual(jte.parse_sidecar_bytes(b"{}"), (jte.FileHeader(), {}))

    def test_bom_is_accepted(self):
        header, _meta = jte.parse_sidecar_bytes(b"\xef\xbb\xbf" + cs.sidecar_doc())
        self.assertEqual(header.language, "es")

    def test_refused_sidecars(self):
        cases = {
            "not JSON": b"{",
            "a list": b"[]",
            "a newer format": cs.sidecar_doc(format=2),
            "language not text": cs.sidecar_doc(language=5),
            "entries not an object": b'{"entries": []}',
            "an entry not an object": b'{"entries": {"a": "Complete"}}',
            "an entry field not text": b'{"entries": {"a": {"status": 1}}}',
        }
        for label, data in cases.items():
            with self.subTest(label):
                with self.assertRaises(jte.SidecarError):
                    jte.parse_sidecar_bytes(data)


def _applied(meta: dict, names=("a", "b")):
    entries = [cs.bare_entry(n) for n in names]
    warnings = jte.apply_sidecar_meta(entries, meta)
    return entries, warnings


class ApplyMetaTests(unittest.TestCase):
    def test_listed_entry_takes_its_metadata(self):
        entries, _w = _applied({"a": {"status": "Review", "translator": "Jo", "modified": ISO}})
        self.assertEqual((entries[0].status, entries[0].translator, entries[0].modify_date),
                         ("Review", "Jo", SHOWN))

    def test_unlisted_entry_stays_new(self):
        entries, _w = _applied({"a": {"status": "Review", "translator": "Jo", "modified": ISO}})
        self.assertEqual((entries[1].status, entries[1].translator, entries[1].modify_date),
                         ("New", "", ""))

    def test_unknown_status_reads_as_new(self):
        entries, _w = _applied({"a": {"status": "Done"}})
        self.assertEqual(entries[0].status, "New")

    def test_bad_date_is_kept_as_stored(self):
        entries, _w = _applied({"a": {"status": "Review", "modified": "2026-13-45"}})
        self.assertEqual(entries[0].modify_date, "2026-13-45")

    def test_warnings(self):
        cases = {
            "clean": ({"a": {"status": "Review", "translator": "", "modified": ISO}}, []),
            "orphan": ({"gone": {"status": "Review"}},
                       ["Metadata: 1 entries for keys no longer in the file"]),
            "unknown status": ({"a": {"status": "Done"}},
                               ["Metadata: 1 unknown status value(s) read as New"]),
            "bad date": ({"a": {"modified": "foo"}},
                         ["Metadata: 1 unrecognized date(s) (e.g. 'foo')"]),
        }
        for label, (meta, expected) in cases.items():
            with self.subTest(label):
                self.assertEqual(_applied(meta)[1], expected)


def _built(entries, header=jte.FileHeader("es", "Español", "1.0.0")) -> dict:
    return json.loads(jte.build_sidecar_bytes(entries, header))


class BuildSidecarTests(unittest.TestCase):
    def test_only_entries_with_metadata_are_listed(self):
        entries = [cs.bare_entry("a"), cs.make_entry(name="b", status="Review", translator="",
                                                     modify_date="")]
        self.assertEqual(list(_built(entries)["entries"]), ["b"])

    def test_dates_are_written_iso(self):
        entries = [cs.make_entry(name="b", modify_date=SHOWN)]
        self.assertEqual(_built(entries)["entries"]["b"]["modified"], ISO)

    def test_unparseable_date_is_written_as_stored(self):
        entries = [cs.make_entry(name="b", modify_date="foo")]
        self.assertEqual(_built(entries)["entries"]["b"]["modified"], "foo")

    def test_header_is_written(self):
        built = _built([], jte.FileHeader("pt-BR", "Português", "2.0.1"))
        self.assertEqual((built["format"], built["language"], built["language_name"],
                          built["version"]), (1, "pt-BR", "Português", "2.0.1"))

    def test_layout_is_one_space_indent_with_trailing_newline(self):
        raw = jte.build_sidecar_bytes([cs.make_entry(name="ā")], jte.FileHeader())
        self.assertEqual(raw, (json.dumps(json.loads(raw), ensure_ascii=False, indent=1)
                               + "\n").encode("utf-8"))

    def test_metadata_survives_a_round_trip(self):
        original = [cs.make_entry(name="a", status="Review", translator="Jo", modify_date=SHOWN),
                    cs.bare_entry("b")]
        _header, meta = jte.parse_sidecar_bytes(jte.build_sidecar_bytes(original, jte.FileHeader()))
        copies, _w = _applied(meta)
        self.assertEqual([(e.status, e.translator, e.modify_date) for e in copies],
                         [(e.status, e.translator, e.modify_date) for e in original])


class SidecarPathTests(unittest.TestCase):
    def test_meta_path_sits_beside_the_file(self):
        self.assertEqual(jte.meta_path_for(Path("C:/t/es.json")), Path("C:/t/es.json.meta"))

    def test_guessed_language(self):
        cases = {"es.json": "es", "pt-BR.json": "pt-BR", "zh-Hant-TW.json": "zh-Hant-TW",
                 "deu.json": "deu", "strings.json": "",
                 "es_restored_2026-10-02_10-00-00.json": ""}
        for name, expected in cases.items():
            with self.subTest(name):
                self.assertEqual(jte.guess_language(Path(name)), expected)

    def test_language_code_accepts_a_long_variant(self):
        self.assertTrue(jte.LANGUAGE_CODE_RE.match("ca-valencia"))

    def test_effective_language_prefers_the_header(self):
        self.assertEqual(jte.effective_language(jte.FileHeader(language="es-AR"), Path("es.json")),
                         "es-AR")

    def test_effective_language_falls_back_to_the_file_name(self):
        self.assertEqual(jte.effective_language(jte.FileHeader(), Path("it.json")), "it")

    def test_read_file_header_without_a_sidecar(self):
        self.assertEqual(jte.read_file_header(cs.temp_dir() / "es.json"), jte.FileHeader())

    def test_read_file_header_of_a_damaged_sidecar(self):
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", b"{")
        self.assertEqual(jte.read_file_header(folder / "es.json"), jte.FileHeader())

    def test_read_file_header_reads_the_sidecar(self):
        folder = cs.temp_dir()
        cs.write_exact(folder / "es.json.meta", cs.sidecar_doc(version="3.1.4"))
        self.assertEqual(jte.read_file_header(folder / "es.json").version, "3.1.4")


def _pair(pairs, meta=None, name="es"):
    return cs.write_pair(cs.temp_dir(), name, pairs, meta=meta)


class LoadTests(unittest.TestCase):
    def test_without_a_sidecar_every_entry_is_new(self):
        loaded = jte.load_translation_file(_pair(PAIRS))
        self.assertEqual({e.status for e in loaded.entries}, {"New"})

    def test_sidecar_metadata_is_applied(self):
        loaded = jte.load_translation_file(_pair(PAIRS, {"Save": ("Review", "Jo", ISO)}))
        self.assertEqual(loaded.entries[0].status, "Review")

    def test_positions_count_from_one(self):
        loaded = jte.load_translation_file(_pair(PAIRS))
        self.assertEqual([e.position for e in loaded.entries], [1, 2, 3])

    def test_header_comes_from_the_sidecar(self):
        loaded = jte.load_translation_file(_pair(PAIRS, {}))
        self.assertEqual(loaded.header.version, "1.0.0")

    def test_damaged_sidecar_is_kept_aside(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        jte.load_translation_file(path)
        self.assertEqual(len(list(path.parent.glob("es.json.meta.corrupt-*"))), 1)

    def test_damaged_sidecar_gives_an_error_notice(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        self.assertEqual(jte.load_translation_file(path).notices[0][1], "error")

    def test_damaged_sidecar_stays_put_when_not_keeping(self):
        path = _pair(PAIRS)
        cs.write_exact(jte.meta_path_for(path), b"{")
        jte.load_translation_file(path, keep_damaged=False)
        self.assertTrue(jte.meta_path_for(path).exists())

    def test_unreadable_sidecar_blocks_its_overwrite(self):
        path = _pair(PAIRS)
        jte.meta_path_for(path).mkdir()   # reading a folder raises OSError
        self.assertTrue(jte.load_translation_file(path).meta_blocked)

    def test_round_trip_flag(self):
        cases = {"canonical": (cs.json_doc(PAIRS), True),
                 "no space after colons": (b'{\n "a":"A"\n}\n', False)}
        for label, (data, expected) in cases.items():
            with self.subTest(label):
                path = cs.write_exact(cs.temp_dir() / "es.json", data)
                self.assertEqual(jte.load_translation_file(path).round_trips, expected)

    def test_refused_file_raises(self):
        path = cs.write_exact(cs.temp_dir() / "es.json", b'{"a": 1}')
        with self.assertRaises(jte.JsonFormatError):
            jte.load_translation_file(path)


class SaveTests(unittest.TestCase):
    def _loaded(self, meta=None):
        path = _pair(PAIRS, meta)
        return path, jte.load_translation_file(path)

    def test_saved_language_file_is_intact(self):
        path, loaded = self._loaded()
        loaded.entries[0].text = "Guardar ya"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        cs.assert_json_intact(self, path, [k for k, _v in PAIRS])

    def test_saved_sidecar_holds_the_metadata(self):
        path, loaded = self._loaded()
        loaded.entries[0].status = "Complete"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        self.assertEqual(json.loads(jte.meta_path_for(path).read_bytes())["entries"]["Save"]["status"],
                         "Complete")

    def test_write_meta_false_leaves_the_sidecar_alone(self):
        path, loaded = self._loaded({"Save": ("Review", "Jo", ISO)})
        before = jte.meta_path_for(path).read_bytes()
        loaded.entries[0].status = "Complete"
        jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header, write_meta=False)
        self.assertEqual(jte.meta_path_for(path).read_bytes(), before)

    def test_sidecar_failure_raises_metadata_write_error(self):
        path, loaded = self._loaded()
        jte.meta_path_for(path).mkdir()
        with self.assertRaises(jte.MetadataWriteError):
            jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)

    def test_sidecar_failure_still_writes_the_language_file(self):
        path, loaded = self._loaded()
        jte.meta_path_for(path).mkdir()
        loaded.entries[0].text = "Guardar ya"
        try:
            jte.save_translation_file(path, loaded.entries, loaded.style, loaded.header)
        except jte.MetadataWriteError:
            pass
        self.assertIn("Guardar ya".encode("utf-8"), path.read_bytes())

    def test_failed_language_write_raises(self):
        path = cs.temp_dir() / "missing folder" / "es.json"
        with self.assertRaises(OSError):
            jte.save_translation_file(path, [cs.bare_entry("a")], jte.DEFAULT_JSON_STYLE,
                                      jte.FileHeader())

    def test_failed_language_write_writes_no_sidecar(self):
        path = cs.temp_dir() / "missing folder" / "es.json"
        try:
            jte.save_translation_file(path, [cs.bare_entry("a")], jte.DEFAULT_JSON_STYLE,
                                      jte.FileHeader())
        except OSError:
            pass
        self.assertFalse(jte.meta_path_for(path).exists())


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))

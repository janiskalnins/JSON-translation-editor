"""Core checks for the JSON language file: reading (refusals included), style detection and
writing back byte for byte. Later tasks add the sidecar and the load/save pair."""

import core_support as cs  # first: offscreen platform, scratch folder, sys.argv[0]

import json
import sys
import unittest

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


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
